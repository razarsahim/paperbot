"""DB-level settlement idempotency: two SEPARATE connections (simulating two
processes/async tasks) cannot both settle the same position. The settlements
table's position_id PRIMARY KEY enforces this at the database level, beyond
the in-connection rowcount guard."""
import sqlite3
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.store import LabStore
from paperbot_pro.perp import ExitEvent, plan_entry
from paperbot_pro.perp import ContractSpec

SPEC = ContractSpec("SOL/USDT:USDT", 0.0006, 0.005, 0.1, 0.001)
INST = {"symbol": "SOL/USDT:USDT", "exchange": "bybit", "taker_fee": 0.0006,
        "maint_margin_rate": 0.005, "tick_size": 0.1, "lot_size": 0.001}


def _engine(path):
    cfg = replace(LabSettings(), db_path=path)
    store = LabStore(path, cfg)
    return LabEngine(store, cfg, market=None, instruments_provider=lambda: []), store, cfg


def test_two_connections_cannot_both_settle(tmp_path):
    path = str(tmp_path / 'lab.sqlite')
    e1, s1, cfg = _engine(path)
    plan = plan_entry("short", 104.6, 1.0, SPEC, cfg, equity=250.0,
                      available_margin=50.0, risk_budget_usd=5.0, with_target=False)
    e1.open_from_plan(INST, plan, "trend", "T", {}, 0, 1000)
    cash0 = s1.strategy_ledger()["trend"]["cash_usd"]
    pos = s1.position("SOL/USDT:USDT")

    # a SECOND engine on its own connection to the same DB file (= 2nd process)
    e2, s2, _ = _engine(path)
    pos2 = s2.position("SOL/USDT:USDT")
    event = ExitEvent("EMERGENCY", 103.5, 1.0, 0.06)

    e1.close_position(dict(pos), event, 2000)
    e2.close_position(dict(pos2), event, 3000)   # different connection, same position

    # exactly one trade, credited once, regardless of which connection we read
    assert len(s1.trades()) == 1
    assert s1.position("SOL/USDT:USDT") is None
    final = s1.strategy_ledger()["trend"]["cash_usd"]
    pnl = s1.trades()[0]["net_pnl_usd"]
    assert final == pytest.approx(cash0 + plan.margin_usd + plan.entry_fee_usd + pnl)
    # settlements table has exactly one row for this position
    n = s1.conn.execute("SELECT COUNT(*) FROM settlements WHERE position_id=?",
                        (pos["id"],)).fetchone()[0]
    assert n == 1


def test_rollback_leaves_cash_unchanged(tmp_path):
    """A failed settlement transaction must not move cash (all-or-nothing)."""
    path = str(tmp_path / 'lab.sqlite')
    e1, s1, cfg = _engine(path)
    plan = plan_entry("short", 104.6, 1.0, SPEC, cfg, equity=250.0,
                      available_margin=50.0, risk_budget_usd=5.0, with_target=False)
    e1.open_from_plan(INST, plan, "trend", "T", {}, 0, 1000)
    cash_before = s1.strategy_ledger()["trend"]["cash_usd"]
    pos = s1.position("SOL/USDT:USDT")
    # force a failure mid-settlement by making the trades insert blow up
    orig = e1.close_position
    bad_event = ExitEvent("EMERGENCY", float("nan"), float("nan"), 0.06)  # NaN won't raise
    # inject a broken row_factory to cause an error during insert
    try:
        with pytest.raises(Exception):
            # monkeypatch _adjust_strategy_cash to raise after the insert
            def boom(*a, **k):
                raise RuntimeError("simulated crash mid-settlement")
            e1._adjust_strategy_cash = boom
            e1.close_position(dict(pos), ExitEvent("EMERGENCY", 103.5, 1.0, 0.06), 2000)
    finally:
        e1._adjust_strategy_cash = LabEngine._adjust_strategy_cash.__get__(e1)
    # position still open, cash unchanged, no trade, no settlement row
    assert s1.position("SOL/USDT:USDT") is not None
    assert s1.strategy_ledger()["trend"]["cash_usd"] == pytest.approx(cash_before)
    assert s1.trades() == []
    assert s1.conn.execute("SELECT COUNT(*) FROM settlements WHERE position_id=?",
                           (pos["id"],)).fetchone()[0] == 0
