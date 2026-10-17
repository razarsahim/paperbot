"""Phase 5: the per-cycle accounting-integrity monitor. A material ledger
inconsistency blocks NEW entries (via the governor) while leaving exits and
monitoring operational, writes ACCOUNTING_INTEGRITY_FAILURE, and preserves
records. Resuming requires a review/clear."""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.governor import LabGovernor
from paperbot_pro.lab.store import LabStore
from paperbot_pro.integrity import check_integrity


def make(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'))
    return LabStore(cfg.db_path, cfg), cfg


def test_clean_ledger_passes_and_does_not_lock(tmp_path):
    store, cfg = make(tmp_path)
    from paperbot_pro.reconcile import reconcile_lab
    res = check_integrity(store, cfg, reconcile_lab, now_ms=1000)
    assert res["ok"] is True
    assert store.get("integrity_locked") in (None, False)


def test_material_breach_blocks_new_entries_and_logs(tmp_path):
    store, cfg = make(tmp_path)
    from paperbot_pro.reconcile import reconcile_lab
    with store.conn:                       # inject a $20 over-credit
        store.conn.execute("UPDATE strategies SET cash_usd=cash_usd+20 WHERE key='trend'")
    res = check_integrity(store, cfg, reconcile_lab, now_ms=2000)
    assert res["ok"] is False
    assert store.get("integrity_locked") is True
    assert any("ACCOUNTING_INTEGRITY_FAILURE" in a["message"] for a in store.audit_log())
    # the governor must now reject new entries
    gov = LabGovernor(store, cfg)
    planned = {"symbol": "X/USDT:USDT", "strategy": "breakout",
               "planned_risk_usd": 1.0, "margin_usd": 5.0, "entry_fee_usd": 0.02}
    verdict = gov.approve(planned, now_ms=2000)
    assert not verdict.approved and "integrity" in verdict.reason.lower()


def test_immaterial_rounding_does_not_trip(tmp_path):
    store, cfg = make(tmp_path)
    from paperbot_pro.reconcile import reconcile_lab
    with store.conn:                       # sub-cent noise must not lock
        store.conn.execute("UPDATE strategies SET cash_usd=cash_usd+0.0005 WHERE key='trend'")
    res = check_integrity(store, cfg, reconcile_lab, now_ms=3000,
                          material_threshold_usd=0.01)
    assert res["ok"] is True
    assert store.get("integrity_locked") in (None, False)


def test_records_preserved_on_breach(tmp_path):
    store, cfg = make(tmp_path)
    from paperbot_pro.reconcile import reconcile_lab
    # a trade exists; the monitor must never delete/alter it
    with store.conn:
        store.conn.execute(
            "INSERT INTO trades(strategy,symbol,side,leverage,qty,entry_price,exit_price,"
            "stop_initial,stop_final,target,margin_usd,notional_usd,entry_fee_usd,exit_fee_usd,"
            "funding_usd,net_pnl_usd,entry_ms,exit_ms,exit_reason,rationale) VALUES"
            "('trend','Z/USDT:USDT','long',10,1,100,101,95,95,NULL,10,100,0.06,0.06,0,0.8,0,1,'STOP','t')")
        store.conn.execute("UPDATE strategies SET cash_usd=cash_usd+99 WHERE key='squeeze'")
    before = store.trades()
    check_integrity(store, cfg, reconcile_lab, now_ms=4000)
    assert store.trades() == before        # untouched


def test_clear_requires_note_and_reenables(tmp_path):
    store, cfg = make(tmp_path)
    from paperbot_pro.integrity import clear_integrity_lock
    store.set("integrity_locked", True)
    store.set("integrity_reason", "test")
    with pytest.raises(ValueError):
        clear_integrity_lock(store, note="")
    clear_integrity_lock(store, note="reviewed and corrected")
    assert store.get("integrity_locked") is False
    assert any("integrity lock cleared" in a["message"].lower() for a in store.audit_log())
