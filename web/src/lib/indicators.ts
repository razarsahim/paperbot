// Client-side deterministic indicator math for chart overlays/panes.
// Display-only: these never generate trading decisions in the UI.

export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export function rsi(values: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  const toRsi = (g: number, l: number) =>
    l === 0 ? 100 : 100 - 100 / (1 + g / l);
  out[period] = toRsi(avgGain, avgLoss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = toRsi(avgGain, avgLoss);
  }
  return out;
}

export interface MacdPoint {
  macd: number | null;
  signal: number | null;
  hist: number | null;
}

export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9
): MacdPoint[] {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const macdLine: (number | null)[] = values.map((_, i) =>
    emaFast[i] !== null && emaSlow[i] !== null
      ? (emaFast[i] as number) - (emaSlow[i] as number)
      : null
  );
  const firstIdx = macdLine.findIndex((v) => v !== null);
  const signalLine: (number | null)[] = new Array(values.length).fill(null);
  if (firstIdx >= 0) {
    const compact = macdLine.slice(firstIdx) as number[];
    const sig = ema(compact, signalPeriod);
    for (let i = 0; i < sig.length; i++) signalLine[firstIdx + i] = sig[i];
  }
  return values.map((_, i) => ({
    macd: macdLine[i],
    signal: signalLine[i],
    hist:
      macdLine[i] !== null && signalLine[i] !== null
        ? (macdLine[i] as number) - (signalLine[i] as number)
        : null,
  }));
}
