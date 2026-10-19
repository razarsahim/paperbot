"""CRH backtest pipeline: universe -> candles -> prescan -> (smart L2) ->
replay -> report, with progress, cancellation and result reuse.

Every result is a self-describing JSON document labelled HISTORICAL
BACKTEST that records the exact window, universe + eligible instruments,
configuration, data sources/fidelity/coverage, trade journal, equity curve,
daily P&L, costs, risk events, signal explanations, warnings and the
accounting / look-ahead checks. Nothing here touches the live engines.
"""
from __future__ import annotations
import datetime as dt
import gzip
import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np

from ..perp import ContractSpec, liquidation_price
from ..replay.extract import metrics
from .config import CRHConfig, scaled_baseline
from .data import DATA_VERSION, DAY_MS, HOUR_MS, MIN_MS, BookQuotes, Cache
from .engine import CRHReplay, FrameProvider, SymbolFrame, near_misses, prescan
from .universe import SURVIVORSHIP_NOTE, UniverseBuilder, days_between

DEFAULT_WARMUP_MS = 10 * DAY_MS          # >= candle_limit (200) hourly bars + slack
PRESET_HOURS = {"24h": 24, "48h": 48, "7d": 168, "30d": 720, "90d": 2160}


def utc_iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_window(params: dict) -> tuple[int, int]:
    """UTC window [t0, t1). Presets end at the last completed UTC hour."""
    if params.get("start") and params.get("end"):
        p = lambda s: int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
        t0, t1 = p(params["start"]), p(params["end"])
    else:
        hours = PRESET_HOURS[params.get("preset", "48h")]
        now = int(time.time() * 1000)
        t1 = now - now % HOUR_MS
        t0 = t1 - hours * HOUR_MS
    t0 -= t0 % MIN_MS
    t1 -= t1 % MIN_MS
    if t1 <= t0:
        raise ValueError("end must be after start")
    return t0, t1


def config_from_params(params: dict) -> CRHConfig:
    capital = float(params.get("capital", 50))
    leverage = float(params.get("leverage", 10))
    overrides = {}
    for k in ("risk_per_trade_usd", "max_combined_risk_usd", "trailing_drawdown_usd",
              "strategy_loss_trigger_usd", "max_open_positions", "fidelity", "signal_timeframe",
              "crash_window_bars", "crash_drop_pct", "require_hammer", "atr_stop_multiplier",
              "trail_atr_multiplier", "approx_half_spread"):
        if params.get(k) is not None:
            v = params[k]
            overrides[k] = v if k in ("fidelity", "signal_timeframe", "require_hammer") else \
                (int(v) if k == "max_open_positions" else float(v))
    if params.get("risk_pct") is not None and "risk_per_trade_usd" not in overrides:
        overrides["risk_per_trade_usd"] = round(capital * float(params["risk_pct"]) / 100, 6)
        overrides["max_combined_risk_usd"] = round(overrides["risk_per_trade_usd"] * 3, 6)
    cfg = scaled_baseline(capital, leverage, **overrides)
    if params.get("label"):
        cfg = replace(cfg, label=str(params["label"]))
    return cfg


