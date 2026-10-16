"use client";

import { Check, Copy, Eye, Flame, TriangleAlert } from "lucide-react";
import { cn } from "cn";
import { useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { SourceBadge } from "@/components/source-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getHype } from "@/lib/api";
import { fmtCompactUsd, fmtNum, fmtUsd, timeAgo } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { HypeToken } from "@/lib/types";

function StatusBadge({ status }: { status: HypeToken["status"] }) {
  if (status === "REJECTED")
    return <Badge className="bg-red-500/15 font-bold text-red-600 dark:text-red-400">REJECTED</Badge>;
  if (status === "WATCH_ONLY")
    return (
      <Badge className="bg-amber-500/15 font-bold text-amber-600 dark:text-amber-400">
        <Eye className="size-3" /> WATCH ONLY
      </Badge>
    );
  return (
    <Badge variant="outline" className="border-emerald-500/50 font-bold text-emerald-600 dark:text-emerald-400">
      ELIGIBLE
    </Badge>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-6"
      aria-label="Copy contract address"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // clipboard unavailable — ignore
        }
      }}
    >
      {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
    </Button>
  );
}

export default function HypePage() {
  const { data, source, loading } = usePoll(getHype, 30_000);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">Hype Radar</h1>
        <SourceBadge source={source} />
      </div>

      {/* Sleeve card */}
      <Card className="border-amber-500/40">
        <CardHeader className="flex-row items-center justify-between py-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Flame className="size-4 text-amber-500" /> Hype sleeve (virtual)
          </CardTitle>
          <SourceBadge source={source} />
        </CardHeader>
        <CardContent>
          {loading || !data ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <>
              {data.sleeve.watch_only && (
                <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm font-medium text-amber-700 dark:text-amber-300">
                  <Eye className="size-4 shrink-0" />
                  WATCH-ONLY MODE — the hype sleeve observes and scores tokens; it never opens
                  simulated positions in them.
                </div>
              )}
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="rounded-lg border border-border/60 p-3">
                  <p className="text-[10px] tracking-wider text-muted-foreground uppercase">Balance</p>
                  <p className="font-semibold tabular-nums">{fmtUsd(data.sleeve.balance_usd)}</p>
                </div>
                <div className="rounded-lg border border-border/60 p-3">
                  <p className="text-[10px] tracking-wider text-muted-foreground uppercase">Spent</p>
                  <p className="font-semibold tabular-nums">{fmtUsd(data.sleeve.spent_usd)}</p>
                </div>
                <div className="rounded-lg border border-border/60 p-3">
                  <p className="text-[10px] tracking-wider text-muted-foreground uppercase">Loss cap</p>
                  <p className="font-semibold tabular-nums">{fmtUsd(data.sleeve.loss_cap_usd)}</p>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Token cards */}
      {loading || !data ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full rounded-xl" />
          ))}
        </div>
      ) : data.tokens.length === 0 ? (
        <EmptyState
          icon={Flame}
          title="No tokens in the current scan window"
          description="Tokens that trip the hype heuristics will appear here with their risk flags and evidence."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {data.tokens.map((t) => (
            <Card
              key={`${t.chain}-${t.symbol}`}
              className={cn(t.status === "REJECTED" && "border-red-500/40")}
            >
              <CardHeader className="flex-row items-start justify-between py-3">
                <div>
                  <CardTitle className="text-sm">
                    {t.symbol}{" "}
                    <span className="font-normal text-muted-foreground">{t.name}</span>
                  </CardTitle>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {t.chain} · scanned {timeAgo(t.ts_ms)}
                  </p>
                </div>
                <StatusBadge status={t.status} />
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "flex size-12 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold tabular-nums",
                      t.score >= 60
                        ? "border-amber-500/60 text-amber-600 dark:text-amber-400"
                        : "border-red-500/60 text-red-600 dark:text-red-400"
                    )}
                  >
                    {t.score}
                  </div>
                  <div className="grid flex-1 grid-cols-3 gap-1 text-[11px] text-muted-foreground">
                    <span>
                      pool
                      <br />
                      <span className="font-medium text-foreground tabular-nums">
                        {t.pool_age_hours === null ? "—" : `${fmtNum(t.pool_age_hours, 0)}h`}
                      </span>
                    </span>
                    <span>
                      liq
                      <br />
                      <span className="font-medium text-foreground tabular-nums">{fmtCompactUsd(t.liquidity_usd)}</span>
                    </span>
                    <span>
                      24h vol
                      <br />
                      <span className="font-medium text-foreground tabular-nums">{fmtCompactUsd(t.volume_24h_usd)}</span>
                    </span>
                  </div>
                </div>

                {t.flags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {t.flags.map((f) => (
                      <Badge key={f} className="bg-red-500/15 font-mono text-[10px] text-red-600 dark:text-red-400">
                        <TriangleAlert className="size-2.5" /> {f}
                      </Badge>
                    ))}
                  </div>
                )}

                {t.contract && (
                  <div className="flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-1">
                    <code className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground">
                      {t.contract}
                    </code>
                    <CopyButton text={t.contract} />
                  </div>
                )}

                <ul className="space-y-1">
                  {t.evidence.map((e, i) => (
                    <li key={i} className="flex gap-2">
                      <Badge variant="outline" className="h-4 shrink-0 px-1.5 font-mono text-[9px]">
                        {e.source}
                      </Badge>
                      <span className="text-muted-foreground">{e.note}</span>
                    </li>
                  ))}
                </ul>

                <p className="rounded-md border border-border/60 bg-muted/30 p-2 leading-relaxed text-muted-foreground">
                  {t.explanation}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <p className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-center text-xs font-medium text-amber-700 dark:text-amber-300">
        Hype signals are not evidence of future growth.
      </p>
    </div>
  );
}
