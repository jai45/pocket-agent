"""Retries and prompt-cache markers in bot/llm.py (the API is faked)."""

import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from bot import llm, timeutil, usage


def status_error(code, headers=None):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(code, headers=headers or {}, request=request)
    return anthropic.APIStatusError("boom", response=response, body=None)


def ok_response():
    return SimpleNamespace(
        model="claude-sonnet-5-5", stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="hi")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                              cache_read_input_tokens=7000, cache_creation_input_tokens=0),
    )


class FakeMessages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    async def create(self, **request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def fake_api(monkeypatch):
    sleeps = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(llm, "_sleep", no_sleep)

    def install(outcomes):
        messages = FakeMessages(outcomes)
        monkeypatch.setattr(llm, "_client", SimpleNamespace(messages=messages))
        return messages, sleeps
    return install


@pytest.mark.parametrize("code, retry", [(429, True), (529, True), (500, True), (503, True),
                                         (400, False), (401, False), (404, False)])
def test_which_status_codes_are_retried(code, retry):
    assert llm.is_retryable(status_error(code)) is retry


def test_connection_and_timeout_errors_are_retried():
    request = httpx.Request("POST", "https://api.anthropic.com")
    assert llm.is_retryable(anthropic.APIConnectionError(request=request))
    assert llm.is_retryable(anthropic.APITimeoutError(request=request))
    assert not llm.is_retryable(ValueError("ours"))


def test_retry_delay_honours_retry_after_and_caps_it():
    assert llm.retry_delay(1, status_error(429, {"retry-after": "3"})) == 3.0
    assert llm.retry_delay(1, status_error(429, {"retry-after": "120"})) == llm.MAX_DELAY_SECONDS
    assert 1.0 <= llm.retry_delay(1, status_error(529)) <= 1.5   # exponential backoff + jitter
    assert 2.0 <= llm.retry_delay(2, status_error(529)) <= 2.5


def test_overloaded_then_success_retries(fake_api):
    api, sleeps = fake_api([status_error(529), ok_response()])
    response = asyncio.run(llm.create([{"role": "user", "content": "hi"}]))
    assert response.stop_reason == "end_turn"
    assert len(api.requests) == 2 and len(sleeps) == 1


def test_gives_up_after_three_tries(fake_api):
    api, sleeps = fake_api([status_error(529)] * 3)
    with pytest.raises(llm.ModelUnavailable):
        asyncio.run(llm.create([{"role": "user", "content": "hi"}]))
    assert len(api.requests) == 3 and len(sleeps) == 2


def test_bad_request_is_not_retried(fake_api):
    api, _ = fake_api([status_error(400)])
    with pytest.raises(anthropic.APIStatusError):
        asyncio.run(llm.create([{"role": "user", "content": "hi"}]))
    assert len(api.requests) == 1


def test_every_call_is_recorded_in_usage(fake_api):
    fake_api([ok_response()])
    asyncio.run(llm.create([{"role": "user", "content": "hi"}], model="claude-sonnet-5-5"))
    today = timeutil.local_today()
    (row,) = usage.totals(today, today)
    assert row["calls"] == 1 and row["cache_read"] == 7000


def test_cache_markers_on_tools_system_and_last_message(fake_api):
    api, _ = fake_api([ok_response()])
    tools = [{"name": "a"}, {"name": "b"}]
    system = [{"type": "text", "text": "fixed"}, {"type": "text", "text": "facts"}]
    messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "x"},
                {"role": "user", "content": "new"}]
    asyncio.run(llm.create(messages, tools=tools, system=system))
    sent = api.requests[0]
    assert "cache_control" not in sent["tools"][0] and sent["tools"][1]["cache_control"] == llm.CACHE
    assert sent["system"][0]["cache_control"] == llm.CACHE and "cache_control" not in sent["system"][1]
    assert sent["messages"][-1]["content"] == [{"type": "text", "text": "new", "cache_control": llm.CACHE}]
    assert sent["messages"][0] == {"role": "user", "content": "old"}
    # Callers' objects are never modified (old markers would pile up past the limit of 4).
    assert tools[1] == {"name": "b"} and "cache_control" not in system[0]
    assert messages[-1] == {"role": "user", "content": "new"}


def test_cache_marker_on_last_block_of_tool_results():
    results = [{"type": "tool_result", "tool_use_id": "t1", "content": "1"},
               {"type": "tool_result", "tool_use_id": "t2", "content": "2"}]
    out = llm.cached_messages([{"role": "user", "content": results}])
    assert "cache_control" not in out[0]["content"][0]
    assert out[0]["content"][1]["cache_control"] == llm.CACHE
    assert "cache_control" not in results[1]


def test_plain_string_system_becomes_one_cached_block():
    assert llm.cached_system("Label this.") == [{"type": "text", "text": "Label this.", "cache_control": llm.CACHE}]
