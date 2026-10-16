"""Deterministic indicators beyond the legacy ema/atr. Pure functions."""
from __future__ import annotations


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI. None during warmup (needs period+1 values)."""
    out: list[float | None] = [None] * len(values)
    if len(values) < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def to_rsi(g, l):
        if l == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + g / l)
    out[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = to_rsi(avg_gain, avg_loss)
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line) lists with None warmups."""
    from paperbot.strategy import ema
    ef, es = ema(values, fast), ema(values, slow)
    line: list[float | None] = [None if (a is None or b is None) else a - b
                                for a, b in zip(ef, es)]
    valid = [v for v in line if v is not None]
    sig_valid = ema(valid, signal) if len(valid) >= signal else [None] * len(valid)
    sig: list[float | None] = [None] * (len(line) - len(sig_valid)) + sig_valid
    return line, sig
