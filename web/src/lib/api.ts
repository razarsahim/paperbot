// Typed API client for the local PaperBot backend.
// Honesty rule: every fetch either returns real backend data tagged
// source:"live", or falls back to typed mock data tagged source:"demo".
// Consumers must surface that tag next to any number they render.

import {
  mockAnalytics,
  mockAudit,
  mockCandles,
  mockHealth,
  mockHype,
  mockOverview,
  mockPositions,
  mockSettings,
  mockSignals,
  mockTrades,
  mockUniverse,
} from "./mock";
import type {
  Analytics,
  ApiResult,
  AuditEntry,
  CandleResponse,
  Health,
  HypeRadar,
  Overview,
  Position,
  Settings,
  SignalEvent,
  Trade,
  Universe,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8777";

const TIMEOUT_MS = 4000;

async function getJson<T>(path: string, fallback: T): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as T;
    return { data, source: "live" };
  } catch {
    return { data: fallback, source: "demo" };
  }
}

export const getHealth = () => getJson<Health>("/api/health", mockHealth);

export const getOverview = () => getJson<Overview>("/api/overview", mockOverview);

export const getUniverse = () => getJson<Universe>("/api/universe", mockUniverse);

export const getPositions = () => getJson<Position[]>("/api/positions", mockPositions);

export function getTrades(params?: {
  limit?: number;
  symbol?: string;
  sleeve?: string;
}): Promise<ApiResult<Trade[]>> {
  const q = new URLSearchParams();
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.symbol) q.set("symbol", params.symbol);
  if (params?.sleeve) q.set("sleeve", params.sleeve);
  const qs = q.toString();
  return getJson<Trade[]>(`/api/trades${qs ? `?${qs}` : ""}`, mockTrades);
}

export function getTrade(id: number): Promise<ApiResult<Trade>> {
  const fallback = mockTrades.find((t) => t.id === id) ?? mockTrades[0];
  return getJson<Trade>(`/api/trades/${id}`, fallback);
}

export const getSignals = (limit = 50) =>
  getJson<SignalEvent[]>(`/api/signals?limit=${limit}`, mockSignals);

export const getAnalytics = () => getJson<Analytics>("/api/analytics", mockAnalytics);

export const getHype = () => getJson<HypeRadar>("/api/hype", mockHype);

export const getAudit = (limit = 100) =>
  getJson<AuditEntry[]>(`/api/audit?limit=${limit}`, mockAudit);

export const getSettings = () => getJson<Settings>("/api/settings", mockSettings);

export function getCandles(
  symbol: string,
  tf: string,
  limit = 300
): Promise<ApiResult<CandleResponse>> {
  const q = new URLSearchParams({ symbol, tf, limit: String(limit) });
  return getJson<CandleResponse>(
    `/api/candles?${q.toString()}`,
    mockCandles(symbol, tf, limit)
  );
}

export const tradesCsvUrl = `${API_BASE}/api/export/trades.csv`;
export const eventsUrl = `${API_BASE}/api/events`;
