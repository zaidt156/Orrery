"""Chat code-interpreter: let the model write and run Python to answer anything computational.

When a request is best solved by code (math, data wrangling, parsing, simulation, generating a
chart/file), the model emits a fenced ```orrery-run Python block and ends its turn. Orrery executes
it in the locked-down Docker sandbox (no network, capped, read-only root, non-root, timeout — see
sandbox.py and security.md), captures stdout/stderr and any files written to out/, feeds that back
to the model as an observation, and the model continues until it produces the final answer.

Universal by design: it relies only on a fenced text convention, so it works on any provider/model
(API, CLI plan, or local) without native tool-calling. Code is always run in the sandbox and treated
as untrusted; the loop is bounded so it always terminates.
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
from collections.abc import AsyncIterator, Awaitable, Callable

from backend.features import files as file_library
from backend.features import sandbox
from backend.features.prompting import strip_think
from backend.features.reasoning_trace import ThinkStream
from backend.providers import ai

MAX_RUNS = 4  # most sandbox executions per turn before we force a final answer
_STDOUT_FEEDBACK_CHARS = 6000

_OPEN = "```orrery-run"
_CLOSE = "```"
_HOLDBACK = len(_OPEN) - 1  # never emit a tail that might be a partial opening fence
_RUN_BLOCK = re.compile(r"```orrery-run[^\n]*\n(.*?)```", re.DOTALL)


class RunStream:
    """Split a streaming answer into visible text vs. ```orrery-run code blocks.

    Mirrors ThinkStream: feed deltas, get back (visible_text, [completed_code_blocks]). The code
    blocks are suppressed from the visible answer (shown as a 'ran Python' step instead). A plain
    ```python block the model is just *showing* passes through untouched — only ```orrery-run runs.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._in_code = False

    def feed(self, delta: str) -> tuple[str, list[str]]:
        self._buf += delta or ""
        out: list[str] = []
        codes: list[str] = []
        while self._buf:
            if self._in_code:
                end = self._buf.find(_CLOSE)
                if end == -1:
                    break  # wait for the closing fence
                codes.append(self._buf[:end])
                self._buf = self._buf[end + len(_CLOSE):]
                self._in_code = False
                continue
            start = self._buf.find(_OPEN)
            if start == -1:
                cut = len(self._buf) - _HOLDBACK
                if cut > 0:
                    out.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                break
            if start > 0:
                out.append(self._buf[:start])
            # skip the opening fence line (``` orrery-run + optional language hint, up to newline)
            nl = self._buf.find("\n", start)
            if nl == -1:
                self._buf = self._buf[start:]  # fence line not complete yet
                break
            self._buf = self._buf[nl + 1:]
            self._in_code = True
        return "".join(out), codes

    def finish(self) -> tuple[str, list[str]]:
        text, codes = "", []
        if self._in_code:
            codes.append(self._buf)  # unterminated block — run what we have
        else:
            text = self._buf
        self._buf = ""
        self._in_code = False
        return text, codes


def _store_files(result: sandbox.SandboxResult) -> list[dict]:
    produced: list[dict] = []
    for item in result.files:
        mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
        try:
            produced.append({"kind": "file", **file_library.store(item.name, mime, item.data)})
        except ValueError:
            continue
    return produced


def _observation(result: sandbox.SandboxResult, produced: list[dict]) -> str:
    parts = [f"[sandbox result] exit_code={result.exit_code} timed_out={result.timed_out}"]
    if result.stdout.strip():
        parts.append("stdout:\n" + result.stdout[:_STDOUT_FEEDBACK_CHARS])
    if result.stderr.strip():
        parts.append("stderr:\n" + result.stderr[:_STDOUT_FEEDBACK_CHARS])
    if produced:
        parts.append("files written to out/: " + ", ".join(f["name"] for f in produced))
    if not result.stdout.strip() and not produced:
        parts.append("(no stdout and no files — print results or save files to out/)")
    return "\n\n".join(parts)


