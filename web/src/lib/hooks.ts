"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { eventsUrl, getLab, getOverview } from "./api";
import type { ApiResult, Lab, Overview, Source } from "./types";

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
