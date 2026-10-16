"""PaperBot Pro settings. SIMULATION ONLY: no credentials, no order APIs."""
from __future__ import annotations
from dataclasses import dataclass, replace
import os


@dataclass(frozen=True)
class ProSettings:
    starting_balance_usd: float = 1000.0
    core_sleeve_usd: float = 900.0
    hype_sleeve_usd: float = 100.0
    leverage: float = 10.0                 # simulated isolated margin only
    risk_per_trade: float = 0.005          # of TOTAL equity, core sleeve
    max_open_positions: int = 3
    max_combined_risk: float = 0.015       # sum of planned stop risks
    max_daily_loss: float = 0.02           # sticky until next UTC day
    max_total_drawdown: float = 0.05       # pause-for-review
    hype_risk_per_trade: float = 0.0025
    hype_cumulative_loss_cap_usd: float = 30.0
    hype_watch_only: bool = True
    taker_fee_default: float = 0.0006      # used only if metadata lacks fees
    slippage_rate: float = 0.0005
    max_spread_pct: float = 0.003
    atr_stop_multiplier: float = 2.0
    reward_risk: float = 2.0
    min_notional_usd: float = 5.0
    exchanges: tuple[str, ...] = ("bybit", "okx", "binanceusdm", "krakenfutures")
    quote_currencies: tuple[str, ...] = ("USDT", "USD")
    universe_size: int = 20
    universe_refresh_hours: int = 24
    scan_interval_seconds: int = 300
    candle_timeframe: str = "1h"
    timeframe_ms: int = 3_600_000
    min_bars: int = 85
    price_fresh_seconds: int = 120
    monitor_gap_seconds: int = 900
    api_host: str = "127.0.0.1"
    api_port: int = 8777
    db_path: str = "state/paperbot_pro.sqlite"
    legacy_db_path: str = "state/paper.sqlite"
    validation_report_path: str = "state/validation_report.json"
    auto_entry: bool = False  # even when True, a validation report is required

    @classmethod
    def from_env(cls) -> "ProSettings":
        cfg = cls()
        casts = {
            "risk_per_trade": float, "max_open_positions": int,
            "max_combined_risk": float, "max_daily_loss": float,
            "max_total_drawdown": float, "leverage": float,
            "scan_interval_seconds": int, "api_port": int,
            "db_path": str, "legacy_db_path": str, "auto_entry": lambda v: v == "1",
        }
        updates = {}
        for name, cast in casts.items():
            raw = os.getenv(f"PAPERBOT_PRO_{name.upper()}")
            if raw is not None:
                updates[name] = cast(raw)
        result = replace(cfg, **updates)
        result.validate()
        return result

    def validate(self) -> None:
        if abs(self.core_sleeve_usd + self.hype_sleeve_usd - self.starting_balance_usd) > 1e-9:
            raise ValueError("Sleeves must sum to the starting balance")
        if not 0 < self.risk_per_trade <= 0.01 or not 0 < self.hype_risk_per_trade <= 0.005:
            raise ValueError("Per-trade risk too large for a research simulator")
        if not 1 <= self.leverage <= 10:
            raise ValueError("Simulated leverage capped at 10x")
        if not 1 <= self.max_open_positions <= 5:
            raise ValueError("max_open_positions must be 1..5")
        if not 0 < self.max_combined_risk <= 0.03:
            raise ValueError("Combined planned risk ceiling too large")
        if not 0 < self.max_daily_loss <= 0.05 or not 0 < self.max_total_drawdown <= 0.20:
            raise ValueError("Lockout thresholds out of range")
        if self.hype_cumulative_loss_cap_usd > self.hype_sleeve_usd:
            raise ValueError("Hype loss cap cannot exceed the hype sleeve")
        if self.taker_fee_default < 0 or self.slippage_rate < 0 or not 0 < self.max_spread_pct < 0.02:
            raise ValueError("Invalid cost assumptions")
        if self.atr_stop_multiplier <= 0 or self.reward_risk <= 0 or self.min_notional_usd <= 0:
            raise ValueError("Invalid stop/target/notional parameters")
        if self.scan_interval_seconds < 60 or self.universe_size > 50:
            raise ValueError("Invalid cadence or universe size")
        if self.candle_timeframe != "1h" or self.timeframe_ms != 3_600_000:
            raise ValueError("Signal timeframe fixed to 1h in this version")
