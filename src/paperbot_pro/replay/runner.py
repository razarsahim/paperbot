"""Drive the UNCHANGED LabEngine through a historical window, minute by minute.

Per simulated minute boundary M (cycle time t = M + 5 s, the live engine's
60 s cadence):
  1. Tick emulation for the 1m bar [M-60s, M): the live engine also checks
     stops/liquidation on every WebSocket tick. From 1m trade-price extremes
     (adjusted by the observed half-spread to approximate bid/ask) we derive
     the first price a tick-driven check would have acted on:
       - open already beyond the stop -> gap fill at the open
       - otherwise a crossed stop fills at the stop price (then the engine's
         own slippage + fees apply in check_exit)
       - if the extreme reaches the liquidation estimate anywhere in the bar,
         LIQUIDATION is taken (conservative: the worse outcome wins for an
         ambiguous bar, as in perp.check_exit)
  2. engine.run_cycle(t): the real monitoring, funding, equity-floor locks,
     completed-candle signal scan, risk governor, entries, trailing-stop
     ratchet, trailing-drawdown HWM and integrity check.

Throwaway SQLite per run. The main DB is never opened by this module.
"""
from __future__ import annotations
import json
import time
from dataclasses import replace
from pathlib import Path

from ..lab.config import STRATEGIES, LabSettings
from ..lab.engine import LabEngine
from ..lab.store import LabStore
from ..perp import check_exit, unrealized_pnl
from .market import HistoricalMarket, bybit_id

MIN_MS = 60_000
CYCLE_OFFSET_MS = 5_000


def _half_spread(market: HistoricalMarket, symbol: str, t: int) -> float:
    s = market.data[bybit_id(symbol)].books.get(t)
    if s is None or not s[2] or not s[3] or s[1] > market.now_ms:
        return 0.0
    return (s[3][0][0] - s[2][0][0]) / 2.0


def emulate_ticks(engine: LabEngine, market: HistoricalMarket, minute_start: int) -> int:
    """Stop/liquidation checks over one completed 1m bar. Returns exits."""
    closed = 0
    bar_end = minute_start + MIN_MS
    for pos in engine.db.open_positions():
        bar = market.minute_bar(pos["symbol"], minute_start)
        if bar is None:
            continue
        if pos["opened_ms"] >= bar_end:
            continue
        hs = _half_spread(market, pos["symbol"], minute_start + CYCLE_OFFSET_MS)
        o, h, l = bar[1], bar[2], bar[3]
        if pos["side"] == "long":
            first, worst = o - hs, l - hs
            if worst <= pos["liq_price_est"]:
                observed = worst
            elif first <= pos["stop"]:
                observed = first
            elif worst <= pos["stop"]:
                observed = pos["stop"]
            else:
                continue
        else:
            first, worst = o + hs, h + hs
            if worst >= pos["liq_price_est"]:
                observed = worst
            elif first >= pos["stop"]:
                observed = first
            elif worst >= pos["stop"]:
                observed = pos["stop"]
            else:
                continue
        event = check_exit(pos, observed, engine.cfg, pos["taker_fee"])
        if event is not None:
            engine.close_position(pos, event, bar_end)
            closed += 1
    return closed


def make_engine(db_path: Path, market: HistoricalMarket, instruments: list[dict],
                strategies: list[str] | None, capital_per_strategy: float = 50.0):
    """Fresh isolated LabStore/LabEngine. strategies=None -> all 10 sleeves
    (combined portfolio); a subset -> independent sleeve(s) only."""
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    base = LabSettings()
    keys = [s.key for s in STRATEGIES] if strategies is None else list(strategies)
    capital = capital_per_strategy * len(keys)
    store = LabStore(str(db_path), base)        # validates the stock config
    cfg = replace(base, starting_capital_usd=capital, db_path=str(db_path),
                  ws_enabled=False, live_state_path=str(db_path) + ".live.json",
                  auto_entry=True)
    store.cfg = cfg
    with store.conn:
        store.conn.execute(
            f"DELETE FROM strategies WHERE key NOT IN ({','.join('?' * len(keys))})", keys)
    store.set("initial_capital", capital)
    store.set("peak_equity", capital)
    store.set("lab_auto_entry", True)
    store.set("replay_note", "HISTORICAL BACKTEST - not live paper")
    engine = LabEngine(store, cfg, market=market,
                       instruments_provider=lambda: instruments)
    return engine


def run(engine: LabEngine, market: HistoricalMarket, t0: int, t1: int,
        progress_every: int = 0) -> dict:
    started = time.time()
    tick_exits = 0
    minute = t0
    n = 0
    while minute < t1:
        t = minute + CYCLE_OFFSET_MS
        market.set_now(t)
        if minute > t0:
            tick_exits += emulate_ticks(engine, market, minute - MIN_MS)
        engine.run_cycle(t)
        n += 1
        if progress_every and n % progress_every == 0:
            print(f"  cycle {n} t={t} trades={len(engine.db.trades(100000))} "
                  f"{time.time() - started:.0f}s", flush=True)
        minute += MIN_MS
    # final minute [t1-60s, t1): stops can still trigger before the window ends
    market.set_now(t1)
    tick_exits += emulate_ticks(engine, market, t1 - MIN_MS)
    # mark-to-market remaining positions at the last fully-closed 1m close
    open_marks = []
    for pos in engine.db.open_positions():
        last = market.last_trade(pos["symbol"])
        open_marks.append({**{k: pos[k] for k in (
            "id", "strategy", "symbol", "side", "qty", "entry_price", "stop",
            "initial_stop", "liq_price_est", "margin_usd", "notional_usd",
            "entry_fee_usd", "funding_paid_usd", "planned_risk_usd", "opened_ms",
            "rationale")},
            "mark": last,
            "unrealized_pnl_usd": unrealized_pnl(pos["side"], pos["entry_price"], last,
                                                 pos["qty"]) if last else None})
    return {"cycles": n, "tick_exits": tick_exits, "open_at_end": open_marks,
            "elapsed_s": round(time.time() - started, 1),
            "max_data_ts_served": market.max_ts_served, "final_now": market.now_ms}


def instruments_from_main_db(main_db: str, symbols: list[str] | None = None) -> list[dict]:
    """Read-only instrument metadata (same query the live engine uses)."""
    from ..lab.engine import main_db_instruments
    rows = main_db_instruments(main_db)
    if symbols:
        rows = [r for r in rows if r["symbol"] in symbols]
    return rows


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))
