"use client";

import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  LineType,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { baseChartOptions, useChartColors } from "./chart-theme";
import type { ChartData } from "@/lib/crh-api";

const H = 3_600_000;

/** Wilder ATR(14) over the plotted candles (display only; the engine's own
 *  ATR is computed on its 199-bar window and may differ slightly). */
function atr14(c: number[][]): (number | null)[] {
  const out: (number | null)[] = new Array(c.length).fill(null);
  if (c.length < 15) return out;
  const tr: number[] = [];
  for (let i = 1; i < c.length; i++) {
    tr.push(Math.max(c[i][2] - c[i][3], Math.abs(c[i][2] - c[i - 1][4]), Math.abs(c[i][3] - c[i - 1][4])));
  }
  let av = tr.slice(0, 14).reduce((a, b) => a + b, 0) / 14;
  out[14] = av;
  for (let i = 15; i < c.length; i++) {
    av = (av * 13 + tr[i - 1]) / 14;
    out[i] = av;
  }
  return out;
}

export function CrhChart({
  data,
  focusTradeId,
  height = 440,
}: {
  data: ChartData;
  focusTradeId?: number | null;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const atrRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const colors = useChartColors();

  useEffect(() => {
    const el = ref.current;
    const el2 = atrRef.current;
    if (!el || !el2 || data.candles.length === 0) return;
    const chart = createChart(el, baseChartOptions(colors));
    chartRef.current = chart;
    const ts = (ms: number) => (ms / 1000) as UTCTimestamp;
    const snap = (ms: number) => ms - (ms % H);
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: colors.up, downColor: colors.down, borderUpColor: colors.up,
      borderDownColor: colors.down, wickUpColor: colors.up, wickDownColor: colors.down,
    });
    candle.setData(data.candles.map(([t, o, h, l, c]) => ({ time: ts(t), open: o, high: h, low: l, close: c })));

    const vol = chart.addSeries(HistogramSeries, {
      priceScaleId: "vol", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false,
    });
    vol.setData(data.candles.map(([t, o, , , c, v]) => ({ time: ts(t), value: v, color: c >= o ? `${colors.up}44` : `${colors.down}44` })));
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 }, visible: false });

    // window shading via a transparent line pair is overkill; mark the window bounds with price-line-free vertical markers
    const markers: SeriesMarker<Time>[] = [];
    for (const m of data.markers) {
      markers.push({
        time: ts(snap(m.ts_ms)),
        position: m.kind === "entry" ? "belowBar" : "aboveBar",
        shape: m.kind === "entry" ? "arrowUp" : "circle",
        color: m.kind === "entry" ? colors.blue : m.win ? colors.up : colors.down,
        text: m.label,
        size: focusTradeId && m.trade_id === focusTradeId ? 2 : 1,
      });
    }
    for (const s of data.signals) {
      markers.push({ time: ts(snap(s.close_ts - H)), position: "belowBar", shape: "square",
        color: colors.amber, text: `signal ${s.drop_pct.toFixed(1)}% / 24h`, size: 0 });
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    if (markers.length) createSeriesMarkers(candle, markers);

    // stop band per trade: initial stop (dashed) -> final/trailed stop (solid), stepped
    for (const s of data.stops) {
      const a = snap(s.from), b = snap(s.to);
      const line = chart.addSeries(LineSeries, {
        color: colors.red, lineWidth: focusTradeId === s.trade_id ? 2 : 1, lineStyle: LineStyle.Dashed,
        lineType: LineType.WithSteps, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      });
      line.setData([{ time: ts(a), value: s.initial }, { time: ts(Math.max(a + H, b)), value: s.final }]);
      const f = chart.addSeries(LineSeries, {
        color: colors.amber, lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false,
      });
      f.setData([{ time: ts(a), value: s.final }, { time: ts(Math.max(a + H, b)), value: s.final }]);
    }

    // ATR pane (separate chart, synced time scale)
    const chart2 = createChart(el2, { ...baseChartOptions(colors), rightPriceScale: { borderColor: colors.border } });
    const a = atr14(data.candles);
    const atrSeries = chart2.addSeries(LineSeries, { color: colors.ema50, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "ATR(14)" });
    atrSeries.setData(data.candles.map((c, i) => ({ time: ts(c[0]), value: a[i] })).filter((p): p is { time: UTCTimestamp; value: number } => p.value !== null));
    const sync = (from: IChartApi, to: IChartApi) =>
      from.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) to.timeScale().setVisibleLogicalRange(r); });
    sync(chart, chart2);
    sync(chart2, chart);

    const focus = focusTradeId ? data.markers.find((m) => m.trade_id === focusTradeId && m.kind === "entry") : null;
    if (focus) {
      const i = data.candles.findIndex((c) => c[0] >= snap(focus.ts_ms));
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, i - 40), to: Math.min(data.candles.length, i + 40) });
    } else {
      chart.timeScale().fitContent();
    }
    return () => { chart.remove(); chart2.remove(); chartRef.current = null; };
  }, [data, colors, focusTradeId]);

  return (
    <div>
      <div ref={ref} style={{ height }} className="w-full" />
      <div ref={atrRef} style={{ height: 110 }} className="w-full" />
    </div>
  );
}
