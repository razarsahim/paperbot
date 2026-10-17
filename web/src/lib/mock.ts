// Deterministic DEMO data shown when the local backend is unreachable.
// Every value here is clearly fake and exists only so the UI can render.
// Components receiving this data MUST show the amber "DEMO" badge.

import type {
  Analytics,
  AuditEntry,
  CandleResponse,
  Health,
  HypeRadar,
  Lab,
  Overview,
  Position,
  Research,
  Settings,
  SignalEvent,
  Strategies,
  Trade,
  Universe,
  UniverseAsset,
} from "./types";

const NOW = Date.now();
const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

export const mockHealth: Health = {
  status: "degraded",
  engines: {
    legacy: { running: true, last_tick_ms: NOW - 42_000 },
    pro: { running: true, last_scan_ms: NOW - 18_000, auto_entry_enabled: false },
  },
  data_sources: [
    { name: "CoinGecko (public)", ok: true, last_ok_ms: NOW - 65_000, detail: "Top-20 snapshot cached 65s ago" },
    { name: "Kraken public OHLCV", ok: true, last_ok_ms: NOW - 31_000, detail: "BTC/GBP spot candles OK" },
    { name: "Perp instrument meta", ok: false, last_ok_ms: NOW - 22 * MIN, detail: "Rate limited — backing off, no trades on stale data" },
  ],
};

export const mockOverview: Overview = {
  mode: "PAPER",
  ts_ms: NOW - 12_000,
  equity_usd: 1000.0,
  cash_usd: 862.4,
  margin_used_usd: 137.6,
  free_margin_usd: 862.4,
  exposure_notional_usd: 688.0,
  daily_pnl_usd: -4.12,
  total_pnl_usd: -18.73,
  win_rate_pct: 33.3,
  profit_factor: 0.64,
  max_drawdown_pct: 3.4,
  risk: {
    open_positions: 2,
    max_positions: 3,
    combined_planned_risk_pct: 1.0,
    risk_ceiling_pct: 1.5,
    daily_locked: false,
    total_locked: false,
    trading_enabled: true,
    pause_reason: null,
  },
  sleeves: {
    core: { balance_usd: 900.0, available_usd: 762.4 },
    hype: { balance_usd: 100.0, available_usd: 100.0, watch_only: true },
  },
  legacy: {
    symbol: "BTC/GBP",
    equity_gbp: 1000.0,
    cash_gbp: 1000.0,
    open_position: false,
    closed_trades: 11,
    locked_total: false,
  },
};

function asset(
  rank: number,
  id: string,
  symbol: string,
  name: string,
  price: number,
  chg: number,
  mcapB: number,
  volB: number,
  trend: UniverseAsset["trend"],
  atr: number | null,
  rsi: number | null,
  signal: UniverseAsset["signal"],
  eligible: boolean,
  reason: string | null,
  spread: number | null = 0.04,
  funding: number | null = 0.0001
): UniverseAsset {
  return {
    rank,
    coingecko_id: id,
    symbol,
    name,
    price_usd: price,
    change_24h_pct: chg,
    market_cap_usd: mcapB * 1e9,
    volume_24h_usd: volB * 1e9,
    trend,
    atr_pct: atr,
    rsi,
    signal,
    eligible,
    reason,
    instrument: eligible || reason !== "No listed perp instrument"
      ? {
          exchange: "binanceusdm (public data)",
          symbol: `${symbol}/USDT:USDT`,
          taker_fee: 0.0005,
          maint_margin_rate: 0.005,
          tick_size: price > 1000 ? 0.1 : price > 1 ? 0.001 : 0.000001,
          lot_size: price > 1000 ? 0.001 : 0.1,
          funding_rate: funding,
          mark_price: price * 1.0002,
          spread_pct: spread,
          data_age_s: 21,
        }
      : null,
  };
}

export const mockUniverse: Universe = {
  updated_at_ms: NOW - 4 * MIN,
  stale: false,
  assets: [
    asset(1, "bitcoin", "BTC", "Bitcoin", 67412.5, 1.84, 1330, 28.4, "up", 2.1, 58.2, "long", true, null),
    asset(2, "ethereum", "ETH", "Ethereum", 3251.8, 0.92, 391, 14.1, "up", 2.8, 54.7, "none", true, null),
    asset(3, "tether", "USDT", "Tether", 1.0, 0.01, 112, 44.2, "flat", 0.1, 50.0, "none", false, "Stablecoin excluded from momentum universe"),
    asset(4, "binancecoin", "BNB", "BNB", 584.3, -0.44, 86, 1.8, "flat", 2.4, 48.9, "none", true, null),
    asset(5, "solana", "SOL", "Solana", 142.76, -2.31, 66, 3.2, "down", 4.1, 41.3, "short", true, null),
    asset(6, "ripple", "XRP", "XRP", 0.5214, -1.12, 29, 1.4, "down", 3.3, 44.6, "none", true, null),
    asset(7, "usd-coin", "USDC", "USD Coin", 1.0, 0.0, 33, 6.8, "flat", 0.1, 50.0, "none", false, "Stablecoin excluded from momentum universe"),
    asset(8, "dogecoin", "DOGE", "Dogecoin", 0.1092, 3.41, 16, 1.1, "up", 5.2, 63.1, "none", true, null),
    asset(9, "cardano", "ADA", "Cardano", 0.3811, -0.76, 13, 0.4, "flat", 3.0, 47.2, "none", true, null),
    asset(10, "tron", "TRX", "TRON", 0.161, 0.31, 14, 0.5, "flat", 1.9, 51.8, "none", true, null),
    asset(11, "avalanche-2", "AVAX", "Avalanche", 24.18, -3.02, 9.8, 0.5, "down", 4.6, 38.4, "none", true, null),
    asset(12, "shiba-inu", "SHIB", "Shiba Inu", 0.0000172, 2.14, 10.1, 0.4, "up", 5.8, 61.0, "none", true, null),
    asset(13, "chainlink", "LINK", "Chainlink", 11.42, 1.21, 7.2, 0.4, "up", 3.9, 56.3, "none", true, null),
    asset(14, "polkadot", "DOT", "Polkadot", 4.87, -0.52, 7.0, 0.2, "flat", 3.4, 46.1, "none", true, null),
    asset(15, "bitcoin-cash", "BCH", "Bitcoin Cash", 341.2, 0.64, 6.7, 0.3, "flat", 3.1, 52.4, "none", true, null),
    asset(16, "near", "NEAR", "NEAR Protocol", 3.92, -1.84, 4.6, 0.3, "down", 4.9, 42.7, "none", true, null),
    asset(17, "matic-network", "POL", "Polygon", 0.412, -2.46, 4.1, 0.2, "down", 4.4, 39.8, "none", true, null),
    asset(18, "litecoin", "LTC", "Litecoin", 68.41, 0.22, 5.1, 0.4, "flat", 2.7, 49.5, "none", true, null),
    asset(19, "internet-computer", "ICP", "Internet Computer", 7.84, 1.02, 3.7, 0.1, "up", 5.1, 55.2, "none", true, null),
    asset(20, "uniswap", "UNI", "Uniswap", 7.12, -0.31, 4.3, 0.2, "flat", 4.0, 48.1, "none", true, null),
  ],
  changes: [
    { date: "2026-10-14", added: ["ICP"], removed: ["ETC"] },
    { date: "2026-10-09", added: ["NEAR"], removed: ["XLM"] },
  ],
};

