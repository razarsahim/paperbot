"use client";

import { History, Pause, Play, Rewind, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { cn } from "cn";
import { EmptyState } from "@/components/empty-state";
import {
  MultiLineChart,
  ReplayPriceChart,
  seriesColor,
  type ReplayMarker,
} from "@/components/charts/replay-charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { fmtNum, fmtPct, fmtPrice, fmtUsd, pnlClass } from "@/lib/format";

// ---------- payload types (written by `python -m paperbot_pro.replay.report`) ----------

interface Trade {
  id: number;
  strategy: string;
  symbol: string;
  side: "long" | "short";
  qty: number;
  entry_price: number;
  exit_price: number;
  stop_initial: number;
  stop_final: number;
  margin_usd: number;
  notional_usd: number;
  entry_fee_usd: number;
  exit_fee_usd: number;
  funding_usd: number;
  net_pnl_usd: number;
  entry_ms: number;
  exit_ms: number;
  exit_reason: string;
  rationale: string;
}

interface OpenPos {
  strategy: string;
  symbol: string;
  side: "long" | "short";
  qty: number;
  entry_price: number;
  mark: number | null;
  unrealized_pnl_usd: number | null;
  opened_ms: number;
  entry_fee_usd: number;
  funding_paid_usd: number;
}

interface Metrics {
  initial_capital_usd: number;
  final_equity_usd: number;
  net_realized_pnl_usd: number;
  net_unrealized_pnl_usd: number;
  net_return_pct: number;
  completed_trades: number;
  open_positions_at_end: number;
  win_rate_pct: number | null;
  avg_win_usd: number | null;
  avg_loss_usd: number | null;
  profit_factor: number | null;
  expectancy_usd: number | null;
  max_drawdown_usd: number;
  max_drawdown_pct: number;
  fees_usd: number;
  funding_usd: number;
  slippage_usd_est: number;
  liquidations: number;
  largest_win_usd: number | null;
  largest_loss_usd: number | null;
  by_side: Record<"long" | "short", { trades: number; net_pnl_usd: number; wins: number }>;
  assets_traded: string[];
  small_sample: boolean;
}

interface SleeveRow extends Metrics {
  key: string;
  name: string;
  cohort: string;
  risk_budget_usd: number;
  fidelity: string;
  fidelity_note: string;
  signals_fired: number;
  signals_approved: number;
  rejections: Record<string, number>;
  locked: boolean;
  lock_reason: string | null;
  equity_curve_hourly: [number, number][];
  trades: Trade[];
  open_at_end: OpenPos[];
}

interface CombinedRun {
  run_id: string;
  with_orderbook: boolean;
  totals: Metrics;
  per_strategy: Record<string, Metrics & { signals_fired: number; rejections: Record<string, number>; locked: boolean }>;
  trades: Trade[];
  open_at_end: OpenPos[];
  equity_curve_hourly: [number, number][];
  equity_curve_min: [number, number][];
  risk_events: { ts_ms: number; level: string; message: string }[];
}

interface Payload {
  label: string;
  window_utc: { start: string; end_exclusive: string; start_ms: number; end_ms: number; days?: number };
  small_sample_threshold: number;
  independent: SleeveRow[];
  rankings: { by_net_return: string[]; by_return_over_drawdown: string[]; by_lowest_drawdown: string[]; risk_metric: string };
  combined: CombinedRun;
  combined_deployed: CombinedRun | null;
  data_quality: Record<string, Record<string, number | null | object>>;
  candles_1h: Record<string, number[][]>;
  exit_rules: { implemented: string; hybrid_50pct_at_2R: string };
}

const WINDOWS = [
  { id: "30d", label: "30 days · 2026-09-18 → 10-18", url: "/replay/replay-2026-09-18_30d.json" },
  { id: "7d", label: "7 days · 2026-10-11 → 10-18", url: "/replay/replay-2026-10-11.json" },
];
const HOUR = 3_600_000;

function utc(ms: number): string {
  return new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

function HistBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-full border border-sky-500/50 bg-sky-500/15 px-2 text-[10px] font-semibold tracking-wider text-sky-700 dark:text-sky-300",
        className
      )}
      title="Replay of archived public market data through the unchanged Lab engine. Not live paper trading. Not predictive."
    >
      HISTORICAL BACKTEST
    </span>
  );
}

