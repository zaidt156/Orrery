"""/skills API routes (split from the api.py monolith; same behavior)."""

from fastapi import APIRouter, HTTPException

from backend.api.schemas import *  # noqa: F401,F403 — request models
from backend.features import skills, team

router = APIRouter()

@router.get("/skills")
async def skills_list() -> dict:
    return {"skills": await skills.list_user_skills(), "builtin": skills.list_builtin()}

@router.post("/skills")
async def skill_create(body: SkillBody) -> dict:
    if not body.body.strip():
        raise HTTPException(status_code=400, detail="Skill content is required")
    return await skills.create_user_skill(body.name, body.body, body.triggers, body.always, body.enabled)

@router.post("/skills/upload")
async def skill_upload(body: SkillUpload) -> dict:
    parsed = skills.parse_skill_markdown(body.markdown, body.name or "Skill")
    if not parsed["body"].strip():
        raise HTTPException(status_code=400, detail="The uploaded file has no skill content")
    return await skills.create_user_skill(parsed["name"], parsed["body"], parsed["triggers"], parsed["always"])

@router.post("/skills/generate")
async def skill_generate(body: SkillGenerate) -> dict:
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Describe the skill you want")
    if not body.model:
        raise HTTPException(status_code=400, detail="Pick a model to generate the skill")
    try:
        return await skills.generate_user_skill(body.model, body.description)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e)[:200])

@router.patch("/skills/{sid}")
async def skill_update(sid: str, body: SkillUpdate) -> dict:
    if not await skills.update_user_skill(sid, **body.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True}

@router.delete("/skills/{sid}")
async def skill_delete(sid: str) -> dict:
    if not await skills.delete_user_skill(sid):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": True}

@router.post("/skills/{sid}/approve")
async def skill_approve(sid: str) -> dict:
    if not await team.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required.")
    if not await skills.set_skill_status(sid, "approved"):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"approved": True}

# --- MCP servers (config + storage; tool execution wired in a later step) ---
