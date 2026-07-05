"""Workflow execution: topological order, {{node.key}} templating, per-node IO logged to
workflow_run_steps (the debug view), stop-on-error. Runs are durable rows; execution is driven by
a Procrastinate job (registered in backend.core.queue) so a closed app resumes cleanly."""
from __future__ import annotations

import datetime
import json
import logging
import re
import time
import uuid
from collections import defaultdict, deque

from backend.automation.registry import get_node
from backend.core.database import get_sessionmaker
from backend.core.models import Workflow, WorkflowRun, WorkflowRunStep

log = logging.getLogger("orrery.automation")

_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9_]+))?\s*\}\}")
_MAX_IO_CHARS = 20_000
MAX_NODES = 40


def _substitute(value, outputs: dict):
    """Replace {{node_id.key}} / {{node_id}} in string config values with earlier outputs."""
    if isinstance(value, str):
        def repl(m):
            node_id, key = m.group(1), m.group(2)
            out = outputs.get(node_id)
            if out is None:
                return m.group(0)
            if key is None:
                return json.dumps(out) if isinstance(out, (dict, list)) else str(out)
            picked = out.get(key) if isinstance(out, dict) else None
            if isinstance(picked, (dict, list)):
                return json.dumps(picked)
            return "" if picked is None else str(picked)
        return _TEMPLATE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, outputs) for v in value]
    return value


def _topo_order(nodes: list[dict], edges: list[dict]) -> list[dict]:
    ids = {n["id"] for n in nodes}
    indeg: dict[str, int] = {nid: 0 for nid in ids}
    children: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in ids and t in ids and s != t:
            children[s].append(t)
            indeg[t] += 1
    queue = deque(nid for nid, d in indeg.items() if d == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for child in children[nid]:
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    if len(order) != len(ids):
        raise ValueError("The workflow has a cycle — connect nodes in one direction only.")
    by_id = {n["id"]: n for n in nodes}
    return [by_id[nid] for nid in order]


def _descendants(start: str, edges: list[dict]) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        children[e.get("source")].append(e.get("target"))
    seen: set[str] = set()
    stack = [start]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _clip(obj) -> str:
    try:
        return json.dumps(obj)[:_MAX_IO_CHARS]
    except (TypeError, ValueError):
        return str(obj)[:_MAX_IO_CHARS]


async def execute_run(run_id: str) -> None:
    """Execute one queued run to completion, recording every step. Never raises."""
    rid = uuid.UUID(run_id)
    async with get_sessionmaker()() as s:
        run = await s.get(WorkflowRun, rid)
        if run is None or run.status not in ("queued", "running"):
            return
        wf = await s.get(Workflow, run.workflow_id)
        if wf is None:
            run.status = "failed"
            run.error = "Workflow no longer exists."
            await s.commit()
            return
        run.status = "running"
        run.started_at = datetime.datetime.now(datetime.timezone.utc)
        await s.commit()
        spec_raw = wf.spec

    status, error = "done", None
    try:
        spec = json.loads(spec_raw or "{}")
        nodes = list(spec.get("nodes") or [])[:MAX_NODES]
        edges = list(spec.get("edges") or [])
        order = _topo_order(nodes, edges)
        outputs: dict[str, dict] = {}
        skipped: set[str] = set()
        for node_def in order:
            nid = node_def.get("id") or ""
            ntype = node_def.get("type") or ""
            if nid in skipped:
                await _record_step(rid, nid, ntype, "skipped", None, None, None, 0)
                continue
            node = get_node(ntype)
            if node is None:
                raise ValueError(f"Unknown node type '{ntype}' — was it removed?")
            raw_config = _substitute(node_def.get("config") or {}, outputs)
            config = node.config_model.model_validate(raw_config) if node.config_model else None
            started = time.monotonic()
            try:
                out = await node.execute(dict(outputs), config)
            except Exception as exc:  # noqa: BLE001 — a node failure fails the run, recorded
                await _record_step(rid, nid, ntype, "failed", raw_config, None, str(exc)[:2000],
                                   int((time.monotonic() - started) * 1000))
                raise ValueError(f"Node '{nid}' ({ntype}) failed: {str(exc)[:300]}")
            outputs[nid] = out if isinstance(out, dict) else {"value": out}
            await _record_step(rid, nid, ntype, "done", raw_config, outputs[nid], None,
                               int((time.monotonic() - started) * 1000))
            # a false if_branch prunes everything downstream of it
            if ntype == "if_branch" and not outputs[nid].get("matched"):
                skipped |= _descendants(nid, edges)
    except Exception as exc:  # noqa: BLE001
        status, error = "failed", str(exc)[:2000]

    async with get_sessionmaker()() as s:
        run = await s.get(WorkflowRun, rid)
        if run is not None:
            run.status = status
            run.error = error
            run.finished_at = datetime.datetime.now(datetime.timezone.utc)
            await s.commit()


async def _record_step(rid: uuid.UUID, node_id: str, node_type: str, status: str,
                       input_obj, output_obj, error: str | None, duration_ms: int) -> None:
    async with get_sessionmaker()() as s:
        s.add(WorkflowRunStep(
            run_id=rid, node_id=node_id[:80], node_type=node_type[:60], status=status,
            input=_clip(input_obj) if input_obj is not None else None,
            output=_clip(output_obj) if output_obj is not None else None,
            error=error, duration_ms=duration_ms,
        ))
        await s.commit()
