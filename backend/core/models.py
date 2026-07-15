from __future__ import annotations

import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, Computed, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBED_DIM = 384  # BAAI/bge-small-en-v1.5


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    model: Mapped[str] = mapped_column(String(120))
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    effort: Mapped[str | None] = mapped_column(String(10), nullable=True)  # low|medium|high|xhigh
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # per-chat RAG collection holding this chat's own uploaded attachments, so they stay retrievable
    # no matter how long the conversation grows (created lazily on the first attachment)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # team mode: which TeamUser owns this chat (null in single-user mode); chats are private per user
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    project: Mapped["Project | None"] = relationship(back_populates="conversations")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # RAG collection holding the project's uploaded files; chats in the project answer from it.
    collection_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # team mode: which TeamUser owns this project (null in single-user mode); projects are private per user
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)  # what the bubble shows (text + a 📎 note)
    # the full text the model should keep seeing on later turns (file/PDF text inlined);
    # null for plain messages → history falls back to `content`
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON metadata for trusted, locally rendered artifacts such as sanitized SVG images.
    artifacts: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON snapshot of the reasoning panel (live thinking + trace steps + sources) so it survives reloads.
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Message versioning (Claude/GPT-style ‹ ›): regenerating a reply or editing/resubmitting a prompt
    # creates a SIBLING (same parent_id) instead of replacing or appending a duplicate. `active` marks
    # which sibling is on the currently-viewed path — exactly one active sibling per parent. History for
    # the model and the loaded conversation both follow the active path from root to leaf; inactive
    # siblings (and their subtrees) are kept so the ‹ › switcher can bring them back.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class CustomModel(Base):
    __tablename__ = "custom_models"

    # any OpenAI-compatible endpoint (Mistral, DeepSeek, Qwen, Kimi, GLM, OpenRouter,
    # local vLLM…). The API key is a secret → keychain under "key:custom:<id>", never here.
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(400))
    model: Mapped[str] = mapped_column(String(200))  # upstream model id, e.g. "qwen-max"
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActiveModel(Base):
    __tablename__ = "active_models"

    # the curated set the user turned on; Chat's model menu shows only these
    model_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    label: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    # small non-secret app config (e.g. branding, spend cap) as JSON text, keyed by name
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    # one row per API-key model call, so spend over any window (hour/day/month/all) is a SUM
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(160))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)


