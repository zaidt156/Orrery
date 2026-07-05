"""Automations: fixed-recipe visual workflows (a DAG of registered nodes) run as durable jobs.

Importing the package registers the built-in nodes.
"""
from backend.automation import nodes  # noqa: F401 — registers built-in nodes on import
from backend.automation.registry import Node, get_node, list_nodes, register_node  # noqa: F401
