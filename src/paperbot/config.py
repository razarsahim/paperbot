from __future__ import annotations
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    exchange: str = "kraken"
    symbol: str = "BTC/GBP"
    timeframe: str = "1h"
    timeframe_ms: int = 3_600_000
    starting_balance: float = 1000.0
    risk_per_trade: float = 0.005
    max_daily_drawdown: float = 0.02
    max_total_drawdown: float = 0.05
    fee_rate: float = 0.004  # 0.4% each way (conservative illustrative assumption)
    slippage_rate: float = 0.001  # 0.1% each way
    max_spread_pct: float = 0.005
    atr_stop_multiplier: float = 2.0
    reward_risk: float = 2.0
    price_fresh_seconds: int = 90
    entry_window_minutes: int = 10
    interval_seconds: int = 60
    min_bars: int = 85

    @classmethod
    def from_env(cls) -> "Settings":
        config = cls()
        allowed = {
            "starting_balance": float, "risk_per_trade": float,
            "max_daily_drawdown": float, "max_total_drawdown": float,
            "fee_rate": float, "slippage_rate": float,
            "max_spread_pct": float, "atr_stop_multiplier": float,
            "reward_risk": float, "entry_window_minutes": int,
            "interval_seconds": int,
        }
        updates = {}
        for name, cast in allowed.items():
            raw = os.getenv(f"PAPERBOT_{name.upper()}")
            if raw is not None:
                updates[name] = cast(raw)
        if os.getenv("PAPERBOT_EXCHANGE") or os.getenv("PAPERBOT_SYMBOL"):
            # Specify both only for another SPOT market. This project has no futures support.
            updates["exchange"] = os.getenv("PAPERBOT_EXCHANGE", config.exchange)
            updates["symbol"] = os.getenv("PAPERBOT_SYMBOL", config.symbol)
        from dataclasses import replace
        result = replace(config, **updates)
        result.validate()
        return result

    def validate(self) -> None:
        if self.timeframe != "1h" or self.timeframe_ms != 3_600_000:
            raise ValueError("Only 1h candles supported by this MVP")
        if not 0 < self.risk_per_trade <= 0.01:
            raise ValueError("Demo risk_per_trade must be <= 1%")
        if not 0 < self.max_daily_drawdown <= 0.10:
            raise ValueError("Daily limit must be between 0 and 10%")
        if not 0 < self.max_total_drawdown <= 0.20:
            raise ValueError("Total limit must be between 0 and 20%")
        if self.starting_balance <= 0 or self.fee_rate < 0 or self.slippage_rate < 0:
            raise ValueError("Invalid balance, fee or slippage")
        if self.atr_stop_multiplier <= 0 or self.reward_risk <= 0:
            raise ValueError("Invalid stop multiplier or reward:risk")
        if not 0 < self.max_spread_pct < 0.05:
            raise ValueError("Invalid spread limit")
        if not 1 <= self.entry_window_minutes <= 15 or self.interval_seconds < 10:
            raise ValueError("Invalid timing parameters")
