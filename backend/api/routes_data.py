"""/data API routes (split from the api.py monolith; same behavior)."""
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

@router.get("/connections")
async def connections_list() -> dict:
    return {"connections": await data.list_connections()}

@router.post("/connections")
async def connection_add(body: NewConnection) -> dict:
    try:
        return await data.add_connection(body.name, body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/connections/{cid}")
async def connection_delete(cid: str) -> dict:
    if not await data.delete_connection(cid):
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"deleted": True}

@router.get("/connections/{cid}/tables")
async def connection_tables(cid: str) -> dict:
    try:
        return {"tables": await data.list_tables(cid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=secrets.redact_url(str(e))[:160])

@router.get("/connections/{cid}/browse")
async def connection_browse(cid: str, schema: str, table: str, limit: int = 100) -> dict:
    try:
        return await data.browse_table(cid, schema, table, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=secrets.redact_url(str(e))[:160])

# --- imported datasets (CSV/Excel uploads + REST APIs, materialized as queryable tables) ---
@router.get("/datasets")
async def datasets_list() -> dict:
    return {"datasets": await datasets.list_datasets()}

@router.post("/datasets/file")
async def dataset_from_file(body: DatasetFileBody) -> dict:
    try:
        return await datasets.create_from_file(body.name, body.filename, body.content, body.workspace_id or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)[:200]}")

@router.post("/datasets/api")
async def dataset_from_api(body: DatasetApiBody) -> dict:
    try:
        return await datasets.create_from_api(body.name, body.url, body.headers or None, body.workspace_id or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"API import failed: {str(e)[:200]}")

@router.post("/datasets/mongo")
async def dataset_from_mongo(body: DatasetMongoBody) -> dict:
    try:
        return await datasets.create_from_mongo(body.name, body.uri, body.collection, body.workspace_id or None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"MongoDB import failed: {secrets.redact_url(str(e))[:200]}")


@router.get("/workspaces")
async def workspaces_list() -> dict:
    return {"workspaces": await datasets.list_workspaces()}

@router.post("/workspaces")
async def workspace_create(body: WorkspaceBody) -> dict:
    try:
        return await datasets.create_workspace(body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/connections/{cid}/schema-map")
async def connection_schema_map(cid: str) -> dict:
    """{table: [columns]} — feeds the data-model join editor's dropdowns."""
    try:
        m = await datamodels._schema_map(cid)  # noqa: SLF001 — shared metadata helper
        return {"tables": {t: list(cols.keys()) for t, cols in m.items()}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=secrets.redact_url(str(e))[:160])

# --- data models: user-connected tables (joins), validated against the live schema ---
@router.get("/datamodels")
async def datamodels_list(connection_id: str = "") -> dict:
    return {"models": await datamodels.list_models(connection_id or None)}

@router.post("/datamodels")
async def datamodel_create(body: DataModelBody) -> dict:
    try:
        return await datamodels.create_model(body.connection_id, body.name, body.spec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Model failed: {secrets.redact_url(str(e))[:200]}")

@router.delete("/datamodels/{mid}")
async def datamodel_delete(mid: str) -> dict:
    if not await datamodels.delete_model(mid):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"deleted": True}

@router.post("/datasets/{did}/refresh")
async def dataset_refresh(did: str) -> dict:
    try:
        return await datasets.refresh_dataset(did)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Refresh failed: {str(e)[:200]}")

@router.delete("/datasets/{did}")
async def dataset_delete(did: str) -> dict:
    if not await datasets.delete_dataset(did):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"deleted": True}

# --- dashboards (AI-designed specs; refresh re-runs saved read-only SQL, no model call) ---
