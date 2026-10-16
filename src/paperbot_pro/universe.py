"""Top-N universe selection from CoinGecko with classification-based exclusion,
and resolution to exchange perp instruments from PUBLIC metadata only.

Stablecoins and wrapped/synthetic representations are excluded by CoinGecko
CATEGORY membership (fetched live), never by a hardcoded symbol blacklist.
If ranking data cannot be refreshed, the previous universe is kept and the
failure is audited — no partial overwrites, no guessed data.
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from .config import ProSettings
from .store import ProStore

COINGECKO = "https://api.coingecko.com/api/v3"
EXCLUDED_CATEGORIES = ("stablecoins", "wrapped-tokens", "liquid-staking-tokens")


@dataclass(frozen=True)
class UniverseCoin:
    coingecko_id: str
    symbol: str
    name: str
    rank: int
    price_usd: float | None
    change_24h_pct: float | None
    market_cap_usd: float | None
    volume_24h_usd: float | None


def select_top(markets: list[dict], excluded_ids: set[str], size: int) -> list[UniverseCoin]:
    """Pick the top `size` non-excluded coins by market-cap rank."""
    out: list[UniverseCoin] = []
    for m in sorted(markets, key=lambda m: m.get("market_cap_rank") or 10**9):
        if m["id"] in excluded_ids:
            continue
        out.append(UniverseCoin(
            coingecko_id=m["id"], symbol=m["symbol"].upper(), name=m.get("name", m["id"]),
            rank=m.get("market_cap_rank") or 0, price_usd=m.get("current_price"),
            change_24h_pct=m.get("price_change_percentage_24h"),
            market_cap_usd=m.get("market_cap"), volume_24h_usd=m.get("total_volume")))
        if len(out) == size:
            break
    return out


def apply_universe(store: ProStore, coins: list[UniverseCoin], now_ms: int) -> None:
    old_ids = [r["coingecko_id"] for r in store.conn.execute(
        "SELECT coingecko_id FROM universe ORDER BY rank")]
    new_ids = [c.coingecko_id for c in coins]
    added = [i for i in new_ids if i not in old_ids]
    removed = [i for i in old_ids if i not in new_ids]
    date = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    with store.conn:
        store.conn.execute("DELETE FROM universe")
        store.conn.executemany(
            "INSERT INTO universe VALUES(?,?,?,?,?,?,?,?,?)",
            [(c.coingecko_id, c.rank, c.symbol, c.name, c.price_usd, c.change_24h_pct,
              c.market_cap_usd, c.volume_24h_usd, now_ms) for c in coins])
        if added or removed:
            store.conn.execute(
                "INSERT INTO universe_changes(date, added, removed) VALUES(?,?,?)",
                (date, json.dumps(added), json.dumps(removed)))


def fetch_coingecko_universe(cfg: ProSettings, http_get) -> list[UniverseCoin]:
    """Live fetcher. http_get(url) -> parsed JSON. Two bounded calls per category
    plus one ranking call."""
    excluded: set[str] = set()
    for category in EXCLUDED_CATEGORIES:
        rows = http_get(f"{COINGECKO}/coins/markets?vs_currency=usd&category={category}"
                        "&order=market_cap_desc&per_page=250&page=1")
        excluded.update(r["id"] for r in rows)
    markets = http_get(f"{COINGECKO}/coins/markets?vs_currency=usd"
                       "&order=market_cap_desc&per_page=100&page=1")
    return select_top(markets, excluded, cfg.universe_size)


def refresh_universe(store: ProStore, cfg: ProSettings, fetcher, now_ms: int | None = None) -> bool:
    """Replace the universe atomically; on ANY failure keep the old one."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    try:
        coins = fetcher()
        if not coins or len(coins) < min(5, cfg.universe_size):
            raise ValueError(f"suspiciously small universe: {len(coins) if coins else 0}")
    except Exception as exc:
        store.audit("error", "universe",
                    f"refresh failed, keeping previous universe: {type(exc).__name__}: {exc}",
                    ts_ms=now_ms)
        return False
    apply_universe(store, coins, now_ms)
    store.audit("info", "universe", f"universe refreshed: {len(coins)} assets", ts_ms=now_ms)
    return True


def _maint_margin(market: dict, tiers_for_symbol: list | None) -> float | None:
    """Tier-1 maintenance margin rate from public leverage tiers, else from
    exchange market metadata. None when genuinely unavailable."""
    if tiers_for_symbol:
        tier = tiers_for_symbol[0]
        mmr = tier.get("maintenanceMarginRate") or tier.get("maintenanceMarginRatio")
        if mmr:
            return float(mmr)
    info = market.get("info") or {}
    raw = info.get("maintMarginPercent")
    if raw is not None:
        return float(raw) / 100.0
    return None


def resolve_instruments(coins: list[UniverseCoin],
                        markets_by_exchange: dict[str, dict],
                        tiers_by_exchange: dict[str, dict],
                        cfg: ProSettings) -> list[dict]:
    """Map each coin to the first exchange exposing a usable linear perp.

    Eligible ONLY when the contract exists with real metadata: active linear
    swap, known taker fee, price/amount precision, and a maintenance-margin
    rate. Anything missing -> NOT ELIGIBLE with the exact reason.
    """
    out = []
    for coin in coins:
        found = None
        reason = "no linear perp market on configured exchanges"
        for exchange in cfg.exchanges:
            markets = markets_by_exchange.get(exchange) or {}
            for quote in cfg.quote_currencies:
                market = markets.get(f"{coin.symbol}/{quote}:{quote}")
                if not market:
                    continue
                if not (market.get("swap") and market.get("linear") and market.get("active")):
                    reason = "market exists but is not an active linear swap"
                    continue
                taker = market.get("taker")
                precision = market.get("precision") or {}
                mmr = _maint_margin(market, (tiers_by_exchange.get(exchange) or {}).get(market["symbol"]))
                if taker is None:
                    reason = "no public fee metadata"
                    continue
                if precision.get("price") is None or precision.get("amount") is None:
                    reason = "no precision (tick/lot) metadata"
                    continue
                if mmr is None:
                    reason = "no maintenance margin data (leverage tiers unavailable)"
                    continue
                found = {"exchange": exchange, "symbol": market["symbol"],
                         "taker_fee": float(taker), "maint_margin_rate": mmr,
                         "tick_size": float(precision["price"]),
                         "lot_size": float(precision["amount"])}
                break
            if found:
                break
        row = {"coingecko_id": coin.coingecko_id, "eligible": found is not None,
               "reason": None if found else reason,
               "exchange": found["exchange"] if found else None,
               "symbol": found["symbol"] if found else None,
               "taker_fee": found["taker_fee"] if found else None,
               "maint_margin_rate": found["maint_margin_rate"] if found else None,
               "tick_size": found["tick_size"] if found else None,
               "lot_size": found["lot_size"] if found else None}
        out.append(row)
    return out


def store_instruments(store: ProStore, rows: list[dict], now_ms: int) -> None:
    with store.conn:
        for r in rows:
            store.conn.execute(
                "INSERT OR REPLACE INTO instruments VALUES(?,?,?,?,?,?,?,?,?,?)",
                (r["coingecko_id"], r["exchange"], r["symbol"], int(r["eligible"]),
                 r["reason"], r["taker_fee"], r["maint_margin_rate"],
                 r["tick_size"], r["lot_size"], now_ms))
