"""Risk governor: the single gate between a signal and a simulated entry.

Hard rails (never relaxed at runtime): per-trade risk, slot limit, combined
planned stop risk, sticky daily loss lockout, total-drawdown pause requiring
manual review, sleeve isolation, hype watch-only + cumulative loss cap.
Every verdict — approve or reject — is persisted to the signals log.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from .config import ProSettings
from .store import ProStore


@dataclass(frozen=True)
class Verdict:
    approved: bool
    reason: str


class RiskGovernor:
    def __init__(self, store: ProStore, cfg: ProSettings):
        self.db = store
        self.cfg = cfg

    def update_locks(self, equity: float, now_ms: int) -> list[str]:
        """Maintain peak/day anchors and sticky locks. Returns new notices."""
        today = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        notices = []
        if self.db.get("utc_day") != today:
            self.db.set("utc_day", today)
            self.db.set("day_start_equity", equity)
            self.db.set("locked_daily", False)
        peak = max(float(self.db.get("peak_equity")), equity)
        self.db.set("peak_equity", peak)
        if equity <= peak * (1 - self.cfg.max_total_drawdown) and not self.db.get("locked_total"):
            self.db.set("locked_total", True)
            self.db.audit("error", "risk",
                          f"TOTAL DRAWDOWN PAUSE at equity {equity:.2f} (peak {peak:.2f}); "
                          "manual review required", ts_ms=now_ms)
            notices.append("TOTAL DRAWDOWN PAUSE")
        day_start = float(self.db.get("day_start_equity", equity))
        if equity <= day_start * (1 - self.cfg.max_daily_loss) and not self.db.get("locked_daily"):
            self.db.set("locked_daily", True)  # sticky until next UTC day
            self.db.audit("warning", "risk",
                          f"Daily loss lockout at equity {equity:.2f} "
                          f"(day start {day_start:.2f})", ts_ms=now_ms)
            notices.append("DAILY LOSS LOCKOUT")
        return notices

    def approve(self, planned: dict, equity: float, now_ms: int,
                symbol_action: tuple[str, str] | None = None) -> Verdict:
        verdict = self._evaluate(planned, equity)
        if symbol_action is not None:
            symbol, action = symbol_action
            self.db.log_signal(now_ms, symbol, action, verdict.approved,
                               None if verdict.approved else verdict.reason,
                               f"planned risk ${planned['planned_risk_usd']:.2f}, "
                               f"margin ${planned['margin_usd']:.2f}, sleeve {planned['sleeve']}")
        return verdict

    def _evaluate(self, planned: dict, equity: float) -> Verdict:
        sleeve = planned["sleeve"]
        if self.db.get("manual_pause"):
            return Verdict(False, "manually paused: run `propaper resume` to re-enable entries")
        # Check live equity against the anchors as well as the sticky flags:
        # a breach must gate entries in the SAME cycle, before update_locks
        # has persisted it at cycle end.
        peak = max(float(self.db.get("peak_equity", equity)), equity)
        if self.db.get("locked_total") or equity <= peak * (1 - self.cfg.max_total_drawdown):
            return Verdict(False, "TOTAL DRAWDOWN PAUSE: manual review required")
        day_start = float(self.db.get("day_start_equity", equity))
        if self.db.get("locked_daily") or equity <= day_start * (1 - self.cfg.max_daily_loss):
            return Verdict(False, "daily loss lockout until next UTC day")
        if sleeve == "hype":
            if self.cfg.hype_watch_only:
                return Verdict(False, "hype sleeve is WATCH ONLY")
            loss = float(self.db.get("hype_cumulative_loss_usd", 0.0))
            if loss + planned["planned_risk_usd"] > self.cfg.hype_cumulative_loss_cap_usd:
                return Verdict(False, f"hype cumulative loss cap "
                                      f"(${self.cfg.hype_cumulative_loss_cap_usd:.0f}) would be exceeded")
        positions = self.db.open_positions()
        if any(p["symbol"] == planned["symbol"] for p in positions):
            return Verdict(False, f"{planned['symbol']} already open: no averaging or duplicates")
        if len(positions) >= self.cfg.max_open_positions:
            return Verdict(False, f"position limit reached ({self.cfg.max_open_positions})")
        combined = sum(p["planned_risk_usd"] for p in positions) + planned["planned_risk_usd"]
        if combined > equity * self.cfg.max_combined_risk + 1e-9:
            return Verdict(False, f"combined planned risk ${combined:.2f} exceeds "
                                  f"{self.cfg.max_combined_risk:.1%} of equity")
        cash_key = "cash_core" if sleeve == "core" else "cash_hype"
        available = float(self.db.get(cash_key))
        needed = planned["margin_usd"] + planned["entry_fee_usd"]
        if needed > available + 1e-9:
            return Verdict(False, f"insufficient {sleeve} sleeve margin: "
                                  f"need ${needed:.2f}, available ${available:.2f}")
        return Verdict(True, "")
