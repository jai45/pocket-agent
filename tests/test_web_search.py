"""Tests for web_search with a mock HTTP transport (no network, fake key)."""

import asyncio
import json

import httpx
import pytest

from bot import config
from bot.tools import web_search as mod

BRAVE = {
    "query": {"original": "starship launch"},
    "web": {"results": [
        {"title": "Starship <strong>launch</strong> recap", "url": "https://news.test/starship",
         "description": "SpaceX&#39;s <strong>Starship</strong> flew  again.", "age": "2 hours ago"},
        {"title": "Starship - Wikipedia", "url": "https://en.wikipedia.org/wiki/SpaceX_Starship",
         "description": "Super heavy-lift launch vehicle."},
        {"title": "No URL entry", "description": "skipped"},
    ]},
}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(config, "BRAVE_API_KEY", "test-key")


def use(monkeypatch, handler):
    monkeypatch.setattr(mod, "_transport", httpx.MockTransport(handler))


def test_results_are_cleaned_and_shaped(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=BRAVE)

    use(monkeypatch, handler)
    result = asyncio.run(mod.web_search("  starship   launch ", max_results=3, freshness="week"))
    assert result["query"] == "starship launch"
    assert result["results"] == [
        {"title": "Starship launch recap", "url": "https://news.test/starship",
         "snippet": "SpaceX's Starship flew again.", "age": "2 hours ago"},
        {"title": "Starship - Wikipedia", "url": "https://en.wikipedia.org/wiki/SpaceX_Starship",
         "snippet": "Super heavy-lift launch vehicle."},
    ]
    req = seen[0]
    assert req.url.params["q"] == "starship launch"
    assert req.url.params["count"] == "3"
    assert req.url.params["freshness"] == "pw"
    assert req.headers["X-Subscription-Token"] == "test-key"


def test_max_results_is_clamped(monkeypatch):
    seen = []
    use(monkeypatch, lambda req: seen.append(req) or httpx.Response(200, json=BRAVE))
    asyncio.run(mod.web_search("x", max_results=99))
    asyncio.run(mod.web_search("x", max_results=0))
    assert [r.url.params["count"] for r in seen] == ["10", "1"]


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(config, "BRAVE_API_KEY", "")
    assert "BRAVE_API_KEY" in asyncio.run(mod.web_search("anything"))["error"]


@pytest.mark.parametrize("status,phrase", [(401, "API key"), (403, "API key"), (429, "rate limit"),
                                           (500, "HTTP 500")])
def test_http_errors(monkeypatch, status, phrase):
    use(monkeypatch, lambda req: httpx.Response(status, json={"error": "x"}))
    error = asyncio.run(mod.web_search("anything"))["error"]
    assert phrase in error
    assert "test-key" not in error  # the secret is never echoed


def test_timeout_and_bad_json(monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)
    use(monkeypatch, slow)
    assert "timed out" in asyncio.run(mod.web_search("x"))["error"]
    use(monkeypatch, lambda req: httpx.Response(200, text="<html>not json"))
    assert "unreadable" in asyncio.run(mod.web_search("x"))["error"]


def test_no_results(monkeypatch):
    use(monkeypatch, lambda req: httpx.Response(200, json={"web": {"results": []}}))
    assert asyncio.run(mod.web_search("zxqv"))["note"].startswith("no results")


def test_input_validation():
    assert "empty" in asyncio.run(mod.web_search("   "))["error"]
    assert "too long" in asyncio.run(mod.web_search("x" * 500))["error"]
    assert "freshness" in asyncio.run(mod.web_search("x", freshness="hour"))["error"]
