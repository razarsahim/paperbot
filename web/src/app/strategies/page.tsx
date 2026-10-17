"use client";

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  Beaker,
  FlaskConical,
  Lock,
  TriangleAlert,
  Trophy,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { cn } from "cn";
import { EmptyState } from "@/components/empty-state";
import { SourceBadge } from "@/components/source-badge";
import { StatTile } from "@/components/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fmtPct, fmtUsd, pnlClass } from "@/lib/format";
import { getStrategies } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import type { StrategyRow } from "@/lib/types";

// ---------- sorting ----------

type SortKey =
  | "rank_by_net_pnl"
  | "lab"
  | "name"
  | "allocation_usd"
  | "equity_usd"
  | "return_pct"
  | "realized_pnl_usd"
  | "unrealized_pnl_usd"
  | "net"
  | "win_rate_pct"
  | "profit_factor"
  | "expectancy_usd"
  | "trade_count"
  | "max_drawdown_realized_usd"
  | "fees_usd"
  | "funding_usd"
  | "open_positions"
  | "leverage"
  | "locked";

type SortDir = "asc" | "desc";

/** Net paper P&L = realized + unrealized (used for ranking and the best/worst tiles). */
function netPnl(r: StrategyRow): number {
  return r.realized_pnl_usd + r.unrealized_pnl_usd;
}

const SORT_ACCESSORS: Record<SortKey, (r: StrategyRow) => number | string | null> = {
  rank_by_net_pnl: (r) => r.rank_by_net_pnl,
  lab: (r) => r.lab,
  name: (r) => r.name,
  allocation_usd: (r) => r.allocation_usd,
  equity_usd: (r) => r.equity_usd,
  return_pct: (r) => r.return_pct,
  realized_pnl_usd: (r) => r.realized_pnl_usd,
  unrealized_pnl_usd: (r) => r.unrealized_pnl_usd,
  net: (r) => netPnl(r),
  win_rate_pct: (r) => r.win_rate_pct,
  profit_factor: (r) => r.profit_factor,
  expectancy_usd: (r) => r.expectancy_usd,
  trade_count: (r) => r.trade_count,
  max_drawdown_realized_usd: (r) => r.max_drawdown_realized_usd,
  fees_usd: (r) => r.fees_usd,
  funding_usd: (r) => r.funding_usd,
  open_positions: (r) => r.open_positions,
  leverage: (r) => r.leverage,
  locked: (r) => (r.locked ? 1 : 0),
};

// Keys whose natural first-click order is ascending (rank 1 first, A→Z).
const ASC_FIRST: ReadonlySet<SortKey> = new Set<SortKey>([
  "rank_by_net_pnl",
  "lab",
  "name",
]);

function defaultDir(key: SortKey): SortDir {
  return ASC_FIRST.has(key) ? "asc" : "desc";
}

function compareRows(a: StrategyRow, b: StrategyRow, key: SortKey, dir: SortDir): number {
  const av = SORT_ACCESSORS[key](a);
  const bv = SORT_ACCESSORS[key](b);
  // Nulls (e.g. no win-rate yet) always sort to the bottom, both directions.
  if (av === null && bv === null) return a.rank_by_net_pnl - b.rank_by_net_pnl;
  if (av === null) return 1;
  if (bv === null) return -1;
  const raw =
    typeof av === "string" && typeof bv === "string"
      ? av.localeCompare(bv)
      : (av as number) - (bv as number);
  return dir === "asc" ? raw : -raw;
}

// ---------- column model (header order == body order) ----------

interface ColumnDef {
  key: SortKey;
  label: string;
  align: "left" | "right" | "center";
  sortable: boolean;
}

