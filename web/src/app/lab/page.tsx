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
import { useState } from "react";
import {
  fmtDateTime,
  fmtPct,
  fmtPrice,
  fmtQty,
  fmtUsd,
  pnlClass,
  timeAgo,
} from "@/lib/format";
import { useLab, useLabLive, useNow } from "@/lib/hooks";
import type {
  Lab,
  LabLiveCapital,
  LabLivePosition,
  LabLiveStatus,
  LabPosition,
  LabStrategy,
  Source,
} from "@/lib/types";

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

/**
 * Live-stream status badge. Driven purely by the `lab_live` SSE stream;
 * an unreachable EventSource is always rendered as DISCONNECTED, even if a
 * payload was received earlier.
 */
function LiveStreamBadge({
  status,
  publishAgeMs,
}: {
  status: LabLiveStatus;
  publishAgeMs: number | undefined;
}) {
  if (status === "LIVE") {
    return (
      <span
        className="inline-flex h-5 shrink-0 items-center rounded-full border border-emerald-500/50 bg-emerald-500/10 px-2 text-[10px] font-semibold tracking-wider text-emerald-600 dark:text-emerald-400"
        title="Continuous Lab P&L stream connected — virtual funds only"
      >
        LIVE PAPER
      </span>
    );
  }
  if (status === "STALE") {
    return (
      <span
        className="inline-flex h-5 shrink-0 items-center rounded-full border border-amber-500/50 bg-amber-500/15 px-2 text-[10px] font-semibold tracking-wider text-amber-600 dark:text-amber-400"
        title="Stream connected but the engine snapshot is old"
      >
        STALE{publishAgeMs !== undefined ? ` · ${Math.round(publishAgeMs / 1000)}s` : ""}
      </span>
    );
  }
  return (
    <span
      className="inline-flex h-5 shrink-0 items-center rounded-full border border-red-500/50 bg-red-500/10 px-2 text-[10px] font-semibold tracking-wider text-red-600 dark:text-red-400"
      title="Live stream unavailable — showing the last stored Lab state from the slow API"
    >
      DISCONNECTED — using last stored state
    </span>
  );
}

/** Feed-to-UI latency chip; receipt time is captured when the SSE event arrives. */
function LatencyChip({ ms }: { ms: number }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex h-5 shrink-0 cursor-default items-center rounded-full border border-border/60 bg-muted/40 px-2 font-mono text-[10px] text-muted-foreground tabular-nums">
          feed → UI ~{Math.round(ms)}ms
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Approximate only: compares the newest exchange ticker timestamp with this
        device&apos;s clock at event receipt. Clock skew between the exchange, the
        local API server and this browser can bias it (negatives are clamped to 0).
      </TooltipContent>
    </Tooltip>
  );
}

/** Row model for the positions table: live stream fields merged over slow data. */
interface PositionRow {
  id: number;
  strategy: string;
  symbol: string;
  side: string;
  leverage: number;
  qty: number;
  entry_price: number;
  mark_price: number | null;
  bid: number | null;
  ask: number | null;
  stop: number;
  target: number | null;
  liq_price_est: number;
  margin_usd: number;
  notional_usd: number;
  funding_paid_usd: number;
  unrealized_pnl_usd: number | null;
  unrealized_pct_on_margin: number | null;
  stop_distance_pct: number | null;
  liq_distance_pct: number | null;
  planned_risk_usd: number | null;
  opened_ms: number | null;
}

/**
 * Merge live positions over the slow snapshot (matched by id for fields the
 * stream does not carry: target, planned risk, opened time). With no live
 * data, fall back to the stored positions; distance/bid/ask columns are shown
 * as "—" rather than recomputed from possibly-stale stored prices.
 */
