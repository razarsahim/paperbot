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
    cohort: str = "extreme"          # "extreme" | "research"
    risk_budget_usd: float = 5.0     # planned per-trade risk cap for this sleeve
    has_floor_lock: bool = False     # research cohort: $30 equity-floor lock
    needs_orderbook: bool = False    # orderflow strategy needs a fresh book


# One unified catalog of 10 strategies under a single $500 Extreme Lab.
# Original five (cohort 'extreme'): $5 planned-risk cap, no per-strategy floor
# lock — protected by the portfolio governor + trailing drawdown only.
# Migrated five (cohort 'research'): $2 cap, $30 equity-floor lock ($20
# cumulative loss from $50), $40 warning, correlation-cluster limit.
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
    StrategyDef("regime_trend", "Regime-Aware Trend Following",
                "4h EMA50/200 trend + ADX>22, 15m confirmation, vol-adjusted size, ATR trail",
                cohort="research", risk_budget_usd=2.0, has_floor_lock=True),
    StrategyDef("volatility_breakout", "Volatility Breakout",
                "BB compression / falling ATR, 20-bar break on completed candle, rel-vol>1.5x",
                cohort="research", risk_budget_usd=2.0, has_floor_lock=True),
    StrategyDef("trend_pullback", "Trend Pullback",
                "HTF trend, pullback to EMA20/50, structural reclaim, swing-invalidation stop",
                cohort="research", risk_budget_usd=2.0, has_floor_lock=True),
    StrategyDef("range_reversion", "Range Mean Reversion",
                "ADX<18, BB(20,2) close back inside band, RSI confirm, exit to midpoint/VWAP",
                cohort="research", risk_budget_usd=2.0, has_floor_lock=True),
    StrategyDef("orderflow_imbalance", "Order-Flow Imbalance",
                "weighted depth imbalance + aggressive flow; rejects stale/spoofy books",
                cohort="research", risk_budget_usd=2.0, has_floor_lock=True,
                needs_orderbook=True),
)

EXTREME_KEYS = tuple(s.key for s in STRATEGIES if s.cohort == "extreme")
RESEARCH_KEYS = tuple(s.key for s in STRATEGIES if s.cohort == "research")


@dataclass(frozen=True)
class LabSettings:
    starting_capital_usd: float = 500.0       # 10 sleeves x $50 (unified lab)
    allocation_per_strategy_usd: float = 50.0
    leverage: float = 10.0                    # simulated isolated margin only
    max_risk_per_trade_usd: float = 5.0       # portfolio ceiling; per-sleeve cap
                                              # is the cohort's risk_budget_usd
    max_combined_risk_usd: float = 15.0
    max_open_positions: int = 3
    trailing_drawdown_usd: float = 50.0       # vs persistent high-water mark
    strategy_warning_floor_usd: float = 40.0  # research cohort only
    strategy_lock_floor_usd: float = 30.0     # research cohort: $20 cumulative loss
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
    orderbook_fresh_seconds: int = 15         # research orderflow strategy
    launch_max_age_days: int = 30             # "new coin" definition
    db_path: str = "state/extreme_lab.sqlite"
    main_db_path: str = "state/paperbot_pro.sqlite"  # read-only: universe/instruments
    auto_entry: bool = False                  # PAPERBOT_LAB_AUTO_ENTRY=1, Lab-only
    ws_enabled: bool = True                   # public ticker stream (read-only)
    ws_url: str = "wss://stream.bybit.com/v5/public/linear"
    ws_max_topics: int = 15                   # positions + top universe, bounded
    live_state_path: str = "state/lab_live.json"
    live_publish_interval_s: float = 0.2      # UI-facing throttle (100-250ms band)

    @classmethod
    def from_env(cls) -> "LabSettings":
        cfg = cls()
        updates = {}
        if os.getenv("PAPERBOT_LAB_AUTO_ENTRY") is not None:
            updates["auto_entry"] = os.getenv("PAPERBOT_LAB_AUTO_ENTRY") == "1"
        if os.getenv("PAPERBOT_LAB_WS") is not None:
            updates["ws_enabled"] = os.getenv("PAPERBOT_LAB_WS") == "1"
        for name, cast in (("db_path", str), ("main_db_path", str),
                           ("live_state_path", str),
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
        if not self.strategy_lock_floor_usd < self.strategy_warning_floor_usd \
                < self.allocation_per_strategy_usd:
            raise ValueError("Need research floor lock < warning < allocation")
        if self.atr_stop_multiplier <= 0 or self.trail_atr_multiplier <= 0:
            raise ValueError("Invalid stop parameters")
        if self.slippage_rate < 0 or not 0 < self.max_spread_pct < 0.02:
            raise ValueError("Invalid cost assumptions")
        if self.monitor_interval_seconds < 15:
            raise ValueError("Monitor interval too aggressive for public APIs")
        if self.candle_timeframe != "1h" or self.timeframe_ms != 3_600_000:
            raise ValueError("Lab signals fixed to 1h candles in this version")
