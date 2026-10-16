import { cn } from "cn";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceBadge } from "@/components/source-badge";
import type { Source } from "@/lib/types";

export function StatTile({
  label,
  value,
  sub,
  source,
  loading,
  valueClassName,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  source: Source;
  loading?: boolean;
  valueClassName?: string;
  icon?: React.ReactNode;
}) {
  return (
    <Card className="gap-1 rounded-xl border-border/60 bg-card/60 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
          {icon}
          {label}
        </span>
        <SourceBadge source={source} />
      </div>
      {loading ? (
        <Skeleton className="h-7 w-28" />
      ) : (
        <div className={cn("text-xl font-semibold tabular-nums", valueClassName)}>
          {value}
        </div>
      )}
      {sub !== undefined &&
        (loading ? (
          <Skeleton className="h-3.5 w-20" />
        ) : (
          <div className="text-xs text-muted-foreground tabular-nums">{sub}</div>
        ))}
    </Card>
  );
}
