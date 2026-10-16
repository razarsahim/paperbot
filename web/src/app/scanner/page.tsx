"use client";

import {
  Minus,
  Radar,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";
import { cn } from "cn";
import { SourceBadge } from "@/components/source-badge";
import { EmptyState } from "@/components/empty-state";
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getUniverse } from "@/lib/api";
import {
  fmtCompactUsd,
  fmtNum,
  fmtPct,
  fmtPrice,
  pnlClass,
  timeAgo,
} from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { UniverseAsset } from "@/lib/types";

function TrendIcon({ trend }: { trend: UniverseAsset["trend"] }) {
  if (trend === "up") return <TrendingUp className="size-4 text-emerald-600 dark:text-emerald-400" />;
  if (trend === "down") return <TrendingDown className="size-4 text-red-600 dark:text-red-400" />;
  return <Minus className="size-4 text-muted-foreground" />;
}

function SignalBadge({ signal }: { signal: UniverseAsset["signal"] }) {
  if (signal === "long")
    return <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">LONG</Badge>;
  if (signal === "short")
    return <Badge className="bg-red-500/15 text-red-600 dark:text-red-400">SHORT</Badge>;
  return <span className="text-xs text-muted-foreground">—</span>;
}

export default function ScannerPage() {
  const { data, source, loading } = usePoll(getUniverse, 30_000);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Scanner — Top 20 universe</h1>
        <SourceBadge source={source} />
        <span className="text-xs text-muted-foreground">
          {data?.updated_at_ms ? `universe updated ${timeAgo(data.updated_at_ms)}` : ""}
        </span>
      </div>

      {data?.stale && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
          <TriangleAlert className="size-4 shrink-0" />
          Universe data is STALE — the engine defaults to no new simulated trades until feeds recover.
        </div>
      )}

      <Card className="py-0">
        <CardContent className="px-0">
          {loading || !data ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : data.assets.length === 0 ? (
            <div className="p-4">
              <EmptyState icon={Radar} title="No universe data" description="The scanner has not produced a universe snapshot yet." />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-10">#</TableHead>
                    <TableHead>Asset</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">24h %</TableHead>
                    <TableHead className="text-right">Mcap</TableHead>
                    <TableHead className="text-right">Volume</TableHead>
                    <TableHead className="text-center">Trend</TableHead>
                    <TableHead className="text-right">ATR%</TableHead>
                    <TableHead className="text-right">RSI</TableHead>
                    <TableHead className="text-center">Signal</TableHead>
                    <TableHead className="text-center">Eligibility</TableHead>
                    <TableHead className="text-right">Funding</TableHead>
                    <TableHead className="text-right">Spread</TableHead>
                    <TableHead className="text-right">Data age</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.assets.map((a) => (
                    <TableRow key={a.coingecko_id} className={cn(!a.eligible && "opacity-70")}>
                      <TableCell className="text-muted-foreground tabular-nums">{a.rank}</TableCell>
                      <TableCell>
                        <span className="font-semibold">{a.symbol}</span>{" "}
                        <span className="hidden text-muted-foreground lg:inline">{a.name}</span>
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums">{fmtPrice(a.price_usd)}</TableCell>
                      <TableCell className={cn("text-right tabular-nums", pnlClass(a.change_24h_pct))}>
                        {fmtPct(a.change_24h_pct, 2, true)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular-nums">{fmtCompactUsd(a.market_cap_usd)}</TableCell>
                      <TableCell className="text-right text-muted-foreground tabular-nums">{fmtCompactUsd(a.volume_24h_usd)}</TableCell>
                      <TableCell className="text-center"><span className="inline-flex justify-center"><TrendIcon trend={a.trend} /></span></TableCell>
                      <TableCell className="text-right tabular-nums">{a.atr_pct === null ? "—" : fmtNum(a.atr_pct, 1)}</TableCell>
                      <TableCell className="text-right tabular-nums">{a.rsi === null ? "—" : fmtNum(a.rsi, 1)}</TableCell>
                      <TableCell className="text-center"><SignalBadge signal={a.signal} /></TableCell>
                      <TableCell className="text-center">
                        {a.eligible ? (
                          <Badge variant="outline" className="border-emerald-500/40 text-emerald-600 dark:text-emerald-400">
                            eligible
                          </Badge>
                        ) : (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Badge className="cursor-help bg-red-500/15 text-red-600 dark:text-red-400">
                                NOT ELIGIBLE
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent side="left" className="max-w-60">
                              {a.reason ?? "No reason provided"}
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {a.instrument?.funding_rate === null || a.instrument?.funding_rate === undefined
                          ? "—"
                          : fmtPct(a.instrument.funding_rate * 100, 4, true)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {a.instrument?.spread_pct === null || a.instrument?.spread_pct === undefined
                          ? "—"
                          : fmtPct(a.instrument.spread_pct, 3)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular-nums">
                        {a.instrument?.data_age_s === null || a.instrument?.data_age_s === undefined
                          ? "—"
                          : `${a.instrument.data_age_s}s`}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-sm">Universe change log</CardTitle>
          <SourceBadge source={source} />
        </CardHeader>
        <CardContent>
          {loading || !data ? (
            <Skeleton className="h-16 w-full" />
          ) : data.changes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No membership changes recorded.</p>
          ) : (
            <ul className="space-y-2 text-xs">
              {data.changes.map((c) => (
                <li key={c.date} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-muted-foreground">{c.date}</span>
                  {c.added.map((s) => (
                    <Badge key={`a-${s}`} variant="outline" className="border-emerald-500/40 text-emerald-600 dark:text-emerald-400">
                      + {s}
                    </Badge>
                  ))}
                  {c.removed.map((s) => (
                    <Badge key={`r-${s}`} variant="outline" className="border-red-500/40 text-red-600 dark:text-red-400">
                      − {s}
                    </Badge>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
