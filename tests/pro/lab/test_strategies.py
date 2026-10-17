from paperbot.models import Candle
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.strategies import evaluate_all

H = 3_600_000
CFG = LabSettings()


def bar(i, o, h, l, c, v=100.0):
    return Candle(i * H, o, h, l, c, v)


def flat(n, price=100.0, v=100.0):
    return [bar(i, price, price + 0.5, price - 0.5, price, v) for i in range(n)]


def ctx(**kw):
    base = dict(funding_rate=0.0001, listing_age_days=400, change_24h_pct=0.0)
    base.update(kw)
    return base


def test_all_strategies_quiet_on_flat_market():
    results = evaluate_all(flat(100), CFG, ctx())
    assert set(results) == {'breakout', 'launch_sniper', 'squeeze', 'trend', 'crash_reversal'}
    assert all(sig.action is None for sig in results.values())
    assert all(sig.reason for sig in results.values())  # every pass explains itself


def test_breakout_fires_on_range_break_with_volume():
    bars = flat(99)
    bars.append(bar(99, 100.0, 103.5, 99.8, 103.2, v=350.0))  # breaks 100.5 high, 3.5x vol
    result = evaluate_all(bars, CFG, ctx())['breakout']
    assert result.action == 'long'
    assert 'broke' in result.reason.lower()
    quiet = evaluate_all(flat(99) + [bar(99, 100.0, 103.5, 99.8, 103.2, v=110.0)],
                         CFG, ctx())['breakout']
    assert quiet.action is None  # no volume confirmation -> no trade


def test_launch_sniper_requires_verified_young_market():
    bars = flat(70)
    bars.append(bar(70, 100.0, 104.0, 99.9, 103.8, v=400.0))
    old = evaluate_all(bars, CFG, ctx(listing_age_days=400))['launch_sniper']
    assert old.action is None and 'young' in old.reason.lower()
    young = evaluate_all(bars, CFG, ctx(listing_age_days=10))['launch_sniper']
    assert young.action == 'long'


def test_squeeze_fades_wick_with_funding_extreme():
    bars = flat(99)
    # deep lower wick: open 100, low 93, close back to 99.5 (wick >> ATR~1)
    bars.append(bar(99, 100.0, 100.4, 93.0, 99.5))
    squeezed = evaluate_all(bars, CFG, ctx(funding_rate=-0.0005))['squeeze']
    assert squeezed.action == 'long'
    mild_funding = evaluate_all(bars, CFG, ctx(funding_rate=0.0001))['squeeze']
    assert mild_funding.action is None  # wick alone is not a squeeze


def test_crash_reversal_needs_drop_and_reversal_candle():
    bars = flat(80, price=100.0)
    price = 100.0
    for i in range(80, 103):  # grind down ~9% over 23h
        nxt = price * 0.996
        bars.append(bar(i, price, price + 0.1, nxt - 0.2, nxt))
        price = nxt
    bars.append(bar(103, price, price + 0.8, price * 0.97, price + 0.6))  # hammer
    result = evaluate_all(bars, CFG, ctx())['crash_reversal']
    assert result.action == 'long'
    no_reversal = evaluate_all(bars[:-1], CFG, ctx())['crash_reversal']
    assert no_reversal.action is None


def test_trend_rider_reuses_reclaim_logic():
    from paperbot.strategy import ema
    bars, price = [], 100.0
    for i in range(90):
        o = price
        price += 0.6
        bars.append(bar(i, o, max(o, price) + 0.2, min(o, price) - 0.2, price))
    e20 = ema([b.close for b in bars], 20)[-1]
    bars.append(bar(90, bars[-1].close, bars[-1].close + 0.2, e20 - 2.5, e20 - 2.0))
    bars.append(bar(91, e20 - 2.0, e20 + 3.5, e20 - 2.2, e20 + 3.0))
    result = evaluate_all(bars, CFG, ctx())['trend']
    assert result.action == 'long'
