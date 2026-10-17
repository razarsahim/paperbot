"""Unified engine: one LabEngine runs all 10 strategies (both signal modules),
applies per-cohort risk budgets and the research-cohort $30 floor lock, stamps
correlation clusters, and iterates only ledger-present strategies so it is safe
before the migration seeds the research sleeves. PAPER ONLY."""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.store import LabStore

H = 3_600_000
SYMBOL = "TST/USDT:USDT"
INSTRUMENT = {"symbol": SYMBOL, "exchange": "fake", "taker_fee": 0.0006,
              "maint_margin_rate": 0.005, "tick_size": 0.1, "lot_size": 0.001}


def flat_rows(n=120, base=100.0):
    return [[i * H, base, base + 0.5, base - 0.5, base, 100.0] for i in range(n)]


class FakeMarket:
    def __init__(self, rows, last):
        self.rows, self.last = rows, last

    def candles(self, e, s, tf, limit):
        return self.rows, 0.0

    def ticker(self, e, s):
        return {"bid": self.last - 0.05, "ask": self.last + 0.05, "last": self.last}, 0.0

    def funding_rate(self, e, s):
        return {"fundingRate": 0.0001}, 0.0


def make(tmp_path, auto_entry=True):
    cfg = replace(LabSettings(), db_path=str(tmp_path / "lab.sqlite"), auto_entry=auto_entry)
    store = LabStore(cfg.db_path, cfg)
    rows = flat_rows()
    engine = LabEngine(store, cfg, market=FakeMarket(rows, rows[-1][4]),
                       instruments_provider=lambda: [INSTRUMENT])
    return engine, store, cfg


def test_both_cohorts_are_evaluated_each_scan(tmp_path):
    engine, store, cfg = make(tmp_path)
    engine.run_cycle(now_ms=flat_rows()[-1][0] + H + 1000)
    opps = store.get("lab_opportunities", {})[SYMBOL]
    # all ten strategies get an opportunity verdict -> both modules ran and merged
    assert set(opps) == {s.key for s in __import__(
        "paperbot_pro.lab.config", fromlist=["STRATEGIES"]).STRATEGIES}
    assert len(opps) == 10


def test_iterates_only_ledger_present_strategies(tmp_path):
    """Before the migration the DB holds only the 5 extreme sleeves. The engine
    must run them without KeyError on the absent research keys."""
    engine, store, cfg = make(tmp_path)
    with store.conn:                       # simulate a pre-migration 5-sleeve DB
        store.conn.execute("DELETE FROM strategies WHERE key IN "
                           "('regime_trend','volatility_breakout','trend_pullback',"
                           "'range_reversion','orderflow_imbalance')")
    summary = engine.run_cycle(now_ms=flat_rows()[-1][0] + H + 1000)  # must not raise
    # the entry loop skips strategies absent from the ledger, so no research
    # sleeve can hold a position pre-migration
    assert all(p["strategy"] in {"breakout", "launch_sniper", "squeeze", "trend",
                                 "crash_reversal"} for p in store.open_positions())
    assert isinstance(summary, dict)  # cycle completed cleanly


def test_open_from_plan_stamps_corr_cluster(tmp_path):
    engine, store, cfg = make(tmp_path)

    class P:  # minimal plan stand-in
        side = "long"; leverage = 10.0; qty = 1.0; entry_price = 100.0
        margin_usd = 20.0; notional_usd = 200.0; stop = 95.0; target = None
        liq_price_est = 90.0; entry_fee_usd = 0.05; planned_risk_usd = 1.0
    engine.open_from_plan(INSTRUMENT, P(), "regime_trend", "regime filter", {},
                          bar_ts=0, now_ms=1, cluster="TST")
    assert store.position(SYMBOL)["corr_cluster"] == "TST"


def test_research_sleeve_floor_lock_exits_and_locks(tmp_path):
    """A research sleeve whose net equity falls to/below the $30 floor is locked
    and its position protectively exited in the same cycle."""
    engine, store, cfg = make(tmp_path)
    with store.conn:
        store.conn.execute("UPDATE strategies SET cash_usd=10 WHERE key='regime_trend'")
        store.conn.execute(
            "INSERT INTO positions(strategy,symbol,side,leverage,qty,entry_price,margin_usd,"
            "notional_usd,stop,initial_stop,target,liq_price_est,entry_fee_usd,planned_risk_usd,"
            "mfe_price,mae_price,opened_ms,signal_bar_ms,rationale,exchange,taker_fee,corr_cluster) "
            "VALUES('regime_trend',?,'long',10,0.19,100,19,190,95,95,NULL,90,0.05,1,100,100,0,0,"
            "'t','fake',0.0006,'TST')", (SYMBOL,))
    # net equity for regime_trend = 10 cash + 19 margin + ~0 uPnL = 29 <= 30 floor
    summary = engine.run_cycle(now_ms=flat_rows()[-1][0] + H + 1000)
    assert store.position(SYMBOL) is None                      # protectively exited
    assert store.strategy_ledger()["regime_trend"]["locked"] == 1
