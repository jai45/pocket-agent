"""Save a note or link for later."""

from bot import db
from bot.notes_store import decode_tags, encode_tags
from bot.tool_context import ToolContext

MAX_NOTE_CHARS = 20_000

SPEC = {
    "name": "save_note",
    "description": (
        "Save a note, idea or link so it can be found later with search_notes. For "
        "a link, fetch_url first and save a short summary as the content with the "
        "url. Add a few lowercase tags (topics). Also used by quiz mode to save "
        "questions the user got wrong with the tag 'weak-spot'. Not for facts about "
        "the user themselves (use remember_fact) or tasks (use add_todo)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "url": {"type": "string", "description": "Optional source link."},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "content"],
    },
}


def save_note(title: str, content: str, ctx: ToolContext, url: str | None = None, tags: list[str] | None = None) -> dict:
    title, content = title.strip(), content.strip()
    if not title or not content:
        return {"error": "a note needs a title and content"}
    if len(content) > MAX_NOTE_CHARS:
        return {"error": f"content too long (max {MAX_NOTE_CHARS} characters); save a summary"}
    stored_tags = encode_tags(tags)
    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO notes (chat_id, title, content, url, tags) VALUES (?, ?, ?, ?, ?)",
            (ctx.chat_id, title, content, (url or "").strip() or None, stored_tags),
        )
    return {"id": cur.lastrowid, "title": title, "tags": decode_tags(stored_tags)}
