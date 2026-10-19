"""Point-in-time eligible universes for the CRH lab.

Daily top-N by CoinGecko market cap at 00:00 UTC (the last cap reading at or
before midnight), the engine's category exclusions (stablecoins, wrapped and
liquid-staking tokens), mapped to Bybit USDT linear perpetuals:
  {SYM}USDT  else  1000{SYM}USDT (contract on 1,000 units; multiplier 1000)
A coin is ELIGIBLE on a day only if the contract is an active linear
perpetual, listed before that day, with public tier-1 maintenance margin,
tick and lot size. Everything else is NOT ELIGIBLE with a recorded reason.

Known limitation (labelled in every result): the candidate set is today's
top ~250 non-excluded coins, so a coin that was top-N historically but has
since fallen out of the top 250 is missed (survivorship). Contracts Bybit
has delisted are not returned by its public API and cannot be verified.
"""
from __future__ import annotations
import bisect
import calendar
import datetime as dt
import json
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .data import Cache, DAY_MS

CG = "https://api.coingecko.com/api/v3"
EXCLUDED_CATEGORIES = ("stablecoins", "wrapped-tokens", "liquid-staking-tokens")
_last_cg_call = [0.0]
SURVIVORSHIP_NOTE = ("Candidates = the 3N coins ranked highest TODAY (non-excluded); a coin that "
                     "was top-N on a past day but has since fallen below rank 3N is missed.")


