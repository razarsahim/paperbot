import pytest
from dataclasses import replace
from paperbot.models import Candle
from paperbot_pro.config import ProSettings
from paperbot_pro.perp import ContractSpec
from paperbot_pro.validation import perp_backtest, validate_markets

H = 3_600_000
SPEC = ContractSpec('TST/USDT:USDT', 0.0006, 0.005, 0.1, 0.001)


def bar(i, o, h, l, c):
    return Candle(i * H, o, h, l, c, 10.0)


def flat_then_trend(n=300):
    bars, price = [], 100.0
    for i in range(n):
        step = 0.4 if i > 100 else 0.0
        o = price
        price += step
        bars.append(bar(i, o, max(o, price) + 0.3, min(o, price) - 0.3, price))
    return bars


def test_perp_backtest_runs_and_charges_costs():
    cfg = ProSettings()
    result = perp_backtest(flat_then_trend(), cfg, SPEC)
    assert result['bars'] == 300
    assert result['final_equity'] > 0
    for t in result['trades']:
        assert t['funding_usd'] >= 0 or t['side'] == 'short'
        assert t['entry_fee_usd'] > 0 and t['exit_fee_usd'] >= 0
        assert t['exit_ms'] >= t['entry_ms']


def test_perp_backtest_is_chronology_safe():
    cfg = ProSettings()
    bars = flat_then_trend()
    base = perp_backtest(bars, cfg, SPEC)
    mutated = bars[:250] + [replace(b, close=b.close * 1.5, high=b.high * 1.6)
                            for b in bars[250:]]
    altered = perp_backtest(mutated, cfg, SPEC)
    early_base = [t for t in base['trades'] if t['exit_ms'] < bars[240].timestamp]
    early_alt = [t for t in altered['trades'] if t['exit_ms'] < bars[240].timestamp]
    assert [t['entry_ms'] for t in early_base] == [t['entry_ms'] for t in early_alt]


def test_perp_backtest_liquidation_first_on_entry_bar_gap():
    cfg = ProSettings()
    bars = flat_then_trend(200)
    # force a catastrophic bar right after a likely-signal region: liq-first
    crash_i = 150
    prev_close = bars[crash_i - 1].close
    bars[crash_i] = bar(crash_i, prev_close, prev_close + 0.1, prev_close * 0.5, prev_close * 0.55)
    result = perp_backtest(bars, cfg, SPEC)
    liqs = [t for t in result['trades'] if t['exit_reason'] == 'LIQUIDATION']
    stops = [t for t in result['trades'] if 'STOP' in t['exit_reason']]
    # whatever was open through the crash must have liquidated, not cleanly stopped
    if any(t['exit_ms'] == bars[crash_i].timestamp for t in result['trades']):
        crash_exits = [t for t in result['trades'] if t['exit_ms'] == bars[crash_i].timestamp]
        assert all(t['exit_reason'] == 'LIQUIDATION' for t in crash_exits)
        for t in crash_exits:
            assert t['net_pnl_usd'] >= -(t['margin_usd'] + t['entry_fee_usd'] + t['funding_usd']) - 1e-9


def test_validate_markets_writes_honest_summary():
    cfg = ProSettings()
    report = validate_markets({'TST/USDT:USDT': (flat_then_trend(), SPEC)}, cfg)
    assert report['markets'][0]['symbol'] == 'TST/USDT:USDT'
    assert 'not evidence' in ' '.join(report['warnings']).lower()
    assert report['combined']['total_trades'] == sum(
        m['trades'] for m in report['markets'])
    assert 'concurrency' in ' '.join(report['warnings']).lower()
