"""Bounded public market data access with TTL caching and visible staleness.

PUBLIC endpoints only (ccxt without credentials). A fetch failure never
fabricates data: the cache serves the last good value with its true age, and
callers decide whether that age is acceptable.
"""
from __future__ import annotations
import time
from .config import ProSettings
from .store import ProStore

CANDLE_TTL_S = {"5m": 60, "15m": 120, "1h": 180, "4h": 600, "1d": 1800}
ALLOWED_TF = tuple(CANDLE_TTL_S)


class TTLCache:
    def __init__(self, clock=time.time):
        self.clock = clock
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str, ttl_seconds: float, fetch):
        """Returns (value, age_seconds). Serves cache within TTL; on fetch
        failure serves the stale value with its real age rather than hiding
        the outage; raises only when there is nothing at all to serve."""
        now = self.clock()
        cached = self._data.get(key)
        if cached is not None and now - cached[0] <= ttl_seconds:
            return cached[1], now - cached[0]
        try:
            value = fetch()
        except Exception:
            if cached is not None:
                return cached[1], now - cached[0]
            raise
        self._data[key] = (now, value)
        return value, 0.0


class MarketData:
    """Lazy public ccxt clients + caches. One instance per process."""
    def __init__(self, cfg: ProSettings):
        self.cfg = cfg
        self._clients: dict[str, object] = {}
        self.cache = TTLCache()

    def client(self, exchange: str):
        if exchange not in self._clients:
            import ccxt
            self._clients[exchange] = getattr(ccxt, exchange)({"enableRateLimit": True})
        return self._clients[exchange]

    def markets(self, exchange: str) -> dict:
        value, _age = self.cache.get(
            f"markets:{exchange}", ttl_seconds=self.cfg.universe_refresh_hours * 3600,
            fetch=lambda: self.client(exchange).load_markets())
        return value

    def leverage_tiers(self, exchange: str) -> dict:
        def fetch():
            client = self.client(exchange)
            if client.has.get("fetchLeverageTiers"):
                return client.fetch_leverage_tiers()
            return {}
        value, _age = self.cache.get(f"tiers:{exchange}",
                                     ttl_seconds=self.cfg.universe_refresh_hours * 3600,
                                     fetch=fetch)
        return value

    def candles(self, exchange: str, symbol: str, tf: str, limit: int = 300):
        if tf not in ALLOWED_TF:
            raise ValueError(f"timeframe must be one of {ALLOWED_TF}")
        return self.cache.get(
            f"ohlcv:{exchange}:{symbol}:{tf}:{limit}", ttl_seconds=CANDLE_TTL_S[tf],
            fetch=lambda: self.client(exchange).fetch_ohlcv(symbol, tf, limit=limit))

    def ticker(self, exchange: str, symbol: str):
        return self.cache.get(
            f"ticker:{exchange}:{symbol}", ttl_seconds=20,
            fetch=lambda: self.client(exchange).fetch_ticker(symbol))

    def funding_rate(self, exchange: str, symbol: str):
        def fetch():
            client = self.client(exchange)
            if client.has.get("fetchFundingRate"):
                return client.fetch_funding_rate(symbol)
            return None
        return self.cache.get(f"funding:{exchange}:{symbol}", ttl_seconds=600, fetch=fetch)


_SHARED: MarketData | None = None


def shared_marketdata(cfg: ProSettings) -> MarketData:
    global _SHARED
    if _SHARED is None:
        _SHARED = MarketData(cfg)
    return _SHARED


def fetch_candles_cached(store: ProStore, cfg: ProSettings, symbol: str,
                         tf: str, limit: int):
    """API helper: resolve the symbol's exchange from stored instruments and
    return raw [[ts,o,h,l,c,v],...]."""
    row = store.conn.execute(
        "SELECT exchange FROM instruments WHERE symbol=? AND eligible=1", (symbol,)).fetchone()
    if row is None:
        raise ValueError(f"no eligible instrument stored for {symbol}")
    md = shared_marketdata(cfg)
    candles, _age = md.candles(row["exchange"], symbol, tf, min(limit, 1000))
    return candles
