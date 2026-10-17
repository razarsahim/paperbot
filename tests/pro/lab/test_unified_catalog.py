"""Unified Extreme Lab catalog: 10 strategies under one $500 portfolio.

The five original Extreme strategies (cohort 'extreme', $5 planned-risk cap, no
per-strategy floor lock) plus the five migrated Research strategies (cohort
'research', $2 cap, $30 equity-floor lock / $40 warning, correlation clusters).
PAPER ONLY."""
import pytest
from paperbot_pro.lab.config import STRATEGIES, LabSettings


EXTREME = {"breakout", "launch_sniper", "squeeze", "trend", "crash_reversal"}
RESEARCH = {"regime_trend", "volatility_breakout", "trend_pullback",
            "range_reversion", "orderflow_imbalance"}


def test_catalog_has_all_ten_strategies():
    keys = {s.key for s in STRATEGIES}
    assert keys == EXTREME | RESEARCH
    assert len(STRATEGIES) == 10  # no duplicates


def test_cohorts_tagged_correctly():
    by_key = {s.key: s for s in STRATEGIES}
    for k in EXTREME:
        assert by_key[k].cohort == "extreme"
    for k in RESEARCH:
        assert by_key[k].cohort == "research"


def test_per_cohort_risk_budget_and_floor_lock():
    by_key = {s.key: s for s in STRATEGIES}
    for k in EXTREME:
        assert by_key[k].risk_budget_usd == 5.0
        assert by_key[k].has_floor_lock is False
    for k in RESEARCH:
        assert by_key[k].risk_budget_usd == 2.0
        assert by_key[k].has_floor_lock is True


def test_orderflow_needs_orderbook():
    by_key = {s.key: s for s in STRATEGIES}
    assert by_key["orderflow_imbalance"].needs_orderbook is True
    assert by_key["breakout"].needs_orderbook is False


def test_combined_capital_is_500_over_ten_50_dollar_sleeves():
    cfg = LabSettings()
    assert cfg.allocation_per_strategy_usd == 50.0
    assert cfg.starting_capital_usd == 500.0
    cfg.validate()  # 50 * 10 == 500


def test_config_carries_research_cohort_settings():
    cfg = LabSettings()
    assert cfg.strategy_lock_floor_usd == 30.0        # $20 cumulative loss from $50
    assert cfg.strategy_warning_floor_usd == 40.0
    assert cfg.orderbook_fresh_seconds == 15
    # portfolio rails unchanged by owner decision
    assert cfg.max_open_positions == 3
    assert cfg.max_combined_risk_usd == 15.0
    assert cfg.trailing_drawdown_usd == 50.0
