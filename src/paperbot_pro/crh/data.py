"""Persistent, versioned historical-data cache for the CRH lab.

Layout (root = $PAPERBOT_CRH_CACHE or ./cache):
  bybit/kline_1h/{SYM}.parquet      1h OHLCV + turnover         (+ .coverage.json)
  bybit/kline_1m/{SYM}.parquet      1m OHLCV + turnover
  bybit/mark_1m/{SYM}.parquet       1m mark-price OHLC
  bybit/funding/{SYM}.parquet       settled funding (ts, rate)
  bybit/book_samples/{SYM}/{date}.json.gz   archived ob200 L2 sampled at cycle times
                                   (+ {date}.missing.json when the archive has no file)
  bybit/instruments/{date}.json, bybit/risk_limit/{SYM}.json
  coingecko/caps/{id}.parquet, coingecko/candidates_{date}.json

Coverage files record every [start, end) range that was verified against the
venue, so a range is never downloaded twice — including ranges the venue has
no bars for (pre-listing). Missing bars inside verified coverage are real.
Everything is PUBLIC data; nothing here is ever fabricated or interpolated.
"""
from __future__ import annotations
import gzip
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..replay import fetch as rest
from ..replay.orderbook import ARCHIVE, sample_day

DATA_VERSION = "bybit-v5-rest/1 ob200-sampler/1 coingecko-caps/1"
MIN_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
KLINE_COLS = ["ts", "open", "high", "low", "close", "volume", "turnover"]
MARK_COLS = ["ts", "open", "high", "low", "close"]
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cache_root() -> Path:
    return Path(os.environ.get("PAPERBOT_CRH_CACHE", "cache"))


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _read_parquet(path: Path, cols: list[str]) -> np.ndarray:
    if not path.exists():
        return np.zeros((0, len(cols)))
    t = pq.read_table(path)
    return np.column_stack([t.column(c).to_numpy().astype(np.float64) for c in cols])


