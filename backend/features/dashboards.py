"""Dashboards: the AI is the designer, not the renderer (PLAN.md and ARCHITECTURE.md).

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
from backend.features import data, datamodels, events as stream_events, skills, team
from backend.providers import ai

log = logging.getLogger("orrery.dashboards")

WIDGET_TYPES = {"stat", "line", "bar", "pie", "table"}  # widget registry (conventions.md)
MAX_WIDGETS = 8
_ROW_CAPS = {"stat": 1, "table": 50}  # charts use the default cap
_DEFAULT_ROW_CAP = 200


# --- SQL validation (defense in depth — the READ ONLY transaction is the enforcement) ------------

def _parse_sql_statements(sql: str) -> list:
    """Parse with the Postgres dialect, degrading to the default dialect if that dialect module is
    unavailable. sqlglot loads dialects dynamically by name, so a packaged (PyInstaller) build that
    did not bundle `sqlglot.dialects.postgres` would otherwise turn every widget into a parse error
    ("No module named 'sqlglot.dialects.postgres'"). The default dialect parses standard SQL fine,
    and the READ ONLY transaction — not this parser — is the real enforcement."""
    import sqlglot

    try:
        return sqlglot.parse(sql, read="postgres")
    except ModuleNotFoundError:
        return sqlglot.parse(sql)


def validate_widget_sql(sql: str) -> str | None:
    """Reject anything that isn't a single SELECT. Returns an error string or None when clean."""
    from sqlglot import exp

    try:
        statements = _parse_sql_statements(sql)
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


_TRANSFORM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
MAX_TRANSFORMS = 6


def _clean_transform(t: dict, allowed_connections: set[str], default_conn: str) -> tuple[dict | None, str | None]:
    """Normalize one model-proposed transform (a named, validated SELECT widgets can build on)."""
    if not isinstance(t, dict):
        return None, "transform is not an object"
    name = str(t.get("name", "")).strip()
    if not _TRANSFORM_NAME.match(name):
        return None, f"transform name {name!r} is not a valid identifier"
    sql = str(t.get("sql", "")).strip().rstrip(";")
    err = validate_widget_sql(sql)
    if err:
        return None, f"transform {name}: {err}"
    conn = str(t.get("connection_id", "") or default_conn)
    if conn not in allowed_connections:
        conn = default_conn
    return {
        "name": name, "connection_id": conn, "sql": sql,
        "description": str(t.get("description", "") or "")[:200],
    }, None


def effective_widget_sql(widget: dict, transforms: list[dict]) -> str:
    """Widget SQL with any referenced same-connection transforms attached as CTEs (BI prep layer)."""
    same = [t for t in transforms if t.get("connection_id") == widget.get("connection_id")]
    if not same:
        return widget["sql"]
    searched = widget["sql"]
    names: set[str] = set()
    changed = True
    while changed:  # include transforms referenced by the widget or by already-included transforms
        changed = False
        for t in same:
            if t["name"] not in names and re.search(rf"\b{re.escape(t['name'])}\b", searched):
                names.add(t["name"])
                searched += "\n" + t["sql"]
                changed = True
    if not names:
        return widget["sql"]
    ordered = [t for t in same if t["name"] in names]  # spec order: later CTEs may use earlier ones
    ctes = ", ".join(f"{t['name']} AS ({t['sql']})" for t in ordered)
    body = widget["sql"].strip()
    if re.match(r"^\s*with\b", body, re.IGNORECASE):
        # the widget brings its own CTEs — merge into one WITH list
        own_ctes = re.sub(r"^\s*with\b", "", body, count=1, flags=re.IGNORECASE).strip()
        combined = f"WITH {ctes}, {own_ctes}"
    else:
        combined = f"WITH {ctes} {body}"
    return combined if validate_widget_sql(combined) is None else widget["sql"]


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

