"""Atomic, idempotent consolidation of the Research Lab into the Extreme Lab.

Correctness guarantees under test:
- No capital invented: combined allocation/cash = sum of the two labs.
- Transferred capital is NOT counted as profit (realized P&L is summed, not reset).
- HWM rebased by the research equity at consolidation (exact, since research
  equity is a constant through its history) -> threshold shifts by the same
  amount, so the $50 trailing distance is preserved.
- equity_history rebased so the combined curve is continuous.
- Existing Extreme positions and journal are untouched.
- Idempotent: running twice changes nothing.
PAPER ONLY.
"""
import sqlite3
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings, RESEARCH_KEYS
from paperbot_pro.lab.store import LabStore
from paperbot_pro.research.config import ResearchSettings
from paperbot_pro.research.store import ResearchStore
from paperbot_pro.lab.merge_migration import merge_research_into_lab


def pre_merge_lab(tmp_path, peak=274.56):
    """An Extreme Lab in its pre-merge shape: 5 extreme sleeves, a BNB position,
    some history. (A fresh LabStore seeds 10; delete the research rows.)"""
    cfg = replace(LabSettings(), db_path=str(tmp_path / "extreme.sqlite"))
    store = LabStore(cfg.db_path, cfg)
    with store.conn:
        store.conn.execute(f"DELETE FROM strategies WHERE key IN "
                           f"({','.join('?' * len(RESEARCH_KEYS))})", RESEARCH_KEYS)
        # trend booked +$2.82 realized via a closed trade, holds no open position
        store.conn.execute("UPDATE strategies SET cash_usd=52.82, realized_pnl_usd=2.82 "
                           "WHERE key='trend'")
        store.conn.execute(
            "INSERT INTO trades(strategy,symbol,side,leverage,qty,entry_price,exit_price,"
            "stop_initial,stop_final,target,margin_usd,notional_usd,entry_fee_usd,exit_fee_usd,"
            "funding_usd,net_pnl_usd,entry_ms,exit_ms,exit_reason,rationale) "
            "VALUES('trend','SOL/USDT:USDT','long',10,1,100,102.82,95,95,NULL,10,100,0.06,0.06,"
            "0,2.82,0,1000,'STOP','t')")
        store.conn.execute(
            "INSERT INTO positions(strategy,symbol,side,leverage,qty,entry_price,margin_usd,"
            "notional_usd,stop,initial_stop,target,liq_price_est,entry_fee_usd,planned_risk_usd,"
            "opened_ms,signal_bar_ms,rationale,exchange,taker_fee) "
            "VALUES('breakout','BNB/USDT:USDT','short',10,0.69,712.84,49.19,491.9,718.2,718.2,"
            "NULL,760,0.3,4,0,0,'t','bybit',0.0006)")
        # reserve the position's margin+fee from the breakout sleeve (cash identity)
        store.conn.execute("UPDATE strategies SET cash_usd = cash_usd - (49.19 + 0.3) "
                           "WHERE key='breakout'")
    store.set("peak_equity", peak)
    store.set("peak_equity_pre_correction", 275.76)
    store.record_equity(1000, 250.98, 199.17, 49.19, 2.62, peak, peak - 50)
    return store, cfg


def research_lab(tmp_path, **sleeve_overrides):
    cfg = replace(ResearchSettings(), db_path=str(tmp_path / "research.sqlite"))
    store = ResearchStore(cfg.db_path, cfg)
    store.log_signal(500, "regime_trend", "ETH/USDT:USDT", "long", False, "ADX low", "d")
    for key, (cash, realized) in sleeve_overrides.items():
        with store.conn:
            store.conn.execute("UPDATE strategies SET cash_usd=?, realized_pnl_usd=? WHERE key=?",
                               (cash, realized, key))
    path = cfg.db_path
    store.close()
    return path


