"""Sending Claude's replies to Telegram: chunking and Markdown -> HTML.

Shared by message handlers (which reply to a message) and scheduled jobs
(which have no message to reply to, so they call bot.send_message). Both
pass in a `send` function, so the formatting logic exists once.
"""

import logging
from collections.abc import Awaitable, Callable

from telegram.constants import ParseMode
from telegram.error import BadRequest

from bot.telegram_format import markdown_to_telegram_html

logger = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4096
# Split the Markdown below Telegram's limit: converting to HTML adds tags
# and escapes (& -> &amp;), so each chunk grows a little.
REPLY_CHUNK_CHARS = 3800


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


Send = Callable[..., Awaitable[object]]


async def send_markdown(send: Send, text: str) -> None:
    """Send Claude's Markdown reply as Telegram HTML, chunked.

    `send` is message.reply_text or functools.partial(bot.send_message, chat_id).
    If Telegram rejects a chunk (e.g. a code block split across chunks left
    an unclosed tag), resend that chunk as plain text so no reply is lost.
    """
    for chunk in split_message(text, limit=REPLY_CHUNK_CHARS):
        try:
            await send(markdown_to_telegram_html(chunk), parse_mode=ParseMode.HTML)
        except BadRequest as exc:
            logger.warning("HTML reply rejected (%s); sending plain text", exc)
            await send(chunk)
