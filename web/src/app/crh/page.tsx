"use client";

import {
  Activity,
  Download,
  FlaskConical,
  GitCompare,
  Play,
  Radar,
  Square,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "cn";
import { CrhChart } from "@/components/charts/crh-chart";
import { MultiLineChart, seriesColor } from "@/components/charts/replay-charts";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fmtPct, fmtPrice, fmtUsd, pnlClass } from "@/lib/format";
import {
  CRH_API_BASE, crh, type ChartData, type Compare, type Forward, type Job, type RunResult,
  type RunRow, type Scanner, type Trade,
} from "@/lib/crh-api";

// ---------- small shared bits ----------
type Mode = "HISTORICAL BACKTEST" | "FORWARD PAPER" | "LIVE MARKET DATA";
const MODE_CLS: Record<Mode, string> = {
  "HISTORICAL BACKTEST": "border-sky-500/50 bg-sky-500/15 text-sky-700 dark:text-sky-300",
  "FORWARD PAPER": "border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  "LIVE MARKET DATA": "border-violet-500/50 bg-violet-500/10 text-violet-700 dark:text-violet-300",
};
function ModeBadge({ mode, className }: { mode: Mode; className?: string }) {
  return <span className={cn("inline-flex h-5 shrink-0 items-center rounded-full border px-2 text-[10px] font-semibold tracking-wider", MODE_CLS[mode], className)}>{mode}</span>;
}
function Tile({ label, value, sub, cls }: { label: string; value: React.ReactNode; sub?: React.ReactNode; cls?: string }) {
  return (
    <div className="rounded-lg border border-border/60 bg-card/60 px-3 py-2">
      <div className="truncate text-[10px] font-medium tracking-wider text-muted-foreground uppercase">{label}</div>
      <div className={cn("text-lg font-semibold tabular-nums", cls)}>{value}</div>
      {sub !== undefined && <div className="text-[11px] text-muted-foreground tabular-nums">{sub}</div>}
    </div>
  );
}
const utc = (ms: number | null | undefined) => (ms ? new Date(ms).toISOString().replace("T", " ").slice(0, 16) + "Z" : "—");
const pf = (v: number | null | undefined) => (v === null || v === undefined ? "—" : Number.isFinite(v) ? v.toFixed(2) : "∞");
const dur = (a: number, b: number) => { const m = Math.round((b - a) / 60000); return m < 120 ? `${m}m` : `${(m / 60).toFixed(1)}h`; };
const isoLocalToUtc = (s: string) => (s ? new Date(s + "Z").toISOString() : "");

// ---------- controls ----------
interface Form {
  preset: string; start: string; end: string; universe: string; symbols: string;
  capital: string; leverage: string; riskPct: string; lossTrigger: string; fidelity: string;
  timeframe: string; label: string;
}
const DEFAULT_FORM: Form = {
  preset: "48h", start: "", end: "", universe: "top50", symbols: "", capital: "500", leverage: "10",
  riskPct: "10", lossTrigger: "", fidelity: "exact", timeframe: "1h", label: "",
};
function formToParams(f: Form): Record<string, unknown> {
  const p: Record<string, unknown> = {
    capital: Number(f.capital), leverage: Number(f.leverage), fidelity: f.fidelity,
    signal_timeframe: f.timeframe, risk_pct: Number(f.riskPct),
  };
  if (f.preset === "custom") { p.start = isoLocalToUtc(f.start); p.end = isoLocalToUtc(f.end); } else p.preset = f.preset;
  if (f.symbols.trim()) p.symbols = f.symbols.split(/[,\s]+/).filter(Boolean).map((s) => (s.includes("/") ? s : `${s.toUpperCase()}/USDT:USDT`));
  else p.universe = f.universe;
  if (f.lossTrigger) p.strategy_loss_trigger_usd = Number(f.lossTrigger);
  if (f.label) p.label = f.label;
  return p;
}

