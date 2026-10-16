"""Read-only local dashboard: streamlit run dashboard.py."""
from pathlib import Path
import json
import os
import sqlite3
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from paperbot.report import drawdown_series, trade_stats  # noqa: E402

st.set_page_config(page_title="PaperBot — BTC/GBP", page_icon="📉", layout="wide")
st.title("Crypto PaperBot")
st.caption("RESEARCH / PAPER TRADING ONLY — virtual account, no real exchange orders")
path = os.getenv("PAPERBOT_DB", "state/paper.sqlite")
if not Path(path).exists():
    st.info("No paper data yet. Run `paperbot once` or `paperbot run`, then refresh.")
    st.stop()
conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
try:
    state = pd.read_sql_query("SELECT key,value FROM kv", conn)
    state_map = {r.key: r.value for r in state.itertuples()}
    positions = pd.read_sql_query("SELECT * FROM position", conn)
    trades = pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC LIMIT 500", conn)
    try:
        equity_hist = pd.read_sql_query(
            "SELECT * FROM equity_history ORDER BY ts_ms", conn)
    except (pd.errors.DatabaseError, sqlite3.OperationalError):
        equity_hist = pd.DataFrame()  # DB written by an older engine version
finally:
    conn.close()

cash = float(json.loads(state_map.get("balance", "0")))
initial = float(json.loads(state_map.get("initial_balance", "1000")))
locked_total = bool(json.loads(state_map.get("locked_total", "false")))
locked_daily = bool(json.loads(state_map.get("locked_daily", "false")))
latest_equity = float(equity_hist["equity"].iloc[-1]) if not equity_hist.empty else None

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Virtual cash (GBP)", f"£{cash:,.2f}")
col2.metric("Marked equity (last tick)",
            f"£{latest_equity:,.2f}" if latest_equity is not None else "n/a")
col3.metric("Open spot positions", len(positions))
col4.metric("Closed trades", len(trades))
col5.metric("Entry lockouts",
            "TOTAL" if locked_total else ("DAILY" if locked_daily else "none"))
if locked_total:
    st.error("TOTAL DRAWDOWN LOCK is on: no new simulated entries until manual review/reset.")

if not equity_hist.empty:
    ts = pd.to_datetime(equity_hist["ts_ms"], unit="ms", utc=True)
    last_seen = ts.iloc[-1].strftime("%Y-%m-%d %H:%M UTC")
    st.subheader("Mark-to-market equity (GBP)")
    st.caption(f"One point per engine tick; last snapshot {last_seen}. "
               "Gaps mean the engine was not running — nothing is interpolated.")
    st.line_chart(pd.DataFrame({"equity": equity_hist["equity"].values}, index=ts),
                  color="#2563eb")
    st.subheader("Drawdown from running equity peak (%)")
    dd = drawdown_series(equity_hist.to_dict("records"))
    st.area_chart(pd.DataFrame({"drawdown %": dd}, index=ts), color="#dc2626")
else:
    st.info("No equity snapshots yet: they are recorded per tick once the "
            "updated engine runs (`paperbot run`). The cumulative realised "
            "P&L line below ignores open-position marks.")

if not positions.empty:
    st.subheader("Open paper position")
    st.dataframe(positions, use_container_width=True, hide_index=True)

if not trades.empty:
    st.subheader("Trading statistics (realised, simulated)")
    stats = trade_stats(trades.to_dict("records"))
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Win rate", f"{stats['win_rate_pct']:.1f}%")
    s2.metric("Profit factor",
              f"{stats['profit_factor']:.2f}" if stats['profit_factor'] is not None else "n/a")
    s3.metric("Expectancy / trade", f"£{stats['expectancy']:+.2f}")
    s4.metric("Total net P&L", f"£{stats['total_net_pnl']:+,.2f}")
    s5.metric("Avg hold", f"{stats['average_hold_hours']:.1f}h")
    st.caption("Simulated results on public data with modeled costs; "
               "they are NOT evidence of future performance.")
    st.subheader("Simulated realised trade results")
    st.dataframe(trades, use_container_width=True, hide_index=True)
    if equity_hist.empty:
        history = trades.sort_values("exit_ms")
        st.line_chart(initial + history["net_pnl"].cumsum().reset_index(drop=True),
                      color="#2563eb")
else:
    st.info("No closed paper positions yet.")

alerts_path = Path(path).parent / "alerts.jsonl"
if alerts_path.exists():
    lines = alerts_path.read_text(encoding="utf-8").splitlines()[-50:]
    if lines:
        st.subheader("Recent alerts")
        alerts = pd.DataFrame([json.loads(line) for line in lines])
        alerts["time"] = pd.to_datetime(alerts["ts"], unit="s", utc=True)
        st.dataframe(alerts[["time", "level", "title", "body"]].iloc[::-1],
                     use_container_width=True, hide_index=True)

st.caption("For local use only. Read-only dashboard; no buttons to submit live orders.")