function buildPositionRows(
  basePositions: LabPosition[],
  livePositions: LabLivePosition[] | null
): PositionRow[] {
  if (livePositions !== null) {
    const byId = new Map<number, LabPosition>(basePositions.map((p) => [p.id, p]));
    return livePositions.map((lp) => {
      const b = byId.get(lp.id);
      return {
        id: lp.id,
        strategy: lp.strategy,
        symbol: lp.symbol,
        side: lp.side,
        leverage: lp.leverage,
        qty: lp.qty,
        entry_price: lp.entry_price,
        mark_price: lp.mark_price,
        bid: lp.bid,
        ask: lp.ask,
        stop: lp.stop,
        target: b?.target ?? null,
        liq_price_est: lp.liq_price_est,
        margin_usd: lp.margin_usd,
        notional_usd: lp.notional_usd,
        funding_paid_usd: lp.funding_paid_usd,
        unrealized_pnl_usd: lp.unrealized_pnl_usd,
        unrealized_pct_on_margin: lp.unrealized_pct_on_margin,
        stop_distance_pct: lp.stop_distance_pct,
        liq_distance_pct: lp.liq_distance_pct,
        planned_risk_usd: b?.planned_risk_usd ?? null,
        opened_ms: b?.opened_ms ?? null,
      };
    });
  }
  return basePositions.map((p) => ({
    id: p.id,
    strategy: p.strategy,
    symbol: p.symbol,
    side: p.side,
    leverage: p.leverage,
    qty: p.qty,
    entry_price: p.entry_price,
    mark_price: p.mark_price,
    bid: null,
    ask: null,
    stop: p.stop,
    target: p.target,
    liq_price_est: p.liq_price_est,
    margin_usd: p.margin_usd,
    notional_usd: p.notional_usd,
    funding_paid_usd: p.funding_paid_usd,
    unrealized_pnl_usd: p.unrealized_pnl_usd,
    unrealized_pct_on_margin:
      p.unrealized_pnl_usd !== null && p.margin_usd > 0
        ? (p.unrealized_pnl_usd / p.margin_usd) * 100
        : null,
    stop_distance_pct: null,
    liq_distance_pct: null,
    planned_risk_usd: p.planned_risk_usd,
    opened_ms: p.opened_ms,
  }));
}

