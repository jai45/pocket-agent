"""Tool registry.

Each tool module exports SPEC (name, description, input_schema) and a
function with the same name as SPEC["name"]. To add a tool, create the file
and add it to TOOL_MODULES below; the agent loop never needs editing.

Tools that need harness facts (which chat this is) declare a `ctx`
parameter; run_tool passes the ToolContext only to those. `ctx` is never in
a SPEC, so the model can't supply or override it.
"""

import inspect
import json
import logging
from types import ModuleType
from typing import Any, Callable

from bot.tool_context import ToolContext
from bot.tools import (
    add_todo,
    calculate,
    cancel_reminder,
    complete_todo,
    convert_units,
    fetch_url,
    get_current_time,
    list_reminders,
    list_todos,
    set_reminder,
)

logger = logging.getLogger(__name__)

TOOL_MODULES: list[ModuleType] = [
    calculate,
    convert_units,
    fetch_url,
    get_current_time,
    set_reminder,
    list_reminders,
    cancel_reminder,
    add_todo,
    list_todos,
    complete_todo,
]

# What we send to the API in the `tools` parameter.
TOOL_SPECS: list[dict] = [m.SPEC for m in TOOL_MODULES]

# name -> function, so dispatch is a dict lookup.
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    m.SPEC["name"]: getattr(m, m.SPEC["name"]) for m in TOOL_MODULES
}


def _to_text(result: Any) -> str:
    """tool_result content must be text; dicts become JSON."""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def _wants_ctx(func: Callable[..., Any]) -> bool:
    return "ctx" in inspect.signature(func).parameters


async def run_tool(name: str, tool_input: dict, ctx: ToolContext | None = None) -> str:
    """Run a tool by name and always return text, never raise.

    A crash inside one tool should become an error message Claude can read
    and react to (retry, apologise, try another tool), not a dead bot.
    """
    func = _FUNCTIONS.get(name)
    if func is None:
        return _to_text({"error": f"Unknown tool: {name}"})
    kwargs = {k: v for k, v in tool_input.items() if k != "ctx"}  # model can't inject ctx
    if _wants_ctx(func):
        if ctx is None:
            return _to_text({"error": f"{name} needs a chat context"})
        kwargs["ctx"] = ctx
    try:
        if inspect.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            result = func(**kwargs)
    except TypeError as exc:
        # Usually Claude sent wrong or missing arguments.
        return _to_text({"error": f"Bad input for {name}: {exc}"})
    except Exception as exc:  # noqa: BLE001 - tools must never crash the loop
        logger.exception("Tool %s raised", name)
        return _to_text({"error": f"{name} failed: {exc}"})
    return _to_text(result)


def is_error(result_text: str) -> bool:
    """True if a tool result is our {"error": ...} shape."""
    try:
        parsed = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, dict) and "error" in parsed
