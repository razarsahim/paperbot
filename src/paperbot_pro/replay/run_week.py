"""CLI: run ONE historical replay (an independent sleeve or the combined lab).

    python -m paperbot_pro.replay.run_week --run-id A_breakout --strategies breakout
    python -m paperbot_pro.replay.run_week --run-id B_combined            (all 10)
    python -m paperbot_pro.replay.run_week --run-id B_deployed --no-orderbook

Output: <out>/<run-id>.sqlite (throwaway LabStore) and <run-id>.json.
HISTORICAL BACKTEST ONLY: no live databases are written, no orders exist.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .extract import extract_run
from .market import HistoricalMarket, bybit_id, load_symbol
from .runner import (daily_universe_provider, dump_json, instruments_from_main_db,
                     make_engine, run)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--strategies", nargs="*", default=None,
                    help="independent sleeve(s); omit for the combined 10-strategy lab")
    ap.add_argument("--data", default="research/replay_2026-10-11/data")
    ap.add_argument("--books", default="research/replay_2026-10-11/data/book_samples")
    ap.add_argument("--out", default="research/replay_2026-10-11/runs")
    ap.add_argument("--main-db", default="state/paperbot_pro.sqlite")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--universe-file", default=None,
                    help="JSON {YYYY-MM-DD: [ccxt symbols in rank order]} (daily membership)")
    ap.add_argument("--extra-instruments", default=None,
                    help="JSON list of instrument metadata for symbols absent from the main DB")
    ap.add_argument("--timeframe", choices=("1h", "1m"), default="1h",
                    help="signal candle timeframe (1m = research variant; strategy "
                         "bar counts are unchanged, so lookbacks shrink 60x)")
    ap.add_argument("--variant", default=None,
                    help="replay-only labelled strategy variant (see replay/variants.py)")
    ap.add_argument("--no-orderbook", action="store_true",
                    help="as-deployed wiring: MarketData has no orderbook() hook")
    ap.add_argument("--t0", type=int, default=1791676800000)   # 2026-10-11 00:00 UTC
    ap.add_argument("--t1", type=int, default=1792281600000)   # 2026-10-18 00:00 UTC
    a = ap.parse_args(argv)
    variant = None
    if a.variant:
        from .variants import VARIANTS, apply_variant
        variant = apply_variant(a.variant)
        a.timeframe = variant["timeframe"]
        a.strategies = VARIANTS[a.variant]["strategies"]
        print(f"[{a.run_id}] {variant['label']}", flush=True)

    instruments = instruments_from_main_db(a.main_db, a.symbols)
    if a.extra_instruments:
        instruments += json.loads(Path(a.extra_instruments).read_text())
    universe = json.loads(Path(a.universe_file).read_text()) if a.universe_file else None
    if universe:
        wanted = {s for day in universe.values() for s in day}
        instruments = [i for i in instruments if i["symbol"] in wanted]
    needs_depth = (not a.no_orderbook) and (a.strategies is None
                                            or "orderflow_imbalance" in a.strategies)
    data = {}
    for inst in instruments:
        sym = bybit_id(inst["symbol"])
        data[sym] = load_symbol(Path(a.data), sym, Path(a.books),
                                top_n=10 if needs_depth else 1)
    market = HistoricalMarket(data, with_orderbook=not a.no_orderbook)
    if variant:
        market.min_candle_limit = variant["min_candle_limit"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / f"{a.run_id}.sqlite"
    provider = (daily_universe_provider(market, universe, {i["symbol"]: i for i in instruments})
                if universe else instruments)
    engine = make_engine(db_path, market, provider, a.strategies, timeframe=a.timeframe)
    print(f"[{a.run_id}] {len(instruments)} instruments, strategies="
          f"{a.strategies or 'ALL 10'}, orderbook={'off' if a.no_orderbook else 'archived'}",
          flush=True)
    summary = run(engine, market, a.t0, a.t1, progress_every=1440)
    result = extract_run(engine.db, summary, run_id=a.run_id,
                         kind="A_independent" if a.strategies else "B_combined",
                         strategies=a.strategies, with_orderbook=not a.no_orderbook,
                         t0=a.t0, t1=a.t1, instruments=instruments)
    result["timeframe"] = a.timeframe
    if variant:
        result["variant"] = variant
        result["label"] = "HISTORICAL BACKTEST - " + variant["label"]
    dump_json(out / f"{a.run_id}.json", result)
    print(f"[{a.run_id}] done in {summary['elapsed_s']}s: "
          f"{len(result['trades'])} trades, final equity "
          f"{result['final_equity_usd']:.2f}", flush=True)


if __name__ == "__main__":
    main()
