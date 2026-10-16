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


def generate_signal(closed_bars: list[Candle], params: StrategyParams) -> ProSignal:
    if len(closed_bars) < params.min_bars:
        return ProSignal(None, 0.0, "Insufficient history", {})
    closes = [c.close for c in closed_bars]
    fast = ema(closes, params.ema_fast)
    slow = ema(closes, params.ema_slow)
    volatility = atr(closed_bars, params.atr_period)[-1]
    strength = rsi(closes, params.rsi_period)[-1]
    f0, f1, s0 = fast[-1], fast[-2], slow[-1]
    if any(v is None for v in (f0, f1, s0, volatility)) or volatility <= 0:
        return ProSignal(None, 0.0, "Indicators warming up", {})
    snapshot = {"close": closes[-1], "ema20": round(f0, 6), "ema50": round(s0, 6),
                "atr": round(volatility, 6), "rsi": round(strength, 2) if strength is not None else None}
    long_setup = f0 > s0 and closes[-2] <= f1 and closes[-1] > f0
    short_setup = f0 < s0 and closes[-2] >= f1 and closes[-1] < f0
    if long_setup:
        return ProSignal("long", volatility, "EMA20>EMA50, close reclaims EMA20 from below", snapshot)
    if short_setup and params.allow_short:
        return ProSignal("short", volatility, "EMA20<EMA50, close rejects EMA20 from above", snapshot)
    if short_setup:
        return ProSignal(None, volatility, "Short setup present but shorts disabled", snapshot)
    return ProSignal(None, volatility, "No qualifying setup", snapshot)
