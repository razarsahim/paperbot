"use client";

import {
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { macd, rsi } from "@/lib/indicators";
import type { CandleResponse } from "@/lib/types";
import { baseChartOptions, useChartColors } from "./chart-theme";

function toLine(
  times: UTCTimestamp[],
  values: (number | null)[]
): { time: UTCTimestamp; value: number }[] {
  const out: { time: UTCTimestamp; value: number }[] = [];
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v !== null) out.push({ time: times[i], value: v });
  }
  return out;
}

export function RsiPane({ data, height = 140 }: { data: CandleResponse; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el || data.candles.length === 0) return;
    const chart = createChart(el, baseChartOptions(colors));
    const times = data.candles.map((c) => (c[0] / 1000) as UTCTimestamp);
    const closes = data.candles.map((c) => c[4]);
    const series = chart.addSeries(LineSeries, {
      color: colors.blue,
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(toLine(times, rsi(closes, 14)));
    for (const level of [30, 70]) {
      series.createPriceLine({
        price: level,
        color: colors.border,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: false,
        title: String(level),
      });
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, colors]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}

export function MacdPane({ data, height = 140 }: { data: CandleResponse; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el || data.candles.length === 0) return;
    const chart = createChart(el, baseChartOptions(colors));
    const times = data.candles.map((c) => (c[0] / 1000) as UTCTimestamp);
    const closes = data.candles.map((c) => c[4]);
    const points = macd(closes);

    const histSeries = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
    });
    histSeries.setData(
      points.flatMap((p, i) =>
        p.hist === null
          ? []
          : [
              {
                time: times[i],
                value: p.hist,
                color: p.hist >= 0 ? `${colors.up}88` : `${colors.down}88`,
              },
            ]
      )
    );
    const macdSeries = chart.addSeries(LineSeries, {
      color: colors.blue,
      lineWidth: 2,
      priceLineVisible: false,
    });
    macdSeries.setData(toLine(times, points.map((p) => p.macd)));
    const signalSeries = chart.addSeries(LineSeries, {
      color: colors.amber,
      lineWidth: 1,
      priceLineVisible: false,
    });
    signalSeries.setData(toLine(times, points.map((p) => p.signal)));

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, colors]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