class Task(Base):
    __tablename__ = "tasks"

    # Unified "Task Brain" ledger : one observable row per background unit of work —
    # detached chat generations, queued jobs, and automations — so the user can see what's running,
    # resume it, or cancel it. Survives navigation; orphaned 'running' rows are reconciled on boot.
    __table_args__ = (
        CheckConstraint("kind IN ('chat', 'job', 'automation')", name="ck_tasks_kind"),
        CheckConstraint(
            "status IN ('running', 'queued', 'done', 'failed', 'canceled', 'interrupted')",
            name="ck_tasks_status",
        ),
        Index("ix_tasks_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="running")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # error / short note, sanitized
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRouteEvent(Base):
    __tablename__ = "task_route_events"

    # Durable route telemetry for production hardening. These rows intentionally store capability
    # decisions and sanitized outcomes only; they never store the user's prompt or generated content.
    __table_args__ = (
        CheckConstraint("route IN ('chat', 'file', 'image', 'audio', 'project')", name="ck_task_route_events_route"),
        CheckConstraint(
            "output_mode IN ('chat', 'file', 'artifact', 'audio')",
            name="ck_task_route_events_output_mode",
        ),
        CheckConstraint(
            "sandbox_policy IN ('none', 'preferred', 'required')",
            name="ck_task_route_events_sandbox_policy",
        ),
        CheckConstraint(
            "outcome IN ("
            "'planned', 'completed', 'failed', 'unavailable', "
            "'sandbox_success', 'sandbox_fallback', 'sandbox_failed', "
            "'deterministic_success', 'deterministic_failed'"
            ")",
            name="ck_task_route_events_outcome",
        ),
        Index("ix_task_route_events_route_created", "route", "created_at"),
        Index("ix_task_route_events_outcome_created", "outcome", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    route: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(80))
    output_mode: Mapped[str] = mapped_column(String(20))
    skills: Mapped[str] = mapped_column(String(300), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    sandbox_policy: Mapped[str] = mapped_column(String(20), default="none")
    outcome: Mapped[str] = mapped_column(String(40), default="planned")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    # in-app feedback; stored in the user's own database (local-first). Forwarding to a
    # central collector is an explicit, separate step the product owner configures.
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    category: Mapped[str] = mapped_column(String(40), default="general")  # bug | idea | praise | general
    message: Mapped[str] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)  # optional email
    context: Mapped[str | None] = mapped_column(Text, nullable=True)  # optional app context (tab, model)


class DataConnection(Base):
    __tablename__ = "data_connections"

    # metadata only — the connection string (a secret) lives in the keychain under "conn:<id>"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    display: Mapped[str] = mapped_column(String(300))  # redacted host:port/db, no password
    # postgres = a user database; datasets = a workspace of imported CSV/API tables, scoped to its
    # own schema (db_schema) so app tables (chats etc.) are never exposed to queries.
    kind: Mapped[str] = mapped_column(String(20), default="postgres")
    db_schema: Mapped[str | None] = mapped_column(String(80), nullable=True)  # datasets workspaces only
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workflow(Base):
    """A fixed-recipe automation: a DAG of registered nodes saved as JSON, versioned on save.

    spec: {"nodes": [{"id","type","config",{"position"}}], "edges": [{"source","target"}]}.
    Execution runs as a durable Procrastinate job; every node's input/output lands in
    workflow_run_steps to power the run-debug view (architecture.md §Automations)."""
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec: Mapped[str] = mapped_column(Text, default="{}")
    history: Mapped[str | None] = mapped_column(Text, nullable=True)  # spec snapshots (rollback)
    enabled: Mapped[bool] = mapped_column(default=True)
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)  # cron text (wired later)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|done|failed|canceled
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowRunStep(Base):
    __tablename__ = "workflow_run_steps"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(String(80))
    node_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12), default="done")  # done|failed|skipped
    input: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON, truncated
    output: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON, truncated
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataModel(Base):
    """A user-defined relationship model: a base table joined to related tables on key columns
    (BI-style 'connect your tables'). Stored as a JSON spec; rendered to validated SQL on use."""
    __tablename__ = "data_models"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(120))
    spec: Mapped[str] = mapped_column(Text)  # {"base": "orders", "joins": [{table,left,right,type}]}
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Dataset(Base):
    """An imported data source (uploaded CSV/Excel file or a REST API endpoint) materialized as a
    table in the orrery_datasets schema — queryable by dashboards like any database table (BI-style).
    API datasets remember their URL so they can be refreshed; header secrets live in the keychain."""
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    table_name: Mapped[str] = mapped_column(String(80), unique=True)  # ds_<slug> inside its schema
    kind: Mapped[str] = mapped_column(String(10))                     # file | api
    db_schema: Mapped[str] = mapped_column(String(80), default="orrery_datasets")  # workspace schema
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)  # filename or URL (no secrets)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Dashboard(Base):
    """An AI-designed dashboard: the model wrote the SQL and picked the charts; Orrery stores the
    result as a spec and refreshes it by re-running the saved read-only SQL — no model call on reuse.

    spec JSON: {"widgets": [{"title", "type" (stat|line|bar|pie|table), "sql", "x", "y"}]}.
    Every revision snapshots the previous spec into history so a bad AI edit rolls back in one click.
    """
    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # the user's plain-words ask
    connection_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))  # which data connection it queries
    model: Mapped[str] = mapped_column(String(120))    # authoring model (revisions may change it)
    spec: Mapped[str] = mapped_column(Text)            # JSON widget spec (see docstring)
    history: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of previous specs
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # team mode: private per user
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    embed_model: Mapped[str] = mapped_column(String(120))
    # "collection" = a Data-tab document set; "ontology" = a reusable knowledge base shown in the
    # Ontology tab. "connected" ontologies are automatically used as context in every chat.
    kind: Mapped[str] = mapped_column(String(20), default="collection")
    connected: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(300))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    # generated keyword-search column (Postgres full-text) for hybrid retrieval; 'simple' (not
    # 'english') keeps it language-neutral so non-English terms match (existing DBs: migration 0008)
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True))

    collection: Mapped["Collection"] = relationship(back_populates="chunks")

    __table_args__ = (Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),)


