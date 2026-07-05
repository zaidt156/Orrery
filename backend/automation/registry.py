"""Workflow node registry (conventions.md): one class + @register_node, and the canvas/engine
discover it — never a type-string switch. Keys are stable forever: they live in saved workflows."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Node:
    key: str = ""            # set by @register_node — persisted in workflow specs, never rename
    label: str = ""
    category: str = "logic"  # ai | data | code | net | logic | tools
    config_model: type[BaseModel] | None = None

    async def execute(self, inputs: dict, config: BaseModel | None) -> dict:
        """inputs = upstream outputs merged ({node_id: output, ...}); return this node's output."""
        raise NotImplementedError


_NODES: dict[str, Node] = {}


def register_node(key: str):
    def deco(cls: type[Node]) -> type[Node]:
        if key in _NODES:
            raise ValueError(f"Node key already registered: {key}")
        cls.key = key
        _NODES[key] = cls()
        return cls
    return deco


def get_node(key: str) -> Node | None:
    return _NODES.get(key)


def list_nodes() -> list[dict]:
    out: list[dict] = []
    for key, node in sorted(_NODES.items()):
        schema: dict[str, Any] = {}
        if node.config_model is not None:
            schema = node.config_model.model_json_schema()
        out.append({"key": key, "label": node.label or key, "category": node.category, "schema": schema})
    return out
