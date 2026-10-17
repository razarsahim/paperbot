"""Research Lab risk governor.

Two independent protection layers, both equity-based (net mark-to-market):
- Per-strategy: a $30 equity floor (= $20 cumulative loss from the $50 start)
  warns at $40 and, when breached, triggers that strategy's simulated exits
  and locks it. No cross-strategy borrowing.
- Lab-level: a $50 trailing drawdown vs a persistent high-water mark; a breach
  locks ALL strategies, emergency-exits and requires a manual reset.
A strategy or lab lock always beats a trading signal. Shared cash,
concurrency and correlated-exposure checks are evaluated together.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from .config import ResearchSettings
from .store import ResearchStore


@dataclass(frozen=True)
class Verdict:
    approved: bool
    reason: str


class ResearchGovernor:
    def __init__(self, store: ResearchStore, cfg: ResearchSettings):
        self.db = store
        self.cfg = cfg

    # ---------------- lab trailing high-water mark ----------------
    def update_hwm(self, net_equity: float, now_ms: int,
                   require_confirmation: bool = False) -> dict:
        """See LabGovernor.update_hwm. require_confirmation debounces the lock
        to two consecutive breached readings on the high-frequency live path,
        so a single post-gap/transient catch-up tick never irreversibly locks;
        the validated REST cycle locks immediately."""
        with self.db.conn:
            row = self.db.conn.execute(
                "SELECT value FROM kv WHERE key='peak_equity'").fetchone()
            prev = json.loads(row[0]) if row else self.cfg.starting_capital_usd
            peak = max(float(prev), net_equity)
            threshold = peak - self.cfg.trailing_drawdown_usd
            breached = net_equity <= threshold
            self.db.conn.execute(
                "INSERT INTO kv(key,value) VALUES('peak_equity',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(peak),))
            locked = json.loads((self.db.conn.execute(
                "SELECT value FROM kv WHERE key='lab_locked'").fetchone() or ["false"])[0])
            streak_row = self.db.conn.execute(
                "SELECT value FROM kv WHERE key='breach_streak'").fetchone()
            streak = (json.loads(streak_row[0]) if streak_row else 0) + 1 if breached else 0
            self.db.conn.execute(
                "INSERT INTO kv(key,value) VALUES('breach_streak',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(streak),))
            if breached and not locked and (not require_confirmation or streak >= 2):
                reason = (f"LAB TRAILING DRAWDOWN BREACH: equity {net_equity:.2f} <= "
                          f"threshold {threshold:.2f} (peak {peak:.2f} - "
                          f"{self.cfg.trailing_drawdown_usd:.0f})")
                for k, v in (("lab_locked", True), ("lab_lock_reason", reason),
                             ("lab_locked_at_ms", now_ms)):
                    self.db.conn.execute(
                        "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, json.dumps(v)))
                self.db.conn.execute(
                    "INSERT INTO audit_log(ts_ms,level,category,message) VALUES(?,?,?,?)",
                    (now_ms, "error", "risk", reason + " — all strategies locked; "
                     "emergency exits will be attempted; manual reset required"))
        return {"peak_equity": peak, "threshold": threshold, "breached": breached,
                "locked": bool(self.db.get("lab_locked")),
                "excess_loss_usd": max(0.0, threshold - net_equity)}

    def reset(self, current_equity: float, note: str) -> None:
        if not self.db.get("lab_locked"):
            raise ValueError("Lab is not locked; nothing to reset")
        if not note or not note.strip():
            raise ValueError("A manual-review note is required to reset")
        with self.db.conn:
            for k, v in (("lab_locked", False), ("lab_lock_reason", None),
                         ("peak_equity", current_equity)):
                self.db.conn.execute(
                    "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, json.dumps(v)))
            self.db.conn.execute(
                "INSERT INTO audit_log(ts_ms,level,category,message) VALUES("
                "CAST(strftime('%s','now') AS INTEGER)*1000,'warning','risk',?)",
                (f"MANUAL RESET after review: '{note}'. Peak re-anchored at {current_equity:.2f}",))

    # ---------------- per-strategy equity floor ----------------
    def strategy_equity_breaches(self, strategy_equity: dict[str, float]) -> list[str]:
        """Strategies whose net equity is at/below the $30 floor. Caller
        exits + locks them (atomic in the engine)."""
        return [k for k, eq in strategy_equity.items()
                if eq <= self.cfg.strategy_lock_floor_usd]

    def lock_strategy(self, key: str, reason: str, now_ms: int) -> None:
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE strategies SET locked=1, lock_reason=? WHERE key=?", (reason, key))
            self.db.conn.execute(
                "INSERT INTO audit_log(ts_ms,level,category,message) VALUES(?,?,?,?)",
                (now_ms, "error", "risk", f"[{key}] STRATEGY LOCKED: {reason}"))

    # ---------------- entry verdicts ----------------
    def approve(self, planned: dict, now_ms: int, log: bool = False,
                action: str = "long") -> Verdict:
        verdict = self._evaluate(planned)
        if log:
            self.db.log_signal(now_ms, planned["strategy"], planned["symbol"], action,
                               verdict.approved,
                               None if verdict.approved else verdict.reason,
                               f"risk ${planned['planned_risk_usd']:.2f}, "
                               f"margin ${planned['margin_usd']:.2f}")
        return verdict

    def _evaluate(self, planned: dict) -> Verdict:
        if self.db.get("lab_locked"):
            return Verdict(False, "Lab locked (trailing drawdown): manual reset required")
        if self.db.get("research_manual_pause"):
            return Verdict(False, "Research Lab manually paused")
        if planned["planned_risk_usd"] > self.cfg.max_risk_per_trade_usd + 1e-9:
            return Verdict(False, f"planned risk ${planned['planned_risk_usd']:.2f} "
                                  f"exceeds the $2 per-trade cap")
        status = self.db.strategy_status(planned["strategy"])
        if status["level"] == "locked":
            return Verdict(False, f"{planned['strategy']} is locked "
                                  f"(equity floor / $20 cumulative loss)")
        if status["level"] == "unknown":
            return Verdict(False, f"unknown strategy '{planned['strategy']}'")
        positions = self.db.open_positions()
        if any(p["symbol"] == planned["symbol"] for p in positions):
            return Verdict(False, f"{planned['symbol']} already open: no duplicates/averaging")
        if len(positions) >= self.cfg.max_open_positions:
            return Verdict(False, f"shared position limit reached ({self.cfg.max_open_positions})")
        cluster = planned.get("corr_cluster", "")
        if cluster and any(p["corr_cluster"] == cluster for p in positions):
            return Verdict(False, f"correlated exposure: a {cluster}-cluster position is "
                                  "already open (shared risk limit)")
        ledger = self.db.strategy_ledger().get(planned["strategy"])
        needed = planned["margin_usd"] + planned["entry_fee_usd"]
        if needed > ledger["cash_usd"] + 1e-9:
            return Verdict(False, f"insufficient {planned['strategy']} cash: need "
                                  f"${needed:.2f}, have ${ledger['cash_usd']:.2f} "
                                  "(no cross-strategy borrowing)")
        return Verdict(True, "")
