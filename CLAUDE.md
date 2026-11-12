# Pocket Agent

A personal AI assistant I chat with on Telegram, built on the Anthropic API.
I am building it to LEARN agentic engineering, so clarity beats cleverness.

## Current phase

Phase 3 (see phase list below). Only build what the current phase asks for.

## Stack

- Python 3.11+, python-telegram-bot v21+ (async, with [job-queue] extra)
- anthropic Python SDK, SQLite via sqlite3, python-dotenv, pytest
- Models come from config.py: DEFAULT_MODEL (Sonnet) and FAST_MODEL (Haiku)

## Architecture rules (do not break)

1. The agent loop lives ONLY in bot/agent.py and is hand-written.
   No LangChain, LlamaIndex, CrewAI or other agent frameworks.
2. Every tool is a file in bot/tools/ exporting SPEC (name, description,
   input_schema) and a function. bot/tools/**init**.py builds the registry.
   Adding a tool must not require editing agent.py.
3. Tools return plain strings or JSON-serialisable dicts. On failure they
   return {"error": "..."}; they never raise into the loop.
4. The loop stops after MAX_AGENT_STEPS (default 8) and handles multiple
   tool_use blocks per turn, returning every tool_result with its tool_use_id.
5. All secrets come from .env. Never hard-code keys or print them in logs.
6. Only users in ALLOWED_USER_IDS get a response. Everyone else is ignored.
7. All times are stored in UTC and shown in TIMEZONE from .env.
8. Each Telegram chat keeps its own history, trimmed to the last 20 messages.

## Coding style

- Small functions, type hints, docstrings that explain WHY.
- Log every model call: model, input/output tokens, tools called, latency.
- Add a pytest test for every tool function (no network in tests; mock it).

## How to work with me

- Before coding, show a short plan and wait for my OK.
- After coding, tell me exactly how to run and test it on Telegram.
- Explain any agentic concept you use in 2-3 plain sentences.
- Commit-sized changes only. Never rewrite files outside the current phase.

## Phase list

0 Hello bot: Telegram <-> Claude chat with history
1 Tools: calculator, fetch_url/summarize link, current time
2 State: reminders (scheduled), to-do list
3 Memory: expenses, grocery list, saved notes/links, user profile facts
4 Multimodal: photos (vision), voice notes (transcribe then agent)
5 Proactive: morning briefing (weather, to-dos, news) on a schedule
6 Hardening: confirmations, cost caps, evals, logging, deployment
