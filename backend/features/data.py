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
    backend = u.get_backend_name()
    if backend in ("postgresql", "postgres"):
        u = u.set(drivername=_ASYNC_PG)
    elif backend in ("mysql", "mariadb"):
        u = u.set(drivername="mysql+aiomysql")
    elif backend == "sqlite":
        u = u.set(drivername="sqlite+aiosqlite")
    elif backend == "mssql":
        u = u.set(drivername="mssql+aioodbc")
        if "driver" not in {k.lower() for k in u.query}:
            u = u.update_query_dict({"driver": "ODBC Driver 17 for SQL Server"})
    else:
        raise ValueError(
            f"Unsupported database type: {backend}. Use postgres://, mysql://, mssql://, or sqlite:///path."
        )
    return u


def _display(u) -> str:
    if u.get_backend_name().startswith("sqlite"):
        return u.database or "sqlite"
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
    """Engine with DB-level read-only enforcement per dialect (never by inspecting SQL)."""
    backend = make_url(url).get_backend_name().split("+")[0]
    if backend == "sqlite":
        eng = create_async_engine(url, pool_pre_ping=True)
        from sqlalchemy import event

        @event.listens_for(eng.sync_engine, "connect")
        def _sqlite_readonly(dbapi_conn, _rec):  # the file itself may be writable; the session is not
            dbapi_conn.execute("PRAGMA query_only = ON")
        return eng
    if backend in ("mysql", "mariadb"):
        return create_async_engine(
            url, pool_pre_ping=True, pool_size=2, max_overflow=2,
            connect_args={"connect_timeout": 5, "init_command": "SET SESSION TRANSACTION READ ONLY"},
        )
    if backend == "mssql":
        # SQL Server has no session read-only mode: connect with a read-only login (recommended in
        # the UI); every dashboard query is additionally parse-gated to a single SELECT.
        return create_async_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2,
                                   connect_args={"timeout": 5})
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


async def _run_readonly(engine: AsyncEngine, sql: str, params: dict | None = None, row_cap: int = ROW_CAP,
                        search_path: str | None = None):
    """Run a query in a read-only, time-limited transaction; return (columns, capped rows).

    Read-only is enforced by the database (any write raises), not by inspecting the SQL:
    Postgres = READ ONLY transaction; MySQL = read-only session (init_command); SQLite = query_only.
    `search_path` (Postgres) lets dataset workspaces resolve bare table names to their own schema.
    """
    dialect = engine.dialect.name
    async with engine.connect() as conn:
        if dialect == "postgresql":
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text(f"SET LOCAL statement_timeout = {int(TIMEOUT_MS)}"))
            if search_path:
                await conn.execute(text(f"SET LOCAL search_path TO {_quote_ident(search_path)}"))
        elif dialect in ("mysql", "mariadb"):
            try:  # best-effort per-query time cap (MySQL 5.7+; MariaDB uses max_statement_time)
                await conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {int(TIMEOUT_MS)}"))
            except Exception:  # noqa: BLE001
                pass
        result = await conn.execute(text(sql), params or {})
        cols = list(result.keys())
        rows = result.fetchmany(int(row_cap))
        await conn.rollback()
    return cols, [[_cell(c) for c in r] for r in rows]


async def dataset_schema(cid: str) -> str | None:
    """The workspace schema for a datasets connection, else None."""
    async with get_sessionmaker()() as s:
        row = await s.get(DataConnection, uuid.UUID(cid))
    if row is not None and (getattr(row, "kind", "") or "") == "datasets":
        return getattr(row, "db_schema", None) or "orrery_datasets"
    return None


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


async def connection_kind(cid: str) -> str:
    """postgres (a user DB) or datasets (an import workspace, scoped to its own schema)."""
    async with get_sessionmaker()() as s:
        row = await s.get(DataConnection, uuid.UUID(cid))
        return getattr(row, "kind", "postgres") or "postgres" if row else "postgres"


