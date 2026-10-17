"""Unified governor: one portfolio governor that applies per-cohort rules.

- Per-trade planned-risk cap is the SLEEVE's budget ($5 extreme / $2 research),
  carried on the planned dict as risk_budget_usd.
- Research sleeves lock at the $30 equity floor; extreme sleeves have no floor.
- Correlation-cluster limit applies when a planned entry carries a corr_cluster.
- Portfolio rails (3 slots, $15 combined risk, no duplicate symbol, trailing
  drawdown lock, integrity lock, manual pause) are shared and unchanged.
"""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.store import LabStore
from paperbot_pro.lab.governor import LabGovernor


def gov(tmp_path, **kw):
    cfg = replace(LabSettings(), db_path=str(tmp_path / "lab.sqlite"), **kw)
    store = LabStore(cfg.db_path, cfg)
    return LabGovernor(store, cfg), store, cfg


def planned(strategy, *, risk=1.0, margin=20.0, fee=0.05, symbol="BTC/USDT:USDT",
            budget=5.0, cluster=""):
    return {"strategy": strategy, "symbol": symbol, "planned_risk_usd": risk,
            "margin_usd": margin, "entry_fee_usd": fee, "risk_budget_usd": budget,
            "corr_cluster": cluster}


def test_per_trade_cap_is_the_sleeve_budget_not_global(tmp_path):
    g, store, cfg = gov(tmp_path)
    # research sleeve, $2 budget: $2.50 planned risk is rejected
    v = g.approve(planned("regime_trend", risk=2.5, budget=2.0), 1)
    assert not v.approved and "2" in v.reason
    # extreme sleeve, $5 budget: the same $2.50 is fine
    v = g.approve(planned("breakout", risk=2.5, budget=5.0), 1)
    assert v.approved


def test_research_sleeve_locks_at_30_floor_blocks_entry(tmp_path):
    g, store, cfg = gov(tmp_path)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=29 WHERE key='volatility_breakout'")
    v = g.approve(planned("volatility_breakout", budget=2.0), 1)
    assert not v.approved and "lock" in v.reason.lower()


def test_extreme_sleeve_has_no_floor_lock(tmp_path):
    g, store, cfg = gov(tmp_path)
    # extreme sleeve drained to $25 but still has cash for a tiny margin: allowed
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=25 WHERE key='breakout'")
    v = g.approve(planned("breakout", margin=20.0, fee=0.05, budget=5.0), 1)
    assert v.approved


def test_correlation_cluster_blocks_second_same_cluster_entry(tmp_path):
    g, store, cfg = gov(tmp_path)
    with store.conn:
        store.conn.execute(
            "INSERT INTO positions(strategy,symbol,side,leverage,qty,entry_price,margin_usd,"
            "notional_usd,stop,initial_stop,target,liq_price_est,entry_fee_usd,planned_risk_usd,"
            "opened_ms,signal_bar_ms,rationale,exchange,taker_fee,corr_cluster) "
            "VALUES('regime_trend','BTC/USDT:USDT','long',10,1,100,20,200,95,95,NULL,90,0.05,1,"
            "0,0,'t','bybit',0.0006,'BTC')")
    v = g.approve(planned("trend_pullback", symbol="BTCUP/USDT:USDT", budget=2.0, cluster="BTC"), 1)
    assert not v.approved and "correlated" in v.reason.lower()
    v = g.approve(planned("trend_pullback", symbol="ETH/USDT:USDT", budget=2.0, cluster="ETH"), 1)
    assert v.approved


def test_lock_strategy_and_equity_breaches(tmp_path):
    g, store, cfg = gov(tmp_path)
    eq = {"regime_trend": 29.0, "breakout": 5.0, "trend": 55.0}
    # only research sleeves at/below the $30 floor are breaches; extreme excluded
    breaches = g.strategy_equity_breaches(eq)
    assert "regime_trend" in breaches
    assert "breakout" not in breaches          # extreme cohort: no floor
    g.lock_strategy("regime_trend", "floor", 1)
    assert store.strategy_ledger()["regime_trend"]["locked"] == 1


def test_portfolio_rails_still_enforced(tmp_path):
    g, store, cfg = gov(tmp_path)
    # duplicate symbol
    with store.conn:
        store.conn.execute(
            "INSERT INTO positions(strategy,symbol,side,leverage,qty,entry_price,margin_usd,"
            "notional_usd,stop,initial_stop,target,liq_price_est,entry_fee_usd,planned_risk_usd,"
            "opened_ms,signal_bar_ms,rationale,exchange,taker_fee) "
            "VALUES('breakout','BTC/USDT:USDT','long',10,1,100,20,200,95,95,NULL,90,0.05,1,"
            "0,0,'t','bybit',0.0006)")
    v = g.approve(planned("trend", symbol="BTC/USDT:USDT"), 1)
    assert not v.approved and "already open" in v.reason
    # integrity lock blocks everything
    store.set("integrity_locked", True)
    assert not g.approve(planned("squeeze", symbol="SOL/USDT:USDT"), 1).approved
