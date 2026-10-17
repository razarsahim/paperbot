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
    validate = sub.add_parser("validate",
                              help="Run per-market perp backtests on real public candles; "
                                   "writes the validation artifact required for auto-entry")
    validate.add_argument("--days", type=int, default=None,
                          help="Paginate this many days of history (e.g. 730); default ~40 days")
    validate.add_argument("--markets", type=int, default=None,
                          help="Limit to the top N eligible markets")
    sub.add_parser("hype-refresh", help="Refresh the WATCH-ONLY hype radar from public pools data")
    sub.add_parser("status", help="Print the simulated portfolio overview")
    sub.add_parser("pause", help="Manually block NEW simulated entries (exits keep running)")
    sub.add_parser("resume", help="Lift a manual pause")
    sub.add_parser("lab-once", help="One Extreme Lab monitor/scan cycle (PAPER ONLY)")
    sub.add_parser("lab-run", help="Continuous Extreme Lab paper engine")
    sub.add_parser("lab-status", help="Extreme Lab capital, HWM/threshold and strategies")
    sub.add_parser("lab-pause", help="Manually block new Lab entries")
    sub.add_parser("lab-resume", help="Lift the Lab manual pause")
    lab_reset = sub.add_parser("lab-reset",
                               help="Clear the trailing-drawdown lockout AFTER manual review")
    lab_reset.add_argument("--note", required=True,
                           help="Required review note recorded in the audit log")
    sub.add_parser("migrate-lab",
                   help="One-time main-portfolio rebalance to $750 (engine must be stopped)")
    args = parser.parse_args()
    cfg = ProSettings.from_env()
    from .store import ProStore
    if args.command and args.command.startswith("lab-"):
        _lab_main(args, cfg)
        return
    if args.command == "api":
        import uvicorn
        from .api import create_app
        print(f"PAPER ONLY read-only API on http://{cfg.api_host}:{cfg.api_port} — never expose publicly")
        uvicorn.run(create_app(cfg), host=cfg.api_host, port=cfg.api_port, log_level="info")
        return
    store = ProStore(cfg.db_path, cfg)
    try:
        if args.command == "migrate-lab":
            _migrate_lab(store, cfg)
        elif args.command == "pause":
            store.set("manual_pause", True)
            store.audit("warning", "risk", "manual pause ENABLED: no new simulated entries")
            print("Paused: no new simulated entries. Open positions keep stop/target/"
                  "liquidation monitoring. `propaper resume` to re-enable.")
        elif args.command == "resume":
            store.set("manual_pause", False)
            store.audit("info", "risk", "manual pause lifted")
            print("Resumed: entries re-enabled (subject to all risk gates).")
        elif args.command == "universe":
            refresh_universe_and_instruments(store, cfg)
        elif args.command == "status":
            from .api import compute_overview
            print(json.dumps(compute_overview(store, cfg), indent=2))
        elif args.command == "validate":
            from .marketdata import shared_marketdata
            from .validation import run_validation
            report = run_validation(store, cfg, shared_marketdata(cfg),
                                    days=args.days, max_markets=args.markets)
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


