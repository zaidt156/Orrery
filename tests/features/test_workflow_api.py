"""The Automations API surface.

The engine and CRUD layer already existed; these cover the routes that were missing, and the two
behaviours that are easy to get wrong at a route boundary: a junk id must read as "not found"
rather than crash, and a spec validation failure must reach the client as a 400 with its reason.
"""
import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app

# psycopg async needs the SelectorEventLoop on Windows (same as the app itself)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Marked at module scope: these exercise real persistence, so they need the PostgreSQL that
# `docker compose up -d` provides. The cross-platform CI job runs `-m "not db"`; the Linux
# job provides a pgvector service and requires them.
pytestmark = pytest.mark.db

TOKEN = "secret-token"


@pytest.fixture
def client():
    return TestClient(create_app(TOKEN))


@pytest.fixture
def auth():
    return {"X-Orrery-Token": TOKEN}


@pytest.fixture(autouse=True)
def _migrated():
    from backend.core.migrations import run_migrations
    asyncio.run(run_migrations())


def _create(client, auth, name="Test workflow"):
    r = client.post("/api/workflows", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_every_workflow_route_requires_the_token(client):
    assert client.get("/api/workflows").status_code == 401
    assert client.get("/api/workflow-nodes").status_code == 401
    assert client.post("/api/workflows", json={"name": "x"}).status_code == 401


def test_node_catalog_comes_from_the_registry(client, auth):
    body = client.get("/api/workflow-nodes", headers=auth).json()

    keys = {n["key"] for n in body["nodes"]}
    assert "llm_prompt" in keys, "the catalog should be the registered nodes, not a fixed list"
    for node in body["nodes"]:
        assert node["label"] and node["category"]
        assert isinstance(node["schema"], dict)   # the canvas builds its settings form from this


def test_create_list_get_and_delete(client, auth):
    created = _create(client, auth, "Nightly report")
    wid = created["id"]
    try:
        assert created["name"] == "Nightly report"

        listed = client.get("/api/workflows", headers=auth).json()["workflows"]
        assert wid in [w["id"] for w in listed]

        fetched = client.get(f"/api/workflows/{wid}", headers=auth)
        assert fetched.status_code == 200
        assert fetched.json()["id"] == wid
    finally:
        assert client.delete(f"/api/workflows/{wid}", headers=auth).status_code == 204

    assert client.get(f"/api/workflows/{wid}", headers=auth).status_code == 404


def test_saving_a_spec_validates_node_types(client, auth):
    created = _create(client, auth)
    wid = created["id"]
    try:
        good = client.patch(f"/api/workflows/{wid}",
                            json={"spec": {"nodes": [{"id": "a", "type": "llm_prompt"}], "edges": []}},
                            headers=auth)
        assert good.status_code == 200
        assert good.json()["spec"]["nodes"][0]["id"] == "a"

        bad = client.patch(f"/api/workflows/{wid}",
                           json={"spec": {"nodes": [{"id": "a", "type": "not_a_real_node"}], "edges": []}},
                           headers=auth)
        assert bad.status_code == 400
        assert "not_a_real_node" in bad.json()["detail"]
    finally:
        client.delete(f"/api/workflows/{wid}", headers=auth)


def test_duplicate_node_ids_are_refused(client, auth):
    created = _create(client, auth)
    wid = created["id"]
    try:
        r = client.patch(f"/api/workflows/{wid}", json={"spec": {
            "nodes": [{"id": "a", "type": "llm_prompt"}, {"id": "a", "type": "llm_prompt"}],
            "edges": [],
        }}, headers=auth)
        assert r.status_code == 400
        assert "unique id" in r.json()["detail"]
    finally:
        client.delete(f"/api/workflows/{wid}", headers=auth)


def test_a_junk_id_is_not_found_rather_than_a_crash(client, auth):
    assert client.get("/api/workflows/not-a-uuid", headers=auth).status_code == 404
    assert client.patch("/api/workflows/not-a-uuid", json={"name": "x"}, headers=auth).status_code == 404
    assert client.delete("/api/workflows/not-a-uuid", headers=auth).status_code == 404
    assert client.post("/api/workflows/not-a-uuid/runs", headers=auth).status_code == 404
    assert client.get("/api/workflows/not-a-uuid/runs", headers=auth).json() == {"runs": []}


def test_a_run_records_durable_steps(client, auth):
    """The run-debug view needs per-node input/output/error, not just a status."""
    created = _create(client, auth)
    wid = created["id"]
    try:
        client.patch(f"/api/workflows/{wid}", json={"spec": {
            "nodes": [{"id": "wait", "type": "delay", "config": {"seconds": 0}}], "edges": [],
        }}, headers=auth)

        started = client.post(f"/api/workflows/{wid}/runs", headers=auth)
        assert started.status_code == 201
        # `run_id`, matching how starting an agent run reports itself
        run_id = started.json()["run_id"]

        runs = client.get(f"/api/workflows/{wid}/runs", headers=auth).json()["runs"]
        assert run_id in [r["id"] for r in runs]

        detail = client.get(f"/api/workflows/{wid}/runs/{run_id}", headers=auth)
        assert detail.status_code == 200
        assert "steps" in detail.json()
    finally:
        client.delete(f"/api/workflows/{wid}", headers=auth)


def test_run_detail_for_an_unknown_run_is_404(client, auth):
    created = _create(client, auth)
    wid = created["id"]
    try:
        import uuid as _uuid
        r = client.get(f"/api/workflows/{wid}/runs/{_uuid.uuid4()}", headers=auth)
        assert r.status_code == 404
    finally:
        client.delete(f"/api/workflows/{wid}", headers=auth)


def test_a_workflow_run_leaves_tool_evidence(client, auth):
    """ADR-005 slice 1: the automation surface records its tool calls like the others.

    Workflow nodes execute through a fixed signature and cannot be handed an identity, so the engine
    scopes one around each node. This checks that the scoping actually reaches the registry.
    """
    import asyncio as _asyncio
    import uuid as _uuid

    from sqlalchemy import select as _select

    from backend.core.database import get_sessionmaker
    from backend.core.models import ToolCallContext

    created = _create(client, auth, "Evidence workflow")
    wid = created["id"]
    try:
        # web_search is a registered node whose body calls the shared registry
        saved = client.patch(f"/api/workflows/{wid}", json={"spec": {
            "nodes": [{"id": "look", "type": "web_search", "config": {"query": "orrery"}}],
            "edges": [],
        }}, headers=auth)
        assert saved.status_code == 200

        started = client.post(f"/api/workflows/{wid}/runs", headers=auth)
        assert started.status_code == 201
        run_id = _uuid.UUID(started.json()["run_id"])

        async def _read():
            async with get_sessionmaker()() as s:
                return (await s.execute(_select(ToolCallContext).where(
                    ToolCallContext.workflow_run_id == run_id
                ))).scalars().all()

        contexts = _asyncio.run(_read())

        assert contexts, "the workflow's tool call left no durable record"
        assert contexts[0].surface == "automation"
        assert contexts[0].tool_key == "web_search"
        assert contexts[0].workflow_run_id == run_id
    finally:
        client.delete(f"/api/workflows/{wid}", headers=auth)
