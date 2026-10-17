"""Additional deterministic indicators for the Research Lab strategies.
Pure functions; None during warmup. No look-ahead (value at i uses bars 0..i)."""
from __future__ import annotations
from datetime import datetime, timezone
from statistics import median
from paperbot.models import Candle


def adx(candles: list[Candle], period: int = 14) -> list[float | None]:
    """Wilder's ADX. None until ~2*period bars of history."""
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < period * 2:
        return out
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        up = candles[i].high - candles[i - 1].high
        dn = candles[i - 1].low - candles[i].low
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    # Wilder smoothing
    atr_s = sum(tr[:period])
    pdm_s = sum(plus_dm[:period])
    mdm_s = sum(minus_dm[:period])
    dx_vals = []
    for i in range(period, len(tr)):
        atr_s = atr_s - atr_s / period + tr[i]
        pdm_s = pdm_s - pdm_s / period + plus_dm[i]
        mdm_s = mdm_s - mdm_s / period + minus_dm[i]
        if atr_s == 0:
            dx_vals.append(0.0)
            continue
        pdi = 100 * pdm_s / atr_s
        mdi = 100 * mdm_s / atr_s
        denom = pdi + mdi
        dx_vals.append(100 * abs(pdi - mdi) / denom if denom else 0.0)
    if len(dx_vals) < period:
        return out
    adx_val = sum(dx_vals[:period]) / period
    # dx_vals[k] corresponds to candle index (period + 1 + k)
    first_adx_candle = period + period  # one TR offset + period DX + period smoothing
    out[first_adx_candle] = adx_val
    for k in range(period, len(dx_vals)):
        adx_val = (adx_val * (period - 1) + dx_vals[k]) / period
        idx = period + 1 + k
        if idx < n:
            out[idx] = adx_val
    return out


def bollinger(values: list[float], period: int = 20, num_std: float = 2.0):
    """Returns (middle, upper, lower, width) lists; width = (upper-lower)/middle."""
    n = len(values)
    mid: list[float | None] = [None] * n
    up: list[float | None] = [None] * n
    lo: list[float | None] = [None] * n
    width: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = values[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        mid[i], up[i], lo[i] = m, m + num_std * sd, m - num_std * sd
        width[i] = (up[i] - lo[i]) / m if m else 0.0
    return mid, up, lo, width


def relative_volume(candles: list[Candle], lookback: int = 20) -> list[float | None]:
    """Each bar's volume divided by the trailing median of the prior `lookback`
    bars' volume. None during warmup."""
    n = len(candles)
    out: list[float | None] = [None] * n
    for i in range(lookback, n):
        window = [candles[j].volume for j in range(i - lookback, i)]
        med = median(window)
        out[i] = (candles[i].volume / med) if med > 0 else None
    return out


def vwap_session(candles: list[Candle]) -> list[float | None]:
    """Session VWAP resetting at each UTC day boundary. Uses typical price."""
    out: list[float | None] = []
    cum_pv = cum_v = 0.0
    day = None
    for c in candles:
        d = datetime.fromtimestamp(c.timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")
        if d != day:
            day, cum_pv, cum_v = d, 0.0, 0.0
        typical = (c.high + c.low + c.close) / 3
        cum_pv += typical * c.volume
        cum_v += c.volume
        out.append(cum_pv / cum_v if cum_v > 0 else None)
    return out
