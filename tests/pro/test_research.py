"""Multi-year research upgrades: fast equivalent signal series, paginated
history, regime-split validation."""
import pytest
from paperbot.models import Candle
from paperbot_pro.config import ProSettings
from paperbot_pro.perp import ContractSpec
from paperbot_pro.scanner import StrategyParams, generate_signal, signal_series

H = 3_600_000
SPEC = ContractSpec('TST/USDT:USDT', 0.0006, 0.005, 0.1, 0.001)


def wavy(n, start_ts=0):
    import math
    bars, price = [], 100.0
    for i in range(n):
        o = price
        price = 100.0 + 10 * math.sin(i / 23) + 4 * math.sin(i / 7) + 2 * math.sin(i / 3)
        c = price
        hi, lo = max(o, c) + 0.5, min(o, c) - 0.5
        bars.append(Candle(start_ts + i * H, o, hi, lo, c, 10.0))
    return bars


def test_signal_series_matches_per_prefix_generate_signal():
    bars = wavy(400)
    params = StrategyParams()
    series = signal_series(bars, params)
    assert len(series) == len(bars)
    for i in (59, 100, 177, 253, 399):
        expected = generate_signal(bars[:i + 1], params)
        assert series[i].action == expected.action, f'mismatch at {i}'
        assert series[i].atr == pytest.approx(expected.atr)


def test_fast_perp_backtest_identical_to_before_and_quick():
    import time
    from paperbot_pro.validation import perp_backtest
    bars = wavy(6000)
    t0 = time.monotonic()
    result = perp_backtest(bars, ProSettings(), SPEC)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f'perp_backtest too slow for multi-year data: {elapsed:.1f}s'
    assert result['bars'] == 6000


def test_validate_markets_regime_split_by_year():
    from paperbot_pro.validation import validate_markets
    year_h = 365 * 24
    bars = wavy(2 * year_h)  # two calendar years from epoch (1970/1971)
    report = validate_markets({'TST/USDT:USDT': (bars, SPEC)}, ProSettings())
    market = report['markets'][0]
    assert 'regimes' in market and len(market['regimes']) == 2
    years = [r['period'] for r in market['regimes']]
    assert years == ['1970', '1971']
    for regime in market['regimes']:
        assert 'net_return_pct' in regime and 'buy_hold_return_pct' in regime
        assert regime['trades'] >= 0
    assert report['benchmarks']['cash_return_pct'] == 0.0
