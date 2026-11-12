"""List every saved fact about the user."""

from bot import memory
from bot.tool_context import ToolContext

SPEC = {
    "name": "recall_facts",
    "description": (
        "List ALL saved facts about the user with ids, newest first. Your "
        "instructions already show the newest few; call this when you need older "
        "ones, when the user asks what you remember, or to find an id for forget_fact."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def recall_facts(ctx: ToolContext) -> dict:
    facts = [
        {"id": f["id"], "fact": f["fact"], "saved": f["created_at"][:10]}
        for f in memory.list_facts(ctx.chat_id)
    ]
    return {"facts": facts} if facts else {"facts": [], "note": "no saved facts"}
