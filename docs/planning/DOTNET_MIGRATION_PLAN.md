# Orrery → .NET Migration Plan

**Status:** planned, not started. **Goal:** port Orrery's backend from Python to .NET (C#) so it ships as a single cross-platform desktop app (Windows, macOS, Linux), **without rewriting the React UI** and **without weakening the security floor** (`security.md`).

This document is written to be executed later, in order, by someone who has read `SKILL.md`, `architecture.md`, `security.md`, and `conventions.md`. It mirrors the current module layout so each Python file has a named C# destination and an acceptance bar.

---

## 0. Read this first — the honest assessment

Before committing to the rewrite, know the trade-off:

- **The current stack is already mostly cross-platform.** FastAPI, React, litellm, SQLAlchemy/psycopg, Procrastinate, fastembed, and `pywebview` all run on Windows/macOS/Linux. The realistic gaps today are (a) **packaging** a clean single artifact per OS and (b) a few `pywebview`/keychain platform details. A "ship on Mac/Linux" goal could be reached by packaging the Python app per-OS (PyInstaller/Briefcase) — far less work than a language rewrite.
- **Reasons that justify going to .NET anyway:** one self-contained native binary per platform (no Python runtime to ship), static typing across the whole logic layer, lower memory/startup, a single toolchain (`dotnet`), and strong native desktop integration. If those are the actual goals, proceed.
- **The cut that makes this affordable:** Orrery already obeys *"React only paints the screen; all logic lives in the backend."* So we **keep the entire React frontend as-is** and only re-implement the backend language + desktop shell. The frontend talks to the same REST/SSE contract; it never learns the backend changed.

If after reading this the team still wants .NET, the plan below is the path.

---

## 1. Target architecture (1:1 with today)

| Layer | Today (Python) | Target (.NET) |
|---|---|---|
| Desktop window | `pywebview` | **Photino.NET** (lightweight native WebView2/WebKitGTK/Cocoa wrapper) loading the local ASP.NET URL — same pattern as today |
| API / server | FastAPI + uvicorn (localhost, SSE) | **ASP.NET Core Minimal APIs** on **Kestrel**, bound to 127.0.0.1; SSE via `IAsyncEnumerable<T>` + `text/event-stream` |
| Frontend | React + Vite (plain JS) | **unchanged** — built to `wwwroot`, served as static files, loaded by Photino |
| Model access | litellm | **Microsoft.Extensions.AI** (`IChatClient`) as the spine + **OpenAI .NET SDK** (with custom `BaseUrl`) for all OpenAI-compatible providers + dedicated clients for Anthropic/Gemini + CLI bridge for subscription routes |
| ORM | SQLAlchemy 2.0 (async) | **EF Core 9** + **Npgsql** provider (async) |
| DB driver | psycopg 3 (async) | **Npgsql** |
| Vectors | pgvector + `pgvector` py | **pgvector-dotnet** (`Pgvector`, `Pgvector.EntityFrameworkCore`) |
| Migrations | hand-rolled `create_all` + `ALTER` | **EF Core Migrations** |
| Job queue | Procrastinate (Postgres) | **Hangfire** + **Hangfire.PostgreSql** (durable, retries, cron); DB-change triggers via **Npgsql LISTEN/NOTIFY** |
| Secrets | `keyring` (OS keychain) | `ISecretStore` abstraction → **DPAPI** (Win) / **Keychain Services** (macOS) / **libsecret/Secret Service** (Linux), encrypted-file fallback |
| Embeddings | fastembed (ONNX) | **Microsoft.ML.OnnxRuntime** + **Microsoft.ML.Tokenizers**, same `BAAI/bge-small-en-v1.5`, dim 384 |
| PDF text | pypdf | **UglyToad.PdfPig** |
| PII redaction | regex (`privacy.py`) | direct C# regex port |
| HTTP | httpx | `HttpClient` / `IHttpClientFactory` |
| Config | pydantic-settings + `.env` | `Microsoft.Extensions.Configuration` + `appsettings.json` + env vars + **`DotNetEnv`** for dev `.env` |
| Tests | pytest | **xUnit** + **Testcontainers (Postgres)** for DB-backed tests |
| Packaging | PyInstaller | `dotnet publish` self-contained single-file per RID |

**Runtime target:** .NET 9 (LTS-track), C# 13. **RIDs:** `win-x64`, `osx-arm64`, `osx-x64`, `linux-x64`.

Postgres stays external (Docker for dev, user-provided in prod) — unchanged. pgvector extension still enabled by migration.

---

## 2. Solution layout

