"""/collections API routes (split from the api.py monolith; same behavior)."""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from backend.api.deps import _require_conversation_access, _sse, _sse_run
from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.core import appconfig, database
from backend.core.config import settings
from backend.features import admin, app_updates, artifacts, chat, dashboards, data, datamodels, datasets, evaluate, exports, feedback, filepreview, local_models, mcp, projects, rag, route_telemetry, skills, team, usage
from backend.features import files as file_library
from backend.providers import accounts, ai, catalog
from backend.security import secrets

router = APIRouter()

@router.get("/collections")
async def collections_list() -> dict:
    return {"collections": await rag.list_collections()}

@router.post("/collections")
async def collection_create(body: NewCollection) -> dict:
    return await rag.create_collection(body.name)

@router.delete("/collections/{cid}")
async def collection_delete(cid: str) -> dict:
    if not await rag.delete_collection(cid):
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"deleted": True}

# Bigger drops index in the durable queue so the request (and the whole app) never freezes.
_ASYNC_INGEST_FILES = 4
_ASYNC_INGEST_CHARS = 1_500_000


def _should_queue_ingest(files: list[dict]) -> bool:
    total = sum(len(str(f.get("content") or "")) for f in files)
    return len(files) > _ASYNC_INGEST_FILES or total > _ASYNC_INGEST_CHARS


@router.post("/collections/{cid}/documents")
async def collection_upload(cid: str, body: UploadDocs) -> dict:
    files = [a.model_dump() for a in body.files]
    try:
        if _should_queue_ingest(files):
            return await rag.enqueue_ingest(cid, files)
        return {"added": await rag.add_documents(cid, files)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)[:160])


@router.get("/collections/{cid}/ingest-status")
async def collection_ingest_status(cid: str) -> dict:
    try:
        return {"progress": rag.ingest_progress(cid)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:160])

@router.get("/collections/{cid}/search")
async def collection_search(cid: str, q: str, k: int = 5) -> dict:
    return {"results": await rag.search(cid, q, k)}

# --- ontologies (reusable knowledge bases; "connected" ones are used as context in every chat) ---
@router.get("/ontologies")
async def ontologies_list() -> dict:
    return {"ontologies": await rag.list_collections(kind="ontology")}

@router.post("/ontologies")
async def ontology_create(body: OntologyBody) -> dict:
    return await rag.create_collection(body.name or "Ontology", kind="ontology", description=body.description)

@router.patch("/ontologies/{cid}")
async def ontology_update(cid: str, body: OntologyUpdate) -> dict:
    if body.connected is not None:
        await rag.set_connected(cid, body.connected)
    if body.name is not None or body.description is not None:
        await rag.update_collection(cid, name=body.name, description=body.description)
    return {"updated": True}

@router.delete("/ontologies/{cid}")
async def ontology_delete(cid: str) -> dict:
    if not await rag.delete_collection(cid):
        raise HTTPException(status_code=404, detail="Ontology not found")
    return {"deleted": True}

@router.get("/ontologies/{cid}/files")
async def ontology_files(cid: str) -> dict:
    return {"files": await rag.documents(cid)}

@router.post("/ontologies/{cid}/files")
async def ontology_add_files(cid: str, body: UploadDocs) -> dict:
    files = [a.model_dump() for a in body.files]
    try:
        if _should_queue_ingest(files):
            queued = await rag.enqueue_ingest(cid, files)
            return {**queued, "added": 0, "files": await rag.documents(cid)}
        added = await rag.add_documents(cid, files)
        return {"added": added, "files": await rag.documents(cid)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)[:160])

@router.delete("/ontologies/{cid}/files")
async def ontology_delete_file(cid: str, source: str) -> dict:
    return {"removed": await rag.delete_source(cid, source)}

# --- user-authored skills (created/edited/uploaded in the UI; merged with built-in skills) ---
