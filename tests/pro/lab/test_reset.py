"""Fresh-start reset: archive the current Extreme Lab (and the frozen Research
archive) to a verified, WAL-consistent snapshot + manifest, then reinitialise a
clean $500 / 10-sleeve forward-paper experiment IN PLACE — preserving the schema
and settlement/idempotency protections, inventing no closing trades or fills.

Guarantees under test:
- Fresh portfolio: $500 equity/cash, $50 x 10, $0 realized, 0 positions, 0 trades,
  peak $500, threshold $450, entries PAUSED (manual), no inherited locks.
- Nothing invented: old open positions are NOT turned into closing trades.
- The archive preserves the old positions/trades/peak/audit for investigation.
- Settlement protection (settlements table + PK) survives the reset.
PAPER ONLY.
"""
import json
import sqlite3
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings, STRATEGIES
from paperbot_pro.lab.store import LabStore
from paperbot_pro.research.config import ResearchSettings
from paperbot_pro.research.store import ResearchStore
from paperbot_pro.reconcile import reconcile_lab
from paperbot_pro.lab.reset import reset_lab, plan_reset


def populated_lab(tmp_path):
    """A lab resembling the live merged state: drained cash, realized P&L, an
    open position, a closed trade, a raised peak."""
    cfg = replace(LabSettings(), db_path=str(tmp_path / "extreme.sqlite"))
    store = LabStore(cfg.db_path, cfg)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=0.51 WHERE key='breakout'")
        store.conn.execute("UPDATE strategies SET cash_usd=52.82, realized_pnl_usd=2.82 WHERE key='trend'")
        store.conn.execute(
            "INSERT INTO positions(strategy,symbol,side,leverage,qty,entry_price,margin_usd,"
            "notional_usd,stop,initial_stop,target,liq_price_est,entry_fee_usd,planned_risk_usd,"
            "opened_ms,signal_bar_ms,rationale,exchange,taker_fee,corr_cluster) "
            "VALUES('breakout','BNB/USDT:USDT','short',10,0.69,712.84,49.19,491.9,718.2,718.2,"
            "NULL,760,0.3,4,0,0,'t','bybit',0.0006,'')")
        store.conn.execute(
            "INSERT INTO trades(strategy,symbol,side,leverage,qty,entry_price,exit_price,"
            "stop_initial,stop_final,target,margin_usd,notional_usd,entry_fee_usd,exit_fee_usd,"
            "funding_usd,net_pnl_usd,entry_ms,exit_ms,exit_reason,rationale) "
            "VALUES('trend','SOL/USDT:USDT','long',10,1,100,102.82,95,95,NULL,10,100,0.06,0.06,"
            "0,2.82,0,1000,'STOP','t')")
    store.set("peak_equity", 524.56)
    store.set("peak_equity_pre_merge", 274.56)
    store.record_equity(1000, 500.5, 429.69, 72.69, -1.88, 524.56, 474.56)
    store.audit("warning", "accounting", "historical: double-close fix evidence")
    return store, cfg


def research_archive(tmp_path):
    cfg = replace(ResearchSettings(), db_path=str(tmp_path / "research.sqlite"))
    ResearchStore(cfg.db_path, cfg).close()
    return cfg.db_path


def test_reset_produces_clean_500_ten_sleeve_portfolio(tmp_path):
    store, cfg = populated_lab(tmp_path)
    archive = str(tmp_path / "archive")
    report = reset_lab(store, research_archive(tmp_path), archive, now_ms=5000)

    led = store.strategy_ledger()
    assert len(led) == 10
    assert all(s["cash_usd"] == pytest.approx(50.0) for s in led.values())
    assert all(s["realized_pnl_usd"] == 0.0 for s in led.values())
    assert all(not s.get("locked") for s in led.values())
    assert store.total_cash() == pytest.approx(500.0)
    assert store.get("peak_equity") == pytest.approx(500.0)
    assert store.get("lab_locked") is False
    assert store.get("lab_manual_pause") is True          # entries paused post-reset
    assert store.open_positions() == []                    # no inherited positions
    assert store.trades() == []                            # no inherited trades
    assert store.equity_history() == []                    # fresh curve
    assert report["fresh"]["threshold"] == pytest.approx(450.0)


