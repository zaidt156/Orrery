from __future__ import annotations

import uuid

from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.core.models import ActiveModel, CustomModel
from backend.security import netguard, secrets

# custom-model keys reuse the provider-key helpers under a "custom:<id>" namespace,
# so the raw key still lives only in the OS keychain (security.md §1)


def custom_model_id(custom_id: str) -> str:
    return f"custom/{custom_id}"


def _key_provider(custom_id: str) -> str:
    return f"custom:{custom_id}"


def custom_model_key(custom_id: str) -> str | None:
    """The raw key for a custom endpoint — for the provider call only, never logged/returned."""
    return secrets.get_provider_key(_key_provider(custom_id))


# --- custom (OpenAI-compatible) models ---

async def list_custom_models() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(CustomModel).order_by(CustomModel.created_at))).scalars().all()
        return [
            {
                "id": custom_model_id(str(c.id)),
                "custom_id": str(c.id),
                "label": c.label,
                "base_url": c.base_url,
                "model": c.model,
                "provider": "custom",
                "configured": bool(custom_model_key(str(c.id))),
            }
            for c in rows
        ]


async def get_custom_model(custom_id: str) -> dict | None:
    async with get_sessionmaker()() as s:
        c = await s.get(CustomModel, uuid.UUID(custom_id))
        if c is None:
            return None
        return {"label": c.label, "base_url": c.base_url, "model": c.model}


async def add_custom_model(label: str, base_url: str, model: str, key: str | None) -> dict:
    base_url = netguard.validate_model_base_url(base_url)  # SSRF guard before we ever store/call it
    cid = uuid.uuid4()
    async with get_sessionmaker()() as s:
        s.add(CustomModel(id=cid, label=label, base_url=base_url, model=model))
        await s.commit()
    if key:
        secrets.set_provider_key(_key_provider(str(cid)), key.strip())
    mid = custom_model_id(str(cid))
    await set_active(mid, label, "custom", True)  # the user just added it → on by default
    return {
        "id": mid, "custom_id": str(cid), "label": label,
        "base_url": base_url, "model": model, "provider": "custom",
        "configured": bool(key),
    }


async def delete_custom_model(custom_id: str) -> bool:
    async with get_sessionmaker()() as s:
        c = await s.get(CustomModel, uuid.UUID(custom_id))
        if c is None:
            return False
        await s.delete(c)
        await s.commit()
    secrets.clear_provider_key(_key_provider(custom_id))
    await set_active(custom_model_id(custom_id), "", "", False)
    return True


# --- activation (which models the Chat menu shows) ---

async def active_ids() -> set[str]:
    async with get_sessionmaker()() as s:
        return set((await s.execute(select(ActiveModel.model_id))).scalars().all())


async def list_active() -> list[dict]:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(ActiveModel).order_by(ActiveModel.created_at))).scalars().all()
        return [{"id": r.model_id, "label": r.label, "provider": r.provider} for r in rows]


async def set_active(model_id: str, label: str, provider: str, on: bool) -> None:
    async with get_sessionmaker()() as s:
        existing = await s.get(ActiveModel, model_id)
        if on:
            if existing is None:
                s.add(ActiveModel(model_id=model_id, label=label, provider=provider))
            elif label:
                existing.label = label
        elif existing is not None:
            await s.delete(existing)
        await s.commit()


async def activate_many(items: list[dict]) -> None:
    """Turn on a batch of models (used when a provider is first configured). Idempotent."""
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(ActiveModel))).scalars().all()
        have = {row.model_id: row for row in rows}
        for it in items:
            existing = have.get(it["id"])
            if existing is None:
                s.add(ActiveModel(model_id=it["id"], label=it["label"], provider=it["provider"]))
            else:
                existing.label = it["label"]
                existing.provider = it["provider"]
        await s.commit()


async def refresh_active_metadata(items: list[dict]) -> None:
    """Refresh labels/providers without changing which models are active."""
    by_id = {it["id"]: it for it in items}
    if not by_id:
        return
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(select(ActiveModel).where(ActiveModel.model_id.in_(by_id)))
        ).scalars().all()
        changed = False
        for row in rows:
            item = by_id[row.model_id]
            if row.label != item["label"] or row.provider != item["provider"]:
                row.label = item["label"]
                row.provider = item["provider"]
                changed = True
        if changed:
            await s.commit()