def _write_parquet(path: Path, rows: np.ndarray, cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = [pa.array(rows[:, 0].astype(np.int64))] + [pa.array(rows[:, i]) for i in range(1, len(cols))]
    tmp = path.with_suffix(".tmp")
    pq.write_table(pa.table(arrays, names=cols), tmp)
    os.replace(tmp, path)


def _coverage_path(path: Path) -> Path:
    return path.with_suffix(".coverage.json")


def _coverage(path: Path) -> list[list[int]]:
    p = _coverage_path(path)
    return json.loads(p.read_text())["ranges"] if p.exists() else []


def _save_coverage(path: Path, ranges: list[list[int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged: list[list[int]] = []
    for a, b in sorted(ranges):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    _coverage_path(path).write_text(json.dumps({"version": DATA_VERSION, "ranges": merged}))


def missing_ranges(covered: list[list[int]], start: int, end: int) -> list[tuple[int, int]]:
    out, cur = [], start
    for a, b in sorted(covered):
        if b <= cur:
            continue
        if a > cur:
            out.append((cur, min(a, end)))
        cur = max(cur, b)
        if cur >= end:
            break
    if cur < end:
        out.append((cur, end))
    return [(a, b) for a, b in out if b > a]


def _merge_rows(old: np.ndarray, new: np.ndarray) -> np.ndarray:
    if len(old) == 0:
        rows = new
    elif len(new) == 0:
        rows = old
    else:
        rows = np.vstack([old, new])
    if len(rows) == 0:
        return rows
    # last write wins per ts, ascending
    order = np.argsort(rows[:, 0], kind="stable")
    rows = rows[order]
    _, idx = np.unique(rows[:, 0][::-1], return_index=True)
    keep = np.sort(len(rows) - 1 - idx)
    return rows[keep]


class Cache:
    def __init__(self, root: Path | None = None, offline: bool = False):
        self.root = root or cache_root()
        self.offline = offline
        self.events: list[str] = []

    # ------------------------------------------------------------ klines
    def _series(self, kind: str, sym: str, cols: list[str], start: int, end: int,
                step: int, fetch) -> np.ndarray:
        path = self.root / "bybit" / kind / f"{sym}.parquet"
        with _lock(str(path)):
            rows = _read_parquet(path, cols)
            cov = _coverage(path)
            gaps = missing_ranges(cov, start, end)
            if gaps and not self.offline:
                for a, b in gaps:
                    # one range per request; persisted immediately so an
                    # interrupted job resumes from the last completed range
                    fetched = [r + [0.0] * (len(cols) - len(r)) for r in fetch(a, b)]
                    if fetched:
                        rows = _merge_rows(rows, np.array(fetched, dtype=np.float64)[:, :len(cols)])
                        _write_parquet(path, rows, cols)
                    cov.append([a, b])
                    _save_coverage(path, cov)
                    self.events.append(f"{kind} {sym}: fetched [{a},{b})")
            sel = (rows[:, 0] >= start) & (rows[:, 0] < end) if len(rows) else np.zeros(0, bool)
            return rows[sel]

    def klines(self, sym: str, tf: str, start: int, end: int) -> np.ndarray:
        interval = {"1h": "60", "1m": "1"}[tf]
        step = HOUR_MS if tf == "1h" else MIN_MS
        return self._series(f"kline_{tf}", sym, KLINE_COLS, start, end, step,
                            lambda a, b: rest.klines(sym, interval, a, b))

    def mark_1m(self, sym: str, start: int, end: int) -> np.ndarray:
        return self._series("mark_1m", sym, MARK_COLS, start, end, MIN_MS,
                            lambda a, b: rest.klines(sym, "1", a, b, "mark-price-kline"))

    def funding(self, sym: str, start: int, end: int) -> list[tuple[int, float]]:
        rows = self._series("funding", sym, ["ts", "rate"], start, end, 8 * HOUR_MS,
                            lambda a, b: [[f["ts"], f["rate"]] for f in rest.funding_history(sym, a, b)])
        return [(int(r[0]), float(r[1])) for r in rows]

    def coverage_summary(self, sym: str, tf: str) -> list[list[int]]:
        return _coverage(self.root / "bybit" / f"kline_{tf}" / f"{sym}.parquet")

    # ------------------------------------------------------------- books
    def book_day_path(self, sym: str, date: str) -> Path:
        return self.root / "bybit" / "book_samples" / sym / f"{date}.json.gz"

    def ensure_book_day(self, sym: str, date: str, progress=None) -> dict | None:
        """Sampled archived L2 for one symbol-day: cached, else downloaded
        (zip deleted after sampling), else recorded as missing. Returns the
        sample meta, or None when the archive has no such file."""
        path = self.book_day_path(sym, date)
        missing = path.parent / f"{date}.missing.json"
        with _lock(str(path)):
            if path.exists():
                return json.loads(gzip.decompress(path.read_bytes()))["meta"]
            if missing.exists():
                return None
            if self.offline:
                return None
            import datetime as dt
            import subprocess
            day_start = int(dt.datetime.strptime(date, "%Y-%m-%d").replace(
                tzinfo=dt.timezone.utc).timestamp() * 1000)
            url = f"{ARCHIVE}/{sym}/{date}_{sym}_ob200.data.zip"
            tmp = self.root / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            z = tmp / f"{date}_{sym}_ob200.data.zip"
            if progress:
                progress(f"downloading L2 {sym} {date}")
            code = ""
            for _ in range(4):
                code = subprocess.run(["curl", "-s", "-m", "1800", "-w", "%{http_code}", "-o",
                                       str(z), url], capture_output=True, text=True).stdout.strip()
                if code in ("200", "404"):
                    break
                time.sleep(5)
            if code != "200":
                z.unlink(missing_ok=True)
                path.parent.mkdir(parents=True, exist_ok=True)
                missing.write_text(json.dumps({"url": url, "http": code,
                                               "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                            time.gmtime())}))
                self.events.append(f"L2 {sym} {date}: archive unavailable ({code})")
                return None
            if progress:
                progress(f"sampling L2 {sym} {date}")
            try:
                result = sample_day(z, day_start)
            finally:
                z.unlink(missing_ok=True)
            result["meta"]["url"] = url
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps(result, separators=(",", ":")).encode()))
            self.events.append(f"L2 {sym} {date}: downloaded + sampled")
            return result["meta"]

    def load_book_day(self, sym: str, date: str) -> dict[int, tuple[float, float, int]] | None:
        path = self.book_day_path(sym, date)
        if not path.exists():
            return None
        out = {}
        for s in json.loads(gzip.decompress(path.read_bytes()))["samples"]:
            if s[1] is not None and s[2] and s[3]:
                out[s[0]] = (float(s[2][0][0]), float(s[3][0][0]), int(s[1]))
        return out

    # --------------------------------------------------------- metadata
    def instruments_info(self, max_age_s: int = 6 * 3600) -> list[dict]:
        p = self.root / "bybit" / "instruments" / "latest.json"
        if p.exists() and time.time() - p.stat().st_mtime < max_age_s:
            return json.loads(p.read_text())["rows"]
        if self.offline and p.exists():
            return json.loads(p.read_text())["rows"]
        import requests
        rows, cursor = [], ""
        while True:
            r = requests.get(f"{rest.BASE}/instruments-info",
                             params={"category": "linear", "limit": 1000, "cursor": cursor},
                             timeout=30).json()
            rows += r["result"]["list"]
            cursor = r["result"].get("nextPageCursor") or ""
            if not cursor:
                break
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "rows": rows}))
        return rows

    def risk_tier1(self, sym: str) -> dict:
        p = self.root / "bybit" / "risk_limit" / f"{sym}.json"
        if p.exists():
            return json.loads(p.read_text())
        if self.offline:
            return {}
        row = rest.risk_tier1(sym)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(row))
        return row

    # ------------------------------------------------------------- bulk
    def prefetch(self, syms: list[str], t0: int, t1: int, warmup_ms: int, progress=None,
                 cancelled=None, workers: int = 6, mark: bool = False) -> None:
        """Concurrent, rate-limited fills of 1h (warm-up), 1m and funding."""
        done = [0]
        total = len(syms)

        def one(sym):
            if cancelled and cancelled():
                return
            self.klines(sym, "1h", t0 - warmup_ms, t1)
            self.klines(sym, "1m", t0 - HOUR_MS, t1)
            self.funding(sym, t0 - 7 * DAY_MS, t1)
            if mark:
                self.mark_1m(sym, t0 - HOUR_MS, t1)
            done[0] += 1
            if progress:
                progress("candles", done[0] / total, sym)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, syms))

    # --------------------------------------------------------------- seed
    def seed_from_research(self, research_root: Path = Path("research")) -> dict:
        """Import the JSON datasets + book samples the earlier replays saved
        (same sources, same sampler) so nothing already on disk is refetched."""
        stats = {"kline": 0, "mark": 0, "funding": 0, "books": 0}
        for data_dir in sorted(research_root.glob("*/data")):
            for kind, cols, key in (("kline_1h", KLINE_COLS, "kline_1h"), ("kline_1m", KLINE_COLS, "kline_1m"),
                                    ("mark_1m", MARK_COLS, "mark_1m"), ("funding", ["ts", "rate"], "funding")):
                for f in sorted((data_dir / kind).glob("*.json")):
                    d = json.loads(f.read_text())
                    meta, rows = d["meta"], d["rows"]
                    path = self.root / "bybit" / key / f"{f.stem}.parquet"
                    with _lock(str(path)):
                        old = _read_parquet(path, cols)
                        if kind == "funding":
                            new = np.array([[r["ts"], r["rate"]] for r in rows], dtype=np.float64) \
                                if rows else np.zeros((0, 2))
                        else:
                            new = np.array([list(r) + [0.0] * (len(cols) - len(r)) for r in rows],
                                           dtype=np.float64)[:, :len(cols)] if rows else np.zeros((0, len(cols)))
                        cov = _coverage(path)
                        cov.append([int(meta["start_ms"]), int(meta["end_ms_exclusive"])])
                        _write_parquet(path, _merge_rows(old, new), cols)
                        _save_coverage(path, cov)
                    stats["kline" if kind.startswith("kline") else "mark" if kind == "mark_1m" else "funding"] += 1
            for f in sorted((data_dir / "book_samples").glob("*/*.json.gz")):
                dst = self.book_day_path(f.parent.name, f.stem.replace(".json", ""))
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(f.read_bytes())
                    stats["books"] += 1
        return stats


class BookQuotes:
    """Lazy per-day quote lookup for one symbol; downloads day-files on demand
    (smart L2 loading). Records which days were unavailable."""
    def __init__(self, cache: Cache, sym: str, progress=None, on_demand: bool = True):
        self.cache, self.sym, self.progress, self.on_demand = cache, sym, progress, on_demand
        self.days: dict[str, dict | None] = {}
        self.missing_days: list[str] = []

    def __call__(self, t: int):
        import datetime as dt
        date = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        if date not in self.days:
            if self.on_demand:
                self.cache.ensure_book_day(self.sym, date, self.progress)
            d = self.cache.load_book_day(self.sym, date)
            self.days[date] = d
            if d is None:
                self.missing_days.append(date)
        d = self.days[date]
        return None if d is None else d.get(t)
