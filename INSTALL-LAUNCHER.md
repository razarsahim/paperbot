# PaperBot Pro.app — one-click launcher

A menu-bar app (📈) that starts, stops and supervises every PaperBot
service in the background — no Terminal windows. All trading stays PAPER
ONLY; the launcher never modifies balances, databases or positions.

## One-time setup (two steps)

1. **Grant folder access** (macOS protects ~/Downloads, where the project
   lives): System Settings → Privacy & Security → **Full Disk Access** →
   "+" → select `/Users/raza/Downloads/crypto-paper-bot/PaperBot Pro.app`
   → toggle it ON. (Alternative: if macOS shows an access prompt on first
   launch, just click Allow.)
2. **Add to Dock**: drag `PaperBot Pro.app` from the project folder onto
   the Dock (optionally ⌘-drag the app into /Applications first — the
   bundle uses absolute paths, so both locations work).

## Using it

Click the 📈 menu-bar icon:

- **Status rows** — 🟢 running · 🟡 stale · 🟠 starting · 🔴 failed ·
  ⚪ stopped, plus "adopted" for services you started yourself in a
  terminal and loud "⚠ duplicate!" warnings.
- **▶ Start All** — API → main scanner (observe-only) → Extreme Lab →
  dashboard (production `next start`, built automatically on first run),
  then opens http://localhost:3000 once healthy.
- **■ Stop All** — graceful (SIGINT → SIGTERM → last-resort KILL), in
  reverse order; only processes whose full command line belongs to this
  project are ever touched — never anything matched by port.
- **↻ Restart All**, **Open Dashboard**, **View Logs** (per-service files
  in `logs/launcher/`), **System Status**.
- **Start Legacy BTC/GBP engine** — optional, on demand.
- **Start at Login…** — OPT-IN only; asks before writing the launchd
  agent, and can disable it again. Never enabled silently.
- **Quit Launcher** — quits the menu-bar app only; services keep running
  and are re-adopted next launch.

Crash recovery: services the launcher started are auto-restarted on
unexpected exit, at most 3 times per 10 minutes, with a notification; after
that they're marked 🔴 failed for manual attention.

## Safety guarantees

- Main portfolio auto-entry stays DISABLED (launcher forces the flag off).
- Extreme Lab keeps its own paper-only auto-entry setting
  (`launcher/config.json` → `lab_auto_entry`, default true), its $250
  balance, five $50 sleeves, simulated 10x isolated margin and the $50
  trailing-drawdown lockout — all enforced by the engines, not the UI.
- Duplicate engines are impossible to start from the launcher (command-line
  matching + the engines' own file locks).

## CLI equivalent

```bash
.venv/bin/python launcher/paperbotctl.py status|start-all|stop-all|restart-all|logs
```

## Troubleshooting

- 🔴 with "exit N": open View Logs → that service's file.
- "⚠ duplicate!": you have an extra copy running in some terminal — close
  it there (Ctrl+C); the launcher will keep the survivor adopted.
- App does nothing from the Dock: the Full Disk Access grant above is
  missing.