def test_reset_invents_no_closing_trades(tmp_path):
    store, cfg = populated_lab(tmp_path)
    reset_lab(store, research_archive(tmp_path), str(tmp_path / "a"), now_ms=5000)
    # the archived BNB position must NOT have become a closing trade in the fresh DB
    assert store.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM settlements").fetchone()[0] == 0


def test_reset_fresh_db_reconciles(tmp_path):
    store, cfg = populated_lab(tmp_path)
    reset_lab(store, research_archive(tmp_path), str(tmp_path / "a"), now_ms=5000)
    rec = reconcile_lab(store, cfg)
    assert rec["ok"], rec["discrepancies"]
    assert rec["portfolio"]["equity_usd"] == pytest.approx(500.0)


def test_settlement_protection_survives_reset(tmp_path):
    store, cfg = populated_lab(tmp_path)
    reset_lab(store, research_archive(tmp_path), str(tmp_path / "a"), now_ms=5000)
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(settlements)")}
    assert "position_id" in cols
    # PK still enforced: a duplicate position_id is rejected
    with store.conn:
        store.conn.execute("INSERT INTO settlements VALUES(1,'X',1,'STOP')")
    with pytest.raises(sqlite3.IntegrityError):
        with store.conn:
            store.conn.execute("INSERT INTO settlements VALUES(1,'Y',2,'STOP')")


def test_archive_preserves_old_state_and_manifest(tmp_path):
    store, cfg = populated_lab(tmp_path)
    archive = str(tmp_path / "archive")
    reset_lab(store, research_archive(tmp_path), archive, now_ms=5000)

    import os
    arc = sqlite3.connect(f"file:{os.path.join(archive, 'extreme_lab.sqlite')}?mode=ro", uri=True)
    arc.row_factory = sqlite3.Row
    assert arc.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # old open position + trade + peak preserved in the archive
    assert [r["symbol"] for r in arc.execute("SELECT symbol FROM positions")] == ["BNB/USDT:USDT"]
    assert arc.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    assert json.loads(arc.execute("SELECT value FROM kv WHERE key='peak_equity'").fetchone()[0]) == pytest.approx(524.56)
    assert any("double-close" in r["message"] for r in arc.execute("SELECT message FROM audit_log"))

    manifest = json.load(open(os.path.join(archive, "manifest.json")))
    assert manifest["lab"]["peak_equity"] == pytest.approx(524.56)
    assert manifest["lab"]["open_positions"] == 1
    assert manifest["lab"]["total_cash"] == pytest.approx(0.51 + 52.82 + 50 * 8)
    assert manifest["fresh"]["total_cash"] == pytest.approx(500.0)


def test_reset_audit_entry_points_to_archive(tmp_path):
    store, cfg = populated_lab(tmp_path)
    archive = str(tmp_path / "archive")
    reset_lab(store, research_archive(tmp_path), archive, now_ms=5000)
    msgs = [r["message"] for r in store.audit_log()]
    assert any("FRESH START" in m and "archive" in m.lower() for m in msgs)


def test_plan_reset_dry_run_does_not_mutate(tmp_path):
    store, cfg = populated_lab(tmp_path)
    store.close()
    plan = plan_reset(cfg.db_path, research_archive(tmp_path))
    assert plan["dry_run"] is True
    assert plan["current"]["open_positions"] == 1
    assert plan["current"]["total_cash"] == pytest.approx(0.51 + 52.82 + 50 * 8)
    assert plan["fresh"]["total_cash"] == pytest.approx(500.0)
    assert plan["fresh"]["peak_equity"] == pytest.approx(500.0)
    # live DB still populated (untouched)
    reopened = LabStore(cfg.db_path, cfg)
    assert reopened.open_positions()[0]["symbol"] == "BNB/USDT:USDT"
    assert reopened.get("peak_equity") == pytest.approx(524.56)