export const mockPositions: Position[] = [
  {
    id: 101,
    symbol: "BTC/USDT:USDT",
    side: "long",
    leverage: 5,
    qty: 0.0051,
    entry_price: 66980.0,
    mark_price: 67425.1,
    liq_price_est: 54210.0,
    stop: 65620.0,
    target: 69700.0,
    margin_usd: 68.8,
    notional_usd: 344.0,
    unrealized_pnl_usd: 2.27,
    funding_paid_usd: -0.11,
    fees_paid_usd: 0.17,
    planned_risk_pct: 0.5,
    opened_at_ms: NOW - 9 * HOUR,
    sleeve: "core",
  },
  {
    id: 102,
    symbol: "SOL/USDT:USDT",
    side: "short",
    leverage: 5,
    qty: 2.41,
    entry_price: 144.9,
    mark_price: 142.71,
    liq_price_est: 172.4,
    stop: 148.55,
    target: 137.2,
    margin_usd: 68.8,
    notional_usd: 344.0,
    unrealized_pnl_usd: 5.28,
    funding_paid_usd: 0.04,
    fees_paid_usd: 0.17,
    planned_risk_pct: 0.5,
    opened_at_ms: NOW - 4 * HOUR,
    sleeve: "core",
  },
];

function trade(
  id: number,
  symbol: string,
  side: Trade["side"],
  entry: number,
  exit: number,
  qty: number,
  pnl: number,
  exitReason: string,
  rationale: string,
  daysAgo: number,
  holdHours: number,
  mfe: number,
  mae: number
): Trade {
  const notional = entry * qty;
  return {
    id,
    symbol,
    side,
    leverage: 5,
    qty,
    entry_price: entry,
    exit_price: exit,
    stop_initial: side === "long" ? entry * 0.98 : entry * 1.02,
    stop_final: side === "long" ? entry * 0.99 : entry * 1.01,
    target: side === "long" ? entry * 1.04 : entry * 0.96,
    margin_usd: notional / 5,
    notional_usd: notional,
    entry_fee_usd: notional * 0.0005,
    exit_fee_usd: exit * qty * 0.0005,
    funding_usd: -0.08,
    slippage_model: "half-spread + 2bps impact",
    net_pnl_usd: pnl,
    mfe_pct: mfe,
    mae_pct: mae,
    entry_ms: NOW - daysAgo * DAY - holdHours * HOUR,
    exit_ms: NOW - daysAgo * DAY,
    exit_reason: exitReason,
    rationale,
    indicator_snapshot: {
      rsi_14: side === "long" ? 61.2 : 38.4,
      ema_20: entry * (side === "long" ? 0.992 : 1.008),
      ema_50: entry * (side === "long" ? 0.981 : 1.019),
      atr_pct: 3.1,
      adx_14: 24.6,
    },
    sleeve: "core",
  };
}

export const mockTrades: Trade[] = [
  trade(9, "BTC/USDT:USDT", "long", 65210, 66480, 0.0052, 5.93, "target", "EMA20>EMA50 cross with RSI confirmation on previous closed bar.", 1, 14, 2.4, -0.6),
  trade(8, "ETH/USDT:USDT", "long", 3310, 3244, 0.102, -7.21, "stop", "Breakout above 20-bar high on prior close; invalidated same day.", 2, 7, 0.4, -2.1),
  trade(7, "SOL/USDT:USDT", "short", 151.2, 147.9, 2.2, 6.68, "target", "Lower-high structure, RSI<45, funding positive — short on prior-bar signal.", 4, 22, 2.6, -0.5),
  trade(6, "DOGE/USDT:USDT", "long", 0.1121, 0.1098, 3050, -7.65, "stop", "Momentum continuation setup failed on volume fade.", 6, 10, 0.8, -2.2),
  trade(5, "BTC/USDT:USDT", "short", 68950, 69420, 0.005, -2.84, "time_stop", "Mean-reversion fade of extended move; exited on 48h time stop.", 9, 48, 0.9, -1.3),
  trade(4, "LINK/USDT:USDT", "long", 10.84, 10.61, 31.5, -8.02, "stop", "Pullback-to-EMA20 entry; stop hit on wick through level.", 12, 16, 1.1, -2.3),
];

export const mockSignals: SignalEvent[] = [
  { ts_ms: NOW - 6 * MIN, symbol: "BTC/USDT:USDT", action: "long", approved: true, reject_reason: null, details: "EMA20>EMA50, RSI 58.2, ATR 2.1% — size 0.5% risk, 5x cap" },
  { ts_ms: NOW - 38 * MIN, symbol: "AVAX/USDT:USDT", action: "short", approved: false, reject_reason: "Combined planned risk would exceed 1.5% ceiling", details: "Signal valid but portfolio risk budget exhausted" },
  { ts_ms: NOW - 2 * HOUR, symbol: "SOL/USDT:USDT", action: "short", approved: true, reject_reason: null, details: "Lower-high + RSI 41.3; spread 0.04% within limit" },
  { ts_ms: NOW - 5 * HOUR, symbol: "SHIB/USDT:USDT", action: "long", approved: false, reject_reason: "Spread 0.22% above 0.10% limit", details: "Execution cost model rejects thin book" },
  { ts_ms: NOW - 8 * HOUR, symbol: "NEAR/USDT:USDT", action: "short", approved: false, reject_reason: "Instrument data stale (>120s)", details: "Default to no trade on stale feed" },
];

function curve(points: number, start: number, end: number, wobble: number): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i < points; i++) {
    const t = i / (points - 1);
    const base = start + (end - start) * t;
    const w = Math.sin(i * 1.7) * wobble + Math.sin(i * 0.43) * wobble * 1.6;
    out.push([NOW - (points - 1 - i) * 6 * HOUR, Math.round((base + w) * 100) / 100]);
  }
  return out;
}

