"""Measured benchmark: original minute-loop LabEngine replay vs the CRH fast
engine, same data, same window (Oct 15-19 2026, 16 top-20 instruments,
crash_reversal only). Prints real wall-clock numbers; nothing is estimated.
Run: .venv/bin/python research/crh_lab_benchmark.py [--skip-original]"""
import json
import sys
import time
from pathlib import Path

from paperbot_pro.crh.data import Cache
from paperbot_pro.crh.runner import run_backtest

T0, T1 = 1792022400000, 1792368000000
SYMS = [f"{s}/USDT:USDT" for s in "BTC ETH BNB XRP SOL TRX ZEC HYPE DOGE XMR LINK ADA XLM NEAR BCH LTC".split()]
out = {"window": "2026-10-15T00:00Z..2026-10-19T00:00Z (96h)", "instruments": len(SYMS)}

if "--skip-original" not in sys.argv:
    from paperbot_pro.replay.market import HistoricalMarket, bybit_id, load_symbol
    from paperbot_pro.replay.runner import daily_universe_provider, instruments_from_main_db, make_engine, run
    D = Path("research/replay_2026-09-18_30d/data")
    uni = json.loads(Path("research/crh_continuous_2026-10-15_to_19/universe_daily.json").read_text())
    inst = [i for i in instruments_from_main_db("state/paperbot_pro.sqlite") if i["symbol"] in SYMS]
    s = time.time()
    data = {bybit_id(i["symbol"]): load_symbol(D, bybit_id(i["symbol"]), D / "book_samples", top_n=1) for i in inst}
    load_s = time.time() - s
    market = HistoricalMarket(data, with_orderbook=True)
    provider = daily_universe_provider(market, uni, {i["symbol"]: i for i in inst})
    eng = make_engine(Path("state/crh_runs/_bench_original.sqlite"), market, provider, ["crash_reversal"])
    s = time.time()
    summ = run(eng, market, T0, T1)
    out["original_minute_loop"] = {"data_load_s": round(load_s, 1), "replay_s": round(time.time() - s, 1),
                                   "cycles": summ["cycles"], "trades": len(eng.db.trades(1000)),
                                   "final_cash": round(eng.db.total_cash(), 4)}

params = {"start": "2026-10-15T00:00:00Z", "end": "2026-10-19T00:00:00Z", "symbols": SYMS, "capital": 50, "leverage": 10}
s = time.time()
r = run_backtest(params, cache=Cache(offline=True))
out["fast_engine_cached"] = {"pipeline_s": round(time.time() - s, 2), "stage_times_s": r["summary"]["stage_times_s"],
                             "cycles": r["cycles"], "trades": r["summary"]["trades"],
                             "final_equity": round(r["summary"]["final_equity"], 4)}
s = time.time()
r2 = run_backtest(params, cache=Cache(offline=True))
out["fast_engine_cached_2nd"] = round(time.time() - s, 2)
print(json.dumps(out, indent=1))
Path("research/crh_lab_benchmark.json").write_text(json.dumps(out, indent=1))
