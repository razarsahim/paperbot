"""Signal generation, strictly separated from approval and simulated execution.

generate_signal() is a pure function of COMPLETED candles and frozen,
reproducible parameters. It never sees portfolio state; the RiskGovernor
approves or rejects, and the engine logs every decision either way. An
indicator pattern is a hypothesis, not a prediction.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from paperbot.models import Candle
from paperbot.strategy import atr, ema
from .indicators import rsi


@dataclass(frozen=True)
class StrategyParams:
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    rsi_period: int = 14
    allow_short: bool = True
    min_bars: int = 60

    def describe(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProSignal:
    action: str | None          # 'long' | 'short' | None
    atr: float
    reason: str
    indicators: dict


def signal_series(bars: list[Candle], params: StrategyParams) -> list[ProSignal]:
    """Signal at every index i, computed from bars[0..i] only — identical to
    generate_signal(bars[:i+1]) for every i (EMA/ATR/RSI are cumulative, so
    full-series indicator values at index i equal the prefix values). One
    O(n) pass instead of O(n^2), which multi-year backtests require."""
    closes = [c.close for c in bars]
    fast = ema(closes, params.ema_fast)
    slow = ema(closes, params.ema_slow)
    volatility_arr = atr(bars, params.atr_period)
    strength_arr = rsi(closes, params.rsi_period)
    out: list[ProSignal] = []
    for i in range(len(bars)):
        if i + 1 < params.min_bars:
            out.append(ProSignal(None, 0.0, "Insufficient history", {}))
            continue
        f0, f1, s0, vol = fast[i], fast[i - 1], slow[i], volatility_arr[i]
        if any(v is None for v in (f0, f1, s0, vol)) or vol <= 0:
            out.append(ProSignal(None, 0.0, "Indicators warming up", {}))
            continue
        strength = strength_arr[i]
        snapshot = {"close": closes[i], "ema20": round(f0, 6), "ema50": round(s0, 6),
                    "atr": round(vol, 6),
                    "rsi": round(strength, 2) if strength is not None else None}
        long_setup = f0 > s0 and closes[i - 1] <= f1 and closes[i] > f0
        short_setup = f0 < s0 and closes[i - 1] >= f1 and closes[i] < f0
        if long_setup:
            out.append(ProSignal("long", vol, "EMA20>EMA50, close reclaims EMA20 from below", snapshot))
        elif short_setup and params.allow_short:
            out.append(ProSignal("short", vol, "EMA20<EMA50, close rejects EMA20 from above", snapshot))
        elif short_setup:
            out.append(ProSignal(None, vol, "Short setup present but shorts disabled", snapshot))
        else:
            out.append(ProSignal(None, vol, "No qualifying setup", snapshot))
    return out


def generate_signal(closed_bars: list[Candle], params: StrategyParams) -> ProSignal:
    if len(closed_bars) < params.min_bars:
        return ProSignal(None, 0.0, "Insufficient history", {})
    return signal_series(closed_bars, params)[-1]
