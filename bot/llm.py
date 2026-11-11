"""Thin wrapper around the Anthropic Messages API.

One place to call the model means one place to log usage and latency, which
is how we will later spot slow or expensive calls.
"""

import logging
import time

from anthropic import AsyncAnthropic
from anthropic.types import Message

from bot import config
from bot.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# One shared client reuses its HTTP connection pool across calls.
_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


async def create(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
    model: str = config.DEFAULT_MODEL,
    system: str = SYSTEM_PROMPT,
) -> Message:
    """Send one request to Claude and return the full response.

    We return the whole Message (not just text) because the agent loop needs
    stop_reason and the tool_use blocks to decide what to do next.
    The API is stateless, so `messages` must contain everything Claude
    should see, starting with a user turn.
    """
    kwargs: dict = {}
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice

    start = time.perf_counter()
    response = await _client.messages.create(
        model=model,
        max_tokens=config.MAX_TOKENS,
        system=system,
        messages=messages,
        output_config={"effort": config.EFFORT},
        **kwargs,
    )
    latency_ms = (time.perf_counter() - start) * 1000

    tools_called = [b.name for b in response.content if b.type == "tool_use"]
    logger.info(
        "model_call model=%s input_tokens=%d output_tokens=%d tools=%s "
        "latency_ms=%.0f stop_reason=%s",
        response.model,
        response.usage.input_tokens,
        response.usage.output_tokens,
        tools_called,
        latency_ms,
        response.stop_reason,
    )
    return response


def response_text(response: Message) -> str:
    """Join the visible text blocks of a response (thinking blocks are skipped)."""
    return "".join(b.text for b in response.content if b.type == "text").strip()
