"use client";

import {
  Activity,
  Ban,
  CircleDot,
  Eye,
  Gauge,
  Lock,
  TriangleAlert,
  Wallet,
} from "lucide-react";
import { cn } from "cn";
import { Sparkline } from "@/components/charts/sparkline";
import { SourceBadge } from "@/components/source-badge";
import { StatTile } from "@/components/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getAnalytics, getHealth } from "@/lib/api";
import { fmtNum, fmtPct, fmtUsd, pnlClass, timeAgo } from "@/lib/format";
import { useNow, useOverview, usePoll } from "@/lib/hooks";

export default function OverviewPage() {
  const { data: ov, source, loading } = useOverview();
  const now = useNow();
  const health = usePoll(getHealth, 15_000);
  const analytics = usePoll(getAnalytics, 60_000);

  const risk = ov?.risk;
  const paused =
    !!risk && (!risk.trading_enabled || risk.daily_locked || risk.total_locked || !!risk.pause_reason);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Overview</h1>
        <SourceBadge source={source} />
        <span className="text-xs text-muted-foreground">
          {ov ? `updated ${timeAgo(ov.ts_ms)}` : "loading…"}
        </span>
        {ov && source === "live" && now > 0 && now - ov.ts_ms > 90_000 && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300">
            <TriangleAlert className="size-3" /> data stale — engine or API not updating
          </span>
        )}
      </div>

      {paused && risk && (
        <div
          className={cn(
            "flex items-start gap-3 rounded-xl border p-4 text-sm",
            risk.total_locked
              ? "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-300"
              : "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300"
          )}
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <div>
            <p className="font-semibold">
              {risk.total_locked
                ? "Total loss pause active — no new simulated entries"
                : risk.daily_locked
                  ? "Daily loss lock active — no new simulated entries today"
                  : "Trading paused"}
            </p>
            {risk.pause_reason && <p className="mt-0.5 text-xs opacity-90">{risk.pause_reason}</p>}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile label="Equity (sim)" source={source} loading={loading} value={fmtUsd(ov?.equity_usd)} sub="virtual USD" />
        <StatTile label="Cash" source={source} loading={loading} value={fmtUsd(ov?.cash_usd)} sub={`margin used ${fmtUsd(ov?.margin_used_usd)}`} />
        <StatTile label="Free margin" source={source} loading={loading} value={fmtUsd(ov?.free_margin_usd)} />
        <StatTile label="Exposure" source={source} loading={loading} value={fmtUsd(ov?.exposure_notional_usd)} sub="notional" />
        <StatTile
          label="Daily P&L"
          source={source}
          loading={loading}
          value={fmtUsd(ov?.daily_pnl_usd, { sign: true })}
          valueClassName={pnlClass(ov?.daily_pnl_usd)}
        />
        <StatTile
          label="Total P&L"
          source={source}
          loading={loading}
          value={fmtUsd(ov?.total_pnl_usd, { sign: true })}
          valueClassName={pnlClass(ov?.total_pnl_usd)}
        />
        <StatTile label="Win rate" source={source} loading={loading} value={ov?.win_rate_pct === null ? "—" : fmtPct(ov?.win_rate_pct, 1)} sub="closed sim trades" />
        <StatTile label="Profit factor" source={source} loading={loading} value={ov?.profit_factor === null ? "—" : fmtNum(ov?.profit_factor)} />
        <StatTile
          label="Max drawdown"
          source={source}
          loading={loading}
          value={fmtPct(ov ? -ov.max_drawdown_pct : null, 1)}
          valueClassName={
            ov && ov.max_drawdown_pct > 0 ? "text-red-600 dark:text-red-400" : undefined
          }
        />
        <StatTile
          label="Risk utilisation"
          icon={<Gauge className="size-3" />}
          source={source}
          loading={loading}
          value={
            risk ? (
              <span className="flex items-center gap-2">
                {fmtPct(risk.combined_planned_risk_pct, 2)}
                <span className="text-xs font-normal text-muted-foreground">
                  / {fmtPct(risk.risk_ceiling_pct, 1)} ceiling
                </span>
              </span>
            ) : (
              "—"
            )
          }
          sub={
            risk ? (
              <span className="mt-1 block h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <span
                  className={cn(
                    "block h-full rounded-full",
                    risk.combined_planned_risk_pct / Math.max(risk.risk_ceiling_pct, 0.01) > 0.8
                      ? "bg-amber-500"
                      : "bg-emerald-500"
                  )}
                  style={{
                    width: `${Math.min(100, (risk.combined_planned_risk_pct / Math.max(risk.risk_ceiling_pct, 0.01)) * 100)}%`,
                  }}
                />
              </span>
            ) : undefined
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Pro engine */}
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="size-4" /> Pro engine
            </CardTitle>
            <SourceBadge source={health.source} />
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {health.loading || !health.data ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <Row
                  k="Status"
                  v={
                    <Badge variant={health.data.engines.pro.running ? "secondary" : "destructive"}>
                      <CircleDot className="size-3" />
                      {health.data.engines.pro.running ? "running" : "stopped"}
                    </Badge>
                  }
                />
                <Row k="Last scan" v={timeAgo(health.data.engines.pro.last_scan_ms)} />
                <Row
                  k="Auto-entry"
                  v={
                    health.data.engines.pro.auto_entry_enabled ? (
                      <Badge variant="secondary">enabled (paper)</Badge>
                    ) : (
                      <Badge variant="outline">
                        <Eye className="size-3" /> signal-only
                      </Badge>
                    )
                  }
                />
                <Row
                  k="Positions"
                  v={risk ? `${risk.open_positions} / ${risk.max_positions}` : "—"}
                />
                {risk?.pause_reason && (
                  <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-700 dark:text-amber-300">
                    <Ban className="mr-1 inline size-3" />
                    {risk.pause_reason}
                  </p>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Legacy engine */}
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="size-4" /> Legacy engine (BTC/GBP)
            </CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {loading || !ov ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <Row k="Symbol" v={<span className="font-mono text-xs">{ov.legacy.symbol}</span>} />
                <Row k="Equity (sim)" v={`£${fmtNum(ov.legacy.equity_gbp)}`} />
                <Row k="Cash" v={`£${fmtNum(ov.legacy.cash_gbp)}`} />
                <Row
                  k="Open position"
                  v={ov.legacy.open_position ? <Badge variant="secondary">yes</Badge> : <Badge variant="outline">none</Badge>}
                />
                <Row k="Closed trades" v={String(ov.legacy.closed_trades)} />
                {ov.legacy.locked_total && (
                  <p className="rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1.5 text-xs text-red-700 dark:text-red-300">
                    <Lock className="mr-1 inline size-3" /> Total loss lockout active
                  </p>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Sleeves */}
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Wallet className="size-4" /> Sleeves (virtual)
            </CardTitle>
            <SourceBadge source={source} />
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {loading || !ov ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <>
                <div className="rounded-lg border border-border/60 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Core</span>
                    <span className="font-semibold tabular-nums">{fmtUsd(ov.sleeves.core.balance_usd)}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground tabular-nums">
                    available {fmtUsd(ov.sleeves.core.available_usd)}
                  </p>
                </div>
                <div className="rounded-lg border border-border/60 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Hype</span>
                    <span className="font-semibold tabular-nums">{fmtUsd(ov.sleeves.hype.balance_usd)}</span>
                  </div>
                  <p className="mt-1 flex items-center justify-between text-xs text-muted-foreground tabular-nums">
                    <span>available {fmtUsd(ov.sleeves.hype.available_usd)}</span>
                    {ov.sleeves.hype.watch_only && (
                      <Badge variant="outline" className="border-amber-500/50 text-amber-600 dark:text-amber-400">
                        <Eye className="size-3" /> watch-only
                      </Badge>
                    )}
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-sm">Simulated equity (recent)</CardTitle>
          <SourceBadge source={analytics.source} />
        </CardHeader>
        <CardContent>
          {analytics.loading || !analytics.data ? (
            <Skeleton className="h-[90px] w-full" />
          ) : (
            <Sparkline points={analytics.data.equity_curve} height={110} />
          )}
          <p className="mt-2 text-[11px] text-muted-foreground">
            Virtual portfolio only. Past simulated performance does not predict future results.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">{k}</span>
      <span className="tabular-nums">{v}</span>
    </div>
  );
}
