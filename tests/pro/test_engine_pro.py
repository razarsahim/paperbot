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
    plan = plan_entry("long", price, 1.0, SPEC, cfg, equity=750.0,
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
    assert cash_after_open == pytest.approx(750.0 - plan.margin_usd - plan.entry_fee_usd)
    event = check_exit(pos, observed_price=pos['stop'] - 1.0, cfg=cfg, taker_fee=SPEC.taker_fee)
    engine.close_position(pos, event, now_ms=13 * H)
    assert store.position(SPEC.symbol) is None
    trades = store.trades()
    assert len(trades) == 1
    # sleeve cash moved by exactly the reported pnl relative to its start
    assert float(store.get('cash_core')) == pytest.approx(750.0 + trades[0]['net_pnl_usd'])
    assert trades[0]['net_pnl_usd'] < 0


def test_liquidation_never_takes_more_than_committed_capital(tmp_path):
    engine, store, cfg = make(tmp_path)
    pos, plan = opened(engine, store, cfg)
    event = check_exit(pos, observed_price=1.0, cfg=cfg, taker_fee=SPEC.taker_fee)
    assert event.reason == "LIQUIDATION"
    engine.close_position(pos, event, now_ms=13 * H)
    cash = float(store.get('cash_core'))
    assert cash == pytest.approx(750.0 - plan.margin_usd - plan.entry_fee_usd)
    assert cash > 0
    assert store.trades()[0]['exit_reason'] == 'LIQUIDATION'


def test_funding_applied_once_per_boundary_even_across_restart(tmp_path):
    engine, store, cfg = make(tmp_path)
    pos, plan = opened(engine, store, cfg)  # opened at 12:00 UTC
    cash_before = float(store.get('cash_core'))
    # 16:00 UTC boundary falls between position open (12h) and now (17h)
    n1 = engine.apply_funding_due(pos, now_ms=17 * H, rate=0.0001, mark=100.0)
    assert n1 == 1
    cash_mid = float(store.get('cash_core'))
    expected = 0.0001 * 100.0 * pos['qty']
    assert cash_mid == pytest.approx(cash_before - expected)

    engine2, store2, cfg2 = make(tmp_path)  # simulated restart, same DB
    pos2 = store2.position(SPEC.symbol)
    n2 = engine2.apply_funding_due(pos2, now_ms=17 * H, rate=0.0001, mark=100.0)
    assert n2 == 0  # idempotent: same boundary never applied twice
    assert float(store2.get('cash_core')) == pytest.approx(cash_mid)
    assert pos2['funding_paid_usd'] == pytest.approx(expected)


def test_outage_spanning_boundaries_charges_all_missed_funding(tmp_path):
    """P1 fix: missed 8h boundaries during an outage are charged on the next
    cycle from the position's OWN anchor, never forfeited by a global clock."""
    engine, store, cfg = make(tmp_path)
    pos, plan = opened(engine, store, cfg)          # opened 12:00 UTC
    n1 = engine.apply_funding_due(pos, now_ms=17 * H, rate=0.0001, mark=100.0)
    assert n1 == 1                                   # 16:00 applied
    # simulate a 20h outage: next cycle only at 37h -> boundaries 24h and 32h missed
    engine2, store2, cfg2 = make(tmp_path)
    pos2 = store2.position(SPEC.symbol)
    n2 = engine2.apply_funding_due(pos2, now_ms=37 * H, rate=0.0001, mark=100.0)
    assert n2 == 2                                   # both retro-charged exactly once
    assert store2.position(SPEC.symbol)['funding_paid_usd'] == pytest.approx(
        3 * 0.0001 * 100.0 * plan.qty)
    rows = list(store2.conn.execute(
        'SELECT funding_ts_ms FROM funding_events ORDER BY funding_ts_ms'))
    assert [r[0] for r in rows] == [16 * H, 24 * H, 32 * H]


def test_auto_entry_gate_blocks_without_validation_artifact(tmp_path):
    engine, store, cfg = make(tmp_path, auto_entry=True)
    allowed, reason = engine.auto_entry_allowed()
    assert allowed is False and 'validation' in reason
    from tests.pro.conftest import write_valid_artifact
    write_valid_artifact(cfg)
    allowed, reason = engine.auto_entry_allowed()
    assert allowed is True

    engine2, store2, cfg2 = make(tmp_path / 'off', auto_entry=False)
    allowed, reason = engine2.auto_entry_allowed()
    assert allowed is False and 'disabled' in reason
