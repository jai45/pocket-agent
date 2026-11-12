"""Add items to the shared grocery list, merging duplicates."""

from bot import db
from bot.tool_context import ToolContext

SPEC = {
    "name": "add_grocery_items",
    "description": (
        "Add one or more items to the user's grocery list. Adding an item that is "
        "already on the list increases its quantity instead of duplicating it. Use "
        "short singular names ('egg', 'milk', 'tomato') so duplicates merge. Use "
        "for shopping-list items, not for to-dos or expenses."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "quantity": {"type": "integer", "description": "Default 1."},
                    },
                    "required": ["name"],
                },
            }
        },
        "required": ["items"],
    },
}


def normalise(name: str) -> str:
    """'  Oat  Milk ' -> 'oat milk', so the UNIQUE constraint can merge them."""
    return " ".join(name.lower().split())


def add_grocery_items(items: list, ctx: ToolContext) -> dict:
    """Upsert each item: insert, or add to the existing quantity."""
    if not isinstance(items, list) or not items:
        return {"error": "items must be a non-empty list"}
    parsed = []
    for item in items:
        if isinstance(item, str):  # tolerate ["milk", "eggs"]
            item = {"name": item}
        name = normalise(str(item.get("name", "")))
        quantity = item.get("quantity", 1)
        if not name:
            return {"error": "every item needs a name"}
        if not isinstance(quantity, int) or quantity < 1:
            return {"error": f"quantity for {name!r} must be a whole number of at least 1"}
        parsed.append((name, quantity))

    conn = db.get_conn()
    with conn:
        conn.executemany(
            "INSERT INTO grocery_items (chat_id, name, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id, name) DO UPDATE SET quantity = quantity + excluded.quantity",
            [(ctx.chat_id, name, qty) for name, qty in parsed],
        )
    names = sorted({name for name, _ in parsed})
    rows = conn.execute(
        f"SELECT name, quantity FROM grocery_items WHERE chat_id = ? AND name IN ({','.join('?' * len(names))})",
        (ctx.chat_id, *names),
    ).fetchall()
    size = conn.execute("SELECT COUNT(*) FROM grocery_items WHERE chat_id = ?", (ctx.chat_id,)).fetchone()[0]
    return {"added": [{"name": r["name"], "quantity": r["quantity"]} for r in rows], "list_size": size}
