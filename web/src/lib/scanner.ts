import type { UniverseAsset } from "./types";

export type SortKey =
  | "rank"
  | "symbol"
  | "price_usd"
  | "change_24h_pct"
  | "market_cap_usd"
  | "volume_24h_usd"
  | "rsi"
  | "atr_pct"
  | "funding_rate"
  | "spread_pct";
export interface ScannerFilters {
  search: string;
  trend: string;
  signal: string;
  eligibility: string;
  volume: string;
}
export const defaultFilters: ScannerFilters = {
  search: "",
  trend: "all",
  signal: "all",
  eligibility: "all",
  volume: "0",
};
export function trendLabel(a: UniverseAsset) {
  return a.rsi == null && a.atr_pct == null
    ? "Unavailable"
    : a.trend === "up"
      ? "Uptrend"
      : a.trend === "down"
        ? "Downtrend"
        : "Flat";
}
export function selectAssets(
  assets: UniverseAsset[],
  f: ScannerFilters,
  key: SortKey,
  descending: boolean,
) {
  return assets
    .filter((a) => {
      const candidate = a.signal === "long" || a.signal === "short";
      return (
        `${a.symbol} ${a.name}`
          .toLowerCase()
          .includes(f.search.trim().toLowerCase()) &&
        (f.trend === "all" || trendLabel(a) === f.trend) &&
        (f.signal === "all" ||
          (f.signal === "candidate"
            ? candidate
            : f.signal === "none"
              ? !candidate
              : a.signal === f.signal)) &&
        (f.eligibility === "all" ||
          a.eligible === (f.eligibility === "eligible")) &&
        (Number(f.volume) === 0 || a.volume_24h_usd >= Number(f.volume))
      );
    })
    .sort((a, b) => {
      const av =
        key === "funding_rate" || key === "spread_pct"
          ? a.instrument?.[key]
          : a[key];
      const bv =
        key === "funding_rate" || key === "spread_pct"
          ? b.instrument?.[key]
          : b[key];
      if (av == null) return bv == null ? a.rank - b.rank : 1;
      if (bv == null) return -1;
      const diff =
        typeof av === "string" ? av.localeCompare(String(bv)) : av - Number(bv);
      return (descending ? -diff : diff) || a.rank - b.rank;
    });
}
