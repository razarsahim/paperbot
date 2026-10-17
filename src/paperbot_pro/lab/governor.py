"""Extreme Lab risk governor: $5/$15/3-slot rails, per-strategy sleeves and
the $50 trailing portfolio drawdown against a persistent high-water mark.

The high-water mark is monotonic BY CONSTRUCTION (max with the persisted
value), so the stop-trading threshold never decreases — across reversals,
restarts and outages. A breach locks all five strategies atomically; only
an explicit manual reset (which re-anchors the peak after human review)
re-enables entries. Emergency exits are executed by the engine, which has
market access; the governor owns state and verdicts only.
"""
from __future__ import annotations
from dataclasses import dataclass
from .config import LabSettings
from .store import LabStore


@dataclass(frozen=True)
class Verdict:
    approved: bool
    reason: str


class LabGovernor:
    def __init__(self, store: LabStore, cfg: LabSettings):
        self.db = store
        self.cfg = cfg

    # ---------------- trailing high-water mark ----------------
    def update_hwm(self, net_equity: float, now_ms: int,
                   require_confirmation: bool = False) -> dict:
        """Ratchet the peak, derive the threshold, detect a breach. The lock
        is set in the SAME transaction as the peak update (atomic).

        require_confirmation: the high-frequency live-tick path sets this so a
        lock needs TWO consecutive breached readings — a single post-gap or
        transient catch-up tick (e.g. a quote that went stale then jumped)
        ratchets the peak and reports the breach but does not irreversibly
        lock. The slower validated REST cycle leaves it False and locks
        immediately. A reading at/above threshold resets the streak."""
        with self.db.conn:
            row = self.db.conn.execute(
                "SELECT value FROM kv WHERE key='peak_equity'").fetchone()
            import json
            previous_peak = json.loads(row[0]) if row else self.cfg.starting_capital_usd
            peak = max(float(previous_peak), net_equity)
            threshold = peak - self.cfg.trailing_drawdown_usd
            breached = net_equity <= threshold
            self.db.conn.execute(
                "INSERT INTO kv(key,value) VALUES('peak_equity',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(peak),))
            already_locked = json.loads((self.db.conn.execute(
                "SELECT value FROM kv WHERE key='lab_locked'").fetchone() or ["false"])[0])
            streak_row = self.db.conn.execute(
                "SELECT value FROM kv WHERE key='breach_streak'").fetchone()
            streak = (json.loads(streak_row[0]) if streak_row else 0) + 1 if breached else 0
            self.db.conn.execute(
                "INSERT INTO kv(key,value) VALUES('breach_streak',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(streak),))
            do_lock = breached and not already_locked and (not require_confirmation or streak >= 2)
            if do_lock:
                reason = (f"TRAILING DRAWDOWN BREACH: net equity {net_equity:.2f} <= "
                          f"threshold {threshold:.2f} (peak {peak:.2f} - "
                          f"{self.cfg.trailing_drawdown_usd:.0f})")
                for key, value in (("lab_locked", True), ("lab_lock_reason", reason),
                                   ("lab_locked_at_ms", now_ms)):
                    self.db.conn.execute(
                        "INSERT INTO kv(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))
                self.db.conn.execute(
                    "INSERT INTO audit_log(ts_ms, level, category, message) VALUES(?,?,?,?)",
                    (now_ms, "error", "risk", reason + " — all strategies locked; "
                     "emergency exits will be attempted; manual reset required"))
        return {"peak_equity": peak, "threshold": threshold, "breached": breached,
                "locked": bool(self.db.get("lab_locked")),
                "excess_loss_usd": max(0.0, threshold - net_equity)}

    def reset(self, current_equity: float, note: str) -> None:
        """Manual post-review reset: clears the lock and RE-ANCHORS the peak
        at current equity (otherwise the old threshold would re-trip at once).
        Refuses when there is nothing to reset."""
        if not self.db.get("lab_locked"):
            raise ValueError("Lab is not locked; nothing to reset")
        if not note or not note.strip():
            raise ValueError("A manual-review note is required to reset")
        with self.db.conn:
            import json
            for key, value in (("lab_locked", False), ("lab_lock_reason", None),
                               ("peak_equity", current_equity)):
                self.db.conn.execute(
                    "INSERT INTO kv(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))
            self.db.conn.execute(
                "INSERT INTO audit_log(ts_ms, level, category, message) VALUES("
                "CAST(strftime('%s','now') AS INTEGER)*1000, 'warning', 'risk', ?)",
                (f"MANUAL RESET after review: '{note}'. Peak re-anchored at "
                 f"{current_equity:.2f}; new threshold "
                 f"{current_equity - self.cfg.trailing_drawdown_usd:.2f}",))

    # ---------------- per-strategy equity floor (research cohort) ----------
    def strategy_equity_breaches(self, strategy_equity: dict[str, float]) -> list[str]:
        """Research-cohort strategies whose net equity is at/below the $30 floor
        ($20 cumulative loss). Extreme-cohort sleeves have no floor and are never
        returned. The caller exits + locks them (atomic in the engine)."""
        from .config import RESEARCH_KEYS
        return [k for k, eq in strategy_equity.items()
                if k in RESEARCH_KEYS and eq <= self.cfg.strategy_lock_floor_usd]

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
        if self.db.get("integrity_locked"):
            return Verdict(False, "accounting integrity lock: new entries blocked "
                                  "pending reconciliation review")
        if self.db.get("lab_locked"):
            return Verdict(False, "Lab locked (trailing drawdown): manual reset required")
        if self.db.get("lab_manual_pause"):
            return Verdict(False, "Lab manually paused")
        # Per-trade cap is the SLEEVE's budget ($5 extreme / $2 research),
        # carried on the plan; falls back to the portfolio ceiling if absent.
        budget = planned.get("risk_budget_usd", self.cfg.max_risk_per_trade_usd)
        if planned["planned_risk_usd"] > budget + 1e-9:
            return Verdict(False, f"planned risk ${planned['planned_risk_usd']:.2f} "
                                  f"exceeds the ${budget:.0f} per-trade cap for this sleeve")
        # Per-strategy lock (research cohort $30 floor; or an explicit lock flag).
        status = self.db.strategy_status(planned["strategy"])
        if status["level"] == "unknown":
            return Verdict(False, f"unknown strategy '{planned['strategy']}'")
        if status["level"] == "locked":
            return Verdict(False, f"{planned['strategy']} is locked "
                                  f"(equity floor / $20 cumulative loss)")
        positions = self.db.open_positions()
        if any(p["symbol"] == planned["symbol"] for p in positions):
            return Verdict(False, f"{planned['symbol']} already open: no duplicates/averaging")
        if len(positions) >= self.cfg.max_open_positions:
            return Verdict(False, f"position limit reached ({self.cfg.max_open_positions})")
        # Correlation-cluster limit (applies when a plan carries a cluster tag).
        cluster = planned.get("corr_cluster", "")
        if cluster and any((p["corr_cluster"] if "corr_cluster" in p.keys() else "") == cluster
                           for p in positions):
            return Verdict(False, f"correlated exposure: a {cluster}-cluster position is "
                                  "already open (shared risk limit)")
        combined = sum(p["planned_risk_usd"] for p in positions) + planned["planned_risk_usd"]
        if combined > self.cfg.max_combined_risk_usd + 1e-9:
            return Verdict(False, f"combined planned risk ${combined:.2f} exceeds the "
                                  f"${self.cfg.max_combined_risk_usd:.0f} cap")
        ledger = self.db.strategy_ledger()
        strategy = ledger.get(planned["strategy"])
        if strategy is None:
            return Verdict(False, f"unknown strategy '{planned['strategy']}'")
        needed = planned["margin_usd"] + planned["entry_fee_usd"]
        if needed > strategy["cash_usd"] + 1e-9:
            return Verdict(False, f"insufficient strategy cash: need ${needed:.2f}, "
                                  f"{planned['strategy']} has ${strategy['cash_usd']:.2f}")
        return Verdict(True, "")