```
Orrery.sln
 ├─ src/
 │   ├─ Orrery.Desktop/        # Photino host; picks free port, starts Kestrel, opens window with ?token=
 │   ├─ Orrery.Api/            # ASP.NET Core: endpoints, SSE, token middleware, static wwwroot (the React build)
 │   ├─ Orrery.Core/           # logic ported from backend/{providers,features,security}
 │   ├─ Orrery.Data/           # EF Core DbContext, entities, migrations, Npgsql/pgvector
 │   ├─ Orrery.Secrets/        # ISecretStore + per-OS implementations
 │   └─ Orrery.Jobs/           # Hangfire setup, workflow/agent jobs (later phases)
 ├─ tests/
 │   ├─ Orrery.Core.Tests/
 │   ├─ Orrery.Api.Tests/      # WebApplicationFactory
 │   └─ Orrery.Data.Tests/     # Testcontainers Postgres
 └─ ui/                        # unchanged React app → builds into Orrery.Api/wwwroot
```

Dependency direction: `Desktop → Api → Core → {Data, Secrets, Jobs}`. `Core` defines interfaces (`ISecretStore`, `IModelClient`, `IClock`); concrete adapters live at the edges (mirrors `conventions.md`: shared helpers exist once and are injected, never re-implemented per tab). Use built-in DI (`IServiceCollection`).

---

## 3. Module-by-module port map

Each current Python module under `backend/core`, `backend/providers`, `backend/features`, and `backend/security` maps to a C# home, with the acceptance bar = "same REST behavior + ported tests pass."

| Python module | C# destination | Notes / gotchas |
|---|---|---|
| `core/config.py` | `Orrery.Core/Config/Settings.cs` (Options pattern) | bind from `appsettings.json` + env; dev `.env` via DotNetEnv |
| `security/secrets.py` | `Orrery.Secrets/ISecretStore.cs` + `DpapiSecretStore`, `MacKeychainSecretStore`, `LibsecretSecretStore` | keep the `key:<provider>` / `custom:<id>` / `conn:<id>` / `account:anthropic:claude_plan` naming; `redact_url`, `mask_key`, `provider_key_status` port directly. **Never** return raw secret to UI (security.md §1). |
| `core/database.py` | `Orrery.Data/OrreryDbContext.cs` + `DbConnectionFactory` | EF Core; pooled `DbContextFactory`; `resolve_database_url` reads keychain then config |
| `core/models.py` | `Orrery.Data/Entities/*.cs` | Conversation, Message, CustomModel, ActiveModel, DataConnection, Collection, Chunk. `Chunk.Embedding` → `Pgvector.Vector(384)`; `tsv` generated column + GIN index via raw SQL in migration; keep `context`, `effort`, `context_window` columns |
| `core/migrations.py` | EF Core Migrations + a startup `MigrateAsync()` | replace `create_all`+`ALTER`; first migration enables `CREATE EXTENSION vector`, creates tables, the `tsv` generated column + GIN index, and Hangfire schema; **port the one-time "seed active models from Claude plan" step** |
| `providers/ai.py` | `Orrery.Core/Ai/ModelRouter.cs` + `Providers/*` | `ModelProvider(id)` prefix routing; `ListAvailableModels` (active-only), `ListCatalog`, `ProviderModels`; discovery/curation per provider (`_curate_*`) port as pure functions (easy to unit-test); `StreamChat` → `IAsyncEnumerable<string>`. `litellm.drop_params` → only pass `reasoning_effort` to providers that support it (per-provider capability map). |
| `providers/accounts.py` | `Orrery.Core/Accounts/ClaudePlan*.cs` + `CliJsonStreamer.cs` | the `claude` CLI bridge is **cleaner in C#**: `System.Diagnostics.Process` with async `StandardOutput` line reads → no Windows event-loop caveat, no thread+queue bridge. Port: status probe + cache, `--print --output-format stream-json --include-partial-messages` parsing (`stream_event`→`content_block_delta`→`text_delta`), model-flag map, image rejection, error sanitizing. |
| `providers/catalog.py` | `Orrery.Core/Catalog/ModelCatalog.cs` | custom models (EF) + activation set; custom key via `ISecretStore` under `custom:<id>`; `AddCustomModel` auto-activates |
| `features/chat.py` | `Orrery.Core/Chat/ChatService.cs` | conversations CRUD; SSE event stream; **keep**: `_content_parts`/`_history_text`/`_db_content` split (display vs. `context`), `FORMAT_INSTRUCTIONS`, the `_limit_messages` token-budget (`context_window`), RAG preamble + `_rag_context` redaction, persist-on-cancel behavior |
| `features/data.py` | `Orrery.Core/Data/ReadOnlyQueryService.cs` | **read-only enforced at the connection** (`SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout`) via Npgsql, *not* by SQL inspection (security.md §3); identifier allow-list from real schema; per-connection isolation by id |
| `features/rag.py` | `Orrery.Core/Rag/RagService.cs` + `Embedder.cs` | chunker (size 900 / overlap 150); OnnxRuntime embedder (verify L2-normalize matches fastembed output); hybrid vector (`<=>` cosine) + keyword (`to_tsvector`/`plainto_tsquery`) fused with RRF (1/(60+rank)) via raw SQL |
| `security/privacy.py` | `Orrery.Core/Privacy/Redactor.cs` | regex port (email/card/ssn/phone/ip); `RedactForModel(text, isLocal)` — local models exempt (security.md §10) |
| `api.py` | `Orrery.Api/Endpoints/*.cs` | one Minimal-API group per concern; **identical routes/shapes** so `ui/src/lib/api.js` is untouched; token middleware (`X-Orrery-Token`); SSE helper writing `data: {json}\n\n` |
| `core/queue.py` | `Orrery.Jobs/` (Hangfire) | Phase 4+; durable jobs, retries, cron; DB-change triggers via Npgsql `LISTEN/NOTIFY` |

