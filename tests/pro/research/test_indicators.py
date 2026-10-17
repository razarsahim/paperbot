import pytest
from paperbot.models import Candle
from paperbot_pro.research.indicators import (adx, bollinger, relative_volume,
                                              vwap_session)

H = 3_600_000


def bar(i, o, h, l, c, v=100.0):
    return Candle(i * H, o, h, l, c, v)


def test_adx_high_in_strong_trend_low_in_chop():
    trend = [bar(i, 100 + i, 100 + i + 0.5, 100 + i - 0.1, 100 + i + 0.4) for i in range(60)]
    chop = [bar(i, 100, 100.6, 99.4, 100 + (0.4 if i % 2 else -0.4)) for i in range(60)]
    a_trend = adx(trend, 14)[-1]
    a_chop = adx(chop, 14)[-1]
    assert a_trend is not None and a_chop is not None
    assert a_trend > 25
    assert a_chop < 20
    assert adx(trend[:10], 14)[-1] is None  # warmup


def test_bollinger_bands_and_compression():
    flat = [bar(i, 100, 100.2, 99.8, 100.0) for i in range(40)]
    mid, upper, lower, width = bollinger([c.close for c in flat], 20, 2.0)
    assert mid[-1] == pytest.approx(100.0)
    assert upper[-1] == pytest.approx(lower[-1])  # zero variance band collapses
    # expanding volatility widens the band
    volatile = [bar(i, 100, 110, 90, 100 + (8 if i % 2 else -8)) for i in range(40)]
    _, u2, l2, w2 = bollinger([c.close for c in volatile], 20, 2.0)
    assert (u2[-1] - l2[-1]) > (upper[-1] - lower[-1])
    assert w2[-1] > width[-1]


def test_relative_volume_vs_trailing_median():
    bars = [bar(i, 100, 101, 99, 100, v=100.0) for i in range(25)]
    bars.append(bar(25, 100, 101, 99, 100, v=250.0))   # 2.5x the median
    rv = relative_volume(bars, lookback=20)
    assert rv[-1] == pytest.approx(2.5)
    assert rv[5] is None  # warmup


def test_vwap_session_resets_daily():
    # two UTC days; VWAP must reset at the day boundary
    day0 = [Candle(i * H, 100, 100, 100, 100, 10.0) for i in range(24)]
    day1 = [Candle((24 + i) * H, 200, 200, 200, 200, 10.0) for i in range(3)]
    vw = vwap_session(day0 + day1)
    assert vw[23] == pytest.approx(100.0)
    assert vw[24] == pytest.approx(200.0)   # reset, not blended toward 100