_SPEC_PROMPT = """You are designing a data dashboard, BI-style. Output ONLY a JSON object, no prose:
{{"name": "<short dashboard name>",
  "transforms": [{{"name": "<snake_case identifier>", "connection_id": "<connection id>",
                  "sql": "<ONE read-only SELECT that cleans/joins/reshapes data>",
                  "description": "<what this prepared dataset is>"}}],
  "widgets": [{{"title": "...", "type": "stat|line|bar|pie|table",
               "connection_id": "<id of the connection this widget queries>",
               "sql": "<ONE read-only PostgreSQL SELECT>",
               "x": "<column for the x-axis / labels>", "y": "<numeric column for values>"}}]}}

Rules:
- 3 to {max_widgets} widgets. Prefer a stat row (1-3 single-number stats), then charts, then at most one table.
- TRANSFORMS (optional, up to {max_transforms}): named prepared datasets — cleaning, joins, unions,
  derived columns. A widget on the SAME connection can then reference a transform by name as if it
  were a table (it is attached as a CTE at run time). Use them to avoid repeating messy joins in
  every widget. Do not redefine a transform name inside a widget's own WITH clause.
- Every query (transform and widget) must be a single SELECT (no writes, no DDL). Aggregate in SQL
  (GROUP BY) so charts get tidy label/value rows; cap raw table listings with LIMIT 50; order time
  series by the time column.
- Use ONLY tables/columns from the schemas below, and set each item's "connection_id" to the id of
  the connection whose schema it uses. Transforms cannot join across different connections.
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

Apply the same rules: 1-{max_widgets} widgets (and up to {max_transforms} named transforms widgets can
reference on the same connection), each with one read-only SELECT against only the listed
tables/columns, each item's connection_id set to the connection whose schema it uses."""


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
    block = "\n\n".join(parts)
    # user-defined relationship models are pre-joined datasets the designer can query by name
    models = await datamodels.models_as_transforms(connection_ids)
    return block + datamodels.describe_models(models)


def _parse_spec_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("The model didn't return a dashboard spec. Try again or pick another model.")
    try:
        return json.loads(match.group(0))
    except (ValueError, TypeError):
        raise ValueError("The model returned malformed JSON. Try again or pick another model.")


async def _ask_model(model: str, prompt: str) -> dict:
    parts: list[str] = []
    async for delta in ai.stream_chat(model, [{"role": "user", "content": prompt}], None, "high"):
        if not isinstance(delta, ai.ReasoningDelta):
            parts.append(str(delta))
    return _parse_spec_json("".join(parts))


def _spec_from_raw(raw: dict, connection_ids: list[str], model_ctes: list[dict]) -> tuple[str, dict, list[str]]:
    """Validate a model-produced spec into (name, spec, dropped-reasons). Shared by the plain and
    streaming build paths; `model_ctes` are the user's data-model joins (fetched once by the caller)."""
    allowed = set(connection_ids)
    default_conn = connection_ids[0]
    reserved = {m["name"] for m in model_ctes}
    transforms, widgets, dropped = [], [], []
    seen_names: set[str] = set(reserved)  # spec transforms may not shadow data-model names
    for t in (raw.get("transforms") or [])[:MAX_TRANSFORMS]:
        cleaned, why = _clean_transform(t, allowed, default_conn)
        if cleaned and cleaned["name"] not in seen_names:
            transforms.append(cleaned)
            seen_names.add(cleaned["name"])
        elif why:
            dropped.append(why)
    for w in (raw.get("widgets") or [])[:MAX_WIDGETS]:
        cleaned, why = _clean_widget(w, allowed, default_conn)
        if cleaned is None:
            dropped.append(why or "invalid")
            continue
        # the widget must also be valid WITH its transforms + data models attached (what actually runs)
        err = validate_widget_sql(effective_widget_sql(cleaned, transforms + model_ctes))
        if err:
            dropped.append(f"{cleaned['title']}: {err}")
            continue
        widgets.append(cleaned)
    if not widgets:
        raise ValueError("None of the model's widgets passed SQL validation. Try again or rephrase.")
    name = str(raw.get("name", "") or "Dashboard")[:160]
    return name, {"connections": connection_ids, "transforms": transforms, "widgets": widgets}, dropped


async def _build_spec(model: str, connection_ids: list[str], prompt: str) -> tuple[str, dict, list[str]]:
    """Run the model, validate every transform + widget, return (name, spec, dropped-reasons)."""
    raw = await _ask_model(model, prompt)
    model_ctes = await datamodels.models_as_transforms(connection_ids)
    return _spec_from_raw(raw, connection_ids, model_ctes)


