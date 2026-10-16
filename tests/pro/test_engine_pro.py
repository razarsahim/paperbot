import json
import pytest
from dataclasses import replace
from paperbot_pro.config import ProSettings
from paperbot_pro.engine import ProEngine
from paperbot_pro.perp import ContractSpec, check_exit, plan_entry
from paperbot_pro.store import ProStore

H = 3_600_000
SPEC = ContractSpec("BTC/USDT:USDT", 0.0006, 0.005, 0.1, 0.001)


def make(tmp_path, **kw):
    cfg = replace(ProSettings(),
                  db_path=str(tmp_path / 'pro.sqlite'),
                  validation_report_path=str(tmp_path / 'validation_report.json'), **kw)
    store = ProStore(cfg.db_path, cfg)
    return ProEngine(store, cfg), store, cfg


def opened(engine, store, cfg, price=100.0):
    plan = plan_entry("long", price, 1.0, SPEC, cfg, equity=1000.0,
                      available_margin=float(store.get('cash_core')),
                      risk_rate=cfg.risk_per_trade)
    assert plan.ok
    engine.open_from_plan(SPEC, plan, rationale="TEST", indicator_snapshot={"x": 1},
                          bar_ts=0, now_ms=12 * H, sleeve="core")
    return store.position(SPEC.symbol), plan


def test_open_close_accounting_conserves_equity(tmp_path):
    engine, store, cfg = make(tmp_path)
    pos, plan = opened(engine, store, cfg)
    assert pos is not None
    cash_after_open = float(store.get('cash_core'))
    assert cash_after_open == pytest.approx(900.0 - plan.margin_usd - plan.entry_fee_usd)
    event = check_exit(pos, observed_price=pos['stop'] - 1.0, cfg=cfg, taker_fee=SPEC.taker_fee)
    engine.close_position(pos, event, now_ms=13 * H)
    assert store.position(SPEC.symbol) is None
    trades = store.trades()
    assert len(trades) == 1
    # sleeve cash moved by exactly the reported pnl relative to its start
    assert float(store.get('cash_core')) == pytest.approx(900.0 + trades[0]['net_pnl_usd'])
    assert trades[0]['net_pnl_usd'] < 0


def test_liquidation_never_takes_more_than_committed_capital(tmp_path):
    engine, store, cfg = make(tmp_path)
    pos, plan = opened(engine, store, cfg)
    event = check_exit(pos, observed_price=1.0, cfg=cfg, taker_fee=SPEC.taker_fee)
    assert event.reason == "LIQUIDATION"
    engine.close_position(pos, event, now_ms=13 * H)
    cash = float(store.get('cash_core'))
    assert cash == pytest.approx(900.0 - plan.margin_usd - plan.entry_fee_usd)
    assert cash > 0
    assert store.trades()[0]['exit_reason'] == 'LIQUIDATION'


def test_funding_applied_once_per_boundary_even_across_restart(tmp_path):
    engine, store, cfg = make(tmp_path)
    pos, plan = opened(engine, store, cfg)
    cash_before = float(store.get('cash_core'))
    # 16:00 UTC boundary falls between last check (12h) and now (17h)
    n1 = engine.apply_funding_due(pos, now_ms=17 * H, rate=0.0001, mark=100.0,
                                  last_check_ms=12 * H)
    assert n1 == 1
    cash_mid = float(store.get('cash_core'))
    expected = 0.0001 * 100.0 * pos['qty']
    assert cash_mid == pytest.approx(cash_before - expected)

    engine2, store2, cfg2 = make(tmp_path)  # simulated restart, same DB
    pos2 = store2.position(SPEC.symbol)
    n2 = engine2.apply_funding_due(pos2, now_ms=17 * H, rate=0.0001, mark=100.0,
                                   last_check_ms=12 * H)
    assert n2 == 0  # idempotent: same boundary never applied twice
    assert float(store2.get('cash_core')) == pytest.approx(cash_mid)
    assert pos2['funding_paid_usd'] == pytest.approx(expected)


def test_auto_entry_gate_blocks_without_validation_artifact(tmp_path):
    engine, store, cfg = make(tmp_path, auto_entry=True)
    allowed, reason = engine.auto_entry_allowed()
    assert allowed is False and 'validation' in reason
    with open(cfg.validation_report_path, 'w') as f:
        json.dump({'summary': 'test'}, f)
    allowed, reason = engine.auto_entry_allowed()
    assert allowed is True

    engine2, store2, cfg2 = make(tmp_path / 'off', auto_entry=False)
    allowed, reason = engine2.auto_entry_allowed()
    assert allowed is False and 'disabled' in reason
