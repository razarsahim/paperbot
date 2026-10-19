"""Cache: coverage bookkeeping, incremental fetch, offline behaviour,
book-day on-demand loading and cached-vs-uncached equivalence."""
import gzip
import json

import numpy as np
import pytest

from paperbot_pro.crh import data as D
from paperbot_pro.crh.data import BookQuotes, Cache, missing_ranges

H, M = 3_600_000, 60_000


def test_missing_ranges_math():
    assert missing_ranges([], 0, 10) == [(0, 10)]
    assert missing_ranges([[0, 10]], 0, 10) == []
    assert missing_ranges([[2, 4], [6, 8]], 0, 10) == [(0, 2), (4, 6), (8, 10)]
    assert missing_ranges([[0, 5]], 3, 10) == [(5, 10)]
    assert missing_ranges([[0, 20]], 3, 10) == []


def test_klines_fetch_only_missing_ranges_and_persist(tmp_path, monkeypatch):
    calls = []

    def fake(sym, interval, a, b, kind="kline"):
        calls.append((a, b))
        return [[t, 1.0, 2.0, 0.5, 1.5, 10.0, 15.0] for t in range(a, b, H)]
    monkeypatch.setattr(D.rest, "klines", fake)
    c = Cache(tmp_path)
    rows = c.klines("XUSDT", "1h", 0, 10 * H)
    assert len(rows) == 10 and calls == [(0, 10 * H)]
    rows = c.klines("XUSDT", "1h", 5 * H, 15 * H)         # only [10h, 15h) is new
    assert len(rows) == 10 and calls[-1] == (10 * H, 15 * H)
    c2 = Cache(tmp_path)                                    # fresh process, same disk
    assert len(c2.klines("XUSDT", "1h", 0, 15 * H)) == 15 and len(calls) == 2
    # offline: never fetches, serves what exists
    off = Cache(tmp_path, offline=True)
    assert len(off.klines("XUSDT", "1h", 0, 30 * H)) == 15 and len(calls) == 2


def test_verified_empty_ranges_are_not_refetched(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(D.rest, "klines", lambda *a, **k: (calls.append(a), [])[1])
    c = Cache(tmp_path)
    assert len(c.klines("NEWUSDT", "1h", 0, 5 * H)) == 0
    assert len(c.klines("NEWUSDT", "1h", 0, 5 * H)) == 0
    assert len(calls) == 1                                   # pre-listing range verified once


def test_book_day_cached_missing_and_quotes(tmp_path):
    c = Cache(tmp_path, offline=True)
    sym, date = "XUSDT", "1970-01-02"
    assert c.ensure_book_day(sym, date) is None             # offline, nothing cached
    p = c.book_day_path(sym, date)
    p.parent.mkdir(parents=True)
    t = 86_400_000 + 5_000
    p.write_bytes(gzip.compress(json.dumps({"meta": {"messages": 1}, "samples": [
        [t, t - 50, [[9.9, 1.0]], [[10.1, 1.0]]], [t + M, None, [], []]]}).encode()))
    q = BookQuotes(c, sym, on_demand=False)
    assert q(t) == (9.9, 10.1, t - 50) and q(t + M) is None
    assert q(t + 2 * 86_400_000) is None and q.missing_days == ["1970-01-04"]


def test_seed_from_research_imports_json_and_books(tmp_path):
    root = tmp_path / "research" / "x" / "data"
    (root / "kline_1h").mkdir(parents=True)
    (root / "kline_1h" / "ZUSDT.json").write_text(json.dumps(
        {"meta": {"start_ms": 0, "end_ms_exclusive": 3 * H},
         "rows": [[0, 1, 2, 0.5, 1.5, 1, 1], [H, 1, 2, 0.5, 1.5, 1, 1]]}))
    (root / "book_samples" / "ZUSDT").mkdir(parents=True)
    (root / "book_samples" / "ZUSDT" / "1970-01-01.json.gz").write_bytes(gzip.compress(b'{"meta":{},"samples":[]}'))
    c = Cache(tmp_path / "cache", offline=True)
    st = c.seed_from_research(tmp_path / "research")
    assert st == {"kline": 1, "mark": 0, "funding": 0, "books": 1}
    assert len(c.klines("ZUSDT", "1h", 0, 3 * H)) == 2
    assert c.coverage_summary("ZUSDT", "1h") == [[0, 3 * H]]
    assert c.book_day_path("ZUSDT", "1970-01-01").exists()


def test_interrupted_fetch_resumes_from_last_completed_range(tmp_path, monkeypatch):
    calls = []

    def flaky(sym, interval, a, b, kind="kline"):
        calls.append((a, b))
        if len(calls) == 2:
            raise ConnectionError("network dropped")
        return [[t, 1, 2, 0.5, 1.5, 1, 1] for t in range(a, b, H)]
    monkeypatch.setattr(D.rest, "klines", flaky)
    Cache(tmp_path).klines("XUSDT", "1h", 0, 5 * H)              # call 1: [0,5h) verified
    with pytest.raises(ConnectionError):
        Cache(tmp_path).klines("XUSDT", "1h", 0, 15 * H)         # call 2: [5h,15h) fails mid-job
    assert Cache(tmp_path).coverage_summary("XUSDT", "1h") == [[0, 5 * H]]
    rows = Cache(tmp_path).klines("XUSDT", "1h", 0, 15 * H)      # call 3 resumes the gap only
    assert len(rows) == 15 and calls[-1] == (5 * H, 15 * H)
