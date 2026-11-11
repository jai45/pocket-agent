"""Telegram entry point: receives messages and replies via the agent loop.

Run with:  python -m bot.main
"""

import asyncio
import logging

from telegram import Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import config, db, history, reminders
from bot.agent import AgentResult, run_agent
from bot.telegram_format import markdown_to_telegram_html

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
# The HTTP libraries log full request URLs at INFO, and Telegram URLs contain
# the bot token. Silence them so the secret never lands in logs.
for noisy in ("httpx", "httpx2"):  # anthropic 1.x uses httpx2
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4096
# Split the Markdown below Telegram's limit: converting to HTML adds tags
# and escapes (& -> &amp;), so each chunk grows a little.
REPLY_CHUNK_CHARS = 3800

# Chats that asked for a tool trace after each reply (/debug). In memory.
debug_chats: set[int] = set()


def is_allowed(update: Update) -> bool:
    """Only whitelisted users get a response; this bot spends real API money."""
    user = update.effective_user
    if user is None or user.id not in config.ALLOWED_USER_IDS:
        logger.debug("Ignoring message from user %s", user.id if user else None)
        return False
    return True


def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split text into chunks Telegram will accept, preferring newline breaks.

    Breaking on a newline (or failing that, a space) keeps chunks readable
    instead of cutting words in half.
    """
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n ")
    if text:
        chunks.append(text)
    return chunks


async def send_formatted(message: Message, text: str) -> None:
    """Send Claude's Markdown reply as Telegram HTML, chunked.

    If Telegram rejects a chunk (e.g. a code block split across chunks left
    an unclosed tag), resend that chunk as plain text so no reply is lost.
    """
    for chunk in split_message(text, limit=REPLY_CHUNK_CHARS):
        try:
            await message.reply_text(markdown_to_telegram_html(chunk), parse_mode=ParseMode.HTML)
        except BadRequest as exc:
            logger.warning("HTML reply rejected (%s); sending plain text", exc)
            await message.reply_text(chunk)


async def keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Re-send "typing..." until cancelled.

    Telegram clears the indicator after ~5 seconds, but long replies can take
    30+ seconds, so a single send would leave the user staring at silence.
    """
    while True:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(4)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user."""
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "Hi! I'm Pocket Agent. Send me a message and I'll help out. "
        "Use /reset to clear our conversation and /debug to see which tools I use."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forget this chat's history so the next message starts fresh."""
    if not is_allowed(update):
        return
    history.reset(update.effective_chat.id)
    await update.message.reply_text("Conversation cleared. Fresh start!")


async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a short tool trace after each reply, to watch the agent work."""
    if not is_allowed(update):
        return
    chat_id = update.effective_chat.id
    if chat_id in debug_chats:
        debug_chats.discard(chat_id)
        await update.message.reply_text("Debug trace off.")
    else:
        debug_chats.add(chat_id)
        await update.message.reply_text("Debug trace on. I'll list the tools I call.")


def format_trace(result: AgentResult) -> str:
    """One line per tool call: step, name, input and a short result."""
    if not result.trace:
        return "🔧 no tools used"
    lines = []
    for call in result.trace:
        args = ", ".join(f"{k}={v!r}" for k, v in call.input.items())
        mark = "⚠️" if call.error else "→"
        result_text = call.result.replace("\n", " ")
        if len(result_text) > 80:
            result_text = result_text[:80] + "…"
        lines.append(f"🔧 {call.step}. {call.name}({args}) {mark} {result_text}")
    return "\n".join(lines)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run the agent on the user's message and send the reply (plus trace if on)."""
    if not is_allowed(update):
        return

    chat_id = update.effective_chat.id
    typing = asyncio.create_task(keep_typing(context, chat_id))
    try:
        result = await run_agent(chat_id, update.message.text)
    except Exception:
        # run_agent only saves history on success, so nothing to undo here.
        logger.exception("Agent failed for chat %s", chat_id)
        await update.message.reply_text("Sorry, something went wrong. Please try again.")
        return
    finally:
        typing.cancel()

    await send_formatted(update.message, result.text)
    if chat_id in debug_chats:
        for chunk in split_message(format_trace(result)):
            await update.message.reply_text(chunk)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the Done / Snooze buttons under a reminder (callback data 'rem:<action>:<id>')."""
    query = update.callback_query
    if not is_allowed(update):
        await query.answer()
        return
    _, action, raw_id = query.data.split(":")
    chat_id = query.message.chat.id
    handler = reminders.mark_done if action == "done" else reminders.snooze
    text = handler(int(raw_id), chat_id)
    if text is None:
        await query.answer("That reminder no longer exists.")
        await query.edit_message_reply_markup(reply_markup=None)
        return
    await query.answer()
    # Replacing the message text also removes the buttons, so they can't be tapped twice.
    await query.edit_message_text(text)


async def on_startup(app: Application) -> None:
    """Open the database and rebuild reminder jobs before polling starts.

    JobQueue jobs live in memory and vanish on restart; the database is the
    source of truth, so we reschedule everything from it here.
    """
    db.init()
    reminders.restore(app.job_queue)


def main() -> None:
    """Build the Telegram app and start long-polling for updates."""
    if not config.ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS is empty: the bot will ignore everyone.")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("debug", debug))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^rem:(done|snooze):\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Pocket Agent starting (model=%s)", config.DEFAULT_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
