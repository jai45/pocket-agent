"""Telegram entry point: receives messages, keeps history, replies via Claude.

Run with:  python -m bot.main
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import config, llm

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

# chat_id -> list of {"role": ..., "content": ...}. In memory for Phase 0,
# so history is lost on restart; persistence comes in a later phase.
histories: dict[int, list[dict]] = {}


def is_allowed(update: Update) -> bool:
    """Only whitelisted users get a response; this bot spends real API money."""
    user = update.effective_user
    if user is None or user.id not in config.ALLOWED_USER_IDS:
        logger.debug("Ignoring message from user %s", user.id if user else None)
        return False
    return True


def trim_history(history: list[dict], limit: int = config.HISTORY_LIMIT) -> list[dict]:
    """Keep the last `limit` messages, making sure the first one is from the user.

    Trimming bounds cost and context size. The API rejects a conversation
    that starts with an assistant turn, so we drop any leading ones.
    """
    trimmed = history[-limit:]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed


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
        "Use /reset to clear our conversation."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forget this chat's history so the next message starts fresh."""
    if not is_allowed(update):
        return
    histories.pop(update.effective_chat.id, None)
    await update.message.reply_text("Conversation cleared. Fresh start!")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Append the user's message, ask Claude, store and send the reply."""
    if not is_allowed(update):
        return

    chat_id = update.effective_chat.id
    history = histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": update.message.text})
    history[:] = trim_history(history)

    typing = asyncio.create_task(keep_typing(context, chat_id))
    try:
        reply = await llm.chat(history)
    except Exception:
        # Undo the user turn so history keeps alternating user/assistant.
        history.pop()
        logger.exception("Model call failed for chat %s", chat_id)
        await update.message.reply_text("Sorry, something went wrong. Please try again.")
        return
    finally:
        typing.cancel()

    history.append({"role": "assistant", "content": reply})
    history[:] = trim_history(history)

    for chunk in split_message(reply):
        await update.message.reply_text(chunk)


def main() -> None:
    """Build the Telegram app and start long-polling for updates."""
    if not config.ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS is empty: the bot will ignore everyone.")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Pocket Agent starting (model=%s)", config.DEFAULT_MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
