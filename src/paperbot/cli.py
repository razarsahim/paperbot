from __future__ import annotations
import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import sys
import time
from pathlib import Path
from .backtest import backtest
from .config import Settings
from .engine import PaperEngine
from .market import PublicSpotMarket, load_csv
from .notify import FailureTracker, Notifier, dispatch_events
from .store import Store


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def single_instance(db_path: str):
    # fcntl is built into macOS / Linux; avoid simultaneous engine writers.
    import fcntl
    path = Path(db_path).expanduser().with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another engine is running against this database") from exc
        yield


def run_once(db_path: str, cfg: Settings, notifier: Notifier | None = None, market=None):
    if market is None:
        market = PublicSpotMarket(cfg.exchange, cfg.symbol, cfg.timeframe)
    bars, quote = market.snapshot()
    store = Store(db_path, cfg.starting_balance, cfg.symbol)
    try:
        engine = PaperEngine(store, cfg)
        events = engine.tick(bars, quote, int(time.time() * 1000))
        equity = engine.equity(quote.bid)
        print(f"{stamp()} PAPER ONLY {cfg.symbol} bid={quote.bid:.2f} equity={equity:.2f}")
        for event in events:
            print("  ", event)
        if not events:
            print("   No new action")
        if notifier is not None:
            dispatch_events(notifier, events)
    finally:
        store.close()


def run_loop(db_path: str, cfg: Settings, notifier: Notifier,
             market_factory=None, sleep=time.sleep, iterations: int | None = None):
    """Poll until stopped. Feed failures back off exponentially (capped at
    15 min), alert after a streak, and alert again on recovery — failures are
    printed, never hidden, and no synthetic data is substituted."""
    if market_factory is None:
        market_factory = lambda: PublicSpotMarket(cfg.exchange, cfg.symbol, cfg.timeframe)
    market = None
    tracker = FailureTracker(threshold=3)
    done = 0
    while iterations is None or done < iterations:
        done += 1
        try:
            if market is None:
                market = market_factory()
            run_once(db_path, cfg, notifier, market)
        except Exception as exc:
            print(f"{stamp()} SAFE ERROR (no new position): {type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)
            if tracker.record_failure(str(exc)):
                notifier.send("error", "FEED FAILURE",
                              f"{tracker.streak} consecutive failed polls; latest: {exc}",
                              key="feed-failure")
            sleep(min(cfg.interval_seconds * 2 ** min(tracker.streak, 5), 900))
            continue
        if tracker.record_success():
            notifier.send("info", "FEED RECOVERED", "public market data polling restored")
        sleep(cfg.interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Spot-only crypto paper bot: NO real trades")
    parser.add_argument("--db", default="state/paper.sqlite", help="Virtual portfolio SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("once", help="Process one public-market snapshot and exit")
    sub.add_parser("run", help="Poll continuously while this process stays running")
    sub.add_parser("status", help="Show saved simulated portfolio and trade log")
    download = sub.add_parser("fetch-history", help="Fetch public spot OHLCV history, no orders")
    download.add_argument("--csv", default="data/real_kraken_btc_gbp.csv")
    download.add_argument("--limit", type=int, default=720)
    back = sub.add_parser("backtest", help="Run candle-accurate (not tick-accurate) offline test")
    back.add_argument("--csv", required=True, help="Candle CSV with ms timestamps and OHLCV")
    wf = sub.add_parser("walkforward",
                        help="Frozen-parameter rolling out-of-sample evaluation, offline")
    wf.add_argument("--csv", required=True, help="Candle CSV with ms timestamps and OHLCV")
    wf.add_argument("--windows", type=int, default=4)
    args = parser.parse_args()
    cfg = Settings.from_env()
    if args.command == "fetch-history":
        market = PublicSpotMarket(cfg.exchange, cfg.symbol, cfg.timeframe)
        candles = market.historical(args.limit)
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
            for b in candles:
                writer.writerow([b.timestamp, b.open, b.high, b.low, b.close, b.volume])
        provenance = {"exchange": cfg.exchange, "symbol": cfg.symbol,
            "market_type": "spot", "timeframe": cfg.timeframe,
            "retrieved_at_utc": stamp(), "number_of_closed_candles": len(candles),
            "first_bar_utc": candles[0].iso, "last_bar_utc": candles[-1].iso,
            "source": "ccxt public fetch_ohlcv", "no_live_execution": True}
        Path(str(out) + ".metadata.json").write_text(json.dumps(provenance, indent=2))
        print(f"Saved {len(candles)} real PUBLIC spot candles to {out} (see .metadata.json).")
        return
    if args.command == "backtest":
        result = backtest(load_csv(args.csv), cfg)
        print(json.dumps(result.summary(), indent=2))
        return
    if args.command == "walkforward":
        from .validation import walk_forward
        report = walk_forward(load_csv(args.csv), cfg, n_windows=args.windows)
        out = report.summary()
        meta_path = Path(args.csv + ".metadata.json")
        if meta_path.exists():
            out["data_provenance"] = json.loads(meta_path.read_text())
        else:
            out["data_provenance"] = "UNKNOWN: no .metadata.json beside the CSV"
        print(json.dumps(out, indent=2))
        return
    if args.command == "status":
        store = Store(args.db, cfg.starting_balance, cfg.symbol)
        try:
            print(json.dumps({"mode": "PAPER ONLY", "symbol": cfg.symbol,
                "virtual_cash": store.get("balance"), "position": store.position(),
                "total_drawdown_locked": store.get("locked_total"),
                "closed_trades": store.trades(100)}, indent=2))
        finally:
            store.close()
        return
    notifier = Notifier.from_env(str(Path(args.db).expanduser().parent))
    with single_instance(args.db):
        if args.command == "once":
            run_once(args.db, cfg, notifier)
        else:
            print("PAPER ONLY; Ctrl+C to stop polling. No exchange keys or order permissions.", flush=True)
            try:
                run_loop(args.db, cfg, notifier)
            except KeyboardInterrupt:
                print("Stopped.")


if __name__ == "__main__":
    main()
