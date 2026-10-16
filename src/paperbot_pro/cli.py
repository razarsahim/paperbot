"""PaperBot Pro CLI. PAPER ONLY: no credentials, no order placement."""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from .config import ProSettings


@contextmanager
def single_instance(db_path: str):
    import fcntl
    path = Path(db_path).expanduser().with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another pro engine is running against this database") from exc
        yield


def _http_get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "paperbot-pro-research"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def refresh_universe_and_instruments(store, cfg: ProSettings) -> None:
    from .marketdata import shared_marketdata
    from .universe import (UniverseCoin, fetch_coingecko_universe, refresh_universe,
                           resolve_instruments, store_instruments)
    ok = refresh_universe(store, cfg, fetcher=lambda: fetch_coingecko_universe(cfg, _http_get))
    print(f"universe refresh: {'ok' if ok else 'FAILED (previous kept)'}")
    rows = list(store.conn.execute("SELECT * FROM universe ORDER BY rank"))
    coins = [UniverseCoin(r["coingecko_id"], r["symbol"], r["name"], r["rank"],
                          r["price_usd"], r["change_24h_pct"], r["market_cap_usd"],
                          r["volume_24h_usd"]) for r in rows]
    md = shared_marketdata(cfg)
    markets_by_ex, tiers_by_ex = {}, {}
    for exchange in cfg.exchanges[:2]:  # bounded: two venues cover the top-20
        try:
            markets_by_ex[exchange] = md.markets(exchange)
            tiers_by_ex[exchange] = md.leverage_tiers(exchange)
        except Exception as exc:
            store.audit("error", "universe", f"{exchange} metadata failed: {exc}")
    resolved = resolve_instruments(coins, markets_by_ex, tiers_by_ex, cfg)
    store_instruments(store, resolved, int(time.time() * 1000))
    eligible = sum(1 for r in resolved if r["eligible"])
    print(f"instruments: {eligible}/{len(resolved)} eligible")
    for r in resolved:
        if not r["eligible"]:
            print(f"  NOT ELIGIBLE {r['coingecko_id']}: {r['reason']}")


def main():
    parser = argparse.ArgumentParser(
        description="PaperBot Pro: multi-asset SIMULATED perp paper trading. NO real orders.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("api", help="Serve the read-only dashboard API on 127.0.0.1")
    sub.add_parser("universe", help="Refresh top-20 universe and perp instrument eligibility")
    sub.add_parser("scan-once", help="One bounded scan/manage cycle, then exit")
    sub.add_parser("run", help="Continuous paper engine (universe daily, scan per interval)")
    sub.add_parser("validate", help="Run per-market perp backtests on real public candles; "
                                    "writes the validation artifact required for auto-entry")
    sub.add_parser("hype-refresh", help="Refresh the WATCH-ONLY hype radar from public pools data")
    sub.add_parser("status", help="Print the simulated portfolio overview")
    args = parser.parse_args()
    cfg = ProSettings.from_env()
    from .store import ProStore
    if args.command == "api":
        import uvicorn
        from .api import create_app
        print(f"PAPER ONLY read-only API on http://{cfg.api_host}:{cfg.api_port} — never expose publicly")
        uvicorn.run(create_app(cfg), host=cfg.api_host, port=cfg.api_port, log_level="info")
        return
    store = ProStore(cfg.db_path, cfg)
    try:
        if args.command == "universe":
            refresh_universe_and_instruments(store, cfg)
        elif args.command == "status":
            from .api import compute_overview
            print(json.dumps(compute_overview(store, cfg), indent=2))
        elif args.command == "validate":
            from .marketdata import shared_marketdata
            from .validation import run_validation
            report = run_validation(store, cfg, shared_marketdata(cfg))
            print(json.dumps({k: report[k] for k in ("summary", "combined", "warnings")}, indent=2))
            print(f"artifact written: {cfg.validation_report_path}")
        elif args.command == "hype-refresh":
            from .hype import refresh_hype
            tokens = refresh_hype(store, cfg, _http_get)
            print(f"hype radar: {len(tokens)} tokens scored (ALL WATCH ONLY / REJECTED)")
        elif args.command == "scan-once":
            from .engine import ProEngine
            with single_instance(cfg.db_path):
                summary = ProEngine(store, cfg).run_cycle()
                print(json.dumps(summary))
        elif args.command == "run":
            from .engine import ProEngine
            engine = ProEngine(store, cfg)
            print("PAPER ONLY pro engine; Ctrl+C to stop. No exchange keys or order permissions.",
                  flush=True)
            with single_instance(cfg.db_path):
                failures = 0
                last_universe = 0.0
                while True:
                    try:
                        if time.time() - last_universe > cfg.universe_refresh_hours * 3600:
                            refresh_universe_and_instruments(store, cfg)
                            from .hype import refresh_hype
                            refresh_hype(store, cfg, _http_get)
                            last_universe = time.time()
                        summary = engine.run_cycle()
                        print(f"{time.strftime('%H:%M:%S')} scan {summary}", flush=True)
                        failures = 0
                        time.sleep(cfg.scan_interval_seconds)
                    except KeyboardInterrupt:
                        print("Stopped.")
                        break
                    except Exception as exc:
                        failures += 1
                        store.audit("error", "engine", f"cycle failed: {type(exc).__name__}: {exc}")
                        print(f"SAFE ERROR (no entries): {type(exc).__name__}: {exc}",
                              file=sys.stderr, flush=True)
                        time.sleep(min(cfg.scan_interval_seconds * 2 ** min(failures, 5), 1800))
    finally:
        store.close()


if __name__ == "__main__":
    main()
