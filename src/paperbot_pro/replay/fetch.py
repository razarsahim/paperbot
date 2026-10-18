"""Download reproducible PUBLIC Bybit v5 market-data snapshots for a replay.

Read-only public endpoints only (no keys, no private routes). Every file is
saved with its request parameters, fetch time and a SHA-256 so a dataset can
be identified and re-verified. Nothing is gap-filled or fabricated: whatever
the venue returns is stored, and completeness is checked separately.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

import requests

BASE = "https://api.bybit.com/v5/market"
MIN_MS = 60_000
HOUR_MS = 3_600_000


def _get(path: str, params: dict, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/{path}", params=params, timeout=30)
            body = r.json()
            if body.get("retCode") == 0:
                return body["result"]
            if body.get("retCode") == 10006:  # rate limit
                time.sleep(2 + attempt * 2)
                continue
            raise RuntimeError(f"{path} {params}: {body.get('retCode')} {body.get('retMsg')}")
        except (requests.RequestException, ValueError):
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"{path} {params}: retries exhausted")


def klines(symbol: str, interval: str, start_ms: int, end_ms: int,
           kind: str = "kline") -> list[list]:
    """[start, end) kline rows ascending, deduped. kind: 'kline' (trade
    price OHLCV+turnover) or 'mark-price-kline' (mark OHLC)."""
    step = int(interval) * MIN_MS
    seen: dict[int, list] = {}
    cursor = start_ms
    while cursor < end_ms:
        batch_end = min(end_ms - 1, cursor + 1000 * step - 1)
        res = _get(kind, {"category": "linear", "symbol": symbol, "interval": interval,
                          "start": cursor, "end": batch_end, "limit": 1000})
        rows = res.get("list") or []
        for row in rows:
            ts = int(row[0])
            if start_ms <= ts < end_ms:
                seen[ts] = [ts] + [float(x) for x in row[1:]]
        cursor = batch_end + 1
    return [seen[t] for t in sorted(seen)]


def funding_history(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    out: dict[int, float] = {}
    end = end_ms - 1
    while True:
        res = _get("funding/history", {"category": "linear", "symbol": symbol,
                                       "startTime": start_ms, "endTime": end, "limit": 200})
        rows = res.get("list") or []
        for r in rows:
            out[int(r["fundingRateTimestamp"])] = float(r["fundingRate"])
        if len(rows) < 200:
            break
        end = min(int(r["fundingRateTimestamp"]) for r in rows) - 1
        if end < start_ms:
            break
    return [{"ts": t, "rate": out[t]} for t in sorted(out)]


def open_interest(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    out: dict[int, float] = {}
    cursor = ""
    for _ in range(100):
        params = {"category": "linear", "symbol": symbol, "intervalTime": "1h",
                  "startTime": start_ms, "endTime": end_ms - 1, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        res = _get("open-interest", params)
        for r in res.get("list") or []:
            out[int(r["timestamp"])] = float(r["openInterest"])
        cursor = res.get("nextPageCursor") or ""
        if not cursor or not res.get("list"):
            break
    return [{"ts": t, "oi": out[t]} for t in sorted(out)]


def risk_tier1(symbol: str) -> dict:
    res = _get("risk-limit", {"category": "linear", "symbol": symbol})
    rows = [r for r in res.get("list") or [] if r.get("symbol") == symbol]
    rows.sort(key=lambda r: float(r["riskLimitValue"]))
    return rows[0] if rows else {}


def _save(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(raw)
    return {"file": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def fetch_symbol(symbol: str, out_dir: Path, t0: int, t1: int, warmup_days: int) -> list[dict]:
    """Fetch every dataset for one symbol; returns manifest entries."""
    fetched = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    w0 = t0 - warmup_days * 86_400_000
    jobs = {
        "kline_1h": (lambda: klines(symbol, "60", w0, t1), w0),
        "kline_1m": (lambda: klines(symbol, "1", t0 - HOUR_MS, t1), t0 - HOUR_MS),
        "mark_1m": (lambda: klines(symbol, "1", t0 - HOUR_MS, t1, "mark-price-kline"),
                    t0 - HOUR_MS),
        "funding": (lambda: funding_history(symbol, w0, t1), w0),
        "open_interest_1h": (lambda: open_interest(symbol, w0, t1), w0),
    }
    entries = []
    for name, (fn, start) in jobs.items():
        rows = fn()
        meta = {"dataset": name, "symbol": symbol, "source": f"{BASE} (public, no auth)",
                "start_ms": start, "end_ms_exclusive": t1, "fetched_utc": fetched,
                "rows": len(rows)}
        entry = _save(out_dir / name / f"{symbol}.json", {"meta": meta, "rows": rows})
        entries.append({**meta, **entry})
    return entries


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Fetch public Bybit replay datasets")
    ap.add_argument("--out", required=True)
    ap.add_argument("--t0", type=int, required=True)
    ap.add_argument("--t1", type=int, required=True)
    ap.add_argument("--warmup-days", type=int, default=90)
    ap.add_argument("symbols", nargs="+")
    a = ap.parse_args(argv)
    out = Path(a.out)
    manifest_path = out / "manifest_rest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"datasets": []}
    tiers = manifest.get("risk_tier1", {})
    for sym in a.symbols:
        manifest["datasets"] = [d for d in manifest["datasets"] if d["symbol"] != sym]
        manifest["datasets"] += fetch_symbol(sym, out, a.t0, a.t1, a.warmup_days)
        tiers[sym] = risk_tier1(sym)
        print(f"fetched {sym}", flush=True)
    manifest["risk_tier1"] = tiers
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
