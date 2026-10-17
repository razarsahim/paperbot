#!/usr/bin/env python3
"""PaperBot Pro service controller.

Manages the project's PAPER-ONLY services as background processes: start,
graceful stop, restart, adoption of already-running instances, per-service
logs, health states and bounded crash recovery. Processes are matched by
their full command line inside this repository — NEVER by port number — so
unrelated processes can't be touched. No balances, databases or positions
are modified by this tool; it only starts/stops the existing programs.
"""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENV = REPO / ".venv" / "bin"
LOGS = REPO / "logs" / "launcher"
MAX_LOG_BYTES = 5 * 1024 * 1024


@dataclass
class ServiceDef:
    key: str
    name: str
    cmd: list[str]
    cwd: str
    match: str | list[str]          # cmdline fingerprint(s), repo-specific
    log: str
    env: dict = field(default_factory=dict)
    health_url: str | None = None   # optional HTTP health probe
    optional: bool = False          # excluded from Start All unless enabled
    # extra patterns accepted ONLY when verifying our own pidfile pid —
    # for processes that rewrite their title (e.g. next-server). External
    # adoption never uses these, so lookalike processes stay untouched.
    own_match: list[str] = field(default_factory=list)
    # Some servers (Next's `next start`) fork a DETACHED worker and the
    # launched process exits. When set, after start we find the pid listening
    # on this port, confirm its command contains an own_match fingerprint,
    # and record THAT pid — so tracking follows the real server, not the
    # wrapper. The port is used only to DISCOVER the pid, never to kill one.
    resolve_listen_port: int | None = None

    @property
    def matches(self) -> list[str]:
        return [self.match] if isinstance(self.match, str) else list(self.match)