def test_merge_combines_capital_without_inventing_or_profiting(tmp_path):
    lab, lab_cfg = pre_merge_lab(tmp_path)
    cash_before = lab.total_cash()
    research = research_lab(tmp_path)
    report = merge_research_into_lab(lab, research)

    led = lab.strategy_ledger()
    assert len(led) == 10
    assert sum(s["allocation_usd"] for s in led.values()) == pytest.approx(500.0)
    # exactly the research cash ($250) is added — no capital invented
    assert lab.total_cash() == pytest.approx(cash_before + 250.0)
    # realized P&L summed, NOT reset and NOT inflated by the $250 transfer
    assert sum(s["realized_pnl_usd"] for s in led.values()) == pytest.approx(2.82)
    assert report["capital_transferred_usd"] == pytest.approx(250.0)
    assert report["realized_pnl_after"] == pytest.approx(2.82)


def test_hwm_rebased_by_research_equity_preserving_distance(tmp_path):
    lab, lab_cfg = pre_merge_lab(tmp_path, peak=274.56)
    research = research_lab(tmp_path)
    merge_research_into_lab(lab, research)
    assert lab.get("peak_equity") == pytest.approx(524.56)       # 274.56 + 250
    assert lab.get("peak_equity_pre_merge") == pytest.approx(274.56)
    # the pre-correction audit value from the earlier fix is preserved
    assert lab.get("peak_equity_pre_correction") == pytest.approx(275.76)
    # equity_history rebased +250 (continuous combined curve)
    row = lab.equity_history()[-1]
    assert row["equity_usd"] == pytest.approx(250.98 + 250)
    assert row["peak_equity_usd"] == pytest.approx(524.56)
    assert row["threshold_usd"] == pytest.approx(474.56)


def test_existing_position_and_signals_preserved(tmp_path):
    lab, lab_cfg = pre_merge_lab(tmp_path)
    research = research_lab(tmp_path)
    before = lab.position("BNB/USDT:USDT")
    merge_research_into_lab(lab, research)
    after = lab.position("BNB/USDT:USDT")
    assert after["qty"] == before["qty"] and after["stop"] == before["stop"]
    assert after["margin_usd"] == before["margin_usd"]
    # research signal journal copied in
    assert any(s["strategy"] == "regime_trend" for s in lab.signals())


def test_preserves_actual_research_balances_not_assumed_50(tmp_path):
    lab, lab_cfg = pre_merge_lab(tmp_path)
    # a research sleeve that actually traded: $54 cash, +$4 realized
    research = research_lab(tmp_path, regime_trend=(54.0, 4.0))
    merge_research_into_lab(lab, research)
    led = lab.strategy_ledger()["regime_trend"]
    assert led["cash_usd"] == pytest.approx(54.0)
    assert led["realized_pnl_usd"] == pytest.approx(4.0)
    # capital transferred reflects the real research equity (254, not 250)
    # total realized now 2.82 + 4.0


def test_plan_merge_dry_run_does_not_mutate_live(tmp_path):
    from paperbot_pro.lab.merge_migration import plan_merge
    lab, lab_cfg = pre_merge_lab(tmp_path)
    lab.close()                       # close so the dry-run copies a quiescent file
    research = research_lab(tmp_path)
    plan = plan_merge(lab_cfg.db_path, research)
    assert plan["dry_run"] is True
    assert plan["before"]["strategies"] == 5
    assert plan["after"]["strategies"] == 10
    assert plan["after"]["reconciles"] is True
    assert plan["after"]["peak_equity"] == pytest.approx(524.56)
    # the LIVE extreme DB still shows the pre-merge state (untouched)
    reopened = LabStore(lab_cfg.db_path, lab_cfg)
    assert len(reopened.strategy_ledger()) == 5
    assert reopened.get("research_merged") is None


def test_migration_is_idempotent(tmp_path):
    lab, lab_cfg = pre_merge_lab(tmp_path)
    research = research_lab(tmp_path)
    merge_research_into_lab(lab, research)
    peak_after_first = lab.get("peak_equity")
    cash_after_first = lab.total_cash()
    report2 = merge_research_into_lab(lab, research)       # run again
    assert report2["already_merged"] is True
    assert lab.get("peak_equity") == pytest.approx(peak_after_first)   # not shifted twice
    assert lab.total_cash() == pytest.approx(cash_after_first)         # not added twice
    assert len(lab.strategy_ledger()) == 10
