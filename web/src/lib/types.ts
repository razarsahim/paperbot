// API contract types for the PaperBot Pro backend (http://127.0.0.1:8777).
// PAPER TRADING ONLY — every value in this system is simulated.

export type Source = "live" | "demo";

export interface ApiResult<T> {
  data: T;
  source: Source;
}

// ---------- /api/health ----------
export interface EngineLegacy {
  running: boolean;
  last_tick_ms: number | null;
}

export interface EnginePro {
  running: boolean;
  last_scan_ms: number | null;
  auto_entry_enabled: boolean;
}

export interface DataSourceHealth {
  name: string;
  ok: boolean;
  last_ok_ms: number | null;
  detail: string;
}

export interface Health {
  status: "ok" | "degraded";
  engines: {
    legacy: EngineLegacy;
    pro: EnginePro;
  };
  data_sources: DataSourceHealth[];
}

// ---------- /api/overview ----------
export interface OverviewRisk {
  open_positions: number;
  max_positions: number;
  combined_planned_risk_pct: number;
  risk_ceiling_pct: number;
  daily_locked: boolean;
  total_locked: boolean;
  trading_enabled: boolean;
  pause_reason: string | null;
}

export interface SleeveBalance {
  balance_usd: number;
  available_usd: number;
}

export interface HypeSleeveBalance extends SleeveBalance {
  watch_only: boolean;
}

export interface LegacyOverview {
  symbol: string;
  equity_gbp: number;
  cash_gbp: number;
  open_position: boolean;
  closed_trades: number;
  locked_total: boolean;
}

export interface Overview {
  mode: "PAPER";
  ts_ms: number;
  equity_usd: number;
  cash_usd: number;
  margin_used_usd: number;
  free_margin_usd: number;
  exposure_notional_usd: number;
  daily_pnl_usd: number;
  total_pnl_usd: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number;
  risk: OverviewRisk;
  sleeves: {
    core: SleeveBalance;
    hype: HypeSleeveBalance;
  };
  legacy: LegacyOverview;
}

// ---------- /api/universe ----------
export interface InstrumentInfo {
  exchange: string;
  symbol: string;
  taker_fee: number;
  maint_margin_rate: number | null;
  tick_size: number | null;
  lot_size: number | null;
  funding_rate: number | null;
  mark_price: number | null;
  spread_pct: number | null;
  data_age_s: number | null;
}

export interface UniverseAsset {
  rank: number;
  coingecko_id: string;
  symbol: string;
  name: string;
  price_usd: number;
  change_24h_pct: number;
  market_cap_usd: number;
  volume_24h_usd: number;
  trend: "up" | "down" | "flat";
  atr_pct: number | null;
  rsi: number | null;
  signal: "long" | "short" | "none" | null;
  eligible: boolean;
  reason: string | null;
  instrument: InstrumentInfo | null;
}

export interface UniverseChange {
  date: string;
  added: string[];
  removed: string[];
}

export interface Universe {
  updated_at_ms: number | null;
  stale: boolean;
  assets: UniverseAsset[];
  changes: UniverseChange[];
}

// ---------- /api/positions ----------
export type Sleeve = "core" | "hype";
export type Side = "long" | "short";

export interface Position {
  id: number;
  symbol: string;
  side: Side;
  leverage: number;
  qty: number;
  entry_price: number;
  mark_price: number | null;
  liq_price_est: number;
  stop: number;
  target: number;
  margin_usd: number;
  notional_usd: number;
  unrealized_pnl_usd: number | null;
  funding_paid_usd: number;
  fees_paid_usd: number;
  planned_risk_pct: number;
  opened_at_ms: number;
  sleeve: Sleeve;
}

// ---------- /api/trades ----------
export interface Trade {
  id: number;
  symbol: string;
  side: Side;
  leverage: number;
  qty: number;
  entry_price: number;
  exit_price: number;
  stop_initial: number;
  stop_final: number;
  target: number;
  margin_usd: number;
  notional_usd: number;
  entry_fee_usd: number;
  exit_fee_usd: number;
  funding_usd: number;
  slippage_model: string;
  net_pnl_usd: number;
  mfe_pct: number | null;
  mae_pct: number | null;
  entry_ms: number;
  exit_ms: number;
  exit_reason: string;
  rationale: string;
  indicator_snapshot: Record<string, number> | null;
  sleeve: Sleeve;
}

// ---------- /api/signals ----------
export interface SignalEvent {
  ts_ms: number;
  symbol: string;
  action: "long" | "short";
  approved: boolean;
  reject_reason: string | null;
  details: string;
}

// ---------- /api/analytics ----------
export interface Analytics {
  equity_curve: [number, number][];
  drawdown_curve: [number, number][];
  monthly: { month: string; pnl_usd: number }[];
  by_asset: { symbol: string; trades: number; pnl_usd: number }[];
  benchmarks: { cash_usd: number; btc_hold_pct: number | null };
  validation: { exists: boolean; summary: string | null };
}

// ---------- /api/hype ----------
export type HypeStatus = "WATCH_ONLY" | "REJECTED" | "ELIGIBLE";

export interface HypeToken {
  symbol: string;
  name: string;
  chain: string;
  contract: string | null;
  pool_age_hours: number | null;
  liquidity_usd: number | null;
  volume_24h_usd: number | null;
  score: number;
  flags: string[];
  evidence: { source: string; note: string }[];
  status: HypeStatus;
  ts_ms: number;
  explanation: string;
}

