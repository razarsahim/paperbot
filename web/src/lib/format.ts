// Number/date formatting helpers. All money shown by this app is SIMULATED.

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function fmtUsd(n: number | null | undefined, opts?: { sign?: boolean }): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const s = usdFmt.format(Math.abs(n));
  if (opts?.sign) return `${n < 0 ? "−" : "+"}${s}`;
  return n < 0 ? `−${s}` : s;
}

export function fmtPrice(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const digits = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 4 : 8;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: digits })}`;
}

export function fmtCompactUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

export function fmtPct(n: number | null | undefined, digits = 2, sign = false): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const s = `${Math.abs(n).toFixed(digits)}%`;
  if (sign) return `${n < 0 ? "−" : "+"}${s}`;
  return n < 0 ? `−${s}` : s;
}

export function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function fmtQty(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

export function timeAgo(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "never";
  const d = Date.now() - ms;
  if (d < 0) return "just now";
  const s = Math.floor(d / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function fmtDateTime(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return new Date(ms).toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDuration(ms: number): string {
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function pnlClass(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n) || n === 0)
    return "text-muted-foreground";
  return n > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400";
}
