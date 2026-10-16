"""Local alerting for SIMULATED trading events and system failures.

Channels: an append-only JSONL audit log (always), an optional user-supplied
webhook (PAPERBOT_WEBHOOK_URL), and optional macOS desktop notifications
(PAPERBOT_DESKTOP_NOTIFY=1). Alert delivery failures are printed to stderr
and never interrupt the engine. This module holds no exchange credentials
and cannot place orders.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


class Notifier:
    def __init__(self, alerts_path: str, webhook_url: str | None = None,
                 desktop: bool = False, throttle_seconds: int = 900,
                 clock=time.time):
        self.path = Path(alerts_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.webhook_url = webhook_url
        self.desktop = desktop
        self.throttle_seconds = throttle_seconds
        self.clock = clock
        self._last_sent: dict[str, float] = {}

    @classmethod
    def from_env(cls, state_dir: str) -> "Notifier":
        return cls(str(Path(state_dir) / "alerts.jsonl"),
                   webhook_url=os.getenv("PAPERBOT_WEBHOOK_URL") or None,
                   desktop=os.getenv("PAPERBOT_DESKTOP_NOTIFY") == "1")

    def send(self, level: str, title: str, body: str, key: str | None = None) -> bool:
        """Returns False when a duplicate key is throttled, True when delivered."""
        now = float(self.clock())
        if key is not None:
            last = self._last_sent.get(key)
            if last is not None and now - last < self.throttle_seconds:
                return False
            self._last_sent[key] = now
        entry = {"ts": now, "level": level, "title": title, "body": body}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        text = f"[PAPER ONLY][{level.upper()}] {title}: {body}"
        if self.webhook_url:
            try:
                payload = json.dumps({"text": text, "content": text, **entry}).encode()
                request = Request(self.webhook_url, data=payload,
                                  headers={"Content-Type": "application/json"})
                urlopen(request, timeout=10).read()
            except Exception as exc:  # alerting must never break the engine
                print(f"ALERT webhook delivery failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
        if self.desktop and sys.platform == "darwin":
            try:
                script = f'display notification {json.dumps(body)} with title {json.dumps(title)}'
                subprocess.run(["osascript", "-e", script], timeout=10,
                               capture_output=True, check=False)
            except Exception as exc:
                print(f"ALERT desktop notification failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
        return True


def dispatch_events(notifier: Notifier, events: list[str]) -> None:
    """Forward noteworthy engine events; HOLD/NO SIGNAL chatter stays local."""
    for event in events:
        if "SIMULATED BUY" in event:
            notifier.send("info", "SIMULATED BUY", event)
        elif "SIMULATED EXIT" in event:
            notifier.send("info", "SIMULATED EXIT", event)
        elif "LOCK" in event:
            notifier.send("warning", "DRAWDOWN LOCK", event, key=event.split(":")[0])
        elif "WIDE SPREAD" in event:
            notifier.send("warning", "WIDE SPREAD", event, key="wide-spread")


class FailureTracker:
    """Alert once when consecutive failures reach a threshold, once on recovery."""
    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.streak = 0
        self.alerted = False

    def record_failure(self, detail: str) -> bool:
        self.streak += 1
        if self.streak >= self.threshold and not self.alerted:
            self.alerted = True
            return True
        return False

    def record_success(self) -> bool:
        recovered = self.alerted
        self.streak = 0
        self.alerted = False
        return recovered
