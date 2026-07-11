"""User-owned, upgrade-safe durable memory with exact revision contracts.

This module is the only filesystem writer for runtime ``LIFE.md`` files. Agent, connector, and
external-API code may prepare proposals, but applying one requires the authenticated local approval
layer to call :func:`apply_exact` with the proposal's immutable hashes.
"""

from __future__ import annotations

import difflib
import datetime
import hashlib
import os
import re
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock
from sqlalchemy import select

from backend.core.paths import resource_path, user_data_dir
from backend.security.secrets import redact_secrets

MAX_LIFE_BYTES = 256 * 1024
_HASH_RX = re.compile(r"^[0-9a-f]{64}$")


class LifeError(RuntimeError):
    """Base class for safe, user-facing LIFE failures."""


class LifeValidationError(LifeError):
    pass


class LifeSecretError(LifeValidationError):
    pass


class LifeConflictError(LifeError):
    pass


class LifePathError(LifeError):
    pass


@dataclass(frozen=True)
class LifeDocument:
    path: Path
    content: str
    revision: str


@dataclass(frozen=True)
class PreparedLifeProposal:
    content: str
    base_hash: str
    target_hash: str
    diff: str


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _owner_segment(owner_id: str | None) -> str | None:
    if owner_id is None:
        return None
    try:
        return str(uuid.UUID(str(owner_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LifePathError("Invalid LIFE owner identifier.") from exc


def canonical_path(*, owner_id: str | None = None, data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else user_data_dir()
    owner = _owner_segment(owner_id)
    return root / "LIFE.md" if owner is None else root / "users" / owner / "LIFE.md"


def _history_dir(*, owner_id: str | None = None, data_root: Path | None = None) -> Path:
    return canonical_path(owner_id=owner_id, data_root=data_root).parent / ".life-history"


def history_path(
    revision: str, *, owner_id: str | None = None, data_root: Path | None = None
) -> Path:
    if not _HASH_RX.fullmatch(revision or ""):
        raise LifePathError("Invalid LIFE revision identifier.")
    return _history_dir(owner_id=owner_id, data_root=data_root) / f"{revision}.md"


def _is_reparse_point(path: Path) -> bool:
    try:
        attrs = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _assert_safe_target(path: Path) -> None:
    """Reject links/reparse points so a canonical write cannot escape its controlled directory."""
    if path.is_symlink() or _is_reparse_point(path):
        raise LifePathError("LIFE.md cannot be a link or reparse point.")
    parent = path.parent
    if parent.is_symlink() or _is_reparse_point(parent):
        raise LifePathError("The LIFE.md directory cannot be a link or reparse point.")
    if path.exists() and not path.is_file():
        raise LifePathError("LIFE.md must be a regular file.")


def _decode_file(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifeValidationError("LIFE.md must be UTF-8 text.") from exc


def _validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise LifeValidationError("LIFE.md content must be text.")
    raw = content.encode("utf-8")
    if len(raw) > MAX_LIFE_BYTES:
        raise LifeValidationError(f"LIFE.md is limited to {MAX_LIFE_BYTES // 1024} KiB.")
    if "\x00" in content:
        raise LifeValidationError("LIFE.md cannot contain NUL characters.")
    if redact_secrets(content) != content:
        raise LifeSecretError("LIFE.md appears to contain a credential or secret. Remove it first.")
    return content


def _lock_for(path: Path) -> FileLock:
    return FileLock(str(path.parent / ".life.lock"), timeout=10)


def _atomic_write_unlocked(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_target(path)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=".life-", suffix=".tmp", dir=path.parent, delete=False
    )
    temporary = Path(handle.name)
    try:
        try:
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        with handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        _assert_safe_target(path)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _snapshot_unlocked(
    content: str, *, owner_id: str | None = None, data_root: Path | None = None
) -> str:
    revision = content_hash(content)
    path = history_path(revision, owner_id=owner_id, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_target(path)
    if not path.exists():
        _atomic_write_unlocked(path, content)
    return revision


def _document(path: Path) -> LifeDocument:
    _assert_safe_target(path)
    content = _decode_file(path)
    return LifeDocument(path=path, content=content, revision=content_hash(content))


def bootstrap(
    *,
    owner_id: str | None = None,
    data_root: Path | None = None,
    template_path: Path | None = None,
) -> LifeDocument:
    """Create a private runtime copy once; never replace an existing user's memory."""
    path = canonical_path(owner_id=owner_id, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_target(path)
    with _lock_for(path):
        _assert_safe_target(path)
        if not path.exists():
            source = Path(template_path) if template_path is not None else resource_path("LIFE.md")
            content = _validate_content(_decode_file(source))
            _atomic_write_unlocked(path, content)
        document = _document(path)
        _snapshot_unlocked(document.content, owner_id=owner_id, data_root=data_root)
        return document


def read_document(
    *, owner_id: str | None = None, data_root: Path | None = None
) -> LifeDocument:
    return bootstrap(owner_id=owner_id, data_root=data_root)


def prepare_proposal(current: str, proposed: str) -> PreparedLifeProposal:
    content = _validate_content(proposed)
    base_hash = content_hash(current)
    target_hash = content_hash(content)
    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"LIFE.md@{base_hash[:12]}",
            tofile=f"LIFE.md@{target_hash[:12]}",
        )
    )
    return PreparedLifeProposal(content, base_hash, target_hash, diff)


def apply_exact(
    content: str,
    *,
    base_hash: str,
    target_hash: str,
    owner_id: str | None = None,
    data_root: Path | None = None,
) -> LifeDocument:
    """Apply bytes bound to exact base/target hashes, with lock, snapshots, and atomic replace."""
    _validate_content(content)
    if not _HASH_RX.fullmatch(base_hash or "") or not _HASH_RX.fullmatch(target_hash or ""):
        raise LifeValidationError("Invalid LIFE proposal hashes.")
    if content_hash(content) != target_hash:
        raise LifeConflictError("The approved LIFE.md content does not match its target hash.")

    path = canonical_path(owner_id=owner_id, data_root=data_root)
    bootstrap(owner_id=owner_id, data_root=data_root)
    with _lock_for(path):
        current = _document(path)
        if current.revision != base_hash:
            raise LifeConflictError("LIFE.md changed since this proposal was prepared.")
        _snapshot_unlocked(current.content, owner_id=owner_id, data_root=data_root)
        _snapshot_unlocked(content, owner_id=owner_id, data_root=data_root)
        _atomic_write_unlocked(path, content)
        return _document(path)


def rollback_exact(
    revision: str,
    *,
    base_hash: str,
    owner_id: str | None = None,
    data_root: Path | None = None,
) -> LifeDocument:
    snapshot = history_path(revision, owner_id=owner_id, data_root=data_root)
    _assert_safe_target(snapshot)
    if not snapshot.is_file():
        raise LifeValidationError("That LIFE.md revision does not exist.")
    content = _decode_file(snapshot)
    return apply_exact(
        content,
        base_hash=base_hash,
        target_hash=content_hash(content),
        owner_id=owner_id,
        data_root=data_root,
    )


def _proposal_dict(row) -> dict:
    return {
        "id": str(row.id),
        "base_hash": row.base_hash,
        "target_hash": row.target_hash,
        "content": row.proposed_content,
        "diff": row.diff or "",
        "reason": row.reason or "",
        "source_type": row.source_type,
        "source_id": row.source_id,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def _owner_filter(model, owner_id: str | None):
    return model.owner_id.is_(None) if owner_id is None else model.owner_id == owner_id


async def document_for_current_user() -> dict:
    from backend.features import team

    owner_id = await team.current_owner_id()
    document = read_document(owner_id=owner_id)
    return {
        "content": document.content,
        "revision": document.revision,
        "location": str(document.path),
    }


async def propose_for_owner(
    proposed_content: str,
    *,
    owner_id: str | None,
    reason: str = "",
    source_type: str,
    source_id: str | None = None,
    lifetime: datetime.timedelta = datetime.timedelta(days=7),
) -> dict:
    """Create a pending exact proposal for an already-authenticated/snapshotted owner.

    Background workers must call this function with the owner stored on their run. They must never
    discover an owner through the desktop's ambient keychain identity.
    """
    if source_type not in {"user", "agent", "rollback", "system"}:
        raise LifeValidationError("Invalid LIFE proposal source.")
    current = read_document(owner_id=owner_id)
    prepared = prepare_proposal(current.content, proposed_content)
    if prepared.base_hash == prepared.target_hash:
        raise LifeValidationError("The proposed LIFE.md has no changes.")

    from backend.core.database import get_sessionmaker
    from backend.core.models import LifeProposal

    now = datetime.datetime.now(datetime.timezone.utc)
    row = LifeProposal(
        owner_id=owner_id,
        base_hash=prepared.base_hash,
        target_hash=prepared.target_hash,
        proposed_content=prepared.content,
        diff=prepared.diff,
        reason=(reason or "").strip()[:500],
        source_type=source_type,
        source_id=(source_id or "").strip()[:64] or None,
        status="pending",
        expires_at=now + lifetime,
    )
    async with get_sessionmaker()() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _proposal_dict(row)


async def propose_for_current_user(proposed_content: str, *, reason: str = "") -> dict:
    from backend.features import team

    return await propose_for_owner(
        proposed_content,
        owner_id=await team.current_owner_id(),
        reason=reason,
        source_type="user",
        lifetime=datetime.timedelta(days=30),
    )


async def _scoped_proposal(session, proposal_id: str, owner_id: str | None, *, lock: bool = False):
    from backend.core.models import LifeProposal

    try:
        parsed = uuid.UUID(proposal_id)
    except (ValueError, TypeError, AttributeError):
        return None
    statement = select(LifeProposal).where(
        LifeProposal.id == parsed,
        _owner_filter(LifeProposal, owner_id),
    )
    if lock:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def list_proposals_for_current_user(*, status: str | None = None) -> list[dict]:
    from backend.core.database import get_sessionmaker
    from backend.core.models import LifeProposal
    from backend.features import team

    owner_id = await team.current_owner_id()
    statement = select(LifeProposal).where(_owner_filter(LifeProposal, owner_id))
    if status:
        if status not in {"pending", "applying", "applied", "rejected", "expired", "apply_failed"}:
            raise LifeValidationError("Invalid LIFE proposal status.")
        statement = statement.where(LifeProposal.status == status)
    statement = statement.order_by(LifeProposal.created_at.desc()).limit(100)
    async with get_sessionmaker()() as session:
        rows = (await session.execute(statement)).scalars().all()
        return [_proposal_dict(row) for row in rows]


def _expired(row, now: datetime.datetime) -> bool:
    expiry = row.expires_at
    if expiry is None:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=datetime.timezone.utc)
    return expiry <= now


async def approve_for_current_user(proposal_id: str, *, target_hash: str) -> dict | None:
    """Apply one exact proposal after an interactive local owner approves its displayed digest."""
    from backend.core.database import get_sessionmaker
    from backend.core.models import LifeRevision
    from backend.features import team

    owner_id = await team.current_owner_id()
    now = datetime.datetime.now(datetime.timezone.utc)
    async with get_sessionmaker()() as session:
        row = await _scoped_proposal(session, proposal_id, owner_id, lock=True)
        if row is None:
            return None
        if not _HASH_RX.fullmatch(target_hash or "") or row.target_hash != target_hash:
            raise LifeConflictError("Approval does not match the displayed LIFE.md proposal.")

        current = read_document(owner_id=owner_id)
        if row.status == "applied" and current.revision == row.target_hash:
            return _proposal_dict(row)
        if row.status not in {"pending", "applying"}:
            raise LifeConflictError(f"This LIFE.md proposal is already {row.status}.")
        if _expired(row, now):
            row.status = "expired"
            row.decided_at = now
            await session.commit()
            raise LifeConflictError("This LIFE.md proposal has expired.")

        row.status = "applying"
        row.decided_by = owner_id or "solo"
        row.decided_at = now
        row.error = None
        await session.commit()

        try:
            if current.revision == row.target_hash:
                applied = current  # reconcile a crash after rename but before the DB commit
            else:
                applied = apply_exact(
                    row.proposed_content,
                    base_hash=row.base_hash,
                    target_hash=row.target_hash,
                    owner_id=owner_id,
                )
        except LifeError as exc:
            row.status = "apply_failed"
            row.error = str(exc)[:300]
            await session.commit()
            raise

        row.status = "applied"
        row.applied_at = datetime.datetime.now(datetime.timezone.utc)
        row.error = None
        exists = (await session.execute(
            select(LifeRevision.id).where(LifeRevision.proposal_id == row.id)
        )).scalar_one_or_none()
        if exists is None:
            session.add(LifeRevision(
                owner_id=owner_id,
                content_hash=applied.revision,
                previous_hash=row.base_hash,
                proposal_id=row.id,
                source_type=row.source_type,
            ))
        await session.commit()
        await session.refresh(row)
        return _proposal_dict(row)


async def reject_for_current_user(
    proposal_id: str, *, target_hash: str, reason: str = ""
) -> dict | None:
    from backend.core.database import get_sessionmaker
    from backend.features import team

    owner_id = await team.current_owner_id()
    async with get_sessionmaker()() as session:
        row = await _scoped_proposal(session, proposal_id, owner_id, lock=True)
        if row is None:
            return None
        if row.target_hash != target_hash:
            raise LifeConflictError("Decision does not match the displayed LIFE.md proposal.")
        if row.status != "pending":
            raise LifeConflictError(f"This LIFE.md proposal is already {row.status}.")
        row.status = "rejected"
        row.decided_by = owner_id or "solo"
        row.decided_at = datetime.datetime.now(datetime.timezone.utc)
        row.error = (reason or "").strip()[:300] or None
        await session.commit()
        await session.refresh(row)
        return _proposal_dict(row)


def _history_for_owner(owner_id: str | None) -> list[dict]:
    current = read_document(owner_id=owner_id)
    items: list[dict] = []
    directory = _history_dir(owner_id=owner_id)
    for path in directory.glob("*.md"):
        revision = path.stem
        if not _HASH_RX.fullmatch(revision) or path.is_symlink() or not path.is_file():
            continue
        try:
            stat_result = path.stat()
        except OSError:
            continue
        items.append({
            "revision": revision,
            "current": revision == current.revision,
            "size": stat_result.st_size,
            "created_at": datetime.datetime.fromtimestamp(
                stat_result.st_mtime, tz=datetime.timezone.utc
            ).isoformat(),
        })
    return sorted(items, key=lambda item: item["created_at"], reverse=True)[:100]


async def history_for_current_user() -> list[dict]:
    from backend.features import team

    return _history_for_owner(await team.current_owner_id())


async def propose_rollback_for_current_user(revision: str, *, reason: str = "") -> dict:
    from backend.features import team

    owner_id = await team.current_owner_id()
    snapshot = history_path(revision, owner_id=owner_id)
    _assert_safe_target(snapshot)
    if not snapshot.is_file():
        raise LifeValidationError("That LIFE.md revision does not exist.")
    return await propose_for_owner(
        _decode_file(snapshot),
        owner_id=owner_id,
        reason=reason or f"Restore LIFE.md revision {revision[:12]}",
        source_type="rollback",
        source_id=revision,
        lifetime=datetime.timedelta(days=30),
    )
