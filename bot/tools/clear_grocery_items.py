"""Remove bought items (or everything) from the grocery list."""

from bot import db
from bot.tool_context import ToolContext
from bot.tools.add_grocery_items import normalise

SPEC = {
    "name": "clear_grocery_items",
    "description": (
        "Remove items from the grocery list, e.g. after the user bought them. Pass "
        "items (names as on the list) to remove some, or all=true to empty the "
        "whole list. Only use all=true when the user clearly asks to clear everything."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "string"}},
            "all": {"type": "boolean", "description": "Remove every item. Default false."},
        },
    },
}


def clear_grocery_items(ctx: ToolContext, items: list[str] | None = None, all: bool = False) -> dict:  # noqa: A002
    conn = db.get_conn()
    if all:
        with conn:
            cur = conn.execute("DELETE FROM grocery_items WHERE chat_id = ?", (ctx.chat_id,))
        return {"cleared": "all", "removed_count": cur.rowcount}
    if not items:
        return {"error": "pass items to remove, or all=true"}
    removed, not_found = [], []
    with conn:
        for raw in items:
            name = normalise(raw)
            cur = conn.execute("DELETE FROM grocery_items WHERE chat_id = ? AND name = ?", (ctx.chat_id, name))
            (removed if cur.rowcount else not_found).append(name)
    result: dict = {"removed": removed}
    if not_found:
        result["not_on_list"] = not_found
    return result
