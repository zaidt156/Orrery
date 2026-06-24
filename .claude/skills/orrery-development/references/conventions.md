# Orrery Conventions

Read this before adding any new unit of functionality. It covers how code is
written, the one repeatable pattern for adding a workflow node / dashboard widget
type / agent capability, how errors are handled, how configuration and secrets
are reached, and what must be tested. For *what* the pieces are, see
`architecture.md`; for the rules that override everything, see `security.md`.

The governing idea: **consistency across sessions beats local cleverness.** When
in doubt, match what already exists rather than introducing a new shape.

## Python style

- **Target Python 3.12.** Use modern syntax (`X | None`, `match`, structural
  typing) freely.
- **Type-hint everything** that crosses a module boundary — function signatures,
  public attributes, returned shapes. Hints are documentation that does not rot.
- **Async by default in the request and worker paths.** FastAPI routes, the AI
  layer, the automation engine, and the agent loop are `async`. Do not block the
  event loop; push genuinely blocking work to a thread or a subprocess.
- **Formatting and linting:** `ruff format` + `ruff check`. No hand-formatting
  arguments about it; run the tool.
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes,
  `UPPER_SNAKE` for module constants. Names say what a thing is for, not what
  type it is (`connection_id`, not `cid`).
- **Comments: short over long.** Keep brief one-line explanation comments where
  they earn their place (a non-obvious "why", a security note like "masked, never
  the raw key"). Do **not** write long multi-line comment blocks or verbose module
  docstrings — the DEVLOG carries the narrative. A concise one-line docstring on a
  public function is fine when it adds something the name doesn't.

## Where code goes

Each module owns one concern (`architecture.md` has the tree). Cross-cutting
helpers exist **once** and are imported, never re-implemented per tab:

- secrets / keychain access and redaction → `backend/security/secrets.py`
- account/key auth modes and official subscription route status → `backend/providers/accounts.py`
- connection resolution (which database, with which credentials) → `backend/core/database.py`
- the model routing layer → `backend/providers/ai.py`
- the shared tool registry → `backend/tools/registry.py`

If you find yourself copying one of these into a feature module, stop and import
the shared one instead. Forking a shared helper per tab is how scope enforcement
and redaction silently drift out of sync.

## The registry pattern (nodes, widgets, agent tools)

Workflow nodes, dashboard widget types, and agent capabilities are all added the
same way: **write one class, register it, and the UI/engine discovers it.** Never
add a feature by branching on a type string scattered across the codebase.

A registered unit has:

1. A **stable string key** (`"llm_prompt"`, `"bar"`, `"db_query"`) — persisted in
   saved workflows/specs/scopes, so it must never change once shipped.
2. A **declared input/config schema** (Pydantic model) — what it accepts, used for
   validation *and* for the config panel the frontend renders.
3. An **`async execute(...)`** (or `render`/`run`) method — the behavior.
4. **Registration** via the registry's decorator so it is discoverable without
   editing a central switch.

### Adding a workflow node (the canonical example)

```python
# backend/automation/nodes.py
from backend.automation.registry import register_node, Node
from pydantic import BaseModel

class HttpRequestConfig(BaseModel):
    url: str
    method: str = "GET"
    # ... fields become the node's config-panel form

@register_node("http_request")          # stable key — never rename after ship
class HttpRequestNode(Node):
    label = "HTTP Request"
    category = "data"                    # triggers | ai | data | logic | code | tools
    config_model = HttpRequestConfig

    async def execute(self, inputs: dict, config: HttpRequestConfig) -> dict:
        # inputs carry upstream outputs; return this node's output dict.
        # Honor timeouts/limits; treat any external response as untrusted data.
        ...
```

That is the whole change — no edits to the engine, the API, or a master list. The
engine enumerates the registry; the frontend reads each node's `label`,
`category`, and `config_model` to build the palette and config panel. Dashboard
widget types (`backend/dashboards.py`) and agent tools
(`backend/tools/registry.py`) follow the identical shape with `render`/`run`
instead of `execute`.

### Agent tools carry their own scope check

Every agent tool, in addition to the above, **enforces scope inside the tool**
(`security.md` §4) — the agent's reasoning is never trusted to police itself:

```python
@register_tool("db_write")
class DbWriteTool(Tool):
    requires = Scope(tables="write", confirm_if="sensitive")
    async def run(self, args: DbWriteArgs, ctx: AgentContext) -> ToolResult:
        ctx.scope.assert_can_write(args.table)      # refuses out-of-scope here
        ctx.budget.charge(...)                       # counted, enforced in code
        # parameterized write only (security.md §2)
```

When you design a tool, ask: *"If the model asked this tool to do the worst
possible thing within its arguments, what stops it?"* The answer must be code in
the tool, not wording in a prompt.

## Database access conventions

- **Always parameterized.** Values go through SQLAlchemy bound parameters. Never
  f-string or concatenate user input, model output, or row data into SQL
  (`security.md` §2). There is no small safe exception.
- **Dynamic identifiers** (table/column names) are validated against a fetched
  allow-list of real schema names before use — never interpolated raw.
- **Read-only contexts** (table browser, dashboard queries, agent reads) use a
  read-only transaction/role, enforced at the connection layer — not by
  inspecting the SQL string (`security.md` §3).
- **Resolve the connection explicitly by id** in automation/agent contexts; never
  rely on an ambient default.
- Every query has a **statement timeout and a row cap**.

## Error handling

- **Fail explicitly over guessing.** This is a data tool; a plausible wrong number
  is worse than an honest error. If the AI cannot ground a query in the schema,
  it declines rather than inventing one.
- **Two audiences, two messages.** Users get a clear, safe message ("Couldn't
  reach the model provider"). Logs get the detail — but **sanitized**: provider
  errors and connection strings can carry secrets/request fragments; redact
  before logging or surfacing (`security.md` §1).
- **Never swallow security failures.** A scope refusal, a read-only violation, or
  a failed parameter binding is surfaced and logged, never silently downgraded to
  a "best effort" path.
- Workflow/agent steps record their own failure to `*_run_steps` so the debug
  view and activity feed show what happened; per-node policy decides stop /
  continue / retry-with-backoff.

## Configuration and secrets

- **Non-secret config** (ports, dev toggles, the local-dev DB URL) comes from
  `pydantic-settings` reading `.env` — see `backend/core/config.py`. `.env` is
  gitignored and is for the local dev container only.
- **Secrets** (provider keys, account tokens, the user's real DB password) are read from the OS
  keychain via `backend/security/secrets.py`/`backend/providers/accounts.py`, loaded only at point of use, never written to
  `.env`, logs, the database, or the frontend (`security.md` §1).
- Add new settings to the `Settings` model, not as scattered `os.getenv` calls.

## Frontend conventions

- **Plain-JS React + Vite.** No TypeScript. Components are small and dumb; all
  logic lives in Python.
- One **API client** module (`ui/src/lib/`) wraps fetch/SSE and attaches the
  session auth token to every call. Views never build raw URLs or re-implement
  streaming.
- The UI **never receives a secret** — only masked placeholders and keychain
  status. If a component needs a real key, the design is wrong.

## Testing

Tests exist to protect the dangerous areas first. For any change, cover:

- **SQL safety:** the query is parameterized; a hostile value cannot break out.
- **Read-only enforcement:** a write attempt in a read-only context is rejected by
  the transaction/role, not by string inspection.
- **Scope enforcement:** an agent tool refuses an out-of-scope table/operation and
  respects loop/spend/confidence limits and the stop signal.
- **Redaction:** secrets and PII do not appear in logs, prompts, or API responses.
- **Registry round-trip:** a registered node/widget/tool is discoverable and its
  config schema validates good input and rejects bad.

Use `pytest` with async support. A feature that touches secrets, SQL, scope, or
the code node does not ship without the matching test.

## And then: document it

After any change, append a `docs/history/DEVLOG.md` entry in plain words — what changed, why,
and what's next — newest at the bottom. See "The DEVLOG discipline" in `SKILL.md`.
This is part of finishing the work, not paperwork after it.
