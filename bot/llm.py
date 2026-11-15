"""Thin wrapper around the Anthropic Messages API.

One place to call the model means one place for retries, prompt caching,
usage/cost recording and logging, so no caller can forget any of them.
"""

import asyncio
import logging
import random
import time

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message

from bot import config, usage
from bot.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# max_retries=0: we retry ourselves below. Leaving the SDK's own 2 retries on
# as well would multiply them (3 x 3 = up to 9 attempts per call).
_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=0)

CACHE = {"type": "ephemeral"}  # 5-minute prompt cache, refreshed on every hit
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 10.0
_sleep = asyncio.sleep  # tests replace this so retries don't really wait


class ModelUnavailable(Exception):
    """Claude stayed overloaded/rate-limited/unreachable after every retry."""


def is_retryable(exc: Exception) -> bool:
    """Retry problems on Anthropic's side or the network, never our own bad requests.

    429 rate limit, 529 overloaded and other 5xx errors usually clear up in
    seconds. A 400 (bad input) or 401 (bad key) will fail the same way every
    time, so retrying would only waste time.
    """
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def retry_delay(attempt: int, exc: Exception) -> float:
    """Seconds to wait before the next try: the server's retry-after, else 1s, 2s, ...

    The random jitter stops many clients that failed together from all
    retrying at the same instant and overloading the server again.
    """
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    try:
        if header is not None:
            return min(float(header), MAX_DELAY_SECONDS)
    except ValueError:
        pass  # an HTTP-date retry-after; fall back to our own schedule
    return min(BASE_DELAY_SECONDS * 2 ** (attempt - 1) + random.uniform(0, 0.5), MAX_DELAY_SECONDS)


def cached_system(system: str | list[dict]) -> list[dict]:
    """System prompt as blocks, with a cache breakpoint after the first one.

    A string becomes one cached block. A list is expected to be
    [fixed prompt, per-user facts]: only the fixed part is marked, so a new
    saved fact doesn't invalidate the cache for everything before it.
    """
    blocks = [{"type": "text", "text": system}] if isinstance(system, str) else [dict(b) for b in system]
    blocks[0]["cache_control"] = CACHE
    return blocks


def cached_tools(tools: list[dict]) -> list[dict]:
    """Mark the last tool: the cache prefix then covers every tool definition."""
    return tools[:-1] + [{**tools[-1], "cache_control": CACHE}]


def cached_messages(messages: list[dict]) -> list[dict]:
    """Mark the newest message so the next step of a tool loop reuses this prefix.

    Returns copies: the agent keeps appending to its own list, and markers
    left on old messages would pile up past the API's limit of 4.
    """
    if not messages:
        return messages
    last = dict(messages[-1])
    content = last["content"]
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content, "cache_control": CACHE}]
    elif content and isinstance(content[-1], dict):
        last["content"] = content[:-1] + [{**content[-1], "cache_control": CACHE}]
    return messages[:-1] + [last]


async def _send_with_retries(**request) -> tuple[Message, int]:
    """Call the API up to LLM_MAX_TRIES times; return (response, attempts used)."""
    for attempt in range(1, config.LLM_MAX_TRIES + 1):
        try:
            return await _client.messages.create(**request), attempt
        except Exception as exc:  # noqa: BLE001 - filtered by is_retryable
            if not is_retryable(exc):
                raise
            if attempt == config.LLM_MAX_TRIES:
                logger.error("model_unavailable model=%s attempts=%d error=%s",
                             request["model"], attempt, exc.__class__.__name__)
                raise ModelUnavailable(str(exc)) from exc
            delay = retry_delay(attempt, exc)
            logger.warning("model_retry model=%s attempt=%d error=%s wait_s=%.1f",
                           request["model"], attempt, exc.__class__.__name__, delay)
            await _sleep(delay)
    raise AssertionError("unreachable")


async def create(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
    model: str = config.DEFAULT_MODEL,
    system: str | list[dict] = SYSTEM_PROMPT,
) -> Message:
    """Send one request to Claude and return the full response.

    We return the whole Message (not just text) because the agent loop needs
    stop_reason and the tool_use blocks to decide what to do next.
    The API is stateless, so `messages` must contain everything Claude
    should see, starting with a user turn.
    Raises ModelUnavailable when retries run out.
    """
    kwargs: dict = {}
    if tools:
        kwargs["tools"] = cached_tools(tools)
    if tool_choice:
        kwargs["tool_choice"] = tool_choice

    start = time.perf_counter()
    response, attempts = await _send_with_retries(
        model=model,
        max_tokens=config.MAX_TOKENS,
        system=cached_system(system),
        messages=cached_messages(messages),
        output_config={"effort": config.EFFORT},
        **kwargs,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    cost = usage.record(model, response.usage)
    inp, out, cache_read, cache_write = usage.tokens_of(response.usage)

    tools_called = [b.name for b in response.content if b.type == "tool_use"]
    logger.info(
        "model_call model=%s input_tokens=%d output_tokens=%d cache_read=%d cache_write=%d "
        "cost_usd=%.5f tools=%s latency_ms=%.0f attempts=%d stop_reason=%s",
        response.model, inp, out, cache_read, cache_write, cost,
        tools_called, latency_ms, attempts, response.stop_reason,
    )
    return response


def response_text(response: Message) -> str:
    """Join the visible text blocks of a response (thinking blocks are skipped)."""
    return "".join(b.text for b in response.content if b.type == "text").strip()
