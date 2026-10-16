"use client";

import { ColorType, type ChartOptions, type DeepPartial } from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export interface ChartColors {
  dark: boolean;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  ema20: string;
  ema50: string;
  line: string;
  areaTop: string;
  areaBottom: string;
  amber: string;
  red: string;
  blue: string;
}

export function chartColors(dark: boolean): ChartColors {
  return dark
    ? {
        dark,
        text: "#8b8f98",
        grid: "rgba(140,145,155,0.08)",
        border: "rgba(140,145,155,0.25)",
        up: "#22c55e",
        down: "#ef4444",
        ema20: "#38bdf8",
        ema50: "#c084fc",
        line: "#34d399",
        areaTop: "rgba(52,211,153,0.25)",
        areaBottom: "rgba(52,211,153,0.02)",
        amber: "#f59e0b",
        red: "#f87171",
        blue: "#60a5fa",
      }
    : {
        dark,
        text: "#6b7280",
        grid: "rgba(100,105,115,0.10)",
        border: "rgba(100,105,115,0.3)",
        up: "#16a34a",
        down: "#dc2626",
        ema20: "#0284c7",
        ema50: "#9333ea",
        line: "#059669",
        areaTop: "rgba(5,150,105,0.2)",
        areaBottom: "rgba(5,150,105,0.02)",
        amber: "#d97706",
        red: "#dc2626",
        blue: "#2563eb",
      };
}

export function useChartColors(): ChartColors {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return chartColors(!mounted || resolvedTheme !== "light");
}

export function baseChartOptions(c: ChartColors): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: c.text,
      fontSize: 11,
      attributionLogo: true,
    },
    grid: {
      vertLines: { color: c.grid },
      horzLines: { color: c.grid },
    },
    rightPriceScale: { borderColor: c.border },
    timeScale: { borderColor: c.border, timeVisible: true, secondsVisible: false },
    crosshair: {
      horzLine: { labelBackgroundColor: c.dark ? "#27272a" : "#e5e7eb" },
      vertLine: { labelBackgroundColor: c.dark ? "#27272a" : "#e5e7eb" },
    },
  };
}
