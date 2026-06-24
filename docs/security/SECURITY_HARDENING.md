# Orrery Security Hardening — Pass 1 (2026-06-22)

A focused audit of the live backend against `security.md`, with the fixes applied this pass. Scope: the localhost boundary, secrets handling, SQL safety, the new custom-model request path, and the model-CLI bridges. Phases 3–6 (dashboards/automations/agents/code-node) are not built yet and are covered when they land.

## Findings & fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | **SSRF via custom-model `base_url`.** The "Add custom model" feature stores a user-supplied URL the backend then calls server-side; nothing stopped pointing it at cloud metadata (`169.254.169.254`), link-local, or non-http schemes (`file://`). | `backend/security/netguard.py` provides `validate_model_base_url()`: only http/https; blocks link-local/multicast/reserved/unspecified; plain http allowed only for loopback/private (so local Ollama/vLLM still work), https for private or public. Enforced **at add time** (`catalog.add_custom_model`) and **again at call time** (`ai.stream_chat`). Tests live in `tests/security/test_netguard.py`. |
| 2 | Medium | **API key leak in logs.** `_fetch_google` passed the key in the URL query (`?key=…`); a failed-discovery `log.warning` logs the exception string, which would contain that URL **with the key**. | Key now sent as `x-goog-api-key` header — never in the URL, so it can't appear in logs/proxies. |
| 3 | Medium | **Session-token compare not constant-time.** `x_orrery_token != session_token` is short-circuiting, leaking timing. | `hmac.compare_digest` + explicit empty-token rejection. |
| 4 | Medium | **No response hardening headers / no body cap.** | Middleware adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, and a strict **CSP** (`default-src 'self'`; `script-src 'self'`; `img-src 'self' data: blob:`; `style-src 'self' 'unsafe-inline'`; `connect-src 'self'`; `object-src 'none'`; `frame-ancestors 'none'`). Body capped at 64 MB (413 otherwise). CSP verified safe — the built `index.html` has no inline scripts. |
| 5 | Low (defense-in-depth) | A non-auth-classified provider error could still embed a key in the user-facing message. | `_sanitize` now scrubs `sk-…`, `AIza…`, and `Bearer …` tokens and matches more auth phrasings. |

## Verified already-correct (no change needed)

- **SQL safety / read-only** (`data.py`): every query parameterized; read-only enforced by the database (`SET TRANSACTION READ ONLY` + rollback), not by SQL inspection; dynamic identifiers validated against a fetched schema allow-list before quoting; statement timeout + row cap; connection string lives in the keychain, redacted on error. (security.md §2, §3)
- **CLI bridges** (`accounts.py`): `subprocess` is always **list-form, never `shell=True`**; the only dynamic arg is the model flag, taken from an allow-list (`_CLAUDE_PLAN_FLAG`); the prompt goes via stdin. No shell/argument injection. (security.md §1)
- **Secrets to UI**: providers/keys endpoints return only masked previews + booleans; raw keys never serialized (covered by `test_api` + `test_accounts`). (security.md §1)
- **Localhost boundary**: Kestrel/uvicorn bind 127.0.0.1; per-session token required on every `/api` route; CORS only in dev. (security.md §7)
- **Markdown rendering**: react-markdown does not render raw HTML (no `rehype-raw`), so model output can't inject script; CSP is a second layer.

## Residual risks / follow-ups

- **DNS rebinding** between the SSRF check and litellm's actual request is not closed (would need a pinned-IP HTTP client). Acceptable for a single-user local app where the user configures their own endpoints; revisit if endpoints ever become model/agent-suppliable.
- **Code-execution node (Phase 4)** is the highest future risk — must ship sandboxed (isolated process, resource limits, no ambient net/fs/secrets) per security.md §5. Not present yet.
- **Prompt-injection via RAG/agent content** — the tool layer is the backstop; full enforcement arrives with Agents (Phase 5).
- **Dependency pinning** — keep `requirements.lock.txt` current (security.md §8).

## Test coverage added

`tests/security/test_netguard.py` (SSRF policy), `tests/test_api.py` (security headers, wrong-token rejection), `tests/providers/test_ai.py` (Google-key scrub). Full suite at the time of this review: **60 passing**.