const eq = curve(90, 1012, 1000, 4.5);
export const mockAnalytics: Analytics = {
  equity_curve: eq,
  drawdown_curve: (() => {
    let peak = -Infinity;
    return eq.map(([t, v]) => {
      peak = Math.max(peak, v);
      return [t, Math.round(((v - peak) / peak) * 10000) / 100] as [number, number];
    });
  })(),
  monthly: [
    { month: "2026-06", pnl_usd: 3.1 },
    { month: "2026-07", pnl_usd: -9.4 },
    { month: "2026-08", pnl_usd: -2.2 },
    { month: "2026-09", pnl_usd: -6.8 },
    { month: "2026-10", pnl_usd: -3.4 },
  ],
  by_asset: [
    { symbol: "BTC/USDT:USDT", trades: 2, pnl_usd: 3.09 },
    { symbol: "SOL/USDT:USDT", trades: 1, pnl_usd: 6.68 },
    { symbol: "ETH/USDT:USDT", trades: 1, pnl_usd: -7.21 },
    { symbol: "DOGE/USDT:USDT", trades: 1, pnl_usd: -7.65 },
    { symbol: "LINK/USDT:USDT", trades: 1, pnl_usd: -8.02 },
  ],
  benchmarks: { cash_usd: 1000.0, btc_hold_pct: 4.2 },
  validation: {
    exists: true,
    summary:
      "Walk-forward backtest (real Kraken BTC/GBP spot): −2.69% over 11 trades, profit factor 0.16, 0/3 windows profitable.",
  },
};

export const mockHype: HypeRadar = {
  sleeve: { balance_usd: 100.0, spent_usd: 0.0, loss_cap_usd: 100.0, watch_only: true },
  tokens: [
    {
      symbol: "GLOWCAT",
      name: "Glow Cat",
      chain: "solana",
      contract: "G1owCaT9xDEMO000000000000000000000000000001",
      pool_age_hours: 31,
      liquidity_usd: 184_000,
      volume_24h_usd: 2_310_000,
      score: 62,
      flags: ["pool_age<48h", "top10_holders_41pct"],
      evidence: [
        { source: "dexscreener", note: "Volume/liquidity ratio 12.5 — elevated churn" },
        { source: "x_mentions", note: "Mentions +340% in 24h, mostly new accounts" },
      ],
      status: "WATCH_ONLY",
      ts_ms: NOW - 20 * MIN,
      explanation: "High social velocity but young pool and concentrated holders. Watch-only; no simulated buy.",
    },
    {
      symbol: "MOONYIELD",
      name: "Moon Yield Finance",
      chain: "bsc",
      contract: "0xDEMO00000000000000000000000000000000dead",
      pool_age_hours: 6,
      liquidity_usd: 21_000,
      volume_24h_usd: 940_000,
      score: 11,
      flags: ["HONEYPOT_SELL_BLOCKED", "mint_authority_active", "liquidity_unlocked", "deployer_prior_rugs:3"],
      evidence: [
        { source: "honeypot_check", note: "Simulated sell reverts — transfer tax 99% on sell path" },
        { source: "chain_scan", note: "Deployer wallet linked to 3 abandoned tokens" },
      ],
      status: "REJECTED",
      ts_ms: NOW - 55 * MIN,
      explanation: "Rejected: sell-path simulation fails (honeypot pattern). Listed only as a negative example.",
    },
    {
      symbol: "DEPIN42",
      name: "DePIN 42",
      chain: "base",
      contract: "0xDEMO0000000000000000000000000000000042ab",
      pool_age_hours: 410,
      liquidity_usd: 1_240_000,
      volume_24h_usd: 5_800_000,
      score: 74,
      flags: ["narrative_crowded"],
      evidence: [
        { source: "dexscreener", note: "Liquidity locked 180d, stable depth both sides" },
        { source: "github", note: "Active repo, 14 contributors, releases weekly" },
      ],
      status: "WATCH_ONLY",
      ts_ms: NOW - 3 * HOUR,
      explanation: "Cleanest profile in scan window; still watch-only — hype score is not evidence of future growth.",
    },
  ],
};

export const mockAudit: AuditEntry[] = [
  { ts_ms: NOW - 3 * MIN, level: "info", category: "scanner", message: "Pro scan complete: 20 assets, 1 signal, 0 entries (auto-entry disabled)" },
  { ts_ms: NOW - 22 * MIN, level: "warning", category: "data", message: "Perp instrument metadata rate-limited; backing off 120s, entries blocked on stale data" },
  { ts_ms: NOW - 61 * MIN, level: "info", category: "risk", message: "Combined planned risk 1.0% of 1.5% ceiling after SOL short" },
  { ts_ms: NOW - 2 * HOUR, level: "info", category: "execution", message: "Simulated fill SOL short 2.41 @ 144.90 (half-spread + 2bps slippage model)" },
  { ts_ms: NOW - 5 * HOUR, level: "error", category: "data", message: "CoinGecko request failed (HTTP 429); served cached universe, marked fresh=false for 4m" },
  { ts_ms: NOW - 9 * HOUR, level: "info", category: "execution", message: "Simulated fill BTC long 0.0051 @ 66,980.00" },
  { ts_ms: NOW - 26 * HOUR, level: "warning", category: "risk", message: "Daily loss reached 1.6% of 2.0% lock threshold; monitoring" },
];

export const mockSettings: Settings = {
  mode: "PAPER (simulated funds only)",
  base_currency: "USD",
  starting_equity_usd: 1000,
  risk_per_trade_pct: 0.5,
  max_open_positions: 3,
  combined_risk_ceiling_pct: 1.5,
  daily_loss_lock_pct: 2.0,
  total_loss_pause_pct: 5.0,
  max_leverage: 5,
  taker_fee_assumption: 0.0005,
  slippage_model: "half-spread + 2bps impact",
  universe_source: "coingecko_top20",
  universe_refresh_min: 15,
  scan_interval_s: 60,
  auto_entry_enabled: false,
  hype_sleeve_usd: 100,
  hype_watch_only: true,
  stale_data_block_s: 120,
  never_widen_stops: true,
  never_average_down: true,
};

// ---------- Extreme Lab (DEMO) ----------
// Clearly synthetic PAPER-ONLY unified lab snapshot: $500 total across ten $50
// sleeves (5 "extreme" + 5 migrated "research" strategies). Negative results on
// purpose: the Lab exists to study failure modes, not to imply profitability.

function labCurve(): [number, number, number][] {
  const points = 72; // ~18 days at 6h
  const out: [number, number, number][] = [];
  let peak = 500;
  for (let i = 0; i < points; i++) {
    const t = i / (points - 1);
    const base = 500 + 14 * Math.sin(t * 2.2) - 20 * t; // drifts down to ~488
    const w = Math.sin(i * 1.9) * 2.4 + Math.sin(i * 0.37) * 3.2;
    const equity = Math.round((base + w) * 100) / 100;
    peak = Math.max(peak, equity);
    const threshold = Math.round(peak * 0.9 * 100) / 100; // 10% trailing drawdown line
    out.push([NOW - (points - 1 - i) * 6 * HOUR, equity, threshold]);
  }
  return out;
}

