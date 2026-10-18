"use client";

import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  LineType,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { baseChartOptions, useChartColors } from "./chart-theme";

export interface ReplayMarker {
  ts_ms: number;
  kind: "entry" | "exit";
  side: "long" | "short";
  label: string;
  win?: boolean;
}

/** Candles revealed up to the replay cursor, with entry/exit markers. */
export function ReplayPriceChart({
  candles,
  markers,
  cursorMs,
  height = 380,
}: {
  candles: number[][];
  markers: ReplayMarker[];
  cursorMs: number;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // a 1h candle is shown only once it has fully closed at the cursor
    const visible = candles.filter((c) => c[0] + 3_600_000 <= cursorMs);
    if (visible.length === 0) return;
    const chart = createChart(el, baseChartOptions(colors));
    const series = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });
    series.setData(
      visible.map(([t, o, h, l, c]) => ({
        time: (t / 1000) as UTCTimestamp,
        open: o,
        high: h,
        low: l,
        close: c,
      }))
    );
    const lastBar = visible[visible.length - 1][0];
    const snap = (ms: number) => Math.min(ms - (ms % 3_600_000), lastBar);
    const m: SeriesMarker<Time>[] = markers
      .filter((x) => x.ts_ms <= cursorMs)
      .sort((a, b) => a.ts_ms - b.ts_ms)
      .map((x) => ({
        time: (snap(x.ts_ms) / 1000) as UTCTimestamp,
        position:
          x.kind === "entry"
            ? x.side === "long"
              ? ("belowBar" as const)
              : ("aboveBar" as const)
            : x.side === "long"
              ? ("aboveBar" as const)
              : ("belowBar" as const),
        shape:
          x.kind === "entry"
            ? x.side === "long"
              ? ("arrowUp" as const)
              : ("arrowDown" as const)
            : ("circle" as const),
        color:
          x.kind === "entry"
            ? colors.blue
            : x.win
              ? colors.up
              : colors.down,
        text: x.label,
      }));
    if (m.length) createSeriesMarkers(series, m);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles, markers, cursorMs, colors]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}

const PALETTE = [
  "#60a5fa", "#f59e0b", "#a78bfa", "#34d399", "#f472b6",
  "#22d3ee", "#facc15", "#fb7185", "#4ade80", "#c084fc",
];

export function seriesColor(i: number): string {
  return PALETTE[i % PALETTE.length];
}

/** Several equity curves truncated at the cursor, plus an optional limit line. */
export function MultiLineChart({
  series,
  cursorMs,
  threshold,
  height = 300,
}: {
  series: { name: string; points: [number, number][]; color: string }[];
  cursorMs: number;
  threshold?: [number, number][];
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el || series.length === 0) return;
    const chart = createChart(el, baseChartOptions(colors));
    for (const s of series) {
      const pts = s.points.filter(([t]) => t <= cursorMs);
      if (pts.length === 0) continue;
      const line = chart.addSeries(LineSeries, {
        color: s.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: s.name,
      });
      line.setData(pts.map(([t, v]) => ({ time: (t / 1000) as UTCTimestamp, value: v })));
    }
    if (threshold) {
      const pts = threshold.filter(([t]) => t <= cursorMs);
      if (pts.length) {
        const limit = chart.addSeries(LineSeries, {
          color: colors.red,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          lineType: LineType.WithSteps,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          title: "lock threshold",
        });
        limit.setData(pts.map(([t, v]) => ({ time: (t / 1000) as UTCTimestamp, value: v })));
      }
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, cursorMs, threshold, colors]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
