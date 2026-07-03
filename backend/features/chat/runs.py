"""Detached runs: keep generating + persisting even if the client navigates away."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from backend.features import events as stream_events
from backend.features import taskbrain

_RUN_DONE = object()
_run_queues: dict[str, asyncio.Queue] = {}
_run_tasks: dict[str, asyncio.Task] = {}


def start_detached(conv_id: str, source: AsyncIterator[dict]) -> asyncio.Queue:
    """Drive a generation to completion in a background task (it persists in its own finally),
    pushing events to a queue the HTTP request observes. Client disconnect stops the observer,
    not the task — so the reply finishes and is saved regardless. Recorded in the Task Brain."""
    from backend.features.chat import router  # late import: router owns _conv_title

    cancel_run(conv_id)
    queue: asyncio.Queue = asyncio.Queue()
    _run_queues[conv_id] = queue

    async def drive() -> None:
        task_id: str | None = None
        status = "done"
        try:
            try:  # the Task Brain ledger is best-effort and must NEVER hang or fail the generation
                title = await asyncio.wait_for(router._conv_title(uuid.UUID(conv_id)), timeout=5)
                task_id = await asyncio.wait_for(taskbrain.start("chat", title, conv_id), timeout=5)
            except Exception:  # noqa: BLE001 — ledger down/slow → just skip recording
                task_id = None
            async for event in source:
                if "error" in event:
                    status = "failed"
                queue.put_nowait(event)
        except asyncio.CancelledError:
            status = "canceled"
            raise
        except Exception as exc:  # noqa: BLE001 — surface a sanitized error
            status = "failed"
            queue.put_nowait(stream_events.error(str(exc)))
        finally:
            queue.put_nowait(_RUN_DONE)
            if _run_queues.get(conv_id) is queue:
                _run_queues.pop(conv_id, None)
            _run_tasks.pop(conv_id, None)
            try:
                await asyncio.wait_for(taskbrain.finish(task_id, status), timeout=5)
            except Exception:  # noqa: BLE001 — ledger update is best-effort
                pass

    _run_tasks[conv_id] = asyncio.create_task(drive())
    return queue


async def observe(queue: asyncio.Queue) -> AsyncIterator[dict]:
    while True:
        event = await queue.get()
        if event is _RUN_DONE:
            return
        yield event


def is_running(conv_id: str) -> bool:
    """True if a detached generation for this conversation is still in flight."""
    return conv_id in _run_tasks


async def resume(conv_id: str) -> AsyncIterator[dict]:
    """Re-attach to an in-flight generation and stream its remaining events. If nothing is
    running, signal done immediately so the client just reloads the (saved) conversation."""
    queue = _run_queues.get(conv_id)
    if queue is None:
        yield stream_events.done()
        return
    yield stream_events.resumed()
    async for event in observe(queue):
        yield event
    yield stream_events.done()


def cancel_run(conv_id: str) -> None:
    """Explicitly stop a run (the Stop button) — different from a client just navigating away."""
    task = _run_tasks.pop(conv_id, None)
    _run_queues.pop(conv_id, None)
    if task and not task.done():
        task.cancel()