function Stat({ label, value, sub, cls }: { label: string; value: React.ReactNode; sub?: React.ReactNode; cls?: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-card/60 px-3 py-2">
      <div className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">{label}</div>
      <div className={cn("text-lg font-semibold tabular-nums", cls)}>{value}</div>
      {sub !== undefined && <div className="text-[11px] text-muted-foreground tabular-nums">{sub}</div>}
    </div>
  );
}

function pf(v: number | null) {
  if (v === null || v === undefined) return "—";
  if (!Number.isFinite(v)) return "∞";
  return v.toFixed(2);
}

/** Equity of a run at the cursor from its per-minute curve. */
function equityAt(curve: [number, number][], ms: number): number | null {
  let lo = 0, hi = curve.length - 1, ans: number | null = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (curve[mid][0] <= ms) {
      ans = curve[mid][1];
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}

/** The engine's monotonic high-water mark minus $50, sampled hourly. */
function lockThreshold(curve: [number, number][], initial: number): [number, number][] {
  const out: [number, number][] = [];
  curve.reduce((peak, [t, v], i) => {
    const p = Math.max(peak, v);
    if (i % 60 === 0 || i === curve.length - 1) out.push([t, p - 50]);
    return p;
  }, initial);
  return out;
}

export default function ReplayPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [windowId, setWindowId] = useState(WINDOWS[0].id);
  const dataUrl = WINDOWS.find((w) => w.id === windowId)!.url;
  const [hour, setHour] = useState(24 * 30);
  const [playing, setPlaying] = useState(false);
  const [rankBy, setRankBy] = useState<"net" | "risk" | "dd">("net");
  const [view, setView] = useState<"B" | "Bdep" | string>("B");
  const [symbol, setSymbol] = useState<string>("BTCUSDT");

  useEffect(() => {
    let live = true;
    fetch(dataUrl)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p: Payload) => {
        if (!live) return;
        setError(null);
        setData(p);
        setPlaying(false);
        setHour(Math.round((p.window_utc.end_ms - p.window_utc.start_ms) / HOUR));
      })
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [dataUrl]);

  const totalHours = data ? Math.round((data.window_utc.end_ms - data.window_utc.start_ms) / HOUR) : 168;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setHour((h) => {
        if (h >= totalHours) {
          setPlaying(false);
          return totalHours;
        }
        return h + Math.max(1, Math.round(totalHours / 168));
      });
    }, 350);
    return () => clearInterval(id);
  }, [playing, totalHours]);

  const cursorMs = data ? data.window_utc.start_ms + hour * HOUR : 0;

  const ranked = useMemo(() => {
    if (!data) return [];
    const order =
      rankBy === "net"
        ? data.rankings.by_net_return
        : rankBy === "risk"
          ? data.rankings.by_return_over_drawdown
          : data.rankings.by_lowest_drawdown;
    return order.map((k) => data.independent.find((r) => r.key === k)!).filter(Boolean);
  }, [data, rankBy]);

  const run: { trades: Trade[]; open: OpenPos[]; label: string } | null = useMemo(() => {
    if (!data) return null;
    if (view === "B") return { trades: data.combined.trades, open: data.combined.open_at_end, label: "Combined $500 (B, archived L2 wired)" };
    if (view === "Bdep" && data.combined_deployed)
      return { trades: data.combined_deployed.trades, open: data.combined_deployed.open_at_end, label: "Combined $500 (B, as-deployed wiring)" };
    const s = data.independent.find((r) => r.key === view);
    return s ? { trades: s.trades, open: s.open_at_end, label: `Independent $50 sleeve (A): ${s.name}` } : null;
  }, [data, view]);

  const markers: ReplayMarker[] = useMemo(() => {
    if (!run) return [];
    const out: ReplayMarker[] = [];
    for (const t of run.trades.filter((t) => t.symbol.replace("/USDT:USDT", "USDT") === symbol)) {
      out.push({ ts_ms: t.entry_ms, kind: "entry", side: t.side, label: `${t.strategy} ${t.side}` });
      out.push({ ts_ms: t.exit_ms, kind: "exit", side: t.side, label: `${t.net_pnl_usd >= 0 ? "+" : ""}${t.net_pnl_usd.toFixed(2)}`, win: t.net_pnl_usd > 0 });
    }
    for (const p of run.open.filter((p) => p.symbol.replace("/USDT:USDT", "USDT") === symbol)) {
      out.push({ ts_ms: p.opened_ms, kind: "entry", side: p.side, label: `${p.strategy} ${p.side} (open)` });
    }
    return out;
  }, [run, symbol]);

  const windowSelect = (
    <Select value={windowId} onValueChange={(v) => { setData(null); setWindowId(v); }}>
      <SelectTrigger className="h-8 w-[240px] text-xs" aria-label="Replay window"><SelectValue /></SelectTrigger>
      <SelectContent>
        {WINDOWS.map((w) => <SelectItem key={w.id} value={w.id}>{w.label}</SelectItem>)}
      </SelectContent>
    </Select>
  );

  if (error) {
    return (
      <div className="space-y-4">
        {windowSelect}
        <EmptyState
        icon={History}
        title="Replay results not found"
        description={`Run the replay and report builder first (${dataUrl}: ${error}). No demo data is shown on this page.`}
        />
      </div>
    );
  }
  if (!data) return <div className="p-6 text-sm text-muted-foreground">Loading historical replay…</div>;

  const B = data.combined;
  const bEq = equityAt(B.equity_curve_min, cursorMs);
  const bClosed = B.trades.filter((t) => t.exit_ms <= cursorMs);
  const bOpen = [...B.trades.filter((t) => t.entry_ms <= cursorMs && t.exit_ms > cursorMs), ...B.open_at_end.filter((p) => p.opened_ms <= cursorMs)];
  const thresholdLine = lockThreshold(B.equity_curve_min, B.totals.initial_capital_usd);
  const tradesSoFar = (run?.trades ?? []).filter((t) => t.entry_ms <= cursorMs).sort((a, b) => a.entry_ms - b.entry_ms);
  const symbols = Object.keys(data.candles_1h);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <Rewind className="size-5" /> {data.window_utc.days ?? Math.round(totalHours / 24)}-Day Historical Replay
          </h1>
          <p className="text-xs text-muted-foreground">
            {data.window_utc.start} → {data.window_utc.end_exclusive} (end exclusive) · unchanged Lab engine · archived Bybit public data
          </p>
        </div>
        <div className="flex items-center gap-2">
          {windowSelect}
          <HistBadge className="h-6 px-3 text-xs" />
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <div>
          <b>HISTORICAL BACKTEST — not LIVE PAPER.</b> Virtual money replayed over a past window.{" "}
          {data.independent.filter((r) => r.small_sample).length} of {data.independent.length} sleeves have fewer than{" "}
          {data.small_sample_threshold} completed trades (flagged &quot;small sample&quot;). One past window is not statistical validation: no
          ranking here is predictive. Independent $50 sleeve
          results (A) and the combined shared $500 portfolio (B) are separate experiments and must not be added together.
          Hybrid 50%-at-2R exits are <b>not implemented</b> and did not occur.
        </div>
      </div>

      {/* time slider */}
      <Card className="gap-2 py-3">
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button size="sm" variant="outline" onClick={() => { if (hour >= totalHours) setHour(0); setPlaying((p) => !p); }} aria-label={playing ? "Pause" : "Play"}>
            {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          </Button>
          <input
            type="range"
            min={0}
            max={totalHours}
            step={1}
            value={hour}
            onChange={(e) => { setPlaying(false); setHour(Number(e.target.value)); }}
            className="min-w-[200px] flex-1 accent-sky-500"
            aria-label="Replay time"
          />
          <span className="w-44 text-right font-mono text-xs tabular-nums">{utc(cursorMs)}</span>
          <span className="text-[11px] text-muted-foreground">hour {hour}/{totalHours}</span>
        </CardContent>
      </Card>

      {/* combined portfolio */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <CardTitle className="text-sm">B · Combined $500 portfolio (shared rails, 3 slots, $15 combined risk, $50 trailing drawdown)</CardTitle>
          <HistBadge />
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
            <Stat label="Equity at cursor" value={fmtUsd(bEq)} cls={pnlClass((bEq ?? 500) - 500)} />
            <Stat label="Closed trades" value={bClosed.length} sub={`net ${fmtUsd(bClosed.reduce((s, t) => s + t.net_pnl_usd, 0), { sign: true })}`} />
            <Stat label="Open at cursor" value={bOpen.length} />
            <Stat label="Final equity" value={fmtUsd(B.totals.final_equity_usd)} cls={pnlClass(B.totals.net_return_pct)} sub={fmtPct(B.totals.net_return_pct, 2, true)} />
            <Stat label="Max drawdown" value={fmtUsd(B.totals.max_drawdown_usd)} sub={fmtPct(B.totals.max_drawdown_pct)} />
            <Stat label="Costs" value={fmtUsd(B.totals.fees_usd + B.totals.slippage_usd_est + B.totals.funding_usd)} sub="fees+slip+funding" />
          </div>
          <MultiLineChart
            cursorMs={cursorMs}
            threshold={thresholdLine}
            series={[
              { name: "B archived-L2", points: B.equity_curve_hourly, color: seriesColor(0) },
              ...(data.combined_deployed ? [{ name: "B as-deployed", points: data.combined_deployed.equity_curve_hourly, color: seriesColor(1) }] : []),
            ]}
          />
          {B.risk_events.filter((e) => e.ts_ms <= cursorMs && e.level === "error").length > 0 && (
            <ul className="space-y-1 text-xs">
              {B.risk_events.filter((e) => e.ts_ms <= cursorMs && e.level === "error").slice(0, 8).map((e, i) => (
                <li key={i} className="text-red-600 dark:text-red-400">{utc(e.ts_ms)} — {e.message}</li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* independent sleeves */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">A · Independent $50 sleeves (each run alone, isolated)</CardTitle>
          <div className="flex items-center gap-2">
            <Select value={rankBy} onValueChange={(v) => setRankBy(v as "net" | "risk" | "dd")}>
              <SelectTrigger className="h-8 w-[220px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="net">Rank: net return</SelectItem>
                <SelectItem value="risk">Rank: return ÷ max drawdown</SelectItem>
                <SelectItem value="dd">Rank: lowest drawdown</SelectItem>
              </SelectContent>
            </Select>
            <HistBadge />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {["#", "Strategy", "Fidelity", "Trades", "Win%", "PF", "Expect.", "Net P&L", "Return", "Max DD", "Fees", "Funding", "Slip.", "Liq", "Lock", "Long/Short", ""].map((h) => (
                    <TableHead key={h} className="text-[11px]">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {ranked.map((r, i) => (
                  <TableRow key={r.key} className={cn("cursor-pointer text-xs", view === r.key && "bg-muted/60")} onClick={() => setView(r.key)}>
                    <TableCell>{i + 1}</TableCell>
                    <TableCell className="font-medium">{r.name}<div className="text-[10px] text-muted-foreground">{r.cohort} · ${r.risk_budget_usd}/trade</div></TableCell>
                    <TableCell title={r.fidelity_note}><Badge variant="outline" className="text-[10px]">{r.fidelity}</Badge></TableCell>
                    <TableCell className="tabular-nums">{r.completed_trades}{r.open_positions_at_end ? ` +${r.open_positions_at_end} open` : ""}</TableCell>
                    <TableCell className="tabular-nums">{r.win_rate_pct === null ? "—" : fmtPct(r.win_rate_pct, 0)}</TableCell>
                    <TableCell className="tabular-nums">{pf(r.profit_factor)}</TableCell>
                    <TableCell className="tabular-nums">{fmtUsd(r.expectancy_usd)}</TableCell>
                    <TableCell className={cn("tabular-nums", pnlClass(r.final_equity_usd - r.initial_capital_usd))}>{fmtUsd(r.final_equity_usd - r.initial_capital_usd, { sign: true })}</TableCell>
                    <TableCell className={cn("tabular-nums", pnlClass(r.net_return_pct))}>{fmtPct(r.net_return_pct, 2, true)}</TableCell>
                    <TableCell className="tabular-nums">{fmtPct(r.max_drawdown_pct, 1)}</TableCell>
                    <TableCell className="tabular-nums">{fmtUsd(r.fees_usd)}</TableCell>
                    <TableCell className="tabular-nums">{fmtUsd(r.funding_usd)}</TableCell>
                    <TableCell className="tabular-nums">{fmtUsd(r.slippage_usd_est)}</TableCell>
                    <TableCell className="tabular-nums">{r.liquidations}</TableCell>
                    <TableCell>{r.locked ? <Badge variant="destructive" className="text-[10px]">locked</Badge> : "—"}</TableCell>
                    <TableCell className="tabular-nums text-[11px]">{r.by_side.long.trades}L {fmtUsd(r.by_side.long.net_pnl_usd)} / {r.by_side.short.trades}S {fmtUsd(r.by_side.short.net_pnl_usd)}</TableCell>
                    <TableCell>{r.small_sample && <Badge variant="outline" className="border-amber-500/50 text-[10px] text-amber-700 dark:text-amber-400">small sample</Badge>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="text-[11px] text-muted-foreground">Risk-adjusted rank uses {data.rankings.risk_metric}. Click a row to load that sleeve into the trade chart and log below.</p>
          <MultiLineChart
            cursorMs={cursorMs}
            height={280}
            series={data.independent.map((r, i) => ({ name: r.key, points: r.equity_curve_hourly, color: seriesColor(i) }))}
          />
        </CardContent>
      </Card>

      {/* price + markers */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">Trade replay · {run?.label}</CardTitle>
          <div className="flex items-center gap-2">
            <Select value={view} onValueChange={setView}>
              <SelectTrigger className="h-8 w-[240px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="B">B · combined (archived L2)</SelectItem>
                {data.combined_deployed && <SelectItem value="Bdep">B · combined (as deployed)</SelectItem>}
                {data.independent.map((r) => <SelectItem key={r.key} value={r.key}>A · {r.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={symbol} onValueChange={setSymbol}>
              <SelectTrigger className="h-8 w-[130px] text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {symbols.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <ReplayPriceChart candles={data.candles_1h[symbol] ?? []} markers={markers} cursorMs={cursorMs} />
          <p className="text-[11px] text-muted-foreground">Arrows = entries (blue), circles = exits (green win / red loss), drawn on the 1h bar containing the event. Only candles closed by the cursor are shown.</p>
          <div className="max-h-[420px] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {["Entry (UTC)", "Exit (UTC)", "Strategy", "Symbol", "Side", "Entry", "Exit", "Reason", "Fees", "Funding", "Net P&L"].map((h) => (
                    <TableHead key={h} className="text-[11px]">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {tradesSoFar.map((t) => {
                  const done = t.exit_ms <= cursorMs;
                  return (
                    <TableRow key={`${t.strategy}-${t.id}`} className="text-xs">
                      <TableCell className="font-mono">{utc(t.entry_ms).slice(5, 16)}</TableCell>
                      <TableCell className="font-mono">{done ? utc(t.exit_ms).slice(5, 16) : "open…"}</TableCell>
                      <TableCell>{t.strategy}</TableCell>
                      <TableCell>{t.symbol.replace("/USDT:USDT", "")}</TableCell>
                      <TableCell>{t.side}</TableCell>
                      <TableCell className="tabular-nums">{fmtPrice(t.entry_price)}</TableCell>
                      <TableCell className="tabular-nums">{done ? fmtPrice(t.exit_price) : "—"}</TableCell>
                      <TableCell>{done ? t.exit_reason : "—"}</TableCell>
                      <TableCell className="tabular-nums">{fmtUsd(t.entry_fee_usd + (done ? t.exit_fee_usd : 0))}</TableCell>
                      <TableCell className="tabular-nums">{done ? fmtUsd(t.funding_usd) : "—"}</TableCell>
                      <TableCell className={cn("tabular-nums", done && pnlClass(t.net_pnl_usd))}>{done ? fmtUsd(t.net_pnl_usd, { sign: true }) : "—"}</TableCell>
                    </TableRow>
                  );
                })}
                {(run?.open ?? []).filter((p) => p.opened_ms <= cursorMs).map((p, i) => (
                  <TableRow key={`open-${i}`} className="text-xs italic">
                    <TableCell className="font-mono">{utc(p.opened_ms).slice(5, 16)}</TableCell>
                    <TableCell>open at window end</TableCell>
                    <TableCell>{p.strategy}</TableCell>
                    <TableCell>{p.symbol.replace("/USDT:USDT", "")}</TableCell>
                    <TableCell>{p.side}</TableCell>
                    <TableCell className="tabular-nums">{fmtPrice(p.entry_price)}</TableCell>
                    <TableCell className="tabular-nums">mark {fmtPrice(p.mark)}</TableCell>
                    <TableCell>unrealized</TableCell>
                    <TableCell className="tabular-nums">{fmtUsd(p.entry_fee_usd)}</TableCell>
                    <TableCell className="tabular-nums">{fmtUsd(p.funding_paid_usd)}</TableCell>
                    <TableCell className={cn("tabular-nums", pnlClass(p.unrealized_pnl_usd ?? 0))}>{fmtUsd(p.unrealized_pnl_usd, { sign: true })}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* fidelity + rejections */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Replay fidelity, rejections and locks (A sleeves)</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {["Strategy", "Fidelity", "Why", "Signals fired / approved", "Top rejection reasons", "Lock"].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.independent.map((r) => (
                  <TableRow key={r.key} className="align-top text-xs">
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px]">{r.fidelity}</Badge></TableCell>
                    <TableCell className="max-w-[360px] whitespace-normal text-[11px] text-muted-foreground">{r.fidelity_note}</TableCell>
                    <TableCell className="tabular-nums">{r.signals_fired} / {r.signals_approved}</TableCell>
                    <TableCell className="max-w-[320px] whitespace-normal text-[11px]">
                      {Object.entries(r.rejections).slice(0, 3).map(([k, v]) => <div key={k}>{v}× {k}</div>)}
                      {Object.keys(r.rejections).length === 0 && "—"}
                    </TableCell>
                    <TableCell className="max-w-[220px] whitespace-normal text-[11px]">{r.lock_reason ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Exit rules actually replayed</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-xs">
          <p><b>Implemented:</b> {data.exit_rules.implemented}</p>
          <p><b>Hybrid 50% at 2R:</b> {data.exit_rules.hybrid_50pct_at_2R}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Data coverage (in-window)</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                {["Symbol", "1h rows (incl. 90d warm-up)", "1m missing", "Mark 1m missing", "1h≠1m agg", "Funding prints", "OI rows", "Book days", "Book msgs", "Book max gap", "Stale/missing book samples"].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(data.data_quality).map(([s, q]) => (
                <TableRow key={s} className="text-xs tabular-nums">
                  <TableCell className="font-medium">{s}</TableCell>
                  <TableCell>{String(q.kline_1h_rows)}</TableCell>
                  <TableCell>{String(q.kline_1m_missing_in_window)}</TableCell>
                  <TableCell>{String(q.mark_1m_missing_in_window)}</TableCell>
                  <TableCell>{String(q.hourly_vs_1m_aggregate_mismatches)}</TableCell>
                  <TableCell>{String(q.funding_prints_in_window)}</TableCell>
                  <TableCell>{String(q.open_interest_rows)}</TableCell>
                  <TableCell>{String(q.book_days)}/{data.window_utc.days ?? 7}</TableCell>
                  <TableCell>{fmtNum(q.book_messages as number, 0)}</TableCell>
                  <TableCell>{q.book_max_gap_ms === null ? "—" : `${((q.book_max_gap_ms as number) / 1000).toFixed(1)}s`}</TableCell>
                  <TableCell>{String(q.book_samples_stale_or_missing)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
