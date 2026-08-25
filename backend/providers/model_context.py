"""What each model's context window actually is.

This table exists because the alternative was silently wrong. Orrery asked litellm for every
model's window, and litellm's database lags new releases by months — but its miss path returns
nothing rather than an error, so an unknown id fell through to a flat 131,072 (32,768 for local
models). A 1M-context model then ran as an eighth of itself, and nothing anywhere said so: the
history trimmer just dropped the user's earlier turns to fit a budget that was never real.

So the numbers Orrery actually offers are written down here, ahead of the lookup, and litellm stays
as the fallback for everything not listed.

**Two rules govern every entry.**

*Understating is silent, overstating is loud.* Too small a window throws away context with no error;
too large a window gets the request rejected by the provider. Neither is acceptable, but they fail
differently, so where a vendor quotes both a native window and an extended one (YaRN, opt-in
long-context modes), the **native** figure is recorded. The extended mode is a server-side choice
Orrery cannot see from here, and claiming it would turn a quiet loss into a hard failure.

*A number here is a citation, not an estimate.* Every value comes from the vendor's stated window.
If a model's window isn't known, it does not belong in this table — `lookup` returning None is the
correct answer, because it lets litellm try.

Matching is by longest normalised prefix. Names are normalised to letters and digits so the many
spellings of one model (`llama-4-scout`, `llama4-scout`, `ollama/llama4-scout:latest`,
`openrouter/meta-llama/llama-4-scout`) collapse to a single comparable form, and so that a version
written `4-8` matches one written `4.8`. Longest-prefix is what keeps `gpt-5.4-mini` from
inheriting `gpt-5.4`'s window, which would be a rejected request at 400K rather than a wasted one.
"""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[-_.\s]+")

_256K = 262_144
_1M = 1_000_000
_GEMINI_1M = 1_048_576  # Google quotes the exact token count, not a round million

# Normalised model-name prefix → context window, as stated by the vendor (August 2026).
WINDOWS: dict[str, int] = {
    # --- OpenAI ---------------------------------------------------------------------------------
    # The 5.x flagships all carry the same 1.05M window across the sol/terra/luna tiers; the small
    # tiers do not, and share an entry per version so neither can inherit the flagship's number.
    "gpt56": 1_050_000,
    "gpt55": 1_050_000,
    "gpt55mini": 400_000,
    "gpt55nano": 400_000,
    "gpt54": 1_050_000,
    "gpt54mini": 400_000,
    "gpt54nano": 400_000,
    "gptoss120b": 131_072,
    "gptoss20b": 131_072,

    # --- Anthropic ------------------------------------------------------------------------------
    # These are the *API* windows. Opus 4.8 is the one model whose window depends on the surface —
    # 500K over the API, up to 1M inside Claude Code — and the plan route resolves that separately
    # (see ai._ANTHROPIC_1M_PREFIXES). Recording 1M here would overstate every direct API call.
    "claudeopus5": _1M,
    "claudesonnet5": _1M,
    "claudefable5": _1M,
    "claudemythos5": _1M,
    "claudeopus48": 500_000,
    "claudesonnet4": _1M,
    "claudehaiku45": 200_000,

    # --- Google ---------------------------------------------------------------------------------
    "gemini37": _GEMINI_1M,
    "gemini36": _GEMINI_1M,
    "gemini35": _GEMINI_1M,
    "gemini31": _GEMINI_1M,
    "gemini25": _GEMINI_1M,
    "gemma4": _256K,
    "gemma4e4b": 131_072,  # the on-device sizes are half the window of their larger siblings
    "gemma4e2b": 131_072,

    # --- xAI ------------------------------------------------------------------------------------
    # Grok's newest is not its longest: 4.6 and 4.5 are half of 4.3. Any scheme that inferred a
    # window from a version number would get this exactly backwards.
    "grok46": 500_000,
    "grok45": 500_000,
    "grok43": _1M,
    "grok420": _1M,

    # --- Meta -----------------------------------------------------------------------------------
    # Scout's 10M is the architecture's ceiling. A local Ollama copy will not serve anything like
    # it, which is why local routes are clamped to what the server reports rather than to this.
    "llama4scout": 10_000_000,
    "llama4maverick": _1M,
    "musespark11": _1M,

    # --- the open-weight frontier ---------------------------------------------------------------
    "deepseekv4": _1M,  # pro, flash, and the experimental vision build are all 1M-class
    "kimik3": _GEMINI_1M,
    "qwen38max": _1M,
    "qwen3824t": _256K,  # 262K native; the ~1.01M figure needs YaRN enabled server-side
    "qwen3827b": _1M,    # hosted long-context; the ollama clamp handles a local copy
    "qwen359b": _256K,
    "glm53": _1M,
    "glm52": _1M,
    "minimaxm3": _1M,

    # --- Mistral (256K across the current line) -------------------------------------------------
    "mistralmedium35": _256K,
    "mistralsmall4": _256K,
    "mistrallarge3": _256K,
    "ministral3": _256K,

    # --- Cohere ---------------------------------------------------------------------------------
    # Command A+ quotes 128K *input* against Command A's 256K total — the plus is parameters and
    # modality, not context, and reading it as an upgrade would overstate it by 2x.
    "commanda": _256K,
    "commandaplus": 131_072,
    "commanda+": 131_072,
    "commandr": 131_072,

    # --- stealth ---------------------------------------------------------------------------------
    "oxalpha": _GEMINI_1M,
}

# Longest first, so the specific entry is found before the family it belongs to.
_ORDERED: list[tuple[str, int]] = sorted(WINDOWS.items(), key=lambda kv: -len(kv[0]))


def normalize(model_id: str | None) -> str:
    """Reduce any spelling of a model id to one comparable name.

    Drops the routing prefix and any vendor path (`openrouter/meta-llama/…`), the Ollama tag after
    a colon, case, and every separator — so `llama-4-scout`, `llama4-scout` and
    `ollama/llama4-scout:latest` are the same string, and a version written `4-8` matches `4.8`.
    """
    if not model_id:
        return ""
    name = str(model_id).strip().rsplit("/", 1)[-1]
    name = name.split(":", 1)[0]  # ollama tag: llama4-scout:q4_K_M
    return _SEPARATORS.sub("", name).lower()


def lookup(model_id: str | None) -> int | None:
    """The stated context window for a known model, or None when it isn't one.

    None is a real answer, not a failure: it hands the question to litellm rather than inventing a
    number, and inventing one is the bug this module was written to remove.
    """
    name = normalize(model_id)
    if not name:
        return None
    for prefix, window in _ORDERED:
        if name.startswith(prefix):
            return window
    return None