const COLUMNS: ColumnDef[] = [
  { key: "rank_by_net_pnl", label: "Rank", align: "left", sortable: true },
  { key: "lab", label: "Lab", align: "left", sortable: true },
  { key: "name", label: "Strategy", align: "left", sortable: true },
  { key: "allocation_usd", label: "Allocation", align: "right", sortable: true },
  { key: "equity_usd", label: "Equity", align: "right", sortable: true },
  { key: "return_pct", label: "Return %", align: "right", sortable: true },
  { key: "realized_pnl_usd", label: "Realized P&L", align: "right", sortable: true },
  { key: "unrealized_pnl_usd", label: "Unrealized P&L", align: "right", sortable: true },
  { key: "win_rate_pct", label: "Win rate", align: "right", sortable: true },
  { key: "profit_factor", label: "Profit factor", align: "right", sortable: true },
  { key: "expectancy_usd", label: "Expectancy", align: "right", sortable: true },
  { key: "trade_count", label: "Trades", align: "right", sortable: true },
  { key: "max_drawdown_realized_usd", label: "Max DD", align: "right", sortable: true },
  { key: "fees_usd", label: "Fees", align: "right", sortable: true },
  { key: "funding_usd", label: "Funding", align: "right", sortable: true },
  { key: "open_positions", label: "Open", align: "right", sortable: true },
  { key: "leverage", label: "Leverage", align: "center", sortable: true },
  { key: "locked", label: "Locked", align: "center", sortable: true },
];

// Dropdown exposes the common sorts (also accessible via header clicks).
const DROPDOWN_SORTS: { value: SortKey; label: string }[] = [
  { value: "rank_by_net_pnl", label: "Rank (net P&L)" },
  { value: "net", label: "Net P&L" },
  { value: "return_pct", label: "Return %" },
  { value: "max_drawdown_realized_usd", label: "Max drawdown" },
  { value: "win_rate_pct", label: "Win rate" },
  { value: "trade_count", label: "Sample size (trades)" },
];

// ---------- cells ----------

function LabChip({ lab }: { lab: StrategyRow["lab"] }) {
  if (lab === "extreme") {
    return (
      <Badge className="border-amber-500/40 bg-amber-500/15 text-[10px] font-semibold tracking-wider text-amber-600 uppercase dark:text-amber-400">
        Extreme
      </Badge>
    );
  }
  return (
    <Badge className="border-cyan-500/40 bg-cyan-500/15 text-[10px] font-semibold tracking-wider text-cyan-700 uppercase dark:text-cyan-300">
      Research
    </Badge>
  );
}

function alignClass(align: ColumnDef["align"]): string {
  if (align === "right") return "text-right";
  if (align === "center") return "text-center";
  return "text-left";
}

