"""Five Research Lab strategy evaluators.

Pure functions of COMPLETED candles plus observable context (higher-timeframe
trend direction, funding rate, and for order-flow a public order-book
snapshot with freshness/spread). Every evaluation explains itself. None of
these thresholds is validated; they are research hypotheses on virtual funds.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
from paperbot.models import Candle
from paperbot.strategy import atr, ema
from ..indicators import rsi
from .config import ResearchSettings
from .indicators import adx, bollinger, relative_volume, vwap_session

ADX_TREND_MIN = 22.0
ADX_RANGE_MAX = 18.0
BREAKOUT_LOOKBACK = 20
RELVOL_MIN = 1.5
OFI_IMBALANCE_MIN = 0.25     # weighted depth imbalance threshold
OFI_DEPTH_MIN_USD = 0.0      # (notional filter applied via spread/liquidity)


@dataclass(frozen=True)
class ResearchSignal:
    strategy: str
    action: str | None
    atr: float
    reason: str
    indicators: dict
    corr_cluster: str = ""


def _corr_cluster(symbol: str) -> str:
    return symbol.split("/")[0]


def _warm(bars, cfg):
    vol = atr(bars, 14)[-1]
    return vol if vol and vol > 0 else None


def _regime_trend(bars, cfg, context, vol) -> ResearchSignal:
    closes = [b.close for b in bars]
    e50, e200 = ema(closes, 50), ema(closes, min(200, len(closes) - 1))
    a = adx(bars, 14)[-1]
    ind = {"adx": round(a, 1) if a else None, "ema50": round(e50[-1], 4) if e50[-1] else None,
           "htf_4h": context.get("htf_trend_4h")}
    if a is None or e50[-1] is None or e200[-1] is None:
        return ResearchSignal("regime_trend", None, vol, "indicators warming up", ind)
    if a < ADX_TREND_MIN:
        return ResearchSignal("regime_trend", None, vol, f"ADX {a:.0f} < {ADX_TREND_MIN:.0f}: no trend", ind)
    up = e50[-1] > e200[-1] and context.get("htf_trend_4h") == "up" and closes[-1] > e50[-1]
    dn = e50[-1] < e200[-1] and context.get("htf_trend_4h") == "down" and closes[-1] < e50[-1]
    if up:
        return ResearchSignal("regime_trend", "long", vol,
                              f"4h up-regime, ADX {a:.0f}, price>EMA50", ind)
    if dn:
        return ResearchSignal("regime_trend", "short", vol,
                              f"4h down-regime, ADX {a:.0f}, price<EMA50", ind)
    return ResearchSignal("regime_trend", None, vol, "regime filter not aligned", ind)


def _volatility_breakout(bars, cfg, context, vol) -> ResearchSignal:
    closes = [b.close for b in bars]
    _, upper, lower, width = bollinger(closes, 20, 2.0)
    rv = relative_volume(bars, 20)[-1]
    recent_widths = [w for w in width[-25:-1] if w is not None]
    compressed = (recent_widths and width[-2] is not None
                  and width[-2] <= min(recent_widths) * 1.15)
    atr_now = atr(bars, 14)
    falling_atr = (len(atr_now) > 6 and atr_now[-2] is not None and atr_now[-6] is not None
                   and atr_now[-2] < atr_now[-6])
    window = bars[-(BREAKOUT_LOOKBACK + 1):-1]
    hi, lo = max(b.high for b in window), min(b.low for b in window)
    last = bars[-1]
    ind = {"rel_vol": round(rv, 2) if rv else None, "bb_width": round(width[-1], 5) if width[-1] else None,
           "compressed": bool(compressed or falling_atr), "lookback_high": round(hi, 4)}
    if rv is None:
        return ResearchSignal("volatility_breakout", None, vol, "rel-volume warming up", ind)
    if not (compressed or falling_atr):
        return ResearchSignal("volatility_breakout", None, vol, "no compression/falling ATR", ind)
    if rv < RELVOL_MIN:
        return ResearchSignal("volatility_breakout", None, vol,
                              f"rel-volume {rv:.1f}x < {RELVOL_MIN}x", ind)
    if last.close > hi:
        return ResearchSignal("volatility_breakout", "long", vol,
                              f"break of {BREAKOUT_LOOKBACK}-bar high on {rv:.1f}x vol after compression", ind)
    if last.close < lo:
        return ResearchSignal("volatility_breakout", "short", vol,
                              f"break of {BREAKOUT_LOOKBACK}-bar low on {rv:.1f}x vol after compression", ind)
    return ResearchSignal("volatility_breakout", None, vol, "compression but no range break", ind)


def _trend_pullback(bars, cfg, context, vol) -> ResearchSignal:
    closes = [b.close for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    ind = {"ema20": round(e20[-1], 4) if e20[-1] else None, "htf_1h": context.get("htf_trend_1h")}
    if e20[-1] is None or e50[-1] is None:
        return ResearchSignal("trend_pullback", None, vol, "EMAs warming up", ind)
    up_trend = e20[-1] > e50[-1] and context.get("htf_trend_1h") == "up"
    dn_trend = e20[-1] < e50[-1] and context.get("htf_trend_1h") == "down"
    # pullback near EMA20 then a structural reclaim (prev close below, now above)
    reclaim_up = up_trend and closes[-2] <= e20[-2] and closes[-1] > e20[-1]
    reclaim_dn = dn_trend and closes[-2] >= e20[-2] and closes[-1] < e20[-1]
    if reclaim_up:
        return ResearchSignal("trend_pullback", "long", vol,
                              "HTF up-trend, pullback to EMA20 reclaimed", ind)
    if reclaim_dn:
        return ResearchSignal("trend_pullback", "short", vol,
                              "HTF down-trend, pullback to EMA20 rejected", ind)
    return ResearchSignal("trend_pullback", None, vol, "no confirmed pullback reclaim", ind)


def _range_reversion(bars, cfg, context, vol) -> ResearchSignal:
    closes = [b.close for b in bars]
    a = adx(bars, 14)[-1]
    _, upper, lower, _ = bollinger(closes, 20, 2.0)
    strength = rsi(closes, 14)[-1]
    ind = {"adx": round(a, 1) if a else None, "rsi": round(strength, 1) if strength else None}
    if a is None or upper[-1] is None:
        return ResearchSignal("range_reversion", None, vol, "indicators warming up", ind)
    if a >= ADX_RANGE_MAX:
        return ResearchSignal("range_reversion", None, vol,
                              f"ADX {a:.0f} >= {ADX_RANGE_MAX:.0f}: trending, strategy suspended", ind)
    # poked below the band (prev low) and closed back inside; optional RSI
    below = bars[-1].low < lower[-1] and closes[-1] > lower[-1]
    above = bars[-1].high > upper[-1] and closes[-1] < upper[-1]
    if below and (strength is None or strength < 40):
        return ResearchSignal("range_reversion", "long", vol,
                              "range: wick below lower band, closed back inside", ind)
    if above and (strength is None or strength > 60):
        return ResearchSignal("range_reversion", "short", vol,
                              "range: wick above upper band, closed back inside", ind)
    return ResearchSignal("range_reversion", None, vol, "no band re-entry", ind)


def _orderflow_imbalance(bars, cfg, context, vol) -> ResearchSignal:
    book = context.get("orderbook")
    if book is None:
        return ResearchSignal("orderflow_imbalance", None, vol, "no order book available", {})
    age = book.get("age_s")
    spread = book.get("spread_pct")
    if age is None or age > cfg.orderbook_fresh_seconds:
        return ResearchSignal("orderflow_imbalance", None, vol,
                              f"order book stale ({age}s): rejecting", {"age_s": age})
    if spread is not None and spread > cfg.max_spread_pct:
        return ResearchSignal("orderflow_imbalance", None, vol,
                              f"spread {spread:.4%} too wide for order-flow signal", {})
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return ResearchSignal("orderflow_imbalance", None, vol, "incomplete order book", {})
    # distance-weighted depth within the top levels
    best = (bids[0][0] + asks[0][0]) / 2
    def weighted(levels, sign):
        total = 0.0
        for price, size in levels[:10]:
            w = 1.0 / (1.0 + abs(price - best) / best * 1000)
            total += size * w
        return total
    bid_depth = weighted(bids, 1)
    ask_depth = weighted(asks, -1)
    denom = bid_depth + ask_depth
    imbalance = (bid_depth - ask_depth) / denom if denom else 0.0
    ind = {"imbalance": round(imbalance, 3), "age_s": age}
    if imbalance >= OFI_IMBALANCE_MIN:
        return ResearchSignal("orderflow_imbalance", "long", vol,
                              f"bid-weighted depth imbalance {imbalance:+.2f}", ind)
    if imbalance <= -OFI_IMBALANCE_MIN:
        return ResearchSignal("orderflow_imbalance", "short", vol,
                              f"ask-weighted depth imbalance {imbalance:+.2f}", ind)
    return ResearchSignal("orderflow_imbalance", None, vol,
                          f"book near balance ({imbalance:+.2f})", ind)


_EVALUATORS = {
    "regime_trend": _regime_trend,
    "volatility_breakout": _volatility_breakout,
    "trend_pullback": _trend_pullback,
    "range_reversion": _range_reversion,
    "orderflow_imbalance": _orderflow_imbalance,
}


def evaluate_all(bars: list[Candle], cfg: ResearchSettings,
                 context: dict) -> dict[str, ResearchSignal]:
    keys = list(_EVALUATORS)
    if len(bars) < cfg.min_bars:
        return {k: ResearchSignal(k, None, 0.0, "insufficient history", {}) for k in keys}
    vol = _warm(bars, cfg)
    if vol is None:
        return {k: ResearchSignal(k, None, 0.0, "ATR warming up", {}) for k in keys}
    out = {}
    for k, fn in _EVALUATORS.items():
        sig = fn(bars, cfg, context, vol)
        # attach correlation cluster from the traded symbol (set by engine)
        out[k] = sig
    return out
