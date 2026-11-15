"""Delete a saved fact about the user."""

from bot import memory
from bot.tool_context import ToolContext

SPEC = {
    "name": "forget_fact",
    "description": (
        "Delete a saved fact by id, when the user asks you to forget it or it is no "
        "longer true. Ids are shown next to each saved fact (or use recall_facts)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
}


NEEDS_CONFIRMATION = True


def describe_action(id: int, ctx: ToolContext) -> str | dict:  # noqa: A002
    fact = next((f["fact"] for f in memory.list_facts(ctx.chat_id) if f["id"] == id), None)
    if fact is None:
        return {"error": f"no saved fact with id {id}"}
    return f'forget fact #{id} "{fact}"'


def forget_fact(id: int, ctx: ToolContext) -> dict:  # noqa: A002 - matches the tool schema
    fact = memory.delete_fact(ctx.chat_id, id)
    if fact is None:
        return {"error": f"no saved fact with id {id}"}
    return {"forgotten": id, "fact": fact}
