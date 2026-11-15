"""Tool registry.

Each tool module exports SPEC (name, description, input_schema) and a
function with the same name as SPEC["name"]. To add a tool, create the file
and add it to TOOL_MODULES below; the agent loop never needs editing.

Tools that need harness facts (which chat this is) declare a `ctx`
parameter; run_tool passes the ToolContext only to those. `ctx` is never in
a SPEC, so the model can't supply or override it.

Risky tools set NEEDS_CONFIRMATION (True, or a function of the input) and
may define describe_action(...) -> str | {"error"} for the Yes/No question.
The flag lives next to SPEC, not inside it: the API rejects unknown fields
in a tool definition. When it applies, run_tool does NOT run the tool; it
saves a pending action and the bot asks the user with buttons. Only a tap
on Yes (bot.confirmations) runs it, with confirmed=True.
"""

import inspect
import json
import logging
from types import ModuleType
from typing import Any, Callable

from bot import confirmations
from bot.tool_context import ToolContext
from bot.tools import (
    add_expense,
    add_grocery_items,
    add_todo,
    calculate,
    cancel_reminder,
    clear_grocery_items,
    complete_todo,
    convert_units,
    delete_expense,
    delete_note,
    expense_summary,
    fetch_url,
    forget_fact,
    get_current_time,
    get_grocery_list,
    get_news,
    get_weather,
    list_reminders,
    list_todos,
    recall_facts,
    remember_fact,
    save_note,
    search_notes,
    set_reminder,
    update_note,
    web_search,
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
    add_expense,
    expense_summary,
    delete_expense,
    add_grocery_items,
    get_grocery_list,
    clear_grocery_items,
    save_note,
    search_notes,
    update_note,
    delete_note,
    remember_fact,
    recall_facts,
    forget_fact,
    get_weather,
    get_news,
    web_search,
]

# What we send to the API in the `tools` parameter.
TOOL_SPECS: list[dict] = [m.SPEC for m in TOOL_MODULES]

# name -> function, so dispatch is a dict lookup.
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    m.SPEC["name"]: getattr(m, m.SPEC["name"]) for m in TOOL_MODULES
}


_MODULES: dict[str, ModuleType] = {m.SPEC["name"]: m for m in TOOL_MODULES}

AWAITING = "awaiting_confirmation"


def needs_confirmation(name: str, tool_input: dict) -> bool:
    """Whether this call must wait for the user's Yes (e.g. only clear ALL groceries)."""
    flag = getattr(_MODULES.get(name), "NEEDS_CONFIRMATION", False)
    return bool(flag(tool_input)) if callable(flag) else bool(flag)


def _call_kwargs(func: Callable[..., Any], tool_input: dict, ctx: ToolContext | None) -> dict:
    """Model input minus any 'ctx' it tried to send, plus the real ctx if wanted."""
    kwargs = {k: v for k, v in tool_input.items() if k != "ctx"}  # model can't inject ctx
    if _wants_ctx(func):
        kwargs["ctx"] = ctx
    return kwargs


async def _call(func: Callable[..., Any], kwargs: dict) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(**kwargs)
    return func(**kwargs)


def _request_confirmation(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    """Validate and describe the action, then park it until the user taps Yes/No.

    describe_action runs first so a bad id fails now ("no reminder #9"),
    instead of showing buttons for something that can't happen.
    """
    describe = getattr(_MODULES[name], "describe_action", None)
    summary = f"run {name}"
    if describe is not None:
        described = describe(**_call_kwargs(describe, tool_input, ctx))
        if isinstance(described, dict):
            return described  # {"error": ...}
        summary = described
    action_id = confirmations.create(ctx.chat_id, name, tool_input, summary)
    return {
        "status": AWAITING,
        "confirmation_id": action_id,
        "action": summary,
        "note": "NOT done yet. The app is showing the user Yes/No buttons for this. "
                "Tell them in one short line what will happen if they tap Yes; "
                "don't ask again in text and don't say it is done.",
    }


def confirmation_id(result_text: str) -> int | None:
    """The pending action id if a tool result is an awaiting-confirmation result."""
    try:
        parsed = json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict) and parsed.get("status") == AWAITING:
        return parsed.get("confirmation_id")
    return None


def _to_text(result: Any) -> str:
    """tool_result content must be text; dicts become JSON."""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def _wants_ctx(func: Callable[..., Any]) -> bool:
    return "ctx" in inspect.signature(func).parameters


async def run_tool(
    name: str, tool_input: dict, ctx: ToolContext | None = None, confirmed: bool = False
) -> str:
    """Run a tool by name and always return text, never raise.

    A crash inside one tool should become an error message Claude can read
    and react to (retry, apologise, try another tool), not a dead bot.
    `confirmed=True` is passed only by the Yes button handler, never by the
    agent loop, so the model has no way to skip the confirmation.
    """
    func = _FUNCTIONS.get(name)
    if func is None:
        return _to_text({"error": f"Unknown tool: {name}"})
    if _wants_ctx(func) and ctx is None:
        return _to_text({"error": f"{name} needs a chat context"})
    try:
        if needs_confirmation(name, tool_input) and not confirmed:
            if ctx is None:
                return _to_text({"error": f"{name} needs a chat context"})
            result = _request_confirmation(name, tool_input, ctx)
        else:
            result = await _call(func, _call_kwargs(func, tool_input, ctx))
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
