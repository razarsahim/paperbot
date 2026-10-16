from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Candle:
    timestamp: int  # UTC candle opening time, milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self) -> None:
        if self.timestamp < 0 or min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("Invalid candle timestamp or price")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Inconsistent candle OHLC")
        if self.volume < 0:
            raise ValueError("Negative volume")

    @property
    def iso(self) -> str:
        return datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    observed_ms: int

    def validate(self, max_spread_pct: float) -> None:
        if not (0 < self.bid <= self.ask):
            raise ValueError("Invalid public market quote")
        if (self.ask - self.bid) / self.ask > max_spread_pct:
            raise ValueError("Spread too wide; refusing simulated fill")