class Controller:
    def __init__(self, services: list[ServiceDef], run_dir: str,
                 max_restarts: int = 3, restart_window_s: float = 600.0):
        self.services = {s.key: s for s in services}
        self.order = [s.key for s in services]
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.max_restarts = max_restarts
        self.restart_window_s = restart_window_s
        self.restart_counts: dict[str, int] = {k: 0 for k in self.services}
        self._restart_first_ts: dict[str, float] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._exit_codes: dict[str, int] = {}

    # ---------------- process discovery ----------------
    def _pidfile(self, svc: ServiceDef) -> Path:
        return self.run_dir / f"{svc.key}.json"

    @staticmethod
    def _proc_table() -> list[tuple[int, str]]:
        out = subprocess.run(["ps", "-axo", "pid=,command="],
                             capture_output=True, text=True).stdout
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            pid_s, _, cmd = line.partition(" ")
            try:
                rows.append((int(pid_s), cmd.strip()))
            except ValueError:
                continue
        return rows

    def _find_matching(self, svc: ServiceDef) -> list[tuple[int, str]]:
        me = os.getpid()
        return [(pid, cmd) for pid, cmd in self._proc_table()
                if pid != me and any(m in cmd for m in svc.matches)]

    def _read_pidfile(self, svc: ServiceDef) -> dict | None:
        pf = self._pidfile(svc)
        if not pf.exists():
            return None
        try:
            return json.loads(pf.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _owned_pid(self, svc: ServiceDef) -> int | None:
        """Pid from our pidfile, verified live. A process we started may have
        rewritten its title (next-server) — accept it if it is still in our
        recorded process group, or matches a cmdline fingerprint. A stale
        pidfile pointing at an unrelated or dead process is ignored."""
        rec = self._read_pidfile(svc)
        if rec is None:
            return None
        pid, pgid = rec.get("pid"), rec.get("pgid")
        accepted = svc.matches + svc.own_match
        for live_pid, cmd in self._proc_table():
            if live_pid != pid:
                continue
            if any(m in cmd for m in accepted):
                return pid
            # title-rewritten but still in the session we created
            if pgid is not None:
                try:
                    if os.getpgid(pid) == pgid:
                        return pid
                except ProcessLookupError:
                    return None
        return None

    # ---------------- lifecycle ----------------
    def _listener_owned(self, svc: ServiceDef) -> int | None:
        """Pid listening on the service's port IFF it looks like our server
        (own_match/matches). Lets us adopt a detached server that has no
        pidfile and a rewritten title — and refuse to start a duplicate."""
        if svc.resolve_listen_port is None:
            return None
        out = subprocess.run(
            ["lsof", "-tnP", f"-iTCP:{svc.resolve_listen_port}", "-sTCP:LISTEN"],
            capture_output=True, text=True).stdout.split()
        accepted = svc.matches + svc.own_match
        for pid_s in out:
            try:
                pid = int(pid_s)
            except ValueError:
                continue
            for live_pid, cmd in self._proc_table():
                if live_pid == pid and any(m in cmd for m in accepted):
                    return pid
        return None

    def start(self, key: str) -> bool:
        svc = self.services[key]
        if (self._owned_pid(svc) is not None or self._find_matching(svc)
                or self._listener_owned(svc) is not None):
            return False  # running or adopted: never start a duplicate
        log_path = Path(svc.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
            log_path.replace(log_path.with_suffix(log_path.suffix + ".1"))
        log_f = open(log_path, "a")
        log_f.write(f"\n===== launcher start {time.strftime('%F %T')} =====\n")
        log_f.flush()
        env = {**os.environ, **svc.env}
        proc = subprocess.Popen(svc.cmd, cwd=svc.cwd, env=env,
                                stdout=log_f, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True)
        self._procs[key] = proc
        self._exit_codes.pop(key, None)
        # pgid = pid because of start_new_session; used to stop the whole tree
        # (e.g. next's wrapper + server worker) without any port-based matching.
        rec = {"pid": proc.pid, "pgid": proc.pid, "cmd": svc.cmd,
               "started_at": time.time()}
        if svc.resolve_listen_port is not None:
            resolved = self._resolve_listener(svc, proc)
            if resolved is not None:
                rec["pid"], rec["pgid"] = resolved
                self._procs.pop(key, None)  # wrapper exited; track the server
        self._pidfile(svc).write_text(json.dumps(rec))
        return True

    def _resolve_listener(self, svc: ServiceDef, proc, timeout: float = 30.0):
        """Wait for the service to listen, then return (pid, pgid) of the
        listener IFF its command matches a fingerprint we own — otherwise
        None. Discovery only; nothing is killed here."""
        deadline = time.time() + timeout
        accepted = svc.matches + svc.own_match
        while time.time() < deadline:
            out = subprocess.run(
                ["lsof", "-tnP", f"-iTCP:{svc.resolve_listen_port}", "-sTCP:LISTEN"],
                capture_output=True, text=True).stdout.split()
            for pid_s in out:
                try:
                    pid = int(pid_s)
                except ValueError:
                    continue
                for live_pid, cmd in self._proc_table():
                    if live_pid == pid and any(m in cmd for m in accepted):
                        try:
                            return pid, os.getpgid(pid)
                        except ProcessLookupError:
                            return None
            if proc.poll() is not None and not out:
                # wrapper died before anything listened and nothing is up yet
                time.sleep(0.4)
            else:
                time.sleep(0.4)
        return None

    def stop(self, key: str, timeout: float = 12.0) -> bool:
        """Graceful: SIGINT (engines handle KeyboardInterrupt cleanly), then
        SIGTERM, then SIGKILL as a last resort. Only cmdline-matched pids."""
        svc = self.services[key]
        pids = set()
        owned = self._owned_pid(svc)
        rec = self._read_pidfile(svc)
        # a detached server (next) whose pidfile was lost is still ours if it
        # listens on our port with our fingerprint — adopt its pid to stop it
        listener = self._listener_owned(svc)
        if listener is not None:
            pids.add(listener)
        if owned is not None:
            pids.add(owned)
        for root in (owned, listener):
            if root is None:
                continue
            try:
                root_pgid = os.getpgid(root)
            except ProcessLookupError:
                continue
            for live_pid, _cmd in self._proc_table():
                try:
                    if os.getpgid(live_pid) == root_pgid:
                        pids.add(live_pid)
                except ProcessLookupError:
                    continue
        pids.update(pid for pid, _ in self._find_matching(svc))
        if not pids:
            self._pidfile(svc).unlink(missing_ok=True)
            return False
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            for pid in list(pids):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pids.discard(pid)
            deadline = time.time() + (timeout / 3)
            while pids and time.time() < deadline:
                time.sleep(0.1)
                for pid in list(pids):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        pids.discard(pid)
            if not pids:
                break
        handle = self._procs.pop(key, None)
        if handle is not None and handle.poll() is not None:
            pass
        self._pidfile(svc).unlink(missing_ok=True)
        self._exit_codes.pop(key, None)
        return True

    def restart(self, key: str) -> bool:
        self.stop(key)
        time.sleep(0.5)
        return self.start(key)

    # ---------------- status ----------------
    def _health(self, svc: ServiceDef) -> bool | None:
        if not svc.health_url:
            return None
        try:
            with urllib.request.urlopen(svc.health_url, timeout=3) as resp:
                return 200 <= resp.status < 400
        except Exception:
            return False

    def status(self) -> dict:
        out = {}
        for key in self.order:
            svc = self.services[key]
            handle = self._procs.get(key)
            if handle is not None and handle.poll() is not None:
                self._exit_codes[key] = handle.returncode
            owned = self._owned_pid(svc)
            matching = self._find_matching(svc)
            listener = self._listener_owned(svc)
            if owned is not None:
                state, pid, adopted = "running", owned, False
            elif matching:
                state, pid, adopted = "running", matching[0][0], True
            elif listener is not None:
                state, pid, adopted = "running", listener, True
            elif key in self._exit_codes and self._exit_codes[key] != 0:
                state, pid, adopted = "failed", None, False
            else:
                # a pidfile with no matching live process is stale — clean it
                self._pidfile(svc).unlink(missing_ok=True)
                state, pid, adopted = "stopped", None, False
            entry = {"name": svc.name, "state": state, "pid": pid,
                     "adopted": adopted, "duplicates": max(0, len(matching) - 1),
                     "exit_code": self._exit_codes.get(key)}
            if state == "running":
                healthy = self._health(svc)
                if healthy is False:
                    entry["state"] = "stale"
                entry["healthy"] = healthy
            out[key] = entry
        return out

    # ---------------- crash recovery ----------------
    def supervise(self) -> list[str]:
        """Restart services we started that died, with a bounded budget per
        window. Returns human-readable event strings."""
        events = []
        now = time.time()
        for key in self.order:
            svc = self.services[key]
            handle = self._procs.get(key)
            if handle is None:
                continue
            code = handle.poll()
            if code is None:
                continue
            self._exit_codes[key] = code
            first = self._restart_first_ts.get(key, 0)
            if now - first > self.restart_window_s:
                self.restart_counts[key] = 0
                self._restart_first_ts[key] = now
            if self.restart_counts[key] >= self.max_restarts:
                events.append(f"{svc.name}: FAILED (exit {code}); restart budget "
                              f"exhausted ({self.max_restarts}) — manual attention needed")
                continue
            self.restart_counts[key] += 1
            self._restart_first_ts.setdefault(key, now)
            self._procs.pop(key, None)
            self._pidfile(svc).unlink(missing_ok=True)
            if self.start(key):
                events.append(f"{svc.name}: crashed (exit {code}); restarted "
                              f"({self.restart_counts[key]}/{self.max_restarts})")
        return events


# ---------------- real service catalogue ----------------

def load_launcher_config() -> dict:
    cfg_path = REPO / "launcher" / "config.json"
    defaults = {"legacy_enabled": False, "lab_auto_entry": True,
                "accept_negative_validation": False}
    if cfg_path.exists():
        try:
            defaults.update(json.loads(cfg_path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def real_services() -> list[ServiceDef]:
    cfg = load_launcher_config()
    lab_env = {"PAPERBOT_LAB_AUTO_ENTRY": "1" if cfg["lab_auto_entry"] else "0"}
    return [
        ServiceDef(
            key="api", name="FastAPI backend (8777)",
            cmd=[str(VENV / "propaper"), "api"], cwd=str(REPO),
            match=[f"{VENV}/propaper api", ".venv/bin/propaper api"],
            log=str(LOGS / "api.log"),
            health_url="http://127.0.0.1:8777/api/health"),
        ServiceDef(
            key="pro", name="Main scanner engine (observe-only)",
            cmd=[str(VENV / "propaper"), "run"], cwd=str(REPO),
            match=[f"{VENV}/propaper run", ".venv/bin/propaper run"],
            log=str(LOGS / "pro-engine.log"),
            env={"PAPERBOT_PRO_AUTO_ENTRY": "0"}),   # main stays disabled
        ServiceDef(
            key="lab", name="Extreme Lab engine",
            cmd=[str(VENV / "propaper"), "lab-run"], cwd=str(REPO),
            match=[f"{VENV}/propaper lab-run", ".venv/bin/propaper lab-run"],
            log=str(LOGS / "lab-engine.log"),
            env=lab_env),
        ServiceDef(
            key="legacy", name="Legacy BTC/GBP engine",
            cmd=[str(VENV / "paperbot"), "run"], cwd=str(REPO),
            match=[f"{VENV}/paperbot run", ".venv/bin/paperbot run"],
            log=str(LOGS / "legacy-engine.log"),
            optional=not cfg["legacy_enabled"]),
        ServiceDef(
            key="web", name="Dashboard (3000, production)",
            cmd=[str(REPO / "web" / "node_modules" / ".bin" / "next"),
                 "start", "-p", "3000"],
            cwd=str(REPO / "web"),
            match=[f"{REPO}/web/node_modules/.bin/next start",
                   f"{REPO}/web/node_modules/next/dist/bin/next start",
                   f"{REPO}/web/node_modules/.bin/next dev",
                   f"{REPO}/web/.next/dev"],   # dev server adopted, not duplicated
            own_match=["next-server"],         # prod next rewrites its title
            resolve_listen_port=3000,          # next forks a detached server
            log=str(LOGS / "web.log"),
            health_url="http://127.0.0.1:3000"),
    ]


def ensure_web_build() -> bool:
    build_id = REPO / "web" / ".next" / "BUILD_ID"
    if build_id.exists():
        return True
    print("Building dashboard (first run)…")
    result = subprocess.run(["/usr/bin/env", "npm", "run", "build"],
                            cwd=str(REPO / "web"))
    return result.returncode == 0


def make_controller() -> Controller:
    return Controller(real_services(), run_dir=str(REPO / "launcher" / "run"))


STATE_GLYPH = {"running": "🟢", "stale": "🟡", "starting": "🟠",
               "failed": "🔴", "stopped": "⚪"}


def start_all(ctl: Controller, open_browser: bool = True) -> None:
    for key in ctl.order:
        svc = ctl.services[key]
        if svc.optional:
            continue
        if key == "web":
            if not ensure_web_build():
                print("Dashboard build FAILED — see terminal output")
                continue
        started = ctl.start(key)
        print(f"  {svc.name}: {'started' if started else 'already running (adopted)'}")
    if open_browser:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen("http://127.0.0.1:3000", timeout=2)
                subprocess.run(["open", "http://localhost:3000"])
                break
            except Exception:
                time.sleep(1)
        else:
            print("Dashboard did not become healthy within 60s — check logs")


def stop_all(ctl: Controller) -> None:
    for key in reversed(ctl.order):
        svc = ctl.services[key]
        stopped = ctl.stop(key)
        print(f"  {svc.name}: {'stopped' if stopped else 'was not running'}")


def print_status(ctl: Controller) -> None:
    for key, entry in ctl.status().items():
        glyph = STATE_GLYPH.get(entry["state"], "?")
        extra = []
        if entry["adopted"]:
            extra.append("adopted")
        if entry["duplicates"]:
            extra.append(f"⚠ {entry['duplicates']} DUPLICATE process(es)")
        if entry.get("exit_code") is not None:
            extra.append(f"exit {entry['exit_code']}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        pid = f" pid {entry['pid']}" if entry["pid"] else ""
        print(f"  {glyph} {entry['name']}: {entry['state']}{pid}{suffix}")


def main() -> None:
    verb = sys.argv[1] if len(sys.argv) > 1 else "status"
    ctl = make_controller()
    if verb == "start-all":
        start_all(ctl)
    elif verb == "stop-all":
        stop_all(ctl)
    elif verb == "restart-all":
        stop_all(ctl)
        time.sleep(1)
        start_all(ctl)
    elif verb == "status":
        print_status(ctl)
    elif verb in ("start", "stop", "restart") and len(sys.argv) > 2:
        getattr(ctl, verb)(sys.argv[2])
        print_status(ctl)
    elif verb == "logs":
        subprocess.run(["open", str(LOGS)])
    else:
        print("usage: paperbotctl [start-all|stop-all|restart-all|status|"
              "start <svc>|stop <svc>|restart <svc>|logs]")


if __name__ == "__main__":
    main()