def _cg_get(url: str, min_gap_s: float = 2.2):
    import requests
    for attempt in range(8):
        wait = min_gap_s - (time.time() - _last_cg_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_cg_call[0] = time.time()
        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        time.sleep(5)
    raise RuntimeError(f"CoinGecko unavailable: {url}")


def day_ms(date: str) -> int:
    return calendar.timegm(time.strptime(date, "%Y-%m-%d")) * 1000


def days_between(t0: int, t1: int) -> list[str]:
    out, d = [], t0 - t0 % DAY_MS
    while d < t1:
        out.append(dt.datetime.fromtimestamp(d / 1000, dt.timezone.utc).strftime("%Y-%m-%d"))
        d += DAY_MS
    return out


class UniverseBuilder:
    def __init__(self, cache: Cache):
        self.cache = cache
        self.root = cache.root / "coingecko"

    # ------------------------------------------------------- candidates
    def candidates(self, size: int | None = None) -> list[dict]:
        """Today's top-500 non-excluded coins (cached per UTC day) merged with
        every coin seen in earlier candidate snapshots. With `size`, only the
        first 3*size by current rank are returned (bounded CoinGecko calls;
        labelled survivorship limitation)."""
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        p = self.root / f"candidates_{today}.json"
        if not p.exists():
            if self.cache.offline:
                older = sorted(self.root.glob("candidates_*.json"))
                if not older:
                    raise RuntimeError("offline and no cached CoinGecko candidates")
                p = older[-1]
            else:
                excluded = set()
                for cat in EXCLUDED_CATEGORIES:
                    for page in (1, 2):
                        rows = _cg_get(f"{CG}/coins/markets?vs_currency=usd&category={cat}"
                                       f"&order=market_cap_desc&per_page=250&page={page}")
                        excluded.update(x["id"] for x in rows)
                        if len(rows) < 250:
                            break
                markets = []
                for page in (1, 2):
                    markets += _cg_get(f"{CG}/coins/markets?vs_currency=usd&order=market_cap_desc"
                                       f"&per_page=250&page={page}")
                cands = {m["id"]: {"id": m["id"], "symbol": m["symbol"].upper(),
                                   "name": m.get("name")}
                         for m in markets if m["id"] not in excluded}
                for old in self.root.glob("candidates_*.json"):
                    for c in json.loads(old.read_text())["candidates"]:
                        cands.setdefault(c["id"], c)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"fetched_utc": today, "excluded_ids": sorted(excluded),
                                         "candidates": list(cands.values())}))
        cands = json.loads(p.read_text())["candidates"]
        return cands[: 3 * size] if size else cands

    # ---------------------------------------------------------- market caps
    def _caps(self, cid: str, t0: int, t1: int) -> list[tuple[int, float]]:
        """Daily 00:00 UTC market caps for [t0, t1), cached with coverage."""
        p = self.root / "caps" / f"{cid}.parquet"
        cov_p = p.with_suffix(".coverage.json")
        cov = json.loads(cov_p.read_text())["ranges"] if cov_p.exists() else []
        rows = {}
        if p.exists():
            t = pq.read_table(p)
            rows = {int(a): float(b) for a, b in zip(t.column("day").to_pylist(),
                                                     t.column("cap").to_pylist())}
        from .data import missing_ranges
        gaps = missing_ranges(cov, t0 - t0 % DAY_MS, t1)
        if gaps and not self.cache.offline:
            # one call per coin covers the last 120 days (daily points), so any
            # later window inside that span is served from the cache
            now_day = int(time.time() * 1000) // DAY_MS * DAY_MS
            lo = min(min(a for a, _ in gaps), now_day - 120 * DAY_MS)
            gaps = missing_ranges(cov, lo, max(t1, now_day + DAY_MS))
            for a, b in gaps:
                # pull raw points for [a-1d, b] then sample the last point <= each midnight
                d = _cg_get(f"{CG}/coins/{cid}/market_chart/range?vs_currency=usd"
                            f"&from={(a - DAY_MS) // 1000}&to={b // 1000}")
                pts = d.get("market_caps") or []
                ts = [x[0] for x in pts]
                day = a
                while day < b:
                    i = bisect.bisect_right(ts, day) - 1
                    if i >= 0 and pts[i][1]:
                        rows[day] = float(pts[i][1])
                    day += DAY_MS
                cov.append([a, b])
            p.parent.mkdir(parents=True, exist_ok=True)
            days = sorted(rows)
            pq.write_table(pa.table({"day": pa.array(days, pa.int64()),
                                     "cap": pa.array([rows[k] for k in days])}), p)
            cov_p.write_text(json.dumps({"ranges": cov}))
        return [(k, v) for k, v in sorted(rows.items()) if t0 <= k < t1]

    # ------------------------------------------------------------ build
    def daily_top(self, size: int, t0: int, t1: int, progress=None, cancelled=None) -> dict:
        """{date: [ {id, symbol, cap, rank}, ... ]} for every UTC day in [t0, t1)."""
        cands = self.candidates(size)
        days = days_between(t0, t1)
        caps: dict[str, dict[int, float]] = {}
        for i, c in enumerate(cands):
            if cancelled and cancelled():
                raise RuntimeError("cancelled")
            caps[c["id"]] = dict(self._caps(c["id"], day_ms(days[0]), day_ms(days[-1]) + DAY_MS))
            if progress:
                progress("universe", (i + 1) / len(cands), c["id"])
        sym_of = {c["id"]: c["symbol"] for c in cands}
        out = {}
        for d in days:
            dm = day_ms(d)
            ranked = sorted(((caps[cid].get(dm) or 0.0), cid) for cid in caps)
            ranked = [(cap, cid) for cap, cid in ranked[::-1] if cap > 0][:size]
            out[d] = [{"id": cid, "symbol": sym_of[cid], "cap": cap, "rank": r + 1}
                      for r, (cap, cid) in enumerate(ranked)]
        return out

    def map_instruments(self, daily: dict) -> tuple[dict, dict, dict]:
        """Returns (universe {date: [ccxt symbols]}, instruments {ccxt: meta},
        ineligible {coin id: reason})."""
        rows = {r["symbol"]: r for r in self.cache.instruments_info()}
        universe, instruments, ineligible = {}, {}, {}
        for date, coins in daily.items():
            dm = day_ms(date)
            universe[date] = []
            for c in coins:
                base = c["symbol"]
                for cand, mult in ((f"{base}USDT", 1), (f"1000{base}USDT", 1000)):
                    r = rows.get(cand)
                    if r is not None:
                        break
                else:
                    ineligible[c["id"]] = f"no Bybit linear perp {base}USDT / 1000{base}USDT"
                    continue
                if r["contractType"] != "LinearPerpetual" or r["status"] != "Trading":
                    ineligible[c["id"]] = f"{cand} not an active linear perpetual"
                    continue
                if int(r["launchTime"]) >= dm:
                    ineligible[c["id"]] = f"{cand} listed after {date}"
                    continue
                ccxt = f"{cand[:-4]}/USDT:USDT"
                if ccxt not in instruments:
                    rl = self.cache.risk_tier1(cand)
                    if not rl.get("maintenanceMargin"):
                        ineligible[c["id"]] = f"{cand} maintenance margin unavailable"
                        continue
                    instruments[ccxt] = {
                        "coingecko_id": c["id"], "exchange": "bybit", "symbol": ccxt,
                        "bybit_symbol": cand, "contract_multiplier": mult,
                        "eligible": 1, "taker_fee": 0.0006,
                        "maint_margin_rate": float(rl["maintenanceMargin"]),
                        "tick_size": float(r["priceFilter"]["tickSize"]),
                        "lot_size": float(r["lotSizeFilter"]["qtyStep"]),
                        "launch_ms": int(r["launchTime"]),
                        "source": "Bybit public instruments-info + risk-limit tier 1; "
                                  "fee = engine default 0.06%"}
                universe[date].append(ccxt)
        return universe, instruments, ineligible
