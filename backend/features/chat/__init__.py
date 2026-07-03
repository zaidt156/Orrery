"""Chat feature package — the facade every caller imports (`from backend.features import chat`).

Modular-monolith layout (conventions.md): the public surface stays on this package while the
implementation lives in focused modules:

  conversations  CRUD + ownership + reasoning/attachment persistence
  retrieval      relevance-gated RAG gathering for turns
  persistence    assistant-reply persistence (incl. HTML→file conversion)
  generation     the plain streaming model call
  runs           detached background runs (survive the client navigating away)
  router         turn prep, task routes, and the stream_reply dispatcher

Cross-module calls go through module attributes (sibling.func) so each function has exactly one
patch point for tests and future extension.
"""
from backend.features.chat import conversations, generation, persistence, retrieval, router, runs  # noqa: F401

# conversation CRUD + message metadata
from backend.features.chat.conversations import (  # noqa: F401
    attachment_text, can_access_conversation, create_conversation, delete_conversation,
    get_conversation, list_conversations, save_reasoning, update_conversation,
    _load_reasoning, _owned_by,
)

# streaming entry points + turn machinery
from backend.features.chat.router import (  # noqa: F401
    regenerate, stream_code_image, stream_reply,
    _TurnContext, _conv_title, _deliver_docspec, _detect_formats, _is_indexable_attachment,
    _mcp_catalog, _model_history, _outer_summary_for_plan, _prepare_turn, _research_query,
    _route_file, _route_image, _route_model_reply, _route_project_create, _route_research,
)

# detached runs
from backend.features.chat.runs import (  # noqa: F401
    cancel_run, is_running, observe, resume, start_detached, _run_queues, _run_tasks,
)

# generation / persistence / retrieval internals used by tests and siblings
from backend.features.chat.generation import _generate  # noqa: F401
from backend.features.chat.persistence import _html_artifact_from_reply, _persist_assistant  # noqa: F401
from backend.features.chat.retrieval import _gather_rag, _rag_context, _vague_query  # noqa: F401

# content/window helpers kept importable from the package (tests + api use them via chat.*)
from backend.features.chat_context import (  # noqa: F401
    DEFAULT_CONTEXT_WINDOW, _build_user_content, _content_token_estimate, _db_content,
    _effective_context_window, _history_text, _latest_user_text, _limit_messages,
    _message_artifacts, _title_from, _wants_high_effort,
)

# module objects reached through the package (tests patch e.g. chat.ai.stream_chat, chat.sandbox.image_ready)
from backend.core.database import get_sessionmaker  # noqa: F401
from backend.features import filegen, route_telemetry, sandbox, taskbrain, team  # noqa: F401
from backend.features import projects as project_store  # noqa: F401
from backend.providers import ai  # noqa: F401
