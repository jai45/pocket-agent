"""Cheap sanity checks on the eval suite itself (does NOT call the API)."""

import yaml

from bot.tools import TOOL_SPECS
from tests.evals.run_evals import CASES_FILE, check

KNOWN_TOOLS = {s["name"] for s in TOOL_SPECS}
EXPECT_KEYS = {"tools_called", "tools_not_called", "reply_contains", "reply_not_contains"}


def test_cases_are_well_formed():
    cases = yaml.safe_load(CASES_FILE.read_text())
    assert len(cases) >= 25
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in cases:
        assert case["message"].strip()
        assert set(case["expect"]) <= EXPECT_KEYS, case["id"]
        for name in case["expect"].get("tools_called", []) + case["expect"].get("tools_not_called", []):
            assert name in KNOWN_TOOLS, f"{case['id']}: unknown tool {name}"


def test_check_reports_each_problem():
    expect = {"tools_called": ["a"], "tools_not_called": ["b"],
              "reply_contains": ["Hello"], "reply_not_contains": ["oops"]}
    assert check(expect, ["a"], "hello there") == []
    assert len(check(expect, ["b"], "oops")) == 4
