// Client for the CRH Lab API (http://127.0.0.1:8778). PAPER ONLY.
// Unlike lib/api.ts there is NO demo fallback: the CRH page shows nothing
// it did not get from the backend.

export const CRH_API_BASE =
  process.env.NEXT_PUBLIC_CRH_API_BASE ?? "http://127.0.0.1:8778";

export interface Trade {
  id: number;
  symbol: string;
  side: "long" | "short";
  leverage: number;
  qty: number;
  entry_price: number;
  exit_price: number;
  stop_initial: number;
  stop_final: number;
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
  planned_risk_usd?: number;
}

export interface OpenPos {
  id: number;
  symbol: string;
  side: "long" | "short";
  leverage: number;
  qty: number;
  entry_price: number;
  margin_usd: number;
  notional_usd: number;
  stop: number;
  initial_stop: number;
  liq_price_est: number;
  entry_fee_usd: number;
  funding_paid_usd: number;
  planned_risk_usd: number;
  opened_ms: number;
  rationale: string;
  mark: number | null;
  unrealized_pnl_usd: number | null;
}

export interface Signal {
  ts_ms: number;
  symbol: string;
  action: string;
  approved: boolean;
  reject_reason: string | null;
  details: string;
}

export interface Totals {
  initial_capital_usd: number;
  final_equity_usd: number;
  net_realized_pnl_usd: number;
  net_unrealized_pnl_usd: number;
  net_return_pct: number;
  completed_trades: number;
  open_positions_at_end: number;
  win_rate_pct: number | null;
  avg_win_usd: number | null;
  avg_loss_usd: number | null;
  profit_factor: number | null;
  expectancy_usd: number | null;
  max_drawdown_usd: number;
  max_drawdown_pct: number;
  fees_usd: number;
  funding_usd: number;
  slippage_usd_est: number;
  liquidations: number;
  largest_win_usd: number | null;
  largest_loss_usd: number | null;
  small_sample: boolean;
}

export interface Summary {
  label: string;
  config_label: string;
  is_baseline_rules: boolean;
  fidelity: string;
  window: { start: string; end_exclusive: string; start_ms: number; end_ms: number; hours: number };
  universe: string;
  eligible_instruments: number;
  candidate_signals: number;
  final_equity: number;
  net_return_pct: number;
  trades: number;
  open_at_end: number;
  max_drawdown_pct?: number;
  max_drawdown_usd?: number;
  locked: boolean;
  strategy_locked: boolean;
  capital: number;
  leverage: number;
  elapsed_s: number;
  stage_times_s: Record<string, number>;
  warnings_count: number;
}

export interface RunResult {
  run_id: string;
  params: Record<string, unknown>;
  config: Record<string, unknown>;
  summary: Summary;
  totals: Totals;
  trades: Trade[];
  open_at_end: OpenPos[];
  signals: Signal[];
  risk_events: { ts_ms: number; level: string; message: string }[];
  equity_curve: number[][]; // [t, equity, peak, threshold]
  daily: { date: string; start_equity: number; end_equity: number; change: number; realised_pnl: number; mark_to_market: number; closed_trades: number; fees_closed_trades: number; funding_paid: number }[];
  universe: { spec: string; note: string; daily: Record<string, string[]>; ineligible: Record<string, string> };
  instruments: Record<string, { bybit_symbol?: string; maint_margin_rate: number; contract_multiplier?: number }>;
  candidates: Record<string, number>;
  near_misses: Record<string, number>;
  data: { version: string; sources: string[]; fidelity: string; l2_missing: string[]; no_data: string[] };
  checks: { leakage: { ok: boolean }; accounting_identity_gap_usd: number; accounting_ok: boolean; stops_never_widened: boolean; mark_price_liquidation: { checked: number; mismatch: unknown[] }; unmonitored_cycles: number };
  warnings: string[];
  reused_from: string | null;
  lock_reason: string | null;
  locked: boolean;
  strategy_locked: boolean;
  final_cash: number;
}

export interface RunRow {
  run_id: string;
  created_ms: number;
  status: string;
  label: string;
  params: Record<string, unknown>;
  summary: Summary | null;
  error: string | null;
}

