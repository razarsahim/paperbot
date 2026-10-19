"use client";

import { cn } from "cn";
import {
  Activity,
  BarChart3,
  ChartCandlestick,
  CircleDot,
  Flame,
  FlaskConical,
  History,
  LayoutDashboard,
  LineChart,
  Menu,
  Radar,
  Settings,
  Rewind,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { ThemeToggle } from "@/components/theme-toggle";
import { getHealth } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/scanner", label: "Scanner", icon: Radar },
  { href: "/charts", label: "Charts", icon: ChartCandlestick },
  { href: "/positions", label: "Positions", icon: Wallet },
  { href: "/history", label: "History", icon: History },
  { href: "/analytics", label: "Analytics", icon: LineChart },
  { href: "/hype", label: "Hype Radar", icon: Flame },
  { href: "/lab", label: "Extreme Lab", icon: FlaskConical },
  { href: "/strategies", label: "Strategy Analytics", icon: BarChart3 },
  { href: "/replay", label: "Historical Replay", icon: Rewind },
  { href: "/crh", label: "CRH Lab", icon: FlaskConical },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-0.5 px-2">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              active
                ? "bg-accent font-medium text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
            )}
          >
            <Icon className="size-4 shrink-0" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Radar className="size-4" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold">PaperBot Pro</p>
          <p className="text-[10px] font-medium tracking-wider text-amber-600 uppercase dark:text-amber-400">
            Paper simulator
          </p>
        </div>
      </div>
      <NavLinks onNavigate={onNavigate} />
      <div className="mt-auto px-4 py-4">
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] leading-snug text-amber-700 dark:text-amber-300">
          <ShieldAlert className="mb-1 size-3.5" />
          No real money. No exchange keys. Research and paper trading only.
        </div>
      </div>
    </div>
  );
}

function HealthPill() {
  const { data, source, loading } = usePoll(getHealth, 15_000);
  if (loading) {
    return (
      <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:inline-flex">
        <CircleDot className="size-3 animate-pulse" /> checking…
      </span>
    );
  }
  if (!data || source === "demo") {
    return (
      <span
        className="hidden items-center gap-1.5 text-xs text-red-600 sm:inline-flex dark:text-red-400"
        title="Backend at 127.0.0.1:8777 unreachable — pages fall back to demo data"
      >
        <CircleDot className="size-3" /> backend offline
      </span>
    );
  }
  const ok = data.status === "ok";
  const feedsDown = data.data_sources.filter((s) => !s.ok).length;
  return (
    <span
      className={cn(
        "hidden items-center gap-1.5 text-xs sm:inline-flex",
        ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"
      )}
      title={`pro scan ${timeAgo(data.engines.pro.last_scan_ms)} · legacy tick ${timeAgo(
        data.engines.legacy.last_tick_ms
      )}${feedsDown ? ` · ${feedsDown} feed(s) degraded` : ""}`}
    >
      <CircleDot className="size-3" />
      {ok ? "healthy" : "degraded"}
    </span>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-dvh w-full">
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 border-r border-border/60 bg-card/30 md:block">
        <SidebarBody />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-border/60 bg-background/80 px-4 backdrop-blur">
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SidebarBody onNavigate={() => setOpen(false)} />
            </SheetContent>
          </Sheet>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/60 bg-amber-500/15 px-2.5 py-1 text-[11px] font-bold tracking-wider text-amber-600 uppercase dark:text-amber-400">
            <ShieldAlert className="size-3.5" />
            Paper trading — simulated funds only
          </span>
          <div className="ml-auto flex items-center gap-3">
            <HealthPill />
            <ThemeToggle />
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-5 md:px-6">{children}</main>
        <footer className="border-t border-border/60 px-6 py-3 text-[11px] text-muted-foreground">
          PaperBot Pro is a research simulator. All balances, fills and P&L are virtual.
          Simulated results never predict future performance.
        </footer>
      </div>
    </div>
  );
}
