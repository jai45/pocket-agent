"""Tests for Markdown -> Telegram HTML conversion."""

from bot.telegram_format import markdown_to_telegram_html as fmt


def test_bold_and_italic():
    assert fmt("The answer is **42** and *roughly* _done_") == (
        "The answer is <b>42</b> and <i>roughly</i> <i>done</i>")


def test_html_special_characters_are_escaped():
    assert fmt("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_bullets_become_dots_not_italics():
    assert fmt("- one\n* two\n  - nested") == "• one\n• two\n  • nested"


def test_headings_become_bold():
    assert fmt("## Summary\ntext") == "<b>Summary</b>\ntext"


def test_inline_code_is_not_formatted_inside():
    assert fmt("run `a**b**c < d`") == "run <code>a**b**c &lt; d</code>"


def test_code_block():
    assert fmt("```python\nx = 1 < 2\n```") == "<pre>x = 1 &lt; 2</pre>"


def test_link():
    assert fmt("see [the docs](https://example.com/a?b=1&c=2)") == (
        'see <a href="https://example.com/a?b=1&amp;c=2">the docs</a>')


def test_maths_and_snake_case_are_left_alone():
    assert fmt("2*3*4 = 24 and my_var_name") == "2*3*4 = 24 and my_var_name"


def test_the_reply_that_started_this():
    text = "The answer is about **702,803,659,163,083,067.699**.\n\n- 838283883 × 838383838 = 702,803,659,163,082,954 (exact)"
    assert fmt(text) == (
        "The answer is about <b>702,803,659,163,083,067.699</b>.\n\n"
        "• 838283883 × 838383838 = 702,803,659,163,082,954 (exact)")
