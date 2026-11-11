"""Convert Claude's Markdown into Telegram-safe HTML.

Telegram shows raw `**` unless a message declares a parse_mode. Its
MarkdownV2 mode needs `.`, `-`, `(` and more escaped, so ordinary model
output gets rejected. HTML mode only needs `<`, `>` and `&` escaped, so we
translate the handful of Markdown features Claude actually uses.
"""

import html
import re

# Placeholders protect code from the other rules; NUL never appears in replies.
_PH = "\x00{}\x00"

_CODE_BLOCK = re.compile(r"```[^\n`]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_BOLD = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*|__(?!\s)(.+?)(?<!\s)__")
# Single * or _ only counts as italic when it isn't inside a word, so
# 2*3*4 and snake_case_names are left alone.
_ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")


def markdown_to_telegram_html(text: str) -> str:
    """Translate common Markdown to Telegram HTML; everything else is escaped."""
    saved: list[str] = []

    def stash(fragment: str) -> str:
        saved.append(fragment)
        return _PH.format(len(saved) - 1)

    # 1. Pull code out first so nothing inside it gets formatted.
    text = _CODE_BLOCK.sub(lambda m: stash(f"<pre>{html.escape(m.group(1).rstrip())}</pre>"), text)
    text = _INLINE_CODE.sub(lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text)

    # 2. Escape the rest, then add our own tags.
    text = html.escape(text, quote=False)
    # The URL is already &-escaped by the line above; only quotes remain unsafe.
    text = _LINK.sub(
        lambda m: stash(f'<a href="{m.group(2).replace(chr(34), "&quot;")}">{m.group(1)}</a>'), text
    )
    text = _HEADING.sub(r"<b>\1</b>", text)
    text = _BULLET.sub(r"\1• ", text)  # before italics, so "* item" isn't italic
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)

    # 3. Put code and links back.
    for i, fragment in enumerate(saved):
        text = text.replace(_PH.format(i), fragment)
    return text