const labEq = labCurve();
const labEquityNow = labEq[labEq.length - 1][1];
const labPeak = Math.max(...labEq.map((p) => p[1]));
const labThreshold = labEq[labEq.length - 1][2];

export const mockLab: Lab = {
  status: {
    live: true,
    last_scan_ms: NOW - 24_000,
    auto_entry: false,
    locked: false,
    lock_reason: null,
    manual_pause: false,
  },
  capital: {
    initial_usd: 500.0,
    equity_usd: labEquityNow,
    cash_usd: Math.round((labEquityNow - 39.7 + 0.17) * 100) / 100,
    margin_used_usd: 39.7,
    unrealized_usd: -0.17,
    peak_equity_usd: labPeak,
    threshold_usd: labThreshold,
    remaining_allowance_usd: Math.round((labEquityNow - labThreshold) * 100) / 100,
  },
  strategies: [
    // --- "extreme" cohort (original 5, no per-strategy floor) ---
    {
      key: "trend",
      name: "trend_rider",
      display_name: "Trend Rider",
      description: "Rides established EMA-stacked trends with a trailing stop; never adds to losers.",
      allocation_usd: 50.0,
      cash_usd: 51.84,
      realized_pnl_usd: 1.84,
      open_symbols: [],
      cohort: "extreme",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 0 },
      unrealized_pnl_usd: 0,
      return_pct: 3.68,
    },
    {
      key: "breakout",
      name: "vol_breakout",
      display_name: "Volatility Breakout",
      description: "Enters on range expansion beyond a prior-bar volatility band; hard stop at band midpoint.",
      allocation_usd: 50.0,
      cash_usd: 27.1,
      realized_pnl_usd: -1.36,
      open_symbols: ["BTC/USDT:USDT"],
      cohort: "extreme",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 0 },
      unrealized_pnl_usd: -0.42,
      return_pct: -3.56,
    },
    {
      key: "funding",
      name: "funding_skew",
      display_name: "Funding Skew",
      description: "Positions against crowded funding extremes on perp data; exits when skew normalises.",
      allocation_usd: 50.0,
      cash_usd: 49.52,
      realized_pnl_usd: -0.48,
      open_symbols: [],
      cohort: "extreme",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 0 },
      unrealized_pnl_usd: 0,
      return_pct: -0.96,
    },
    {
      key: "momo",
      name: "momentum_burst",
      display_name: "Momentum Burst",
      description: "Short-horizon continuation after volume-confirmed bursts; tightest stop in the lab.",
      allocation_usd: 50.0,
      cash_usd: 47.73,
      realized_pnl_usd: -2.27,
      open_symbols: [],
      cohort: "extreme",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 0 },
      unrealized_pnl_usd: 0,
      return_pct: -4.54,
    },
    {
      key: "meanrev",
      name: "mean_reversion",
      display_name: "Mean Reversion",
      description: "Fades RSI extremes back toward the 20-bar mean; strict time stop at 24h.",
      allocation_usd: 50.0,
      cash_usd: 46.9,
      realized_pnl_usd: -3.1,
      open_symbols: [],
      cohort: "extreme",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 0 },
      unrealized_pnl_usd: 0,
      return_pct: -6.2,
    },
    // --- "research" cohort (migrated 5, $30 per-strategy floor) ---
    {
      key: "carry",
      name: "basis_carry",
      display_name: "Basis Carry",
      description: "Harvests calm perp/spot basis with tight risk; stands aside when basis is noisy.",
      allocation_usd: 50.0,
      cash_usd: 50.73,
      realized_pnl_usd: 0.73,
      open_symbols: ["ETH/USDT:USDT"],
      cohort: "research",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 20.73 },
      unrealized_pnl_usd: 0.18,
      return_pct: 1.82,
    },
    {
      key: "pairs",
      name: "stat_pairs",
      display_name: "Stat Pairs",
      description: "Trades mean-reverting spreads between correlated majors; neutral net exposure.",
      allocation_usd: 50.0,
      cash_usd: 48.11,
      realized_pnl_usd: -1.89,
      open_symbols: ["BTC/USDT:USDT"],
      cohort: "research",
      leverage: 10,
      status: { level: "warning", remaining_allowance_usd: 18.18 },
      unrealized_pnl_usd: 0.07,
      return_pct: -3.64,
    },
    {
      key: "seasonality",
      name: "intraday_seasonality",
      display_name: "Intraday Seasonality",
      description: "Small positions around repeatable intraday windows; flat outside them.",
      allocation_usd: 50.0,
      cash_usd: 49.6,
      realized_pnl_usd: -0.4,
      open_symbols: [],
      cohort: "research",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 19.6 },
      unrealized_pnl_usd: 0,
      return_pct: -0.8,
    },
    {
      key: "liqsweep",
      name: "liquidity_sweep",
      display_name: "Liquidity Sweep",
      description: "Fades stop-run wicks back into range; strict 12h time stop.",
      allocation_usd: 50.0,
      cash_usd: 49.95,
      realized_pnl_usd: -0.05,
      open_symbols: [],
      cohort: "research",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 19.95 },
      unrealized_pnl_usd: 0,
      return_pct: -0.1,
    },
    {
      key: "voltarget",
      name: "vol_target_trend",
      display_name: "Vol-Target Trend",
      description: "Trend exposure scaled inversely to realised volatility; never adds to losers.",
      allocation_usd: 50.0,
      cash_usd: 46.18,
      realized_pnl_usd: -3.82,
      open_symbols: [],
      cohort: "research",
      leverage: 10,
      status: { level: "locked", remaining_allowance_usd: 0.0 },
      unrealized_pnl_usd: 0,
      return_pct: -7.64,
      locked: true,
      lock_reason: "Per-strategy $30 floor reached — new entries blocked for the session",
    },
  ],
  positions: [
    {
      id: 501,
      strategy: "breakout",
      symbol: "BTC/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 0.0032,
      entry_price: 67120.0,
      margin_usd: 21.5,
      notional_usd: 214.8,
      stop: 66210.0,
      target: 69350.0,
      liq_price_est: 61140.0,
      funding_paid_usd: -0.06,
      planned_risk_usd: 2.91,
      opened_ms: NOW - 5 * HOUR,
      mark_price: 66988.5,
      unrealized_pnl_usd: -0.42,
    },
    {
      id: 801,
      strategy: "carry",
      symbol: "ETH/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 0.028,
      entry_price: 3248.0,
      margin_usd: 9.1,
      notional_usd: 90.94,
      stop: 3201.0,
      target: 3330.0,
      liq_price_est: 2960.0,
      funding_paid_usd: 0.04,
      planned_risk_usd: 1.32,
      opened_ms: NOW - 7 * HOUR,
      mark_price: 3254.4,
      unrealized_pnl_usd: 0.18,
    },
    {
      id: 802,
      strategy: "pairs",
      symbol: "BTC/USDT:USDT",
      side: "short",
      leverage: 10,
      qty: 0.00135,
      entry_price: 67240.0,
      margin_usd: 9.1,
      notional_usd: 90.77,
      stop: 68010.0,
      target: 65900.0,
      liq_price_est: 73800.0,
      funding_paid_usd: -0.02,
      planned_risk_usd: 1.04,
      opened_ms: NOW - 3 * HOUR,
      mark_price: 67188.0,
      unrealized_pnl_usd: 0.07,
    },
  ],
  signals: [
    {
      id: 9007,
      ts_ms: NOW - 9 * MIN,
      strategy: "trend",
      symbol: "ETH/USDT:USDT",
      action: "long",
      approved: false,
      reject_reason: "Remaining drawdown allowance below per-trade risk floor",
      details: "EMA stack intact but lab allowance is below the required $15 buffer",
    },
    {
      id: 9006,
      ts_ms: NOW - 42 * MIN,
      strategy: "momo",
      symbol: "DOGE/USDT:USDT",
      action: "long",
      approved: false,
      reject_reason: "Auto-entry disabled",
      details: "Volume burst 3.1x average; signal logged only",
    },
    {
      id: 9005,
      ts_ms: NOW - 5 * HOUR,
      strategy: "breakout",
      symbol: "BTC/USDT:USDT",
      action: "long",
      approved: true,
      reject_reason: null,
      details: "Range expansion above 20-bar band; risk $2.91, 10x margin cap OK",
    },
    {
      id: 9004,
      ts_ms: NOW - 8 * HOUR,
      strategy: "funding",
      symbol: "SOL/USDT:USDT",
      action: "short",
      approved: false,
      reject_reason: "Funding data stale (>120s)",
      details: "Default to no trade on stale feed",
    },
  ],
  trades: [
    {
      id: 701,
      strategy: "trend",
      symbol: "BTC/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 0.003,
      entry_price: 65840.0,
      exit_price: 66710.0,
      stop_initial: 65020.0,
      stop_final: 66010.0,
      target: 68200.0,
      margin_usd: 19.75,
      notional_usd: 197.5,
      entry_fee_usd: 0.1,
      exit_fee_usd: 0.1,
      funding_usd: -0.09,
      net_pnl_usd: 2.32,
      mfe_pct: 1.9,
      mae_pct: -0.4,
      entry_ms: NOW - 4 * DAY - 18 * HOUR,
      exit_ms: NOW - 4 * DAY,
      exit_reason: "trailing_stop",
      rationale: "EMA20>EMA50>EMA200 stack on prior close; trailed to lock gains.",
    },
    {
      id: 702,
      strategy: "meanrev",
      symbol: "SOL/USDT:USDT",
      side: "short",
      leverage: 10,
      qty: 1.4,
      entry_price: 148.2,
      exit_price: 150.6,
      stop_initial: 150.55,
      stop_final: 150.55,
      target: 142.8,
      margin_usd: 20.75,
      notional_usd: 207.5,
      entry_fee_usd: 0.1,
      exit_fee_usd: 0.11,
      funding_usd: 0.03,
      net_pnl_usd: -3.1,
      mfe_pct: 0.6,
      mae_pct: -1.7,
      entry_ms: NOW - 7 * DAY - 9 * HOUR,
      exit_ms: NOW - 7 * DAY,
      exit_reason: "stop",
      rationale: "RSI 76 fade toward 20-bar mean; invalidated on continuation.",
    },
    {
      id: 703,
      strategy: "momo",
      symbol: "DOGE/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 1800,
      entry_price: 0.1085,
      exit_price: 0.1071,
      stop_initial: 0.1066,
      stop_final: 0.1066,
      target: 0.1128,
      margin_usd: 19.53,
      notional_usd: 195.3,
      entry_fee_usd: 0.1,
      exit_fee_usd: 0.1,
      funding_usd: -0.04,
      net_pnl_usd: -2.27,
      mfe_pct: 0.5,
      mae_pct: -1.4,
      entry_ms: NOW - 10 * DAY - 6 * HOUR,
      exit_ms: NOW - 10 * DAY,
      exit_reason: "EMERGENCY",
      rationale: "Flattened by lab-wide emergency rule when intraday drawdown spiked.",
    },
  ],
  opportunities: {
    "BTC/USDT:USDT": {
      breakout: { action: "long", reason: "Price pressing 20-bar band upper edge with rising ATR" },
      trend: { action: null, reason: "EMA stack intact but pullback not complete" },
      meanrev: { action: null, reason: "RSI 58 — no extreme to fade" },
      funding: { action: null, reason: "Funding 0.01%/8h — no crowded skew" },
      momo: { action: null, reason: "Volume 1.1x average — below 2x burst gate" },
    },
    "ETH/USDT:USDT": {
      breakout: { action: null, reason: "Inside prior range; no expansion" },
      trend: { action: "long", reason: "EMA20>EMA50>EMA200 with higher-low structure" },
      meanrev: { action: null, reason: "RSI 54 — neutral" },
      funding: { action: null, reason: "Funding near flat" },
      momo: { action: null, reason: "No volume burst in window" },
    },
    "SOL/USDT:USDT": {
      breakout: { action: null, reason: "ATR contracting; breakout filter off" },
      trend: { action: null, reason: "EMAs flat and interleaved" },
      meanrev: { action: "short", reason: "RSI 74 against declining 20-bar mean" },
      funding: { action: "short", reason: "Funding +0.09%/8h crowded long" },
      momo: { action: null, reason: "Burst gate not met" },
    },
    "DOGE/USDT:USDT": {
      breakout: { action: null, reason: "Spread 0.14% above execution limit" },
      trend: { action: null, reason: "No established trend" },
      meanrev: { action: null, reason: "RSI 61 — neutral zone" },
      funding: { action: null, reason: "Funding data stale — default no trade" },
      momo: { action: "long", reason: "Volume 3.1x average with range break (auto-entry off)" },
    },
  },
  equity_curve: labEq,
  audit: [
    { id: 41, ts_ms: NOW - 4 * MIN, level: "info", category: "scanner", message: "Lab scan complete: 4 symbols × 5 strategies, 4 candidate signals, 0 entries (auto-entry off)" },
    { id: 40, ts_ms: NOW - 9 * MIN, level: "warning", category: "risk", message: "Remaining drawdown allowance below $15 soft floor — new entries gated" },
    { id: 39, ts_ms: NOW - 2 * HOUR, level: "info", category: "execution", message: "Mark-to-market: BTC breakout position −$0.42 unrealized, stop unchanged" },
    { id: 38, ts_ms: NOW - 8 * HOUR, level: "error", category: "data", message: "Funding feed stale (>120s) — funding_skew entries blocked, nothing hidden" },
    { id: 37, ts_ms: NOW - 10 * DAY, level: "error", category: "risk", message: "EMERGENCY flatten: intraday drawdown spike breached lab rule; DOGE momo closed at market" },
  ],
};

