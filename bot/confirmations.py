"""Pending actions that wait for the user's Yes/No tap.

The agent turn ENDS when a risky tool is requested; the action is parked in
the database. A later button tap runs it (or not) directly, without the
model. That is simpler than pausing the agent loop mid-turn, survives a
restart, and means the model can never "click Yes" for the user.
"""

import json
import logging
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot import db, history, timeutil
from bot.tool_context import ToolContext

logger = logging.getLogger(__name__)

EXPIRY_MINUTES = 10
DECLINED_TEXT = "Okay, I left it."
EXPIRED_TEXT = "That request expired. Ask me again if you still want it."
GONE_TEXT = "That request was already handled."


def create(chat_id: int, tool: str, tool_input: dict, summary: str) -> int:
    """Park one action; return its id (used in the button callback data)."""
    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO pending_actions (chat_id, tool, input, summary) VALUES (?, ?, ?, ?)",
            (chat_id, tool, json.dumps(tool_input, ensure_ascii=False), summary),
        )
    return cur.lastrowid


def get(action_id: int, chat_id: int):
    """Only the chat that created an action can see or resolve it."""
    return db.get_conn().execute(
        "SELECT * FROM pending_actions WHERE id = ? AND chat_id = ?", (action_id, chat_id)
    ).fetchone()


def question(action_id: int, chat_id: int) -> str | None:
    row = get(action_id, chat_id)
    return f"❓ Okay to {row['summary']}?" if row else None


def keyboard(action_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=f"confirm:yes:{action_id}"),
        InlineKeyboardButton("❌ No", callback_data=f"confirm:no:{action_id}"),
    ]])


def _expired(row) -> bool:
    created = timeutil.from_iso(row["created_at"].replace("Z", "+00:00"))
    return timeutil.utc_now() - created > timedelta(minutes=EXPIRY_MINUTES)


def _set_status(action_id: int, status: str) -> bool:
    """Move pending -> status. False if someone (a double tap) got there first."""
    conn = db.get_conn()
    with conn:
        cur = conn.execute(
            "UPDATE pending_actions SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            (status, timeutil.to_iso(timeutil.utc_now()), action_id),
        )
    return cur.rowcount == 1


def _result_text(summary: str, output: str) -> str:
    from bot.tools import is_error  # late import: bot.tools imports this module

    if is_error(output):
        return f"⚠️ Couldn't {summary}: {json.loads(output)['error']}"
    return f"✅ Done: {summary}."


async def resolve(action_id: int, chat_id: int, approved: bool) -> str:
    """Handle a Yes/No tap; return the text that replaces the question.

    The status flips BEFORE the tool runs, so two quick taps can't run it twice.
    The outcome is saved to history so the model sees it on the next message.
    """
    from bot.agent import ToolCall, build_tool_log  # late imports avoid a cycle
    from bot.tools import is_error, run_tool

    row = get(action_id, chat_id)
    if row is None or row["status"] != "pending":
        return GONE_TEXT
    if _expired(row):
        _set_status(action_id, "expired")
        return EXPIRED_TEXT
    if not _set_status(action_id, "confirmed" if approved else "declined"):
        return GONE_TEXT

    tool_input = json.loads(row["input"])
    label = f"{row['tool']} {row['input']}"
    if not approved:
        history.add_exchange(chat_id, f"[button: declined {label}]", DECLINED_TEXT)
        return DECLINED_TEXT

    output = await run_tool(row["tool"], tool_input, ToolContext(chat_id), confirmed=True)
    text = _result_text(row["summary"], output)
    log = build_tool_log([ToolCall(1, row["tool"], tool_input, output, is_error(output))])
    history.add_exchange(chat_id, f"[button: confirmed {label}]", text, tool_log=log)
    logger.info("confirmation chat=%s action=%s tool=%s approved=%s", chat_id, action_id, row["tool"], approved)
    return text
