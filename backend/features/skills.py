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


def _load() -> list["Skill"]:
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


def reload() -> None:
    global _cache
    _cache = None


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