export default function CrhPage() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [form, setForm] = useState<Form>(DEFAULT_FORM);
  const [job, setJob] = useState<Job | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [run, setRun] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("backtest");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshRuns = useCallback(() => {
    crh.runs().then((r) => { setRuns(r); setOnline(true); }).catch(() => setOnline(false));
  }, []);
  useEffect(() => {
    let alive = true;
    crh.runs().then((r) => { if (alive) { setRuns(r); setOnline(true); } }).catch(() => alive && setOnline(false));
    return () => { alive = false; };
  }, []);

  const loadRun = useCallback(async (id: string) => {
    try { setRun(await crh.run(id)); setError(null); } catch (e) { setError(String(e)); }
  }, []);

  // poll the active job
  useEffect(() => {
    if (!job || ["done", "failed", "cancelled"].includes(job.status)) { if (pollRef.current) clearInterval(pollRef.current); return; }
    pollRef.current = setInterval(async () => {
      try {
        const j = await crh.job(job.job_id);
        setJob(j);
        if (j.status === "done" && j.run_id) { await loadRun(j.run_id); refreshRuns(); }
        if (j.status === "failed") setError(j.error ?? "backtest failed");
      } catch (e) { setError(String(e)); }
    }, 700);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [job, loadRun, refreshRuns]);

  const start = async (force = false) => {
    setError(null);
    try { setJob(await crh.start(formToParams(form), force)); } catch (e) { setError(String(e)); }
  };
  const stop = async () => { if (job) { try { await crh.cancel(job.job_id); } catch (e) { setError(String(e)); } } };
  const running = !!job && ["queued", "running"].includes(job.status);

  if (online === false) {
    return (
      <div className="space-y-4">
        <Header />
        <EmptyState icon={FlaskConical} title="CRH Lab API is not running"
          description={`Start it with: propaper crh-api  (serves ${CRH_API_BASE}, paper only). Nothing is shown from demo data on this page.`} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <Header />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="backtest"><Zap className="mr-1 size-3.5" />Backtest</TabsTrigger>
          <TabsTrigger value="compare"><GitCompare className="mr-1 size-3.5" />Compare</TabsTrigger>
          <TabsTrigger value="scanner"><Radar className="mr-1 size-3.5" />Signal scanner</TabsTrigger>
          <TabsTrigger value="forward"><Activity className="mr-1 size-3.5" />Forward paper</TabsTrigger>
        </TabsList>

        <TabsContent value="backtest" className="space-y-4">
          <Controls form={form} setForm={setForm} running={running} onRun={() => start(false)} onRerun={() => start(true)} onStop={stop} />
          {job && <Progress job={job} />}
          {error && <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-700 dark:text-red-300">{error}</div>}
          {run ? <RunView key={run.run_id} run={run} /> : (
            <RunsList runs={runs} onOpen={loadRun} onDelete={async (id) => { await crh.deleteRun(id); refreshRuns(); }} />
          )}
          {run && <RunsList runs={runs} onOpen={loadRun} onDelete={async (id) => { await crh.deleteRun(id); if (run.run_id === id) setRun(null); refreshRuns(); }} compact />}
        </TabsContent>
        <TabsContent value="compare"><CompareView runs={runs} /></TabsContent>
        <TabsContent value="scanner"><ScannerView runId={run?.run_id ?? null} /></TabsContent>
        <TabsContent value="forward"><ForwardView /></TabsContent>
      </Tabs>
    </div>
  );
}

function Header() {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold"><FlaskConical className="size-5" /> Crash Reversal Hunter — Trading Lab</h1>
        <p className="text-xs text-muted-foreground">Deployed CRH rules replayed on archived Bybit public data · paper only · no orders, no keys, no real money</p>
      </div>
      <div className="flex items-center gap-2"><ModeBadge mode="HISTORICAL BACKTEST" /><ModeBadge mode="FORWARD PAPER" /><ModeBadge mode="LIVE MARKET DATA" /></div>
    </div>
  );
}

// ---------- controls panel ----------
function Controls({ form, setForm, running, onRun, onRerun, onStop }: {
  form: Form; setForm: (f: Form) => void; running: boolean; onRun: () => void; onRerun: () => void; onStop: () => void;
}) {
  const set = (k: keyof Form) => (v: string) => setForm({ ...form, [k]: v });
  const capital = Number(form.capital) || 0;
  const risk = (capital * (Number(form.riskPct) || 0)) / 100;
  const baseline = form.timeframe === "1h" && form.fidelity === "exact";
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-sm">Historical backtest</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px]">{baseline ? "BASELINE rules (deployed CRH)" : "EXPERIMENT"}</Badge>
          <ModeBadge mode="HISTORICAL BACKTEST" />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Field label="Range (UTC)">
            <Select value={form.preset} onValueChange={set("preset")}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["24h", "48h", "7d", "30d", "90d"].map((p) => <SelectItem key={p} value={p}>Last {p}</SelectItem>)}
                <SelectItem value="custom">Custom dates</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {form.preset === "custom" && (<>
            <Field label="Start (UTC)"><Input type="datetime-local" className="h-8 text-xs" value={form.start} onChange={(e) => set("start")(e.target.value)} /></Field>
            <Field label="End (UTC, exclusive)"><Input type="datetime-local" className="h-8 text-xs" value={form.end} onChange={(e) => set("end")(e.target.value)} /></Field>
          </>)}
          <Field label="Universe">
            <Select value={form.universe} onValueChange={set("universe")} disabled={!!form.symbols.trim()}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="top20">Top 20 eligible (deployed)</SelectItem>
                <SelectItem value="top50">Top 50 eligible</SelectItem>
                <SelectItem value="top100">Top 100 eligible</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Or specific coins (overrides)"><Input className="h-8 text-xs" placeholder="e.g. ZEC, NEAR, ENA" value={form.symbols} onChange={(e) => set("symbols")(e.target.value)} /></Field>
          <Field label="Starting capital">
            <Select value={form.capital} onValueChange={set("capital")}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{["50", "100", "500", "1000", "5000"].map((c) => <SelectItem key={c} value={c}>${c}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Simulated leverage">
            <Select value={form.leverage} onValueChange={set("leverage")}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{["1", "5", "10", "15", "25"].map((l) => <SelectItem key={l} value={l}>{l}x isolated</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label={`Risk / trade (${fmtUsd(risk)})`}><Input className="h-8 text-xs" type="number" step="0.5" value={form.riskPct} onChange={(e) => set("riskPct")(e.target.value)} /><span className="text-[10px] text-muted-foreground">% of capital · deployed = 10%</span></Field>
          <Field label="Strategy loss trigger ($)"><Input className="h-8 text-xs" type="number" placeholder="none (deployed)" value={form.lossTrigger} onChange={(e) => set("lossTrigger")(e.target.value)} /></Field>
          <Field label="Signal timeframe">
            <Select value={form.timeframe} onValueChange={set("timeframe")}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="1h">1 hour (deployed)</SelectItem><SelectItem value="1m">1 minute (experiment)</SelectItem></SelectContent>
            </Select>
          </Field>
          <Field label="Execution data">
            <Select value={form.fidelity} onValueChange={set("fidelity")}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="exact">Exact (archived L2 quotes)</SelectItem><SelectItem value="approximate">Approximate (candles only)</SelectItem></SelectContent>
            </Select>
          </Field>
          <Field label="Label (optional)"><Input className="h-8 text-xs" value={form.label} onChange={(e) => set("label")(e.target.value)} /></Field>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onRun} disabled={running}><Play className="mr-1 size-3.5" />Run backtest</Button>
          <Button size="sm" variant="outline" onClick={onRerun} disabled={running} title="Ignore the cached result for identical settings">Re-run (no cache)</Button>
          <Button size="sm" variant="destructive" onClick={onStop} disabled={!running}><Square className="mr-1 size-3.5" />Stop</Button>
          <span className="text-[11px] text-muted-foreground">Identical settings + data version reuse the stored result instantly. The first run on a new universe/window downloads data (CoinGecko ranks are rate-limited: a top-50 universe can take several minutes once; afterwards it is cached). Rails: 3 slots, combined risk 3× per-trade, trailing drawdown = capital (deployed proportions).</span>
        </div>
      </CardContent>
    </Card>
  );
}
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1 text-[11px] text-muted-foreground"><span>{label}</span>{children}</label>;
}

function Progress({ job }: { job: Job }) {
  const pct = Math.round(job.overall * 100);
  const cls = job.status === "failed" ? "bg-red-500" : job.status === "cancelled" ? "bg-amber-500" : "bg-sky-500";
  return (
    <Card className="py-3">
      <CardContent className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">{job.status.toUpperCase()} · stage: {job.stage}{job.detail ? ` · ${job.detail}` : ""}{job.reused ? " · reused cached result" : ""}</span>
          <span className="tabular-nums">{pct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded bg-muted"><div className={cn("h-2 transition-all", cls)} style={{ width: `${pct}%` }} /></div>
        {job.error && <div className="text-xs text-red-600 dark:text-red-400">{job.error}</div>}
      </CardContent>
    </Card>
  );
}

// ---------- run view ----------
function RunView({ run }: { run: RunResult }) {
  const t = run.totals, s = run.summary;
  const traded = useMemo(() => Array.from(new Set([...run.trades.map((x) => x.symbol), ...run.open_at_end.map((x) => x.symbol)])), [run]);
  // RunView is keyed by run_id by its parent, so initial state is per run
  const [symbol, setSymbol] = useState<string | null>(traded[0] ?? null);
  const [focus, setFocus] = useState<number | null>(null);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    crh.chart(run.run_id, symbol).then((c) => alive && setChart(c)).catch(() => alive && setChart(null));
    return () => { alive = false; };
  }, [run.run_id, symbol]);
  const openTrade = (tr: Trade | { symbol: string; id: number }) => { setSymbol(tr.symbol); setFocus(tr.id); };
  const rows = useMemo(() => {
    const all = [
      ...run.trades.map((x) => ({ ...x, status: x.exit_reason === "LIQUIDATION" ? "liquidation" : x.exit_reason.startsWith("STOP") ? (x.stop_final > x.stop_initial ? "trailing-stop" : "stop-loss") : "other", open: false })),
      ...run.open_at_end.map((p) => ({ id: p.id, symbol: p.symbol, side: p.side, leverage: p.leverage, qty: p.qty, entry_price: p.entry_price, exit_price: p.mark ?? 0, stop_initial: p.initial_stop, stop_final: p.stop, margin_usd: p.margin_usd, notional_usd: p.notional_usd, entry_fee_usd: p.entry_fee_usd, exit_fee_usd: 0, funding_usd: p.funding_paid_usd, net_pnl_usd: (p.unrealized_pnl_usd ?? 0) - p.entry_fee_usd - p.funding_paid_usd, mfe_pct: null, mae_pct: null, entry_ms: p.opened_ms, exit_ms: s.window.end_ms, exit_reason: "OPEN", rationale: p.rationale, planned_risk_usd: p.planned_risk_usd, status: "open", open: true })),
    ];
    return all.filter((x) => filter === "all" || (filter === "wins" ? !x.open && x.net_pnl_usd > 0 : filter === "losses" ? !x.open && x.net_pnl_usd <= 0 : x.status === filter)).sort((a, b) => a.entry_ms - b.entry_ms);
  }, [run, filter, s.window.end_ms]);
  const rejected = run.signals.filter((x) => !x.approved);
  const costs = t.fees_usd + t.slippage_usd_est + t.funding_usd;
  return (
    <div className="space-y-4">
      {/* A. overview */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">{s.config_label} · {s.window.start} → {s.window.end_exclusive} · {s.universe} ({s.eligible_instruments} eligible) · {s.fidelity}</CardTitle>
          <div className="flex items-center gap-2">
            <a href={crh.exportJsonUrl(run.run_id)} className="text-xs underline"><Download className="mr-1 inline size-3" />JSON</a>
            <a href={crh.exportCsvUrl(run.run_id)} className="text-xs underline"><Download className="mr-1 inline size-3" />CSV</a>
            <ModeBadge mode="HISTORICAL BACKTEST" />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
            <Tile label="Final equity" value={fmtUsd(t.final_equity_usd)} cls={pnlClass(t.net_return_pct)} sub={`start ${fmtUsd(t.initial_capital_usd)} · ${s.leverage}x`} />
            <Tile label="Total return" value={fmtPct(t.net_return_pct, 2, true)} cls={pnlClass(t.net_return_pct)} sub={run.reused_from ? "cached result" : `${s.elapsed_s}s`} />
            <Tile label="Realised P&L" value={fmtUsd(t.net_realized_pnl_usd, { sign: true })} cls={pnlClass(t.net_realized_pnl_usd)} sub={`${t.completed_trades} closed`} />
            <Tile label="Unrealised P&L" value={fmtUsd(t.net_unrealized_pnl_usd, { sign: true })} cls={pnlClass(t.net_unrealized_pnl_usd)} sub={`${t.open_positions_at_end} open at end`} />
            <Tile label="Win rate / PF" value={`${t.win_rate_pct === null ? "—" : fmtPct(t.win_rate_pct, 0)} / ${pf(t.profit_factor)}`} sub={t.small_sample ? "small sample" : ""} />
            <Tile label="Max drawdown" value={fmtUsd(t.max_drawdown_usd)} sub={fmtPct(t.max_drawdown_pct, 1)} />
            <Tile label="Costs" value={fmtUsd(costs)} sub={`fees ${fmtUsd(t.fees_usd)} · slip ${fmtUsd(t.slippage_usd_est)} · fund ${fmtUsd(t.funding_usd)}`} />
          </div>
          <div className="flex flex-wrap gap-2 text-[11px]">
            <Badge variant={run.locked ? "destructive" : "outline"}>{run.locked ? `LOCKED: ${run.lock_reason}` : "no trailing-drawdown lock"}</Badge>
            <Badge variant={run.strategy_locked ? "destructive" : "outline"}>{run.strategy_locked ? "strategy loss-lock hit" : "no strategy loss-lock"}</Badge>
            <Badge variant="outline">liquidations {t.liquidations}</Badge>
            <Badge variant="outline">signals {s.candidate_signals} · approved {run.signals.filter((x) => x.approved).length} · rejected {rejected.length}</Badge>
            <Badge variant={run.checks.leakage.ok && run.checks.accounting_ok ? "outline" : "destructive"}>checks: look-ahead {run.checks.leakage.ok ? "ok" : "FAIL"} · accounting {run.checks.accounting_ok ? "ok" : "FAIL"} · stops never widened {run.checks.stops_never_widened ? "ok" : "FAIL"} · mark-liq mismatches {run.checks.mark_price_liquidation.mismatch.length}</Badge>
          </div>
          {run.warnings.length > 0 && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-[11px] text-amber-800 dark:text-amber-300">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" /><div>{run.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>
            </div>
          )}
          <MultiLineChart cursorMs={s.window.end_ms + 1} height={240}
            series={[{ name: "equity", points: run.equity_curve.map((p) => [p[0], p[1]] as [number, number]), color: seriesColor(0) }]}
            threshold={run.equity_curve.map((p) => [p[0], p[3]] as [number, number])} />
        </CardContent>
      </Card>

      {/* daily */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Daily equity / P&L (realised vs mark-to-market)</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <Table><TableHeader><TableRow>{["Day (UTC)", "Start", "End", "Change", "Realised", "Mark-to-market", "Closed", "Fees (closed)", "Funding"].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}</TableRow></TableHeader>
            <TableBody>{run.daily.map((d) => (
              <TableRow key={d.date} className="text-xs tabular-nums"><TableCell>{d.date}</TableCell><TableCell>{fmtUsd(d.start_equity)}</TableCell><TableCell>{fmtUsd(d.end_equity)}</TableCell>
                <TableCell className={pnlClass(d.change)}>{fmtUsd(d.change, { sign: true })}</TableCell><TableCell className={pnlClass(d.realised_pnl)}>{fmtUsd(d.realised_pnl, { sign: true })}</TableCell>
                <TableCell className={pnlClass(d.mark_to_market)}>{fmtUsd(d.mark_to_market, { sign: true })}</TableCell><TableCell>{d.closed_trades}</TableCell><TableCell>{fmtUsd(d.fees_closed_trades)}</TableCell><TableCell>{fmtUsd(d.funding_paid)}</TableCell></TableRow>))}
            </TableBody></Table>
        </CardContent>
      </Card>

      {/* C. chart */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">Trade chart · 1h candles · entries, stops (dashed = initial → trailed), exits, signal candles</CardTitle>
          <div className="flex items-center gap-2">
            {traded.length > 0 && (
              <Select value={symbol ?? ""} onValueChange={(v) => { setSymbol(v); setFocus(null); }}>
                <SelectTrigger className="h-8 w-[170px] text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{traded.map((x) => <SelectItem key={x} value={x}>{x.replace("/USDT:USDT", "")}</SelectItem>)}</SelectContent>
              </Select>
            )}
            <ModeBadge mode="HISTORICAL BACKTEST" />
          </div>
        </CardHeader>
        <CardContent>
          {chart ? <CrhChart data={chart} focusTradeId={focus} /> : <EmptyState icon={FlaskConical} title={traded.length ? "Loading chart…" : "No trades in this run"} description={traded.length ? undefined : "No CRH signal was approved in this window, so there is nothing to plot."} />}
        </CardContent>
      </Card>

      {/* D. trades */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">Trade history</CardTitle>
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="h-8 w-[180px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{[["all", "All"], ["wins", "Winning"], ["losses", "Losing"], ["open", "Open"], ["trailing-stop", "Trailing-stop exits"], ["stop-loss", "Stop-loss exits"], ["liquidation", "Liquidations"]].map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
          </Select>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow>{["Coin", "Side", "Entry (UTC)", "Exit (UTC)", "Entry px", "Exit px", "Qty", "Margin", "Lev", "Risk", "Gross", "Fees", "Slip (est)", "Funding", "Net", "Exit reason", "Duration"].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}</TableRow></TableHeader>
            <TableBody>
              {rows.map((x) => {
                const gross = x.net_pnl_usd + x.entry_fee_usd + x.exit_fee_usd + x.funding_usd;
                const slip = x.notional_usd * 0.0005 * (x.open ? 1 : 2);
                return (
                  <TableRow key={`${x.id}-${x.symbol}`} className={cn("cursor-pointer text-xs tabular-nums", focus === x.id && "bg-muted/60")} onClick={() => openTrade(x)}>
                    <TableCell className="font-medium">{x.symbol.replace("/USDT:USDT", "")}</TableCell><TableCell>{x.side}</TableCell>
                    <TableCell className="font-mono">{utc(x.entry_ms)}</TableCell><TableCell className="font-mono">{x.open ? "open" : utc(x.exit_ms)}</TableCell>
                    <TableCell>{fmtPrice(x.entry_price)}</TableCell><TableCell>{x.open ? `mark ${fmtPrice(x.exit_price)}` : fmtPrice(x.exit_price)}</TableCell>
                    <TableCell>{x.qty}</TableCell><TableCell>{fmtUsd(x.margin_usd)}</TableCell><TableCell>{x.leverage}x</TableCell><TableCell>{fmtUsd(x.planned_risk_usd ?? null)}</TableCell>
                    <TableCell className={pnlClass(gross)}>{fmtUsd(gross, { sign: true })}</TableCell><TableCell>{fmtUsd(x.entry_fee_usd + x.exit_fee_usd)}</TableCell><TableCell>{fmtUsd(slip)}</TableCell><TableCell>{fmtUsd(x.funding_usd)}</TableCell>
                    <TableCell className={cn("font-semibold", pnlClass(x.net_pnl_usd))}>{fmtUsd(x.net_pnl_usd, { sign: true })}{x.open && <span className="ml-1 text-[9px] text-muted-foreground">unrealised</span>}</TableCell>
                    <TableCell>{x.exit_reason}</TableCell><TableCell>{dur(x.entry_ms, x.exit_ms)}</TableCell>
                  </TableRow>);
              })}
              {rows.length === 0 && <TableRow><TableCell colSpan={17} className="text-center text-xs text-muted-foreground">no trades match</TableCell></TableRow>}
            </TableBody>
          </Table>
          {rejected.length > 0 && (
            <div className="mt-3">
              <div className="mb-1 text-[11px] font-medium tracking-wider text-muted-foreground uppercase">Rejected signals ({rejected.length})</div>
              <Table><TableBody>{rejected.slice(0, 50).map((x, i) => (
                <TableRow key={i} className="text-xs"><TableCell className="font-mono">{utc(x.ts_ms)}</TableCell><TableCell>{x.symbol.replace("/USDT:USDT", "")}</TableCell><TableCell>{x.reject_reason}</TableCell><TableCell className="text-muted-foreground">{x.details}</TableCell></TableRow>))}</TableBody></Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* audit */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Audit: data sources, fidelity, universe, risk events</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-xs">
          <div><b>Data:</b> {run.data.sources.join(" · ")} · version {run.data.version} · fidelity {run.data.fidelity}{run.data.l2_missing.length ? ` · L2 missing: ${run.data.l2_missing.join(", ")}` : ""}</div>
          <div><b>Universe:</b> {run.universe.note}. Not eligible: {Object.keys(run.universe.ineligible).length} ({Object.entries(run.universe.ineligible).slice(0, 8).map(([k, v]) => `${k}: ${v}`).join("; ")}{Object.keys(run.universe.ineligible).length > 8 ? "; …" : ""})</div>
          <div><b>Config:</b> {JSON.stringify(run.config)}</div>
          {run.risk_events.filter((e) => e.level !== "info").length > 0 && <div><b>Risk events:</b> {run.risk_events.filter((e) => e.level !== "info").map((e, i) => <div key={i} className={e.level === "error" ? "text-red-600 dark:text-red-400" : ""}>{utc(e.ts_ms)} — {e.message}</div>)}</div>}
        </CardContent>
      </Card>
    </div>
  );
}

function RunsList({ runs, onOpen, onDelete, compact }: { runs: RunRow[]; onOpen: (id: string) => void; onDelete: (id: string) => void; compact?: boolean }) {
  const done = runs.filter((r) => r.status === "done" && r.summary);
  if (done.length === 0) return compact ? null : <EmptyState icon={FlaskConical} title="No stored backtests yet" description="Configure a window and press Run backtest." />;
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">Stored runs ({done.length})</CardTitle></CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <TableHeader><TableRow>{["Created", "Label", "Window", "Universe", "Capital", "Lev", "Trades", "Return", "Max DD", "Fidelity", ""].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}</TableRow></TableHeader>
          <TableBody>{done.slice(0, compact ? 8 : 50).map((r) => { const s = r.summary!; return (
            <TableRow key={r.run_id} className="cursor-pointer text-xs tabular-nums" onClick={() => onOpen(r.run_id)}>
              <TableCell className="font-mono">{utc(r.created_ms)}</TableCell><TableCell>{s.config_label}</TableCell>
              <TableCell className="font-mono">{s.window.start.slice(0, 16)} → {s.window.end_exclusive.slice(5, 16)}</TableCell><TableCell>{s.universe}</TableCell>
              <TableCell>{fmtUsd(s.capital)}</TableCell><TableCell>{s.leverage}x</TableCell><TableCell>{s.trades}{s.open_at_end ? ` +${s.open_at_end}` : ""}</TableCell>
              <TableCell className={pnlClass(s.net_return_pct)}>{fmtPct(s.net_return_pct, 2, true)}</TableCell><TableCell>{fmtPct(s.max_drawdown_pct ?? 0, 1)}</TableCell>
              <TableCell className="max-w-[160px] truncate">{s.fidelity}</TableCell>
              <TableCell><button className="text-[11px] text-red-600 underline" onClick={(e) => { e.stopPropagation(); onDelete(r.run_id); }}>delete</button></TableCell>
            </TableRow>); })}</TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ---------- compare ----------
function CompareView({ runs }: { runs: RunRow[] }) {
  const [sel, setSel] = useState<string[]>([]);
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const done = runs.filter((r) => r.status === "done" && r.summary);
  const go = async () => { try { setCmp(await crh.compare(sel)); setErr(null); } catch (e) { setErr(String(e)); } };
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm">Select two or more completed runs</CardTitle><ModeBadge mode="HISTORICAL BACKTEST" /></CardHeader>
        <CardContent className="space-y-2">
          {done.length < 2 ? <p className="text-xs text-muted-foreground">Run at least two backtests first.</p> : done.map((r) => { const s = r.summary!; return (
            <label key={r.run_id} className="flex cursor-pointer items-center gap-2 text-xs">
              <input type="checkbox" checked={sel.includes(r.run_id)} onChange={(e) => setSel(e.target.checked ? [...sel, r.run_id] : sel.filter((x) => x !== r.run_id))} />
              <span className="font-mono">{r.run_id}</span> · {s.config_label} · {s.window.start.slice(0, 10)}→{s.window.end_exclusive.slice(0, 10)} · {s.universe} · {fmtUsd(s.capital)} {s.leverage}x · <span className={pnlClass(s.net_return_pct)}>{fmtPct(s.net_return_pct, 2, true)}</span>
            </label>); })}
          <Button size="sm" disabled={sel.length < 2} onClick={go}><GitCompare className="mr-1 size-3.5" />Compare results</Button>
          {err && <div className="text-xs text-red-600">{err}</div>}
        </CardContent>
      </Card>
      {cmp && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Side by side</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {cmp.flags.map((f, i) => <div key={i} className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-[11px] text-amber-800 dark:text-amber-300">{f}</div>)}
            <div className="rounded border border-border/60 p-2 text-xs"><b>Verdict:</b> {cmp.verdict}</div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow><TableHead className="text-[11px]">Metric</TableHead>{cmp.runs.map((r) => <TableHead key={r.run_id} className="text-[11px]">{r.label}<div className="font-mono text-[10px] text-muted-foreground">{r.run_id}</div></TableHead>)}</TableRow></TableHeader>
                <TableBody>
                  {([
                    ["Window", (r) => `${r.window.start.slice(0, 16)} → ${r.window.end_exclusive.slice(0, 16)}`],
                    ["Universe / fidelity", (r) => `${r.universe} · ${r.fidelity}`],
                    ["Capital / leverage / tf", (r) => `${fmtUsd(r.capital)} · ${r.leverage}x · ${r.signal_timeframe}`],
                    ["Net profit", (r) => <span className={pnlClass(r.net_pnl)}>{fmtUsd(r.net_pnl, { sign: true })}</span>],
                    ["Return %", (r) => <span className={pnlClass(r.net_return_pct)}>{fmtPct(r.net_return_pct, 2, true)}</span>],
                    ["Realised / unrealised", (r) => `${fmtUsd(r.realized, { sign: true })} / ${fmtUsd(r.unrealized, { sign: true })}`],
                    ["Closed trades / open", (r) => `${r.trades} / ${r.open_at_end}`],
                    ["Win rate", (r) => r.win_rate_pct === null ? "—" : fmtPct(r.win_rate_pct, 0)],
                    ["Profit factor", (r) => pf(r.profit_factor)],
                    ["Max drawdown", (r) => `${fmtUsd(r.max_drawdown_usd)} (${fmtPct(r.max_drawdown_pct, 1)})`],
                    ["Largest loss", (r) => fmtUsd(r.largest_loss)],
                    ["Liquidations", (r) => String(r.liquidations)],
                    ["Fees / funding / slippage", (r) => `${fmtUsd(r.fees)} / ${fmtUsd(r.funding)} / ${fmtUsd(r.slippage)}`],
                    ["Signals / approved", (r) => `${r.signals} / ${r.approved}`],
                    ["Return ÷ max DD", (r) => r.return_over_dd === null ? "—" : r.return_over_dd.toFixed(2)],
                    ["Symbols traded", (r) => r.symbols_traded.map((s) => s.replace("/USDT:USDT", "")).join(", ") || "—"],
                  ] as [string, (r: Compare["runs"][number]) => React.ReactNode][]).map(([name, f]) => (
                    <TableRow key={name} className="text-xs tabular-nums"><TableCell className="font-medium">{name}</TableCell>{cmp.runs.map((r) => <TableCell key={r.run_id}>{f(r)}</TableCell>)}</TableRow>))}
                </TableBody>
              </Table>
            </div>
            <div className="text-[11px] text-muted-foreground">Signals added in 2nd vs 1st: {cmp.signals_added_in_second.join(", ") || "none"} · missing: {cmp.signals_missing_in_second.join(", ") || "none"}</div>
            <MultiLineChart cursorMs={Number.MAX_SAFE_INTEGER} height={260} series={cmp.runs.map((r, i) => ({ name: r.run_id, points: r.equity_curve, color: seriesColor(i) }))} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------- scanner ----------
function ScannerView({ runId }: { runId: string | null }) {
  const [mode, setMode] = useState<"run" | "live">(runId ? "run" : "live");
  const [uni, setUni] = useState("top50");
  const [data, setData] = useState<Scanner | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const loading = data === null && err === null;
  useEffect(() => {
    let alive = true;
    crh.scanner(mode === "run" ? runId ?? undefined : undefined, uni)
      .then((d) => { if (alive) { setData(d); setErr(null); } })
      .catch((e) => { if (alive) setErr(String(e)); });
    return () => { alive = false; };
  }, [mode, runId, uni, nonce]);
  const load = () => { setData(null); setErr(null); setNonce((n) => n + 1); };
  const badge: Mode = data?.label === "LIVE MARKET DATA" ? "LIVE MARKET DATA" : "HISTORICAL BACKTEST";
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-sm">Signal scanner — drop ≤ −8% over 24 bars + hammer on the closed 1h candle</CardTitle>
        <div className="flex items-center gap-2">
          <Select value={mode} onValueChange={(v) => setMode(v as "run" | "live")}><SelectTrigger className="h-8 w-[200px] text-xs"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="run" disabled={!runId}>Current run (historical)</SelectItem><SelectItem value="live">Latest closed candle (live data)</SelectItem></SelectContent></Select>
          {mode === "live" && <Select value={uni} onValueChange={setUni}><SelectTrigger className="h-8 w-[110px] text-xs"><SelectValue /></SelectTrigger><SelectContent>{["top20", "top50", "top100"].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent></Select>}
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>Refresh</Button>
          <ModeBadge mode={badge} />
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {err && <div className="text-xs text-red-600">{err}</div>}
        {data?.note && <div className="mb-2 text-[11px] text-muted-foreground">{data.note}{data.as_of_ms ? ` · as of ${utc(data.as_of_ms)}` : ""}</div>}
        <Table>
          <TableHeader><TableRow>{(mode === "live" ? ["Coin", "24h change", "Drop ≤ −8%", "Hammer", "Status", "Candle close (UTC)", "Reason", "Data"] : ["Coin", "Signals", "Near-misses", "Worst drop", "Last signal (UTC)", "Status", "Rejections", "Data"]).map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}</TableRow></TableHeader>
          <TableBody>
            {(data?.rows ?? []).sort((a, b) => (a.status === "signal" ? -1 : b.status === "signal" ? 1 : a.status === "near-miss" ? -1 : 1)).map((r) => (
              <TableRow key={r.symbol} className={cn("text-xs tabular-nums", r.status === "signal" && "bg-emerald-500/10", r.status === "near-miss" && "bg-amber-500/10")}>
                <TableCell className="font-medium">{r.symbol.replace("/USDT:USDT", "")}</TableCell>
                {mode === "live" ? (<>
                  <TableCell className={pnlClass(r.change_24h_pct ?? 0)}>{r.change_24h_pct === null || r.change_24h_pct === undefined ? "—" : fmtPct(r.change_24h_pct, 2, true)}</TableCell>
                  <TableCell>{r.drop_condition ? "yes" : "no"}</TableCell><TableCell>{r.hammer ? "yes" : "no"}</TableCell>
                  <TableCell><Badge variant="outline" className="text-[10px]">{r.status}</Badge></TableCell><TableCell className="font-mono">{utc(r.candle_close_ts)}</TableCell>
                  <TableCell className="text-muted-foreground">{r.reason ?? r.error ?? ""}</TableCell><TableCell>{r.data ?? ""}</TableCell>
                </>) : (<>
                  <TableCell>{r.signals}</TableCell><TableCell>{r.near_misses}</TableCell>
                  <TableCell className={pnlClass(r.worst_drop_pct ?? 0)}>{r.worst_drop_pct === null || r.worst_drop_pct === undefined ? "—" : fmtPct(r.worst_drop_pct, 2, true)}</TableCell>
                  <TableCell className="font-mono">{utc(r.last_signal_ts)}</TableCell><TableCell><Badge variant="outline" className="text-[10px]">{r.status}</Badge></TableCell>
                  <TableCell className="max-w-[260px] truncate text-muted-foreground">{(r.rejections ?? []).join("; ")}</TableCell><TableCell>{r.data}</TableCell>
                </>)}
              </TableRow>))}
          </TableBody>
        </Table>
        {data?.ineligible && Object.keys(data.ineligible).length > 0 && <div className="mt-2 text-[11px] text-muted-foreground">Not eligible: {Object.entries(data.ineligible).map(([k, v]) => `${k} (${v})`).join("; ")}</div>}
      </CardContent>
    </Card>
  );
}

// ---------- forward paper ----------
function ForwardView() {
  const [d, setD] = useState<Forward | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => { try { const x = await crh.forward(); if (alive) { setD(x); setErr(null); } } catch (e) { if (alive) setErr(String(e)); } };
    tick(); const id = setInterval(tick, 15000); return () => { alive = false; clearInterval(id); };
  }, []);
  if (err) return <div className="text-xs text-red-600">{err}</div>;
  if (!d) return <div className="text-xs text-muted-foreground">Loading…</div>;
  if (!d.available) return <EmptyState icon={Activity} title="Forward-paper sleeve unavailable" description={d.reason} />;
  const s = d.sleeve!;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">Live Extreme Lab · crash_reversal sleeve (read-only view of the running paper engine)</CardTitle>
          <div className="flex items-center gap-2"><Badge variant="outline" className="text-[10px]">last scan {utc(d.last_scan_ms)}</Badge><Badge variant={d.lab_locked ? "destructive" : "outline"} className="text-[10px]">{d.lab_locked ? "LAB LOCKED" : "lab unlocked"}</Badge><Badge variant="outline" className="text-[10px]">auto-entry {d.auto_entry ? "on" : "off"}</Badge><ModeBadge mode="FORWARD PAPER" /></div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
            <Tile label="Sleeve equity" value={fmtUsd(s.equity_usd)} cls={pnlClass(s.return_pct)} sub={`allocation ${fmtUsd(s.allocation_usd)}`} />
            <Tile label="Return" value={fmtPct(s.return_pct, 2, true)} cls={pnlClass(s.return_pct)} />
            <Tile label="Realised" value={fmtUsd(s.realized_pnl_usd, { sign: true })} cls={pnlClass(s.realized_pnl_usd)} sub={`${s.trades} trades`} />
            <Tile label="Unrealised" value={fmtUsd(s.unrealized_usd, { sign: true })} cls={pnlClass(s.unrealized_usd)} sub={`${d.positions?.length ?? 0} open`} />
            <Tile label="Win rate / PF" value={`${s.win_rate_pct === null ? "—" : fmtPct(s.win_rate_pct, 0)} / ${pf(s.profit_factor)}`} />
            <Tile label="Fees / funding" value={fmtUsd(s.fees_usd)} sub={`funding ${fmtUsd(s.funding_usd)}`} />
            <Tile label="Status" value={s.locked ? "LOCKED" : "active"} sub={s.lock_reason ?? d.lab_lock_reason ?? ""} />
          </div>
          <p className="text-[11px] text-muted-foreground">This is the running paper account; it is never combined with historical backtest figures. The lab engine itself is not controlled from this page.</p>
          {(d.positions?.length ?? 0) > 0 && (
            <Table><TableHeader><TableRow>{["Coin", "Side", "Qty", "Entry", "Mark", "Stop", "Liq est", "Unrealised", "Opened (UTC)"].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>{d.positions!.map((p, i) => (
                <TableRow key={i} className="text-xs tabular-nums"><TableCell>{String(p.symbol).replace("/USDT:USDT", "")}</TableCell><TableCell>{String(p.side)}</TableCell><TableCell>{String(p.qty)}</TableCell><TableCell>{fmtPrice(p.entry_price as number)}</TableCell><TableCell>{fmtPrice(p.mark_price as number | null)}</TableCell><TableCell>{fmtPrice(p.stop as number)}</TableCell><TableCell>{fmtPrice(p.liq_price_est as number)}</TableCell><TableCell className={pnlClass(p.unrealized_pnl_usd as number)}>{fmtUsd(p.unrealized_pnl_usd as number | null, { sign: true })}</TableCell><TableCell className="font-mono">{utc(p.opened_ms as number)}</TableCell></TableRow>))}</TableBody></Table>
          )}
          {(d.trades?.length ?? 0) > 0 && (
            <Table><TableHeader><TableRow>{["Coin", "Side", "Entry (UTC)", "Exit (UTC)", "Entry", "Exit", "Net", "Reason"].map((h) => <TableHead key={h} className="text-[11px]">{h}</TableHead>)}</TableRow></TableHeader>
              <TableBody>{d.trades!.slice(0, 50).map((t, i) => (
                <TableRow key={i} className="text-xs tabular-nums"><TableCell>{String(t.symbol).replace("/USDT:USDT", "")}</TableCell><TableCell>{String(t.side)}</TableCell><TableCell className="font-mono">{utc(t.entry_ms as number)}</TableCell><TableCell className="font-mono">{utc(t.exit_ms as number)}</TableCell><TableCell>{fmtPrice(t.entry_price as number)}</TableCell><TableCell>{fmtPrice(t.exit_price as number)}</TableCell><TableCell className={pnlClass(t.net_pnl_usd as number)}>{fmtUsd(t.net_pnl_usd as number, { sign: true })}</TableCell><TableCell>{String(t.exit_reason)}</TableCell></TableRow>))}</TableBody></Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