// ---------- Strategy Research Lab (DEMO) ----------
// Second $250 PAPER-ONLY lab. Same shape as mockLab plus per-strategy status
// levels and correlation-cluster tags on positions. Negative/thin results on
// purpose — the lab studies behaviour, never implies profitability.

function researchCurve(): [number, number, number][] {
  const points = 72;
  const out: [number, number, number][] = [];
  let peak = 250;
  for (let i = 0; i < points; i++) {
    const t = i / (points - 1);
    const base = 250 + 6 * Math.sin(t * 1.8) - 11 * t; // drifts down to ~245
    const w = Math.sin(i * 1.4) * 1.3 + Math.sin(i * 0.52) * 2.0;
    const equity = Math.round((base + w) * 100) / 100;
    peak = Math.max(peak, equity);
    const threshold = Math.round(peak * 0.9 * 100) / 100;
    out.push([NOW - (points - 1 - i) * 6 * HOUR, equity, threshold]);
  }
  return out;
}

const resEq = researchCurve();
const resEquityNow = resEq[resEq.length - 1][1];
const resPeak = Math.max(...resEq.map((p) => p[1]));
const resThreshold = resEq[resEq.length - 1][2];

export const mockResearch: Research = {
  status: {
    live: true,
    last_scan_ms: NOW - 31_000,
    auto_entry: false,
    locked: false,
    lock_reason: null,
    manual_pause: false,
  },
  capital: {
    initial_usd: 250.0,
    equity_usd: resEquityNow,
    cash_usd: Math.round((resEquityNow - 18.2 - 0.18) * 100) / 100,
    margin_used_usd: 18.2,
    unrealized_usd: 0.18,
    peak_equity_usd: resPeak,
    threshold_usd: resThreshold,
    remaining_allowance_usd: Math.round((resEquityNow - resThreshold) * 100) / 100,
  },
  strategies: [
    {
      key: "carry",
      name: "basis_carry",
      display_name: "Basis Carry",
      description: "Harvests calm perp/spot basis with tight risk; stands aside when basis is noisy.",
      allocation_usd: 50.0,
      cash_usd: 50.73,
      realized_pnl_usd: 0.73,
      open_symbols: ["ETH/USDT:USDT"],
      cohort: "research",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 4.92 },
      unrealized_pnl_usd: 0.18,
      return_pct: 1.82,
    },
    {
      key: "pairs",
      name: "stat_pairs",
      display_name: "Stat Pairs",
      description: "Trades mean-reverting spreads between correlated majors; neutral net exposure.",
      allocation_usd: 50.0,
      cash_usd: 48.11,
      realized_pnl_usd: -1.89,
      open_symbols: ["BTC/USDT:USDT"],
      cohort: "research",
      leverage: 10,
      status: { level: "warning", remaining_allowance_usd: 1.34 },
      unrealized_pnl_usd: 0.07,
      return_pct: -3.64,
    },
    {
      key: "seasonality",
      name: "intraday_seasonality",
      display_name: "Intraday Seasonality",
      description: "Small positions around repeatable intraday windows; flat outside them.",
      allocation_usd: 50.0,
      cash_usd: 49.6,
      realized_pnl_usd: -0.4,
      open_symbols: [],
      cohort: "research",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 4.6 },
      unrealized_pnl_usd: 0,
      return_pct: -0.8,
    },
    {
      key: "voltarget",
      name: "vol_target_trend",
      display_name: "Vol-Target Trend",
      description: "Trend exposure scaled inversely to realised volatility; never adds to losers.",
      allocation_usd: 50.0,
      cash_usd: 46.18,
      realized_pnl_usd: -3.82,
      open_symbols: [],
      cohort: "research",
      leverage: 10,
      status: { level: "locked", remaining_allowance_usd: 0.0 },
      unrealized_pnl_usd: 0,
      return_pct: -7.64,
      locked: true,
      lock_reason: "Per-strategy $30 floor reached — new entries blocked for the session",
    },
    {
      key: "liqsweep",
      name: "liquidity_sweep",
      display_name: "Liquidity Sweep",
      description: "Fades stop-run wicks back into range; strict 12h time stop.",
      allocation_usd: 50.0,
      cash_usd: 49.95,
      realized_pnl_usd: -0.05,
      open_symbols: [],
      cohort: "research",
      leverage: 10,
      status: { level: "ok", remaining_allowance_usd: 4.95 },
      unrealized_pnl_usd: 0,
      return_pct: -0.1,
    },
  ],
  positions: [
    {
      id: 801,
      strategy: "carry",
      symbol: "ETH/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 0.028,
      entry_price: 3248.0,
      margin_usd: 9.1,
      notional_usd: 90.94,
      stop: 3201.0,
      target: 3330.0,
      liq_price_est: 2960.0,
      funding_paid_usd: 0.04,
      planned_risk_usd: 1.32,
      opened_ms: NOW - 7 * HOUR,
      mark_price: 3254.4,
      unrealized_pnl_usd: 0.18,
      corr_cluster: "ETH-beta",
    },
    {
      id: 802,
      strategy: "pairs",
      symbol: "BTC/USDT:USDT",
      side: "short",
      leverage: 10,
      qty: 0.00135,
      entry_price: 67240.0,
      margin_usd: 9.1,
      notional_usd: 90.77,
      stop: 68010.0,
      target: 65900.0,
      liq_price_est: 73800.0,
      funding_paid_usd: -0.02,
      planned_risk_usd: 1.04,
      opened_ms: NOW - 3 * HOUR,
      mark_price: 67188.0,
      unrealized_pnl_usd: 0.07,
      corr_cluster: "BTC-beta",
    },
  ],
  signals: [
    {
      id: 9107,
      ts_ms: NOW - 12 * MIN,
      strategy: "voltarget",
      symbol: "SOL/USDT:USDT",
      action: "long",
      approved: false,
      reject_reason: "Strategy locked — trailing allowance exhausted",
      details: "Trend filter positive but vol_target_trend is locked for the session",
    },
    {
      id: 9106,
      ts_ms: NOW - 48 * MIN,
      strategy: "pairs",
      symbol: "BTC/USDT:USDT",
      action: "short",
      approved: true,
      reject_reason: null,
      details: "BTC/ETH spread 2.1σ rich; net-neutral leg sized to $1.04 risk",
    },
    {
      id: 9105,
      ts_ms: NOW - 7 * HOUR,
      strategy: "carry",
      symbol: "ETH/USDT:USDT",
      action: "long",
      approved: true,
      reject_reason: null,
      details: "Basis calm and positive; carry leg within allowance",
    },
    {
      id: 9104,
      ts_ms: NOW - 9 * HOUR,
      strategy: "seasonality",
      symbol: "BTC/USDT:USDT",
      action: "long",
      approved: false,
      reject_reason: "Outside defined intraday window",
      details: "Window gate closed; signal logged only",
    },
  ],
  trades: [
    {
      id: 751,
      strategy: "carry",
      symbol: "ETH/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 0.03,
      entry_price: 3180.0,
      exit_price: 3226.0,
      stop_initial: 3140.0,
      stop_final: 3190.0,
      target: 3260.0,
      margin_usd: 9.54,
      notional_usd: 95.4,
      entry_fee_usd: 0.05,
      exit_fee_usd: 0.05,
      funding_usd: 0.06,
      net_pnl_usd: 1.19,
      mfe_pct: 1.6,
      mae_pct: -0.3,
      entry_ms: NOW - 3 * DAY - 11 * HOUR,
      exit_ms: NOW - 3 * DAY,
      exit_reason: "target",
      rationale: "Calm positive basis; carry closed into target on prior-bar signal.",
    },
    {
      id: 752,
      strategy: "voltarget",
      symbol: "BTC/USDT:USDT",
      side: "long",
      leverage: 10,
      qty: 0.0014,
      entry_price: 68010.0,
      exit_price: 66980.0,
      stop_initial: 66950.0,
      stop_final: 66950.0,
      target: 70100.0,
      margin_usd: 9.52,
      notional_usd: 95.21,
      entry_fee_usd: 0.05,
      exit_fee_usd: 0.05,
      funding_usd: -0.03,
      net_pnl_usd: -1.57,
      mfe_pct: 0.4,
      mae_pct: -1.6,
      entry_ms: NOW - 6 * DAY - 5 * HOUR,
      exit_ms: NOW - 6 * DAY,
      exit_reason: "stop",
      rationale: "Vol-scaled trend entry invalidated on reversal; stop honoured, never widened.",
    },
  ],
  opportunities: {
    "BTC/USDT:USDT": {
      carry: { action: null, reason: "Basis noisy — stand aside" },
      pairs: { action: "short", reason: "BTC/ETH spread 2.1σ rich" },
      seasonality: { action: null, reason: "Outside defined window" },
      voltarget: { action: null, reason: "Strategy locked this session" },
      liqsweep: { action: null, reason: "No stop-run wick detected" },
    },
    "ETH/USDT:USDT": {
      carry: { action: "long", reason: "Calm positive basis within allowance" },
      pairs: { action: "long", reason: "Spread long leg vs BTC short" },
      seasonality: { action: null, reason: "Window closed" },
      voltarget: { action: null, reason: "Strategy locked this session" },
      liqsweep: { action: null, reason: "Range intact" },
    },
    "SOL/USDT:USDT": {
      carry: { action: null, reason: "Basis too volatile" },
      pairs: { action: null, reason: "No cointegrated partner in window" },
      seasonality: { action: null, reason: "Outside defined window" },
      voltarget: { action: "long", reason: "Trend positive (blocked — locked)" },
      liqsweep: { action: null, reason: "No sweep structure" },
    },
  },
  equity_curve: resEq,
  audit: [
    { id: 61, ts_ms: NOW - 5 * MIN, level: "info", category: "scanner", message: "Research scan complete: 3 symbols × 5 strategies, 1 entry, nothing hidden" },
    { id: 60, ts_ms: NOW - 12 * MIN, level: "warning", category: "risk", message: "vol_target_trend locked — trailing allowance exhausted; new entries blocked" },
    { id: 59, ts_ms: NOW - 48 * MIN, level: "info", category: "execution", message: "Simulated fill BTC pairs short 0.00135 @ 67,240.00 (half-spread + 2bps model)" },
    { id: 58, ts_ms: NOW - 3 * HOUR, level: "warning", category: "risk", message: "stat_pairs remaining allowance $1.34 — below $2 soft floor, monitoring" },
    { id: 57, ts_ms: NOW - 6 * DAY, level: "info", category: "risk", message: "vol_target_trend stop honoured without widening on BTC reversal" },
  ],
};

