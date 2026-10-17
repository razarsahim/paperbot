"""Regression: a trailing-drawdown breach computed from a mark that arrived
after a data gap (post-gap catch-up tick) must NOT irreversibly lock the lab
on the live path — it ratchets the peak and reports the breach, but the lock
is confirmed only by a fresh, non-gapped valuation (or the validated cycle).
This reproduces the HYPE stale-quote nuisance lock from 2026-10-17."""
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.governor import LabGovernor
from paperbot_pro.lab.live import LiveValuator, TickerBook
from paperbot_pro.lab.store import LabStore


def make(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'))
    store = LabStore(cfg.db_path, cfg)
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
               margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
               entry_fee_usd, planned_risk_usd, opened_ms, signal_bar_ms, rationale,
               exchange, taker_fee) VALUES('trend','HYPE/USDT:USDT','short',10,2.0,80,
               16,160,82,82,NULL,84,0.1,4.0,0,0,'T','bybit',0.0006)""")
        store.conn.execute("UPDATE strategies SET cash_usd=cash_usd-16.1 WHERE key='trend'")
    return LiveValuator(store, cfg, LabGovernor(store, cfg)), store, cfg


def test_post_gap_tick_does_not_lock_but_fresh_confirmation_does(tmp_path):
    valuator, store, cfg = make(tmp_path)
    clock = {'t': 1000.0}
    book = TickerBook(clock=lambda: clock['t'])
    # healthy mark: short at 80, mark 79 -> small profit; peak ratchets
    book.apply('HYPEUSDT', {"markPrice": "79", "bid1Price": "78.95",
                            "ask1Price": "79.05", "lastPrice": "79"}, 1000, "snapshot")
    s = valuator.value(book, now_ms=1000)
    peak = s['capital']['peak_equity_usd']
    assert not s['breached'] and store.get('lab_locked') is False

    # 30-minute DATA GAP, then a catch-up tick with a big adverse jump
    clock['t'] += 1800.0
    book.apply('HYPEUSDT', {"markPrice": "120", "bid1Price": "119.9",
                            "ask1Price": "120.1"}, 1000 + 1800_000, "delta")
    s = valuator.value(book, now_ms=1000 + 1800_000)
    assert s['breached'] is True                 # the drawdown IS reported
    assert store.get('lab_locked') is False      # but NOT locked on a post-gap tick

    # a second, normal-cadence tick still below threshold -> confirmed -> lock
    clock['t'] += 2.0
    book.apply('HYPEUSDT', {"markPrice": "121"}, 1000 + 1802_000, "delta")
    s = valuator.value(book, now_ms=1000 + 1802_000)
    assert store.get('lab_locked') is True


def test_transient_single_tick_dip_that_reverts_never_locks(tmp_path):
    valuator, store, cfg = make(tmp_path)
    clock = {'t': 1000.0}
    book = TickerBook(clock=lambda: clock['t'])
    book.apply('HYPEUSDT', {"markPrice": "79", "bid1Price": "78.95",
                            "ask1Price": "79.05"}, 1000, "snapshot")
    valuator.value(book, now_ms=1000)
    clock['t'] += 2.0
    book.apply('HYPEUSDT', {"markPrice": "120"}, 1002_000, "delta")   # fresh spike
    valuator.value(book, now_ms=1002_000)
    assert store.get('lab_locked') is False      # first breach: pending, not locked
    clock['t'] += 2.0
    book.apply('HYPEUSDT', {"markPrice": "79"}, 1004_000, "delta")    # reverts
    s = valuator.value(book, now_ms=1004_000)
    assert not s['breached'] and store.get('lab_locked') is False     # streak cleared


def test_validated_cycle_still_locks_immediately(tmp_path):
    """The governor's direct update_hwm (used by the slow REST cycle) keeps
    its immediate single-call lock — that path uses validated quotes."""
    valuator, store, cfg = make(tmp_path)
    gov = LabGovernor(store, cfg)
    gov.update_hwm(300.0, now_ms=1000)
    s = gov.update_hwm(240.0, now_ms=2000)       # 60 below peak
    assert s['breached'] and store.get('lab_locked') is True
