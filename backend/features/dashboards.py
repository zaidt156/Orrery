"""Dashboards: the AI is the designer, not the renderer (plan §3, architecture.md).

The user describes a dashboard in plain words, picks the model that builds it, and selects one or
more data connections. The model reads each connection's schema and returns a widget spec — per
widget: title, chart type, WHICH CONNECTION it queries (multi-source dashboards), and the SQL.
Orrery validates every query (sqlglot: exactly one SELECT, nothing data-modifying) and stores the
spec in Postgres. Opening or refreshing a dashboard re-runs the saved read-only SQL — no model call,
no token cost, and reuse can never introduce new unseen SQL (security.md §3). Every revision
snapshots the previous spec into history so a bad AI edit rolls back in one click.
"""
from __future__ import annotations

import json
import logging
import re
import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import Dashboard, DataConnection
from backend.features import data, team
from backend.providers import ai

log = logging.getLogger("orrery.dashboards")

WIDGET_TYPES = {"stat", "line", "bar", "pie", "table"}  # widget registry (conventions.md)
MAX_WIDGETS = 8
_ROW_CAPS = {"stat": 1, "table": 50}  # charts use the default cap
_DEFAULT_ROW_CAP = 200


# --- SQL validation (defense in depth — the READ ONLY transaction is the enforcement) ------------

def validate_widget_sql(sql: str) -> str | None:
    """Reject anything that isn't a single SELECT. Returns an error string or None when clean."""
    import sqlglot
    from sqlglot import exp

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as exc:  # noqa: BLE001
        return f"SQL didn't parse: {str(exc)[:160]}"
    if len(statements) != 1 or statements[0] is None:
        return "Exactly one SQL statement is allowed per widget."
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        return "Only SELECT queries are allowed."
    banned = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter,
              exp.TruncateTable, exp.Grant, exp.Command, exp.Set, exp.Copy)
    for node_type in banned:
        if stmt.find(node_type) is not None:
            return "Only read-only SELECT queries are allowed."
    return None


def _clean_widget(w: dict, allowed_connections: set[str], default_conn: str) -> tuple[dict | None, str | None]:
    """Normalize one model-proposed widget; returns (widget, None) or (None, why it was dropped)."""
    if not isinstance(w, dict):
        return None, "not an object"
    wtype = str(w.get("type", "")).strip().lower()
    if wtype not in WIDGET_TYPES:
        return None, f"unknown widget type {wtype!r}"
    sql = str(w.get("sql", "")).strip().rstrip(";")
    err = validate_widget_sql(sql)
    if err:
        return None, err
    conn = str(w.get("connection_id", "") or default_conn)
    if conn not in allowed_connections:
        conn = default_conn
    return {
        "title": str(w.get("title", "") or "Untitled")[:120],
        "type": wtype,
        "connection_id": conn,
        "sql": sql,
        "x": str(w.get("x", "") or "")[:80],   # column hints for the renderer
        "y": str(w.get("y", "") or "")[:80],
    }, None


# --- spec generation ------------------------------------------------------------------------------

_SPEC_PROMPT = """You are designing a data dashboard. Output ONLY a JSON object, no prose:
{{"name": "<short dashboard name>",
  "widgets": [{{"title": "...", "type": "stat|line|bar|pie|table",
               "connection_id": "<id of the connection this widget queries>",
               "sql": "<ONE read-only PostgreSQL SELECT>",
               "x": "<column for the x-axis / labels>", "y": "<numeric column for values>"}}]}}

Rules:
- 3 to {max_widgets} widgets. Prefer a stat row (1-3 single-number stats), then charts, then at most one table.
- Every query must be a single SELECT (no writes, no DDL). Aggregate in SQL (GROUP BY) so charts get
  tidy label/value rows; cap raw table listings with LIMIT 50; order time series by the time column.
- Use ONLY tables/columns from the schemas below, and set each widget's "connection_id" to the id of
  the connection whose schema you used for that query.
- "stat" widgets: the query returns one row; the first numeric column is shown big.
- "line"/"bar": x = label/time column, y = numeric column. "pie": x = label column, y = value column.

Available data connections and their schemas:
{schemas}

The user wants: {description}"""

