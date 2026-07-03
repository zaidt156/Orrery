"""Request/response models for the API routes (split from api.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

class NewConversation(BaseModel):
    model: str
    system_prompt: str | None = None
    effort: str | None = None
    # any size the UI offers; clamped server-side to the chosen model's real maximum
    context_window: int = Field(default=1_000_000, ge=4_096, le=2_000_000)
    project_id: str | None = None


class UpdateConversation(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    effort: str | None = None
    context_window: int | None = Field(default=None, ge=4_096, le=2_000_000)
    project_id: str | None = None


class Attachment(BaseModel):
    name: str
    mime: str = ""
    kind: str  # image | text | pdf
    content: str  # data URL (image) or file text


class NewMessage(BaseModel):
    content: str
    attachments: list[Attachment] = []
    collection_id: str | None = None


class ProviderKey(BaseModel):
    key: str


class PlanConnection(BaseModel):
    acknowledged: bool = False


class SetActive(BaseModel):
    id: str
    label: str = ""
    provider: str = ""
    active: bool


class LocalModelAction(BaseModel):
    model: str
    active: bool | None = None


class NewCustomModel(BaseModel):
    label: str
    base_url: str
    model: str
    key: str = ""


class Branding(BaseModel):
    enabled: bool = False
    name: str = Field(default="", max_length=80)
    tagline: str = Field(default="", max_length=160)
    details: str = Field(default="", max_length=280)
    logo: str = Field(default="", max_length=1_500_000)

    @field_validator("logo")
    @classmethod
    def validate_logo(cls, value: str) -> str:
        if not value:
            return ""
        allowed = (
            "data:image/png;base64,",
            "data:image/jpeg;base64,",
            "data:image/webp;base64,",
            "data:image/gif;base64,",
        )
        if not value.startswith(allowed):
            raise ValueError("Logo must be an uploaded PNG, JPEG, WebP, or GIF image")
        return value


class SpendCap(BaseModel):
    enabled: bool = False
    limit_usd: float = Field(default=10.0, ge=0)
    period: Literal["hour", "day", "month", "all"] = "month"


class NewFeedback(BaseModel):
    category: Literal["bug", "idea", "praise", "general"] = "general"
    message: str
    contact: str = ""
    context: str = ""


class ProjectBody(BaseModel):
    name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=8000)


class NewConnection(BaseModel):
    name: str = ""
    url: str


class NewCollection(BaseModel):
    name: str = ""


class UploadDocs(BaseModel):
    files: list[Attachment] = []


class NewArtifact(BaseModel):
    html: str


class ReasoningBody(BaseModel):
    reasoning: dict = {}  # UI snapshot: thinking text, trace steps, outer card, summary, sources


class OntologyBody(BaseModel):
    name: str = ""
    description: str = ""


class OntologyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    connected: bool | None = None  # connect => used as standing context in every chat


class SkillBody(BaseModel):
    name: str = ""
    body: str = ""
    triggers: str = ""   # comma/newline separated phrases that trigger this skill
    always: bool = False  # apply on every turn
    enabled: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    body: str | None = None
    triggers: str | None = None
    always: bool | None = None
    enabled: bool | None = None


class SkillUpload(BaseModel):
    markdown: str = ""
    name: str = ""


class SkillGenerate(BaseModel):
    description: str = ""
    model: str = ""


class McpBody(BaseModel):
    name: str = ""
    transport: str = "stdio"  # stdio | http
    command: str = ""
    url: str = ""
    enabled: bool = False
    env: dict[str, str] = {}  # secret values -> keychain only; the API returns names, never values


class McpUpdate(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    url: str | None = None
    enabled: bool | None = None
    env: dict[str, str] | None = None  # replaces the server's env vars; {} clears them


class DefaultsBody(BaseModel):
    model: str = ""
    effort: str = ""  # "" (standard) | low | high | xhigh


class DatasetFileBody(BaseModel):
    name: str = ""
    filename: str = ""
    content: str = ""  # raw text for CSV/JSON, base64 for Excel
    workspace_id: str = ""


class DatasetApiBody(BaseModel):
    name: str = ""
    url: str = ""
    headers: dict[str, str] = {}  # auth headers -> keychain, never stored in the DB
    workspace_id: str = ""


class WorkspaceBody(BaseModel):
    name: str = ""


class DataModelBody(BaseModel):
    connection_id: str
    name: str = ""
    spec: dict = {}  # {"base": "orders", "joins": [{"table","left","right","type"}]}


class TransformsBody(BaseModel):
    transforms: list[dict] = []


class LayoutBody(BaseModel):
    order: list[int] = []


class EvaluateBody(BaseModel):
    models: list[str] = []  # extra candidate models (the current answer is always included)
    judge: str = ""


class AdoptBody(BaseModel):
    text: str
    model: str = ""


class DashboardCreate(BaseModel):
    model: str
    connection_ids: list[str] = []
    description: str = Field(default="", max_length=4000)


class DashboardRevise(BaseModel):
    model: str
    instruction: str = Field(default="", max_length=4000)


class AdminToken(BaseModel):
    token: str = ""
    current: str = ""


class AdminFlags(BaseModel):
    flags: dict = {}
    token: str = ""


class TeamSetup(BaseModel):
    name: str = ""


class TeamUnlock(BaseModel):
    key: str = ""


class TeamUserBody(BaseModel):
    name: str = ""
    role: str = "member"


class TeamUserUpdate(BaseModel):
    role: str | None = None
    disabled: bool | None = None


class DbConnection(BaseModel):
    url: str


class PrivacyMode(BaseModel):
    mode: Literal["off", "basic", "strict"]




class DatasetMongoBody(BaseModel):
    name: str = ""
    uri: str = ""          # mongodb:// URI -> keychain, never stored in the DB
    collection: str = ""
    workspace_id: str = ""
