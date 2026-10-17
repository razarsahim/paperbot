"""Bybit public WS message handling (pure) and tick-driven engine enforcement
(offline: ticks injected, no network)."""
import json
import pytest
from dataclasses import replace
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.engine import LabEngine
from paperbot_pro.lab.feed import parse_message
from paperbot_pro.lab.store import LabStore


# ---------------- parse_message ----------------

def test_parse_ticker_snapshot_and_delta():
    raw = json.dumps({"topic": "tickers.BCHUSDT", "type": "snapshot",
                      "ts": 1792190000000,
                      "data": {"symbol": "BCHUSDT", "markPrice": "277.5",
                               "lastPrice": "277.4", "bid1Price": "277.3",
                               "ask1Price": "277.6"}})
    parsed = parse_message(raw)
    assert parsed == ("BCHUSDT", {"symbol": "BCHUSDT", "markPrice": "277.5",
                                  "lastPrice": "277.4", "bid1Price": "277.3",
                                  "ask1Price": "277.6"}, 1792190000000, "snapshot")
    delta = json.dumps({"topic": "tickers.BCHUSDT", "type": "delta",
                        "ts": 1792190001000, "data": {"lastPrice": "278"}})
    assert parse_message(delta)[3] == "delta"


def test_parse_ignores_pong_subscriptions_and_garbage():
    assert parse_message(json.dumps({"op": "pong"})) is None
    assert parse_message(json.dumps({"success": True, "op": "subscribe"})) is None
    assert parse_message("not json {") is None
    assert parse_message(json.dumps({"topic": "orderbook.1.BTCUSDT",
                                     "ts": 1, "data": {}})) is None


# ---------------- tick-driven enforcement ----------------

INSTRUMENT = {'symbol': 'BCH/USDT:USDT', 'exchange': 'bybit', 'taker_fee': 0.0006,
              'maint_margin_rate': 0.005, 'tick_size': 0.1, 'lot_size': 0.001}


def engine_with_position(tmp_path):
    cfg = replace(LabSettings(), db_path=str(tmp_path / 'lab.sqlite'),
                  live_state_path=str(tmp_path / 'live.json'))
    store = LabStore(cfg.db_path, cfg)
    engine = LabEngine(store, cfg, market=None, instruments_provider=lambda: [INSTRUMENT])
    with store.conn:
        store.conn.execute(
            """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
               margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
               entry_fee_usd, planned_risk_usd, opened_ms, signal_bar_ms, rationale,
               exchange, taker_fee)
               VALUES('trend','BCH/USDT:USDT','long',10,0.8,277.45,22.2,222.0,
                      271.92,271.92,NULL,251.56,0.13,4.98,0,0,'T','bybit',0.0006)""")
        store.conn.execute(
            "UPDATE strategies SET cash_usd = cash_usd - 22.33 WHERE key='trend'")
    clock = {'t': 0.0}
    engine.start_live_components(publisher_clock=lambda: clock['t'])
    engine._test_clock = clock       # tests advance this past the throttle
    return engine, store, cfg


def tick(engine, mark, bid=None, ask=None, ts=None):
    engine._test_clock['t'] += 0.3   # advance past the publish throttle
    engine.on_live_ticker('BCHUSDT',
                          {"markPrice": str(mark),
                           "lastPrice": str(mark),
                           "bid1Price": str(bid if bid is not None else mark - 0.05),
                           "ask1Price": str(ask if ask is not None else mark + 0.05)},
                          ts if ts is not None else tick.ts, "snapshot")
    tick.ts += 1000
tick.ts = 1_792_000_000_000


def test_rapid_ticks_update_state_file_without_sqlite_trades(tmp_path):
    engine, store, cfg = engine_with_position(tmp_path)
    for i, mark in enumerate((277.5, 277.8, 278.2, 279.0, 278.6)):
        tick(engine, mark)
    state = json.loads(open(cfg.live_state_path).read())
    assert state['positions'][0]['mark_price'] == 278.6  # latest tick landed
    assert state['capital']['equity_usd'] > 250.0     # in profit
    assert store.trades() == []                        # no exits, no spurious writes
    assert store.position('BCH/USDT:USDT') is not None


def test_tick_through_stop_closes_once_no_duplicates(tmp_path):
    engine, store, cfg = engine_with_position(tmp_path)
    tick(engine, 275.0)
    tick(engine, 271.5, bid=271.4)     # bid below stop 271.92 -> exit
    tick(engine, 270.0, bid=269.9)     # position already gone: no duplicate
    tick(engine, 269.0, bid=268.9)
    trades = store.trades()
    assert len(trades) == 1
    assert 'STOP' in trades[0]['exit_reason']
    assert store.position('BCH/USDT:USDT') is None
    # cash moved exactly once, by the reported pnl
    ledger = store.strategy_ledger()['trend']
    assert ledger['cash_usd'] == pytest.approx(50.0 - 22.33 + 22.2 + trades[0]['net_pnl_usd'] + 0.13)


def test_tick_breach_locks_and_emergency_exits_via_book(tmp_path):
    engine, store, cfg = engine_with_position(tmp_path)
    store.set('peak_equity', 550.0)    # prior simulated gains: threshold 500
    tick(engine, 277.0)                # equity ~499.5 < 500 -> breach FLAGGED (pending)
    assert store.get('lab_locked') is False            # one tick: not yet locked
    tick(engine, 276.5)                # confirming second breached tick -> lock
    assert store.get('lab_locked') is True
    assert store.position('BCH/USDT:USDT') is None
    assert store.trades()[0]['exit_reason'].startswith('EMERGENCY')
    state = json.loads(open(cfg.live_state_path).read())
    assert state['locked'] is True


def test_out_of_order_tick_ignored_for_enforcement(tmp_path):
    engine, store, cfg = engine_with_position(tmp_path)
    tick(engine, 277.0, ts=2_000_000_000_000)
    engine.on_live_ticker('BCHUSDT', {"markPrice": "100", "bid1Price": "99"},
                          1_999_999_000_000, "delta")   # stale, out of order
    assert store.position('BCH/USDT:USDT') is not None  # not stopped out on it
    assert store.trades() == []