_REVISE_PROMPT = """You are revising an existing dashboard spec. Output ONLY the complete updated JSON object
(same shape: name + widgets; keep unchanged widgets exactly as they are).

Current spec:
{spec}

Available data connections and their schemas:
{schemas}

Requested change: {instruction}

Apply the same rules: 1-{max_widgets} widgets, each with one read-only SELECT against only the listed
tables/columns, each widget's connection_id set to the connection whose schema it queries."""


async def _connection_names(ids: list[str]) -> dict[str, str]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(DataConnection))).scalars().all()
        return {str(r.id): r.name for r in rows if str(r.id) in set(ids)}


async def _schemas_block(connection_ids: list[str]) -> str:
    parts = []
    for cid in connection_ids:
        try:
            overview = await data.schema_overview(cid)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Couldn't read the schema of connection {cid[:8]}…: {str(exc)[:120]}")
        parts.append(f'connection_id "{cid}":\n{overview or "- (no tables found)"}')
    return "\n\n".join(parts)


async def _ask_model(model: str, prompt: str) -> dict:
    parts: list[str] = []
    async for delta in ai.stream_chat(model, [{"role": "user", "content": prompt}], None, "high"):
        if not isinstance(delta, ai.ReasoningDelta):
            parts.append(str(delta))
    text = "".join(parts)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("The model didn't return a dashboard spec. Try again or pick another model.")
    try:
        return json.loads(match.group(0))
    except (ValueError, TypeError):
        raise ValueError("The model returned malformed JSON. Try again or pick another model.")


async def _build_spec(model: str, connection_ids: list[str], prompt: str) -> tuple[str, dict, list[str]]:
    """Run the model, validate every widget, return (name, spec, dropped-reasons)."""
    raw = await _ask_model(model, prompt)
    allowed = set(connection_ids)
    default_conn = connection_ids[0]
    widgets, dropped = [], []
    for w in (raw.get("widgets") or [])[:MAX_WIDGETS]:
        cleaned, why = _clean_widget(w, allowed, default_conn)
        if cleaned:
            widgets.append(cleaned)
        else:
            dropped.append(why or "invalid")
    if not widgets:
        raise ValueError("None of the model's widgets passed SQL validation. Try again or rephrase.")
    name = str(raw.get("name", "") or "Dashboard")[:160]
    return name, {"connections": connection_ids, "widgets": widgets}, dropped


# --- CRUD + execution -----------------------------------------------------------------------------

