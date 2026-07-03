"""Data models: user-defined relationships between tables (BI-style "connect your tables").

A model names a base table and joins related tables on key columns — like Power BI's model view.
Orrery validates every table/column against the connection's real schema (allow-list, then dialect
quoting — security.md §2), builds one SELECT with the joins, and exposes the model everywhere:
- the dashboard-designing AI sees it as a pre-joined dataset it can query by name;
- at run time the model is attached as a CTE (same mechanism as transforms), so nothing is ever
  written to the user's database and read-only connections work unchanged.
Columns are aliased table_column to avoid collisions across joined tables."""
from __future__ import annotations

import json
import logging
import re
import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import DataModel
from backend.features import data

log = logging.getLogger("orrery.datamodels")

MAX_JOINS = 8
_NAME = re.compile(r"[^a-z0-9_]+")
_JOIN_TYPES = {"left": "LEFT JOIN", "inner": "JOIN", "full": "FULL JOIN"}


def _slug(name: str) -> str:
    s = _NAME.sub("_", (name or "").strip().lower()).strip("_") or "model"
    if s[0].isdigit():
        s = f"m_{s}"
    return ("dm_" + s)[:60]


async def _schema_map(cid: str) -> dict[str, dict[str, str]]:
    """{table: {column: type}} for the connection, using each dialect's real metadata."""
    rows = await data._columns_rows(cid, 40 * 24 * 2)  # noqa: SLF001 — sibling feature module
    engine = data._engine(cid)  # noqa: SLF001
    default_schema = (await data.dataset_schema(cid)) or {"sqlite": "main", "mysql": None, "mariadb": None, "mssql": "dbo"}.get(engine.dialect.name, "public")
    out: dict[str, dict[str, str]] = {}
    for schema, table, col, dtype in rows:
        key = table if (default_schema is None or schema == default_schema) else f"{schema}.{table}"
        out.setdefault(key, {})[col] = dtype
    return out


def _split_ref(ref: str) -> tuple[str, str]:
    """'orders.customer_id' -> (table, column); table may itself be schema-qualified."""
    parts = (ref or "").rsplit(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Use table.column references (got {ref!r}).")
    return parts[0], parts[1]


def _quote_table(q, table: str) -> str:
    return ".".join(q(p) for p in table.split("."))


def build_model_sql(cid_schema: dict[str, dict[str, str]], spec: dict, quote) -> str:
    """Deterministic SELECT from a validated join spec. Raises ValueError on anything unknown."""
    base = str(spec.get("base", "")).strip()
    if base not in cid_schema:
        raise ValueError(f"Unknown base table {base!r}.")
    joins = list(spec.get("joins") or [])[:MAX_JOINS]
    tables = [base]
    clauses = []
    for j in joins:
        table = str(j.get("table", "")).strip()
        lt, lc = _split_ref(str(j.get("left", "")))
        rt, rc = _split_ref(str(j.get("right", "")))
        jt = _JOIN_TYPES.get(str(j.get("type", "left")).lower(), "LEFT JOIN")
        if table not in cid_schema:
            raise ValueError(f"Unknown joined table {table!r}.")
        for t, c in ((lt, lc), (rt, rc)):
            if t not in cid_schema or c not in cid_schema[t]:
                raise ValueError(f"Unknown column {t}.{c}.")
        if lt not in tables and lt != table:
            raise ValueError(f"Join key {lt}.{lc} must reference an already-joined table.")
        tables.append(table)
        clauses.append(
            f"{jt} {_quote_table(quote, table)} ON "
            f"{_quote_table(quote, lt)}.{quote(lc)} = {_quote_table(quote, rt)}.{quote(rc)}"
        )
    # alias columns table_column to keep them unambiguous after the joins ("ds_" import prefix dropped)
    selects = []
    for t in tables:
        t_alias = t.split(".")[-1]
        if t_alias.startswith("ds_"):
            t_alias = t_alias[3:]
        for c in list(cid_schema[t].keys())[:40]:
            selects.append(f"{_quote_table(quote, t)}.{quote(c)} AS {quote(f'{t_alias}_{c}')}")
    return f"SELECT {', '.join(selects)} FROM {_quote_table(quote, base)} " + " ".join(clauses)


def _dict(m: DataModel) -> dict:
    try:
        spec = json.loads(m.spec)
    except (ValueError, TypeError):
        spec = {}
    return {"id": str(m.id), "connection_id": str(m.connection_id), "name": m.name,
            "slug": _slug(m.name), "spec": spec}


async def list_models(connection_id: str | None = None) -> list[dict]:
    async with get_sessionmaker()() as s:
        q = select(DataModel).order_by(DataModel.created_at)
        if connection_id:
            q = q.where(DataModel.connection_id == uuid.UUID(connection_id))
        rows = (await s.execute(q)).scalars().all()
        return [_dict(r) for r in rows]


async def create_model(connection_id: str, name: str, spec: dict) -> dict:
    schema_map = await _schema_map(connection_id)
    quote = data._engine(connection_id).dialect.identifier_preparer.quote  # noqa: SLF001
    sql = build_model_sql(schema_map, spec, quote)  # validates; raises ValueError with a clear message
    # prove it runs (read-only, 1 row) before saving
    await data.run_readonly_query(connection_id, f"SELECT * FROM ({sql}) AS _m LIMIT 1", row_cap=1)
    async with get_sessionmaker()() as s:
        row = DataModel(connection_id=uuid.UUID(connection_id), name=(name.strip() or "Model")[:120],
                        spec=json.dumps(spec))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return _dict(row)


async def delete_model(model_id: str) -> bool:
    async with get_sessionmaker()() as s:
        row = await s.get(DataModel, uuid.UUID(model_id))
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
        return True


async def models_as_transforms(connection_ids: list[str]) -> list[dict]:
    """Models rendered as transform dicts ({name, connection_id, sql}) for the dashboard engine."""
    out = []
    for cid in connection_ids:
        try:
            schema_map = await _schema_map(cid)
            quote = data._engine(cid).dialect.identifier_preparer.quote  # noqa: SLF001
        except Exception:  # noqa: BLE001 — unreachable connection → skip its models
            continue
        for m in await list_models(cid):
            try:
                sql = build_model_sql(schema_map, m["spec"], quote)
            except ValueError:
                continue  # schema drifted since the model was defined; skip rather than break boards
            out.append({"name": m["slug"], "connection_id": cid, "sql": sql,
                        "description": f"data model: {m['name']}"})
    return out


def describe_models(models: list[dict]) -> str:
    """Prompt block so the designing AI knows the pre-joined models it can query by name."""
    if not models:
        return ""
    lines = [f'- {m["name"]} (connection_id "{m["connection_id"]}"): {m["description"]}' for m in models]
    return (
        "\n\nPre-joined DATA MODELS (query them by name like tables; they already contain the joins):\n"
        + "\n".join(lines)
    )
