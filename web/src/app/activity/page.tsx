"use client";

import { Activity, Ban, Check, ScrollText } from "lucide-react";
import { cn } from "cn";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getAudit, getSignals } from "@/lib/api";
import { fmtDateTime, timeAgo } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

export default function ActivityPage() {
  const signals = usePoll(() => getSignals(50), 15_000);
  const audit = usePoll(() => getAudit(200), 15_000);
  const [level, setLevel] = useState("all");

  const filteredAudit = useMemo(
    () => (audit.data ?? []).filter((a) => level === "all" || a.level === level),
    [audit.data, level]
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Bot activity</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        {/* Signals feed */}
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Activity className="size-4" /> Signals feed
            </CardTitle>
            <SourceBadge source={signals.source} />
          </CardHeader>
          <CardContent className="space-y-2">
            {signals.loading || !signals.data ? (
              Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)
            ) : signals.data.length === 0 ? (
              <EmptyState icon={Activity} title="No signals yet" description="Approved and rejected signals from the pro scanner will stream here." />
            ) : (
              signals.data.map((s, i) => (
                <div
                  key={`${s.ts_ms}-${s.symbol}-${i}`}
                  className={cn(
                    "rounded-lg border p-3",
                    s.approved
                      ? "border-emerald-500/30 bg-emerald-500/5"
                      : "border-border/60 bg-muted/30 opacity-90"
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {s.approved ? (
                      <Badge className="bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
                        <Check className="size-3" /> approved
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-muted-foreground">
                        <Ban className="size-3" /> rejected
                      </Badge>
                    )}
                    <span className="font-mono font-medium">{s.symbol}</span>
                    <Badge
                      variant="outline"
                      className={
                        s.action === "long"
                          ? "border-emerald-500/40 text-emerald-600 dark:text-emerald-400"
                          : "border-red-500/40 text-red-600 dark:text-red-400"
                      }
                    >
                      {s.action.toUpperCase()}
                    </Badge>
                    <span className="ml-auto text-muted-foreground tabular-nums">{timeAgo(s.ts_ms)}</span>
                  </div>
                  {s.reject_reason && (
                    <p className="mt-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
                      {s.reject_reason}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">{s.details}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Audit log */}
        <Card className="py-0 xl:col-span-3">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <ScrollText className="size-4" /> Audit log
            </CardTitle>
            <div className="flex items-center gap-2">
              <Select value={level} onValueChange={setLevel}>
                <SelectTrigger className="w-28 text-xs" size="sm">
                  <SelectValue placeholder="Level" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All levels</SelectItem>
                  <SelectItem value="info">info</SelectItem>
                  <SelectItem value="warning">warning</SelectItem>
                  <SelectItem value="error">error</SelectItem>
                </SelectContent>
              </Select>
              <SourceBadge source={audit.source} />
            </div>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            {audit.loading || !audit.data ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : filteredAudit.length === 0 ? (
              <div className="p-4">
                <EmptyState icon={ScrollText} title="No audit entries" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table className="text-xs">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="w-40">Time</TableHead>
                      <TableHead className="w-24">Level</TableHead>
                      <TableHead className="w-28">Category</TableHead>
                      <TableHead>Message</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredAudit.map((a, i) => (
                      <TableRow key={`${a.ts_ms}-${i}`}>
                        <TableCell className="whitespace-nowrap text-muted-foreground tabular-nums">
                          {fmtDateTime(a.ts_ms)}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={cn(
                              a.level === "error" &&
                                "border-red-500/50 text-red-600 dark:text-red-400",
                              a.level === "warning" &&
                                "border-amber-500/50 text-amber-600 dark:text-amber-400",
                              a.level === "info" && "text-muted-foreground"
                            )}
                          >
                            {a.level}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-muted-foreground">{a.category}</TableCell>
                        <TableCell className="min-w-64">{a.message}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
