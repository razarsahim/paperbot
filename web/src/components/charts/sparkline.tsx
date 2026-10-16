"use client";

import {
  AreaSeries,
  createChart,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { baseChartOptions, useChartColors } from "./chart-theme";

export function Sparkline({
  points,
  height = 90,
}: {
  /** [ts_ms, value] */
  points: [number, number][];
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;
    const chart = createChart(el, {
      ...baseChartOptions(colors),
      rightPriceScale: { visible: false },
      timeScale: { visible: false },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      handleScroll: false,
      handleScale: false,
      crosshair: { horzLine: { visible: false }, vertLine: { visible: false } },
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: colors.line,
      topColor: colors.areaTop,
      bottomColor: colors.areaBottom,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(
      points.map(([t, v]) => ({ time: (t / 1000) as UTCTimestamp, value: v }))
    );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points, colors]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