/** Amber below 2% distance, red below 0.8%. */
function distanceClass(pct: number | null): string {
  if (pct === null) return "text-muted-foreground/60";
  if (pct < 0.8) return "font-semibold text-red-600 dark:text-red-400";
  if (pct < 2) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

/**
 * Mark price cell that flashes its background green/red based on the
 * direction of change. Pure CSS background animation retriggered by a key
 * bump — the number itself is never animated or interpolated. Direction is
 * derived with the guarded set-state-during-render pattern (no Date.now and
 * no setState inside effects, per the react-hooks purity rules).
 */
function MarkPriceCell({
  mark,
  bid,
  ask,
}: {
  mark: number | null;
  bid: number | null;
  ask: number | null;
}) {
  const [tick, setTick] = useState<{
    mark: number | null;
    dir: "up" | "down" | null;
    seq: number;
  }>({ mark: null, dir: null, seq: 0 });
  if (mark !== tick.mark) {
    setTick({
      mark,
      dir:
        mark !== null && tick.mark !== null
          ? mark > tick.mark
            ? "up"
            : "down"
          : null,
      seq: tick.seq + 1,
    });
  }
  return (
    <TableCell
      key={tick.seq}
      className={cn(
        "text-right tabular-nums",
        tick.dir === "up" && "lab-flash-up",
        tick.dir === "down" && "lab-flash-down"
      )}
    >
      <span className="font-medium">{fmtPrice(mark)}</span>
      {(bid !== null || ask !== null) && (
        <span className="block text-[10px] leading-tight text-muted-foreground">
          {fmtPrice(bid)} / {fmtPrice(ask)}
        </span>
      )}
    </TableCell>
  );
}

/** Local wall-clock time with seconds for the "last market event" line. */
function fmtClock(ms: number): string {
  return new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Relative age from a ticking `now` (never calls Date.now in render). */
function relAge(deltaMs: number): string {
  const s = Math.floor(Math.max(0, deltaMs) / 1000);
  if (s < 1) return "<1s ago";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
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
  const { live, connected, receivedAtMs } = useLabLive();
  const now = useNow(15_000);
  const nowFast = useNow(1_000);
  const lab = data ?? null;

  // EventSource down => DISCONNECTED regardless of the last payload received.
  const liveStatus: LabLiveStatus =
    connected && live !== null ? live.live_status : "DISCONNECTED";
  const disconnected = liveStatus === "DISCONNECTED";

  // Live overlays — only trusted while the stream itself is not DISCONNECTED.
  const liveCapital: LabLiveCapital | null = disconnected ? null : (live?.capital ?? null);
  const livePositions: LabLivePosition[] | null = disconnected
    ? null
    : (live?.positions ?? null);
  const locked = Boolean(lab?.status.locked) || (!disconnected && Boolean(live?.locked));

  // Feed → UI latency: client clock captured at SSE receipt vs. exchange ts.
  const latencyMs =
    liveStatus === "LIVE" &&
    receivedAtMs !== null &&
    live?.exchange_ts_ms !== null &&
    live?.exchange_ts_ms !== undefined
      ? Math.max(0, receivedAtMs - live.exchange_ts_ms)
      : null;

  // Capital: live stream when present, otherwise the stored slow snapshot.
  const capital = liveCapital ?? lab?.capital ?? null;
  const capitalSource: Source = liveCapital ? "live" : source;
  const capitalLoading = loading && liveCapital === null;

  const positionRows = buildPositionRows(lab?.positions ?? [], livePositions);
  const positionsSource: Source = livePositions !== null ? "live" : source;
  const positionsLoading = loading && livePositions === null;

  // Newest exchange ticker timestamp seen in the last received payload.
  let lastMarketTs: number | null =
    typeof live?.exchange_ts_ms === "number" ? live.exchange_ts_ms : null;
  for (const p of live?.positions ?? []) {
    if (p.exchange_ts_ms !== null && (lastMarketTs === null || p.exchange_ts_ms > lastMarketTs)) {
      lastMarketTs = p.exchange_ts_ms;
    }
  }

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
        <div className="flex flex-wrap items-center gap-2">
          <LiveStreamBadge status={liveStatus} publishAgeMs={live?.publish_age_ms} />
          {latencyMs !== null && <LatencyChip ms={latencyMs} />}
          {disconnected ? (
            // Stream down: fall back to the stored-state chips from useLab().
            <LabStatusChips status={lab?.status} source={source} now={now} />
          ) : (
            lab?.status.manual_pause && (
              <Badge variant="outline" className="text-[10px] tracking-wider uppercase">
                manually paused
              </Badge>
            )
          )}
        </div>
      </div>

      {/* Emergency lockout banner (stored state OR live stream) */}
      {locked && (
        <div className="flex w-full flex-col gap-1 rounded-xl border border-red-500/60 bg-red-500/10 p-4">
          <p className="flex items-center gap-2 text-sm font-bold tracking-wide text-red-600 uppercase dark:text-red-400">
            <Lock className="size-4 shrink-0" />
            EMERGENCY LOCKOUT — trailing drawdown breached
          </p>
          {lab?.status.lock_reason && (
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

      {/* Capital row — overlaid with live stream values when present */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="Initial (virtual)"
          value={fmtUsd(capital?.initial_usd ?? 250)}
          source={capitalSource}
          loading={capitalLoading}
        />
        <StatTile
          label="Equity"
          value={fmtUsd(capital?.equity_usd)}
          sub={
            liveCapital ? (
              <span>
                unrealized{" "}
                <span className={pnlClass(liveCapital.unrealized_usd)}>
                  {fmtUsd(liveCapital.unrealized_usd, { sign: true })}
                </span>
                {" · "}realized{" "}
                <span className={pnlClass(liveCapital.realized_usd)}>
                  {fmtUsd(liveCapital.realized_usd, { sign: true })}
                </span>
              </span>
            ) : lab ? (
              `unrealized ${fmtUsd(lab.capital.unrealized_usd, { sign: true })}`
            ) : undefined
          }
          source={capitalSource}
          loading={capitalLoading}
        />
        <StatTile
          label="Peak equity"
          value={fmtUsd(capital?.peak_equity_usd)}
          source={capitalSource}
          loading={capitalLoading}
        />
        <StatTile
          label="Trailing threshold"
          value={fmtUsd(capital?.threshold_usd)}
          sub="lockout below this line"
          source={capitalSource}
          loading={capitalLoading}
        />
        <StatTile
          label="Remaining allowance"
          value={fmtUsd(capital?.remaining_allowance_usd)}
          valueClassName={
            capital ? allowanceClass(capital.remaining_allowance_usd) : undefined
          }
          sub="equity − threshold"
          source={capitalSource}
          loading={capitalLoading}
        />
        <StatTile
          label="Margin used"
          value={fmtUsd(capital?.margin_used_usd)}
          sub={capital ? `cash ${fmtUsd(capital.cash_usd)}` : undefined}
          source={capitalSource}
          loading={capitalLoading}
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
            <SourceBadge source={positionsSource} />
          </CardHeader>
          <CardContent className="px-0 pb-3">
            {positionsLoading && positionRows.length === 0 ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : positionRows.length === 0 ? (
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
                      <TableHead className="text-right">Mark · bid/ask</TableHead>
                      <TableHead className="text-right">Stop</TableHead>
                      <TableHead className="text-right">→ Stop</TableHead>
                      <TableHead className="text-right">Target</TableHead>
                      <TableHead className="text-right">Liq est</TableHead>
                      <TableHead className="text-right">→ Liq</TableHead>
                      <TableHead className="text-right">Margin</TableHead>
                      <TableHead className="text-right">Notional</TableHead>
                      <TableHead className="text-right">Funding</TableHead>
                      <TableHead className="text-right">uP&L</TableHead>
                      <TableHead className="text-right">Planned risk</TableHead>
                      <TableHead className="text-right">Opened</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {positionRows.map((p) => (
                      <TableRow key={p.id}>
                        <TableCell>
                          <StrategyBadge
                            k={p.strategy}
                            strategies={lab?.strategies ?? []}
                          />
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
                        <MarkPriceCell mark={p.mark_price} bid={p.bid} ask={p.ask} />
                        <TableCell className="text-right text-red-600 tabular-nums dark:text-red-400">
                          {fmtPrice(p.stop)}
                        </TableCell>
                        <TableCell
                          className={cn("text-right tabular-nums", distanceClass(p.stop_distance_pct))}
                        >
                          {p.stop_distance_pct === null ? "—" : fmtPct(p.stop_distance_pct)}
                        </TableCell>
                        <TableCell className="text-right text-emerald-600 tabular-nums dark:text-emerald-400">
                          {fmtPrice(p.target)}
                        </TableCell>
                        <TableCell className="text-right text-amber-600 tabular-nums dark:text-amber-400">
                          {fmtPrice(p.liq_price_est)}
                        </TableCell>
                        <TableCell
                          className={cn("text-right tabular-nums", distanceClass(p.liq_distance_pct))}
                        >
                          {p.liq_distance_pct === null ? "—" : fmtPct(p.liq_distance_pct)}
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
                          {p.unrealized_pct_on_margin !== null && (
                            <span
                              className={cn(
                                "block text-[10px] leading-tight font-normal",
                                pnlClass(p.unrealized_pct_on_margin)
                              )}
                            >
                              {fmtPct(p.unrealized_pct_on_margin, 2, true)} on margin
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {p.planned_risk_usd === null ? "—" : fmtUsd(p.planned_risk_usd)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground tabular-nums">
                          {p.opened_ms === null ? "—" : timeAgo(p.opened_ms)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {lastMarketTs !== null && (
              <p className="px-4 pt-2 text-[11px] text-muted-foreground tabular-nums">
                Last market event: {fmtClock(lastMarketTs)}
                {nowFast > 0 ? ` · ${relAge(nowFast - lastMarketTs)}` : ""}
              </p>
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
