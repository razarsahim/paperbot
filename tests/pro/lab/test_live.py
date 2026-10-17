"""Tick-driven valuation core: snapshot/delta book, live valuator, publisher."""
import json
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.governor import LabGovernor
from paperbot_pro.lab.live import LiveStatePublisher, LiveValuator, TickerBook
from paperbot_pro.lab.store import LabStore


# ---------------- TickerBook ----------------

def test_book_merges_deltas_retaining_snapshot_fields():
    book = TickerBook()
    book.apply("BCHUSDT", {"markPrice": "277.5", "lastPrice": "277.4",
                           "bid1Price": "277.3", "ask1Price": "277.6"},
               ts_ms=1000, kind="snapshot")
    book.apply("BCHUSDT", {"lastPrice": "278.0"}, ts_ms=2000, kind="delta")
    t = book.get("BCHUSDT")
    assert t["lastPrice"] == 278.0
    assert t["markPrice"] == 277.5          # retained from snapshot
    assert t["bid1Price"] == 277.3
    assert t["ts_ms"] == 2000


def test_book_rejects_out_of_order_and_tracks_staleness():
    book = TickerBook(clock=lambda: 10.0)
    book.apply("X", {"markPrice": "100"}, ts_ms=5000, kind="snapshot")
    accepted = book.apply("X", {"markPrice": "90"}, ts_ms=4000, kind="delta")
    assert accepted is False
    assert book.get("X")["markPrice"] == 100.0
    book.clock = lambda: 10.0 + 120.0
    assert book.age_seconds("X") == pytest.approx(120.0)
    assert book.get("Y") is None


# ---------------- LiveValuator ----------------

def make_store(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'))
    return LabStore(cfg.db_path, cfg), cfg


def open_fake(store, symbol, side, qty, entry, margin, stop, liq, strategy='trend'):
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
               margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
               entry_fee_usd, planned_risk_usd, opened_ms, signal_bar_ms, rationale,
               exchange, taker_fee) VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,0.1,4.0,0,0,'T','bybit',0.0006)""",
            (strategy, symbol, side, 10.0, qty, entry, margin, margin * 10,
             stop, stop, liq))
        store.conn.execute("UPDATE strategies SET cash_usd = cash_usd - ? WHERE key=?",
                           (margin + 0.1, strategy))


def test_valuation_long_short_signs_and_percent_on_margin(tmp_path):
    store, cfg = make_store(tmp_path)
    open_fake(store, 'AAAUSDT', 'long', qty=1.0, entry=100.0, margin=10.0,
              stop=95.0, liq=90.5, strategy='trend')
    open_fake(store, 'BBBUSDT', 'short', qty=2.0, entry=50.0, margin=10.0,
              stop=55.0, liq=59.5, strategy='breakout')
    valuator = LiveValuator(store, cfg, LabGovernor(store, cfg))
    book = TickerBook()
    book.apply('AAAUSDT', {"markPrice": "103", "bid1Price": "102.9",
                           "ask1Price": "103.1", "lastPrice": "103"}, 1000, "snapshot")
    book.apply('BBBUSDT', {"markPrice": "48", "bid1Price": "47.9",
                           "ask1Price": "48.1", "lastPrice": "48"}, 1000, "snapshot")
    state = valuator.value(book, now_ms=60_000)
    by_symbol = {p['symbol']: p for p in state['positions']}
    long_p = by_symbol['AAAUSDT']
    assert long_p['unrealized_pnl_usd'] == pytest.approx(3.0)       # (103-100)*1
    assert long_p['unrealized_pct_on_margin'] == pytest.approx(30.0)
    assert long_p['stop_distance_pct'] == pytest.approx((103 - 95) / 103 * 100)
    short_p = by_symbol['BBBUSDT']
    assert short_p['unrealized_pnl_usd'] == pytest.approx(4.0)      # (50-48)*2
    assert short_p['unrealized_pct_on_margin'] == pytest.approx(40.0)
    # equity = cash (2*50-10.1-10.1 + 3*50) + margins (20) + uPnL (7)
    expected_equity = (250.0 - 20.2) + 20.0 + 7.0
    assert state['capital']['equity_usd'] == pytest.approx(expected_equity)
    assert state['capital']['unrealized_usd'] == pytest.approx(7.0)


def test_hwm_ratchets_on_ticks_and_breach_flags(tmp_path):
    store, cfg = make_store(tmp_path)
    open_fake(store, 'AAAUSDT', 'long', qty=10.0, entry=100.0, margin=100.0,
              stop=95.0, liq=90.5)
    valuator = LiveValuator(store, cfg, LabGovernor(store, cfg))
    book = TickerBook()
    book.apply('AAAUSDT', {"markPrice": "110", "bid1Price": "109.9",
                           "ask1Price": "110.1", "lastPrice": "110"}, 1000, "snapshot")
    s1 = valuator.value(book, now_ms=1000)           # uPnL +100 -> equity ~349.9
    assert s1['capital']['peak_equity_usd'] > 349.0
    assert store.get('peak_equity') == pytest.approx(s1['capital']['peak_equity_usd'])
    # rapid reversal: equity drops > $50 from the new peak -> breach flagged.
    # The live path needs a CONFIRMING second breached tick to lock (so a
    # single post-gap/transient mark can't nuisance-trip the lockout).
    book.apply('AAAUSDT', {"markPrice": "104", "bid1Price": "103.9",
                           "ask1Price": "104.1"}, 2000, "delta")
    s2 = valuator.value(book, now_ms=2000)
    assert s2['capital']['threshold_usd'] == pytest.approx(
        s1['capital']['peak_equity_usd'] - 50.0)
    assert s2['breached'] is True
    assert store.get('lab_locked') is False           # first breach: pending
    book.apply('AAAUSDT', {"markPrice": "103.5"}, 3000, "delta")
    valuator.value(book, now_ms=3000)                 # confirmed
    assert store.get('lab_locked') is True            # now persisted/locked


def test_missing_mark_keeps_position_unvalued_not_fabricated(tmp_path):
    store, cfg = make_store(tmp_path)
    open_fake(store, 'AAAUSDT', 'long', qty=1.0, entry=100.0, margin=10.0,
              stop=95.0, liq=90.5)
    valuator = LiveValuator(store, cfg, LabGovernor(store, cfg))
    state = valuator.value(TickerBook(), now_ms=1000)
    p = state['positions'][0]
    assert p['mark_price'] is None and p['unrealized_pnl_usd'] is None
    assert state['capital']['complete'] is False       # flagged, not guessed


# ---------------- LiveStatePublisher ----------------

def test_publisher_throttles_and_writes_atomically(tmp_path):
    path = tmp_path / 'live.json'
    clock = {'t': 100.0}
    publisher = LiveStatePublisher(str(path), min_interval_s=0.25,
                                   clock=lambda: clock['t'])
    assert publisher.publish({'n': 1}) is True
    clock['t'] += 0.1
    assert publisher.publish({'n': 2}) is False        # throttled
    clock['t'] += 0.2
    assert publisher.publish({'n': 3}) is True
    data = json.loads(path.read_text())
    assert data['n'] == 3
    assert data['published_at_ms'] > 0
    assert not list(tmp_path.glob('*.tmp*'))           # atomic: no temp litter