export interface HypeRadar {
  sleeve: {
    balance_usd: number;
    spent_usd: number;
    loss_cap_usd: number;
    watch_only: boolean;
  };
  tokens: HypeToken[];
}

// ---------- /api/audit ----------
export interface AuditEntry {
  ts_ms: number;
  level: "info" | "warning" | "error";
  category: string;
  message: string;
}

// ---------- /api/settings ----------
export type Settings = Record<string, string | number | boolean>;

// ---------- /api/lab ----------
// Extreme Lab: a speculative PAPER-ONLY research simulation (virtual $250).
export interface LabStatus {
  live: boolean;
  last_scan_ms: number | null;
  auto_entry: boolean;
  locked: boolean;
  lock_reason: string | null;
  manual_pause: boolean;
}

export interface LabCapital {
  initial_usd: number;
  equity_usd: number;
  cash_usd: number;
  margin_used_usd: number;
  unrealized_usd: number;
  peak_equity_usd: number;
  threshold_usd: number;
  remaining_allowance_usd: number;
}

export interface LabStrategy {
  key: string;
  name: string;
  display_name: string;
  description: string;
  allocation_usd: number;
  cash_usd: number;
  realized_pnl_usd: number;
  open_symbols: string[];
}

export interface LabPosition {
  id: number;
  strategy: string;
  symbol: string;
  side: "long" | "short";
  leverage: number;
  qty: number;
  entry_price: number;
  margin_usd: number;
  notional_usd: number;
  stop: number;
  target: number | null;
  liq_price_est: number;
  funding_paid_usd: number;
  planned_risk_usd: number;
  opened_ms: number;
  mark_price: number | null;
  unrealized_pnl_usd: number | null;
}

export interface LabSignal {
  id: number;
  ts_ms: number;
  strategy: string;
  symbol: string;
  action: string;
  approved: boolean;
  reject_reason: string | null;
  details: string;
}

export interface LabTrade {
  id: number;
  strategy: string;
  symbol: string;
  side: string;
  leverage: number;
  qty: number;
  entry_price: number;
  exit_price: number;
  stop_initial: number;
  stop_final: number;
  target: number | null;
  margin_usd: number;
  notional_usd: number;
  entry_fee_usd: number;
  exit_fee_usd: number;
  funding_usd: number;
  net_pnl_usd: number;
  mfe_pct: number | null;
  mae_pct: number | null;
  entry_ms: number;
  exit_ms: number;
  exit_reason: string;
  rationale: string;
}

export interface LabAudit {
  id: number;
  ts_ms: number;
  level: string;
  category: string;
  message: string;
}

export interface Lab {
  status: LabStatus;
  capital: LabCapital;
  strategies: LabStrategy[];
  positions: LabPosition[];
  signals: LabSignal[];
  trades: LabTrade[];
  opportunities: Record<string, Record<string, { action: string | null; reason: string }>>;
  /** [ts_ms, equity_usd, threshold_usd] */
  equity_curve: [number, number, number][];
  audit: LabAudit[];
}

// ---------- /api/lab/stream (SSE `lab_live` events) ----------
// Continuously updating Lab P&L. Still PAPER ONLY — simulated funds.
export type LabLiveStatus = "LIVE" | "STALE" | "DISCONNECTED";

export interface LabLivePosition {
  id: number;
  strategy: string;
  symbol: string;
  side: Side;
  leverage: number;
  qty: number;
  entry_price: number;
  mark_price: number | null;
  last_price: number | null;
  bid: number | null;
  ask: number | null;
  notional_usd: number;
  margin_usd: number;
  stop: number;
  liq_price_est: number;
  funding_paid_usd: number;
  unrealized_pnl_usd: number | null;
  unrealized_pct_on_margin: number | null;
  stop_distance_pct: number | null;
  liq_distance_pct: number | null;
  exchange_ts_ms: number | null;
}

export interface LabLiveCapital {
  initial_usd: number;
  equity_usd: number;
  cash_usd: number;
  margin_used_usd: number;
  unrealized_usd: number;
  realized_usd: number;
  peak_equity_usd: number;
  threshold_usd: number;
  remaining_allowance_usd: number;
  complete: boolean;
}

export interface LabLive {
  live_status: LabLiveStatus;
  /** API server clock at emit. */
  server_ts_ms: number;
  /** Age of the engine snapshot at emit. */
  publish_age_ms?: number;
  /** Engine valuation time. */
  ts_ms?: number;
  /** Newest exchange ticker timestamp used. */
  exchange_ts_ms?: number | null;
  locked?: boolean;
  breached?: boolean;
  /** Optional connected/disconnected notes. */
  stream_status?: string;
  positions?: LabLivePosition[];
  /** null when DISCONNECTED. */
  capital?: LabLiveCapital | null;
}

// ---------- /api/candles ----------
export interface CandleMarker {
  ts_ms: number;
  kind: "entry" | "exit";
  side: Side;
  price: number;
  label: string;
}

export interface CandleResponse {
  symbol: string;
  tf: string;
  /** [ts_ms, open, high, low, close, volume] */
  candles: [number, number, number, number, number, number][];
  markers: CandleMarker[];
  overlays: {
    stop: number | null;
    target: number | null;
    liq: number | null;
  };
}
