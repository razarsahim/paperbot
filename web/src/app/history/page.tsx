"use client";

import { Download, History as HistoryIcon } from "lucide-react";
import { cn } from "cn";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getTrades, tradesCsvUrl } from "@/lib/api";
import {
  fmtDateTime,
  fmtDuration,
  fmtNum,
  fmtPct,
  fmtPrice,
  fmtQty,
  fmtUsd,
  pnlClass,
} from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { Trade } from "@/lib/types";

export default function HistoryPage() {
  const { data, source, loading } = usePoll(() => getTrades({ limit: 200 }), 30_000);
  const [symbol, setSymbol] = useState("all");
  const [sleeve, setSleeve] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [selected, setSelected] = useState<Trade | null>(null);

  const symbols = useMemo(
    () => Array.from(new Set((data ?? []).map((t) => t.symbol))).sort(),
    [data]
  );

  const filtered = useMemo(
    () =>
      (data ?? []).filter(
        (t) =>
          (symbol === "all" || t.symbol === symbol) &&
          (sleeve === "all" || t.sleeve === sleeve) &&
          (outcome === "all" ||
            (outcome === "win" ? t.net_pnl_usd > 0 : t.net_pnl_usd <= 0))
      ),
    [data, symbol, sleeve, outcome]
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Trade history (simulated)</h1>
        <SourceBadge source={source} />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="w-44 text-xs" size="sm">
              <SelectValue placeholder="Symbol" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All symbols</SelectItem>
              {symbols.map((s) => (
                <SelectItem key={s} value={s} className="font-mono text-xs">
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sleeve} onValueChange={setSleeve}>
            <SelectTrigger className="w-28 text-xs" size="sm">
              <SelectValue placeholder="Sleeve" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sleeves</SelectItem>
              <SelectItem value="core">core</SelectItem>
              <SelectItem value="hype">hype</SelectItem>
            </SelectContent>
          </Select>
          <Select value={outcome} onValueChange={setOutcome}>
            <SelectTrigger className="w-28 text-xs" size="sm">
              <SelectValue placeholder="Outcome" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All results</SelectItem>
              <SelectItem value="win">Wins</SelectItem>
              <SelectItem value="loss">Losses</SelectItem>
            </SelectContent>
          </Select>
          <Button asChild variant="outline" size="sm">
            <a href={tradesCsvUrl} download>
              <Download className="size-3.5" /> CSV
            </a>
          </Button>
        </div>
      </div>

      <Card className="py-0">
        <CardContent className="px-0">
          {loading || !data ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-4">
              <EmptyState
                icon={HistoryIcon}
                title="No simulated trades match"
                description="Closed paper trades will be listed here with full audit detail."
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>ID</TableHead>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Exit</TableHead>
                    <TableHead className="text-right">Net P&L</TableHead>
                    <TableHead>Exit reason</TableHead>
                    <TableHead>Sleeve</TableHead>
                    <TableHead className="text-right">Closed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((t) => (
                    <TableRow
                      key={t.id}
                      className="cursor-pointer"
                      onClick={() => setSelected(t)}
                    >
                      <TableCell className="text-muted-foreground tabular-nums">#{t.id}</TableCell>
                      <TableCell className="font-mono font-medium">{t.symbol}</TableCell>
                      <TableCell>
                        <Badge
                          className={
                            t.side === "long"
                              ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                              : "bg-red-500/15 text-red-600 dark:text-red-400"
                          }
                        >
                          {t.side.toUpperCase()} {t.leverage}x
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{fmtQty(t.qty)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtPrice(t.entry_price)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtPrice(t.exit_price)}</TableCell>
                      <TableCell className={cn("text-right font-semibold tabular-nums", pnlClass(t.net_pnl_usd))}>
                        {fmtUsd(t.net_pnl_usd, { sign: true })}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{t.exit_reason}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="uppercase">{t.sleeve}</Badge>
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground tabular-nums">
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

      <TradeDetail trade={selected} onClose={() => setSelected(null)} source={source} />
    </div>
  );
}

function Field({ k, v, className }: { k: string; v: React.ReactNode; className?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-muted-foreground">{k}</span>
      <span className={cn("text-right text-xs font-medium tabular-nums", className)}>{v}</span>
    </div>
  );
}

function TradeDetail({
  trade,
  onClose,
  source,
}: {
  trade: Trade | null;
  onClose: () => void;
  source: "live" | "demo";
}) {
  return (
    <Sheet open={trade !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-hidden sm:max-w-md">
        {trade && (
          <>
            <SheetHeader className="pb-2">
              <SheetTitle className="flex items-center gap-2 font-mono text-base">
                #{trade.id} {trade.symbol}
                <SourceBadge source={source} />
              </SheetTitle>
              <SheetDescription>
                Simulated {trade.side} {trade.leverage}x · {trade.sleeve} sleeve ·{" "}
                {fmtDuration(trade.exit_ms - trade.entry_ms)} held
              </SheetDescription>
            </SheetHeader>
            <ScrollArea className="h-full px-4 pb-6">
              <div className="space-y-4 pb-10">
                <section>
                  <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">Result</h3>
                  <Field
                    k="Net P&L"
                    v={fmtUsd(trade.net_pnl_usd, { sign: true })}
                    className={cn("text-sm", pnlClass(trade.net_pnl_usd))}
                  />
                  <Field k="Exit reason" v={<Badge variant="outline">{trade.exit_reason}</Badge>} />
                  <Field k="MFE" v={trade.mfe_pct === null ? "—" : fmtPct(trade.mfe_pct, 2, true)} className="text-emerald-600 dark:text-emerald-400" />
                  <Field k="MAE" v={trade.mae_pct === null ? "—" : fmtPct(trade.mae_pct, 2, true)} className="text-red-600 dark:text-red-400" />
                </section>
                <Separator />
                <section>
                  <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">Execution</h3>
                  <Field k="Qty" v={fmtQty(trade.qty)} />
                  <Field k="Entry price" v={fmtPrice(trade.entry_price)} />
                  <Field k="Exit price" v={fmtPrice(trade.exit_price)} />
                  <Field k="Initial stop" v={fmtPrice(trade.stop_initial)} />
                  <Field k="Final stop" v={fmtPrice(trade.stop_final)} />
                  <Field k="Target" v={fmtPrice(trade.target)} />
                  <Field k="Margin" v={fmtUsd(trade.margin_usd)} />
                  <Field k="Notional" v={fmtUsd(trade.notional_usd)} />
                  <Field k="Entered" v={fmtDateTime(trade.entry_ms)} />
                  <Field k="Exited" v={fmtDateTime(trade.exit_ms)} />
                </section>
                <Separator />
                <section>
                  <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">Costs (modelled)</h3>
                  <Field k="Entry fee" v={fmtUsd(trade.entry_fee_usd)} />
                  <Field k="Exit fee" v={fmtUsd(trade.exit_fee_usd)} />
                  <Field k="Funding" v={fmtUsd(trade.funding_usd, { sign: true })} className={pnlClass(trade.funding_usd)} />
                  <Field k="Slippage model" v={<span className="font-mono">{trade.slippage_model}</span>} />
                </section>
                <Separator />
                <section>
                  <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">Rationale</h3>
                  <p className="rounded-lg border border-border/60 bg-muted/40 p-3 text-xs leading-relaxed">
                    {trade.rationale}
                  </p>
                </section>
                {trade.indicator_snapshot && (
                  <section>
                    <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                      Indicator snapshot (at signal bar close)
                    </h3>
                    {Object.entries(trade.indicator_snapshot).map(([k, v]) => (
                      <Field key={k} k={k} v={fmtNum(v, 4)} />
                    ))}
                  </section>
                )}
                <p className="text-[10px] text-muted-foreground">
                  Simulated fill with modelled costs — not a real transaction.
                </p>
              </div>
            </ScrollArea>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
