"use client";

import { useMemo, useState } from "react";
import { MacdPane, RsiPane } from "@/components/charts/indicator-panes";
import { PriceChart } from "@/components/charts/price-chart";
import { SourceBadge } from "@/components/source-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getCandles, getUniverse } from "@/lib/api";
import { fmtPrice, timeAgo } from "@/lib/format";
import { useFetchOnce, useLabLive, usePoll } from "@/lib/hooks";

const TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"] as const;

export default function ChartsPage() {
  const universe = useFetchOnce(getUniverse);
  const [symbol, setSymbol] = useState("BTC/USDT:USDT");
  const [tf, setTf] = useState<string>("1h");

  const symbols = useMemo(() => {
    const fromUniverse =
      universe.data?.assets
        .filter((a) => a.instrument)
        .map((a) => a.instrument!.symbol) ?? [];
    return fromUniverse.length > 0 ? fromUniverse : ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"];
  }, [universe.data]);

  const candles = usePoll(() => getCandles(symbol, tf, 300), 30_000, [symbol, tf]);
  const last = candles.data?.candles.at(-1);

  // Live mark from the Lab stream when this symbol has an open lab position.
  const { live, connected } = useLabLive();
  const liveMark =
    connected && live?.live_status === "LIVE"
      ? (live.positions?.find((p) => p.symbol === symbol && p.mark_price !== null)
          ?.mark_price ?? null)
      : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Chart workbench</h1>
        <SourceBadge source={candles.source} />
        {liveMark !== null ? (
          <span
            className="text-xs text-emerald-600 tabular-nums dark:text-emerald-400"
            title="Live mark price from the Lab stream for this symbol's open lab position"
          >
            last {fmtPrice(liveMark)} · live mark
          </span>
        ) : (
          last && (
            <span className="text-xs text-muted-foreground tabular-nums">
              last {fmtPrice(last[4])} · bar {timeAgo(last[0])}
            </span>
          )
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="w-52 font-mono text-xs">
            <SelectValue placeholder="Symbol" />
          </SelectTrigger>
          <SelectContent>
            {symbols.map((s) => (
              <SelectItem key={s} value={s} className="font-mono text-xs">
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Tabs value={tf} onValueChange={setTf}>
          <TabsList>
            {TIMEFRAMES.map((t) => (
              <TabsTrigger key={t} value={t} className="px-3 text-xs">
                {t}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <span className="text-[11px] text-muted-foreground">
          EMA20 / EMA50, RSI and MACD computed client-side from fetched candles.
        </span>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between py-3">
          <CardTitle className="font-mono text-sm">
            {symbol} · {tf}
          </CardTitle>
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 bg-sky-500" /> EMA20
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 bg-purple-500" /> EMA50
            </span>
            <SourceBadge source={candles.source} />
          </div>
        </CardHeader>
        <CardContent>
          {candles.loading || !candles.data ? (
            <Skeleton className="h-[420px] w-full" />
          ) : (
            <PriceChart data={candles.data} height={420} />
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">RSI (14)</CardTitle>
            <SourceBadge source={candles.source} />
          </CardHeader>
          <CardContent>
            {candles.loading || !candles.data ? (
              <Skeleton className="h-[140px] w-full" />
            ) : (
              <RsiPane data={candles.data} />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-sm">MACD (12, 26, 9)</CardTitle>
            <SourceBadge source={candles.source} />
          </CardHeader>
          <CardContent>
            {candles.loading || !candles.data ? (
              <Skeleton className="h-[140px] w-full" />
            ) : (
              <MacdPane data={candles.data} />
            )}
          </CardContent>
        </Card>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Markers show simulated entries/exits only. Price lines: stop (red), target (green), estimated
        liquidation (amber) for the simulated position, when present.
      </p>
    </div>
  );
}