async def _stream_spec(model: str, connection_ids: list[str], prompt: str):
    """Design a spec while streaming progress to the UI. Yields stream_events (status/reasoning),
    then a final {"_spec": (name, spec, dropped)} sentinel. The model's own reasoning is forwarded
    so the build is no longer an opaque 'working…' wait."""
    yield stream_events.status(f"Designing the dashboard with {model.split('/')[-1]}…")
    parts: list[str] = []
    async for delta in ai.stream_chat(model, [{"role": "user", "content": prompt}], None, "high"):
        if isinstance(delta, ai.ReasoningDelta):
            yield stream_events.reasoning_delta(str(delta))
        else:
            parts.append(str(delta))
    yield stream_events.status("Validating the queries against your schema…")
    raw = _parse_spec_json("".join(parts))
    model_ctes = await datamodels.models_as_transforms(connection_ids)
    yield {"_spec": _spec_from_raw(raw, connection_ids, model_ctes)}


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
        "transforms": spec.get("transforms", []),
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


async def _create_prompt(connection_ids: list[str], description: str) -> str:
    schemas = await _schemas_block(connection_ids)
    prompt = _SPEC_PROMPT.format(max_widgets=MAX_WIDGETS, max_transforms=MAX_TRANSFORMS,
                                 schemas=schemas, description=description.strip())
    guidance = skills.skills_prompt(f"dashboard visualization chart {description}")
    # the dashboard-design skill: chart choice, aggregation, labeling rules
    return f"{guidance}\n\n{prompt}" if guidance else prompt


async def _persist_new_dashboard(name: str, spec: dict, description: str, model: str,
                                 connection_ids: list[str], dropped: list[str]) -> dict:
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


def _clean_connection_ids(connection_ids: list[str]) -> list[str]:
    ids = [c for c in connection_ids if c]
    if not ids:
        raise ValueError("Pick at least one data connection.")
    return ids


async def create_dashboard(model: str, connection_ids: list[str], description: str) -> dict:
    connection_ids = _clean_connection_ids(connection_ids)
    prompt = await _create_prompt(connection_ids, description)
    name, spec, dropped = await _build_spec(model, connection_ids, prompt)
    return await _persist_new_dashboard(name, spec, description, model, connection_ids, dropped)


async def create_dashboard_stream(model: str, connection_ids: list[str], description: str):
    """Streaming build: yields status + the model's reasoning, then a `result` event carrying the
    finished dashboard, then `done`. Errors surface as an `error` event, never an unhandled 500."""
    try:
        connection_ids = _clean_connection_ids(connection_ids)
        yield stream_events.status("Reading your data schema…")
        prompt = await _create_prompt(connection_ids, description)
        result = None
        async for ev in _stream_spec(model, connection_ids, prompt):
            if isinstance(ev, dict) and "_spec" in ev:
                result = ev["_spec"]
            else:
                yield ev
        name, spec, dropped = result
        out = await _persist_new_dashboard(name, spec, description, model, connection_ids, dropped)
        yield stream_events.result({"dashboard": out})
        yield stream_events.done()
    except Exception as exc:  # noqa: BLE001 — surface a clean error frame, not a broken stream
        yield stream_events.error(str(exc)[:300])
        yield stream_events.done()


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
    # widgets can reference spec transforms AND user-defined data models (joined tables) as CTEs
    model_ctes = await datamodels.models_as_transforms(spec.get("connections", []))
    transforms = list(spec.get("transforms", [])) + model_ctes
    results = []
    for w in spec.get("widgets", []):
        item = dict(w)
        item["connection"] = conn_names.get(w.get("connection_id", ""), "database")
        # What actually runs: the widget SQL with its referenced transforms attached as CTEs.
        run_sql = effective_widget_sql(w, transforms)
        # Belt and braces: the stored SQL was validated at save time, but re-check before running.
        err = validate_widget_sql(run_sql)
        if err is None:
            try:
                cols, rows = await data.run_readonly_query(
                    w["connection_id"], run_sql, row_cap=_ROW_CAPS.get(w["type"], _DEFAULT_ROW_CAP))
                item["columns"], item["rows"] = cols, rows
            except Exception as exc:  # noqa: BLE001 — one broken widget shouldn't kill the board
                item["error"] = str(exc)[:200]
        else:
            item["error"] = err
        results.append(item)
    base["widgets"] = results
    return base


