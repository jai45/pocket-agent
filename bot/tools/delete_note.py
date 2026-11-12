"""Delete a saved note."""

from bot import db
from bot.tool_context import ToolContext

SPEC = {
    "name": "delete_note",
    "description": "Delete a saved note by id. Find the id with search_notes first; never guess ids.",
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
}


def delete_note(id: int, ctx: ToolContext) -> dict:  # noqa: A002 - matches the tool schema
    conn = db.get_conn()
    row = conn.execute("SELECT title FROM notes WHERE id = ? AND chat_id = ?", (id, ctx.chat_id)).fetchone()
    if row is None:
        return {"error": f"no note with id {id}"}
    with conn:  # the notes_ad trigger removes it from the search index
        conn.execute("DELETE FROM notes WHERE id = ?", (id,))
    return {"deleted": id, "title": row["title"]}
