"""Chat tool loop: let the model run Python and search the web to answer anything.

The model can emit two fenced tool blocks and end its turn:
  ```orrery-run     -> Python executed in the locked-down Docker sandbox (no network, capped,
                       read-only root, non-root, timeout — see sandbox.py and security.md).
  ```orrery-search  -> a web search performed by the backend (websearch.py), so web access is
                       UNIVERSAL: it works on any model/connection (local, CLI plan, or API key),
                       not only cloud models with their own web tool.

Orrery runs the requested tool(s), feeds the results back as an observation, and the model continues
until it produces the final answer. The loop is bounded so it always terminates. Sandbox output and
web results are treated as UNTRUSTED context (facts to use/cite, never instructions). It relies only
on a fenced text convention, so no native provider tool-calling is required.
"""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import AsyncIterator, Awaitable, Callable

from backend.features import files as file_library
from backend.features import sandbox, websearch
from backend.features.prompting import strip_think
from backend.features.reasoning_trace import ThinkStream
from backend.providers import ai

MAX_RUNS = 4  # most tool rounds per turn before we force a final answer
_STDOUT_FEEDBACK_CHARS = 6000

_FENCE = "```orrery-"
_CLOSE = "```"
_KINDS = ("run", "search")
_HOLDBACK = len("```orrery-search")  # hold back enough to detect the longest opener