function renderCell(key: SortKey, r: StrategyRow) {
  switch (key) {
    case "rank_by_net_pnl":
      return (
        <span className="inline-flex items-center gap-1.5 font-semibold tabular-nums">
          {r.rank_by_net_pnl === 1 && <Trophy className="size-3.5 text-amber-500" />}
          {r.rank_by_net_pnl}
        </span>
      );
    case "lab":
      return <LabChip lab={r.lab} />;
    case "name":
      return <span className="font-medium whitespace-nowrap">{r.name}</span>;
    case "allocation_usd":
      return <span className="tabular-nums">{fmtUsd(r.allocation_usd)}</span>;
    case "equity_usd":
      return <span className="tabular-nums">{fmtUsd(r.equity_usd)}</span>;
    case "return_pct":
      return (
        <span className={cn("tabular-nums", pnlClass(r.return_pct))}>
          {fmtPct(r.return_pct, 2, true)}
        </span>
      );
    case "realized_pnl_usd":
      return (
        <span className={cn("tabular-nums", pnlClass(r.realized_pnl_usd))}>
          {fmtUsd(r.realized_pnl_usd, { sign: true })}
        </span>
      );
    case "unrealized_pnl_usd":
      return (
        <span className={cn("font-medium tabular-nums", pnlClass(r.unrealized_pnl_usd))}>
          {fmtUsd(r.unrealized_pnl_usd, { sign: true })}
        </span>
      );
    case "win_rate_pct":
      return (
        <span className="tabular-nums">
          {r.win_rate_pct === null ? "—" : fmtPct(r.win_rate_pct, 1)}
        </span>
      );
    case "profit_factor":
      return (
        <span className="tabular-nums">
          {r.profit_factor === null ? "—" : r.profit_factor.toFixed(2)}
        </span>
      );
    case "expectancy_usd":
      return (
        <span className={cn("tabular-nums", r.expectancy_usd === null ? "" : pnlClass(r.expectancy_usd))}>
          {r.expectancy_usd === null ? "—" : fmtUsd(r.expectancy_usd, { sign: true })}
        </span>
      );
    case "trade_count":
      return (
        <span className="inline-flex items-center justify-end gap-1 tabular-nums">
          {r.trade_count}
          {r.sample === "insufficient" && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex cursor-default">
                  <TriangleAlert className="size-3.5 text-amber-500" />
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Insufficient sample — far too few trades to draw any conclusion.
              </TooltipContent>
            </Tooltip>
          )}
        </span>
      );
    case "max_drawdown_realized_usd":
      return (
        <span
          className={cn(
            "tabular-nums",
            r.max_drawdown_realized_usd > 0 ? "text-red-600 dark:text-red-400" : "text-muted-foreground"
          )}
        >
          {r.max_drawdown_realized_usd > 0 ? `−${fmtUsd(r.max_drawdown_realized_usd)}` : fmtUsd(0)}
        </span>
      );
    case "fees_usd":
      return <span className="text-muted-foreground tabular-nums">{fmtUsd(r.fees_usd)}</span>;
    case "funding_usd":
      return (
        <span className={cn("tabular-nums", pnlClass(r.funding_usd))}>
          {fmtUsd(r.funding_usd, { sign: true })}
        </span>
      );
    case "open_positions":
      return <span className="tabular-nums">{r.open_positions}</span>;
    case "leverage":
      return (
        <Badge variant="outline" className="tabular-nums">
          {r.leverage}x
        </Badge>
      );
    case "locked":
      return r.locked ? (
        <span className="inline-flex items-center justify-center" title="Strategy locked — new entries blocked">
          <Lock className="size-4 text-red-600 dark:text-red-400" />
        </span>
      ) : (
        <span className="text-muted-foreground/50">—</span>
      );
    default:
      return null;
  }
}

function SortHeader({
  col,
  active,
  dir,
  onSort,
}: {
  col: ColumnDef;
  active: boolean;
  dir: SortDir;
  onSort: (key: SortKey) => void;
}) {
  const Icon = active ? (dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <TableHead
      className={cn(
        alignClass(col.align),
        "cursor-pointer select-none whitespace-nowrap hover:text-foreground",
        active && "text-foreground"
      )}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(col.key)}
        className={cn(
          "inline-flex items-center gap-1",
          col.align === "right" && "flex-row-reverse",
          col.align === "center" && "justify-center"
        )}
      >
        {col.label}
        <Icon className={cn("size-3", active ? "opacity-100" : "opacity-40")} />
      </button>
    </TableHead>
  );
}

// ---------- page ----------

