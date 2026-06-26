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
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS effort VARCHAR(10)"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_window INTEGER"))
        await conn.execute(text("UPDATE conversations SET context_window = 1000000 WHERE context_window IS NULL"))
        await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS context TEXT"))
        await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS artifacts TEXT"))
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
