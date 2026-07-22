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

import json
from collections.abc import AsyncIterator, Awaitable, Callable

from backend import tools as tool_registry
from backend.features import events as stream_events
from backend.features.prompting import strip_think
from backend.features.reasoning_trace import ThinkStream
from backend.providers import ai

MAX_RUNS = 4  # most tool rounds per turn before we force a final answer
_STDOUT_FEEDBACK_CHARS = 6000

_FENCE = "```orrery-"
_CLOSE = "```"
_KINDS = ("run", "shell", "search", "tool")
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


def _tool_artifacts(result: dict) -> list[dict]:
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        return [item for item in artifacts if isinstance(item, dict)]
    files = result.get("files")
    if isinstance(files, list) and files and isinstance(files[0], dict):
        return [item for item in files if isinstance(item, dict)]
    return []


def _tool_observation(key: str, result: dict, artifacts: list[dict] | None = None) -> str:
    public = {k: v for k, v in result.items() if k not in {"artifacts", "sandbox_runs"}}
    text = json.dumps(public, ensure_ascii=False, default=str)[:_STDOUT_FEEDBACK_CHARS]
    parts = [f"[tool result] {key}:\n{text}"]
    if artifacts:
        parts.append("files written: " + ", ".join(str(f.get("name") or "file") for f in artifacts))
    if not artifacts and not str(public.get("stdout") or "").strip():
        parts.append("(no stdout and no files - print results or save files to out/)")
    return "\n\n".join(parts)


