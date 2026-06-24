# Production Account Connections — how users connect models without touching a terminal

**Problem this solves:** the current optional account routes launch a vendor CLI the user already installed and logged into. That works for advanced local users, but a shipped product still needs provider-approved in-app OAuth or a guided API-key flow for non-technical users.

---

## 1. The honest constraint (read first)

- A **consumer subscription** (ChatGPT Plus/Pro, Gemini Advanced, Claude Pro/Max) does **not** automatically grant a third-party app the right to call the provider's API on that subscription. That entitlement is the provider's to grant.
- The legitimate "Sign in with X" experiences are **OAuth 2.0 Authorization Code + PKCE** flows where the app is a **registered OAuth client the provider approved**. Vendor CLIs (claude/codex/gemini) are the vendor's own first-party clients doing exactly this.
- Therefore the blocker for "one-click subscription" is **provider approval + a registered client_id**, not Orrery's code. Orrery can ship the flow; each provider must permit it.
- The **universally available** path for every provider is an **API key** (separate, usage-based billing). It works for everyone today; the job is to make adding one feel like two clicks, not a chore.

CLI-config editing and "install this CLI" steps **never appear in the production UI.** At most they live behind an "Advanced / local" disclosure for power users.

---

## 2. The three connection methods (and when each is offered)

For each provider, the Connect screen automatically offers the **best method available**, in this priority:

1. **In-app OAuth ("Sign in")** — *one click*, used when Orrery has a provider-approved client for that account type. Opens the provider's own login in the system browser; user approves; we get tokens. **This is the "like Claude" experience.**
2. **API key ("Add key")** — *two clicks + paste*, the universal fallback. We deep-link the user straight to the provider's API-keys page and give a one-field paste box. Works for every provider that has an API.
3. **Local CLI (advanced, opt-in)** — the current Claude Code, Codex, and eligible Gemini CLI routes. Orrery launches the first-party executable and never extracts its token.

The point: a normal user sees **one button per provider** — "Sign in" if we have OAuth for it, otherwise "Add key" with a guided paste. No terminals, no config files.

---

## 3. How the one-click OAuth actually works (the plumbing to build)

Standard **OAuth 2.0 Authorization Code flow with PKCE + loopback redirect** (RFC 8252 — the correct pattern for desktop apps):

1. User clicks **Connect <provider>**.
2. Orrery generates a PKCE `code_verifier` + `code_challenge` and a random `state`, starts a **temporary localhost listener** on a random port (e.g. `http://127.0.0.1:<port>/callback`).
3. Orrery opens the provider's **authorize URL** in the user's **system browser** (not an embedded webview — safer, and the user trusts their own browser): `client_id`, `redirect_uri=http://127.0.0.1:<port>/callback`, `scope`, `state`, `code_challenge`.
4. User logs in and approves **on the provider's own page** (Orrery never sees the password).
5. Provider redirects back to the loopback URL with `code` + `state`. Orrery verifies `state`, then exchanges `code` + `code_verifier` at the provider's **token endpoint** for an **access token + refresh token**.
6. Orrery stores the **refresh token in the OS keychain** (never the DB/logs/UI), uses the access token for calls, and **refreshes automatically** when it expires.
7. The Connect screen flips to "Connected ✓" — same end state as Claude plan today.

**Security requirements (security.md §1, §7):**
- PKCE mandatory (no client secret in a distributed desktop app).
- Validate `state` (CSRF), enforce exact loopback `redirect_uri`, short-lived listener, one-time use.
- Tokens live only in the keychain; access tokens kept in memory; refresh token encrypted at rest by the OS keychain.
- Never embed a long-lived client secret in the shipped binary; use public-client PKCE.

This module is **provider-agnostic** — one `OAuthConnector` with per-provider config (authorize URL, token URL, scopes, client_id). Adding a provider = adding a config row, once it's approved.

---

## 4. Per-provider reality (verify current policy before shipping each)

Provider programs change; confirm each provider's *current* developer terms at build time. As a planning baseline:

| Provider | One-click OAuth (subscription) | Reliable production path today |
|---|---|---|
| **OpenAI / ChatGPT** | Codex CLI officially supports ChatGPT sign-in and non-interactive execution. Orrery can launch that CLI locally, but direct in-app OAuth still needs an approved Orrery client. | **API key** by default; optional local Codex CLI route. |
| **Google / Gemini** | Consumer Gemini CLI service ended June 18, 2026 and moved to Antigravity. Direct in-app entitlement still requires a sanctioned Google program. | **API key** by default; Gemini CLI only for supported enterprise/API-key accounts; Antigravity pending a safe headless interface. |
| **Anthropic / Claude** | Claude Code supports signed-in non-interactive use. Direct Orrery OAuth still needs provider approval. | **API key** by default; optional local Claude Code route. |
| **Mistral, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Together, Groq, local** | n/a | **API key** (already shipped via the universal custom-model + built-in providers). |

**Net:** in production, **API keys are the dependable "works for everyone" method**, made smooth (deep-link + paste). True one-click OAuth ships **per provider, as each approves Orrery as a client.** Don't promise a subscription one-click we can't deliver — promise "Connect" and give the best real method per provider.

---

## 5. UX in production (what the user sees)

- **Settings → Accounts**: one card per provider with a single primary button:
  - has OAuth approved → **"Sign in with <provider>"** (one click, §3 flow).
  - otherwise → **"Connect"** → opens a small panel: a "Get your key →" deep-link button to the provider's keys page + one paste field + Save. Two clicks and a paste.
- A subtle **"Advanced"** link reveals the local-CLI route for users who already run those tools.
- Connected state, masked preview, and disconnect — same as today.
- First-run wizard: "Connect a model to get started" → the same cards. Optionally offer **Ollama (local, free, no account)** as the zero-friction default so the app is useful before any account is connected.

---

## 6. What to build now vs. what's blocked

**Buildable now (no provider dependency):**
- The reusable `OAuthConnector` (PKCE + loopback listener + token store/refresh in keychain) — ready so any approved provider is a config away.
- The smoother **API-key UX** (deep-link to the provider's key page + guided paste) — biggest immediate win for production friction, works for every provider today.
- Move the optional local CLI routes behind an "Advanced" disclosure.
- **Ollama as the no-account default** for first-run.

**Blocked on the provider (project-owner action, not code):**
- Registering Orrery as an OAuth client with OpenAI/Google/etc. and confirming each permits the access we want. Until then, those providers ship as "Add key."

---

## 7. Recommendation

1. Ship **API-key connect, made friction-light** (deep-link + paste) as the production default for all providers — this removes the terminal/config steps entirely and works for everyone now.
2. Build the **provider-agnostic OAuth/PKCE module** so "Sign in with X" lights up the moment a provider approves our client.
3. Keep the **local-CLI routes as an Advanced option** for developers.
4. Pursue **OpenAI "Sign in with ChatGPT"** registration first (most likely to yield a real subscription one-click), then others as policy allows.
5. Offer **Ollama** at first run so a brand-new user can chat with zero accounts.

*Update §4 as each provider's policy is confirmed and as clients are registered. This pairs with `security.md` §1/§7 for token handling.*
