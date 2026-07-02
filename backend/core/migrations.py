from __future__ import annotations

import logging

from sqlalchemy import text

from backend.core.database import get_engine

log = logging.getLogger("orrery.migrations")


async def _queue_schema_present() -> bool:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT to_regclass('public.procrastinate_jobs')"))
        return result.scalar() is not None


# Versioned migrations (plan #6): each runs once, tracked in schema_migrations. Statements use
# DROP-IF-EXISTS / IF-NOT-EXISTS guards so a re-run is harmless. DDL that can't apply (e.g. a
# constraint an old row violates) is logged and skipped, never crashing startup.
_VERSIONED_MIGRATIONS: list[tuple[str, list[str]]] = [
    ("0001_check_constraints", [
        "ALTER TABLE messages DROP CONSTRAINT IF EXISTS ck_messages_role",
        "ALTER TABLE messages ADD CONSTRAINT ck_messages_role CHECK (role IN ('user','assistant','system'))",
        "ALTER TABLE conversations DROP CONSTRAINT IF EXISTS ck_conversations_effort",
        "ALTER TABLE conversations ADD CONSTRAINT ck_conversations_effort "
        "CHECK (effort IS NULL OR effort IN ('low','medium','high','xhigh','max'))",
        "ALTER TABLE feedback DROP CONSTRAINT IF EXISTS ck_feedback_category",
        "ALTER TABLE feedback ADD CONSTRAINT ck_feedback_category "
        "CHECK (category IN ('bug','idea','praise','general'))",
    ]),
    ("0002_chunks_hnsw_index", [
        # HNSW index for fast semantic search; matches rag.search's cosine (<=>) operator
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)",
    ]),
    ("0003_task_route_events", [
        "CREATE TABLE IF NOT EXISTS task_route_events ("
        "id UUID PRIMARY KEY, "
        "conversation_id UUID NULL REFERENCES conversations(id) ON DELETE SET NULL, "
        "route VARCHAR(20) NOT NULL, "
        "label VARCHAR(80) NOT NULL, "
        "output_mode VARCHAR(20) NOT NULL, "
        "skills VARCHAR(300) NOT NULL DEFAULT '', "
        "confidence DOUBLE PRECISION NOT NULL DEFAULT 0, "
        "has_attachments BOOLEAN NOT NULL DEFAULT FALSE, "
        "sandbox_policy VARCHAR(20) NOT NULL DEFAULT 'none', "
        "outcome VARCHAR(40) NOT NULL DEFAULT 'planned', "
        "detail TEXT NULL, "
        "created_at TIMESTAMPTZ DEFAULT now(), "
        "CONSTRAINT ck_task_route_events_route CHECK (route IN ('chat', 'file', 'image', 'audio', 'project')), "
        "CONSTRAINT ck_task_route_events_output_mode CHECK (output_mode IN ('chat', 'file', 'artifact', 'audio')), "
        "CONSTRAINT ck_task_route_events_sandbox_policy CHECK (sandbox_policy IN ('none', 'preferred', 'required')), "
        "CONSTRAINT ck_task_route_events_outcome CHECK (outcome IN ("
        "'planned', 'completed', 'failed', 'unavailable', "
        "'sandbox_success', 'sandbox_fallback', 'sandbox_failed', "
        "'deterministic_success', 'deterministic_failed'))"
        ")",
        "CREATE INDEX IF NOT EXISTS ix_task_route_events_conversation_id ON task_route_events (conversation_id)",
        "CREATE INDEX IF NOT EXISTS ix_task_route_events_route_created ON task_route_events (route, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_task_route_events_outcome_created ON task_route_events (outcome, created_at)",
    ]),
]


async def _apply_versioned(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
        ))
    for version, statements in _VERSIONED_MIGRATIONS:
        try:
            async with engine.begin() as conn:
                done = (await conn.execute(
                    text("SELECT 1 FROM schema_migrations WHERE version = :v"), {"v": version}
                )).scalar()
                if done:
                    continue
                for sql in statements:
                    await conn.execute(text(sql))
                await conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version}
                )
            log.info("applied migration %s", version)
        except Exception as exc:  # noqa: BLE001 — one bad optional migration must not block startup
            log.error("migration %s skipped: %s", version, str(exc)[:200])


