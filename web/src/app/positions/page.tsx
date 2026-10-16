"use client";

import { Wallet } from "lucide-react";
import { cn } from "cn";
import { EmptyState } from "@/components/empty-state";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getPositions } from "@/lib/api";
import {
  fmtPct,
  fmtPrice,
  fmtQty,
  fmtUsd,
  pnlClass,
  timeAgo,
} from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { Position } from "@/lib/types";

function liqDistancePct(p: Position): number | null {
  const mark = p.mark_price;
  if (mark === null || mark === 0) return null;
  return (Math.abs(mark - p.liq_price_est) / mark) * 100;
}

function SideBadge({ side }: { side: Position["side"] }) {
  return side === "long" ? (
    <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">LONG</Badge>
  ) : (
    <Badge className="bg-red-500/15 text-red-600 dark:text-red-400">SHORT</Badge>
  );
}

export default function PositionsPage() {
  const { data, source, loading } = usePoll(getPositions, 10_000);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Open positions (simulated)</h1>
        <SourceBadge source={source} />
      </div>

      <Card className="py-0">
        <CardContent className="px-0">
          {loading || !data ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : data.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={Wallet}
                title="No open simulated positions"
                description="When the paper engine opens a position it will appear here with its full risk breakdown."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Symbol</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Lev</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Mark</TableHead>
                    <TableHead className="text-right">Stop</TableHead>
                    <TableHead className="text-right">Target</TableHead>
                    <TableHead className="text-right">Liq est</TableHead>
                    <TableHead className="text-right">Liq dist</TableHead>
                    <TableHead className="text-right">Margin</TableHead>
                    <TableHead className="text-right">Notional</TableHead>
                    <TableHead className="text-right">uP&L</TableHead>
                    <TableHead className="text-right">Funding</TableHead>
                    <TableHead className="text-right">Fees</TableHead>
                    <TableHead className="text-right">Risk</TableHead>
                    <TableHead>Sleeve</TableHead>
                    <TableHead className="text-right">Opened</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((p) => {
                    const liqDist = liqDistancePct(p);
                    return (
                      <TableRow key={p.id}>
                        <TableCell className="font-mono font-medium">{p.symbol}</TableCell>
                        <TableCell><SideBadge side={p.side} /></TableCell>
                        <TableCell className="text-right tabular-nums">{p.leverage}x</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtQty(p.qty)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtPrice(p.entry_price)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtPrice(p.mark_price)}</TableCell>
                        <TableCell className="text-right text-red-600 tabular-nums dark:text-red-400">{fmtPrice(p.stop)}</TableCell>
                        <TableCell className="text-right text-emerald-600 tabular-nums dark:text-emerald-400">{fmtPrice(p.target)}</TableCell>
                        <TableCell className="text-right text-amber-600 tabular-nums dark:text-amber-400">{fmtPrice(p.liq_price_est)}</TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            liqDist !== null && liqDist < 10
                              ? "font-semibold text-red-600 dark:text-red-400"
                              : "text-muted-foreground"
                          )}
                        >
                          {liqDist === null ? "—" : fmtPct(liqDist, 1)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{fmtUsd(p.margin_usd)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtUsd(p.notional_usd)}</TableCell>
                        <TableCell className={cn("text-right font-semibold tabular-nums", pnlClass(p.unrealized_pnl_usd))}>
                          {p.unrealized_pnl_usd === null ? "—" : fmtUsd(p.unrealized_pnl_usd, { sign: true })}
                        </TableCell>
                        <TableCell className={cn("text-right tabular-nums", pnlClass(p.funding_paid_usd))}>
                          {fmtUsd(p.funding_paid_usd, { sign: true })}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular-nums">{fmtUsd(p.fees_paid_usd)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtPct(p.planned_risk_pct, 2)}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="uppercase">{p.sleeve}</Badge>
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular-nums">{timeAgo(p.opened_at_ms)}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-[11px] text-muted-foreground">
        All positions are virtual fills from the paper engine. Liquidation prices are conservative
        estimates for the simulation; no real margin exists anywhere.
      </p>
    </div>
  );
}
