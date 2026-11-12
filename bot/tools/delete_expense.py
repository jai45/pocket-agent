"""Delete a mistaken expense."""

from bot import db, money
from bot.tool_context import ToolContext

SPEC = {
    "name": "delete_expense",
    "description": (
        "Delete one expense by id, e.g. when the user says an amount was wrong or "
        "logged twice. If you don't know the id, call expense_summary with "
        "include_items=true first. Never guess ids. To correct an amount, delete "
        "the old expense and add a new one."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "Expense id."}},
        "required": ["id"],
    },
}


def delete_expense(id: int, ctx: ToolContext) -> dict:  # noqa: A002 - matches the tool schema
    row = db.get_conn().execute(
        "SELECT * FROM expenses WHERE id = ? AND chat_id = ?", (id, ctx.chat_id)
    ).fetchone()
    if row is None:
        return {"error": f"no expense with id {id}"}
    conn = db.get_conn()
    with conn:
        conn.execute("DELETE FROM expenses WHERE id = ?", (id,))
    return {"deleted": id, "amount": money.format_money(row["amount_cents"]), "note": row["note"]}