async def _revise_prompt(did: str, instruction: str) -> tuple[list[str], str] | None:
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        spec = _load_spec(row)
        connection_ids = spec.get("connections") or [str(row.connection_id)]
    schemas = await _schemas_block(connection_ids)
    prompt = _REVISE_PROMPT.format(spec=json.dumps(spec, indent=1), schemas=schemas,
                                   instruction=instruction.strip(), max_widgets=MAX_WIDGETS,
                                   max_transforms=MAX_TRANSFORMS)
    return connection_ids, prompt


async def _persist_revision(did: str, name: str, new_spec: dict, model: str, dropped: list[str]) -> dict | None:
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


async def revise_dashboard(did: str, model: str, instruction: str) -> dict | None:
    prep = await _revise_prompt(did, instruction)
    if prep is None:
        return None
    connection_ids, prompt = prep
    name, new_spec, dropped = await _build_spec(model, connection_ids, prompt)
    out = await _persist_revision(did, name, new_spec, model, dropped)
    return out


async def revise_dashboard_stream(did: str, model: str, instruction: str):
    """Streaming revise — same event contract as create_dashboard_stream."""
    try:
        yield stream_events.status("Reviewing the current dashboard…")
        prep = await _revise_prompt(did, instruction)
        if prep is None:
            yield stream_events.error("Dashboard not found.")
            yield stream_events.done()
            return
        connection_ids, prompt = prep
        result = None
        async for ev in _stream_spec(model, connection_ids, prompt):
            if isinstance(ev, dict) and "_spec" in ev:
                result = ev["_spec"]
            else:
                yield ev
        name, new_spec, dropped = result
        out = await _persist_revision(did, name, new_spec, model, dropped)
        if out is None:
            yield stream_events.error("Dashboard not found.")
        else:
            yield stream_events.result({"dashboard": out})
        yield stream_events.done()
    except Exception as exc:  # noqa: BLE001
        yield stream_events.error(str(exc)[:300])
        yield stream_events.done()


async def set_transforms(did: str, transforms: list[dict]) -> dict | None:
    """Manual transform editing: validate each entry, snapshot the old spec, save."""
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        spec = _load_spec(row)
        allowed = set(spec.get("connections") or [str(row.connection_id)])
        default_conn = next(iter(allowed))
        cleaned_list, errors = [], []
        seen: set[str] = set()
        for t in transforms[:MAX_TRANSFORMS]:
            cleaned, why = _clean_transform(t, allowed, default_conn)
            if cleaned and cleaned["name"] not in seen:
                cleaned_list.append(cleaned)
                seen.add(cleaned["name"])
            elif why:
                errors.append(why)
        if errors:
            raise ValueError("; ".join(errors)[:300])
        try:
            history = json.loads(row.history) if row.history else []
        except (ValueError, TypeError):
            history = []
        history.append({"name": row.name, "model": row.model, "spec": spec})
        row.history = json.dumps(history[-10:])
        spec["transforms"] = cleaned_list
        row.spec = json.dumps(spec)
        await s.commit()
        await s.refresh(row)
        return _dict(row, spec)


async def set_layout(did: str, order: list[int]) -> dict | None:
    """Persist the user's drag-rearranged widget order (AI designs; the user arranges)."""
    async with get_sessionmaker()() as s:
        row = await _get_owned(s, did)
        if row is None:
            return None
        spec = _load_spec(row)
        widgets = spec.get("widgets", [])
        if sorted(order) != list(range(len(widgets))):
            raise ValueError("Layout order must be a permutation of the current widgets.")
        spec["widgets"] = [widgets[i] for i in order]
        row.spec = json.dumps(spec)
        await s.commit()
        await s.refresh(row)
        return _dict(row, spec)


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
