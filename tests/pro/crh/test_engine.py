"""CRH fast engine: signal parity with the deployed evaluator, look-ahead,
candle boundaries, warm-up, trailing, liquidation, funding, costs, locks,
multiday carry and accounting — on synthetic data."""
import numpy as np
import pytest

from paperbot.models import Candle
from paperbot.strategy import atr
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.strategies import _crash_reversal
from paperbot_pro.perp import ContractSpec
from paperbot_pro.crh.config import CRHConfig, scaled_baseline
from paperbot_pro.crh.engine import (CRHReplay, FrameProvider, SymbolFrame, crh_signal,
                                      near_misses, prescan)

H, M = 3_600_000, 60_000
T0 = 1_000 * 86_400_000          # a UTC midnight
SYM = "TST/USDT:USDT"
SPEC = ContractSpec(SYM, 0.0006, 0.005, 0.01, 0.001)


def make_frame(hours, price_fn, crash_at=None, hammer=True, quotes=True, spread=0.0002,
               funding=None, m1_override=None):
    """Synthetic 1h + 1m series starting 300h before T0. price_fn(hour_index)->close."""
    n = 300 + hours
    h_ts = np.array([T0 - 300 * H + i * H for i in range(n)], dtype=np.int64)
    closes = np.array([price_fn(i) for i in range(n)], dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.001
    lows = np.minimum(opens, closes) * 0.999
    if crash_at is not None:                       # make bar crash_at a -9% 24h drop + hammer
        i = 300 + crash_at
        closes[i] = closes[i - 24] * 0.91
        opens[i] = closes[i] * 0.995 if hammer else closes[i] * 1.005
        lows[i] = min(opens[i], closes[i]) * 0.98   # long lower wick
        highs[i] = max(opens[i], closes[i]) * 1.001
    sig = np.column_stack([opens, highs, lows, closes, np.full(n, 100.0)])
    # 1m bars: flat inside each hour at the hour's close path (linear o->c)
    m_ts, m_rows = [], []
    for i in range(n):
        for k in range(60):
            p0 = opens[i] + (closes[i] - opens[i]) * k / 60
            p1 = opens[i] + (closes[i] - opens[i]) * (k + 1) / 60
            m_ts.append(h_ts[i] + k * M)
            m_rows.append([p0, max(p0, p1), min(p0, p1), p1])
    m_ts = np.array(m_ts, dtype=np.int64)
    m_rows = np.array(m_rows, dtype=float)
    if m1_override:
        for ts, row in m1_override.items():
            m_rows[np.searchsorted(m_ts, ts)] = row
    idx = {int(t): i for i, t in enumerate(m_ts)}

    def q(t):
        if not quotes:
            return None
        i = idx.get(t - t % M)
        if i is None:
            return None
        mid = m_rows[i, 0]
        return mid * (1 - spread / 2), mid * (1 + spread / 2), t - 100
    return SymbolFrame(SYM, SPEC, h_ts, sig, m_ts, m_rows, funding or [(T0 - 8 * H, 0.0001)], q)


class P(FrameProvider):
    def __init__(self, frames):
        self.frames = frames

    def universe(self, day):
        return list(self.frames)

    def frame(self, s):
        return self.frames.get(s)


def run(frame, cfg=None, hours=48):
    cfg = cfg or CRHConfig()
    eng = CRHReplay(cfg, P({SYM: frame}), T0, T0 + hours * H)
    return eng.run()


# ------------------------------------------------------------------ signals
def test_crh_signal_matches_deployed_evaluator_on_random_data():
    rng = np.random.default_rng(1)
    cfg = CRHConfig()
    for _ in range(300):
        n = int(rng.integers(26, 199))
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
        bars = []
        for i, c in enumerate(closes):
            o = closes[i - 1] if i else c
            lo = min(o, c) * (1 - abs(rng.normal(0, 0.03)))
            hi = max(o, c) * (1 + abs(rng.normal(0, 0.01)))
            bars.append(Candle(T0 + i * H, float(o), float(hi), float(lo), float(c), 1.0))
        vol = atr(bars, 14)[-1] or 1.0
        ref = _crash_reversal(bars, LabSettings(), {}, vol)
        act, reason, ind = crh_signal(bars, cfg, vol)
        assert act == ref.action and ind == ref.indicators
        assert reason.replace("24-bar", "24h") == ref.reason.replace("24h", "24h")


def test_prescan_finds_only_closed_in_window_candidates():
    fr = make_frame(48, lambda i: 100.0, crash_at=5)
    cfg = CRHConfig()
    c = prescan(fr, cfg, T0, T0 + 48 * H)
    assert [x["close_ts"] for x in c] == [T0 + 6 * H]        # bar 5 closes at hour 6
    assert c[0]["drop_pct"] == pytest.approx(-9.0) and c[0]["hammer"]
    assert prescan(fr, cfg, T0 + 7 * H, T0 + 48 * H) == []   # closed before the window
    assert prescan(fr, cfg, T0, T0 + 6 * H) == []           # closes exactly at end (excl.)


def test_near_miss_is_drop_without_hammer():
    fr = make_frame(48, lambda i: 100.0, crash_at=5, hammer=False)
    assert prescan(fr, CRHConfig(), T0, T0 + 48 * H) == []
    nm = near_misses(fr, CRHConfig(), T0, T0 + 48 * H)
    assert len(nm) == 1 and nm[0]["drop_pct"] == pytest.approx(-9.0)


# ----------------------------------------------------------------- lifecycle
def test_entry_at_next_cycle_quote_and_warmup_respected():
    fr = make_frame(48, lambda i: 100.0, crash_at=5)
    r = run(fr)
    assert len(r["signals"]) == 1 and r["signals"][0]["approved"]
    assert r["signals"][0]["ts_ms"] == T0 + 6 * H + 5_000       # candle close + 5s cycle
    pos = r["trades"] + r["open_at_end"]
    assert len(pos) == 1 and pos[0]["entry_ms"] if r["trades"] else pos[0]["opened_ms"] == T0 + 6 * H + 5_000
    assert r["leakage_check"]["ok"]
    # too little history => no signal (min_bars)
    short = make_frame(48, lambda i: 100.0, crash_at=5)
    short.sig_ts, short.sig_ohlcv = short.sig_ts[-40:], short.sig_ohlcv[-40:]
    assert run(short)["signals"] == []


def test_no_quote_at_signal_time_means_no_entry_and_a_warning():
    fr = make_frame(48, lambda i: 100.0, crash_at=5, quotes=False)
    r = run(fr)
    assert r["trades"] == [] and r["open_at_end"] == []
    assert r["signals"][0]["approved"] is False
    assert "market data unavailable" in r["signals"][0]["reject_reason"]
    assert any("no quote" in w for w in r["warnings"])


def test_trailing_stop_ratchets_only_up_and_exits_on_pullback():
    # crash at bar 5, then +1%/h for 20h, then a sharp drop
    def px(i):
        k = i - 305
        if k < 0:
            return 100.0
        if k <= 20:
            return 91.0 * (1.01 ** k)
        return 91.0 * (1.01 ** 20) * 0.9
    fr = make_frame(48, px, crash_at=5)
    r = run(fr)
    assert len(r["trades"]) == 1
    t = r["trades"][0]
    assert t["stop_final"] > t["stop_initial"] and t["exit_reason"].startswith("STOP")
    assert t["net_pnl_usd"] > 0 and t["exit_ms"] <= T0 + 28 * H


def test_liquidation_wins_over_stop_on_gap_and_loses_margin_plus_fees():
    cfg = CRHConfig()
    fr = make_frame(48, lambda i: 100.0, crash_at=5)
    r = run(fr, cfg, hours=8)               # open at hour 6, still open at end
    pos = r["open_at_end"][0]
    liq = pos["liq_price_est"]
    # now a 1m bar that gaps through both stop and liquidation at hour 7
    gap_ts = T0 + 7 * H
    fr2 = make_frame(48, lambda i: 100.0, crash_at=5,
                     m1_override={gap_ts: [liq * 0.99, liq * 0.99, liq * 0.98, liq * 0.985]})
    r2 = run(fr2, cfg, hours=10)
    t = r2["trades"][0]
    assert t["exit_reason"] == "LIQUIDATION"
    assert t["net_pnl_usd"] == pytest.approx(-(t["margin_usd"] + t["entry_fee_usd"] + t["funding_usd"]))
    assert r2["final_cash"] == pytest.approx(cfg.starting_capital_usd - t["margin_usd"] - t["entry_fee_usd"] - t["funding_usd"])


def test_funding_applied_at_8h_boundaries_with_settled_rate_only():
    fr = make_frame(48, lambda i: 100.0, crash_at=5,
                    funding=[(T0 - 8 * H, 0.0001), (T0 + 8 * H, 0.001), (T0 + 16 * H, -0.002)])
    r = run(fr, hours=30)
    ev = r["funding_events"]
    assert [e["funding_ts_ms"] for e in ev] == [T0 + 8 * H, T0 + 16 * H, T0 + 24 * H]
    assert [e["rate"] for e in ev] == [0.001, -0.002, -0.002]   # rate settled at/before boundary
    assert ev[0]["amount_usd"] > 0 and ev[1]["amount_usd"] < 0


def test_fees_and_slippage_are_charged_exactly_as_perp_math():
    fr = make_frame(48, lambda i: 100.0, crash_at=5)
    r = run(fr, hours=8)
    pos = r["open_at_end"][0]
    q_ask = fr.quotes(T0 + 6 * H + 5_000)[1]
    assert pos["entry_price"] == pytest.approx(q_ask * (1 + 0.0005))
    assert pos["entry_fee_usd"] == pytest.approx(pos["notional_usd"] * 0.0006)
    assert pos["planned_risk_usd"] <= 5.0 + 1e-9


def test_position_and_combined_risk_limits_and_cash_limit():
    frames = {}
    for k in range(5):
        s = f"S{k}/USDT:USDT"
        f = make_frame(48, lambda i: 100.0, crash_at=5)
        f.symbol = s
        f.spec = ContractSpec(s, 0.0006, 0.005, 0.01, 0.001)
        frames[s] = f
    cfg = scaled_baseline(500.0, risk_per_trade_usd=5.0, max_combined_risk_usd=15.0)
    r = CRHReplay(cfg, P(frames), T0, T0 + 8 * H).run()
    approved = [s for s in r["signals"] if s["approved"]]
    rejected = [s["reject_reason"] for s in r["signals"] if not s["approved"]]
    assert len(approved) == 3 and all("position limit reached (3)" in x for x in rejected)
    cfg2 = scaled_baseline(500.0, risk_per_trade_usd=5.0, max_open_positions=5,
                           max_combined_risk_usd=5.0)
    r2 = CRHReplay(cfg2, P(frames), T0, T0 + 8 * H).run()
    assert sum(s["approved"] for s in r2["signals"]) == 1
    assert any("combined planned risk" in x for x in [s["reject_reason"] or "" for s in r2["signals"]])
    # the deployed $50 sleeve: cash, not slots, is the binding limit (live finding F5)
    r3 = CRHReplay(CRHConfig(), P(frames), T0, T0 + 8 * H).run()
    assert any("position too small" in (s["reject_reason"] or "") for s in r3["signals"])


def test_trailing_drawdown_lock_blocks_entries_and_emergency_exits():
    def px(i):      # crash at 5, rally +40% by hour 20 then collapse to -40%
        k = i - 305
        if k < 0:
            return 100.0
        return 91.0 * (1.4 if 10 <= k < 20 else 0.6 if k >= 20 else 1.0)
    cfg = scaled_baseline(50.0, trailing_drawdown_usd=5.0)
    fr = make_frame(48, px, crash_at=5)
    r = run(fr, cfg, hours=40)
    assert r["locked"] and "TRAILING DRAWDOWN BREACH" in r["lock_reason"]
    assert r["open_at_end"] == [] and r["trades"][0]["exit_reason"] in (
        "EMERGENCY (trailing drawdown)", "STOP", "STOP (gap)")


def test_strategy_loss_trigger_locks_and_exits():
    def px(i):
        k = i - 305
        return 100.0 if k < 0 else (91.0 if k < 3 else 60.0)
    cfg = scaled_baseline(50.0, strategy_loss_trigger_usd=1.0, leverage=10.0)
    r = run(make_frame(48, px, crash_at=5), cfg, hours=12)
    assert r["strategy_locked"]
    assert any("STRATEGY LOCKED" in e["message"] for e in r["risk_events"])


def test_positions_and_stops_carry_across_midnight_without_reset():
    fr = make_frame(72, lambda i: 100.0, crash_at=20)        # signal closes 21:00 day 1
    r = run(fr, hours=60)
    pos = r["open_at_end"][0]
    assert pos["opened_ms"] < T0 + 24 * H < r["equity_curve"][-1][0]
    day1 = [p for p in r["equity_curve"] if p[0] <= T0 + 24 * H][-1]
    day2 = [p for p in r["equity_curve"] if p[0] >= T0 + 24 * H][0]
    paid = sum(e["amount_usd"] for e in r["funding_events"] if day1[0] < e["funding_ts_ms"] <= day2[0])
    assert day1[2] - paid == pytest.approx(day2[2])             # only funding moves cash at midnight
    assert paid != 0                                            # 00:00 UTC is a funding boundary
    assert r["final_cash"] == pytest.approx(50.0 - pos["margin_usd"] - pos["entry_fee_usd"]
                                            - pos["funding_paid_usd"])


def test_accounting_identity_and_no_lookahead_on_every_run():
    fr = make_frame(48, lambda i: 100.0 + (i % 7), crash_at=5)
    r = run(fr)
    margin = sum(p["margin_usd"] for p in r["open_at_end"])
    unreal = sum(p["unrealized_pnl_usd"] or 0 for p in r["open_at_end"])
    assert r["final_cash"] + margin + unreal == pytest.approx(r["final_equity"])
    assert r["leakage_check"]["ok"]


def test_approximate_fidelity_uses_minute_opens_and_is_labelled():
    fr = make_frame(48, lambda i: 100.0, crash_at=5, quotes=False)
    cfg = scaled_baseline(50.0, fidelity="approximate")
    r = run(fr, cfg, hours=8)
    assert r["fidelity"] == "approximate" and len(r["open_at_end"]) == 1
    o = fr.m1_ohlc[np.searchsorted(fr.m1_ts, T0 + 6 * H), 0]
    assert r["open_at_end"][0]["entry_price"] == pytest.approx(o * (1 + 0.0005) * (1 + 0.0005))


def test_cancel_raises_cleanly():
    fr = make_frame(48, lambda i: 100.0, crash_at=5)
    with pytest.raises(RuntimeError, match="cancelled"):
        CRHReplay(CRHConfig(), P({SYM: fr}), T0, T0 + 8 * H, cancelled=lambda: True).run()


def test_config_validation_and_fingerprint():
    with pytest.raises(ValueError):
        CRHConfig(leverage=50).validate()
    with pytest.raises(ValueError):
        CRHConfig(strategy_loss_trigger_usd=60).validate()
    assert CRHConfig().fingerprint() != scaled_baseline(500).fingerprint()
    assert scaled_baseline(500).is_baseline() and not scaled_baseline(50, crash_drop_pct=-5).is_baseline()
