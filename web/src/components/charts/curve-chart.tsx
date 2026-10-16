"use client";

import {
  AreaSeries,
  BaselineSeries,
  createChart,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { baseChartOptions, useChartColors } from "./chart-theme";

/** Area curve (equity) or baseline curve (drawdown, values <= 0). */
export function CurveChart({
  points,
  height = 260,
  mode = "area",
}: {
  /** [ts_ms, value] */
  points: [number, number][];
  height?: number;
  mode?: "area" | "baseline";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;
    const chart = createChart(el, baseChartOptions(colors));
    const data = points.map(([t, v]) => ({
      time: (t / 1000) as UTCTimestamp,
      value: v,
    }));
    if (mode === "area") {
      const series = chart.addSeries(AreaSeries, {
        lineColor: colors.line,
        topColor: colors.areaTop,
        bottomColor: colors.areaBottom,
        lineWidth: 2,
      });
      series.setData(data);
    } else {
      const series = chart.addSeries(BaselineSeries, {
        baseValue: { type: "price", price: 0 },
        topLineColor: colors.up,
        topFillColor1: `${colors.up}22`,
        topFillColor2: `${colors.up}05`,
        bottomLineColor: colors.down,
        bottomFillColor1: `${colors.down}05`,
        bottomFillColor2: `${colors.down}33`,
        lineWidth: 2,
      });
      series.setData(data);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points, colors, mode]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
