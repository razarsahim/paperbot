"use client";

import { useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Radar,
  Search,
  RefreshCw,
} from "lucide-react";
import { ScannerAnalysis } from "@/components/scanner-analysis";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { getHealth, getSignals, getUniverse } from "@/lib/api";
import {
  fmtCompactUsd,
  fmtDateTime,
  fmtNum,
  fmtPct,
  fmtPrice,
  pnlClass,
} from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import {
  defaultFilters,
  selectAssets,
  trendLabel,
  type ScannerFilters,
  type SortKey,
} from "@/lib/scanner";

const getDecisionLog = () => getSignals(200);
const columns: [SortKey, string][] = [
  ["rank", "#"],
  ["symbol", "Asset"],
  ["price_usd", "Price · USD"],
  ["change_24h_pct", "24h change"],
  ["market_cap_usd", "Market cap"],
  ["volume_24h_usd", "24h volume"],
  ["rsi", "RSI"],
  ["atr_pct", "ATR %"],
  ["funding_rate", "Funding"],
  ["spread_pct", "Spread"],
];

export default function ScannerPage() {
  const universe = usePoll(getUniverse, 30_000);
  const health = usePoll(getHealth, 30_000);
  const signals = usePoll(getDecisionLog, 30_000);
  const [filters, setFilters] = useState<ScannerFilters>(defaultFilters);
  const [sort, setSort] = useState<SortKey>("rank");
  const [descending, setDescending] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const data = universe.source === "live" ? universe.data : null;
  const assets = data?.assets ?? [];
  const rows = selectAssets(assets, filters, sort, descending);
  const asset = assets.find((a) => a.coingecko_id === selected);
  const scan =
    health.source === "live" ? health.data?.engines.pro.last_scan_ms : null;
  const candidates = assets.filter(
    (a) => a.signal === "long" || a.signal === "short",
  ).length;
  function filter(key: keyof ScannerFilters, value: string) {
    setFilters((f) => ({ ...f, [key]: value }));
  }
  function refresh() {
    universe.refresh();
    health.refresh();
    signals.refresh();
  }
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="mb-1 text-[10px] font-semibold tracking-[0.2em] text-muted-foreground uppercase">
            Market intelligence / Public data
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">
            Market scanner{" "}
            <span className="ml-2 align-middle text-xs font-normal text-muted-foreground">
              TOP 20
            </span>
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Explore the universe. Inspect the evidence.
          </p>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw className="size-4" />
          Refresh data
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[
          [
            "Universe",
            data ? `${assets.length} assets` : "—",
            "Dynamically selected by the engine",
          ],
          [
            "Instrument coverage",
            data ? `${assets.filter((a) => a.eligible).length} eligible` : "—",
            "Verified contract metadata",
          ],
          [
            "Strategy candidates",
            data ? String(candidates) : "—",
            "Candidates are not approved entries",
          ],
          [
            "Paper auto-entry",
            health.source === "live" && health.data
              ? health.data.engines.pro.auto_entry_enabled
                ? "Enabled"
                : "Disabled"
              : "Unknown",
            "Read-only dashboard",
          ],
        ].map(([label, value, note]) => (
          <div key={label} className="rounded-xl border bg-card/50 p-4">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-2 text-xl font-semibold tracking-tight tabular-nums">
              {value}
            </p>
            <p className="mt-1 text-[11px] text-muted-foreground">{note}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-lg border px-4 py-3 text-xs text-muted-foreground">
        <span>
          <span
            className={`mr-2 inline-block size-1.5 rounded-full ${data ? "bg-emerald-500" : "bg-amber-500"}`}
          />
          {data
            ? "API connected · stored snapshots"
            : universe.loading
              ? "Connecting…"
              : "API unavailable"}
        </span>
        <span>
          Market snapshot:{" "}
          <strong className="font-medium text-foreground">
            {fmtDateTime(data?.updated_at_ms)}
          </strong>
        </span>
        <span>
          Scanner evaluated:{" "}
          <strong className="font-medium text-foreground">
            {fmtDateTime(scan)}
          </strong>
        </span>
        <span>Times in your local timezone</span>
      </div>
      {data?.stale && (
        <p
          role="status"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300"
        >
          Market snapshot is stale. Displayed prices are historical snapshots;
          the engine independently checks data before any simulated entry.
        </p>
      )}
      {health.source === "live" &&
        health.data &&
        !health.data.engines.pro.running && (
          <p className="text-sm text-amber-700 dark:text-amber-300">
            Scanner cycle is overdue or unavailable. Indicators and candidates
            may be out of date.
          </p>
        )}
      <section
        className="overflow-hidden rounded-xl border bg-card/30"
        aria-label="Cryptocurrency universe"
      >
        <div className="flex flex-wrap items-end gap-3 border-b p-4">
          <label className="min-w-48 flex-1">
            <span className="mb-1.5 block text-xs text-muted-foreground">
              Find an asset
            </span>
            <div className="relative">
              <Search className="absolute top-3 left-3 size-4 text-muted-foreground" />
              <input
                className="h-10 w-full rounded-md border bg-background pr-3 pl-9 text-sm"
                placeholder="Search name or symbol…"
                value={filters.search}
                onChange={(e) => filter("search", e.target.value)}
              />
            </div>
          </label>
          {(
            [
              [
                "trend",
                "Trend",
                [
                  ["all", "All trends"],
                  ["Uptrend", "Uptrend"],
                  ["Downtrend", "Downtrend"],
                  ["Flat", "Flat"],
                  ["Unavailable", "Unavailable"],
                ],
              ],
              [
                "signal",
                "Strategy signal",
                [
                  ["all", "All signals"],
                  ["candidate", "Candidates"],
                  ["long", "Long"],
                  ["short", "Short"],
                  ["none", "None reported"],
                ],
              ],
              [
                "eligibility",
                "Instrument",
                [
                  ["all", "All instruments"],
                  ["eligible", "Eligible"],
                  ["ineligible", "Ineligible"],
                ],
              ],
              [
                "volume",
                "24h volume",
                [
                  ["0", "Any volume"],
                  ["100000000", "≥ $100M"],
                  ["1000000000", "≥ $1B"],
                  ["10000000000", "≥ $10B"],
                ],
              ],
            ] as [keyof ScannerFilters, string, string[][]][]
          ).map(([key, label, options]) => (
            <label key={key} className="min-w-32 flex-1 sm:flex-none">
              <span className="mb-1.5 block text-xs text-muted-foreground">
                {label}
              </span>
              <select
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={filters[key]}
                onChange={(e) => filter(key, e.target.value)}
              >
                {options.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <div className="flex items-center justify-between gap-2 px-4 py-3 text-xs text-muted-foreground">
          <p aria-live="polite">
            {rows.length} of {assets.length} assets · select an asset for
            analysis
          </p>
          <button
            onClick={() => {
              setFilters(defaultFilters);
              setSort("rank");
              setDescending(false);
            }}
            className="rounded px-2 py-1 text-foreground hover:bg-muted"
          >
            Reset view
          </button>
        </div>
        {universe.loading ? (
          <div className="p-12 text-center text-muted-foreground">
            Loading universe…
          </div>
        ) : !data ? (
          <div role="status" className="p-12 text-center">
            <Radar className="mx-auto mb-3 size-6 text-muted-foreground" />
            <h2 className="font-medium">Market data unavailable</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              The local API could not be reached. No demo prices or
              opportunities are shown.
            </p>
          </div>
        ) : !rows.length ? (
          <div className="p-12 text-center text-muted-foreground">
            {assets.length
              ? "No assets match these filters. Reset the view to see the full universe."
              : "The engine has not stored a universe yet."}
          </div>
        ) : (
          <div
            className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-ring"
            tabIndex={0}
            role="region"
            aria-label="Asset table, scroll horizontally for all metrics"
          >
            <table className="w-full whitespace-nowrap text-xs tabular-nums">
              <caption className="sr-only">
                Crypto market snapshots and scanner indicators. Sort with column
                buttons. Open asset analysis with its symbol.
              </caption>
              <thead className="border-y bg-muted/30">
                <tr>
                  {columns.map(([key, label]) => (
                    <th
                      key={key}
                      scope="col"
                      aria-sort={
                        sort === key
                          ? descending
                            ? "descending"
                            : "ascending"
                          : "none"
                      }
                      className={`px-3 py-3 font-medium text-muted-foreground ${key === "symbol" ? "text-left" : "text-right"}`}
                    >
                      <button
                        className="inline-flex items-center gap-1.5 rounded hover:text-foreground"
                        onClick={() => {
                          setSort(key);
                          setDescending(
                            sort === key
                              ? !descending
                              : key !== "rank" && key !== "symbol",
                          );
                        }}
                      >
                        {label}
                        {sort === key ? (
                          descending ? (
                            <ArrowDown className="size-3" />
                          ) : (
                            <ArrowUp className="size-3" />
                          )
                        ) : (
                          <ArrowUpDown className="size-3 opacity-40" />
                        )}
                      </button>
                    </th>
                  ))}
                  <th
                    scope="col"
                    className="px-3 text-left font-medium text-muted-foreground"
                  >
                    EMA trend
                  </th>
                  <th
                    scope="col"
                    className="px-3 text-left font-medium text-muted-foreground"
                  >
                    Candidate
                  </th>
                  <th
                    scope="col"
                    className="px-3 text-left font-medium text-muted-foreground"
                  >
                    Instrument
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr
                    key={a.coingecko_id}
                    className="border-b border-border/50 last:border-0 hover:bg-muted/40"
                  >
                    <td className="px-3 py-4 text-right text-muted-foreground">
                      {a.rank}
                    </td>
                    <td className="sticky left-0 bg-background px-3 py-3">
                      <button
                        className="flex min-w-28 items-center gap-3 rounded text-left focus-visible:outline-2 focus-visible:outline-ring"
                        aria-label={`Analyze ${a.name}`}
                        onClick={(e) => {
                          trigger.current = e.currentTarget;
                          setSelected(a.coingecko_id);
                        }}
                      >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-muted/40 text-[10px] font-semibold text-muted-foreground">
                          {a.symbol.slice(0, 2)}
                        </span>
                        <span>
                          <span className="block font-semibold text-foreground">
                            {a.symbol}
                          </span>
                          <span className="block max-w-32 truncate text-[10px] text-muted-foreground">
                            {a.name}
                          </span>
                        </span>
                      </button>
                    </td>
                    <td className="px-3 text-right font-medium">
                      {fmtPrice(a.price_usd)}
                    </td>
                    <td
                      className={`px-3 text-right ${pnlClass(a.change_24h_pct)}`}
                    >
                      {fmtPct(a.change_24h_pct, 2, true)}
                    </td>
                    <td className="px-3 text-right text-muted-foreground">
                      {fmtCompactUsd(a.market_cap_usd)}
                    </td>
                    <td className="px-3 text-right">
                      {fmtCompactUsd(a.volume_24h_usd)}
                    </td>
                    <td className="px-3 text-right">{fmtNum(a.rsi, 1)}</td>
                    <td className="px-3 text-right">{fmtPct(a.atr_pct, 2)}</td>
                    <td className="px-3 text-right">
                      {fmtPct(
                        a.instrument?.funding_rate == null
                          ? null
                          : a.instrument.funding_rate * 100,
                        4,
                        true,
                      )}
                    </td>
                    <td className="px-3 text-right">
                      {fmtPct(a.instrument?.spread_pct, 3)}
                    </td>
                    <td className="px-3 text-muted-foreground">
                      {trendLabel(a)}
                    </td>
                    <td className="px-3">
                      {a.signal === "long" || a.signal === "short" ? (
                        <span className="font-medium text-sky-600 dark:text-sky-300">
                          {a.signal.toUpperCase()}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3">
                      <span
                        className={
                          a.eligible
                            ? "text-muted-foreground"
                            : "text-amber-700 dark:text-amber-300"
                        }
                      >
                        {a.eligible ? "Eligible" : "Ineligible ↗"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="border-t px-4 py-3 text-[11px] leading-relaxed text-muted-foreground">
          Price, change, cap and volume use the market snapshot. RSI, ATR,
          funding and spread use the scanner snapshot. — means unavailable or no
          candidate reported. Instrument eligibility never implies entry
          approval.
        </p>
      </section>
      <details className="rounded-xl border bg-card/30 p-4">
        <summary className="cursor-pointer text-sm font-medium">
          Universe membership history{" "}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {data?.changes.length ?? 0} records
          </span>
        </summary>
        <ul className="mt-4 space-y-3 text-xs text-muted-foreground">
          {data?.changes.map((c, i) => (
            <li key={`${c.date}:${i}`} className="flex flex-wrap gap-3">
              <time>{c.date}</time>
              <span>Added: {c.added.join(", ") || "none"}</span>
              <span>Removed: {c.removed.join(", ") || "none"}</span>
            </li>
          ))}
        </ul>
        {!data?.changes.length && (
          <p className="mt-3 text-xs text-muted-foreground">
            No membership history available.
          </p>
        )}
      </details>
      <Sheet
        open={Boolean(asset)}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent
          className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-2xl"
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            trigger.current?.focus();
          }}
        >
          <SheetHeader className="border-b p-6 pr-14">
            <SheetTitle>
              {asset?.symbol}{" "}
              <span className="font-normal text-muted-foreground">
                / {asset?.name}
              </span>
            </SheetTitle>
            <SheetDescription>
              Asset analysis · public market data · paper only
            </SheetDescription>
          </SheetHeader>
          {asset && (
            <div className="px-6 pb-8">
              <ScannerAnalysis
                key={asset.coingecko_id}
                asset={asset}
                events={signals.source === "live" ? (signals.data ?? []) : []}
                logAvailable={signals.source === "live" && !signals.loading}
                scanMs={scan}
              />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
