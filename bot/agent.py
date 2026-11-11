"""The agent loop: let Claude call tools until it has an answer.

Hand-written on purpose (no frameworks) so every step is visible.
Adding a tool never requires editing this file; see bot/tools/__init__.py.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field

from bot import config, history, llm
from bot.tools import TOOL_SPECS, is_error, run_tool

logger = logging.getLogger(__name__)

RESULT_PREVIEW_CHARS = 200
# Tool results kept in history are short: enough to prove what happened,
# without a fetched page eating the context on every later turn.
TOOL_LOG_RESULT_CHARS = 300


@dataclass
class ToolCall:
    """One tool call, kept for the /debug trace."""

    step: int
    name: str
    input: dict
    result: str
    error: bool


@dataclass
class AgentResult:
    """The final reply plus a record of the tools used to produce it."""

    text: str
    trace: list[ToolCall] = field(default_factory=list)


def _preview(text: str, limit: int = RESULT_PREVIEW_CHARS) -> str:
    """Shorten long tool results for logs and traces."""
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def build_tool_log(trace: list[ToolCall]) -> str | None:
    """Summarise this turn's tool calls as a note to keep in history."""
    if not trace:
        return None
    lines = ["Tools used to answer the user message above (recorded by the app):"]
    for call in trace:
        args = ", ".join(f"{k}={v!r}" for k, v in call.input.items())
        status = " (error)" if call.error else ""
        lines.append(f"- {call.name}({args}){status} -> {_preview(call.result, TOOL_LOG_RESULT_CHARS)}")
    return "\n".join(lines)


async def _run_tool_calls(step: int, tool_uses: list) -> tuple[list[dict], list[ToolCall]]:
    """Run every tool_use block from one turn concurrently.

    Claude can ask for several tools at once (e.g. the time AND a sum). They
    are independent, so we run them in parallel and return ALL results, each
    tagged with the tool_use_id it answers, in a single user message.
    """
    outputs = await asyncio.gather(*(run_tool(b.name, b.input) for b in tool_uses))

    results, calls = [], []
    for block, output in zip(tool_uses, outputs):
        failed = is_error(output)
        logger.info(
            "agent_step step=%d tool=%s input=%s result=%s",
            step, block.name, json.dumps(block.input, ensure_ascii=False), _preview(output),
        )
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": output,
            "is_error": failed,
        })
        calls.append(ToolCall(step, block.name, block.input, output, failed))
    return results, calls


async def run_agent(chat_id: int, user_text: str) -> AgentResult:
    """Answer one user message, calling tools as needed, and save the exchange."""
    messages = history.get_history(chat_id) + [{"role": "user", "content": user_text}]
    trace: list[ToolCall] = []
    text = ""

    for step in range(1, config.MAX_AGENT_STEPS + 1):
        last_step = step == config.MAX_AGENT_STEPS
        response = await llm.create(
            messages,
            tools=TOOL_SPECS,
            # On the final step, forbid tools so Claude must answer with what it has.
            tool_choice={"type": "none"} if last_step else None,
        )
        logger.info(
            "agent_turn step=%d stop_reason=%s input_tokens=%d output_tokens=%d",
            step, response.stop_reason, response.usage.input_tokens, response.usage.output_tokens,
        )

        # Echo the assistant turn back unchanged (thinking + tool_use blocks
        # included); the API needs it to match tool results to their calls.
        messages.append({"role": "assistant", "content": response.content})
        text = llm.response_text(response)

        if response.stop_reason != "tool_use":
            break

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        results, calls = await _run_tool_calls(step, tool_uses)
        trace.extend(calls)
        messages.append({"role": "user", "content": results})

    if response.stop_reason == "refusal":
        text = "Sorry, I can't help with that one."
    elif response.stop_reason == "max_tokens":
        text = (text + "\n\n…(reply cut off: hit the length limit)").strip()
    elif response.stop_reason == "tool_use":
        # Only reachable if the model ignored tool_choice=none on the last step.
        text = text or "I ran out of steps before finishing. Try a simpler request?"
    text = text or "(no reply)"

    history.add_exchange(chat_id, user_text, text, tool_log=build_tool_log(trace))
    return AgentResult(text=text, trace=trace)
