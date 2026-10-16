"use client";

import {
  Database,
  Settings as SettingsIcon,
  ShieldCheck,
  Wifi,
  WifiOff,
} from "lucide-react";
import { cn } from "cn";
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
import { getHealth, getSettings } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

const HARD_RAILS = [
  "Max 0.5% of equity risked per simulated trade",
  "Max 3 open positions at once",
  "Max 1.5% combined planned risk across all positions",
  "2% daily loss locks new entries until the next day",
  "5% total loss pauses the strategy entirely",
  "Stops are never widened once set",
  "Never averages down into a losing position",
  "No new entries when market data is stale or suspect",
] as const;

export default function SettingsPage() {
  const settings = usePoll(getSettings, 60_000);
  const health = usePoll(getHealth, 15_000);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Settings & system health</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* Read-only settings */}
        <Card className="py-0">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <SettingsIcon className="size-4" /> Engine configuration (read-only)
            </CardTitle>
            <SourceBadge source={settings.source} />
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {settings.loading || !settings.data ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 8 }).map((_, i) => (
                  <Skeleton key={i} className="h-7 w-full" />
                ))}
              </div>
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Key</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(settings.data).map(([k, v]) => (
                    <TableRow key={k}>
                      <TableCell className="font-mono text-muted-foreground">{k}</TableCell>
                      <TableCell className="text-right font-medium tabular-nums">
                        {typeof v === "boolean" ? (
                          <Badge variant="outline" className={v ? "border-emerald-500/40 text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}>
                            {String(v)}
                          </Badge>
                        ) : (
                          String(v)
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-4">
          {/* Risk controls */}
          <Card className="border-emerald-500/30">
            <CardHeader className="flex-row items-center justify-between py-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <ShieldCheck className="size-4 text-emerald-500" /> Hard risk rails
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2 text-xs">
                {HARD_RAILS.map((r) => (
                  <li key={r} className="flex items-start gap-2">
                    <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[11px] text-muted-foreground">
                These rails are enforced in the paper engine and cannot be disabled from this
                dashboard. The dashboard is read-only.
              </p>
            </CardContent>
          </Card>

          {/* Data health */}
          <Card>
            <CardHeader className="flex-row items-center justify-between py-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Database className="size-4" /> Data health
              </CardTitle>
              <div className="flex items-center gap-2">
                {health.data && (
                  <Badge
                    variant="outline"
                    className={
                      health.data.status === "ok"
                        ? "border-emerald-500/40 text-emerald-600 dark:text-emerald-400"
                        : "border-amber-500/40 text-amber-600 dark:text-amber-400"
                    }
                  >
                    {health.data.status}
                  </Badge>
                )}
                <SourceBadge source={health.source} />
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {health.loading || !health.data ? (
                Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)
              ) : (
                health.data.data_sources.map((s) => (
                  <div
                    key={s.name}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3",
                      s.ok ? "border-border/60" : "border-amber-500/40 bg-amber-500/5"
                    )}
                  >
                    {s.ok ? (
                      <Wifi className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                    ) : (
                      <WifiOff className="mt-0.5 size-4 shrink-0 text-amber-500" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium">{s.name}</p>
                        <span className="text-[10px] text-muted-foreground tabular-nums">
                          last ok {timeAgo(s.last_ok_ms)}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">{s.detail}</p>
                    </div>
                  </div>
                ))
              )}
              <p className="text-[11px] text-muted-foreground">
                The engine defaults to no simulated trades whenever a required feed is stale,
                irregular or unavailable.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
