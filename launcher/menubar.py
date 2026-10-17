#!/usr/bin/env python3
"""PaperBot Pro — macOS menu-bar launcher (rumps).

Controls the PAPER-ONLY services via launcher.paperbotctl: start/stop/
restart, per-service status glyphs, log access, dashboard opening, bounded
crash recovery with notifications, and OPT-IN Start-at-Login (asks first).
"""
from __future__ import annotations
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rumps  # noqa: E402

from launcher.paperbotctl import (LOGS, REPO, STATE_GLYPH, ensure_web_build,
                                  make_controller)  # noqa: E402

LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.paperbot.pro.launcher.plist"
APP_PATH = REPO / "PaperBot Pro.app"


class PaperBotApp(rumps.App):
    def __init__(self):
        super().__init__("PaperBot", title="📈", quit_button=None)
        self.ctl = make_controller()
        self.busy = False
        self.status_items = {}
        for key in self.ctl.order:
            item = rumps.MenuItem(f"… {self.ctl.services[key].name}")
            item.set_callback(None)
            self.status_items[key] = item
        self.menu = [
            *self.status_items.values(),
            None,
            rumps.MenuItem("▶ Start All", callback=self.start_all),
            rumps.MenuItem("■ Stop All", callback=self.stop_all),
            rumps.MenuItem("↻ Restart All", callback=self.restart_all),
            None,
            rumps.MenuItem("Open Dashboard", callback=self.open_dashboard),
            rumps.MenuItem("View Logs", callback=self.view_logs),
            rumps.MenuItem("System Status", callback=self.system_status),
            None,
            rumps.MenuItem("Start Legacy BTC/GBP engine", callback=self.start_legacy),
            rumps.MenuItem("Start at Login…", callback=self.toggle_login),
            None,
            rumps.MenuItem("Quit Launcher (services keep running)",
                           callback=self.quit_launcher),
        ]
        self.timer = rumps.Timer(self.tick, 5)
        self.timer.start()
        print("menu ready", flush=True)

    # ---------------- periodic ----------------
    def tick(self, _timer=None):
        try:
            status = self.ctl.status()
        except Exception as exc:
            self.title = "📈⚠"
            print(f"status error: {exc}", flush=True)
            return
        states = []
        for key, entry in status.items():
            glyph = STATE_GLYPH.get(entry["state"], "?")
            text = f"{glyph} {entry['name']}"
            if entry["adopted"]:
                text += " · adopted"
            if entry["duplicates"]:
                text += f" · ⚠ {entry['duplicates']} duplicate!"
            if entry.get("exit_code") is not None and entry["state"] == "failed":
                text += f" · exit {entry['exit_code']}"
            self.status_items[key].title = text
            if not self.ctl.services[key].optional:
                states.append(entry["state"])
        if any(s == "failed" for s in states):
            self.title = "📈🔴"
        elif any(s == "stale" for s in states):
            self.title = "📈🟡"
        elif all(s == "running" for s in states) and states:
            self.title = "📈🟢"
        else:
            self.title = "📈"
        for event in self.ctl.supervise():
            rumps.notification("PaperBot Pro", "Service recovery", event)
            print(event, flush=True)

    # ---------------- actions ----------------
    def _run_async(self, label, fn):
        if self.busy:
            rumps.notification("PaperBot Pro", label, "Another operation is in progress")
            return
        self.busy = True

        def worker():
            try:
                fn()
                rumps.notification("PaperBot Pro", label, "Done")
            except Exception as exc:
                rumps.notification("PaperBot Pro", f"{label} FAILED", str(exc))
                print(f"{label} failed: {exc}", flush=True)
            finally:
                self.busy = False
        threading.Thread(target=worker, daemon=True).start()

    def start_all(self, _):
        def go():
            if not ensure_web_build():
                raise RuntimeError("dashboard build failed — see logs")
            for key in self.ctl.order:
                if self.ctl.services[key].optional:
                    continue
                self.ctl.start(key)
            deadline = time.time() + 60
            import urllib.request
            while time.time() < deadline:
                try:
                    urllib.request.urlopen("http://127.0.0.1:3000", timeout=2)
                    subprocess.run(["open", "http://localhost:3000"])
                    return
                except Exception:
                    time.sleep(1)
            raise RuntimeError("dashboard not healthy after 60s — check logs")
        self._run_async("Start All", go)

    def stop_all(self, _):
        def go():
            for key in reversed(self.ctl.order):
                self.ctl.stop(key)
        self._run_async("Stop All", go)

    def restart_all(self, _):
        def go():
            for key in reversed(self.ctl.order):
                self.ctl.stop(key)
            time.sleep(1)
            for key in self.ctl.order:
                if not self.ctl.services[key].optional:
                    self.ctl.start(key)
        self._run_async("Restart All", go)

    def start_legacy(self, _):
        self._run_async("Legacy engine", lambda: self.ctl.start("legacy"))

    def open_dashboard(self, _):
        subprocess.run(["open", "http://localhost:3000"])

    def view_logs(self, _):
        LOGS.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(LOGS)])

    def system_status(self, _):
        lines = []
        for entry in self.ctl.status().values():
            glyph = STATE_GLYPH.get(entry["state"], "?")
            extra = " (adopted)" if entry["adopted"] else ""
            dup = f"  ⚠ {entry['duplicates']} duplicate(s)!" if entry["duplicates"] else ""
            lines.append(f"{glyph} {entry['name']}: {entry['state']}{extra}{dup}")
        lines.append("")
        lines.append("All trading is PAPER ONLY — virtual funds, public data.")
        rumps.alert("PaperBot Pro — System Status", "\n".join(lines))

    # ---------------- start at login (opt-in) ----------------
    def toggle_login(self, _):
        if LAUNCH_AGENT.exists():
            if rumps.alert("Start at Login", "Start at Login is ENABLED. Disable it?",
                           ok="Disable", cancel="Keep") == 1:
                subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT)],
                               capture_output=True)
                LAUNCH_AGENT.unlink(missing_ok=True)
                rumps.notification("PaperBot Pro", "Start at Login", "Disabled")
            return
        if rumps.alert("Start at Login",
                       "Launch PaperBot Pro automatically when you log in?\n"
                       "(The launcher only; services still start on your command.)",
                       ok="Enable", cancel="Not now") != 1:
            return
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT.write_text(f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\"
 \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>com.paperbot.pro.launcher</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/open</string><string>-a</string>
         <string>{APP_PATH}</string></array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""")
        subprocess.run(["launchctl", "load", str(LAUNCH_AGENT)], capture_output=True)
        rumps.notification("PaperBot Pro", "Start at Login", "Enabled")

    def quit_launcher(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    PaperBotApp().run()
