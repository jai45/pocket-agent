"""Tests for the agent loop with a fake model (no network).

FakeLLM returns scripted responses and records what the loop sent, so we can
check the loop's bookkeeping: tool_use_ids, parallel calls, the step limit.
"""

import asyncio
from types import SimpleNamespace

import pytest

from bot import agent, config, history


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(blocks, stop_reason):
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, messages, tools=None, tool_choice=None, system=None):
        self.calls.append({"messages": list(messages), "tool_choice": tool_choice, "system": system})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def clean_history():
    history.reset(1)
    yield
    history.reset(1)


def install(monkeypatch, responses):
    fake = FakeLLM(responses)
    monkeypatch.setattr(agent.llm, "create", fake.create)
    return fake


def test_plain_answer_without_tools(monkeypatch):
    fake = install(monkeypatch, [response([text_block("Hello!")], "end_turn")])
    result = asyncio.run(agent.run_agent(1, "hi"))
    assert result.text == "Hello!"
    assert result.trace == []
    assert len(fake.calls) == 1
    assert history.get_history(1)[-1] == {"role": "assistant", "content": "Hello!"}


def test_single_tool_call_then_answer(monkeypatch):
    fake = install(monkeypatch, [
        response([tool_block("t1", "calculate", {"expression": "6*7"})], "tool_use"),
        response([text_block("It's 42.")], "end_turn"),
    ])
    result = asyncio.run(agent.run_agent(1, "what is 6*7?"))
    assert result.text == "It's 42."
    assert [c.name for c in result.trace] == ["calculate"]

    # Second call must include the tool_result answering t1.
    tool_results = fake.calls[1]["messages"][-1]["content"]
    assert tool_results[0]["tool_use_id"] == "t1"
    assert '"result": 42' in tool_results[0]["content"]
    assert tool_results[0]["is_error"] is False


def test_multiple_tool_calls_in_one_turn_all_get_results(monkeypatch):
    fake = install(monkeypatch, [
        response([
            text_block("Let me check."),
            tool_block("a", "calculate", {"expression": "1+1"}),
            tool_block("b", "convert_units", {"value": 1, "from_unit": "km", "to_unit": "m"}),
        ], "tool_use"),
        response([text_block("2, and 1000 m.")], "end_turn"),
    ])
    result = asyncio.run(agent.run_agent(1, "two things"))
    tool_results = fake.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in tool_results] == ["a", "b"]
    assert len(result.trace) == 2


def test_tool_error_is_flagged(monkeypatch):
    fake = install(monkeypatch, [
        response([tool_block("x", "calculate", {"expression": "1/0"})], "tool_use"),
        response([text_block("Can't divide by zero.")], "end_turn"),
    ])
    result = asyncio.run(agent.run_agent(1, "1/0?"))
    assert fake.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert result.trace[0].error is True


def test_step_limit_forbids_tools_on_last_step(monkeypatch):
    looping = [response([tool_block(f"t{i}", "calculate", {"expression": "1"})], "tool_use")
               for i in range(config.MAX_AGENT_STEPS - 1)]
    fake = install(monkeypatch, looping + [response([text_block("Best I can do.")], "end_turn")])
    result = asyncio.run(agent.run_agent(1, "loop forever"))
    assert len(fake.calls) == config.MAX_AGENT_STEPS
    assert fake.calls[-1]["tool_choice"] == {"type": "none"}
    assert all(c["tool_choice"] is None for c in fake.calls[:-1])
    assert result.text == "Best I can do."


def test_history_is_text_with_a_tool_log(monkeypatch):
    install(monkeypatch, [
        response([tool_block("t1", "calculate", {"expression": "2"})], "tool_use"),
        response([text_block("2")], "end_turn"),
    ])
    asyncio.run(agent.run_agent(1, "q"))
    stored = history.get_history(1)
    assert [m["role"] for m in stored] == ["user", "system", "assistant"]
    assert all(isinstance(m["content"], str) for m in stored)
    assert "calculate(expression='2')" in stored[1]["content"]


def test_tool_log_reaches_the_next_request(monkeypatch):
    fake = install(monkeypatch, [
        response([tool_block("t1", "calculate", {"expression": "6*7"})], "tool_use"),
        response([text_block("The calculator says 42.")], "end_turn"),
        response([text_block("Yes, I checked.")], "end_turn"),
    ])
    asyncio.run(agent.run_agent(1, "6*7?"))
    asyncio.run(agent.run_agent(1, "did you really check?"))
    sent = fake.calls[2]["messages"]
    assert [m["role"] for m in sent] == ["user", "system", "assistant", "user"]
    assert '"result": 42' in sent[1]["content"]


def test_no_tool_log_when_no_tools_used(monkeypatch):
    install(monkeypatch, [response([text_block("Hi!")], "end_turn")])
    asyncio.run(agent.run_agent(1, "hello"))
    assert [m["role"] for m in history.get_history(1)] == ["user", "assistant"]


def test_tool_log_truncates_long_results():
    long_call = agent.ToolCall(1, "fetch_url", {"url": "u"}, "x" * 5000, False)
    log = agent.build_tool_log([long_call])
    assert len(log) < 500


def test_refusal_gets_polite_message(monkeypatch):
    install(monkeypatch, [response([], "refusal")])
    assert asyncio.run(agent.run_agent(1, "bad")).text == "Sorry, I can't help with that one."


def test_saved_facts_are_injected_into_the_system_prompt(monkeypatch):
    from bot import memory
    memory.add_fact(1, "Vegetarian")
    memory.add_fact(2, "Someone else's fact")
    fake = install(monkeypatch, [response([text_block("Try a lentil curry.")], "end_turn")])
    asyncio.run(agent.run_agent(1, "dinner idea?"))
    system = fake.calls[0]["system"]
    assert system.startswith("You are Pocket Agent")
    assert "Vegetarian" in system
    assert "Someone else's fact" not in system


def test_fact_saved_mid_conversation_shows_up_next_message(monkeypatch):
    fake = install(monkeypatch, [
        response([tool_block("t1", "remember_fact", {"fact": "Lives in Toronto"})], "tool_use"),
        response([text_block("📝 Noted: lives in Toronto (#1)")], "end_turn"),
        response([text_block("Toronto weather is…")], "end_turn"),
    ])
    asyncio.run(agent.run_agent(1, "I live in Toronto"))
    assert "Lives in Toronto" not in fake.calls[0]["system"]
    asyncio.run(agent.run_agent(1, "what's the weather like where I live?"))
    assert "#1 Lives in Toronto" in fake.calls[2]["system"]