# ----------------------------------------------------------------- provider
class CacheProvider(FrameProvider):
    def __init__(self, cache: Cache, cfg: CRHConfig, universe: dict[str, list[str]],
                 instruments: dict[str, dict], t0: int, t1: int, warmup_ms: int,
                 progress=None, books_on_demand: bool = True):
        self.cache, self.cfg, self.uni, self.inst = cache, cfg, universe, instruments
        self.t0, self.t1, self.warmup = t0, t1, warmup_ms
        self.progress, self.on_demand = progress, books_on_demand
        self.quotes: dict[str, BookQuotes] = {}
        self._frames: dict[str, SymbolFrame | None] = {}

    def universe(self, day: str) -> list[str]:
        return self.uni.get(day, [])

    def bybit_symbol(self, ccxt: str) -> str:
        return self.inst[ccxt].get("bybit_symbol") or (ccxt.split("/")[0] + "USDT")

    def frame(self, symbol: str) -> SymbolFrame | None:
        if symbol in self._frames:
            return self._frames[symbol]
        meta = self.inst.get(symbol)
        if meta is None:
            self._frames[symbol] = None
            return None
        sym = self.bybit_symbol(symbol)
        h1 = self.cache.klines(sym, "1h", self.t0 - self.warmup, self.t1)
        m1 = self.cache.klines(sym, "1m", self.t0 - HOUR_MS, self.t1)
        if len(h1) == 0 or len(m1) == 0:
            self._frames[symbol] = None
            return None
        spec = ContractSpec(symbol, meta["taker_fee"], meta["maint_margin_rate"],
                            meta["tick_size"], meta["lot_size"])
        sig_ts, sig = (h1[:, 0].astype(np.int64), h1[:, 1:6]) if self.cfg.signal_timeframe == "1h" \
            else (m1[:, 0].astype(np.int64), m1[:, 1:6])
        q = None
        if self.cfg.fidelity == "exact":
            q = self.quotes.setdefault(sym, BookQuotes(self.cache, sym, self.progress, self.on_demand))
        fr = SymbolFrame(symbol, spec, sig_ts, np.ascontiguousarray(sig),
                         m1[:, 0].astype(np.int64), np.ascontiguousarray(m1[:, 1:5]),
                         self.cache.funding(sym, self.t0 - 7 * DAY_MS, self.t1), q)
        self._frames[symbol] = fr
        return fr


