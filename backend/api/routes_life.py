"""Local-owner API for LIFE.md review, proposals, decisions, history, and rollback."""

from fastapi import APIRouter, HTTPException, Query

from backend.api.schemas import LifeDecision, LifeProposalCreate, LifeRejection, LifeRollbackCreate
from backend.features import life

router = APIRouter()


def _raise_life_error(exc: life.LifeError) -> None:
    status = 409 if isinstance(exc, life.LifeConflictError) else 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/life")
async def life_read() -> dict:
    try:
        return await life.document_for_current_user()
    except life.LifeError as exc:
        _raise_life_error(exc)


@router.post("/life/onboarded")
async def life_mark_onboarded() -> dict:
    return await life.mark_onboarded_for_current_user()


@router.get("/life/history")
async def life_history() -> dict:
    try:
        return {"revisions": await life.history_for_current_user()}
    except life.LifeError as exc:
        _raise_life_error(exc)


@router.get("/life/proposals")
async def life_proposals(status: str | None = Query(default=None)) -> dict:
    try:
        return {"proposals": await life.list_proposals_for_current_user(status=status)}
    except life.LifeError as exc:
        _raise_life_error(exc)


@router.post("/life/proposals", status_code=201)
async def life_propose(body: LifeProposalCreate) -> dict:
    try:
        return await life.propose_for_current_user(body.content, reason=body.reason)
    except life.LifeError as exc:
        _raise_life_error(exc)


@router.post("/life/proposals/{proposal_id}/approve")
async def life_approve(proposal_id: str, body: LifeDecision) -> dict:
    try:
        proposal = await life.approve_for_current_user(proposal_id, target_hash=body.target_hash)
    except life.LifeError as exc:
        _raise_life_error(exc)
    if proposal is None:
        raise HTTPException(status_code=404, detail="LIFE.md proposal not found")
    return proposal


@router.post("/life/proposals/{proposal_id}/reject")
async def life_reject(proposal_id: str, body: LifeRejection) -> dict:
    try:
        proposal = await life.reject_for_current_user(
            proposal_id, target_hash=body.target_hash, reason=body.reason
        )
    except life.LifeError as exc:
        _raise_life_error(exc)
    if proposal is None:
        raise HTTPException(status_code=404, detail="LIFE.md proposal not found")
    return proposal


@router.post("/life/rollback-proposals", status_code=201)
async def life_propose_rollback(body: LifeRollbackCreate) -> dict:
    try:
        return await life.propose_rollback_for_current_user(body.revision, reason=body.reason)
    except life.LifeError as exc:
        _raise_life_error(exc)
