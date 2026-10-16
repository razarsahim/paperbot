"use client";

import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { ema } from "@/lib/indicators";
import type { CandleResponse } from "@/lib/types";
import { baseChartOptions, useChartColors } from "./chart-theme";

export function PriceChart({
  data,
  height = 420,
}: {
  data: CandleResponse;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    if (!el || data.candles.length === 0) return;

    const chart = createChart(el, baseChartOptions(colors));

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });
    candleSeries.setData(
      data.candles.map(([t, o, h, l, c]) => ({
        time: (t / 1000) as UTCTimestamp,
        open: o,
        high: h,
        low: l,
        close: c,
      }))
    );

    // Volume histogram on an overlay scale pinned to the bottom 20%.
    const volSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volSeries.setData(
      data.candles.map(([t, o, , , c, v]) => ({
        time: (t / 1000) as UTCTimestamp,
        value: v,
        color: c >= o ? `${colors.up}55` : `${colors.down}55`,
      }))
    );
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
      visible: false,
    });

    // EMA overlays computed client-side from the candle closes.
    const closes = data.candles.map((c) => c[4]);
    const times = data.candles.map((c) => (c[0] / 1000) as UTCTimestamp);
    for (const [period, color] of [
      [20, colors.ema20],
      [50, colors.ema50],
    ] as const) {
      const values = ema(closes, period);
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      series.setData(
        values
          .map((v, i) => (v === null ? null : { time: times[i], value: v }))
          .filter((p): p is { time: UTCTimestamp; value: number } => p !== null)
      );
    }

    // Entry/exit markers from the API.
    if (data.markers.length > 0) {
      const markers: SeriesMarker<Time>[] = [...data.markers]
        .sort((a, b) => a.ts_ms - b.ts_ms)
        .map((m) => ({
          time: (m.ts_ms / 1000) as UTCTimestamp,
          position: m.kind === "entry" ? ("belowBar" as const) : ("aboveBar" as const),
          shape:
            m.kind === "entry"
              ? m.side === "long"
                ? ("arrowUp" as const)
                : ("arrowDown" as const)
              : ("circle" as const),
          color: m.side === "long" ? colors.up : colors.down,
          text: m.label,
        }));
      createSeriesMarkers(candleSeries, markers);
    }

    // Stop / target / liquidation estimate price lines.
    const lines: [number | null, string, string][] = [
      [data.overlays.stop, colors.red, "stop"],
      [data.overlays.target, colors.up, "target"],
      [data.overlays.liq, colors.amber, "liq est"],
    ];
    for (const [price, color, title] of lines) {
      if (price !== null) {
        candleSeries.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title,
        });
      }
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, colors]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
