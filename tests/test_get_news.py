"""Tests for get_news with canned RSS/Atom feeds (no network)."""

import asyncio

import httpx
import pytest

from bot import config
from bot.tools import get_news as mod

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Example Tech</title>
<item><title>Old story</title><link>https://ex.com/old</link><pubDate>Mon, 09 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Newest   story</title><link>https://ex.com/new</link><pubDate>Fri, 13 Nov 2026 22:00:00 GMT</pubDate></item>
<item><title>Shared story</title><link>https://ex.com/shared</link><pubDate>Thu, 12 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Other Wire</title>
<entry><title>Shared story</title><link href="https://other.com/shared"/><updated>2026-11-12T09:00:00Z</updated></entry>
<entry><title>Undated story</title><link href="https://other.com/u"/></entry>
</feed>"""


@pytest.fixture(autouse=True)
def feeds(monkeypatch):
    monkeypatch.setattr(config, "NEWS_FEEDS", {"tech": ["https://a.test/rss", "https://b.test/atom"],
                                               "world": ["https://down.test/rss"]})


def use(monkeypatch, handler):
    monkeypatch.setattr(mod, "_transport", httpx.MockTransport(handler))


def feeds_handler(req):
    if req.url.host == "a.test":
        return httpx.Response(200, text=RSS)
    if req.url.host == "b.test":
        return httpx.Response(200, text=ATOM)
    return httpx.Response(500)


def test_merges_sorts_newest_first_and_dedupes(monkeypatch, london):
    use(monkeypatch, feeds_handler)
    result = asyncio.run(mod.get_news("tech", max_items=10))
    titles = [i["title"] for i in result["items"]]
    assert titles == ["Newest story", "Shared story", "Old story", "Undated story"]
    assert result["items"][0] == {"title": "Newest story", "source": "Example Tech",
                                  "link": "https://ex.com/new", "published": "Fri 13 Nov 22:00"}
    assert result["items"][-1]["published"] is None
    assert "unavailable_feeds" not in result


def test_max_items_is_respected_and_clamped(monkeypatch):
    use(monkeypatch, feeds_handler)
    assert len(asyncio.run(mod.get_news("tech", max_items=2))["items"]) == 2
    assert len(asyncio.run(mod.get_news("tech", max_items=0))["items"]) == 1


def test_one_failing_feed_is_reported_not_fatal(monkeypatch):
    def handler(req):
        if req.url.host == "b.test":
            raise httpx.ConnectError("down", request=req)
        return feeds_handler(req)
    use(monkeypatch, handler)
    result = asyncio.run(mod.get_news("tech"))
    assert len(result["items"]) == 3
    assert result["unavailable_feeds"] == ["https://b.test/atom"]


def test_all_feeds_failing(monkeypatch):
    use(monkeypatch, feeds_handler)
    assert "couldn't load" in asyncio.run(mod.get_news("world"))["error"]


def test_unknown_topic_lists_available():
    result = asyncio.run(mod.get_news("gardening"))
    assert "tech" in result["error"] and "world" in result["error"]