async def run(
    model: str,
    formatted_prompt: str,
    messages: list[dict],
    effort: str | None,
    *,
    trace,
    persist: Callable[[str, list[dict] | None], Awaitable[str]],
    max_runs: int = MAX_RUNS,
) -> AsyncIterator[dict]:
    """Drive the write-code → run → observe → continue loop, then persist the final answer.

    `formatted_prompt` is the fully built system prompt (already includes the orrery-run capability).
    `persist(text, artifacts)` saves the assistant message and returns its id. Yields chat events
    (delta / reasoning step via `trace` / files / message_id / done / error).
    """
    work = list(messages)
    visible_parts: list[str] = []
    all_files: list[dict] = []
    usage = {"in": 0, "out": 0, "cost": 0.0, "have_cost": False, "pricing_known": True, "provider": None, "model": None}

    for run_index in range(max_runs):
        run_stream = RunStream()
        think = ThinkStream()
        code_blocks: list[str] = []
        usage_out: dict = {}
        try:
            async for delta in ai.stream_chat(model, work, formatted_prompt, effort, usage_out):
                if isinstance(delta, ai.ReasoningDelta):
                    think.feed_reasoning(str(delta))
                    continue
                answer, _ = think.feed(delta)
                if not answer:
                    continue
                visible, codes = run_stream.feed(answer)
                code_blocks.extend(codes)
                if visible:
                    visible_parts.append(visible)
                    yield {"delta": visible}
            tail, _ = think.finish()
            if tail:
                visible, codes = run_stream.feed(tail)
                code_blocks.extend(codes)
                if visible:
                    visible_parts.append(visible)
                    yield {"delta": visible}
            tail_visible, tail_codes = run_stream.finish()
            code_blocks.extend(tail_codes)
            if tail_visible:
                visible_parts.append(tail_visible)
                yield {"delta": tail_visible}
            usage["in"] += usage_out.get("tokens_in") or 0
            usage["out"] += usage_out.get("tokens_out") or 0
            if usage_out.get("cost") is not None:
                usage["cost"] += usage_out["cost"]
                usage["have_cost"] = True
                usage["provider"] = usage_out.get("provider")
                usage["model"] = usage_out.get("model")
            usage["pricing_known"] = usage_out.get("pricing_known", usage["pricing_known"])
        except ai.MissingKeyError as exc:
            yield {"error": f"No API key for {exc.provider}. Add it in Settings."}
            return
        except Exception as exc:  # noqa: BLE001 — provider errors already sanitized upstream
            yield {"error": str(exc)}
            return

        code = next((c for c in code_blocks if c.strip()), "")
        if not code.strip() or run_index == max_runs - 1:
            break  # no code requested (or budget spent) → this is the final answer

        yield trace.step(
            "Running Python", "Executing the model's code in the secure sandbox (no network, capped, isolated).",
            kind="tool", status="running", phase="execute", metadata={"run": run_index + 1},
        )
        try:
            result = await asyncio.to_thread(sandbox.run_code, code)
        except sandbox.SandboxError as exc:
            yield trace.error("Sandbox unavailable", str(exc))
            work.append({"role": "assistant", "content": "```orrery-run\n" + code + "\n```"})
            work.append({"role": "user", "content": f"[sandbox error] {exc}. Answer without running code."})
            continue

        produced = _store_files(result)
        if produced:
            all_files.extend(produced)
            yield {"files": produced}
        yield trace.step(
            "Code finished" if result.ok else "Code run had issues",
            f"exit {result.exit_code}, {len(produced)} file(s)" + (" — timed out" if result.timed_out else ""),
            kind="result", status="done" if result.ok else "warning", phase="execute",
            metadata={"exit_code": result.exit_code, "files": len(produced)},
        )
        work.append({"role": "assistant", "content": "```orrery-run\n" + code + "\n```"})
        work.append({"role": "user", "content": _observation(result, produced)})

    final_text = strip_think("".join(visible_parts)).strip()
    if not final_text:
        final_text = "Here is the result." if all_files else "I wasn't able to produce an answer."
    message_id = await persist(final_text, all_files or None)
    if message_id:
        yield {"message_id": message_id}
    if usage["in"] or usage["out"]:
        yield {"message_usage": {"in": usage["in"], "out": usage["out"], "pricing_known": usage["pricing_known"]}}
    if usage["have_cost"] and (usage["in"] or usage["out"]):
        from backend.features import usage as usage_mod
        await usage_mod.record(usage["provider"], usage["model"], usage["in"], usage["out"], usage["cost"])
        yield {"usage": await usage_mod.summary()}
    yield {"done": True}
