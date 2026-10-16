from __future__ import annotations
from dataclasses import dataclass
from .models import Candle


@dataclass(frozen=True)
class Signal:
    buy: bool
    atr: float
    reason: str


def ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    result: list[float | None] = [None] * (period - 1)
    prev = sum(values[:period]) / period
    result.append(prev)
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        prev = multiplier * value + (1 - multiplier) * prev
        result.append(prev)
    return result


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return result
    tr = []
    for i in range(1, len(candles)):
        bar, prev = candles[i], candles[i - 1]
        tr.append(max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close)))
    av = sum(tr[:period]) / period
    result[period] = av
    for i in range(period + 1, len(candles)):
        av = (av * (period - 1) + tr[i - 1]) / period
        result[i] = av
    return result


def evaluate(candles: list[Candle]) -> Signal:
    """Bar-close strategy: EMA20>EMA50 and price reclaims EMA20 from below.

    The signal at candles[-1] NEVER reads any future bar.
    It is a deliberately simple, UNVALIDATED hypothesis, not investment advice.
    """
    if len(candles) < 60:
        return Signal(False, 0.0, "Insufficient history")
    close = [c.close for c in candles]
    fast, slow = ema(close, 20), ema(close, 50)
    volatility = atr(candles, 14)[-1]
    f0, f1, s0 = fast[-1], fast[-2], slow[-1]
    if any(x is None for x in (f0, f1, s0, volatility)):
        return Signal(False, 0.0, "Indicators still warming up")
    assert f0 is not None and f1 is not None and s0 is not None and volatility is not None
    buy = f0 > s0 and close[-2] <= f1 and close[-1] > f0 and volatility > 0
    return Signal(buy, volatility, "EMA20>EMA50, close reclaims EMA20" if buy else "No qualifying EMA reclaim")