async def run_migrations() -> None:
    """Enable pgvector and ensure the app + job-queue schema exists. Idempotent."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    log.info("pgvector extension ensured")

    # Orrery's own feature tables (only creates what's missing)
    from backend.core.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # additive column migrations (create_all only creates missing tables, not columns)
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS project_id UUID"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_project_id ON conversations (project_id)"))
        await conn.execute(text(
            """
            DO $$
            BEGIN
                ALTER TABLE conversations
                ADD CONSTRAINT fk_conversations_project_id
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END $$;
            """
        ))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS collection_id UUID"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS effort VARCHAR(10)"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_window INTEGER"))
        await conn.execute(text("UPDATE conversations SET context_window = 1000000 WHERE context_window IS NULL"))
        await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS context TEXT"))
        await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS artifacts TEXT"))
        await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reasoning TEXT"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS collection_id UUID"))
        # Ontologies are collections with a kind + a connected flag (connected => used as chat context)
        await conn.execute(text("ALTER TABLE collections ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'collection'"))
        await conn.execute(text("ALTER TABLE collections ADD COLUMN IF NOT EXISTS connected BOOLEAN NOT NULL DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE collections ADD COLUMN IF NOT EXISTS description TEXT"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS tools TEXT"))
        # Team mode: chats/projects are private to their owner (null = single-user / legacy)
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36)"))
        await conn.execute(text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36)"))
        # Data sources: connection kind (postgres | datasets) + the datasets schema for imports
        await conn.execute(text("ALTER TABLE data_connections ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'postgres'"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS orrery_datasets"))
        # Team mode: member-authored skills/MCP need admin approval before they go team-wide
        await conn.execute(text("ALTER TABLE user_skills ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36)"))
        await conn.execute(text("ALTER TABLE user_skills ADD COLUMN IF NOT EXISTS status VARCHAR(12) NOT NULL DEFAULT 'approved'"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36)"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS status VARCHAR(12) NOT NULL DEFAULT 'approved'"))
        label_updates = {
            "claude_plan/default": "Claude plan - adaptive thinking",
            "claude_plan/opus": "Claude plan - Opus - adaptive thinking",
            "claude_plan/sonnet": "Claude plan - Sonnet - adaptive thinking",
            "claude_plan/haiku": "Claude plan - Haiku - fast",
            "chatgpt_plan/default": "ChatGPT plan - best available - reasoning",
            "chatgpt_plan/gpt-5.5": "ChatGPT plan - GPT-5.5 - reasoning",
            "chatgpt_plan/gpt-5.5-mini": "ChatGPT plan - GPT-5.4 mini - fast reasoning",
        }
        for model_id, label in label_updates.items():
            await conn.execute(
                text("UPDATE active_models SET label = :label WHERE model_id = :model_id"),
                {"model_id": model_id, "label": label},
            )
        empty = (await conn.execute(text("SELECT COUNT(*) FROM active_models"))).scalar() == 0
    log.info("application tables ensured")

    await _apply_versioned(engine)  # constraints + vector index (idempotent, fail-safe)

    # seed the active set once so an existing Claude-plan user keeps a working Chat menu
    if empty:
        from backend.providers import accounts, catalog

        plan = accounts.claude_plan_models()  # [] (no CLI probe) unless already connected
        if plan:
            await catalog.activate_many(
                [{"id": m["id"], "label": m["label"], "provider": m["provider"]} for m in plan]
            )
            log.info("seeded active models from Claude plan")

    if await _queue_schema_present():
        log.info("job-queue schema already present")
        return

    # Procrastinate's own schema (tables backing the durable queue)
    from backend.core.queue import get_queue_app

    queue_app = get_queue_app()
    async with queue_app.open_async():
        await queue_app.schema_manager.apply_schema_async()
    log.info("job-queue schema applied")