---

## 4. Security parity checklist (port = these still hold)

`security.md` is the floor; the .NET port must satisfy each item or it does not ship:

- [ ] Secrets only in OS keychain via `ISecretStore`; never in DB/logs/UI/prompts; masked previews only.
- [ ] EF Core/Npgsql **parameterized** everywhere; raw SQL via `FromSqlInterpolated`/parameters; **never** string-built from user/model/row text.
- [ ] Dynamic identifiers validated against a fetched schema allow-list.
- [ ] Read-only contexts enforced at the **transaction/role** layer (`SET TRANSACTION READ ONLY`), not by inspecting SQL.
- [ ] Kestrel binds **127.0.0.1 only**; per-session token required on every `/api` call; token generated by `Orrery.Desktop` and passed via window URL.
- [ ] Outbound calls only to user-configured providers (+ Ollama localhost).
- [ ] PII redaction on the outbound cloud path; local-model exemption explicit and per-provider.
- [ ] Code-execution node (Phase 4): isolated process + wall-clock/memory/CPU limits, no ambient network/filesystem/secret access. **Cross-platform sandboxing is an open design item — see §8.**
- [ ] Provider errors sanitized before surfacing/logging.
- [ ] Every new NuGet dependency justified + pinned (central package management, `Directory.Packages.props`) + noted in DEVLOG (security.md §8).

---

## 5. Migration strategy & ordering

A language change can't be a true side-by-side strangler, but we approximate it: **port behind the unchanging REST contract, validated by the React UI + ported tests.** Build phase parity follows the existing roadmap (don't pull later phases forward).

**Stage A — Walking skeleton (proves cross-platform).**
1. `Orrery.Desktop` (Photino) picks a free port, starts an empty Kestrel, opens the window with `?token=…`.
2. `Orrery.Api` serves the **existing React build** from `wwwroot` + a `/api/health` endpoint + token middleware.
3. Run on all three OSes. Acceptance: the current React UI loads and shows "backend ok" on Windows, macOS, Linux.

**Stage B — Data + secrets spine.**
4. `Orrery.Secrets` per-OS, with a round-trip test on each platform.
5. `Orrery.Data` (DbContext, entities, first EF migration incl. pgvector + tsv/GIN), `MigrateAsync` on boot, port the active-model seed.

**Stage C — Chat parity (Phase 1).**
6. `ai` (routing/curation/streaming) + `accounts` (CLI bridge) + `catalog`.
7. `chat` (history, `context`, `context_window` budgeting, SSE, persist-on-cancel) + `privacy`.
8. Acceptance: Chat tab works end-to-end against the same endpoints; streaming, model switching (incl. claude_plan variants + custom models), effort, full-context-with-files all verified.

**Stage D — Data/RAG parity (Phase 2).**
9. `data` (read-only) + `rag` (onnx embedder + hybrid search).
10. Acceptance: connect a DB read-only (writes refused by Postgres), build a collection, "use my data" cites sources, PII redacted outbound.

**Stage E — Jobs + later phases.**
11. `Orrery.Jobs` (Hangfire) → Dashboards (3), Automations (4), Agents (5), Media/Power (6) ported per roadmap; code-sandbox per §8.

**Stage F — Packaging & cutover (§7).**

At each stage, the React UI is the integration test: if a tab still works, the port preserved behavior.

---

## 6. Database & data migration