async def _schema_filter(cid: str) -> str:
    async with get_sessionmaker()() as s:
        row = await s.get(DataConnection, uuid.UUID(cid))
    if row is not None and (getattr(row, "kind", "") or "") == "datasets":
        schema = (getattr(row, "db_schema", None) or "orrery_datasets").replace("'", "''")
        return f"table_schema = '{schema}'"
    # normal connections never see any import workspace (the app's own tables are in public — those
    # stay visible only when the user deliberately connects Orrery's own database)
    return ("table_schema NOT IN ('pg_catalog', 'information_schema', 'orrery_datasets') "
            "AND table_schema NOT LIKE 'orrery_ws_%'")


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
        out.append({"id": str(r.id), "name": r.name, "display": r.display, "reachable": ok,
                    "kind": getattr(r, "kind", "postgres") or "postgres"})
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


async def run_readonly_query(cid: str, sql: str, row_cap: int = ROW_CAP):
    """Run one query against a connection in the DB-enforced read-only path (dashboards, tools)."""
    return await _run_readonly(_engine(cid), sql, row_cap=row_cap, search_path=await dataset_schema(cid))


async def _columns_rows(cid: str, cap: int):
    """(schema, table, column, type) rows across dialects (SQLite has no information_schema)."""
    engine = _engine(cid)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        _c, names = await _run_readonly(
            engine,
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name",
            row_cap=200,
        )
        out = []
        for (tname,) in names[:60]:
            safe = tname.replace("'", "''")
            _c2, cols = await _run_readonly(engine, f"SELECT name, type FROM pragma_table_info('{safe}')", row_cap=200)
            out += [("main", tname, c[0], (c[1] or "text").lower()) for c in cols]
        return out
    if dialect in ("mysql", "mariadb"):
        where = "table_schema = DATABASE()"
    else:
        where = await _schema_filter(cid)
    _c, rows = await _run_readonly(
        engine,
        "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
        f"WHERE {where} ORDER BY table_schema, table_name, ordinal_position",
        row_cap=cap,
    )
    return rows


async def schema_overview(cid: str, max_tables: int = 40, max_columns: int = 24) -> str:
    """Compact 'table(col type, …)' listing a model can design queries against."""
    rows = await _columns_rows(cid, max_tables * max_columns * 2)
    engine = _engine(cid)
    default_schema = (await dataset_schema(cid)) or {"sqlite": "main", "mysql": None, "mariadb": None, "mssql": "dbo"}.get(engine.dialect.name, "public")
    tables: dict[str, list[str]] = {}
    for schema, table, col, dtype in rows:
        key = table if (default_schema is None or schema == default_schema) else f"{schema}.{table}"
        cols = tables.setdefault(key, [])
        if len(cols) < max_columns:
            cols.append(f"{col} {dtype}")
    lines = [f"- {name}({', '.join(cols)})" for name, cols in list(tables.items())[:max_tables]]
    return "\n".join(lines)


async def list_tables(cid: str) -> list[dict]:
    engine = _engine(cid)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        _c, rows = await _run_readonly(
            engine,
            "SELECT 'main', name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name",
            row_cap=2000,
        )
    else:
        where = "table_schema = DATABASE()" if dialect in ("mysql", "mariadb") else await _schema_filter(cid)
        _c, rows = await _run_readonly(
            engine,
            f"SELECT table_schema, table_name FROM information_schema.tables WHERE {where} "
            "ORDER BY table_schema, table_name",
            row_cap=2000,
        )
    return [{"schema": r[0], "table": r[1]} for r in rows]


async def browse_table(cid: str, schema: str, table: str, limit: int = 100) -> dict:
    allow = {(t["schema"], t["table"]) for t in await list_tables(cid)}
    if (schema, table) not in allow:  # validate against real names before quoting
        raise ValueError("Unknown table")
    limit = max(1, min(int(limit), ROW_CAP))
    engine = _engine(cid)
    q = engine.dialect.identifier_preparer.quote  # dialect-correct quoting (backticks vs double quotes)
    target = q(table) if engine.dialect.name == "sqlite" else f"{q(schema)}.{q(table)}"
    sql = f"SELECT * FROM {target} LIMIT {limit}"
    cols, rows = await _run_readonly(engine, sql, row_cap=limit)
    return {"schema": schema, "table": table, "columns": cols, "rows": rows}