def _dict(d: Dashboard, spec: dict | None = None) -> dict:
    spec = spec if spec is not None else _load_spec(d)
    history_len = 0
    try:
        history_len = len(json.loads(d.history)) if d.history else 0
    except (ValueError, TypeError):
        pass
    return {
        "id": str(d.id), "name": d.name, "description": d.description or "",
        "model": d.model, "connection_id": str(d.connection_id),
        "connections": spec.get("connections", [str(d.connection_id)]),
        "widgets": spec.get("widgets", []), "versions": history_len,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _load_spec(d: Dashboard) -> dict:
    try:
        spec = json.loads(d.spec)
        return spec if isinstance(spec, dict) else {}
    except (ValueError, TypeError):
        return {}


async def _get_owned(s, did: str) -> Dashboard | None:
    row = await s.get(Dashboard, uuid.UUID(did))
    if row is None:
        return None
    owner = await team.current_owner_id()
    if owner is not None and row.owner_id != owner:
        return None
    return row


async def list_dashboards() -> list[dict]:
    owner = await team.current_owner_id()
    async with get_sessionmaker()() as s:
        q = select(Dashboard).order_by(Dashboard.updated_at.desc())
        if owner is not None:
            q = q.where(Dashboard.owner_id == owner)
        rows = (await s.execute(q)).scalars().all()
        return [_dict(r) for r in rows]


async def create_dashboard(model: str, connection_ids: list[str], description: str) -> dict:
    connection_ids = [c for c in connection_ids if c]
    if not connection_ids:
        raise ValueError("Pick at least one data connection.")
    schemas = await _schemas_block(connection_ids)
    prompt = _SPEC_PROMPT.format(max_widgets=MAX_WIDGETS, schemas=schemas, description=description.strip())
    name, spec, dropped = await _build_spec(model, connection_ids, prompt)
    async with get_sessionmaker()() as s:
        row = Dashboard(
            name=name, description=description.strip()[:2000] or None,
            connection_id=uuid.UUID(connection_ids[0]), model=model,
            spec=json.dumps(spec), owner_id=await team.current_owner_id(),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        out = _dict(row, spec)
    if dropped:
        out["dropped"] = dropped
    return out


async def get_dashboard(did: str) -> dict | None:
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        return _dict(row) if row else None


async def run_dashboard(did: str) -> dict | None:
    """Re-run the saved read-only SQL for every widget (no model call). Per-widget errors are soft."""
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        spec = _load_spec(row)
        base = _dict(row, spec)
    conn_names = await _connection_names([str(w.get("connection_id")) for w in spec.get("widgets", [])])
    results = []
    for w in spec.get("widgets", []):
        item = dict(w)
        item["connection"] = conn_names.get(w.get("connection_id", ""), "database")
        # Belt and braces: the stored SQL was validated at save time, but re-check before running.
        err = validate_widget_sql(w.get("sql", ""))
        if err is None:
            try:
                cols, rows = await data.run_readonly_query(
                    w["connection_id"], w["sql"], row_cap=_ROW_CAPS.get(w["type"], _DEFAULT_ROW_CAP))
                item["columns"], item["rows"] = cols, rows
            except Exception as exc:  # noqa: BLE001 — one broken widget shouldn't kill the board
                item["error"] = str(exc)[:200]
        else:
            item["error"] = err
        results.append(item)
    base["widgets"] = results
    return base


async def revise_dashboard(did: str, model: str, instruction: str) -> dict | None:
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        spec = _load_spec(row)
    connection_ids = spec.get("connections") or [str(row.connection_id)]
    schemas = await _schemas_block(connection_ids)
    prompt = _REVISE_PROMPT.format(spec=json.dumps(spec, indent=1), schemas=schemas,
                                   instruction=instruction.strip(), max_widgets=MAX_WIDGETS)
    name, new_spec, dropped = await _build_spec(model, connection_ids, prompt)
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        try:
            history = json.loads(row.history) if row.history else []
        except (ValueError, TypeError):
            history = []
        history.append({"name": row.name, "model": row.model, "spec": _load_spec(row)})
        row.history = json.dumps(history[-10:])  # keep the last 10 versions
        row.name = name
        row.model = model  # the reviser becomes the current author
        row.spec = json.dumps(new_spec)
        await s.commit()
        await s.refresh(row)
        out = _dict(row, new_spec)
    if dropped:
        out["dropped"] = dropped
    return out


async def rollback_dashboard(did: str) -> dict | None:
    """Restore the previous spec (one click undo for a bad AI edit)."""
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        try:
            history = json.loads(row.history) if row.history else []
        except (ValueError, TypeError):
            history = []
        if not history:
            raise ValueError("No earlier version to roll back to.")
        prev = history.pop()
        row.history = json.dumps(history)
        row.name = prev.get("name", row.name)
        row.model = prev.get("model", row.model)
        row.spec = json.dumps(prev.get("spec", {}))
        await s.commit()
        await s.refresh(row)
        return _dict(row)


async def delete_dashboard(did: str) -> bool:
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
        return True