async def _run_registry_tool(
    servers: list[dict],
    body: str,
    *,
    allowed_tools: set[str] | None,
    context: dict,
) -> dict:
    """Parse an orrery-tool request and execute through the shared registry."""
    try:
        spec = json.loads(body)
    except (ValueError, TypeError):
        return {"ok": False, "label": "invalid request", "observation": "[tool] The orrery-tool block was not valid JSON."}
    if not isinstance(spec, dict):
        return {"ok": False, "label": "invalid request", "observation": "[tool] The orrery-tool block must be a JSON object."}

    if "server" in spec:
        name = str(spec.get("server", "")).strip()
        tool = str(spec.get("tool", "")).strip()
        args = spec.get("args") if isinstance(spec.get("args"), dict) else {}
        server = next((s for s in servers if s.get("name") == name or s.get("id") == name), None)
        if server is None or not tool:
            return {"ok": False, "label": f"{name}::{tool}", "observation": f"[mcp] No connected server/tool for '{name}::{tool}'."}
        result = await tool_registry.run_tool(
            "mcp_call",
            {"server_id": server["id"], "tool": tool, "args": args},
            allowed=allowed_tools,
        )
        artifacts = _tool_artifacts(result)
        return {
            "ok": result.get("ok", False),
            "label": f"{name}::{tool}",
            "observation": _tool_observation("mcp_call", result, artifacts),
            "artifacts": artifacts,
        }

    key = str(spec.get("tool") or spec.get("key") or "").strip()
    args = spec.get("args") if isinstance(spec.get("args"), dict) else {}
    if not key:
        return {"ok": False, "label": "missing tool", "observation": "[tool] Missing 'tool' key."}
    if key == "file_generate":
        args = dict(args)
        args.setdefault("model", context.get("model") or "")
        args.setdefault("system_prompt", context.get("system_prompt") or "")
        args.setdefault("effort", context.get("effort") or "")
        args.setdefault("trusted_context", context.get("trusted_context") or "")
        args.setdefault("untrusted_context", context.get("untrusted_context") or "")
    result = await tool_registry.run_tool(key, args, allowed=allowed_tools)
    artifacts = _tool_artifacts(result)
    return {
        "ok": result.get("ok", False),
        "label": key,
        "observation": _tool_observation(key, result, artifacts),
        "artifacts": artifacts,
    }


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
    mcp_servers: list[dict] | None = None,
    allowed_tools: set[str] | None = None,
    system_prompt: str | None = None,
    trusted_context: str | None = None,
    untrusted_context: str | None = None,
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
                        yield ev  # optional debug reasoning event
                    continue
                answer, revs = think.feed(delta)
                for ev in revs:
                    yield ev  # optional debug reasoning event
                if not answer:
                    continue
                visible, found = run_stream.feed(answer)
                blocks.extend(found)
                if visible:
                    iter_visible.append(visible)
                    visible_parts.append(visible)
                    yield stream_events.delta(visible)
            tail, tail_revs = think.finish()
            for ev in tail_revs:
                yield ev
            if tail:
                visible, found = run_stream.feed(tail)
                blocks.extend(found)
                if visible:
                    iter_visible.append(visible)
                    visible_parts.append(visible)
                    yield stream_events.delta(visible)
            tail_visible, tail_blocks = run_stream.finish()
            blocks.extend(tail_blocks)
            if tail_visible:
                iter_visible.append(tail_visible)
                visible_parts.append(tail_visible)
                yield stream_events.delta(tail_visible)
            usage["in"] += usage_out.get("tokens_in") or 0
            usage["out"] += usage_out.get("tokens_out") or 0
            if usage_out.get("cost") is not None:
                usage["cost"] += usage_out["cost"]
                usage["have_cost"] = True
                usage["provider"] = usage_out.get("provider")
                usage["model"] = usage_out.get("model")
            usage["pricing_known"] = usage_out.get("pricing_known", usage["pricing_known"])
        except ai.MissingKeyError as exc:
            yield stream_events.missing_key(exc.provider)
            return
        except Exception as exc:  # noqa: BLE001 — provider errors already sanitized upstream
            yield stream_events.error(str(exc))
            # Persist the failed turn (any partial answer + the error) so it survives a chat switch
            # instead of vanishing with the stream.
            failed_text = strip_think("".join(visible_parts)).strip()
            error_note = f"⚠️ The model call failed: {exc}"
            failed_text = f"{failed_text}\n\n{error_note}" if failed_text else error_note
            message_id = await persist(failed_text, all_files or None)
            yield stream_events.message_id(message_id)
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
                result = await tool_registry.run_tool("run_python", {"code": body}, allowed=allowed_tools)
                produced = _tool_artifacts(result)
                if produced:
                    all_files.extend(produced)
                    yield stream_events.files(produced)
                exit_code = result.get("exit_code")
                timed_out = bool(result.get("timed_out"))
                yield trace.step(
                    "Code finished" if result.get("ok") else "Code run had issues",
                    f"exit {exit_code}, {len(produced)} file(s)" + (" - timed out" if timed_out else ""),
                    kind="result", status="done" if result.get("ok") else "warning", phase="execute",
                    metadata={"exit_code": exit_code, "files": len(produced)},
                )
                echo += f"\n\n```orrery-run\n{body}\n```"
                observations.append(_tool_observation("run_python", result, produced))
            elif kind == "shell":
                yield trace.step(
                    "Running shell commands", "Executing in the secure sandbox (no network, capped, isolated).",
                    kind="tool", status="running", phase="execute", metadata={"run": run_index + 1},
                )
                result = await tool_registry.run_tool("run_shell", {"script": body}, allowed=allowed_tools)
                produced = _tool_artifacts(result)
                if produced:
                    all_files.extend(produced)
                    yield stream_events.files(produced)
                exit_code = result.get("exit_code")
                timed_out = bool(result.get("timed_out"))
                yield trace.step(
                    "Commands finished" if result.get("ok") else "Command run had issues",
                    f"exit {exit_code}, {len(produced)} file(s)" + (" - timed out" if timed_out else ""),
                    kind="result", status="done" if result.get("ok") else "warning", phase="execute",
                    metadata={"exit_code": exit_code, "files": len(produced)},
                )
                echo += f"\n\n```orrery-shell\n{body}\n```"
                observations.append(_tool_observation("run_shell", result, produced))
            elif kind == "search":
                if not allow_web:
                    echo += f"\n\n```orrery-search\n{body.strip()}\n```"
                    observations.append("[web search is disabled by the administrator]")
                    continue
                query = next((line.strip() for line in body.splitlines() if line.strip()), "")
                yield trace.step("Searching the web", query or "(empty query)",
                                 kind="tool", status="running", phase="gather", metadata={"run": run_index + 1})
                search_res = await tool_registry.run_tool("web_search", {"query": query}, allowed=allowed_tools) if query else {"ok": False, "results": []}
                results = search_res.get("results") if isinstance(search_res.get("results"), list) else []
                urls = [r["url"] for r in results if r.get("url")][:8]
                if urls:
                    yield stream_events.sources(urls)
                search_ok = bool(search_res.get("ok"))
                if not search_ok:
                    result_title = "Web search failed"
                    result_detail = str(search_res.get("error") or "Web search is unavailable.")
                elif results:
                    result_title = "Web results"
                    result_detail = f"{len(results)} result(s) for: {query}"
                else:
                    result_title = "No web results"
                    result_detail = f"0 result(s) for: {query}"
                yield trace.step(
                    result_title,
                    result_detail,
                    kind="result", status="done" if search_ok else "warning", phase="gather",
                    metadata={"results": len(results), "sources": urls},
                )
                echo += f"\n\n```orrery-search\n{query}\n```"
                observations.append(_tool_observation("web_search", search_res))
            else:  # tool (MCP)
                echo += f"\n\n```orrery-tool\n{body.strip()}\n```"
                tool_res = await _run_registry_tool(
                    mcp_servers or [],
                    body,
                    allowed_tools=allowed_tools,
                    context={
                        "model": model,
                        "system_prompt": system_prompt or "",
                        "effort": effort or "",
                        "trusted_context": trusted_context or "",
                        "untrusted_context": untrusted_context or "",
                    },
                )
                produced = _tool_artifacts(tool_res)
                if produced:
                    all_files.extend(produced)
                    yield stream_events.files(produced)
                yield trace.step(
                    "Calling tool" if tool_res["ok"] else "Tool issue", tool_res["label"],
                    kind="tool", status="done" if tool_res["ok"] else "warning", phase="execute",
                    metadata={"run": run_index + 1, "files": len(produced)},
                )
                observations.append(tool_res["observation"])

        work.append({"role": "assistant", "content": echo.strip()})
        work.append({"role": "user", "content": "\n\n".join(observations)})

    final_text = strip_think("".join(visible_parts)).strip()
    if not final_text:
        final_text = "Here is the result." if all_files else "I wasn't able to produce an answer."
    message_id = await persist(final_text, all_files or None)
    if message_id:
        yield stream_events.message_id(message_id)
    if usage["in"] or usage["out"]:
        yield stream_events.message_usage(usage["in"], usage["out"], usage["pricing_known"])
    if usage["have_cost"] and (usage["in"] or usage["out"]):
        from backend.features import usage as usage_mod
        await usage_mod.record(usage["provider"], usage["model"], usage["in"], usage["out"], usage["cost"])
        yield stream_events.usage(await usage_mod.summary())
    yield stream_events.done()
