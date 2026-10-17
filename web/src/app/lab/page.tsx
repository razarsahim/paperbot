"use client";

import {
  FlaskConical,
  Gauge,
  Lock,
  Radio,
  Scale,
  TrendingUp,
  Waves,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { cn } from "cn";
import { CurveChart } from "@/components/charts/curve-chart";
import { EmptyState } from "@/components/empty-state";
import { SourceBadge } from "@/components/source-badge";
import { StatTile } from "@/components/stat-tile";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  fmtDateTime,
  fmtPrice,
  fmtQty,
  fmtUsd,
  pnlClass,
  timeAgo,
} from "@/lib/format";
import { useLab, useNow } from "@/lib/hooks";
import type { Lab, LabStrategy, Source } from "@/lib/types";

const STALE_AFTER_MS = 3 * 60_000;

const STRATEGY_ICONS: Record<string, LucideIcon> = {
  breakout: Zap,
  trend: TrendingUp,
  meanrev: Waves,
  funding: Scale,
  momo: Gauge,
};

function strategyIcon(key: string): LucideIcon {
  return STRATEGY_ICONS[key] ?? FlaskConical;
}

/**
 * Header status chips. Mock/demo data is ALWAYS labelled with the amber DEMO
 * badge and never "LIVE PAPER" — that label is reserved for a reachable
 * backend whose lab engine reports live:true (still simulated funds).
 */
function LabStatusChips({
  status,
  source,
  now,
}: {
  status: Lab["status"] | undefined;
  source: Source;
  now: number;
}) {
  const stale =
    status !== undefined &&
    now > 0 &&
    (status.last_scan_ms === null || now - status.last_scan_ms > STALE_AFTER_MS);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {source === "demo" ? (
        <SourceBadge source="demo" />
      ) : status?.live ? (
        <span
          className="inline-flex h-5 shrink-0 items-center rounded-full border border-emerald-500/50 px-2 text-[10px] font-semibold tracking-wider text-emerald-600 dark:text-emerald-400"
          title="Lab engine running on the local backend — virtual funds only"
        >
          LIVE PAPER
        </span>
      ) : (
        <span
          className="inline-flex h-5 shrink-0 items-center rounded-full border border-red-500/50 bg-red-500/10 px-2 text-[10px] font-semibold tracking-wider text-red-600 dark:text-red-400"
          title="Backend reachable but the Lab engine is not running"
        >
          OFFLINE — engine not running
        </span>
      )}
      {stale && (
        <span
          className="inline-flex h-5 shrink-0 items-center gap-1 rounded-full border border-amber-500/50 bg-amber-500/15 px-2 text-[10px] font-semibold tracking-wider text-amber-600 dark:text-amber-400"
          title="Last lab scan is older than 3 minutes — data may be stale"
        >
          STALE · {timeAgo(status?.last_scan_ms)}
        </span>
      )}
      {status?.manual_pause && (
        <Badge variant="outline" className="text-[10px] tracking-wider uppercase">
          manually paused
        </Badge>
      )}
    </div>
  );
}

function ActionBadge({ action }: { action: string }) {
  const a = action.toLowerCase();
  if (a === "long") {
    return <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">LONG</Badge>;
  }
  if (a === "short") {
    return <Badge className="bg-red-500/15 text-red-600 dark:text-red-400">SHORT</Badge>;
  }
  return <Badge variant="outline" className="uppercase">{action}</Badge>;
}

function ExitReasonBadge({ reason }: { reason: string }) {
  const emergency = /emergency/i.test(reason);
  return (
    <Badge
      variant="outline"
      className={cn(
        "uppercase",
        emergency &&
          "border-red-500/60 bg-red-500/15 font-bold text-red-600 dark:text-red-400"
      )}
    >
      {reason}
    </Badge>
  );
}

function StrategyBadge({ k, strategies }: { k: string; strategies: LabStrategy[] }) {
  const s = strategies.find((x) => x.key === k);
  return (
    <Badge variant="outline" className="font-mono text-[10px]">
      {s?.display_name ?? k}
    </Badge>
  );
}

function allowanceClass(usd: number): string {
  if (usd < 5) return "text-red-600 dark:text-red-400";
  if (usd < 15) return "text-amber-600 dark:text-amber-400";
  return "";
}

