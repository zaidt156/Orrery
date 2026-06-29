"""Skills: reusable instruction playbooks the model 'reads' before fulfilling a request.

Each file in skills/ is a Markdown doc with light frontmatter (name, triggers, always).
For every turn we match the user's message against each skill's triggers and inject the
matching skills into the system prompt — so e.g. asking for a PowerPoint pulls in the
deck-design skill, asking to code pulls in the coding skill, and a core skill (always on)
keeps every answer thorough and well-reasoned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
_cache: list["Skill"] | None = None


@dataclass
class Skill:
    name: str
    body: str
    triggers: list[str] = field(default_factory=list)
    always: bool = False

    def matches(self, text: str) -> bool:
        return self.always or any(t and t in text for t in self.triggers)


def _parse(raw: str, fallback_name: str) -> "Skill | None":
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            for line in raw[3:end].strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = value.strip()
            body = raw[end + 4:].strip()
    if not body.strip():
        return None
    triggers = [t.strip().lower() for t in re.split(r"[,\n]", meta.get("triggers", "")) if t.strip()]
    always = meta.get("always", "").strip().lower() in {"true", "yes", "1"}
    return Skill(name=meta.get("name") or fallback_name, body=body.strip(), triggers=triggers, always=always)


def _builtin() -> list["Skill"]:
    global _cache
    if _cache is None:
        loaded: list[Skill] = []
        if _SKILLS_DIR.is_dir():
            # flat skills (skills/name.md) and the open folder format (skills/name/SKILL.md)
            paths = sorted(_SKILLS_DIR.glob("*.md")) + sorted(_SKILLS_DIR.glob("*/SKILL.md"))
            for path in paths:
                fallback = path.parent.name if path.name.upper() == "SKILL.MD" else path.stem
                try:
                    skill = _parse(path.read_text(encoding="utf-8"), fallback)
                except OSError:
                    continue
                if skill:
                    loaded.append(skill)
        _cache = loaded
    return _cache


# Enabled user-authored skills, mirrored from the DB into memory so select() stays synchronous.
_user_skills: list["Skill"] = []


def _load() -> list["Skill"]:
    """Built-in file skills plus the user's own enabled skills."""
    return _builtin() + _user_skills


def reload() -> None:
    global _cache
    _cache = None


async def refresh_user_skills() -> None:
    """Reload enabled user skills from the DB. Called at startup and after any create/edit/delete."""
    global _user_skills
    from sqlalchemy import select as sa_select

    from backend.core.database import get_sessionmaker
    from backend.core.models import UserSkill
    try:
        async with get_sessionmaker()() as s:
            rows = (await s.execute(sa_select(UserSkill).where(UserSkill.enabled.is_(True)))).scalars().all()
        _user_skills = [
            Skill(
                name=r.name,
                body=r.body,
                triggers=[t.strip().lower() for t in re.split(r"[,\n]", r.triggers or "") if t.strip()],
                always=bool(r.always),
            )
            for r in rows if (r.body or "").strip()
        ]
    except Exception:  # noqa: BLE001 — DB unavailable shouldn't break skill loading; keep current set
        pass


def select(user_text: str) -> list["Skill"]:
    text = (user_text or "").lower()
    return [skill for skill in _load() if skill.matches(text)]


def skills_prompt(user_text: str) -> str:
    chosen = select(user_text)
    if not chosen:
        return ""
    blocks = [f"### Skill — {skill.name}\n{skill.body}" for skill in chosen]
    return (
        "Before answering, apply these Orrery skills (read them fully and follow them):\n\n"
        + "\n\n".join(blocks)
    )


# --- user-authored skills (created/edited in the UI; stored in the DB) ---

def _user_skill_dict(r) -> dict:
    return {
        "id": str(r.id), "name": r.name, "triggers": r.triggers or "", "body": r.body,
        "always": bool(r.always), "enabled": bool(r.enabled),
    }


