"""Thin wrapper around the Anthropic Messages API.

One place to call the model means one place to log usage and latency, which
is how we will later spot slow or expensive calls.
"""

import logging
import time

from anthropic import AsyncAnthropic

from bot import config
from bot.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# One shared client reuses its HTTP connection pool across calls.
_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)


async def chat(
    messages: list[dict],
    model: str = config.DEFAULT_MODEL,
    system: str = SYSTEM_PROMPT,
) -> str:
    """Send the conversation to Claude and return its text reply.

    The API is stateless, so `messages` must contain the whole history we
    want Claude to see, alternating user/assistant and starting with user.
    """
    start = time.perf_counter()
    response = await _client.messages.create(
        model=model,
        max_tokens=config.MAX_TOKENS,
        system=system,
        messages=messages,
        output_config={"effort": config.EFFORT},
    )
    latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "model_call model=%s input_tokens=%d output_tokens=%d tools=[] "
        "latency_ms=%.0f stop_reason=%s",
        response.model,
        response.usage.input_tokens,
        response.usage.output_tokens,
        latency_ms,
        response.stop_reason,
    )

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if response.stop_reason == "max_tokens":
        # Hitting the cap mid-answer (or mid-thinking) should be visible, not silent.
        text = (text + "\n\n…(reply cut off: hit the length limit)").strip()
    return text or "(no reply)"
