"""Trade-for-trade equivalence of the fast CRH engine with the ORIGINAL
minute-by-minute LabEngine replay on real archived data (Oct 15-16 2026,
ZEC + NEAR trades). Skipped when the local 1m/book data is absent."""
import json
from pathlib import Path

import numpy as np
import pytest

from paperbot_pro.perp import ContractSpec
from paperbot_pro.crh.config import CRHConfig
from paperbot_pro.crh.engine import CRHReplay, FrameProvider, SymbolFrame

DATA = Path("research/replay_2026-09-18_30d/data")
UNI = Path("research/crh_continuous_2026-10-15_to_19/universe_daily.json")
T0 = 1792022400000                     # 2026-10-15 00:00 UTC
T1 = T0 + 40 * 3_600_000               # 2026-10-16 16:00 UTC (both trades exit 15:23)
pytestmark = pytest.mark.skipif(not (DATA / "kline_1m" / "ZECUSDT.json").exists()
                                or not UNI.exists(), reason="local archived data not present")


class ResearchProvider(FrameProvider):
    """Frames straight from the research JSON + book samples (the exact
    inputs the original harness used)."""
    def __init__(self, instruments, universe):
        from paperbot_pro.replay.market import load_symbol
        self.inst, self.uni, self.cache = instruments, universe, {}
        self.load_symbol = load_symbol

    def universe(self, day):
        return self.uni[day]

    def frame(self, symbol):
        if symbol in self.cache:
            return self.cache[symbol]
        bid = symbol.split("/")[0] + "USDT"
        sd = self.load_symbol(DATA, bid, DATA / "book_samples", top_n=1)
        i = self.inst[symbol]
        spec = ContractSpec(symbol, i["taker_fee"], i["maint_margin_rate"], i["tick_size"], i["lot_size"])
        h1 = np.array([r[:6] for r in sd.k1h], dtype=float)
        m1 = np.array([r[:5] for r in sd.k1m], dtype=float)
        books = sd.books

        def q(t):
            s = books.get(t)
            return None if s is None else (s[2][0][0], s[3][0][0], s[1])
        fr = SymbolFrame(symbol, spec, h1[:, 0].astype(np.int64), h1[:, 1:6],
                         m1[:, 0].astype(np.int64), m1[:, 1:5],
                         [(f["ts"], f["rate"]) for f in sd.funding], q)
        self.cache[symbol] = fr
        return fr


@pytest.fixture(scope="module")
def original():
    from paperbot_pro.replay.market import HistoricalMarket, bybit_id, load_symbol
    from paperbot_pro.replay.runner import (daily_universe_provider, instruments_from_main_db,
                                            make_engine, run)
    from paperbot_pro.replay.extract import extract_run
    universe = json.loads(UNI.read_text())
    instruments = instruments_from_main_db("state/paperbot_pro.sqlite")
    wanted = {s for d in universe.values() for s in d}
    instruments = [i for i in instruments if i["symbol"] in wanted]
    data = {bybit_id(i["symbol"]): load_symbol(DATA, bybit_id(i["symbol"]), DATA / "book_samples", top_n=1)
            for i in instruments}
    market = HistoricalMarket(data, with_orderbook=True)
    tmp = Path("state/crh_runs"); tmp.mkdir(parents=True, exist_ok=True)
    provider = daily_universe_provider(market, universe, {i["symbol"]: i for i in instruments})
    eng = make_engine(tmp / "_equiv_original.sqlite", market, provider, ["crash_reversal"])
    summary = run(eng, market, T0, T1)
    res = extract_run(eng.db, summary, "orig", "A_independent", ["crash_reversal"], True, T0, T1, instruments)
    return res, {i["symbol"]: i for i in instruments}, universe


def test_fast_engine_reproduces_original_trades_signals_and_equity(original):
    res, instruments, universe = original
    fast = CRHReplay(CRHConfig(), ResearchProvider(instruments, universe), T0, T1).run()
    keys = ("symbol", "side", "qty", "entry_price", "exit_price", "stop_initial", "stop_final",
            "margin_usd", "notional_usd", "entry_fee_usd", "exit_fee_usd", "funding_usd",
            "net_pnl_usd", "entry_ms", "exit_ms", "exit_reason")
    assert len(res["trades"]) == 2
    for a, b in zip(res["trades"], fast["trades"]):
        for k in keys:
            assert a[k] == pytest.approx(b[k], rel=1e-12, abs=1e-9), k
    assert [(s["ts_ms"], s["symbol"], s["approved"], s["reject_reason"]) for s in res["signals"]] == \
           [(s["ts_ms"], s["symbol"], s["approved"], s["reject_reason"]) for s in fast["signals"]]
    assert fast["final_cash"] == pytest.approx(res["totals"]["final_equity_usd"], abs=1e-9)
    # equity path: identical at every minute the original recorded while positions were open
    orig_curve = {p[0]: p[1] for p in res["equity_curve_min"]}
    fast_curve = {p[0]: p[1] for p in fast["equity_curve"]}
    common = sorted(set(orig_curve) & set(fast_curve))
    assert len(common) > 1000
    assert max(abs(orig_curve[t] - fast_curve[t]) for t in common) < 1e-9
    assert fast["cycles"] < res["cycles"]