// ---------- Unified strategy comparison (DEMO) ----------
// 10 forward-paper strategies across both labs. Ranks 1..10 by net P&L.
// NOT a backtest — thin samples are flagged `insufficient`.

export const mockStrategies: Strategies = {
  count: 10,
  note:
    "Forward-paper diagnostics only — live simulated results across both labs. These are not backtests and never validated returns; samples flagged as insufficient are far too small to draw any conclusion from.",
  strategies: [
    {
      lab: "research", key: "carry", name: "Basis Carry",
      allocation_usd: 50, cash_usd: 50.73, equity_usd: 50.91,
      unrealized_pnl_usd: 0.18, realized_pnl_usd: 0.73, return_pct: 1.82,
      open_positions: 1, leverage: 10, locked: false,
      trade_count: 6, win_rate_pct: 66.7, profit_factor: 1.84, expectancy_usd: 0.19,
      max_drawdown_realized_usd: 1.2, fees_usd: 0.61, funding_usd: 0.14,
      sample: "developing", rank_by_net_pnl: 1,
    },
    {
      lab: "extreme", key: "trend", name: "Trend Rider",
      allocation_usd: 50, cash_usd: 51.84, equity_usd: 51.84,
      unrealized_pnl_usd: 0, realized_pnl_usd: 1.84, return_pct: 3.68,
      open_positions: 0, leverage: 10, locked: false,
      trade_count: 5, win_rate_pct: 60.0, profit_factor: 1.52, expectancy_usd: 0.37,
      max_drawdown_realized_usd: 2.1, fees_usd: 0.52, funding_usd: -0.12,
      sample: "developing", rank_by_net_pnl: 2,
    },
    {
      lab: "research", key: "liqsweep", name: "Liquidity Sweep",
      allocation_usd: 50, cash_usd: 49.95, equity_usd: 49.95,
      unrealized_pnl_usd: 0, realized_pnl_usd: -0.05, return_pct: -0.1,
      open_positions: 0, leverage: 10, locked: false,
      trade_count: 2, win_rate_pct: 50.0, profit_factor: 0.94, expectancy_usd: -0.03,
      max_drawdown_realized_usd: 0.4, fees_usd: 0.2, funding_usd: 0.01,
      sample: "insufficient", rank_by_net_pnl: 3,
    },
    {
      lab: "research", key: "seasonality", name: "Intraday Seasonality",
      allocation_usd: 50, cash_usd: 49.6, equity_usd: 49.6,
      unrealized_pnl_usd: 0, realized_pnl_usd: -0.4, return_pct: -0.8,
      open_positions: 0, leverage: 10, locked: false,
      trade_count: 1, win_rate_pct: null, profit_factor: null, expectancy_usd: null,
      max_drawdown_realized_usd: 0.4, fees_usd: 0.1, funding_usd: 0.0,
      sample: "insufficient", rank_by_net_pnl: 4,
    },
    {
      lab: "extreme", key: "funding", name: "Funding Skew",
      allocation_usd: 50, cash_usd: 49.52, equity_usd: 49.52,
      unrealized_pnl_usd: 0, realized_pnl_usd: -0.48, return_pct: -0.96,
      open_positions: 0, leverage: 10, locked: false,
      trade_count: 4, win_rate_pct: 50.0, profit_factor: 0.88, expectancy_usd: -0.12,
      max_drawdown_realized_usd: 1.0, fees_usd: 0.4, funding_usd: 0.22,
      sample: "developing", rank_by_net_pnl: 5,
    },
    {
      lab: "extreme", key: "breakout", name: "Volatility Breakout",
      allocation_usd: 50, cash_usd: 27.1, equity_usd: 48.22,
      unrealized_pnl_usd: -0.42, realized_pnl_usd: -1.36, return_pct: -3.56,
      open_positions: 1, leverage: 10, locked: false,
      trade_count: 7, win_rate_pct: 42.9, profit_factor: 0.71, expectancy_usd: -0.19,
      max_drawdown_realized_usd: 3.2, fees_usd: 0.74, funding_usd: -0.18,
      sample: "developing", rank_by_net_pnl: 6,
    },
    {
      lab: "research", key: "pairs", name: "Stat Pairs",
      allocation_usd: 50, cash_usd: 48.11, equity_usd: 48.18,
      unrealized_pnl_usd: 0.07, realized_pnl_usd: -1.89, return_pct: -3.64,
      open_positions: 1, leverage: 10, locked: false,
      trade_count: 8, win_rate_pct: 37.5, profit_factor: 0.76, expectancy_usd: -0.23,
      max_drawdown_realized_usd: 2.6, fees_usd: 0.82, funding_usd: -0.09,
      sample: "developing", rank_by_net_pnl: 7,
    },
    {
      lab: "extreme", key: "momo", name: "Momentum Burst",
      allocation_usd: 50, cash_usd: 47.73, equity_usd: 47.73,
      unrealized_pnl_usd: 0, realized_pnl_usd: -2.27, return_pct: -4.54,
      open_positions: 0, leverage: 10, locked: false,
      trade_count: 6, win_rate_pct: 33.3, profit_factor: 0.64, expectancy_usd: -0.38,
      max_drawdown_realized_usd: 3.5, fees_usd: 0.6, funding_usd: -0.07,
      sample: "developing", rank_by_net_pnl: 8,
    },
    {
      lab: "extreme", key: "meanrev", name: "Mean Reversion",
      allocation_usd: 50, cash_usd: 46.9, equity_usd: 46.9,
      unrealized_pnl_usd: 0, realized_pnl_usd: -3.1, return_pct: -6.2,
      open_positions: 0, leverage: 10, locked: false,
      trade_count: 9, win_rate_pct: 44.4, profit_factor: 0.58, expectancy_usd: -0.34,
      max_drawdown_realized_usd: 4.1, fees_usd: 0.9, funding_usd: 0.03,
      sample: "developing", rank_by_net_pnl: 9,
    },
    {
      lab: "research", key: "voltarget", name: "Vol-Target Trend",
      allocation_usd: 50, cash_usd: 46.18, equity_usd: 46.18,
      unrealized_pnl_usd: 0, realized_pnl_usd: -3.82, return_pct: -7.64,
      open_positions: 0, leverage: 10, locked: true,
      trade_count: 7, win_rate_pct: 28.6, profit_factor: 0.49, expectancy_usd: -0.55,
      max_drawdown_realized_usd: 4.6, fees_usd: 0.7, funding_usd: -0.11,
      sample: "developing", rank_by_net_pnl: 10,
    },
  ],
};

