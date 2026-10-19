"""Historical-replay harness: look-ahead safety, stop/liquidation sequencing on
ambiguous bars, point-in-time order books and isolated accounting."""
import io
import json
import zipfile

import pytest

from paperbot_pro.perp import check_exit
from paperbot_pro.reconcile import reconcile_lab
from paperbot_pro.replay.market import HistoricalMarket, SymbolData
from paperbot_pro.replay.orderbook import sample_day
from paperbot_pro.replay.runner import emulate_ticks, make_engine, run

H = 3_600_000
M = 60_000
T0 = 100 * H
SYM = "TST/USDT:USDT"
INST = {"symbol": SYM, "exchange": "bybit", "taker_fee": 0.0006,
        "maint_margin_rate": 0.005, "tick_size": 0.01, "lot_size": 0.001}


def flat_data(n_hours=100, price=100.0, minutes_after=6 * 60, book=True):
    k1h = [[i * H, price, price + 0.5, price - 0.5, price, 100.0, 0.0]
           for i in range(n_hours)]
    k1m = [[T0 - H + j * M, price, price + 0.05, price - 0.05, price, 1.0, 0.0]
           for j in range(60 + minutes_after)]
    # add the in-window 1h bars too (complete series)
    for i in range(minutes_after // 60):
        k1h.append([T0 + i * H, price, price + 0.5, price - 0.5, price, 100.0, 0.0])
    books = {}
    if book:
        for j in range(-60, minutes_after):
            t = T0 + j * M + 5_000
            books[t] = [t, t - 100, [[price - 0.01, 5.0]], [[price + 0.01, 5.0]]]
    funding = [{"ts": T0 - 8 * H, "rate": 0.0001}, {"ts": T0 + 8 * H, "rate": 0.05}]
    return {"TSTUSDT": SymbolData(k1h, k1m, funding, books)}


def test_candles_never_include_unfinished_or_future_bars():
    mkt = HistoricalMarket(flat_data())
    mkt.set_now(T0 + 2 * H + 30 * M + 5_000)
    raw, _ = mkt.candles("bybit", SYM, "1h", 200)
    closed = [r for r in raw if r[0] + H <= mkt.now_ms]
    assert closed[-1][0] == T0 + H                  # last complete hour
    forming = raw[-1]
    assert forming[0] == T0 + 2 * H                 # rebuilt from 30 closed minutes
    assert mkt.max_ts_served <= mkt.now_ms
    assert len(raw) == 103                          # 102 closed + forming (all that exist)


def test_served_future_data_raises():
    mkt = HistoricalMarket(flat_data())
    mkt.set_now(T0)
    with pytest.raises(AssertionError):
        mkt._served(T0 + 1)


def test_funding_is_last_settled_rate_only():
    mkt = HistoricalMarket(flat_data())
    mkt.set_now(T0 + 8 * H - 1)
    f, _ = mkt.funding_rate("bybit", SYM)
    assert f["fundingRate"] == 0.0001               # the 0.05 print is in the future


def test_orderbook_is_optional_hook():
    assert getattr(HistoricalMarket(flat_data(), with_orderbook=False),
                   "orderbook", None) is None
    mkt = HistoricalMarket(flat_data(), with_orderbook=True)
    mkt.set_now(T0 + 5_000)
    book, age = mkt.orderbook("bybit", SYM)
    assert book["bids"][0][0] < book["asks"][0][0] and age == pytest.approx(0.1)


def _engine(tmp_path, data, strategies=("trend",)):
    mkt = HistoricalMarket(data)
    eng = make_engine(tmp_path / "r.sqlite", mkt, [INST],
                      None if strategies is None else list(strategies))
    return eng, mkt


def _open(eng, side, entry, stop, liq, qty=1.0):
    with eng.db.conn:
        eng.db.conn.execute(
            """INSERT INTO positions(strategy, symbol, side, leverage, qty, entry_price,
               margin_usd, notional_usd, stop, initial_stop, target, liq_price_est,
               entry_fee_usd, funding_paid_usd, planned_risk_usd, mfe_price, mae_price,
               opened_ms, signal_bar_ms, rationale, exchange, taker_fee, corr_cluster)
               VALUES('trend',?,?,10,?,?,?,?,?,?,NULL,?,0.06,0,2,?,?,?,?,'t','bybit',0.0006,'')""",
            (SYM, side, qty, entry, entry * qty / 10, entry * qty, stop, stop, liq,
             entry, entry, T0 - H, T0 - 2 * H))
        eng.db.conn.execute("UPDATE strategies SET cash_usd = cash_usd - ?",
                            (entry * qty / 10 + 0.06,))


def _set_bar(data, minute, o, h, l, c):
    sd = data["TSTUSDT"]
    bar = [minute, o, h, l, c, 1.0, 0.0]
    sd.k1m_by_ts[minute] = bar


@pytest.mark.parametrize("side,o,h,l,expect_reason,expect_obs", [
    ("long", 100, 100.2, 97.5, "STOP", 98.0),          # crossed: fills at stop
    ("long", 97.0, 97.2, 96.5, "STOP (gap)", 97.0),    # opened through stop
    ("long", 99.0, 99.5, 89.0, "LIQUIDATION", None),   # reached liq in same bar
    ("short", 100, 102.5, 99.8, "STOP", 102.0),
    ("short", 103, 103.5, 102.8, "STOP (gap)", 103.0),
    ("short", 101, 111.0, 100.5, "LIQUIDATION", None),
])
def test_ambiguous_bars_take_conservative_exit(tmp_path, side, o, h, l,
                                               expect_reason, expect_obs):
    data = flat_data(book=False)
    eng, mkt = _engine(tmp_path, data)
    stop, liq = (98.0, 90.5) if side == "long" else (102.0, 109.5)
    _open(eng, side, 100.0, stop, liq)
    _set_bar(data, T0, o, h, l, o)
    mkt.set_now(T0 + M + 5_000)
    assert emulate_ticks(eng, mkt, T0) == 1
    trade = eng.db.trades()[0]
    assert trade["exit_reason"] == expect_reason
    if expect_obs is not None:
        sign = 1 if side == "long" else -1
        assert trade["exit_price"] == pytest.approx(expect_obs * (1 - sign * eng.cfg.slippage_rate))
    assert reconcile_lab(eng.db, eng.cfg)["discrepancies"] == []


def test_untouched_stop_holds(tmp_path):
    data = flat_data(book=False)
    eng, mkt = _engine(tmp_path, data)
    _open(eng, "long", 100.0, 98.0, 90.5)
    _set_bar(data, T0, 100, 101, 98.01, 100.5)
    mkt.set_now(T0 + M + 5_000)
    assert emulate_ticks(eng, mkt, T0) == 0 and len(eng.db.open_positions()) == 1


def test_position_opened_after_bar_is_not_checked_against_it(tmp_path):
    data = flat_data(book=False)
    eng, mkt = _engine(tmp_path, data)
    _open(eng, "long", 100.0, 98.0, 90.5)
    eng.db.conn.execute("UPDATE positions SET opened_ms=?", (T0 + M + 5_000,))
    _set_bar(data, T0, 100, 100, 50, 60)
    mkt.set_now(T0 + 2 * M + 5_000)
    assert emulate_ticks(eng, mkt, T0) == 0


def test_independent_sleeve_has_only_its_ledger_and_capital(tmp_path):
    eng, _ = _engine(tmp_path, flat_data(), strategies=("squeeze",))
    assert list(eng.db.strategy_ledger()) == ["squeeze"]
    assert eng.db.total_cash() == 50.0 and eng.db.get("peak_equity") == 50.0
    eng2, _ = _engine(tmp_path, flat_data(), strategies=None)
    assert len(eng2.db.strategy_ledger()) == 10 and eng2.db.total_cash() == 500.0


def test_flat_market_full_run_is_quiet_and_reconciles(tmp_path):
    data = flat_data(minutes_after=3 * 60)
    mkt = HistoricalMarket(data)
    eng = make_engine(tmp_path / "r.sqlite", mkt, [INST], None)
    out = run(eng, mkt, T0, T0 + 3 * H)
    assert out["cycles"] == 180
    assert out["max_data_ts_served"] <= out["final_now"]
    assert eng.db.total_cash() == pytest.approx(500.0)
    assert reconcile_lab(eng.db, eng.cfg)["discrepancies"] == []


def test_orderbook_sampler_is_point_in_time(tmp_path):
    day = 1_000 * 86_400_000
    lines = [
        {"type": "snapshot", "ts": day + 1_000,
         "data": {"b": [["10.0", "1"]], "a": [["10.2", "1"]]}},
        {"type": "delta", "ts": day + 5_000,               # exactly at sample time: included
         "data": {"b": [["10.1", "2"]], "a": []}},
        {"type": "delta", "ts": day + 5_001,               # after sample: excluded
         "data": {"b": [["10.15", "9"]], "a": [["10.2", "0"], ["10.3", "1"]]}},
    ]
    z = tmp_path / "d_TSTUSDT_ob200.data.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("d.data", "\n".join(json.dumps(x) for x in lines))
    out = sample_day(z, day)
    t, last_ts, bids, asks = out["samples"][0]
    assert t == day + 5_000 and last_ts == day + 5_000
    assert bids[0] == [10.1, 2.0] and asks[0] == [10.2, 1.0]
    t2, _, bids2, asks2 = out["samples"][1]
    assert bids2[0] == [10.15, 9.0] and asks2[0] == [10.3, 1.0]   # removal applied
    assert out["meta"]["crossed_samples"] == 0


def test_daily_universe_follows_simulated_day_and_skips_unknown_metadata():
    from paperbot_pro.replay.runner import daily_universe_provider
    day = 86_400_000
    mkt = HistoricalMarket({})
    meta = {"A/USDT:USDT": {"symbol": "A/USDT:USDT"}, "B/USDT:USDT": {"symbol": "B/USDT:USDT"}}
    uni = {"1970-01-01": ["A/USDT:USDT", "NOPE/USDT:USDT"], "1970-01-02": ["B/USDT:USDT"]}
    prov = daily_universe_provider(mkt, uni, meta)
    mkt.set_now(day - 1)
    assert [i["symbol"] for i in prov()] == ["A/USDT:USDT"]
    mkt.set_now(day)
    assert [i["symbol"] for i in prov()] == ["B/USDT:USDT"]
