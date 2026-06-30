"""Centralized chat stream event constructors.

The HTTP layer sends these dictionaries as SSE JSON payloads. Keep the legacy
wire shape stable: most events are still a single top-level key because the UI
already consumes them that way.
"""

from __future__ import annotations

from typing import Any, Literal

EventName = Literal[
    "artifact",
    "delta",
    "done",
    "error",
    "files",
    "message_id",
    "message_usage",
    "project",
    "reasoning_delta",
    "result",
    "resumed",
    "sources",
    "status",
    "svg",
    "title",
    "usage",
]

ChatEvent = dict[str, Any]


def _event(name: EventName, value: Any) -> ChatEvent:
    return {name: value}


def artifact(value: dict[str, Any]) -> ChatEvent:
    return _event("artifact", value)


def delta(text: str) -> ChatEvent:
    return _event("delta", text)


def done() -> ChatEvent:
    return _event("done", True)


def error(message: str) -> ChatEvent:
    return _event("error", message)


def files(items: list[dict[str, Any]]) -> ChatEvent:
    return _event("files", items)


def message_id(value: str) -> ChatEvent:
    return _event("message_id", value)


def message_usage(tokens_in: int | None, tokens_out: int | None, pricing_known: bool = True) -> ChatEvent:
    return _event(
        "message_usage",
        {
            "in": tokens_in or 0,
            "out": tokens_out or 0,
            "pricing_known": pricing_known,
        },
    )


def project(value: dict[str, Any]) -> ChatEvent:
    return _event("project", value)


def reasoning_delta(text: str) -> ChatEvent:
    return _event("reasoning_delta", text)


def result(value: dict[str, Any]) -> ChatEvent:
    return _event("result", value)


def resumed() -> ChatEvent:
    return _event("resumed", True)


def sources(items: list[str]) -> ChatEvent:
    return _event("sources", items)


def status(text: str) -> ChatEvent:
    return _event("status", text)


def svg(content: str) -> ChatEvent:
    return _event("svg", content)


def title(text: str) -> ChatEvent:
    return _event("title", text)


def usage(summary: dict[str, Any]) -> ChatEvent:
    return _event("usage", summary)


def missing_key(provider: str) -> ChatEvent:
    return error(f"No API key for {provider}. Add it in Settings.")
