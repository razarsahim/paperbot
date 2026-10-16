from __future__ import annotations
import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from .models import Candle, Quote


def load_csv(path: str) -> list[Candle]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        out = [Candle(int(row["timestamp"]), float(row["open"]), float(row["high"]),
                      float(row["low"]), float(row["close"]), float(row["volume"])) for row in reader]
    if not out:
        raise ValueError("Empty candle CSV")
    for c in out:
        c.validate()
    if any(a.timestamp >= b.timestamp for a, b in zip(out, out[1:])):
        raise ValueError("Candles must be ordered uniquely, oldest first")
    return out


class PublicSpotMarket:
    """Read-only public data only: no exchange keys, no order API, no futures."""
    def __init__(self, exchange: str, symbol: str, timeframe="1h"):
        import ccxt  # optional for offline backtests
        if exchange not in ("kraken", "coinbase", "bitstamp"):
            raise ValueError("Only explicitly allowed spot-data exchanges supported")
        self.client = getattr(ccxt, exchange)({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        self.client.load_markets()
        market = self.client.market(symbol)
        if not market.get("spot") or market.get("contract"):
            raise ValueError("Only spot markets are allowed")
        self.symbol = symbol
        self.timeframe = timeframe

    def historical(self, limit: int = 720) -> list[Candle]:
        """Download exchange-limited PUBLIC spot candles; no private API access."""
        if not 100 <= limit <= 720:
            raise ValueError("Historical download limit must be from 100 to 720")
        raw = self.client.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
        now_ms = int(time.time() * 1000)
        bars = [Candle(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw]
        closed = [b for b in bars if b.timestamp + 3_600_000 <= now_ms - 3000]
        if len(closed) < 100:
            raise ValueError("Not enough completed candles returned by exchange")
        for b in closed:
            b.validate()
        if any(b.timestamp - a.timestamp != 3_600_000 for a, b in zip(closed, closed[1:])):
            raise ValueError("Exchange history contains gaps or duplicate bars")
        return closed

    def snapshot(self) -> tuple[list[Candle], Quote]:
        raw = self.client.fetch_ohlcv(self.symbol, self.timeframe, limit=180)
        now_ms = int(time.time() * 1000)
        bars = [Candle(int(x[0]), *[float(v) for v in x[1:6]]) for x in raw]
        # Include only candles whose end has passed; exchange may return live candle.
        closed = [b for b in bars if b.timestamp + 3_600_000 <= now_ms - 3000]
        ticker = self.client.fetch_ticker(self.symbol)
        bid, ask = ticker.get("bid"), ticker.get("ask")
        if bid is None or ask is None:
            raise ValueError("Exchange did not provide both bid and ask; no synthetic fill")
        observed_ms = int(ticker.get("timestamp") or time.time() * 1000)
        quote = Quote(float(bid), float(ask), observed_ms)
        return closed, quote
