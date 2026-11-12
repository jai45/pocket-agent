"""Show the grocery list."""

from bot import db
from bot.tool_context import ToolContext

SPEC = {
    "name": "get_grocery_list",
    "description": (
        "Get the user's current grocery list with quantities. Use this, not "
        "conversation memory, whenever asked what's on the list."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def get_grocery_list(ctx: ToolContext) -> dict:
    rows = db.get_conn().execute(
        "SELECT name, quantity FROM grocery_items WHERE chat_id = ? ORDER BY id", (ctx.chat_id,)
    ).fetchall()
    items = [{"name": r["name"], "quantity": r["quantity"]} for r in rows]
    return {"items": items} if items else {"items": [], "note": "the grocery list is empty"}
