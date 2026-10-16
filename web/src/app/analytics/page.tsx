"use client";

import { FlaskConical, TriangleAlert } from "lucide-react";
import { cn } from "cn";
import { CurveChart } from "@/components/charts/curve-chart";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getAnalytics } from "@/lib/api";
import { fmtPct, fmtUsd, pnlClass } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

const VALIDATION_STATEMENT =
  "Validation evidence to date is NEGATIVE/UNPROVEN (see the live report line below for current numbers). Simulated results never predict future performance.";

export default function AnalyticsPage() {
  const { data, source, loading } = usePoll(getAnalytics, 60_000);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Analytics (simulated portfolio)</h1>
        <SourceBadge source={source} />
      </div>

      {/* Pinned scientific validation card */}
      <Card className="border-amber-500/50 bg-amber-500/5">
        <CardHeader className="flex-row items-center justify-between py-3">
          <CardTitle className="flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
            <FlaskConical className="size-4" /> Scientific validation
          </CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <Badge
                variant="outline"
                className={
                  data.validation.exists
                    ? "border-emerald-500/50 text-emerald-600 dark:text-emerald-400"
                    : "border-red-500/50 text-red-600 dark:text-red-400"
                }
              >
                {data.validation.exists ? "validation report present" : "no validation report"}
              </Badge>
            )}
            <SourceBadge source={source} />
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="flex items-start gap-2 text-sm font-medium text-amber-800 dark:text-amber-200">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" />
            {VALIDATION_STATEMENT}
          </p>
          {data?.validation.summary && (
            <p className="text-xs text-muted-foreground">{data.validation.summary}</p>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Equity curve (virtual USD)</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent>
            {loading || !data ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (
              <CurveChart points={data.equity_curve} mode="area" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Drawdown %</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent>
            {loading || !data ? (
              <Skeleton className="h-[260px] w-full" />
            ) : (
              <CurveChart points={data.drawdown_curve} mode="baseline" />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Monthly P&L</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent>
            {loading || !data ? (
              <Skeleton className="h-32 w-full" />
            ) : data.monthly.length === 0 ? (
              <p className="text-xs text-muted-foreground">No closed months yet.</p>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {data.monthly.map((m) => (
                  <div
                    key={m.month}
                    className={cn(
                      "rounded-lg border p-2 text-center",
                      m.pnl_usd > 0
                        ? "border-emerald-500/30 bg-emerald-500/10"
                        : m.pnl_usd < 0
                          ? "border-red-500/30 bg-red-500/10"
                          : "border-border/60"
                    )}
                  >
                    <p className="text-[10px] font-mono text-muted-foreground">{m.month}</p>
                    <p className={cn("text-sm font-semibold tabular-nums", pnlClass(m.pnl_usd))}>
                      {fmtUsd(m.pnl_usd, { sign: true })}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">P&L by asset</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="px-0">
            {loading || !data ? (
              <Skeleton className="mx-4 h-32 w-auto" />
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Symbol</TableHead>
                    <TableHead className="text-right">Trades</TableHead>
                    <TableHead className="text-right">Net P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.by_asset.map((a) => (
                    <TableRow key={a.symbol}>
                      <TableCell className="font-mono">{a.symbol}</TableCell>
                      <TableCell className="text-right tabular-nums">{a.trades}</TableCell>
                      <TableCell className={cn("text-right font-medium tabular-nums", pnlClass(a.pnl_usd))}>
                        {fmtUsd(a.pnl_usd, { sign: true })}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Benchmarks</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {loading || !data ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <>
                <div className="flex items-center justify-between rounded-lg border border-border/60 p-3">
                  <span className="text-xs text-muted-foreground">Doing nothing (cash)</span>
                  <span className="font-semibold tabular-nums">{fmtUsd(data.benchmarks.cash_usd)}</span>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border/60 p-3">
                  <span className="text-xs text-muted-foreground">Buy-and-hold BTC (same window)</span>
                  <span className={cn("font-semibold tabular-nums", pnlClass(data.benchmarks.btc_hold_pct))}>
                    {data.benchmarks.btc_hold_pct === null ? "—" : fmtPct(data.benchmarks.btc_hold_pct, 2, true)}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  A strategy must beat both benchmarks out-of-sample before it means anything.
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