def _migrate_lab(store, cfg: ProSettings) -> None:
    """One-time restructure of the RUNNING state to main $750 + Lab $250.
    Refuses while the main engine holds its lock, and refuses when the
    accounting is not in the known pre-migration state."""
    import fcntl
    lock_path = Path(cfg.db_path).with_suffix(".lock")
    if lock_path.exists():
        with open(lock_path, "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
            except BlockingIOError:
                print("REFUSED: the main engine is running. Stop `propaper run` "
                      "first, migrate, then restart it.")
                return
    if store.open_positions() or store.trades(limit=1):
        print("REFUSED: positions or trades exist; manual review required before "
              "rebalancing. Nothing was changed.")
        return
    core, hype = float(store.get("cash_core")), float(store.get("cash_hype"))
    if (core, hype) == (750.0, 0.0):
        print("Already migrated (main = $750).")
        return
    if (core, hype) != (900.0, 100.0):
        print(f"REFUSED: unexpected balances core={core} hype={hype}; manual review "
              "required. Nothing was changed.")
        return
    with store.conn:
        import json as _json
        for key, value in (("cash_core", 750.0), ("cash_hype", 0.0),
                           ("initial_balance", 750.0), ("peak_equity", 750.0),
                           ("day_start_equity", 750.0)):
            store.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, _json.dumps(value)))
        store.conn.execute(
            "INSERT INTO audit_log(ts_ms, level, category, message) VALUES("
            "CAST(strftime('%s','now') AS INTEGER)*1000, 'warning', 'accounting', "
            "'RESTRUCTURE: main portfolio rebalanced $1,000 -> $750; the retired "
            "$100 hype sleeve and $150 of core fund the $250 Extreme Lab "
            "(state/extreme_lab.sqlite). Aggregate stays $1,000.')")
    from .lab.config import LabSettings
    from .lab.store import LabStore
    lab_cfg = LabSettings.from_env()
    LabStore(lab_cfg.db_path, lab_cfg).close()
    print("Migrated: main $750 (peak/day anchors reset), Extreme Lab $250 "
          f"initialized at {lab_cfg.db_path}. Restart `propaper run` and the API.")


def _lab_main(args, cfg: ProSettings) -> None:
    from dataclasses import replace as _replace
    from .lab.config import LabSettings
    from .lab.engine import LabEngine
    from .lab.governor import LabGovernor
    from .lab.store import LabStore
    lab_cfg = _replace(LabSettings.from_env(), main_db_path=cfg.db_path)
    store = LabStore(lab_cfg.db_path, lab_cfg)
    try:
        if args.command == "lab-status":
            from .api import compute_lab
            snapshot = compute_lab(store, lab_cfg)
            snapshot["signals"] = snapshot["signals"][:5]
            snapshot["trades"] = snapshot["trades"][:5]
            snapshot["audit"] = snapshot["audit"][:5]
            snapshot["equity_curve"] = snapshot["equity_curve"][-5:]
            print(json.dumps(snapshot, indent=2))
        elif args.command == "lab-pause":
            store.set("lab_manual_pause", True)
            store.audit("warning", "risk", "Lab manual pause ENABLED")
            print("Lab paused: no new entries; monitoring and exits continue.")
        elif args.command == "lab-resume":
            store.set("lab_manual_pause", False)
            store.audit("info", "risk", "Lab manual pause lifted")
            print("Lab resumed (subject to all rails and the trailing lockout).")
        elif args.command == "lab-reset":
            from .api import compute_lab
            equity = compute_lab(store, lab_cfg)["capital"]["equity_usd"]
            LabGovernor(store, lab_cfg).reset(current_equity=equity, note=args.note)
            print(f"Lockout cleared after review. Peak re-anchored at ${equity:.2f}; "
                  f"new threshold ${equity - lab_cfg.trailing_drawdown_usd:.2f}.")
        elif args.command == "lab-once":
            with single_instance(lab_cfg.db_path):
                print(json.dumps(LabEngine(store, lab_cfg).run_cycle()))
        elif args.command == "lab-run":
            engine = LabEngine(store, lab_cfg)
            print("EXTREME LAB — PAPER ONLY, virtual $250, experimental. "
                  f"Auto-entry: {'ON' if lab_cfg.auto_entry else 'OFF'}. Ctrl+C stops.",
                  flush=True)
            with single_instance(lab_cfg.db_path):
                failures = 0
                while True:
                    try:
                        summary = engine.run_cycle()
                        print(f"{time.strftime('%H:%M:%S')} lab {summary}", flush=True)
                        failures = 0
                        time.sleep(lab_cfg.monitor_interval_seconds)
                    except KeyboardInterrupt:
                        print("Stopped.")
                        break
                    except Exception as exc:
                        failures += 1
                        store.audit("error", "engine",
                                    f"lab cycle failed: {type(exc).__name__}: {exc}")
                        print(f"SAFE ERROR (no entries): {type(exc).__name__}: {exc}",
                              file=sys.stderr, flush=True)
                        time.sleep(min(lab_cfg.monitor_interval_seconds * 2 ** min(failures, 5),
                                       1800))
    finally:
        store.close()


if __name__ == "__main__":
    main()
