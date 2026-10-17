"""Five deterministic, reproducible Extreme Lab strategy evaluators.

Pure functions of COMPLETED candles plus observable context (funding rate,
listing age). Every evaluation returns an explanation whether or not it
fires. None of these patterns predicts the future; they are speculative
research hypotheses running on virtual funds only.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
from paperbot.models import Candle
from paperbot.strategy import atr
from .config import LabSettings
from ..scanner import StrategyParams, generate_signal

BREAKOUT_LOOKBACK = 48
BREAKOUT_VOLUME_X = 2.0
SQUEEZE_WICK_ATR_X = 2.0
SQUEEZE_FUNDING_ABS = 0.0003   # 0.03%/8h is an elevated funding reading
CRASH_DROP_PCT = -8.0          # over the last 24 bars (1h tf)
CRASH_WINDOW = 24


@dataclass(frozen=True)
class LabSignal:
    strategy: str
    action: str | None      # 'long' | 'short' | None
    atr: float
    reason: str
    indicators: dict


def _base(bars: list[Candle], cfg: LabSettings):
    volatility = atr(bars, 14)[-1]
    return volatility if volatility and volatility > 0 else None


def _breakout(bars, cfg, context, volatility) -> LabSignal:
    window = bars[-(BREAKOUT_LOOKBACK + 1):-1]
    last = bars[-1]
    volumes = [b.volume for b in bars[-21:-1]]
    vol_avg = mean(volumes) if volumes else 0.0
    vol_x = (last.volume / vol_avg) if vol_avg > 0 else 0.0
    high_break = last.close > max(b.high for b in window)
    low_break = last.close < min(b.low for b in window)
    ind = {"lookback_high": round(max(b.high for b in window), 6),
           "lookback_low": round(min(b.low for b in window), 6),
           "volume_x": round(vol_x, 2), "close": last.close}
    if high_break and vol_x >= BREAKOUT_VOLUME_X:
        return LabSignal("breakout", "long", volatility,
                         f"close broke {BREAKOUT_LOOKBACK}-bar high on {vol_x:.1f}x volume", ind)
    if low_break and vol_x >= BREAKOUT_VOLUME_X:
        return LabSignal("breakout", "short", volatility,
                         f"close broke {BREAKOUT_LOOKBACK}-bar low on {vol_x:.1f}x volume", ind)
    if high_break or low_break:
        return LabSignal("breakout", None, volatility,
                         f"range break without volume confirmation ({vol_x:.1f}x)", ind)
    return LabSignal("breakout", None, volatility, "no range break", ind)


def _launch_sniper(bars, cfg, context, volatility) -> LabSignal:
    age = context.get("listing_age_days")
    ind = {"listing_age_days": age}
    if age is None or age > cfg.launch_max_age_days:
        return LabSignal("launch_sniper", None, volatility,
                         f"no verified young market (listing age {age}d > {cfg.launch_max_age_days}d)",
                         ind)
    window = bars[-25:-1]
    last = bars[-1]
    if last.close > max(b.high for b in window):
        return LabSignal("launch_sniper", "long", volatility,
                         f"young listing ({age:.0f}d) breaking 24-bar high", ind)
    return LabSignal("launch_sniper", None, volatility,
                     f"young listing ({age:.0f}d) without momentum trigger", ind)


def _squeeze(bars, cfg, context, volatility) -> LabSignal:
    last = bars[-1]
    funding = context.get("funding_rate")
    lower_wick = min(last.open, last.close) - last.low
    upper_wick = last.high - max(last.open, last.close)
    ind = {"funding_rate": funding, "lower_wick_atr": round(lower_wick / volatility, 2),
           "upper_wick_atr": round(upper_wick / volatility, 2)}
    if funding is None:
        return LabSignal("squeeze", None, volatility, "funding data unavailable", ind)
    if lower_wick > SQUEEZE_WICK_ATR_X * volatility and funding <= -SQUEEZE_FUNDING_ABS:
        return LabSignal("squeeze", "long", volatility,
                         "deep lower wick with crowded-short funding: fading the squeeze", ind)
    if upper_wick > SQUEEZE_WICK_ATR_X * volatility and funding >= SQUEEZE_FUNDING_ABS:
        return LabSignal("squeeze", "short", volatility,
                         "deep upper wick with crowded-long funding: fading the squeeze", ind)
    if lower_wick > SQUEEZE_WICK_ATR_X * volatility or upper_wick > SQUEEZE_WICK_ATR_X * volatility:
        return LabSignal("squeeze", None, volatility,
                         "large wick but funding not at an extreme", ind)
    return LabSignal("squeeze", None, volatility, "no squeeze signature", ind)


def _trend(bars, cfg, context, volatility) -> LabSignal:
    signal = generate_signal(bars, StrategyParams())
    return LabSignal("trend", signal.action, signal.atr or volatility,
                     signal.reason, signal.indicators)


def _crash_reversal(bars, cfg, context, volatility) -> LabSignal:
    if len(bars) < CRASH_WINDOW + 2:
        return LabSignal("crash_reversal", None, volatility, "insufficient history", {})
    last = bars[-1]
    ref = bars[-(CRASH_WINDOW + 1)].close
    drop_pct = (last.close / ref - 1) * 100
    body = abs(last.close - last.open)
    lower_wick = min(last.open, last.close) - last.low
    reversal = last.close > last.open and lower_wick > body
    ind = {"drop_24h_pct": round(drop_pct, 2), "reversal_candle": reversal}
    if drop_pct <= CRASH_DROP_PCT and reversal:
        return LabSignal("crash_reversal", "long", volatility,
                         f"{drop_pct:.1f}% 24h drop with hammer reversal candle", ind)
    if drop_pct <= CRASH_DROP_PCT:
        return LabSignal("crash_reversal", None, volatility,
                         f"{drop_pct:.1f}% drop but no reversal candle yet", ind)
    return LabSignal("crash_reversal", None, volatility, "no crash signature", ind)


def evaluate_all(bars: list[Candle], cfg: LabSettings, context: dict) -> dict[str, LabSignal]:
    """Evaluate every strategy on completed candles. Always returns all five
    with explanations, fired or not."""
    if len(bars) < cfg.min_bars:
        return {k: LabSignal(k, None, 0.0, "insufficient history", {})
                for k in ("breakout", "launch_sniper", "squeeze", "trend", "crash_reversal")}
    volatility = _base(bars, cfg)
    if volatility is None:
        return {k: LabSignal(k, None, 0.0, "ATR warming up", {})
                for k in ("breakout", "launch_sniper", "squeeze", "trend", "crash_reversal")}
    return {
        "breakout": _breakout(bars, cfg, context, volatility),
        "launch_sniper": _launch_sniper(bars, cfg, context, volatility),
        "squeeze": _squeeze(bars, cfg, context, volatility),
        "trend": _trend(bars, cfg, context, volatility),
        "crash_reversal": _crash_reversal(bars, cfg, context, volatility),
    }