def parse_skill_markdown(raw: str, fallback_name: str = "Skill") -> dict:
    """Parse an uploaded .md skill (same frontmatter format as built-in skills) into fields."""
    skill = _parse(raw or "", fallback_name)
    if skill is None:
        return {"name": fallback_name, "triggers": "", "body": (raw or "").strip(), "always": False}
    return {"name": skill.name, "triggers": ", ".join(skill.triggers), "body": skill.body, "always": skill.always}


def list_builtin() -> list[dict]:
    """The built-in (prebuilt) skills shipped with Orrery — always available, read-only."""
    return [{"name": s.name, "triggers": ", ".join(s.triggers), "always": s.always} for s in _builtin()]


async def list_user_skills() -> list[dict]:
    from sqlalchemy import select as sa_select

    from backend.core.database import get_sessionmaker
    from backend.core.models import UserSkill
    async with get_sessionmaker()() as s:
        rows = (await s.execute(sa_select(UserSkill).order_by(UserSkill.created_at))).scalars().all()
        return [_user_skill_dict(r) for r in rows]


async def create_user_skill(name: str, body: str, triggers: str = "", always: bool = False, enabled: bool = True) -> dict:
    from backend.core.database import get_sessionmaker
    from backend.core.models import UserSkill
    async with get_sessionmaker()() as s:
        row = UserSkill(name=(name.strip() or "Skill")[:120], body=body.strip(), triggers=triggers.strip(),
                        always=bool(always), enabled=bool(enabled))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        out = _user_skill_dict(row)
    await refresh_user_skills()
    return out


async def update_user_skill(skill_id: str, **fields) -> bool:
    import uuid as _uuid

    from backend.core.database import get_sessionmaker
    from backend.core.models import UserSkill
    async with get_sessionmaker()() as s:
        row = await s.get(UserSkill, _uuid.UUID(skill_id))
        if row is None:
            return False
        if fields.get("name") is not None:
            row.name = (fields["name"].strip() or row.name)[:120]
        if fields.get("body") is not None:
            row.body = fields["body"].strip()
        if fields.get("triggers") is not None:
            row.triggers = fields["triggers"].strip()
        if fields.get("always") is not None:
            row.always = bool(fields["always"])
        if fields.get("enabled") is not None:
            row.enabled = bool(fields["enabled"])
        await s.commit()
    await refresh_user_skills()
    return True


async def generate_user_skill(model: str, description: str) -> dict:
    """Have the model draft a full skill (name, triggers, body) from a plain-language description."""
    import json as _json

    from backend.providers import ai
    instruction = (
        "You are creating a reusable Orrery 'skill' — an instruction playbook an AI reads before "
        "answering matching requests. From the user's description, output ONLY a JSON object with keys:\n"
        '  "name": a short title,\n'
        '  "triggers": a comma-separated list of phrases that should activate this skill (empty string '
        'if it should always apply),\n'
        '  "always": true or false (true = apply on every message),\n'
        '  "body": the full playbook in Markdown — clear, specific, actionable guidance the model should '
        "follow.\n"
        "Return only the JSON object, no prose around it.\n\nUser description:\n" + description.strip()
    )
    parts: list[str] = []
    async for delta in ai.stream_chat(model, [{"role": "user", "content": instruction}], None, "high"):
        if not isinstance(delta, ai.ReasoningDelta):
            parts.append(str(delta))
    text = "".join(parts)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    data: dict = {}
    if match:
        try:
            data = _json.loads(match.group(0))
        except (ValueError, TypeError):
            data = {}
    name = str(data.get("name") or "Generated skill")
    body = str(data.get("body") or text).strip()
    triggers = data.get("triggers") or ""
    if isinstance(triggers, list):
        triggers = ", ".join(str(t) for t in triggers)
    always = bool(data.get("always"))
    return await create_user_skill(name, body, str(triggers), always, enabled=True)


async def delete_user_skill(skill_id: str) -> bool:
    import uuid as _uuid

    from backend.core.database import get_sessionmaker
    from backend.core.models import UserSkill
    async with get_sessionmaker()() as s:
        row = await s.get(UserSkill, _uuid.UUID(skill_id))
        if row is None:
            return False
        await s.delete(row)
        await s.commit()
    await refresh_user_skills()
    return True
