"""Read-only local dashboard: streamlit run dashboard.py."""
from pathlib import Path
import os
import sqlite3
import pandas as pd
import streamlit as st

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
finally:
    conn.close()
import json
cash = float(json.loads(state_map.get("balance", "0")))
initial = float(json.loads(state_map.get("initial_balance", "1000")))
locked = bool(json.loads(state_map.get("locked_total", "false")))
col1, col2, col3, col4 = st.columns(4)
col1.metric("Virtual cash (GBP)", f"£{cash:,.2f}")
col2.metric("Open spot positions", len(positions))
col3.metric("Closed trades", len(trades))
col4.metric("Total drawdown lock", "ON" if locked else "OFF")
st.warning("Cash is not total equity when a position is open. Open-position values are marked only on live market ticks; do not treat this dashboard as a real account balance.")
if not positions.empty:
    st.subheader("Open paper position")
    st.dataframe(positions, use_container_width=True, hide_index=True)
if not trades.empty:
    st.subheader("Simulated realised trade results")
    st.metric("Realised net P&L of displayed trades (GBP)", f"£{trades['net_pnl'].sum():,.2f}")
    st.dataframe(trades, use_container_width=True, hide_index=True)
    history = trades.sort_values("exit_ms")
    st.line_chart(initial + history["net_pnl"].cumsum().reset_index(drop=True))
else:
    st.info("No closed paper positions yet.")
st.caption("For local use only. Read-only dashboard; no buttons to submit live orders.")
