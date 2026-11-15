"""Cost maths, usage recording and budget states (no network)."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from bot import config, usage


def api_usage(inp=0, out=0, cread=0, cwrite=0):
    return SimpleNamespace(input_tokens=inp, output_tokens=out,
                           cache_read_input_tokens=cread, cache_creation_input_tokens=cwrite)


def test_cost_uses_per_model_prices():
    # Sonnet: 1M in = $2, 1M out = $10, 1M cache read = $0.10, 1M cache write = $2.50
    assert usage.cost_usd("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.0)
    assert usage.cost_usd("claude-sonnet-5-5", 0, 1_000_000) == pytest.approx(10.0)
    assert usage.cost_usd("claude-sonnet-5-5", 0, 0, 1_000_000, 1_000_000) == pytest.approx(2.6)
    assert usage.cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.6)


def test_dated_model_id_matches_by_prefix_and_unknown_uses_highest_price():
    assert usage.prices_for("claude-haiku-5-5-20261001") == config.MODEL_PRICES["claude-haiku-5-5"]
    assert usage.prices_for("mystery-model")["output"] == 10.00


def test_missing_cache_fields_count_as_zero():
    assert usage.tokens_of(SimpleNamespace(input_tokens=5, output_tokens=2)) == (5, 2, 0, 0)
    assert usage.tokens_of(api_usage(1, 2, None, None)) == (1, 2, 0, 0)


def test_record_and_totals_per_model(freeze):
    freeze(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
    usage.record("claude-sonnet-5-5", api_usage(1000, 100, 5000, 0))
    usage.record("claude-sonnet-5-5", api_usage(1000, 100))
    usage.record("claude-haiku-5-5", api_usage(1000, 100))
    rows = {r["model"]: r for r in usage.totals(date(2026, 11, 14), date(2026, 11, 14))}
    assert rows["claude-sonnet-5-5"]["calls"] == 2
    assert rows["claude-sonnet-5-5"]["cache_read"] == 5000
    assert usage.spent_today() == pytest.approx(2 * 0.003 + 0.0005 + 0.0001 + 0.00005)


def test_budget_states(monkeypatch, freeze):
    freeze(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.0)
    usage.record("claude-sonnet-5-5", api_usage(0, 100_000))  # $1.00
    assert usage.budget_state() == usage.OK  # no budget set = no limit
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 2.0)
    assert usage.budget_state() == usage.OK
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 1.0)
    assert usage.budget_state() == usage.FAST
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.5)
    assert usage.budget_state() == usage.BLOCKED


def test_yesterdays_spend_does_not_count_today(monkeypatch, freeze):
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.5)
    freeze(datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
    usage.record("claude-sonnet-5-5", api_usage(0, 100_000))
    freeze(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
    assert usage.budget_state() == usage.OK


def test_cost_report_shows_today_month_and_savings(monkeypatch, freeze):
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 1.0)
    freeze(datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
    usage.record("claude-haiku-5-5", api_usage(1000, 1000))
    freeze(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
    usage.record("claude-sonnet-5-5", api_usage(100, 100, 10_000, 0))
    report = usage.cost_report()
    assert "Today: $0.0022 (1 calls)" in report
    assert "This month: $0.0028 (2 calls)" in report
    assert "caching saved about $0.0190" in report
    assert "Daily budget: $1.00 (normal)" in report
