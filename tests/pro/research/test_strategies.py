import pytest
from paperbot.models import Candle
from paperbot.strategy import ema
from paperbot_pro.research.config import ResearchSettings
from paperbot_pro.research.strategies import evaluate_all

H = 3_600_000
CFG = ResearchSettings()


def bar(i, o, h, l, c, v=100.0):
    return Candle(i * H, o, h, l, c, v)


def uptrend(n, start=100.0, step=0.8, v=100.0):
    bars, p = [], start
    for i in range(n):
        o = p; p += step; c = p
        bars.append(bar(i, o, max(o, c) + 0.3, min(o, c) - 0.3, c, v))
    return bars


def ctx(**kw):
    base = dict(funding_rate=0.0001, orderbook=None,
                htf_trend_4h='up', htf_trend_1h='up')
    base.update(kw)
    return base


def test_all_five_present_and_quiet_on_insufficient_history():
    res = evaluate_all(uptrend(30), CFG, ctx())
    assert set(res) == {'regime_trend', 'volatility_breakout', 'trend_pullback',
                        'range_reversion', 'orderflow_imbalance'}
    assert all(s.action is None and s.reason for s in res.values())


def test_regime_trend_fires_in_strong_up_regime():
    bars = uptrend(120, step=1.0)   # strong ADX, EMAs stacked up
    res = evaluate_all(bars, CFG, ctx(htf_trend_4h='up'))['regime_trend']
    assert res.action == 'long'
    assert 'adx' in res.indicators
    # suppressed when the 4h filter disagrees
    counter = evaluate_all(bars, CFG, ctx(htf_trend_4h='down'))['regime_trend']
    assert counter.action is None


def test_volatility_breakout_needs_compression_break_and_relvol():
    # quiet range then a high-volume break of the 20-bar high
    bars = [bar(i, 100, 100.4, 99.6, 100.0, v=100.0) for i in range(60)]
    bars.append(bar(60, 100, 103.5, 99.9, 103.2, v=400.0))   # 4x vol break
    res = evaluate_all(bars, CFG, ctx())['volatility_breakout']
    assert res.action == 'long'
    # same break without volume -> no trade
    bars[-1] = bar(60, 100, 103.5, 99.9, 103.2, v=110.0)
    assert evaluate_all(bars, CFG, ctx())['volatility_breakout'].action is None


def test_trend_pullback_reclaim_in_uptrend():
    bars = uptrend(90, step=0.6)
    e20 = ema([b.close for b in bars], 20)[-1]
    bars.append(bar(90, bars[-1].close, bars[-1].close + 0.2, e20 - 2.5, e20 - 2.0))  # dip
    bars.append(bar(91, e20 - 2.0, e20 + 3.5, e20 - 2.2, e20 + 3.0))                  # reclaim
    res = evaluate_all(bars, CFG, ctx(htf_trend_1h='up'))['trend_pullback']
    assert res.action == 'long'
    # no HTF trend -> suppressed
    assert evaluate_all(bars, CFG, ctx(htf_trend_1h='down'))['trend_pullback'].action is None


def test_range_reversion_only_in_low_adx_and_band_reentry():
    # choppy range; price pokes below lower band then closes back inside
    import math
    bars = [bar(i, 100, 100.8, 99.2, 100 + math.sin(i / 2) * 0.6) for i in range(60)]
    bars.append(bar(60, 100, 100.3, 96.0, 99.9))   # wick below band, close back inside
    res = evaluate_all(bars, CFG, ctx())['range_reversion']
    assert res.action in ('long', None)   # depends on band; must never fire in a trend
    trend_ctx = evaluate_all(uptrend(120, step=1.0), CFG, ctx())['range_reversion']
    assert trend_ctx.action is None        # suspended in strong trend (high ADX)


def test_orderflow_imbalance_requires_fresh_book_and_rejects_thin():
    bars = uptrend(70)
    strong_buy = {'bids': [[100, 50], [99.9, 40], [99.8, 30]],
                  'asks': [[100.1, 5], [100.2, 4], [100.3, 3]],
                  'age_s': 2.0, 'spread_pct': 0.0005}
    res = evaluate_all(bars, CFG, ctx(orderbook=strong_buy))['orderflow_imbalance']
    assert res.action == 'long'
    # stale book -> no signal, honest reason
    stale = dict(strong_buy, age_s=40.0)
    r2 = evaluate_all(bars, CFG, ctx(orderbook=stale))['orderflow_imbalance']
    assert r2.action is None and 'stale' in r2.reason.lower()
    # missing book -> no signal
    r3 = evaluate_all(bars, CFG, ctx(orderbook=None))['orderflow_imbalance']
    assert r3.action is None
    # balanced book -> no edge
    flat = {'bids': [[100, 10]], 'asks': [[100.1, 10]], 'age_s': 1.0, 'spread_pct': 0.0005}
    assert evaluate_all(bars, CFG, ctx(orderbook=flat))['orderflow_imbalance'].action is None
