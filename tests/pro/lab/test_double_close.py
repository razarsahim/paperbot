"""Regression: close_position must be idempotent. During an emergency exit,
two paths (live tick + cycle) could grab the same position dict before either
deletes it and both book a trade + credit cash — the 2026-10-17 SOL
double-close that inflated the trend sleeve by ~one margin ($19.87)."""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.store import LabStore
from paperbot_pro.perp import ContractSpec, check_exit, plan_entry

SPEC = ContractSpec("SOL/USDT:USDT", 0.0006, 0.005, 0.1, 0.001)


def test_closing_same_position_twice_credits_once(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'))
    store = LabStore(cfg.db_path, cfg)
    engine = LabEngine(store, cfg, market=None, instruments_provider=lambda: [])
    plan = plan_entry("short", 104.6, 1.0, SPEC, cfg, equity=250.0,
                      available_margin=50.0, risk_budget_usd=5.0, with_target=False)
    inst = {"symbol": "SOL/USDT:USDT", "exchange": "bybit", "taker_fee": 0.0006,
            "maint_margin_rate": 0.005, "tick_size": 0.1, "lot_size": 0.001}
    engine.open_from_plan(inst, plan, "trend", "T", {}, 0, 1000)
    cash_after_open = store.strategy_ledger()["trend"]["cash_usd"]
    pos = store.position("SOL/USDT:USDT")

    # two code paths grabbed the SAME position dict, then both call close
    event = check_exit(pos, 103.5, cfg, SPEC.taker_fee) or type(
        "E", (), {"reason": "EMERGENCY", "exit_price": 103.5, "pnl_usd": 1.0,
                  "exit_fee_usd": 0.06})()
    engine.close_position(dict(pos), event, 2000)
    engine.close_position(dict(pos), event, 3000)   # duplicate must be a no-op

    assert len(store.trades()) == 1                 # only ONE trade recorded
    assert store.position("SOL/USDT:USDT") is None
    final = store.strategy_ledger()["trend"]["cash_usd"]
    trade_pnl = store.trades()[0]["net_pnl_usd"]
    # cash moved by exactly the margin+fee returned + pnl, counted once
    assert final == pytest.approx(cash_after_open + plan.margin_usd
                                  + plan.entry_fee_usd + trade_pnl)