export interface Job {
  job_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  stage: string;
  fraction: number;
  overall: number;
  detail: string | null;
  run_id: string | null;
  reused: boolean;
  error: string | null;
  log: { t: number; stage: string; detail: string | null }[];
}

export interface ChartData {
  symbol: string;
  candles: number[][];
  markers: { ts_ms: number; kind: "entry" | "exit"; side: "long" | "short"; label: string; trade_id: number; win?: boolean }[];
  stops: { trade_id: number; from: number; to: number; initial: number; final: number }[];
  signals: { close_ts: number; drop_pct: number }[];
  window: { start_ms: number; end_ms: number };
}

export interface CompareRow {
  run_id: string;
  label: string;
  window: Summary["window"];
  universe: string;
  fidelity: string;
  capital: number;
  leverage: number;
  signal_timeframe: string;
  net_pnl: number;
  net_return_pct: number;
  trades: number;
  open_at_end: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number;
  max_drawdown_usd: number;
  largest_loss: number | null;
  liquidations: number;
  fees: number;
  funding: number;
  slippage: number;
  realized: number;
  unrealized: number;
  signals: number;
  approved: number;
  return_over_dd: number | null;
  equity_curve: [number, number][];
  symbols_traded: string[];
}

export interface Compare {
  runs: CompareRow[];
  flags: string[];
  verdict: string;
  signals_added_in_second: string[];
  signals_missing_in_second: string[];
}

export interface ScannerRow {
  symbol: string;
  status: string;
  change_24h_pct?: number | null;
  drop_condition?: boolean;
  hammer?: boolean;
  reason?: string;
  candle_close_ts?: number;
  signals?: number;
  near_misses?: number;
  worst_drop_pct?: number | null;
  last_signal_ts?: number | null;
  rejections?: string[];
  data?: string;
  error?: string;
}

export interface Scanner {
  label: string;
  rows: ScannerRow[];
  as_of_ms?: number;
  note?: string;
  ineligible?: Record<string, string>;
}

export interface Forward {
  label: string;
  available: boolean;
  reason?: string;
  last_scan_ms?: number | null;
  auto_entry?: boolean;
  lab_locked?: boolean;
  lab_lock_reason?: string | null;
  sleeve?: { allocation_usd: number; cash_usd: number; realized_pnl_usd: number; locked: boolean; lock_reason: string | null; equity_usd: number; margin_usd: number; unrealized_usd: number; return_pct: number; trades: number; win_rate_pct: number | null; profit_factor: number | null; fees_usd: number; funding_usd: number };
  positions?: Record<string, unknown>[];
  trades?: Record<string, unknown>[];
  signals?: Record<string, unknown>[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${CRH_API_BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const crh = {
  health: () => req<{ ok: boolean; runs: number; jobs: number }>("/api/crh/health"),
  presets: () => req<Record<string, unknown>>("/api/crh/presets"),
  start: (params: Record<string, unknown>, force = false) =>
    req<Job>(`/api/crh/backtests${force ? "?force=true" : ""}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  job: (id: string) => req<Job>(`/api/crh/jobs/${id}`),
  cancel: (id: string) => req<{ cancelled: boolean }>(`/api/crh/jobs/${id}/cancel`, { method: "POST" }),
  runs: () => req<RunRow[]>("/api/crh/runs"),
  run: (id: string) => req<RunResult>(`/api/crh/runs/${id}`),
  deleteRun: (id: string) => req<{ deleted: string }>(`/api/crh/runs/${id}`, { method: "DELETE" }),
  chart: (id: string, symbol: string) =>
    req<ChartData>(`/api/crh/runs/${id}/chart?symbol=${encodeURIComponent(symbol)}`),
  compare: (ids: string[]) => req<Compare>(`/api/crh/compare?ids=${ids.join(",")}`),
  scanner: (runId?: string, universe = "top50") =>
    req<Scanner>(runId ? `/api/crh/scanner?run_id=${runId}` : `/api/crh/scanner?universe=${universe}`),
  forward: () => req<Forward>("/api/crh/forward"),
  exportJsonUrl: (id: string) => `${CRH_API_BASE}/api/crh/runs/${id}/export.json`,
  exportCsvUrl: (id: string) => `${CRH_API_BASE}/api/crh/runs/${id}/export.csv`,
};
