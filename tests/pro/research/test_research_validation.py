import pytest
from paperbot.models import Candle
from paperbot_pro.perp import ContractSpec
from paperbot_pro.research.config import ResearchSettings
from paperbot_pro.research.validation import validate_strategies

H = 3_600_000
SPEC = ContractSpec('TST/USDT:USDT', 0.0006, 0.005, 0.1, 0.001)


def wavy(n, start_ts=0):
    import math
    bars, p = [], 100.0
    for i in range(n):
        o = p
        p = 100 + 12 * math.sin(i / 29) + 5 * math.sin(i / 8) + 2 * math.sin(i / 3)
        c = p
        bars.append(Candle(start_ts + i * H, o, max(o, c) + 0.6, min(o, c) - 0.6, c,
                           100 + 40 * abs(math.sin(i / 5))))
    return bars


def test_validate_runs_each_strategy_with_costs_and_honest_warnings():
    cfg = ResearchSettings()
    report = validate_strategies({'TST/USDT:USDT': (wavy(1500), SPEC)}, cfg)
    assert set(report['per_strategy']) == {
        'regime_trend', 'volatility_breakout', 'trend_pullback',
        'range_reversion', 'orderflow_imbalance'}
    for key, r in report['per_strategy'].items():
        assert 'net_return_pct' in r and 'trades' in r
        if key == 'orderflow_imbalance':
            assert r['skipped'] is True        # needs order book, not backtestable here
    assert 'not evidence' in ' '.join(report['warnings']).lower()
    assert 'holdout' in ' '.join(report['warnings']).lower()
    assert report['costs_modeled'] is True


def test_validate_is_chronology_safe():
    from dataclasses import replace
    cfg = ResearchSettings()
    bars = wavy(1200)
    base = validate_strategies({'TST/USDT:USDT': (bars, SPEC)}, cfg)
    mutated = bars[:1000] + [replace(b, close=b.close * 1.5, high=b.high * 1.6)
                             for b in bars[1000:]]
    alt = validate_strategies({'TST/USDT:USDT': (mutated, SPEC)}, cfg)
    # trades that closed before the mutation point must be identical
    cut_ts = bars[980].timestamp
    for key in ('regime_trend', 'volatility_breakout', 'trend_pullback', 'range_reversion'):
        eb = [t for t in base['per_strategy'][key]['trade_list'] if t['exit_ms'] < cut_ts]
        ea = [t for t in alt['per_strategy'][key]['trade_list'] if t['exit_ms'] < cut_ts]
        assert [t['entry_ms'] for t in eb] == [t['entry_ms'] for t in ea]


def test_portfolio_walkforward_holdout_untouched():
    cfg = ResearchSettings()
    report = validate_strategies({'TST/USDT:USDT': (wavy(2000), SPEC)}, cfg,
                                 n_windows=3)
    wf = report['walk_forward']
    assert len(wf['windows']) == 3
    assert wf['holdout']['reserved'] is True
    assert wf['holdout']['used_for_tuning'] is False
