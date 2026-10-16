from paperbot.models import Candle
from paperbot_pro.indicators import rsi
from paperbot_pro.scanner import StrategyParams, generate_signal


def trend_series(n, start=100.0, step=0.5):
    bars, price = [], start
    for i in range(n):
        o = price
        price = price + step
        c = price
        hi, lo = max(o, c) + 0.2, min(o, c) - 0.2
        bars.append(Candle(i * 3_600_000, o, hi, lo, c, 10.0))
    return bars


def test_long_signal_on_pullback_reclaim_in_uptrend():
    bars = trend_series(80, step=0.6)
    last_ts = bars[-1].timestamp
    # pullback bar closing below EMA20, then a reclaim bar closing above it
    from paperbot.strategy import ema
    closes = [b.close for b in bars]
    e20 = ema(closes, 20)[-1]
    dip_close = e20 - 2.0
    dip = Candle(last_ts + 3_600_000, bars[-1].close, bars[-1].close + 0.2,
                 dip_close - 0.5, dip_close, 10.0)
    reclaim_close = e20 + 3.0
    reclaim = Candle(last_ts + 7_200_000, dip_close, reclaim_close + 0.5,
                     dip_close - 0.2, reclaim_close, 10.0)
    signal = generate_signal(bars + [dip, reclaim], StrategyParams())
    assert signal.action == 'long'
    assert signal.atr > 0
    assert 'ema20' in signal.indicators and 'rsi' in signal.indicators


def test_short_signal_mirrors_in_downtrend():
    bars = trend_series(80, start=200.0, step=-0.6)
    from paperbot.strategy import ema
    e20 = ema([b.close for b in bars], 20)[-1]
    last_ts = bars[-1].timestamp
    bounce_close = e20 + 2.0
    bounce = Candle(last_ts + 3_600_000, bars[-1].close, bounce_close + 0.5,
                    bars[-1].close - 0.2, bounce_close, 10.0)
    reject_close = e20 - 3.0
    reject = Candle(last_ts + 7_200_000, bounce_close, bounce_close + 0.2,
                    reject_close - 0.5, reject_close, 10.0)
    signal = generate_signal(bars + [bounce, reject], StrategyParams())
    assert signal.action == 'short'


def test_short_disabled_by_params():
    bars = trend_series(80, start=200.0, step=-0.6)
    from paperbot.strategy import ema
    e20 = ema([b.close for b in bars], 20)[-1]
    last_ts = bars[-1].timestamp
    bounce = Candle(last_ts + 3_600_000, bars[-1].close, e20 + 2.5,
                    bars[-1].close - 0.2, e20 + 2.0, 10.0)
    reject = Candle(last_ts + 7_200_000, e20 + 2.0, e20 + 2.2, e20 - 3.5, e20 - 3.0, 10.0)
    signal = generate_signal(bars + [bounce, reject], StrategyParams(allow_short=False))
    assert signal.action is None


def test_insufficient_history_yields_no_action():
    signal = generate_signal(trend_series(30), StrategyParams())
    assert signal.action is None
    assert 'Insufficient' in signal.reason


def test_rsi_direction_sanity():
    up = [100 + i for i in range(30)]
    down = [100 - i for i in range(30)]
    assert rsi(up, 14)[-1] > 70
    assert rsi(down, 14)[-1] < 30
    assert rsi([100.0] * 10, 14)[-1] is None  # not enough data
