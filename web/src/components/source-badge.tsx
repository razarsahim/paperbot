import { cn } from "cn";
import type { Source } from "@/lib/types";

/**
 * Honesty badge: every data-bearing section renders one of these.
 * DEMO  = backend unreachable, typed mock data shown (amber).
 * LIVE SIM = real local paper-engine data (green outline) — still simulated money.
 */
export function SourceBadge({ source, className }: { source: Source; className?: string }) {
  if (source === "demo") {
    return (
      <span
        className={cn(
          "inline-flex h-5 shrink-0 items-center rounded-full border border-amber-500/50 bg-amber-500/15 px-2 text-[10px] font-semibold tracking-wider text-amber-600 dark:text-amber-400",
          className
        )}
        title="Backend unreachable — showing built-in demo data, not real simulator output"
      >
        DEMO
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-full border border-emerald-500/50 bg-transparent px-2 text-[10px] font-semibold tracking-wider text-emerald-600 dark:text-emerald-400",
        className
      )}
      title="Live data from the local paper-trading engine (simulated funds)"
    >
      LIVE SIM
    </span>
  );
}
