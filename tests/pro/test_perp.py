import pytest
from dataclasses import replace
from paperbot_pro.config import ProSettings
from paperbot_pro.perp import (ContractSpec, check_exit, funding_cost,
                               liquidation_price, plan_entry, realized_pnl,
                               unrealized_pnl)

SPEC = ContractSpec(symbol="BTC/USDT:USDT", taker_fee=0.0006,
                    maint_margin_rate=0.005, tick_size=0.1, lot_size=0.001)
CFG = ProSettings()


def test_liquidation_price_estimates_bracket_entry():
    long_liq = liquidation_price("long", 100.0, 10.0, 0.005)
    short_liq = liquidation_price("short", 100.0, 10.0, 0.005)
    assert long_liq == pytest.approx(100.0 * (1 - 0.1 + 0.005))   # 90.5
    assert short_liq == pytest.approx(100.0 * (1 + 0.1 - 0.005))  # 109.5


def test_plan_entry_long_sizes_to_risk_budget_with_costs():
    plan = plan_entry("long", price=100.0, atr_value=1.0, spec=SPEC, cfg=CFG,
                      equity=1000.0, available_margin=900.0,
                      risk_rate=CFG.risk_per_trade)
    assert plan.ok, plan.reason
    assert plan.side == "long" and plan.leverage == 10.0
    assert plan.stop < plan.entry_price < plan.target
    assert plan.liq_price_est < plan.stop  # stop must trigger before liquidation
    # planned worst-case loss (stop + slippage + both fees) within 0.5% of equity
    assert plan.planned_risk_usd <= 1000.0 * CFG.risk_per_trade + 1e-9
    assert plan.qty == pytest.approx(round(plan.qty / SPEC.lot_size) * SPEC.lot_size)
    assert plan.margin_usd == pytest.approx(plan.notional_usd / 10.0)


def test_plan_entry_rejects_stop_beyond_liquidation():
    plan = plan_entry("long", price=100.0, atr_value=6.0, spec=SPEC, cfg=CFG,
                      equity=1000.0, available_margin=900.0,
                      risk_rate=CFG.risk_per_trade)
    assert not plan.ok
    assert "liquidation" in plan.reason


def test_plan_entry_caps_margin_to_available_sleeve():
    tight = plan_entry("long", price=100.0, atr_value=0.02, spec=SPEC, cfg=CFG,
                       equity=1000.0, available_margin=5.0,
                       risk_rate=CFG.risk_per_trade)
    if tight.ok:
        assert tight.margin_usd <= 5.0 + 1e-9
    else:
        assert "margin" in tight.reason or "too small" in tight.reason


def test_check_exit_liquidation_beats_stop_when_both_gapped():
    pos = dict(side="long", entry_price=100.0, qty=1.0, stop=95.0, target=104.0,
               liq_price_est=90.5, margin_usd=10.0, entry_fee_usd=0.06,
               funding_paid_usd=0.0)
    event = check_exit(pos, observed_price=88.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert event.reason == "LIQUIDATION"
    # loss capped at margin + fees + funding: never more than committed capital
    assert event.pnl_usd == pytest.approx(-(10.0 + 0.06))
    event2 = check_exit(pos, observed_price=93.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert event2.reason == "STOP (gap)"
    exit_fill = 93.0 * (1 - CFG.slippage_rate)
    expected = (exit_fill - 100.0) * 1.0 - 0.06 - exit_fill * 1.0 * SPEC.taker_fee
    assert event2.pnl_usd == pytest.approx(expected)
    assert abs(event2.pnl_usd) > 100.0 * 0.05  # honestly worse than planned


def test_check_exit_target_fill_never_better_than_target():
    pos = dict(side="long", entry_price=100.0, qty=1.0, stop=95.0, target=104.0,
               liq_price_est=90.5, margin_usd=10.0, entry_fee_usd=0.06,
               funding_paid_usd=0.0)
    event = check_exit(pos, observed_price=110.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert event.reason == "TARGET"
    assert event.exit_price == pytest.approx(104.0 * (1 - CFG.slippage_rate))


def test_check_exit_short_mirrors():
    pos = dict(side="short", entry_price=100.0, qty=1.0, stop=105.0, target=96.0,
               liq_price_est=109.5, margin_usd=10.0, entry_fee_usd=0.06,
               funding_paid_usd=0.0)
    assert check_exit(pos, observed_price=111.0, cfg=CFG, taker_fee=SPEC.taker_fee).reason == "LIQUIDATION"
    stop_event = check_exit(pos, observed_price=106.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert stop_event.reason == "STOP (gap)"
    assert stop_event.pnl_usd < 0
    target_event = check_exit(pos, observed_price=95.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert target_event.reason == "TARGET"
    assert target_event.pnl_usd > 0
    assert check_exit(pos, observed_price=100.0, cfg=CFG, taker_fee=SPEC.taker_fee) is None


def test_funding_cost_signs():
    # positive rate: longs pay, shorts receive
    assert funding_cost("long", rate=0.0001, mark=100.0, qty=2.0) == pytest.approx(0.02)
    assert funding_cost("short", rate=0.0001, mark=100.0, qty=2.0) == pytest.approx(-0.02)
    assert funding_cost("long", rate=-0.0001, mark=100.0, qty=2.0) == pytest.approx(-0.02)


def test_unrealized_and_realized_pnl_signs():
    assert unrealized_pnl("long", 100.0, 101.0, 2.0) == pytest.approx(2.0)
    assert unrealized_pnl("short", 100.0, 101.0, 2.0) == pytest.approx(-2.0)
    pnl = realized_pnl("short", entry=100.0, exit_fill=96.0, qty=1.0,
                       entry_fee=0.06, exit_fee=0.058, funding=0.01)
    assert pnl == pytest.approx(4.0 - 0.06 - 0.058 - 0.01)