// Deterministic pseudo-random candles so the DEMO chart is stable per symbol/tf.
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TF_MS: Record<string, number> = {
  "5m": 5 * MIN,
  "15m": 15 * MIN,
  "1h": HOUR,
  "4h": 4 * HOUR,
  "1d": DAY,
};

export function mockCandles(symbol: string, tf: string, limit = 300): CandleResponse {
  const step = TF_MS[tf] ?? HOUR;
  let seed = 7;
  for (const ch of symbol + tf) seed = (seed * 31 + ch.charCodeAt(0)) | 0;
  const rnd = mulberry32(seed);
  const base = symbol.startsWith("BTC") ? 67000 : symbol.startsWith("ETH") ? 3250 : symbol.startsWith("SOL") ? 143 : 50 + rnd() * 200;
  const candles: CandleResponse["candles"] = [];
  // Align to the timeframe grid so repeated fetches line up.
  const last = Math.floor(NOW / step) * step;
  let close = base * (0.92 + rnd() * 0.08);
  for (let i = limit - 1; i >= 0; i--) {
    const ts = last - i * step;
    const drift = (rnd() - 0.485) * base * 0.006;
    const open = close;
    close = Math.max(base * 0.5, open + drift);
    const high = Math.max(open, close) + rnd() * base * 0.003;
    const low = Math.min(open, close) - rnd() * base * 0.003;
    const vol = 40 + rnd() * 300;
    const r = (x: number) => Math.round(x * 100) / 100;
    candles.push([ts, r(open), r(high), r(low), r(close), Math.round(vol * 10) / 10]);
  }
  const entryIdx = Math.max(0, candles.length - 40);
  const exitIdx = Math.max(0, candles.length - 12);
  return {
    symbol,
    tf,
    candles,
    markers: [
      { ts_ms: candles[entryIdx][0], kind: "entry", side: "long", price: candles[entryIdx][4], label: "DEMO entry" },
      { ts_ms: candles[exitIdx][0], kind: "exit", side: "long", price: candles[exitIdx][4], label: "DEMO exit" },
    ],
    overlays: {
      stop: Math.round(close * 0.98 * 100) / 100,
      target: Math.round(close * 1.04 * 100) / 100,
      liq: Math.round(close * 0.81 * 100) / 100,
    },
  };
}
