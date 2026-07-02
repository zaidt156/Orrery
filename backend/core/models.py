from __future__ import annotations

import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, Computed, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
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
    # generated keyword-search column (Postgres full-text) for hybrid retrieval
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('english', content)", persisted=True))

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