- **Schema:** EF Core owns it going forward. Generate the initial migration to match the *current* Postgres schema exactly (same table/column names, the `tsv` generated column, the GIN index, `Vector(384)`), so an existing user's database upgrades in place rather than being recreated.
- **No data loss:** chats, collections, chunks (with embeddings), connections, custom/active models, and conversation `context`/`effort`/`context_window` all carry over because the schema is identical. Validate by pointing the .NET build at a populated dev DB and reading existing conversations.
- **Hangfire tables** are additive (own schema), created on first run; they replace `procrastinate_*` tables (old queue tables can be dropped after Automations/Agents are ported).
- **Embeddings caveat:** confirm the OnnxRuntime + tokenizer pipeline produces vectors numerically equivalent to fastembed for the same model (same normalization). If they differ, existing chunk embeddings stay valid for search only if the **query** embedder matches the **stored** embedder — so either keep using the identical ONNX model/normalization, or plan a one-time re-embed of existing collections.

---

## 7. Packaging & distribution

- `dotnet publish -c Release -r <rid> --self-contained -p:PublishSingleFile=true` per RID; Photino bundles the platform webview (WebView2 on Win, WKWebView on macOS, WebKitGTK on Linux — Linux needs `libwebkit2gtk` present/bundled).
- Installers: **Windows** MSIX or Inno Setup; **macOS** `.dmg`/`.pkg` with **codesign + notarization** (Apple Developer account required — a real cost/step); **Linux** AppImage and/or `.deb`.
- Postgres remains the user's (Docker dev compose unchanged). Ship the same first-run "enter connection string" flow.
- CI: GitHub Actions matrix (windows/macos/ubuntu) building all RIDs.

---

## 8. Risks, unknowns, mitigations

1. **No litellm equivalent.** Mitigation: most providers (OpenAI, DeepSeek, Mistral, Qwen, Kimi, GLM, OpenRouter, Together, Groq, local) are **OpenAI-compatible** → one OpenAI SDK client with `BaseUrl` covers them. Only Anthropic + Gemini + the claude/codex CLI bridges need bespoke clients. Microsoft.Extensions.AI gives a common `IChatClient` seam.
2. **Procrastinate → Hangfire mismatch.** Hangfire uses its own storage/semantics; LISTEN/NOTIFY DB triggers are custom (Npgsql supports it natively). Acceptable; revisit at Automations phase.
3. **Cross-platform keychain.** No single perfect NuGet lib. Mitigation: thin `ISecretStore` with three native backends (DPAPI / Security.framework P/Invoke / libsecret), with per-OS round-trip tests; encrypted-file fallback only if a backend is unavailable. (Reference pattern: MSAL's cross-platform token cache.)
4. **Embedding parity** (see §6) — verify or re-embed.
5. **Code-execution sandbox (Phase 4)** is the hardest cross-platform piece: the current design runs Python snippets in an isolated subprocess. Options in .NET: (a) keep a bundled Python sandbox subprocess; (b) move snippet language to a WASM runtime (**Wasmtime**) for true cross-OS isolation; (c) OS-native isolation (Job Objects/Win, cgroups+seccomp/Linux, sandbox-exec/macOS). Decide before Phase 4; do **not** ship code execution without it (security.md §5).
6. **Photino maturity** vs `pywebview` — validate WebView2/WebKitGTK SSE streaming and `?token=` handoff early (Stage A) on all three OSes.
7. **macOS notarization** is a process + paid-account dependency for distribution.

---

## 9. Effort & milestones (rough)

Assumes one experienced .NET dev, current scope = Phases 1–2 already built in Python.

- Stage A (skeleton, 3-OS): ~1 week.
- Stage B (data + secrets): ~1–1.5 weeks.
- Stage C (chat parity): ~2 weeks.
- Stage D (data/RAG parity): ~1.5 weeks.
- Stage E (jobs + later phases): tracks the original roadmap, per phase.
- Stage F (packaging/signing/CI): ~1 week + macOS signing setup.

**Hard rule:** the React UI and the REST/SSE contract are frozen during the port. If a port needs a contract change, change it in Python first (so both stay in sync) or defer.

---

## 10. Open decisions (resolve before starting)

- [ ] Confirm the rewrite is worth it vs. packaging the existing Python app per-OS (§0).
- [ ] Photino vs Avalonia+WebView vs MAUI BlazorWebView (recommended: **Photino**, to keep React).
- [ ] Microsoft.Extensions.AI vs Semantic Kernel as the model spine (recommended: **Microsoft.Extensions.AI** + OpenAI SDK).
- [ ] Hangfire vs Quartz.NET for jobs (recommended: **Hangfire.PostgreSql**).
- [ ] Code-sandbox approach for Phase 4 (WASM vs bundled-Python vs OS-native).
- [ ] Embedding parity: reuse identical ONNX pipeline, or accept a one-time re-embed.

---

*Keep this file in sync with `ORRERY_PLAN.md` and `../history/DEVLOG.md` when the port begins. Update §10 as decisions are made, and tick §4 as each security item is verified on the .NET side.*
