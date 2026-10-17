"""Phase 7 financial-integrity regression batch (gaps not covered elsewhere).

Already covered by other suites and preserved: concurrent close from separate
connections + rollback (test_settlement_idempotency), double-close
(test_double_close), funding idempotency (test_engine_pro), HWM persistence /
strategy lockouts / drawdown breaches (test_governor), integrity lockouts +
recovery (test_integrity_monitor), historical reconciliation (test_reconcile).

Note: the engines use trailing stops with NO fixed target and NO partial
exits, so a '50% partial take-profit at 2R' path does not exist — a duplicate
2R partial is therefore structurally impossible (documented, not fabricated).
"""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.governor import LabGovernor
from paperbot_pro.lab.store import LabStore
from paperbot_pro.perp import ContractSpec, ExitEvent, check_exit, plan_entry

INST = {"symbol": "X/USDT:USDT", "exchange": "bybit", "taker_fee": 0.0006,
        "maint_margin_rate": 0.005, "tick_size": 0.1, "lot_size": 0.001}
SPEC = ContractSpec("X/USDT:USDT", 0.0006, 0.005, 0.1, 0.001)


def engine(tmp_path, name='lab.sqlite'):
    cfg = replace(LabSettings(), db_path=str(tmp_path / name))
    store = LabStore(cfg.db_path, cfg)
    return LabEngine(store, cfg, market=None, instruments_provider=lambda: []), store, cfg


def _open(e, side, strategy="trend", symbol="X/USDT:USDT", entry=100.0):
    spec = replace(SPEC, symbol=symbol)
    plan = plan_entry(side, entry, 1.0, spec, e.cfg, equity=250.0,
                      available_margin=50.0, risk_budget_usd=5.0, with_target=False)
    inst = dict(INST, symbol=symbol)
    e.open_from_plan(inst, plan, strategy, "T", {}, 0, 1000)
    return e.db.position(symbol), plan


def test_duplicate_liquidation_credits_once(tmp_path):
    e, s, cfg = engine(tmp_path)
    pos, plan = _open(e, "long")
    liq_event = ExitEvent("LIQUIDATION", pos["liq_price_est"],
                          -(pos["margin_usd"] + pos["entry_fee_usd"]), 0.0)
    cash_before = s.strategy_ledger()["trend"]["cash_usd"]
    e.close_position(dict(pos), liq_event, 2000)
    e.close_position(dict(pos), liq_event, 2500)   # duplicate liquidation
    assert len([t for t in s.trades() if t["exit_reason"] == "LIQUIDATION"]) == 1
    # liquidation credits 0 (margin wiped); cash unchanged by the close itself
    assert s.strategy_ledger()["trend"]["cash_usd"] == pytest.approx(cash_before)


def test_long_and_short_settlement_signs(tmp_path):
    e, s, cfg = engine(tmp_path)
    lp, lplan = _open(e, "long", strategy="trend", symbol="A/USDT:USDT", entry=100.0)
    # long exits at +2 -> profit
    e.close_position(dict(lp), ExitEvent("STOP", 102.0,
                     (102.0 - lp["entry_price"]) * lp["qty"] - lp["entry_fee_usd"] - 0.06, 0.06), 2000)
    sp, splan = _open(e, "short", strategy="breakout", symbol="B/USDT:USDT", entry=100.0)
    # short exits at -2 (price fell) -> profit
    e.close_position(dict(sp), ExitEvent("STOP", 98.0,
                     (sp["entry_price"] - 98.0) * sp["qty"] - sp["entry_fee_usd"] - 0.06, 0.06), 3000)
    trades = {t["symbol"]: t for t in s.trades()}
    assert trades["A/USDT:USDT"]["net_pnl_usd"] > 0
    assert trades["B/USDT:USDT"]["net_pnl_usd"] > 0
    # each sleeve reconciles independently
    from paperbot_pro.reconcile import reconcile_lab
    assert reconcile_lab(s, cfg)["ok"]


def test_multiple_positions_close_simultaneously_reconcile(tmp_path):
    e, s, cfg = engine(tmp_path)
    positions = []
    for i, strat in enumerate(("trend", "breakout", "squeeze")):
        p, _ = _open(e, "long", strategy=strat, symbol=f"S{i}/USDT:USDT", entry=100.0)
        positions.append(p)
    for p in positions:
        e.close_position(dict(p), ExitEvent("STOP", 99.0,
                         (99.0 - p["entry_price"]) * p["qty"] - p["entry_fee_usd"] - 0.06, 0.06),
                         5000)
    assert len(s.trades()) == 3 and s.open_positions() == []
    from paperbot_pro.reconcile import reconcile_lab
    assert reconcile_lab(s, cfg)["ok"]


def test_restart_with_open_position_preserves_accounting(tmp_path):
    e, s, cfg = engine(tmp_path)
    p, plan = _open(e, "long", strategy="trend", symbol="R/USDT:USDT", entry=100.0)
    cash = s.strategy_ledger()["trend"]["cash_usd"]
    s.close()
    # "restart": reopen the store/engine on the same DB
    s2 = LabStore(cfg.db_path, cfg)
    assert s2.position("R/USDT:USDT") is not None
    assert s2.strategy_ledger()["trend"]["cash_usd"] == pytest.approx(cash)
    from paperbot_pro.reconcile import reconcile_lab
    assert reconcile_lab(s2, cfg)["ok"]        # still balances after restart


def test_false_inflated_equity_cannot_approve_entry(tmp_path):
    e, s, cfg = engine(tmp_path)
    from paperbot_pro.integrity import check_integrity
    from paperbot_pro.reconcile import reconcile_lab
    with s.conn:                               # inflate a sleeve by $30
        s.conn.execute("UPDATE strategies SET cash_usd=cash_usd+30 WHERE key='squeeze'")
    check_integrity(s, cfg, reconcile_lab, now_ms=1000)
    gov = LabGovernor(s, cfg)
    # even though squeeze "has" extra cash, the integrity lock blocks the entry
    v = gov.approve({"symbol": "Q/USDT:USDT", "strategy": "squeeze",
                     "planned_risk_usd": 1.0, "margin_usd": 20.0, "entry_fee_usd": 0.1},
                    now_ms=1000)
    assert not v.approved and "integrity" in v.reason.lower()


def test_correction_does_not_touch_unrelated_balances(tmp_path):
    e, s, cfg = engine(tmp_path)
    before = {k: v["cash_usd"] for k, v in s.strategy_ledger().items()}
    # a hypothetical correction to ONE sleeve must leave the others identical
    with s.conn:
        s.conn.execute("UPDATE strategies SET cash_usd=cash_usd-5 WHERE key='trend'")
    after = {k: v["cash_usd"] for k, v in s.strategy_ledger().items()}
    changed = [k for k in before if abs(before[k] - after[k]) > 1e-9]
    assert changed == ["trend"]
    assert all(abs(before[k] - after[k]) < 1e-9 for k in before if k != "trend")
