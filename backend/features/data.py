from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.core.database import get_sessionmaker
from backend.core.models import DataConnection
from backend.security import secrets

log = logging.getLogger("orrery.data")

ROW_CAP = 200
TIMEOUT_MS = 8000
_ASYNC_PG = "postgresql+psycopg"

_engines: dict[str, AsyncEngine] = {}


def _coerce_async(url: str):
    u = make_url(url)  # raises on garbage input
    if u.get_backend_name() in ("postgresql", "postgres"):
        u = u.set(drivername=_ASYNC_PG)
    return u


def _display(u) -> str:
    return f"{u.host or 'localhost'}:{u.port or 5432}/{u.database or ''}"


def _conn_secret(cid: str) -> str:
    return f"conn:{cid}"


def _cell(v):
    if v is None or isinstance(v, (int, float, bool, str)):
        return v
    return str(v)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _new_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url, pool_pre_ping=True, pool_size=2, max_overflow=2,
        connect_args={"connect_timeout": 5},
    )


def _engine(cid: str) -> AsyncEngine:
    eng = _engines.get(cid)
    if eng is None:
        url = secrets.get_secret(_conn_secret(cid))
        if not url:
            raise ValueError("Connection not found")
        eng = _new_engine(url)
        _engines[cid] = eng
    return eng


async def _run_readonly(engine: AsyncEngine, sql: str, params: dict | None = None, row_cap: int = ROW_CAP):
    """Run a query in a read-only, time-limited transaction; return (columns, capped rows).

    Read-only is enforced by the database (any write raises), not by inspecting the SQL.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await conn.execute(text(f"SET LOCAL statement_timeout = {int(TIMEOUT_MS)}"))
        result = await conn.execute(text(sql), params or {})
        cols = list(result.keys())
        rows = result.fetchmany(int(row_cap))
        await conn.rollback()
    return cols, [[_cell(c) for c in r] for r in rows]


async def _test_url(url: str) -> None:
    eng = _new_engine(url)
    try:
        await _run_readonly(eng, "SELECT 1", row_cap=1)
    finally:
        await eng.dispose()


async def add_connection(name: str, url: str) -> dict:
    try:
        u = _coerce_async(url)
    except Exception:  # noqa: BLE001
        raise ValueError("That doesn't look like a valid connection string.")
    async_url = u.render_as_string(hide_password=False)
    try:
        await _test_url(async_url)
    except Exception as exc:  # noqa: BLE001 — redact the password before surfacing
        raise ValueError(f"Couldn't connect: {secrets.redact_url(str(exc))[:160]}")

    cid = uuid.uuid4()
    async with get_sessionmaker()() as s:
        row = DataConnection(id=cid, name=(name.strip() or "database"), display=_display(u))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        meta = {"id": str(row.id), "name": row.name, "display": row.display, "reachable": True}
    secrets.set_secret(_conn_secret(str(cid)), async_url)  # the secret never goes in the DB
    return meta


async def list_connections() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(DataConnection).order_by(DataConnection.created_at))).scalars().all()
    out = []
    for r in rows:
        try:
            await _run_readonly(_engine(str(r.id)), "SELECT 1", row_cap=1)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        out.append({"id": str(r.id), "name": r.name, "display": r.display, "reachable": ok})
    return out


async def delete_connection(cid: str) -> bool:
    async with get_sessionmaker()() as s:
        row = await s.get(DataConnection, uuid.UUID(cid))
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
    eng = _engines.pop(cid, None)
    if eng is not None:
        await eng.dispose()
    secrets.delete_secret(_conn_secret(cid))
    return True


async def list_tables(cid: str) -> list[dict]:
    _cols, rows = await _run_readonly(
        _engine(cid),
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY table_schema, table_name",
        row_cap=2000,
    )
    return [{"schema": r[0], "table": r[1]} for r in rows]


async def browse_table(cid: str, schema: str, table: str, limit: int = 100) -> dict:
    allow = {(t["schema"], t["table"]) for t in await list_tables(cid)}
    if (schema, table) not in allow:  # validate against real names before quoting
        raise ValueError("Unknown table")
    limit = max(1, min(int(limit), ROW_CAP))
    sql = f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)} LIMIT {limit}"
    cols, rows = await _run_readonly(_engine(cid), sql, row_cap=limit)
    return {"schema": schema, "table": table, "columns": cols, "rows": rows}