export default function StrategiesPage() {
  const { data, source, loading } = usePoll(getStrategies, 15_000);
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "rank_by_net_pnl",
    dir: "asc",
  });

  const rows = useMemo(() => data?.strategies ?? [], [data]);

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => compareRows(a, b, sort.key, sort.dir));
  }, [rows, sort]);

  const onSort = (key: SortKey) =>
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: defaultDir(key) }
    );

  // Top-of-page aggregates.
  const summary = useMemo(() => {
    if (rows.length === 0) return null;
    const totalEquity = rows.reduce((s, r) => s + r.equity_usd, 0);
    const lockedCount = rows.filter((r) => r.locked).length;
    const insufficientCount = rows.filter((r) => r.sample === "insufficient").length;
    let best = rows[0];
    let worst = rows[0];
    for (const r of rows) {
      if (netPnl(r) > netPnl(best)) best = r;
      if (netPnl(r) < netPnl(worst)) worst = r;
    }
    const perLab = (lab: StrategyRow["lab"]) => {
      const sub = rows.filter((r) => r.lab === lab);
      return {
        equity: sub.reduce((s, r) => s + r.equity_usd, 0),
        count: sub.length,
        locked: sub.filter((r) => r.locked).length,
      };
    };
    return {
      totalEquity,
      lockedCount,
      insufficientCount,
      best,
      worst,
      extreme: perLab("extreme"),
      research: perLab("research"),
    };
  }, [rows]);

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <BarChart3 className="size-5 text-muted-foreground" />
            Strategy Analytics
          </h1>
          <SourceBadge source={source} />
        </div>
        <p className="max-w-3xl text-xs text-muted-foreground">
          {data?.note ??
            "Forward-paper diagnostics only — live simulated results across both cohorts of the unified Extreme Lab. These are not backtests and never validated returns."}
        </p>
      </div>

      {/* 3-way separation legend */}
      <Card className="border-border/60 bg-card/60 py-3">
        <CardContent className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-flex h-4 items-center rounded-full border border-emerald-500/50 px-1.5 text-[9px] font-semibold tracking-wider text-emerald-600 uppercase dark:text-emerald-400">
                Forward paper
              </span>
              <span className="text-muted-foreground">live simulated paper — what this page shows</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-flex h-4 items-center rounded-full border border-border px-1.5 text-[9px] font-semibold tracking-wider text-muted-foreground uppercase">
                Backtest
              </span>
              <span className="text-muted-foreground">historical replay — NOT shown here (see Analytics)</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-flex h-4 items-center rounded-full border border-amber-500/50 bg-amber-500/15 px-1.5 text-[9px] font-semibold tracking-wider text-amber-600 uppercase dark:text-amber-400">
                Demo
              </span>
              <span className="text-muted-foreground">built-in fallback when the backend is offline</span>
            </span>
          </div>
          <p className="text-[11px] leading-snug text-amber-700 dark:text-amber-300">
            Everything on this page is forward-paper{source === "demo" ? " (currently demo)" : ""} — never a
            backtest and never a validated return. Simulated results do not predict future performance.
          </p>
        </CardContent>
      </Card>

      {/* Top stat tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <StatTile
          label="Total virtual equity"
          value={fmtUsd(summary?.totalEquity)}
          sub="unified lab · both cohorts"
          source={source}
          loading={loading && !summary}
        />
        <StatTile
          label="Locked strategies"
          value={summary ? String(summary.lockedCount) : "—"}
          valueClassName={summary && summary.lockedCount > 0 ? "text-red-600 dark:text-red-400" : undefined}
          sub={`of ${rows.length || "—"} tracked`}
          source={source}
          loading={loading && !summary}
        />
        <StatTile
          label="Best by net P&L"
          value={summary ? summary.best.name : "—"}
          valueClassName="text-base"
          sub={
            summary ? (
              <span className={pnlClass(netPnl(summary.best))}>
                {fmtUsd(netPnl(summary.best), { sign: true })}
              </span>
            ) : undefined
          }
          source={source}
          loading={loading && !summary}
        />
        <StatTile
          label="Worst by net P&L"
          value={summary ? summary.worst.name : "—"}
          valueClassName="text-base"
          sub={
            summary ? (
              <span className={pnlClass(netPnl(summary.worst))}>
                {fmtUsd(netPnl(summary.worst), { sign: true })}
              </span>
            ) : undefined
          }
          source={source}
          loading={loading && !summary}
        />
        <StatTile
          label="Insufficient samples"
          value={summary ? String(summary.insufficientCount) : "—"}
          valueClassName={
            summary && summary.insufficientCount > 0 ? "text-amber-600 dark:text-amber-400" : undefined
          }
          sub="too few trades to trust"
          source={source}
          loading={loading && !summary}
        />
      </div>

      {/* Per-lab summary pair */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Link href="/lab" className="group">
          <Card className="h-full gap-1 rounded-xl border-amber-500/30 bg-amber-500/5 px-4 py-3 transition-colors group-hover:border-amber-500/60">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm font-semibold">
                <FlaskConical className="size-4 text-amber-500" />
                Extreme cohort
              </span>
              <span className="text-[10px] tracking-wider text-muted-foreground uppercase">
                5 sleeves · $250
              </span>
            </div>
            <div className="flex items-end justify-between gap-2">
              <span className="text-xl font-semibold tabular-nums">
                {loading && !summary ? <Skeleton className="h-6 w-20" /> : fmtUsd(summary?.extreme.equity)}
              </span>
              {summary && summary.extreme.locked > 0 ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-red-600 dark:text-red-400">
                  <Lock className="size-3" />
                  {summary.extreme.locked} locked
                </span>
              ) : (
                <span className="text-[11px] text-muted-foreground">
                  {summary?.extreme.count ?? 0} strategies · none locked
                </span>
              )}
            </div>
          </Card>
        </Link>
        <Link href="/lab" className="group">
          <Card className="h-full gap-1 rounded-xl border-cyan-500/30 bg-cyan-500/5 px-4 py-3 transition-colors group-hover:border-cyan-500/60">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-sm font-semibold">
                <Beaker className="size-4 text-cyan-500" />
                Research cohort
              </span>
              <span className="text-[10px] tracking-wider text-muted-foreground uppercase">
                5 sleeves · $250
              </span>
            </div>
            <div className="flex items-end justify-between gap-2">
              <span className="text-xl font-semibold tabular-nums">
                {loading && !summary ? <Skeleton className="h-6 w-20" /> : fmtUsd(summary?.research.equity)}
              </span>
              {summary && summary.research.locked > 0 ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-red-600 dark:text-red-400">
                  <Lock className="size-3" />
                  {summary.research.locked} locked
                </span>
              ) : (
                <span className="text-[11px] text-muted-foreground">
                  {summary?.research.count ?? 0} strategies · none locked
                </span>
              )}
            </div>
          </Card>
        </Link>
      </div>

      {/* Comparison table */}
      <Card className="py-0">
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 py-3">
          <CardTitle className="text-sm">All strategies — forward-paper comparison</CardTitle>
          <div className="flex items-center gap-2">
            <span className="hidden text-[11px] text-muted-foreground sm:inline">Sort by</span>
            <Select
              value={sort.key}
              onValueChange={(v) => setSort({ key: v as SortKey, dir: defaultDir(v as SortKey) })}
            >
              <SelectTrigger size="sm" className="w-44" aria-label="Sort strategies by">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DROPDOWN_SORTS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <SourceBadge source={source} />
          </div>
        </CardHeader>
        <CardContent className="px-0 pb-3">
          {loading && rows.length === 0 ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={BarChart3}
                title="No strategies to compare"
                description="The backend returned no strategy rows."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    {COLUMNS.map((col) => (
                      <SortHeader
                        key={col.key}
                        col={col}
                        active={sort.key === col.key}
                        dir={sort.dir}
                        onSort={onSort}
                      />
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.map((r) => (
                    <TableRow
                      key={`${r.lab}:${r.key}`}
                      className={r.lab === "extreme" ? "bg-amber-500/5" : "bg-cyan-500/5"}
                    >
                      {COLUMNS.map((col) => (
                        <TableCell
                          key={col.key}
                          className={cn(alignClass(col.align), "whitespace-nowrap")}
                        >
                          {renderCell(col.key, r)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Disclaimer */}
      <p className="text-[11px] text-muted-foreground">
        Forward-paper diagnostics across the unified Extreme Lab (10 sleeves, virtual $500) — the
        extreme and research cohorts, $250 each. Rankings reflect simulated net P&L only and are not
        evidence of skill or future performance. Strategies flagged with a warning icon have too few
        trades to interpret.
      </p>
    </div>
  );
}
