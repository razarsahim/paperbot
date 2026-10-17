"""Read-only ledger reconciliation — the authoritative accounting identity
and discrepancy detection used by `propaper audit-accounting`."""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.store import LabStore
from paperbot_pro.reconcile import reconcile_lab


def open_pos(store, strategy, symbol, margin, entry_fee, funding_paid=0.0,
             qty=1.0, entry=100.0, entry_ms=1000):
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(strategy,symbol,side,leverage,qty,entry_price,
               margin_usd,notional_usd,stop,initial_stop,target,liq_price_est,
               entry_fee_usd,funding_paid_usd,planned_risk_usd,opened_ms,signal_bar_ms,
               rationale,exchange,taker_fee) VALUES(?,?,'long',10,?,?,?,?,95,95,NULL,90.5,
               ?,?,4,?,0,'T','bybit',0.0006)""",
            (strategy, symbol, qty, entry, margin, margin*10, entry_fee, funding_paid, entry_ms))
        store.conn.execute(
            "UPDATE strategies SET cash_usd=cash_usd-? WHERE key=?",
            (margin+entry_fee+funding_paid, strategy))


def close_trade(store, strategy, symbol, net_pnl, qty=1.0, entry=100.0,
                entry_ms=1000, exit_ms=2000):
    with store.conn:
        store.conn.execute(
            """INSERT INTO trades(strategy,symbol,side,leverage,qty,entry_price,exit_price,
               stop_initial,stop_final,target,margin_usd,notional_usd,entry_fee_usd,
               exit_fee_usd,funding_usd,net_pnl_usd,entry_ms,exit_ms,exit_reason,rationale)
               VALUES(?,?,'long',10,?,?,?,95,95,NULL,10,100,0.06,0.06,0,?,?,?,'STOP','t')""",
            (strategy, symbol, qty, entry, entry+net_pnl, net_pnl, entry_ms, exit_ms))
        store.conn.execute(
            "UPDATE strategies SET cash_usd=cash_usd+?, realized_pnl_usd=realized_pnl_usd+? WHERE key=?",
            (net_pnl, net_pnl, strategy))


def make(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'))
    return LabStore(cfg.db_path, cfg), cfg


def test_clean_ledger_reconciles(tmp_path):
    store, cfg = make(tmp_path)
    close_trade(store, 'trend', 'BTC/USDT:USDT', net_pnl=2.82)
    open_pos(store, 'breakout', 'BNB/USDT:USDT', margin=20.0, entry_fee=0.12)
    report = reconcile_lab(store, cfg)
    assert report['ok'] is True
    assert report['discrepancies'] == []
    # 500 (10 x $50 sleeves) + 2.82 realized - 0.12 entry fee on the open position
    assert report['portfolio']['equity_usd'] == pytest.approx(500.0 + 2.82 - 0.12)


def test_detects_cash_identity_breach(tmp_path):
    store, cfg = make(tmp_path)
    close_trade(store, 'trend', 'BTC/USDT:USDT', net_pnl=2.0)
    # inject a $20 over-credit like the double-close bug
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=cash_usd+20 WHERE key='trend'")
    report = reconcile_lab(store, cfg)
    assert report['ok'] is False
    d = next(x for x in report['discrepancies'] if x['strategy'] == 'trend')
    assert d['kind'] == 'cash_identity'
    assert d['impact_usd'] == pytest.approx(20.0)
    assert 'expected' in d and d['expected'] == pytest.approx(52.0)


def test_detects_duplicate_settlement(tmp_path):
    store, cfg = make(tmp_path)
    close_trade(store, 'trend', 'SOL/USDT:USDT', net_pnl=1.75, entry_ms=5000, exit_ms=6000)
    close_trade(store, 'trend', 'SOL/USDT:USDT', net_pnl=1.75, entry_ms=5000, exit_ms=6500)
    report = reconcile_lab(store, cfg)
    dup = [x for x in report['discrepancies'] if x['kind'] == 'duplicate_settlement']
    assert dup and 'SOL/USDT:USDT' in dup[0]['detail']


def test_detects_funding_mismatch(tmp_path):
    store, cfg = make(tmp_path)
    open_pos(store, 'trend', 'BTC/USDT:USDT', margin=10.0, entry_fee=0.06, funding_paid=0.5)
    pos_id = store.position('BTC/USDT:USDT')['id']
    # funding_events only record 0.2 but position claims 0.5 paid
    with store.conn:
        store.conn.execute("INSERT INTO funding_events VALUES(?,?,?,?)", (pos_id, 8*3_600_000, 0.0001, 0.2))
    report = reconcile_lab(store, cfg)
    fm = [x for x in report['discrepancies'] if x['kind'] == 'funding_mismatch']
    assert fm and fm[0]['impact_usd'] == pytest.approx(0.3)


def test_peak_below_recorded_equity_is_a_note_not_a_lock(tmp_path):
    """A peak BELOW a historically-recorded equity (e.g. after a legitimate
    downward peak correction, where old snapshots were inflated) only tightens
    protection — it must be an informational note, never a material
    discrepancy that trips the integrity lock."""
    store, cfg = make(tmp_path)
    store.record_equity(1000, 525.07, 500, 0, 0, 525.07, 475.07)  # inflated old snapshot
    store.set("peak_equity", 524.56)                               # corrected (lower) peak
    report = reconcile_lab(store, cfg)
    assert report["ok"] is True                                    # NOT a discrepancy
    assert not any(d["kind"] == "hwm_not_ratcheted" for d in report["discrepancies"])
    assert any("peak" in n.lower() for n in report["notes"])       # surfaced as a note


def test_peak_below_initial_is_a_real_discrepancy(tmp_path):
    store, cfg = make(tmp_path)
    store.set("peak_equity", 480.0)        # below the $500 starting capital = corruption
    report = reconcile_lab(store, cfg)
    assert not report["ok"]
    assert any(d["kind"] == "peak_below_initial" for d in report["discrepancies"])


def test_recommended_correction_present(tmp_path):
    store, cfg = make(tmp_path)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=cash_usd+5 WHERE key='squeeze'")
    report = reconcile_lab(store, cfg)
    d = report['discrepancies'][0]
    assert 'recommended_correction' in d and 'cash_usd' in d['recommended_correction']