class McpServer(Base):
    """A Model Context Protocol server the user connects as a tool/context source (configured in the UI).

    Config + storage only at this stage; actual tool execution is wired in a later step. Treat any
    connected server's output as untrusted, and require explicit per-server opt-in (enabled).
    """
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    transport: Mapped[str] = mapped_column(String(20), default="stdio")  # stdio | http
    command: Mapped[str | None] = mapped_column(Text, nullable=True)     # for stdio: the launch command
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # for http/sse: the endpoint
    enabled: Mapped[bool] = mapped_column(default=False)                 # explicit opt-in
    tools: Mapped[str | None] = mapped_column(Text, nullable=True)       # cached tool catalog (JSON)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)        # team: who added it
    status: Mapped[str] = mapped_column(String(12), default="approved")  # approved | pending (team approval)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSkill(Base):
    """A user-authored skill playbook (like the built-in skills/*.md, but created/edited in the UI)."""
    __tablename__ = "user_skills"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    triggers: Mapped[str] = mapped_column(Text, default="")  # comma/newline separated phrases
    body: Mapped[str] = mapped_column(Text)
    always: Mapped[bool] = mapped_column(default=False)       # apply on every turn
    enabled: Mapped[bool] = mapped_column(default=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)        # team: who authored it
    status: Mapped[str] = mapped_column(String(12), default="approved")  # approved | pending (team approval)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LifeProposal(Base):
    """An immutable candidate change to one owner's canonical LIFE.md.

    The full proposed bytes are stored in the user's own database so an approval is bound to exact
    content. Application logs and audit events must use hashes/metadata only, never this field.
    """

    __tablename__ = "life_proposals"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('user', 'agent', 'rollback', 'system')",
            name="ck_life_proposals_source_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'applying', 'applied', 'rejected', 'expired', 'apply_failed')",
            name="ck_life_proposals_status",
        ),
        Index("ix_life_proposals_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    base_hash: Mapped[str] = mapped_column(String(64))
    target_hash: Mapped[str] = mapped_column(String(64))
    proposed_content: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(String(500), default="")
    source_type: Mapped[str] = mapped_column(String(20), default="user")
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifeRevision(Base):
    """Metadata pointer for a content-addressed LIFE.md snapshot on local disk."""

    __tablename__ = "life_revisions"
    __table_args__ = (Index("ix_life_revisions_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("life_proposals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), default="proposal")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Agent(Base):
    """Owner-scoped agent identity; executable configuration lives in immutable AgentVersion rows."""

    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_agents_status"),
        Index("ix_agents_owner_updated", "owner_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentVersion(Base):
    """Immutable, complete execution snapshot created on every agent edit."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        Index("ix_agent_versions_agent_created", "agent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[str] = mapped_column(Text)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(36), default="solo")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentSchedule(Base):
    __tablename__ = "agent_schedules"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_schedules_agent"),
        CheckConstraint("misfire_policy IN ('skip', 'coalesce')", name="ck_agent_schedules_misfire"),
        CheckConstraint(
            "concurrency_policy IN ('forbid', 'queue', 'replace')",
            name="ck_agent_schedules_concurrency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cron: Mapped[str] = mapped_column(String(120), default="0 9 * * *")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    misfire_policy: Mapped[str] = mapped_column(String(12), default="coalesce")
    concurrency_policy: Mapped[str] = mapped_column(String(12), default="forbid")
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_fire_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_fire_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('manual', 'schedule', 'api', 'slack', 'gmail')",
            name="ck_agent_runs_trigger_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'succeeded', 'failed', "
            "'cancelled', 'interrupted')",
            name="ck_agent_runs_status",
        ),
        Index("ix_agent_runs_agent_created", "agent_id", "created_at"),
        Index("ix_agent_runs_owner_status", "owner_id", "status"),
        Index("ix_agent_runs_idempotency", "agent_id", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(16))
    trigger_principal: Mapped[str] = mapped_column(String(200), default="local-owner")
    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    input_digest: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    config_snapshot: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    usage: Mapped[str] = mapped_column(Text, default="{}")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('system', 'model', 'tool', 'approval', 'memory')",
            name="ck_agent_run_steps_kind",
        ),
        Index("ix_agent_run_steps_run_created", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="done")
    tool_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(24), nullable=True)
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentApproval(Base):
    __tablename__ = "agent_approvals"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'expired')", name="ck_agent_approvals_status"),
        Index("ix_agent_approvals_owner_status", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tool_key: Mapped[str] = mapped_column(String(80))
    risk: Mapped[str] = mapped_column(String(24))
    action_digest: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AgentApiCredential(Base):
    __tablename__ = "agent_api_credentials"
    __table_args__ = (Index("ix_agent_api_credentials_prefix", "prefix"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Integration key")
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(200), default="invoke,read")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentTriggerEvent(Base):
    __tablename__ = "agent_trigger_events"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uq_agent_trigger_events_source_event"),
        Index("ix_agent_trigger_events_agent_received", "agent_id", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(20))
    source_event_id: Mapped[str] = mapped_column(String(200))
    principal: Mapped[str] = mapped_column(String(200))
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="received")
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamUser(Base):
    """A member of a shared (team) Orrery, identified by an access key. Only present when team mode is on.

    The access key is a high-entropy secret shown once at creation; only its hash is stored here (never
    the plaintext, never logged — security.md §1). The *role* is the source of truth for privileges and
    lives in this row, not encoded in the key, so a key cannot be forged into admin.
    """
    __tablename__ = "team_users"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10), default="member")  # admin | member
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex of the key
    disabled: Mapped[bool] = mapped_column(default=False)  # revoked: locked out next launch
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
