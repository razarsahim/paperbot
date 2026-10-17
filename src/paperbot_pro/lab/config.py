"""Extreme Lab settings: an ISOLATED $250 virtual experimental portfolio.

PAPER ONLY. The Lab shares the public market-data layer and perp math with
the main simulator but owns its own database, risk governor, trailing
portfolio drawdown and (separate, explicitly experimental) auto-entry flag.
Nothing here can touch the main $750 portfolio or any real funds.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import os


@dataclass(frozen=True)
class StrategyDef:
    key: str
    name: str
    description: str


STRATEGIES: tuple[StrategyDef, ...] = (
    StrategyDef("breakout", "Explosive Breakout Hunter",
                "N-bar high/low break with volume expansion"),
    StrategyDef("launch_sniper", "New Coin Launch Sniper",
                "recently listed perps with momentum; idle unless a verified young market exists"),
    StrategyDef("squeeze", "Liquidation Squeeze Hunter",
                "extreme wick + funding extreme, fades the squeeze"),
    StrategyDef("trend", "Trend Rider",
                "EMA pullback-reclaim with ATR trailing stop, no fixed target"),
    StrategyDef("crash_reversal", "Crash Reversal Hunter",
                "deep 24h drop followed by a reversal candle"),
)


@dataclass(frozen=True)
class LabSettings:
    starting_capital_usd: float = 250.0
    allocation_per_strategy_usd: float = 50.0
    leverage: float = 10.0                    # simulated isolated margin only
    max_risk_per_trade_usd: float = 5.0       # planned, including est. costs
    max_combined_risk_usd: float = 15.0
    max_open_positions: int = 3
    trailing_drawdown_usd: float = 50.0       # vs persistent high-water mark
    atr_stop_multiplier: float = 2.0
    trail_atr_multiplier: float = 2.5         # trailing stop distance
    slippage_rate: float = 0.0005
    max_spread_pct: float = 0.003
    taker_fee_default: float = 0.0006
    min_notional_usd: float = 5.0
    candle_timeframe: str = "1h"
    timeframe_ms: int = 3_600_000
    min_bars: int = 60
    monitor_interval_seconds: int = 60        # position/quote monitoring
    price_fresh_seconds: int = 90
    launch_max_age_days: int = 30             # "new coin" definition
    db_path: str = "state/extreme_lab.sqlite"
    main_db_path: str = "state/paperbot_pro.sqlite"  # read-only: universe/instruments
    auto_entry: bool = False                  # PAPERBOT_LAB_AUTO_ENTRY=1, Lab-only

    @classmethod
    def from_env(cls) -> "LabSettings":
        cfg = cls()
        updates = {}
        if os.getenv("PAPERBOT_LAB_AUTO_ENTRY") is not None:
            updates["auto_entry"] = os.getenv("PAPERBOT_LAB_AUTO_ENTRY") == "1"
        for name, cast in (("db_path", str), ("main_db_path", str),
                           ("monitor_interval_seconds", int)):
            raw = os.getenv(f"PAPERBOT_LAB_{name.upper()}")
            if raw is not None:
                updates[name] = cast(raw)
        result = replace(cfg, **updates)
        result.validate()
        return result

    def validate(self) -> None:
        if abs(self.allocation_per_strategy_usd * len(STRATEGIES)
               - self.starting_capital_usd) > 1e-9:
            raise ValueError("Strategy allocations must sum to the Lab capital")
        if not 0 < self.max_risk_per_trade_usd <= 5.0:
            raise ValueError("Lab per-trade planned risk capped at $5")
        if not 0 < self.max_combined_risk_usd <= 15.0:
            raise ValueError("Lab combined planned risk capped at $15")
        if not 1 <= self.max_open_positions <= 3:
            raise ValueError("Lab concurrent positions capped at 3")
        if not 1 <= self.leverage <= 10:
            raise ValueError("Simulated leverage capped at 10x")
        if not 10.0 <= self.trailing_drawdown_usd <= 100.0:
            raise ValueError("Trailing drawdown must be a sane dollar figure")
        if self.atr_stop_multiplier <= 0 or self.trail_atr_multiplier <= 0:
            raise ValueError("Invalid stop parameters")
        if self.slippage_rate < 0 or not 0 < self.max_spread_pct < 0.02:
            raise ValueError("Invalid cost assumptions")
        if self.monitor_interval_seconds < 15:
            raise ValueError("Monitor interval too aggressive for public APIs")
        if self.candle_timeframe != "1h" or self.timeframe_ms != 3_600_000:
            raise ValueError("Lab signals fixed to 1h candles in this version")
