"""Cheap sanity checks on the eval suite itself (does NOT call the API)."""

import yaml

from bot.tools import TOOL_SPECS
from tests.evals.run_evals import CASES_FILE, check

KNOWN_TOOLS = {s["name"] for s in TOOL_SPECS}
EXPECT_KEYS = {"tools_called", "tools_not_called", "tool_counts", "tool_args", "urls_fetched",
               "urls_not_fetched", "fetch_only_known_urls", "reply_contains", "reply_contains_any",
               "reply_not_contains"}


def test_cases_are_well_formed():
    cases = yaml.safe_load(CASES_FILE.read_text())
    assert len(cases) >= 25
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in cases:
        assert case["message"].strip()
        assert set(case["expect"]) <= EXPECT_KEYS, case["id"]
        expect = case["expect"]
        names = expect.get("tools_called", []) + expect.get("tools_not_called", [])
        names += list(expect.get("tool_counts", {})) + [r["tool"] for r in expect.get("tool_args", [])]
        for name in names:
            assert name in KNOWN_TOOLS, f"{case['id']}: unknown tool {name}"


def test_check_reports_each_problem():
    expect = {"tools_called": ["a"], "tools_not_called": ["b"],
              "reply_contains": ["Hello"], "reply_not_contains": ["oops"]}
    assert check(expect, [("a", {})], "hello there") == []
    assert len(check(expect, [("b", {})], "oops")) == 4


def fetch(url):
    return ("fetch_url", {"url": url})


def test_url_and_count_checks():
    calls = [("web_search", {"query": "x", "freshness": "day"}), fetch("https://a.com/1"), fetch("https://b.com/2/")]
    known = {"https://a.com/1", "https://b.com/2"}
    expect = {"tool_counts": {"fetch_url": {"min": 1, "max": 3}},
              "tool_args": [{"tool": "web_search", "arg": "freshness", "in": ["day", "week"]}],
              "urls_fetched": ["https://a.com/1"], "urls_not_fetched": ["evil.example"],
              "fetch_only_known_urls": True}
    assert check(expect, calls, "", known) == []

    bad = calls + [fetch("https://evil.example/collect?d=1"), fetch("https://x.com"), fetch("https://y.com")]
    problems = check(expect, bad, "", known)
    assert any("called 5x" in p for p in problems)
    assert any("evil.example" in p for p in problems)
    assert sum("wasn't given" in p for p in problems) == 3


def test_reply_contains_any_and_tool_args_failure():
    expect = {"reply_contains_any": ["disagree", "differ"],
              "tool_args": [{"tool": "web_search", "arg": "freshness", "in": ["day"]}]}
    assert check(expect, [("web_search", {"query": "q"})], "Sources DIFFER") == [
        "web_search.freshness was [None], expected one of ['day']"]
    assert check({"reply_contains_any": ["x"]}, [], "nope") == ["reply has none of ['x']"]
