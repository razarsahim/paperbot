"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { eventsUrl, getLab, getOverview, labStreamUrl } from "./api";
import type { ApiResult, Lab, LabLive, Overview, Source } from "./types";

export interface Loadable<T> {
  data: T | null;
  source: Source;
  loading: boolean;
  refresh: () => void;
}

/**
 * Poll an API-client function on an interval. The fetcher already handles
 * fallback-to-mock, so `source` always tells the truth about where the
 * currently displayed data came from.
 */
export function usePoll<T>(
  fetcher: () => Promise<ApiResult<T>>,
  intervalMs = 10_000,
  deps: unknown[] = []
): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [source, setSource] = useState<Source>("demo");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const run = async () => {
      const res = await fetcherRef.current();
      if (!alive) return;
      setData(res.data);
      setSource(res.source);
      setLoading(false);
    };
    void run();
    if (intervalMs > 0) timer = setInterval(run, intervalMs);
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick, ...deps]);

  return { data, source, loading, refresh };
}

/** One-shot fetch (no polling). */
export function useFetchOnce<T>(
  fetcher: () => Promise<ApiResult<T>>,
  deps: unknown[] = []
): Loadable<T> {
  return usePoll(fetcher, 0, deps);
}

/**
 * Overview with live updates: subscribes to the backend SSE stream for
 * `overview` events; if the stream errors it silently falls back to the
 * 10s polling that is always running underneath.
 */
/** Ticking clock for staleness displays; updates every `intervalMs`. */
export function useNow(intervalMs = 15_000): number {
  // 0 until mounted: callers treat that as "not stale yet". Date.now() must
  // not run during (pre)render — Next's static prerenderer rejects it.
  const [now, setNow] = useState<number>(0);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/**
 * Poll + SSE combo: polls `fetcher` every 10s and overlays the latest payload
 * from the named SSE event when the stream is healthy. SSE data always comes
 * from the real backend, so overlaid data is honestly tagged source:"live".
 */
function useSseResource<T>(
  fetcher: () => Promise<ApiResult<T>>,
  eventName: string
): Loadable<T> {
  const base = usePoll(fetcher, 10_000);
  const [sse, setSse] = useState<T | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;
    let es: EventSource | null = null;
    try {
      es = new EventSource(eventsUrl);
      es.addEventListener(eventName, (ev) => {
        try {
          setSse(JSON.parse((ev as MessageEvent).data) as T);
        } catch {
          // ignore malformed event, polling still covers us
        }
      });
      es.onerror = () => {
        // Fall back silently to polling.
        es?.close();
        setSse(null);
      };
    } catch {
      // EventSource construction failed — polling covers us.
    }
    return () => es?.close();
  }, [eventName]);

  if (sse) return { ...base, data: sse, source: "live", loading: false };
  return base;
}

export function useOverview(): Loadable<Overview> {
  return useSseResource(getOverview, "overview");
}

/** Extreme Lab state: `lab` SSE events with 10s polling fallback. */
export function useLab(): Loadable<Lab> {
  return useSseResource(getLab, "lab");
}

// ---------- Continuous Lab P&L stream (/api/lab/stream) ----------

export interface LabLiveState {
  /** Latest `lab_live` payload (throttled to <=1 render per 150ms, trailing edge). */
  live: LabLive | null;
  /** True while the EventSource is open. False means treat as DISCONNECTED. */
  connected: boolean;
  /** Client clock captured when the rendered payload was received (ms). */
  receivedAtMs: number | null;
}

const LAB_LIVE_RENDER_THROTTLE_MS = 150;
const LAB_LIVE_RECONNECT_BASE_MS = 2_000;
const LAB_LIVE_RECONNECT_MAX_MS = 30_000;

/**
 * Subscribe to the `lab_live` SSE stream. Reconnects with exponential backoff
 * (2s, 4s, 8s … capped at 30s) by closing and recreating the EventSource.
 * Re-renders are throttled to at most one per 150ms; the latest payload is
 * never dropped — a trailing flush always delivers it. No prices are ever
 * fabricated or interpolated: only payloads the backend actually sent are
 * stored, each with the client receipt time for honest latency display.
 */
export function useLabLive(): LabLiveState {
  const [state, setState] = useState<{
    live: LabLive | null;
    receivedAtMs: number | null;
  }>({ live: null, receivedAtMs: null });
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;

    let disposed = false;
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    // Trailing-edge throttle: latest pending payload wins, nothing dropped.
    let pending: { live: LabLive; receivedAtMs: number } | null = null;
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    let lastFlushMs = 0;

    const flush = () => {
      flushTimer = null;
      if (disposed || pending === null) return;
      const next = pending;
      pending = null;
      lastFlushMs = Date.now();
      setState({ live: next.live, receivedAtMs: next.receivedAtMs });
    };

    const push = (live: LabLive) => {
      pending = { live, receivedAtMs: Date.now() };
      if (flushTimer !== null) return; // trailing flush already scheduled
      const sinceLast = Date.now() - lastFlushMs;
      if (sinceLast >= LAB_LIVE_RENDER_THROTTLE_MS) {
        flush();
      } else {
        flushTimer = setTimeout(flush, LAB_LIVE_RENDER_THROTTLE_MS - sinceLast);
      }
    };

    const scheduleReconnect = () => {
      if (disposed || reconnectTimer !== null) return;
      const delay = Math.min(
        LAB_LIVE_RECONNECT_MAX_MS,
        LAB_LIVE_RECONNECT_BASE_MS * 2 ** attempt
      );
      attempt += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (disposed) return;
      try {
        es = new EventSource(labStreamUrl);
      } catch {
        scheduleReconnect();
        return;
      }
      es.onopen = () => {
        if (disposed) return;
        attempt = 0; // healthy again — reset backoff
        setConnected(true);
      };
      es.addEventListener("lab_live", (ev) => {
        if (disposed) return;
        try {
          push(JSON.parse((ev as MessageEvent).data) as LabLive);
        } catch {
          // Malformed event: ignore. Never synthesize a payload.
        }
      });
      es.onerror = () => {
        if (disposed) return;
        setConnected(false);
        es?.close();
        es = null;
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      if (flushTimer !== null) clearTimeout(flushTimer);
      es?.close();
    };
  }, []);

  return { live: state.live, connected, receivedAtMs: state.receivedAtMs };
}
