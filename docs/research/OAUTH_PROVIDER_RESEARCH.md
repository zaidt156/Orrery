# Official Account and CLI Access (verified 2026-06-22)

Orrery supports API keys, local models, and selected first-party command-line account routes. These are separate mechanisms:

- **API route:** Orrery calls the provider API with a key stored in the OS keychain.
- **Official CLI route:** Orrery launches an installed vendor CLI. The CLI reads and refreshes its own login. Orrery never reads or copies the OAuth/session token.
- **Unsupported token reuse:** copying a vendor CLI token, browser cookie, private session, or first-party OAuth client into Orrery. This remains prohibited.

## Current provider position

### Anthropic

Claude Code supports signed-in account use and non-interactive execution. Orrery launches `claude --print` with tools disabled, MCP configuration locked down, permission prompts disabled, and session persistence off. On Windows, the optional installer uses only the official `Anthropic.ClaudeCode` WinGet package, and sign-in launches the vendor-owned `claude auth login` flow.

This route is text-first in Orrery. Image attachments must use an API-key vision model. Connect performs a small safe readiness request before storing Orrery's local connected marker.

### OpenAI

OpenAI documents both **Sign in with ChatGPT for subscription access** and API-key access in Codex CLI. OpenAI also documents `codex exec` as its non-interactive/programmatic interface and states that it reuses saved CLI authentication.

Orrery therefore supports an optional Codex route without extracting tokens:

- empty temporary working directory;
- read-only Codex sandbox;
- approval policy `never`;
- ephemeral session;
- no web-search flag;
- a local acknowledgement before connect.
- fixed official WinGet install/update (`OpenAI.Codex`) after explicit consent;
- vendor-owned `codex login` in a separate console when authentication is missing;
- a real read-only readiness request before the route is marked connected.

Older Codex releases can still load normal user configuration, which may initialize configured plugins or MCP servers. Orrery displays that limitation when the installed CLI cannot isolate user configuration. API-key models remain the faster, simpler default for ordinary chat.

The default route is version-aware. Current Codex uses GPT-5.5; older compatible releases fall back to GPT-5.4 mini instead of selecting a model that requires a newer CLI. Orrery also prefers the official WinGet installation over stale npm or editor-extension shims.

### Google

Gemini CLI documents Google-account login and a headless JSON/JSONL interface. It also supports read-only Plan Mode.

Google announced on **May 19, 2026** that, starting **June 18, 2026**, Gemini CLI would stop serving consumer free, Google AI Pro, and Google AI Ultra requests. Those users moved to Antigravity CLI. Gemini CLI remains supported for eligible Standard/Enterprise accounts and API-key routes.

Orrery keeps a Gemini CLI adapter for supported accounts. It requires headless JSON output and read-only Plan Mode. Consumer subscription users see the Antigravity migration notice instead of a misleading Connect path. Antigravity will be added only after Google publishes a stable headless interface that Orrery can restrict safely.

## Chinese and other providers

DeepSeek is built in. Qwen, Kimi, and GLM use their official OpenAI-compatible APIs through Orrery's custom-model route. Current presets:

| Provider | Base URL | Example model |
|---|---|---|
| Qwen / Alibaba Model Studio | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `qwen3.7-max` |
| Kimi / Moonshot | `https://api.moonshot.ai/v1` | `kimi-k2.7-code` |
| GLM / Z.AI | `https://api.z.ai/api/paas/v4` | `glm-5.2` |

Provider chat subscriptions are not assumed to fund API calls. Use the provider's API key unless it publishes a supported local CLI or approved OAuth program.

## Security rules

1. Never scrape browser cookies, desktop state, or private web APIs.
2. Never read, copy, return, log, or store vendor CLI OAuth/session files.
3. CLI routes are opt-in and display their execution limits.
4. Coding-agent CLIs run in an empty temporary directory with the strongest non-writing/no-persistence flags their official interface exposes.
5. If a required safety flag is missing, the route is unavailable.
6. API keys and Orrery's local connected markers remain in the OS keychain.

## Official sources

- OpenAI: [Codex authentication](https://developers.openai.com/codex/auth), [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive/)
- Anthropic: [Claude Code authentication](https://code.claude.com/docs/en/authentication), [Claude Code headless mode](https://code.claude.com/docs/en/headless)
- Google: [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/), [Gemini CLI headless mode](https://geminicli.com/docs/cli/headless/), [Gemini CLI to Antigravity announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- Qwen: [Alibaba Model Studio models](https://help.aliyun.com/zh/model-studio/models)
- Kimi: [Kimi chat completion API](https://platform.kimi.ai/docs/api/chat)
- GLM: [Z.AI quick start](https://docs.z.ai/guides/overview/quick-start)