# -------------------------------------------------------------------- store
class RunStore:
    SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, created_ms INTEGER NOT NULL, status TEXT NOT NULL,
        reuse_key TEXT, label TEXT, params_json TEXT NOT NULL, summary_json TEXT,
        error TEXT);"""

    def __init__(self, db_path: str = "state/crh_lab.sqlite", results_dir: str = "state/crh_runs"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(self.SCHEMA)

    def create(self, run_id: str, params: dict, reuse_key: str, label: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO runs(run_id, created_ms, status, reuse_key, label, "
                              "params_json) VALUES(?,?,?,?,?,?)",
                              (run_id, int(time.time() * 1000), "running", reuse_key, label,
                               json.dumps(params)))

    def finish(self, run_id: str, result: dict) -> None:
        (self.results_dir / f"{run_id}.json.gz").write_bytes(
            gzip.compress(json.dumps(result, default=str).encode()))
        with self.conn:
            self.conn.execute("UPDATE runs SET status='done', summary_json=? WHERE run_id=?",
                              (json.dumps(result["summary"], default=str), run_id))

    def fail(self, run_id: str, error: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE runs SET status=?, error=? WHERE run_id=?",
                              ("cancelled" if error == "cancelled" else "failed", error, run_id))

    def find_reusable(self, reuse_key: str) -> str | None:
        row = self.conn.execute("SELECT run_id FROM runs WHERE reuse_key=? AND status='done' "
                                "ORDER BY created_ms DESC LIMIT 1", (reuse_key,)).fetchone()
        return row["run_id"] if row else None

    def list(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY created_ms DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d.pop("params_json"))
            d["summary"] = json.loads(d["summary_json"]) if d["summary_json"] else None
            d.pop("summary_json")
            out.append(d)
        return out

    def load(self, run_id: str) -> dict | None:
        p = self.results_dir / f"{run_id}.json.gz"
        if not p.exists():
            return None
        return json.loads(gzip.decompress(p.read_bytes()))

    def delete(self, run_id: str) -> None:
        (self.results_dir / f"{run_id}.json.gz").unlink(missing_ok=True)
        with self.conn:
            self.conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))


# ----------------------------------------------------------------- pipeline
def daily_breakdown(result: dict, t0: int, t1: int) -> list[dict]:
    """Per UTC day: equity at start/end, realised P&L from trades closed that
    day, mark-to-market change (the rest), fees/funding paid that day."""
    curve = result["equity_curve"]
    days = days_between(t0, t1)
    out = []
    for d in days:
        a = max(t0, int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000))
        b = min(t1, a + DAY_MS - (a % DAY_MS))
        start_eq = next((p[1] for p in reversed(curve) if p[0] <= a + 5000), result["config"]["starting_capital_usd"])
        end_eq = next((p[1] for p in reversed(curve) if p[0] <= b + 5000), start_eq)
        closed = [t for t in result["trades"] if a <= t["exit_ms"] < b]
        realised = sum(t["net_pnl_usd"] for t in closed)
        fees = sum(t["entry_fee_usd"] + t["exit_fee_usd"] for t in closed)
        funding = sum(e["amount_usd"] for e in result["funding_events"] if a <= e["funding_ts_ms"] < b)
        out.append({"date": d, "start_equity": start_eq, "end_equity": end_eq,
                    "change": end_eq - start_eq, "realised_pnl": realised,
                    "mark_to_market": end_eq - start_eq - realised,
                    "closed_trades": len(closed), "fees_closed_trades": fees,
                    "funding_paid": funding})
    return out


def mark_liquidation_check(cache: Cache, provider: CacheProvider, result: dict,
                           cfg: CRHConfig, offline: bool) -> dict:
    """Exchange liquidates on MARK price: did mark ever cross the estimate?"""
    out = {"checked": 0, "sim_liquidations": 0, "mark_crossed_liq": 0, "mismatch": [],
           "unavailable": []}
    for t in result["trades"]:
        sym = provider.bybit_symbol(t["symbol"])
        try:
            rows = cache.mark_1m(sym, t["entry_ms"] - t["entry_ms"] % MIN_MS, t["exit_ms"] + MIN_MS)
        except Exception as exc:                       # network off: say so, never guess
            out["unavailable"].append(f"{sym}: {type(exc).__name__}")
            continue
        liq = liquidation_price(t["side"], t["entry_price"], cfg.leverage,
                                provider.inst[t["symbol"]]["maint_margin_rate"])
        crossed = bool(len(rows) and ((rows[:, 3] <= liq).any() if t["side"] == "long"
                                      else (rows[:, 2] >= liq).any()))
        out["checked"] += 1
        out["sim_liquidations"] += t["exit_reason"] == "LIQUIDATION"
        out["mark_crossed_liq"] += crossed
        if crossed != (t["exit_reason"] == "LIQUIDATION"):
            out["mismatch"].append({"trade_id": t["id"], "symbol": t["symbol"],
                                    "exit_reason": t["exit_reason"], "mark_crossed": crossed})
    return out


def reuse_key(params: dict, cfg: CRHConfig, t0: int, t1: int) -> str:
    key = {"cfg": cfg.fingerprint(), "t0": t0, "t1": t1, "data": DATA_VERSION,
           "universe": params.get("universe", "top20"),
           "symbols": sorted(params.get("symbols") or [])}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:20]


def run_backtest(params: dict, cache: Cache | None = None, store: RunStore | None = None,
                 progress=None, cancelled=None, run_id: str | None = None,
                 force: bool = False) -> dict:
    """Full pipeline. progress(stage, fraction, detail); cancelled() -> bool."""
    progress = progress or (lambda *a: None)
    cancelled = cancelled or (lambda: False)
    cache = cache or Cache()
    t0, t1 = resolve_window(params)
    cfg = config_from_params(params)
    key = reuse_key(params, cfg, t0, t1)
    run_id = run_id or uuid.uuid4().hex[:12]
    if store is not None:
        if not force:
            prev = store.find_reusable(key)
            if prev:
                res = store.load(prev)
                if res is not None:
                    res["reused_from"] = prev
                    return res
        store.create(run_id, params, key, cfg.label)
    started = time.time()
    stage_times = {}
    try:
        # ---- 1. universe ----
        s = time.time()
        progress("universe", 0.0, "resolving point-in-time universe")
        ub = UniverseBuilder(cache)
        uni_spec = params.get("universe", "top20")
        if params.get("symbols"):
            # explicit instrument list: eligibility still verified from public metadata
            rows = {r["symbol"]: r for r in cache.instruments_info()}
            instruments, universe, ineligible, daily = {}, {}, {}, {}
            for ccxt in params["symbols"]:
                bsym = ccxt.split("/")[0] + "USDT"
                r = rows.get(bsym)
                if r is None or r["contractType"] != "LinearPerpetual" or r["status"] != "Trading":
                    ineligible[ccxt] = f"{bsym} not an active Bybit linear perpetual"
                    continue
                rl = cache.risk_tier1(bsym)
                if not rl.get("maintenanceMargin"):
                    ineligible[ccxt] = f"{bsym} maintenance margin unavailable"
                    continue
                instruments[ccxt] = {"coingecko_id": None, "exchange": "bybit", "symbol": ccxt,
                                     "bybit_symbol": bsym, "contract_multiplier": 1, "eligible": 1,
                                     "taker_fee": 0.0006,
                                     "maint_margin_rate": float(rl["maintenanceMargin"]),
                                     "tick_size": float(r["priceFilter"]["tickSize"]),
                                     "lot_size": float(r["lotSizeFilter"]["qtyStep"]),
                                     "launch_ms": int(r["launchTime"]),
                                     "source": "Bybit public instruments-info + risk-limit tier 1"}
            for d in days_between(t0, t1):
                universe[d] = [s for s in params["symbols"] if s in instruments]
            universe_note = "explicit symbol list (not a market-cap universe)"
        else:
            size = int(uni_spec.replace("top", ""))
            daily = ub.daily_top(size, t0, t1, progress, cancelled)
            universe, instruments, ineligible = ub.map_instruments(daily)
            universe_note = f"daily top-{size} by CoinGecko market cap at 00:00 UTC; {SURVIVORSHIP_NOTE}"
        stage_times["universe"] = round(time.time() - s, 2)
        if cancelled():
            raise RuntimeError("cancelled")
        # ---- 2. candles ----
        s = time.time()
        syms = sorted({(instruments[c].get("bybit_symbol") or c.split("/")[0] + "USDT")
                       for day in universe.values() for c in day})
        cache.prefetch(syms, t0, t1, DEFAULT_WARMUP_MS, progress, cancelled)
        stage_times["candles"] = round(time.time() - s, 2)
        if cancelled():
            raise RuntimeError("cancelled")
        # ---- 3. prescan ----
        s = time.time()
        provider = CacheProvider(cache, cfg, universe, instruments, t0, t1, DEFAULT_WARMUP_MS,
                                 lambda msg: progress("books", None, msg))
        candidates, misses, no_data = {}, {}, []
        all_syms = sorted({c for day in universe.values() for c in day})
        for i, ccxt in enumerate(all_syms):
            fr = provider.frame(ccxt)
            if fr is None:
                no_data.append(ccxt)
                continue
            c = prescan(fr, cfg, t0, t1)
            if c:
                candidates[ccxt] = c
            m = near_misses(fr, cfg, t0, t1)
            if m:
                misses[ccxt] = m
            progress("prescan", (i + 1) / max(1, len(all_syms)), ccxt)
        stage_times["prescan"] = round(time.time() - s, 2)
        # ---- 4. smart L2 (exact mode): the day of each candidate signal ----
        s = time.time()
        l2_missing = []
        if cfg.fidelity == "exact":
            needed = sorted({(provider.bybit_symbol(c), dt.datetime.fromtimestamp(
                x["close_ts"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d"))
                for c, lst in candidates.items() for x in lst})
            for i, (sym, date) in enumerate(needed):
                if cancelled():
                    raise RuntimeError("cancelled")
                if cache.ensure_book_day(sym, date, lambda m: progress("books", i / max(1, len(needed)), m)) is None:
                    l2_missing.append(f"{sym} {date}")
        stage_times["books"] = round(time.time() - s, 2)
        # ---- 5. replay ----
        s = time.time()
        eng = CRHReplay(cfg, provider, t0, t1, lambda st, f: progress(st, f, None), cancelled)
        result = eng.run()
        stage_times["replay"] = round(time.time() - s, 2)
        # ---- 6. report ----
        s = time.time()
        progress("report", 0.5, "metrics + checks")
        for q in provider.quotes.values():
            l2_missing += [f"{q.sym} {d}" for d in q.missing_days]
        curve = [[p[0], p[1]] for p in result["equity_curve"]]
        tot = metrics(result["trades"], result["open_at_end"], curve,
                      cfg.starting_capital_usd, cfg.slippage_rate)
        unreal_gross = sum(p["unrealized_pnl_usd"] or 0.0 for p in result["open_at_end"])
        identity_gap = (result["final_cash"] + sum(p["margin_usd"] for p in result["open_at_end"])
                        + unreal_gross) - result["final_equity"]
        mark_check = mark_liquidation_check(cache, provider, result, cfg, cache.offline)
        exact_with_gaps = cfg.fidelity == "exact" and bool(sorted(set(l2_missing)))
        fidelity_label = ("approximate (1m opens ± synthetic half-spread; conservative costs)"
                          if cfg.fidelity == "approximate" else
                          "exact-with-gaps (archived L2; some symbol-days unavailable, see warnings)"
                          if exact_with_gaps else "exact (archived Bybit L2 quotes + 1m price path)")
        warnings = list(result["warnings"])
        if exact_with_gaps:
            warnings.append("Archived L2 unavailable for: " + ", ".join(sorted(set(l2_missing))))
        if no_data:
            warnings.append("No candle data (skipped like the live engine): " + ", ".join(no_data))
        if ineligible:
            warnings.append(f"{len(ineligible)} NOT ELIGIBLE: " + "; ".join(
                f"{k}: {v}" for k, v in list(ineligible.items())[:25]))
        if not instruments:
            warnings.append("No eligible instruments: nothing could be traded")
        if cache.events:
            pass
        summary = {
            "label": "HISTORICAL BACKTEST", "config_label": cfg.label,
            "is_baseline_rules": cfg.is_baseline(), "fidelity": fidelity_label,
            "window": {"start": utc_iso(t0), "end_exclusive": utc_iso(t1), "start_ms": t0,
                       "end_ms": t1, "hours": (t1 - t0) // HOUR_MS},
            "universe": uni_spec if not params.get("symbols") else "custom",
            "eligible_instruments": len(instruments), "candidate_signals":
                sum(len(v) for v in candidates.values()),
            "final_equity": tot["final_equity_usd"], "net_return_pct": tot["net_return_pct"],
            "realized_pnl": tot["net_realized_pnl_usd"], "unrealized_pnl": tot["net_unrealized_pnl_usd"],
            "trades": tot["completed_trades"], "open_at_end": tot["open_positions_at_end"],
            "win_rate_pct": tot["win_rate_pct"], "profit_factor": tot["profit_factor"],
            "max_drawdown_usd": tot["max_drawdown_usd"], "max_drawdown_pct": tot["max_drawdown_pct"],
            "fees_usd": tot["fees_usd"], "funding_usd": tot["funding_usd"],
            "slippage_usd_est": tot["slippage_usd_est"], "liquidations": tot["liquidations"],
            "locked": result["locked"], "strategy_locked": result["strategy_locked"],
            "capital": cfg.starting_capital_usd, "leverage": cfg.leverage,
            "elapsed_s": round(time.time() - started, 2), "stage_times_s": stage_times,
            "warnings_count": len(warnings), "small_sample": tot["small_sample"],
        }
        out = {
            **result, "run_id": run_id, "params": params, "summary": summary, "totals": tot,
            "daily": daily_breakdown(result, t0, t1),
            "universe": {"spec": uni_spec, "note": universe_note, "daily": universe,
                         "daily_ranked": {d: [{k: c[k] for k in ("id", "symbol", "rank")} for c in v]
                                          for d, v in (daily or {}).items()},
                         "ineligible": ineligible},
            "instruments": instruments,
            "candidates": candidates, "near_misses": misses,
            "data": {"version": DATA_VERSION,
                     "sources": ["Bybit v5 public REST kline/mark-price-kline/funding/risk-limit/"
                                 "instruments-info (no auth)",
                                 "Bybit public historical orderbook.200 archive (quote-saver.bycsi.com)",
                                 "CoinGecko public API (market caps, categories)"],
                     "fidelity": fidelity_label, "l2_missing": sorted(set(l2_missing)),
                     "cache_events": cache.events[-200:], "no_data": no_data},
            "checks": {"leakage": result["leakage_check"],
                       "accounting_identity_gap_usd": identity_gap,
                       "accounting_ok": abs(identity_gap) < 1e-6,
                       "stops_never_widened": all(t["stop_final"] >= t["stop_initial"] for t in result["trades"]
                                                  if t["side"] == "long"),
                       "mark_price_liquidation": mark_check,
                       "unmonitored_cycles": result["unmonitored_cycles"]},
            "warnings": warnings,
            "reused_from": None,
        }
        stage_times["report"] = round(time.time() - s, 2)
        summary["stage_times_s"] = stage_times
        summary["elapsed_s"] = round(time.time() - started, 2)
        if store is not None:
            store.finish(run_id, out)
        progress("done", 1.0, None)
        return out
    except Exception as exc:
        if store is not None:
            store.fail(run_id, str(exc))
        raise
