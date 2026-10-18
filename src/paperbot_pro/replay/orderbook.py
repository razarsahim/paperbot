"""Reconstruct point-in-time order books from Bybit's PUBLIC archived L2 feed.

Source: Bybit historical market data (quote-saver.bycsi.com, "ob200" linear
files): the recorded public WebSocket orderbook.200 stream, one snapshot then
deltas, with exchange timestamps. We replay every message in order and sample
the book at each simulated engine cycle time, keeping only what a live engine
could have seen at that instant (state after messages with ts <= sample).
No book is ever synthesised from candles.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path

try:
    import orjson
    _loads = orjson.loads
except ImportError:  # pragma: no cover
    _loads = json.loads

DAY_MS = 86_400_000
TOP_N = 10


def _apply(book: dict, levels) -> None:
    for p, q in levels:
        if q == "0" or float(q) == 0.0:
            book.pop(p, None)
        else:
            book[p] = q


def _top(book: dict, reverse: bool) -> list[list[float]]:
    prices = sorted(book, key=float, reverse=reverse)[:TOP_N]
    return [[float(p), float(book[p])] for p in prices]


def sample_day(zip_path: Path, day_start_ms: int, cycle_offset_ms: int = 5_000,
               cycle_ms: int = 60_000) -> dict:
    """Return {'meta': stats, 'samples': [[t, last_msg_ts, bids10, asks10], ...]}.
    A sample is None-booked ([t, None, [], []]) until the first snapshot."""
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    bids: dict[str, str] = {}
    asks: dict[str, str] = {}
    samples = []
    next_t = day_start_ms + cycle_offset_ms
    end_t = day_start_ms + DAY_MS
    last_ts = None
    have_book = False
    n_msgs = n_snap = 0
    max_gap = 0
    gaps_over_15s = 0
    crossed = 0
    first_ts = None

    def emit_until(ts_limit):
        nonlocal next_t, crossed
        while next_t < end_t and next_t < ts_limit:
            if have_book:
                b, a = _top(bids, True), _top(asks, False)
                if b and a and b[0][0] >= a[0][0]:
                    crossed += 1
                samples.append([next_t, last_ts, b, a])
            else:
                samples.append([next_t, None, [], []])
            next_t += cycle_ms

    with zipfile.ZipFile(zip_path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            for line in io.TextIOWrapper(fh, encoding="utf-8"):
                if not line.strip():
                    continue
                msg = _loads(line)
                ts = int(msg["ts"])
                # emit samples strictly before this message's timestamp
                # (state as of messages with ts <= sample time)
                emit_until(ts)
                data = msg["data"]
                if msg.get("type") == "snapshot":
                    bids, asks = {}, {}
                    n_snap += 1
                    have_book = True
                _apply(bids, data.get("b") or [])
                _apply(asks, data.get("a") or [])
                if last_ts is not None:
                    gap = ts - last_ts
                    max_gap = max(max_gap, gap)
                    if gap > 15_000:
                        gaps_over_15s += 1
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
                n_msgs += 1
    emit_until(end_t)
    meta = {"source_file": zip_path.name, "source_sha256": sha,
            "messages": n_msgs, "snapshots": n_snap, "first_ts": first_ts,
            "last_ts": last_ts, "max_gap_ms": max_gap, "gaps_over_15s": gaps_over_15s,
            "crossed_samples": crossed, "samples": len(samples)}
    return {"meta": meta, "samples": samples}


def _work(args):
    zip_path, day_start, out_path = args
    out = Path(out_path)
    if out.exists():
        return json.loads(gzip.decompress(out.read_bytes()))["meta"]
    result = sample_day(Path(zip_path), day_start)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(json.dumps(result, separators=(",", ":")).encode()))
    return result["meta"]


def main(argv: list[str] | None = None) -> None:
    import argparse
    import datetime as dt
    from multiprocessing import Pool
    ap = argparse.ArgumentParser(description="Sample archived ob200 books at cycle times")
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args(argv)
    jobs = []
    for z in sorted(Path(a.raw).glob("*_ob200.data.zip")):
        day, sym = z.name.split("_")[0], z.name.split("_")[1]
        start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(
            tzinfo=dt.timezone.utc).timestamp() * 1000)
        jobs.append((str(z), start, str(Path(a.out) / sym / f"{day}.json.gz")))
    with Pool(a.procs) as pool:
        metas = pool.map(_work, jobs, chunksize=1)
    manifest = {"source": "https://quote-saver.bycsi.com/orderbook/linear/ (Bybit public "
                          "historical orderbook.200 archive)",
                "cycle_offset_ms": 5000, "cycle_ms": 60000, "top_levels": TOP_N,
                "files": metas}
    Path(a.out, "manifest_books.json").write_text(json.dumps(manifest, indent=1))
    print(f"processed {len(metas)} files")


if __name__ == "__main__":
    main()
