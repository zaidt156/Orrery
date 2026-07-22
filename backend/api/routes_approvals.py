"""Tool-approval decisions for the central Chat/Automations gate (features/approvals.py)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.features import approvals

router = APIRouter()


class ApprovalDecision(BaseModel):
    approve: bool
    remember: bool = False


@router.get("/tool-approvals")
async def tool_approvals_pending() -> dict:
    return {"approvals": await approvals.list_pending()}


@router.post("/tool-approvals/{approval_id}/decide")
async def tool_approval_decide(approval_id: str, body: ApprovalDecision) -> dict:
    result = await approvals.decide(approval_id, approve=body.approve, remember=body.remember)
    if result is None:
        raise HTTPException(status_code=404, detail="Approval not found (it may have expired).")
    return result
