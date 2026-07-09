"""Message versioning: the conversation is a tree (Message.parent_id), and exactly one sibling per
parent is `active`. These pure helpers turn the flat row set into the currently-viewed path plus the
‹ › switcher metadata, so both history assembly and conversation loading follow the same active path.

Kept dependency-free (attribute access only) so it unit-tests without a database: any object with
`.id`, `.parent_id`, `.active`, and `.created_at` works (ORM rows in prod, stubs in tests)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _key(created_at: Any, mid: Any) -> tuple:
    # created_at may be None on freshly-built rows not yet flushed; fall back to id for a stable order.
    return (created_at is not None, created_at, str(mid))


def _children_map(messages: list) -> dict:
    children: dict = defaultdict(list)
    for m in messages:
        children[_pid(m)].append(m)
    for group in children.values():
        group.sort(key=lambda m: _key(m.created_at, m.id))
    return children


def _pid(m) -> str | None:
    pid = getattr(m, "parent_id", None)
    return str(pid) if pid is not None else None


def _pick_active(group: list):
    """The active sibling in a group, or the newest as a safe fallback if none/many are flagged."""
    actives = [m for m in group if getattr(m, "active", True)]
    if len(actives) == 1:
        return actives[0]
    if actives:
        return max(actives, key=lambda m: _key(m.created_at, m.id))
    return group[-1] if group else None


def active_path(messages: list) -> list:
    """Root-to-leaf list of messages on the active path (following the active child at each step)."""
    if not messages:
        return []
    children = _children_map(messages)
    path: list = []
    node = _pick_active(children.get(None, []))
    seen: set = set()
    while node is not None and str(node.id) not in seen:
        seen.add(str(node.id))
        path.append(node)
        node = _pick_active(children.get(str(node.id), []))
    return path


def leaf_id(messages: list) -> str | None:
    """The id (str) of the active path's tip — where a newly sent message attaches as a child."""
    path = active_path(messages)
    return str(path[-1].id) if path else None


def ancestors(messages: list, target_id: str) -> list:
    """Root-to-target chain (inclusive) following parent pointers — works for messages on OR off
    the active path, so per-message actions (evaluate, export) see the history that actually led
    to that exact version. Empty list when the target isn't in the set."""
    by_id = {str(m.id): m for m in messages}
    node = by_id.get(str(target_id))
    chain: list = []
    seen: set = set()
    while node is not None and str(node.id) not in seen:
        seen.add(str(node.id))
        chain.append(node)
        pid = _pid(node)
        node = by_id.get(pid) if pid is not None else None
    chain.reverse()
    return chain


def sibling_turn_seed(messages: list, target_id: str) -> tuple | None:
    """(parent_id, prior_history) for resubmitting a user turn as a new sibling version: the new
    message shares the target's parent, and the model sees only the chain BEFORE the target.
    None when the target isn't a known user message (caller falls back to a normal append)."""
    chain = ancestors(messages, target_id)
    if not chain or getattr(chain[-1], "role", "") != "user":
        return None
    return getattr(chain[-1], "parent_id", None), chain[:-1]


def trim_to_last_user(path: list) -> list:
    """The path up to (and including) its most recent user turn — the regenerate anchor. Trailing
    assistant replies are dropped (not deleted: the new reply becomes their sibling version)."""
    end = len(path)
    while end and getattr(path[end - 1], "role", "") != "user":
        end -= 1
    return path[:end]


def version_map(messages: list) -> dict:
    """{message_id: {"version": 1-based index, "versions": count, "siblings": [ids in order]}}.

    Only messages that have at least one sibling get an entry worth showing arrows for, but every
    path message is included so the frontend can look each one up uniformly."""
    children = _children_map(messages)
    out: dict = {}
    for group in children.values():
        ordered_ids = [str(m.id) for m in group]  # already time-sorted by _children_map
        count = len(group)
        active = _pick_active(group)
        active_id = str(active.id) if active is not None else None
        for i, m in enumerate(group):
            out[str(m.id)] = {
                "version": i + 1,
                "versions": count,
                "siblings": ordered_ids,
                "active_sibling": active_id,
            }
    return out
