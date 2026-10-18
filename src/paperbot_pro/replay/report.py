"""Aggregate replay runs into the comparison report + dashboard payload.

Everything here is labelled HISTORICAL BACKTEST. Independent sleeve results
(A) and the combined shared-portfolio result (B) are kept in separate
sections and never summed into each other.
"""
from __future__ import annotations
import gzip
import json
import math
from pathlib import Path

from ..lab.config import STRATEGIES
from .extract import SMALL_SAMPLE

HOUR_MS = 3_600_000
MIN_MS = 60_000

# Replay fidelity per strategy, from the code audit + data audit. Stated, not tuned.
FIDELITY = {
    "breakout": ("HIGH", "Pure 1h-candle logic; real Bybit 1h/1m OHLCV and archived bid/ask."),
    "launch_sniper": ("NOT TESTABLE", "Code treats a market as 'young' only when <200 1h bars "
                      "exist AND >=60 closed bars are needed to evaluate; no top-20 universe "
                      "member qualified, and the only crypto perps listed in range (DRVUSDT, "
                      "DNAUSDT, both 2026-10-16) never reached 60 closed bars before the window "
                      "ended. Zero eligible decision points."),
    "squeeze": ("LIMITED (proxy)", "Code uses wick size + funding rate as a squeeze PROXY; it "
                "never reads liquidation data. Replay feeds the last SETTLED funding rate (the "
                "live engine reads the predicted next rate, which is not archived). No "
                "historical liquidation feed was used or is required by the code."),
    "trend": ("HIGH", "Pure 1h-candle logic (scanner.generate_signal)."),
    "crash_reversal": ("HIGH", "Pure 1h-candle logic."),
    "regime_trend": ("MEDIUM (as deployed)", "Needs a 4h trend context; the deployed MarketData "
                     "has no htf_trend() hook, so the engine defaults it to 'up'. Replayed "
                     "exactly as deployed => effectively LONG-ONLY with no real 4h filter."),
    "volatility_breakout": ("HIGH", "Pure 1h-candle logic."),
    "trend_pullback": ("MEDIUM (as deployed)", "Needs a 1h HTF trend context that the deployed "
                       "MarketData never supplies (defaults 'up') => LONG-ONLY as deployed."),
    "range_reversion": ("HIGH", "Pure 1h-candle logic. Note: the described 'exit to "
                        "midpoint/VWAP' is NOT implemented; exits are the shared ATR trail."),
    "orderflow_imbalance": ("MEDIUM (archived L2)", "Real Bybit ob200 L2 archive replayed "
                            "message-by-message, sampled at each 60s cycle (top-10 levels, "
                            "true age/spread). Code uses depth imbalance only (no trade-flow "
                            "term despite its description). The DEPLOYED engine has no "
                            "orderbook() hook, so live it never trades; this replay wires the "
                            "archive in to test the logic itself."),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return f"{v:,.{nd}f}"


def rank_rows(rows: list[dict]) -> dict:
    by_net = sorted(rows, key=lambda r: r["net_return_pct"], reverse=True)

    def risk_key(r):
        # risk-adjusted: return per unit of max drawdown; zero-trade sleeves
        # (no risk taken) rank between profitable and losing ones
        if r["completed_trades"] == 0 and r["open_positions_at_end"] == 0:
            return 0.0
        dd = r["max_drawdown_pct"] or 0.0
        return r["net_return_pct"] / max(dd, 0.5)
    by_risk = sorted(rows, key=risk_key, reverse=True)
    by_dd = sorted(rows, key=lambda r: r["max_drawdown_pct"])
    return {"by_net_return": [r["key"] for r in by_net],
            "by_return_over_drawdown": [r["key"] for r in by_risk],
            "by_lowest_drawdown": [r["key"] for r in by_dd],
            "risk_metric": "net_return_pct / max(max_drawdown_pct, 0.5)"}


def mark_liquidation_check(trades: list[dict], data_dir: Path, liq_by_trade: dict) -> list[dict]:
    """For every trade, would Bybit's MARK price (what the exchange liquidates on)
    have crossed the simulated liquidation estimate while the trade was open?"""
    cache: dict[str, dict] = {}
    out = []
    for t in trades:
        sym = t["symbol"].split("/")[0] + "USDT"
        if sym not in cache:
            rows = json.loads((data_dir / "mark_1m" / f"{sym}.json").read_text())["rows"]
            cache[sym] = {r[0]: r for r in rows}
        liq = liq_by_trade.get(t["id"])
        if liq is None:
            continue
        start = t["entry_ms"] - t["entry_ms"] % MIN_MS
        crossed = False
        m = start
        while m < t["exit_ms"]:
            r = cache[sym].get(m)
            if r is not None and ((t["side"] == "long" and r[3] <= liq) or
                                  (t["side"] == "short" and r[2] >= liq)):
                crossed = True
                break
            m += MIN_MS
        out.append({"trade_id": t["id"], "strategy": t["strategy"], "symbol": t["symbol"],
                    "exit_reason": t["exit_reason"], "mark_crossed_liq": crossed})
    return out


def data_quality(data_dir: Path, book_dir: Path, symbols: list[str], t0: int, t1: int) -> dict:
    out = {}
    for sym in symbols:
        k1h = json.loads((data_dir / "kline_1h" / f"{sym}.json").read_text())["rows"]
        k1m = json.loads((data_dir / "kline_1m" / f"{sym}.json").read_text())["rows"]
        mk = json.loads((data_dir / "mark_1m" / f"{sym}.json").read_text())["rows"]
        fu = json.loads((data_dir / "funding" / f"{sym}.json").read_text())["rows"]
        oi = json.loads((data_dir / "open_interest_1h" / f"{sym}.json").read_text())["rows"]
        by_m = {r[0]: r for r in k1m}
        mism = 0
        for r in k1h:
            if t0 <= r[0] < t1:
                mins = [by_m.get(r[0] + i * MIN_MS) for i in range(60)]
                if any(x is None for x in mins):
                    mism += 1
                    continue
                agg = (mins[0][1], max(x[2] for x in mins), min(x[3] for x in mins), mins[-1][4])
                if any(abs(a - b) > 1e-9 * max(1.0, abs(b)) for a, b in zip(agg, r[1:5])):
                    mism += 1
        def gaps(ts, step, lo, hi):
            have = set(ts)
            return sum(1 for x in range(lo, hi, step) if x not in have)
        books = []
        for f in sorted((book_dir / sym).glob("*.json.gz")) if (book_dir / sym).exists() else []:
            books.append(json.loads(gzip.decompress(f.read_bytes()))["meta"])
        days = len(books)
        stale_samples = 0
        if (book_dir / sym).exists():
            for f in sorted((book_dir / sym).glob("*.json.gz")):
                for s in json.loads(gzip.decompress(f.read_bytes()))["samples"]:
                    if s[1] is None or s[0] - s[1] > 15_000:
                        stale_samples += 1
        out[sym] = {
            "kline_1h_rows": len(k1h), "kline_1h_missing": gaps([r[0] for r in k1h], HOUR_MS,
                                                                   k1h[0][0], t1),
            "kline_1m_missing_in_window": gaps([r[0] for r in k1m], MIN_MS, t0, t1),
            "mark_1m_missing_in_window": gaps([r[0] for r in mk], MIN_MS, t0, t1),
            "hourly_vs_1m_aggregate_mismatches": mism,
            "zero_volume_1m_bars": sum(1 for r in k1m if t0 <= r[0] < t1 and r[5] == 0),
            "funding_prints_in_window": sum(1 for f in fu if t0 <= f["ts"] < t1),
            "funding_off_8h_grid": sum(1 for f in fu if f["ts"] % (8 * HOUR_MS)),
            "open_interest_rows": len(oi),
            "book_days": days,
            "book_messages": sum(b["messages"] for b in books),
            "book_max_gap_ms": max((b["max_gap_ms"] for b in books), default=None),
            "book_gaps_over_15s": sum(b["gaps_over_15s"] for b in books),
            "book_crossed_samples": sum(b["crossed_samples"] for b in books),
            "book_samples_stale_or_missing": stale_samples,
            "book_source_sha256": {b["source_file"]: b["source_sha256"] for b in books},
            "warmup_start_ms": k1h[0][0],
        }
    return out


def build(runs_dir: Path, data_dir: Path, book_dir: Path, out_json: Path,
          validation_report: Path | None, t0: int, t1: int) -> dict:
    a_runs = {k.key: _load(runs_dir / f"A_{k.key}.json") for k in STRATEGIES
              if (runs_dir / f"A_{k.key}.json").exists()}
    b = _load(runs_dir / "B_combined.json")
    b_dep = _load(runs_dir / "B_deployed.json") if (runs_dir / "B_deployed.json").exists() else None
    rows = []
    for s in STRATEGIES:
        r = a_runs.get(s.key)
        if r is None:
            continue
        m = dict(r["totals"])
        ps = r["per_strategy"][s.key]
        rows.append({**m, "key": s.key, "name": s.name, "cohort": s.cohort,
                     "risk_budget_usd": s.risk_budget_usd,
                     "fidelity": FIDELITY[s.key][0], "fidelity_note": FIDELITY[s.key][1],
                     "signals_fired": ps["signals_fired"],
                     "signals_approved": ps["signals_approved"],
                     "rejections": ps["rejections"], "locked": ps["locked"],
                     "lock_reason": ps["lock_reason"],
                     "risk_events": r["risk_events"],
                     "equity_curve_hourly": r["equity_curve_hourly"],
                     "trades": r["trades"], "open_at_end": r["open_at_end"],
                     "leakage_ok": r["leakage_check"]["ok"],
                     "identity_gap": r["accounting_identity_gap_usd"]})
    ranks = rank_rows(rows)
    symbols = [s.split("/")[0] + "USDT" for s in b["instruments"]]
    dq = data_quality(data_dir, book_dir, symbols, t0, t1)
    # liquidation estimates are in the run DBs (positions are deleted on close,
    # so recover them from the signal-time plan via trades' stop + leverage)
    candles = {}
    for sym in symbols:
        k1h = json.loads((data_dir / "kline_1h" / f"{sym}.json").read_text())["rows"]
        candles[sym] = [r[:6] for r in k1h if t0 - 48 * HOUR_MS <= r[0] < t1]
    # mark-price liquidation cross-check (exchange liquidates on MARK price)
    from ..perp import liquidation_price
    tiers = json.loads((data_dir / "manifest_rest.json").read_text())["risk_tier1"]
    def liq_map(trades):
        return {t["id"]: liquidation_price(
            t["side"], t["entry_price"], 10.0,
            float(tiers[t["symbol"].split("/")[0] + "USDT"]["maintenanceMargin"]))
            for t in trades}
    mark_checks = {}
    for name, trades in [("B_combined", b["trades"])] + \
            [(f"A_{r['key']}", r["trades"]) for r in rows]:
        res = mark_liquidation_check(trades, data_dir, liq_map(trades))
        mark_checks[name] = {
            "trades": len(res),
            "sim_liquidations": sum(1 for x in res if x["exit_reason"] == "LIQUIDATION"),
            "mark_crossed_liq": sum(1 for x in res if x["mark_crossed_liq"]),
            "mismatch": [x for x in res if (x["exit_reason"] == "LIQUIDATION") != x["mark_crossed_liq"]],
        }
    evidence = None
    if validation_report and validation_report.exists():
        v = json.loads(validation_report.read_text())
        evidence = {"source": str(validation_report), "generated_at_utc": v["generated_at_utc"],
                    "outcome": v["outcome"], "summary": v["summary"],
                    "strategy": "main-engine trend logic (same generate_signal as Trend Rider)",
                    "markets": [{"symbol": m["symbol"], "trades": m["trades"],
                                 "net_return_pct": m["net_return_pct"],
                                 "profit_factor": m["profit_factor"],
                                 "win_rate_pct": m["win_rate_pct"]} for m in v["markets"]]}
    payload = {
        "label": "HISTORICAL BACKTEST — not live paper; simulated, not predictive",
        "window_utc": {"start": "2026-10-11T00:00:00Z", "end_exclusive": "2026-10-18T00:00:00Z",
                       "start_ms": t0, "end_ms": t1},
        "small_sample_threshold": SMALL_SAMPLE,
        "independent": rows,
        "rankings": ranks,
        "combined": b, "combined_deployed": b_dep,
        "data_quality": dq,
        "mark_liquidation_check": mark_checks,
        "candles_1h": candles,
        "prior_evidence": evidence,
        "exit_rules": {
            "implemented": "Fixed initial stop = entry fill -/+ 2.0 x ATR(14,1h); ATR trailing "
                           "stop (2.5 x ATR) ratcheted on each completed 1h candle, never "
                           "widened; no fixed take-profit; full-position exit only; "
                           "liquidation if the isolated estimate is reached first.",
            "hybrid_50pct_at_2R": "NOT IMPLEMENTED (docs/PENDING-FEATURES.md). No partial exits "
                                  "occurred in this replay. Proposed as a separate experiment.",
        },
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, separators=(",", ":"), default=str))
    return payload


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="research/replay_2026-10-11/runs")
    ap.add_argument("--data", default="research/replay_2026-10-11/data")
    ap.add_argument("--books", default="research/replay_2026-10-11/data/book_samples")
    ap.add_argument("--out", default="web/public/replay/replay-2026-10-11.json")
    ap.add_argument("--validation", default="state/validation_report.json")
    ap.add_argument("--t0", type=int, default=1791676800000)
    ap.add_argument("--t1", type=int, default=1792281600000)
    a = ap.parse_args(argv)
    p = build(Path(a.runs), Path(a.data), Path(a.books), Path(a.out),
              Path(a.validation), a.t0, a.t1)
    print(f"wrote {a.out}: {len(p['independent'])} independent sleeves")


if __name__ == "__main__":
    main()
