import pytest
from paperbot_pro.config import ProSettings
from paperbot_pro.perp import ContractSpec, check_exit, plan_entry, trail_stop

SPEC = ContractSpec("TST/USDT:USDT", 0.0006, 0.005, 0.1, 0.001)
CFG = ProSettings()


def test_plan_entry_accepts_absolute_dollar_risk_budget():
    plan = plan_entry("long", price=100.0, atr_value=1.0, spec=SPEC, cfg=CFG,
                      equity=250.0, available_margin=50.0,
                      risk_budget_usd=5.0)
    assert plan.ok, plan.reason
    assert plan.planned_risk_usd <= 5.0 + 1e-9
    assert plan.margin_usd <= 50.0 + 1e-9


def test_plan_entry_supports_no_target():
    plan = plan_entry("long", price=100.0, atr_value=1.0, spec=SPEC, cfg=CFG,
                      equity=250.0, available_margin=50.0,
                      risk_budget_usd=5.0, with_target=False)
    assert plan.ok
    assert plan.target is None


def test_check_exit_without_target_never_takes_profit_cap():
    pos = dict(side="long", entry_price=100.0, qty=0.5, stop=98.0, target=None,
               liq_price_est=90.5, margin_usd=5.0, entry_fee_usd=0.03,
               funding_paid_usd=0.0)
    assert check_exit(pos, observed_price=150.0, cfg=CFG, taker_fee=SPEC.taker_fee) is None
    stop_event = check_exit(pos, observed_price=97.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert stop_event is not None and 'STOP' in stop_event.reason
    liq_event = check_exit(pos, observed_price=80.0, cfg=CFG, taker_fee=SPEC.taker_fee)
    assert liq_event.reason == 'LIQUIDATION'


def test_trail_stop_monotonic_never_widens():
    # long: stop ratchets up with price, never down
    s1 = trail_stop("long", current_stop=98.0, observed=105.0, atr_value=1.0, multiplier=2.5)
    assert s1 == pytest.approx(102.5)
    s2 = trail_stop("long", current_stop=s1, observed=101.0, atr_value=1.0, multiplier=2.5)
    assert s2 == s1  # price fell back: stop must NOT widen
    # short mirror: stop ratchets down
    s3 = trail_stop("short", current_stop=102.0, observed=95.0, atr_value=1.0, multiplier=2.5)
    assert s3 == pytest.approx(97.5)
    s4 = trail_stop("short", current_stop=s3, observed=99.0, atr_value=1.0, multiplier=2.5)
    assert s4 == s3
