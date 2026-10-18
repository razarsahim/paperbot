"""Point-in-time historical market adapter for the unchanged LabEngine.

Implements the same duck-typed surface as MarketData (candles, ticker,
funding_rate, and optionally orderbook) but answers ONLY with information
that existed at the simulated clock `now_ms`:

- 1h candles: bars with open time + 1h <= now are complete; the forming bar is
  rebuilt from 1m bars that have fully closed before now (never later data).
- ticker: best bid/ask from the archived order book as of now; `last` is the
  close of the latest fully-closed 1m bar. Age = now - last book update.
- funding: the most recent SETTLED funding rate with timestamp <= now (the
  live engine sees the predicted next rate, which is not archived).
- orderbook: archived top-10 levels as of now with true age and spread.

Any request that would need data beyond `now` is impossible by construction;
`assert_no_future` is used by tests to prove it.
"""
from __future__ import annotations
import bisect
import gzip
import json
from pathlib import Path

HOUR_MS = 3_600_000
MIN_MS = 60_000


def bybit_id(ccxt_symbol: str) -> str:
    """'BTC/USDT:USDT' -> 'BTCUSDT'."""
    base, rest = ccxt_symbol.split("/")
    return base + rest.split(":")[0]


class SymbolData:
    def __init__(self, k1h: list, k1m: list, funding: list, books: dict | None):
        self.k1h = k1h
        self.k1h_ts = [r[0] for r in k1h]
        self.k1m = k1m
        self.k1m_ts = [r[0] for r in k1m]
        self.k1m_by_ts = {r[0]: r for r in k1m}
        self.funding = funding
        self.funding_ts = [f["ts"] for f in funding]
        self.books = books or {}   # cycle_time -> [t, last_ts, bids, asks]


def load_symbol(data_dir: Path, sym: str, book_dir: Path | None,
                top_n: int = 10) -> SymbolData:
    def rows(name):
        return json.loads((data_dir / name / f"{sym}.json").read_text())["rows"]
    books = {}
    if book_dir is not None and (book_dir / sym).exists():
        for f in sorted((book_dir / sym).glob("*.json.gz")):
            for s in json.loads(gzip.decompress(f.read_bytes()))["samples"]:
                if s[1] is not None:
                    books[s[0]] = [s[0], s[1], s[2][:top_n], s[3][:top_n]]
    return SymbolData(rows("kline_1h"), rows("kline_1m"), rows("funding"), books)


class HistoricalMarket:
    def __init__(self, data: dict[str, SymbolData], with_orderbook: bool = True):
        self.data = data
        self.now_ms = 0
        self.with_orderbook = with_orderbook
        self.max_ts_served = 0     # leakage audit: newest data timestamp handed out

    def set_now(self, now_ms: int) -> None:
        self.now_ms = now_ms

    def _served(self, ts: int) -> None:
        if ts > self.max_ts_served:
            self.max_ts_served = ts
        if ts > self.now_ms:
            raise AssertionError(f"look-ahead: served data at {ts} > now {self.now_ms}")

    def _sd(self, symbol: str) -> SymbolData:
        sd = self.data.get(bybit_id(symbol))
        if sd is None:
            raise KeyError(f"no historical data for {symbol}")
        return sd

    # -- MarketData surface ------------------------------------------------
    def candles(self, exchange: str, symbol: str, tf: str, limit: int = 300):
        if tf != "1h":
            raise ValueError("replay serves 1h signal candles only")
        sd = self._sd(symbol)
        now = self.now_ms
        hour_start = now - now % HOUR_MS
        i = bisect.bisect_left(sd.k1h_ts, hour_start)   # bars strictly before forming hour
        closed = [r[:6] for r in sd.k1h[max(0, i - limit):i]]
        for r in closed:
            self._served(r[0] + HOUR_MS)                 # its close time must be <= now
        # forming bar from completed 1m bars in [hour_start, now)
        last_full_min = now - now % MIN_MS               # 1m bars with ts+60s <= now
        j0 = bisect.bisect_left(sd.k1m_ts, hour_start)
        j1 = bisect.bisect_left(sd.k1m_ts, last_full_min)
        mins = sd.k1m[j0:j1]
        if mins:
            for m in mins:
                self._served(m[0] + MIN_MS)
            forming = [hour_start, mins[0][1], max(m[2] for m in mins),
                       min(m[3] for m in mins), mins[-1][4], sum(m[5] for m in mins)]
        elif hour_start in sd.k1m_by_ts:
            o = sd.k1m_by_ts[hour_start][1]              # opening print only
            forming = [hour_start, o, o, o, o, 0.0]
        else:
            forming = None
        raw = closed + ([forming] if forming else [])
        return raw[-limit:], 0.0

    def last_trade(self, symbol: str) -> float | None:
        sd = self._sd(symbol)
        now = self.now_ms
        j = bisect.bisect_left(sd.k1m_ts, now - now % MIN_MS) - 1
        if j < 0:
            return None
        self._served(sd.k1m[j][0] + MIN_MS)
        return sd.k1m[j][4]

    def book(self, symbol: str):
        sd = self._sd(symbol)
        s = sd.books.get(self.now_ms)
        if s is None:
            return None
        self._served(s[1])
        return s

    def ticker(self, exchange: str, symbol: str):
        s = self.book(symbol)
        last = self.last_trade(symbol)
        if s is None or not s[2] or not s[3]:
            raise ConnectionError(f"no archived book for {symbol} at {self.now_ms}")
        age = (self.now_ms - s[1]) / 1000.0
        return {"bid": s[2][0][0], "ask": s[3][0][0], "last": last}, age

    def funding_rate(self, exchange: str, symbol: str):
        sd = self._sd(symbol)
        k = bisect.bisect_right(sd.funding_ts, self.now_ms) - 1
        if k < 0:
            return None, 0.0
        f = sd.funding[k]
        self._served(f["ts"])
        return {"fundingRate": f["rate"], "fundingTimestamp": f["ts"]}, \
            (self.now_ms - f["ts"]) / 1000.0

    def __getattr__(self, name):
        # `orderbook` exists only when wired, mirroring an optional market hook
        if name == "orderbook" and self.__dict__.get("with_orderbook"):
            return self._orderbook
        raise AttributeError(name)

    def _orderbook(self, exchange: str, symbol: str):
        s = self.book(symbol)
        if s is None:
            raise ConnectionError("no archived book")
        bids, asks = s[2], s[3]
        age = (self.now_ms - s[1]) / 1000.0
        spread = ((asks[0][0] - bids[0][0]) / asks[0][0]) if bids and asks else None
        return {"bids": bids, "asks": asks, "age_s": age, "spread_pct": spread}, age

    # -- replay helpers ----------------------------------------------------
    def minute_bar(self, symbol: str, minute_start: int):
        bar = self._sd(symbol).k1m_by_ts.get(minute_start)
        if bar is not None:
            self._served(bar[0] + MIN_MS)
        return bar