class RunStream:
    """Split a streaming answer into visible text vs. orrery tool blocks.

    Mirrors ThinkStream: feed deltas, get back (visible_text, [(kind, body)]) where kind is "run" or
    "search". The tool blocks are suppressed from the visible answer (shown as activity steps instead).
    A plain ```python block the model is only *showing* passes through untouched.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._in = False
        self._kind: str | None = None

    def feed(self, delta: str) -> tuple[str, list[tuple[str, str]]]:
        self._buf += delta or ""
        out: list[str] = []
        blocks: list[tuple[str, str]] = []
        while self._buf:
            if self._in:
                end = self._buf.find(_CLOSE)
                if end == -1:
                    break  # wait for the closing fence
                blocks.append((self._kind or "run", self._buf[:end]))
                self._buf = self._buf[end + len(_CLOSE):]
                self._in = False
                self._kind = None
                continue
            start = self._buf.find(_FENCE)
            if start == -1:
                cut = len(self._buf) - (_HOLDBACK - 1)
                if cut > 0:
                    out.append(self._buf[:cut])
                    self._buf = self._buf[cut:]
                break
            nl = self._buf.find("\n", start)
            if nl == -1:  # opener line not complete yet — emit text before it, hold the rest
                if start > 0:
                    out.append(self._buf[:start])
                    self._buf = self._buf[start:]
                break
            head = self._buf[start + len(_FENCE):nl].strip().lower()
            kind = next((k for k in _KINDS if head.startswith(k)), None)
            if kind is None:  # an orrery- fence we don't recognize — pass it through as text
                out.append(self._buf[:nl + 1])
                self._buf = self._buf[nl + 1:]
                continue
            if start > 0:
                out.append(self._buf[:start])
            self._buf = self._buf[nl + 1:]
            self._in = True
            self._kind = kind
        return "".join(out), blocks

    def finish(self) -> tuple[str, list[tuple[str, str]]]:
        text, blocks = "", []
        if self._in:
            blocks.append((self._kind or "run", self._buf))  # unterminated — use what we have
        else:
            text = self._buf
        self._buf = ""
        self._in = False
        self._kind = None
        return text, blocks


def _store_files(result: sandbox.SandboxResult) -> list[dict]:
    produced: list[dict] = []
    for item in result.files:
        mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
        try:
            produced.append({"kind": "file", **file_library.store(item.name, mime, item.data)})
        except ValueError:
            continue
    return produced


def _sandbox_observation(result: sandbox.SandboxResult, produced: list[dict]) -> str:
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
    allow_web: bool = True,
) -> AsyncIterator[dict]:
    """Drive the tool loop (run code / search web -> observe -> continue), then persist the answer.

    `formatted_prompt` already includes the tool capability block. `persist(text, artifacts)` saves the
    assistant message and returns its id. Yields chat events (delta / step via `trace` / files /
    sources / message_id / usage / done / error).
    """
    work = list(messages)
    visible_parts: list[str] = []
    all_files: list[dict] = []
    usage = {"in": 0, "out": 0, "cost": 0.0, "have_cost": False, "pricing_known": True, "provider": None, "model": None}

    for run_index in range(max_runs):
        run_stream = RunStream()
        think = ThinkStream()
        blocks: list[tuple[str, str]] = []
        iter_visible: list[str] = []
        usage_out: dict = {}
        try:
            async for delta in ai.stream_chat(model, work, formatted_prompt, effort, usage_out):
                if isinstance(delta, ai.ReasoningDelta):
                    for ev in think.feed_reasoning(str(delta)):
                        yield ev  # stream the model's raw reasoning live
                    continue
                answer, revs = think.feed(delta)
                for ev in revs:
                    yield ev  # inline <think> reasoning, streamed live
                if not answer:
                    continue
                visible, found = run_stream.feed(answer)
                blocks.extend(found)
                if visible:
                    iter_visible.append(visible)
                    visible_parts.append(visible)
                    yield {"delta": visible}
            tail, tail_revs = think.finish()
            for ev in tail_revs:
                yield ev
            if tail:
                visible, found = run_stream.feed(tail)
                blocks.extend(found)
                if visible:
                    iter_visible.append(visible)
                    visible_parts.append(visible)
                    yield {"delta": visible}
            tail_visible, tail_blocks = run_stream.finish()
            blocks.extend(tail_blocks)
            if tail_visible:
                iter_visible.append(tail_visible)
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

        actionable = [(k, b) for k, b in blocks if b.strip()]
        if not actionable or run_index == max_runs - 1:
            break  # no tool requested (or budget spent) → this is the final answer

        echo = "".join(iter_visible)
        observations: list[str] = []
        for kind, body in actionable:
            if kind == "run":
                yield trace.step(
                    "Running Python", "Executing the model's code in the secure sandbox (no network, capped, isolated).",
                    kind="tool", status="running", phase="execute", metadata={"run": run_index + 1},
                )
                try:
                    result = await asyncio.to_thread(sandbox.run_code, body)
                except sandbox.SandboxError as exc:
                    yield trace.error("Sandbox unavailable", str(exc))
                    echo += f"\n\n```orrery-run\n{body}\n```"
                    observations.append(f"[sandbox error] {exc}. Answer without running code.")
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
                echo += f"\n\n```orrery-run\n{body}\n```"
                observations.append(_sandbox_observation(result, produced))
            else:  # search
                if not allow_web:
                    echo += f"\n\n```orrery-search\n{body.strip()}\n```"
                    observations.append("[web search is disabled by the administrator]")
                    continue
                query = next((line.strip() for line in body.splitlines() if line.strip()), "")
                yield trace.step("Searching the web", query or "(empty query)",
                                 kind="tool", status="running", phase="gather", metadata={"run": run_index + 1})
                results = await websearch.search(query) if query else []
                urls = [r["url"] for r in results if r.get("url")][:8]
                if urls:
                    yield {"sources": urls}
                yield trace.step(
                    "Web results" if results else "No web results",
                    f"{len(results)} result(s) for: {query}",
                    kind="result", status="done" if results else "warning", phase="gather",
                    metadata={"results": len(results), "sources": urls},
                )
                echo += f"\n\n```orrery-search\n{query}\n```"
                observations.append(f"[web search results] for \"{query}\":\n{websearch.format_results(results)}")

        work.append({"role": "assistant", "content": echo.strip()})
        work.append({"role": "user", "content": "\n\n".join(observations)})

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
