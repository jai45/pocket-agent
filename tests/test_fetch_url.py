"""Tests for fetch_url using a mock HTTP transport (no real network)."""

import asyncio

import httpx
import pytest

from bot.tools import fetch_url as mod

ARTICLE = """<html><head><title>Lighthouses of Maine</title></head><body>
<nav>Home | About</nav>
<article><h1>Lighthouses of Maine</h1>
<p>Maine has more than sixty lighthouses along its rocky coast. Many were built in
the nineteenth century to guide fishing boats and cargo ships through fog.</p>
<p>Portland Head Light, first lit in 1791, is the oldest lighthouse in the state and
one of the most photographed in the United States.</p>
<p>Today most lights are automated, but several keepers' houses are now museums
that welcome visitors throughout the summer season.</p></article>
<footer>Copyright</footer></body></html>"""


def _use_transport(monkeypatch, handler):
    monkeypatch.setattr(mod, "_transport", httpx.MockTransport(handler))


def test_extracts_title_and_text(monkeypatch):
    _use_transport(monkeypatch, lambda req: httpx.Response(
        200, text=ARTICLE, headers={"content-type": "text/html; charset=utf-8"}))
    result = asyncio.run(mod.fetch_url("https://example.com/maine"))
    assert result["title"] == "Lighthouses of Maine"
    assert "Portland Head Light" in result["text"]
    assert result["truncated"] is False


def test_long_text_is_truncated(monkeypatch):
    long_article = ARTICLE.replace("</article>", "<p>" + "Fog horn. " * 2000 + "</p></article>")
    _use_transport(monkeypatch, lambda req: httpx.Response(
        200, text=long_article, headers={"content-type": "text/html"}))
    result = asyncio.run(mod.fetch_url("https://example.com/long"))
    assert len(result["text"]) == mod.MAX_CHARS
    assert result["truncated"] is True


def test_http_error_status(monkeypatch):
    _use_transport(monkeypatch, lambda req: httpx.Response(404, text="nope"))
    assert asyncio.run(mod.fetch_url("https://example.com/missing")) == {
        "error": "HTTP 404 fetching https://example.com/missing"}


def test_timeout(monkeypatch):
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)
    _use_transport(monkeypatch, handler)
    assert "timed out" in asyncio.run(mod.fetch_url("https://example.com/slow"))["error"]


def test_non_html_is_refused(monkeypatch):
    _use_transport(monkeypatch, lambda req: httpx.Response(
        200, content=b"%PDF", headers={"content-type": "application/pdf"}))
    assert "not a web page" in asyncio.run(mod.fetch_url("https://example.com/a.pdf"))["error"]


@pytest.mark.parametrize("url", ["ftp://example.com/x", "example.com", "file:///etc/passwd"])
def test_bad_scheme(url):
    assert "error" in asyncio.run(mod.fetch_url(url))


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/", "http://192.168.1.1/", "http://[::1]/"])
def test_private_addresses_are_refused(url):
    # _transport is None here, so the real address check runs (IP literals: no DNS).
    assert "private" in asyncio.run(mod.fetch_url(url))["error"]
