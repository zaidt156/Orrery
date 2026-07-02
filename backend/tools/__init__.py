"""Shared tool registry package. Importing it registers the built-in tools."""
from backend.tools.registry import Tool, get_tool, list_tools, register_tool, run_tool  # noqa: F401
from backend.tools import builtin  # noqa: F401  — registers the built-in tools on import
