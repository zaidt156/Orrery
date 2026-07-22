"""Central approval gate for non-Agent tool side effects (Chat and Automations).

Risk-tiered so it rarely asks: read-only and sandboxed tools never prompt; only tools whose risk is
external_write or destructive (mcp_call, crabbox_run) require a user decision. An approval binds to
the sha256 digest of the exact validated arguments, is single-use, and expires — replaying an id or
tampering with the arguments invalidates it. "Always allow" decisions persist per owner in app
config so a trusted tool asks once, not on every call. Pending approvals live in memory (process
lifetime, like detached chat runs); Agent runs keep their own durable AgentApproval gate.

Enforcement happens in tools/registry.run_tool — below the model, on the actual execution boundary
(security.md §4/§11): no prompt wording can bypass it, and Chat cannot skip a check its owning
feature would apply.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

log = logging.getLogger("orrery.approvals")

GATED_RISKS = {"external_write", "destructive"}
PENDING_TTL_SECONDS = 600.0  # an undecided or unconsumed approval dies after 10 minutes
WAIT_SECONDS = 300.0         # how long a chat turn waits for the user before giving up

_ALLOWLIST_KEY = "tool_approval_allowlist"  # appconfig: {owner: [remember_key, ...]}


@dataclass
class _Approval:
    id: str
    tool_key: str
    remember_key: str
    digest: str
    label: str
    summary: str
    owner: str
    rememberable: bool = True  # destructive tools always ask — one click never becomes standing RCE
    status: str = "pending"  # pending | approved | denied | expired
    created: float = field(default_factory=time.monotonic)
    decided: asyncio.Event = field(default_factory=asyncio.Event)


_STORE: dict[str, _Approval] = {}


def args_digest(tool_key: str, args: dict) -> str:
    canonical = json.dumps({"tool": tool_key, "args": args}, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _remember_key(tool_key: str, args: dict) -> str:
    # MCP is remembered per server+tool, not as a blanket "all MCP" grant
    if tool_key == "mcp_call":
        return f"mcp:{args.get('server_id')}:{args.get('tool')}"
    return tool_key


def _summary_for(tool_key: str, label: str, args: dict) -> str:
    if tool_key == "mcp_call":
        preview = json.dumps(args.get("args") or {}, ensure_ascii=False, default=str)[:200]
        return f"Call MCP tool '{args.get('tool')}' with arguments {preview}"
    if tool_key == "crabbox_run":
        command = args.get("shell") or " ".join(args.get("command") or [])
        return f"Run remotely: {str(command)[:200]}"
    return f"Run {label or tool_key}"


async def _owner_key() -> str:
    """Approvals are per-identity. A locked/unknown team client cannot approve anything."""
    from backend.features import team
    in_team, owner = await team.owner_scope()
    if in_team and owner is None:
        raise PermissionError("Team access key required.")
    return owner or "solo"


async def _allowlist(owner: str) -> set[str]:
    from backend.core import appconfig
    stored = await appconfig.get_setting(_ALLOWLIST_KEY, {}) or {}
    return set(stored.get(owner) or [])


async def _remember(owner: str, remember_key: str) -> None:
    from backend.core import appconfig
    stored = await appconfig.get_setting(_ALLOWLIST_KEY, {}) or {}
    values = set(stored.get(owner) or [])
    values.add(remember_key)
    stored[owner] = sorted(values)
    await appconfig.set_setting(_ALLOWLIST_KEY, stored)


def _expired(entry: _Approval) -> bool:
    return time.monotonic() - entry.created > PENDING_TTL_SECONDS


def _sweep() -> None:
    for entry in list(_STORE.values()):
        if _expired(entry):
            _STORE.pop(entry.id, None)


def _public(entry: _Approval) -> dict:
    return {"id": entry.id, "tool": entry.tool_key, "label": entry.label,
            "summary": entry.summary, "status": entry.status,
            "rememberable": entry.rememberable}


async def gate(tool, validated_args: dict, approval_id: str | None = None) -> dict:
    """Decide one execution: {"allowed": True} or {"allowed": False, "error": ..., "approval": ...}.

    Called by run_tool after argument validation; the digest therefore covers exactly what would
    execute. With approval_id, the referenced approval must be approved, unexpired, owned by the
    caller, and match the digest — then it is consumed (single-use)."""
    if tool.risk not in GATED_RISKS:
        return {"allowed": True}
    try:
        owner = await _owner_key()
    except Exception:  # noqa: BLE001 — unknown identity cannot approve side effects
        return {"allowed": False, "approval": None,
                "error": "This action needs an identified user's approval."}
    digest = args_digest(tool.key, validated_args)
    if approval_id:
        entry = _STORE.pop(approval_id, None)  # consume: the id can never authorize twice
        ok = (entry is not None and entry.owner == owner and entry.status == "approved"
              and entry.digest == digest and not _expired(entry))
        if not ok:
            log.warning("tool approval rejected for %s (missing/expired/tampered)", tool.key)
            return {"allowed": False, "approval": None,
                    "error": "The approval is missing, expired, or does not match this exact action."}
        log.info("tool approval consumed: %s digest=%s", tool.key, digest[:12])
        return {"allowed": True}
    rememberable = tool.risk != "destructive"
    remember_key = _remember_key(tool.key, validated_args)
    if rememberable:
        try:
            if remember_key in await _allowlist(owner):
                log.info("tool pre-approved by allowlist: %s", remember_key)
                return {"allowed": True}
        except Exception:  # noqa: BLE001 — unreadable allowlist just means we ask; asking is the safe direction
            pass
    _sweep()
    entry = _Approval(
        id=uuid.uuid4().hex, tool_key=tool.key, remember_key=remember_key, digest=digest,
        label=tool.label or tool.key, summary=_summary_for(tool.key, tool.label, validated_args),
        owner=owner, rememberable=rememberable,
    )
    _STORE[entry.id] = entry
    log.info("tool approval requested: %s digest=%s", tool.key, digest[:12])
    return {"allowed": False, "approval": _public(entry), "error": "This action needs your approval."}


async def wait(approval_id: str, timeout: float = WAIT_SECONDS) -> str:
    """Block until the user decides (or the wait times out). Returns the final status."""
    entry = _STORE.get(approval_id)
    if entry is None:
        return "expired"
    try:
        await asyncio.wait_for(entry.decided.wait(), timeout=timeout)
    except TimeoutError:
        if entry.status == "pending":
            entry.status = "expired"
            _STORE.pop(entry.id, None)
    return entry.status


async def decide(approval_id: str, *, approve: bool, remember: bool = False) -> dict | None:
    """The user's decision. None when the approval is unknown or belongs to someone else."""
    owner = await _owner_key()
    entry = _STORE.get(approval_id)
    if entry is None or entry.owner != owner:
        return None
    if entry.status == "pending" and _expired(entry):
        entry.status = "expired"
        entry.decided.set()
        _STORE.pop(entry.id, None)
    if entry.status == "pending":
        entry.status = "approved" if approve else "denied"
        if approve and remember and entry.rememberable:
            await _remember(owner, entry.remember_key)
        entry.decided.set()
        if entry.status == "denied":
            _STORE.pop(entry.id, None)
        log.info("tool approval %s: %s", entry.status, entry.tool_key)
    return {"id": entry.id, "status": entry.status}


async def list_pending() -> list[dict]:
    owner = await _owner_key()
    _sweep()
    return [_public(e) for e in _STORE.values() if e.owner == owner and e.status == "pending"]