function auditLevelClass(level: string): string {
  const l = level.toLowerCase();
  if (l === "error") return "text-red-600 dark:text-red-400";
  if (l === "warning") return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

export default function LabPage() {
  const { data, source, loading } = useLab();
  const now = useNow(15_000);
  const lab = data ?? null;

  const equityPoints: [number, number][] =
    lab?.equity_curve.map(([t, eq]) => [t, eq]) ?? [];
  const thresholdPoints: [number, number][] =
    lab?.equity_curve.map(([t, , th]) => [t, th]) ?? [];

  const symbols = lab ? Object.keys(lab.opportunities) : [];

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <FlaskConical className="size-5 text-muted-foreground" />
          Extreme Lab
        </h1>
        <LabStatusChips status={lab?.status} source={source} now={now} />
      </div>

      {/* Emergency lockout banner */}
      {lab?.status.locked && (
        <div className="flex w-full flex-col gap-1 rounded-xl border border-red-500/60 bg-red-500/10 p-4">
          <p className="flex items-center gap-2 text-sm font-bold tracking-wide text-red-600 uppercase dark:text-red-400">
            <Lock className="size-4 shrink-0" />
            EMERGENCY LOCKOUT — trailing drawdown breached
          </p>
          {lab.status.lock_reason && (
            <p className="text-sm text-red-700 dark:text-red-300">{lab.status.lock_reason}</p>
          )}
          <p className="text-xs text-muted-foreground">
            New entries are blocked and stay blocked. Manual reset required: run{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
              propaper lab-reset --note &quot;...&quot;
            </code>
          </p>
        </div>
      )}

      {/* Capital row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Initial (virtual)"
          value={fmtUsd(lab?.capital.initial_usd ?? 250)}
          source={source}
          loading={loading}
        />
        <StatTile
          label="Equity"
          value={fmtUsd(lab?.capital.equity_usd)}
          sub={lab ? `unrealized ${fmtUsd(lab.capital.unrealized_usd, { sign: true })}` : undefined}
          source={source}
          loading={loading}
        />
        <StatTile
          label="Peak equity"
          value={fmtUsd(lab?.capital.peak_equity_usd)}
          source={source}
          loading={loading}
        />
        <StatTile
          label="Trailing threshold"
          value={fmtUsd(lab?.capital.threshold_usd)}
          sub="lockout below this line"
          source={source}
          loading={loading}
        />
        <StatTile
          label="Remaining allowance"
          value={fmtUsd(lab?.capital.remaining_allowance_usd)}
          valueClassName={lab ? allowanceClass(lab.capital.remaining_allowance_usd) : undefined}
          sub="equity − threshold"
          source={source}
          loading={loading}
        />
        <StatTile
          label="Margin used"
          value={fmtUsd(lab?.capital.margin_used_usd)}
          sub={lab ? `cash ${fmtUsd(lab.capital.cash_usd)}` : undefined}
          source={source}
          loading={loading}
        />
      </div>

      {/* Equity chart with trailing threshold */}
      <Card>
        <CardHeader className="flex-row items-center justify-between py-3">
          <CardTitle className="text-sm">
            Lab equity (virtual USD) vs trailing lockout threshold
          </CardTitle>
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1.5 text-[10px] text-muted-foreground sm:inline-flex">
              <span className="inline-block h-0 w-5 border-t-2 border-dashed border-red-500" />
              threshold
            </span>
            <SourceBadge source={source} />
          </div>
        </CardHeader>
        <CardContent>
          {loading || !lab ? (
            <Skeleton className="h-[260px] w-full" />
          ) : (
            <CurveChart points={equityPoints} threshold={thresholdPoints} mode="area" />
          )}
        </CardContent>
      </Card>

      {/* Strategy cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
        {loading || !lab
          ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-36 w-full" />)
          : lab.strategies.map((s) => {
              const Icon = strategyIcon(s.key);
              return (
                <Card key={s.key} className="gap-2 rounded-xl border-border/60 bg-card/60 py-4">
                  <CardHeader className="flex-row items-center justify-between py-0">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      {s.display_name}
                    </CardTitle>
                    <SourceBadge source={source} />
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2">
                    <p className="text-xs leading-snug text-muted-foreground">{s.description}</p>
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <p className="text-[10px] tracking-wider text-muted-foreground uppercase">Alloc</p>
                        <p className="font-semibold tabular-nums">{fmtUsd(s.allocation_usd)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] tracking-wider text-muted-foreground uppercase">Cash</p>
                        <p className="font-semibold tabular-nums">{fmtUsd(s.cash_usd)}</p>
                      </div>
                      <div>
                        <p className="text-[10px] tracking-wider text-muted-foreground uppercase">Real. P&L</p>
                        <p className={cn("font-semibold tabular-nums", pnlClass(s.realized_pnl_usd))}>
                          {fmtUsd(s.realized_pnl_usd, { sign: true })}
                        </p>
                      </div>
                    </div>
                    <div className="flex min-h-5 flex-wrap gap-1">
                      {s.open_symbols.length === 0 ? (
                        <span className="text-[10px] text-muted-foreground">no open symbols</span>
                      ) : (
                        s.open_symbols.map((sym) => (
                          <Badge key={sym} variant="outline" className="font-mono text-[10px]">
                            {sym}
                          </Badge>
                        ))
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
      </div>

      {/* Opportunities matrix */}
      <Card className="py-0">
        <CardHeader className="flex-row items-center justify-between py-3">
          <CardTitle className="text-sm">Currently analysed opportunities</CardTitle>
          <SourceBadge source={source} />
        </CardHeader>
        <CardContent className="px-0 pb-3">
          {loading || !lab ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : symbols.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={Radio}
                title="No symbols in the current scan window"
                description="The Lab scanner has not produced an opportunity matrix yet."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Symbol</TableHead>
                    {lab.strategies.map((s) => (
                      <TableHead key={s.key} className="text-center">
                        {s.display_name}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {symbols.map((sym) => {
                    const row = lab.opportunities[sym];
                    return (
                      <TableRow key={sym}>
                        <TableCell className="font-mono font-medium">{sym}</TableCell>
                        {lab.strategies.map((s) => {
                          const cell = row[s.key];
                          return (
                            <TableCell key={s.key} className="text-center">
                              {cell ? (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span className="inline-flex cursor-default justify-center">
                                      {cell.action ? (
                                        <ActionBadge action={cell.action} />
                                      ) : (
                                        <span className="text-muted-foreground/60">—</span>
                                      )}
                                    </span>
                                  </TooltipTrigger>
                                  <TooltipContent>{cell.reason}</TooltipContent>
                                </Tooltip>
                              ) : (
                                <span className="text-muted-foreground/60">—</span>
                              )}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Signals + positions */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="py-0 xl:col-span-1">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Signals feed</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="flex flex-col gap-2 pb-4">
            {loading || !lab ? (
              Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)
            ) : lab.signals.length === 0 ? (
              <EmptyState icon={Radio} title="No Lab signals yet" />
            ) : (
              lab.signals.map((sig) => (
                <div
                  key={sig.id}
                  className={cn(
                    "rounded-lg border p-2.5",
                    sig.approved
                      ? "border-emerald-500/30 bg-emerald-500/5"
                      : "border-border/60 bg-muted/30"
                  )}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <ActionBadge action={sig.action} />
                    <span className="font-mono text-xs font-medium">{sig.symbol}</span>
                    <StrategyBadge k={sig.strategy} strategies={lab.strategies} />
                    <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">
                      {timeAgo(sig.ts_ms)}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">{sig.details}</p>
                  {sig.approved ? (
                    <p className="mt-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                      Approved by all risk gates
                    </p>
                  ) : (
                    <p className="mt-0.5 text-[11px] font-medium text-muted-foreground">
                      Rejected{sig.reject_reason ? ` — ${sig.reject_reason}` : ""}
                    </p>
                  )}
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="py-0 xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Open Lab positions (simulated)</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="px-0 pb-3">
            {loading || !lab ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : lab.positions.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  icon={FlaskConical}
                  title="No open Lab positions"
                  description="No open Lab positions — entries require the Lab auto-entry flag and all risk gates."
                />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table className="text-xs">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Strategy</TableHead>
                      <TableHead>Symbol</TableHead>
                      <TableHead>Side</TableHead>
                      <TableHead>Lev</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Entry</TableHead>
                      <TableHead className="text-right">Mark</TableHead>
                      <TableHead className="text-right">Stop</TableHead>
                      <TableHead className="text-right">Target</TableHead>
                      <TableHead className="text-right">Liq est</TableHead>
                      <TableHead className="text-right">Margin</TableHead>
                      <TableHead className="text-right">Notional</TableHead>
                      <TableHead className="text-right">Funding</TableHead>
                      <TableHead className="text-right">uP&L</TableHead>
                      <TableHead className="text-right">Planned risk</TableHead>
                      <TableHead className="text-right">Opened</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {lab.positions.map((p) => (
                      <TableRow key={p.id}>
                        <TableCell>
                          <StrategyBadge k={p.strategy} strategies={lab.strategies} />
                        </TableCell>
                        <TableCell className="font-mono font-medium">{p.symbol}</TableCell>
                        <TableCell>
                          <ActionBadge action={p.side} />
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="tabular-nums">
                            {p.leverage}x
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{fmtQty(p.qty)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtPrice(p.entry_price)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtPrice(p.mark_price)}</TableCell>
                        <TableCell className="text-right text-red-600 tabular-nums dark:text-red-400">
                          {fmtPrice(p.stop)}
                        </TableCell>
                        <TableCell className="text-right text-emerald-600 tabular-nums dark:text-emerald-400">
                          {fmtPrice(p.target)}
                        </TableCell>
                        <TableCell className="text-right text-amber-600 tabular-nums dark:text-amber-400">
                          {fmtPrice(p.liq_price_est)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{fmtUsd(p.margin_usd)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmtUsd(p.notional_usd)}</TableCell>
                        <TableCell className={cn("text-right tabular-nums", pnlClass(p.funding_paid_usd))}>
                          {fmtUsd(p.funding_paid_usd, { sign: true })}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-semibold tabular-nums",
                            pnlClass(p.unrealized_pnl_usd)
                          )}
                        >
                          {p.unrealized_pnl_usd === null
                            ? "—"
                            : fmtUsd(p.unrealized_pnl_usd, { sign: true })}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtUsd(p.planned_risk_usd)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular-nums">
                          {timeAgo(p.opened_ms)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Completed trades + audit trail */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="py-0 xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Completed Lab trades (simulated)</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="px-0 pb-3">
            {loading || !lab ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : lab.trades.length === 0 ? (
              <div className="p-4">
                <EmptyState icon={FlaskConical} title="No completed Lab trades yet" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table className="text-xs">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Strategy</TableHead>
                      <TableHead>Symbol</TableHead>
                      <TableHead>Side</TableHead>
                      <TableHead>Lev</TableHead>
                      <TableHead className="text-right">Entry → Exit</TableHead>
                      <TableHead className="text-right">Fees + funding</TableHead>
                      <TableHead className="text-right">Net P&L</TableHead>
                      <TableHead>Exit reason</TableHead>
                      <TableHead className="text-right">Closed</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {lab.trades.map((t) => (
                      <TableRow key={t.id} title={t.rationale}>
                        <TableCell>
                          <StrategyBadge k={t.strategy} strategies={lab.strategies} />
                        </TableCell>
                        <TableCell className="font-mono font-medium">{t.symbol}</TableCell>
                        <TableCell>
                          <ActionBadge action={t.side} />
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="tabular-nums">
                            {t.leverage}x
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right whitespace-nowrap tabular-nums">
                          {fmtPrice(t.entry_price)} → {fmtPrice(t.exit_price)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular-nums">
                          {fmtUsd(t.entry_fee_usd + t.exit_fee_usd + t.funding_usd)}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right font-semibold tabular-nums",
                            pnlClass(t.net_pnl_usd)
                          )}
                        >
                          {fmtUsd(t.net_pnl_usd, { sign: true })}
                        </TableCell>
                        <TableCell>
                          <ExitReasonBadge reason={t.exit_reason} />
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground whitespace-nowrap tabular-nums">
                          {fmtDateTime(t.exit_ms)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="py-0 xl:col-span-1">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">Audit trail</CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="flex flex-col gap-2 pb-4">
            {loading || !lab ? (
              Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)
            ) : lab.audit.length === 0 ? (
              <EmptyState icon={Radio} title="No audit entries yet" />
            ) : (
              lab.audit.map((a) => (
                <div key={a.id} className="rounded-lg border border-border/60 p-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-[10px] font-bold tracking-wider uppercase",
                        auditLevelClass(a.level)
                      )}
                    >
                      {a.level}
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">{a.category}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">
                      {timeAgo(a.ts_ms)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] leading-snug">{a.message}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      {/* Disclaimer */}
      <p className="text-[11px] text-muted-foreground">
        Extreme Lab is a speculative PAPER-ONLY research simulation with virtual funds. Nothing here
        is investment advice, and negative results are expected.
      </p>
    </div>
  );
}
