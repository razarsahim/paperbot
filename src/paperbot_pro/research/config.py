"""Strategy Research Lab settings: an ISOLATED $250 virtual portfolio with
five new strategies, independent per-strategy ledgers and locks, and its own
$50 trailing drawdown. PAPER ONLY; shares the public market-data layer and
perp math but owns its database, governor and (separate, experimental)
auto-entry flag. Cannot touch the main portfolio or the existing Lab."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import os


@dataclass(frozen=True)
class StrategyDef:
    key: str
    name: str
    description: str
    needs_orderbook: bool = False


STRATEGIES: tuple[StrategyDef, ...] = (
    StrategyDef("regime_trend", "Regime-Aware Trend Following",
                "4h EMA50/200 trend + ADX>22, 15m confirmation, vol-adjusted size, ATR trail"),
    StrategyDef("volatility_breakout", "Volatility Breakout",
                "BB compression / falling ATR, 20-bar break on completed candle, rel-vol>1.5x"),
    StrategyDef("trend_pullback", "Trend Pullback",
                "HTF trend, pullback to EMA20/50, structural reclaim, swing-invalidation stop"),
    StrategyDef("range_reversion", "Range Mean Reversion",
                "ADX<18, BB(20,2) close back inside band, RSI confirm, exit to midpoint/VWAP"),
    StrategyDef("orderflow_imbalance", "Order-Flow Imbalance",
                "weighted depth imbalance + aggressive flow; rejects stale/spoofy books",
                needs_orderbook=True),
)


@dataclass(frozen=True)
class ResearchSettings:
    starting_capital_usd: float = 250.0
    allocation_per_strategy_usd: float = 50.0
    leverage: float = 10.0
    max_risk_per_trade_usd: float = 2.0
    strategy_warning_floor_usd: float = 40.0
    strategy_lock_floor_usd: float = 30.0      # = $20 cumulative loss from $50
    trailing_drawdown_usd: float = 50.0        # lab-level, vs persistent HWM
    max_open_positions: int = 4                # shared concurrency across strategies
    atr_stop_multiplier: float = 2.0
    trail_atr_multiplier: float = 2.5
    slippage_rate: float = 0.0005
    max_spread_pct: float = 0.003
    taker_fee_default: float = 0.0006
    min_notional_usd: float = 5.0
    candle_timeframe: str = "1h"
    timeframe_ms: int = 3_600_000
    min_bars: int = 60
    monitor_interval_seconds: int = 60
    price_fresh_seconds: int = 90
    orderbook_fresh_seconds: int = 15
    db_path: str = "state/research_lab.sqlite"
    main_db_path: str = "state/paperbot_pro.sqlite"   # read-only: universe/instruments
    live_state_path: str = "state/research_live.json"
    live_publish_interval_s: float = 0.2
    ws_enabled: bool = True
    ws_url: str = "wss://stream.bybit.com/v5/public/linear"
    ws_max_topics: int = 15
    auto_entry: bool = False                   # PAPERBOT_RESEARCH_AUTO_ENTRY=1, lab-only

    @classmethod
    def from_env(cls) -> "ResearchSettings":
        cfg = cls()
        updates = {}
        if os.getenv("PAPERBOT_RESEARCH_AUTO_ENTRY") is not None:
            updates["auto_entry"] = os.getenv("PAPERBOT_RESEARCH_AUTO_ENTRY") == "1"
        if os.getenv("PAPERBOT_RESEARCH_WS") is not None:
            updates["ws_enabled"] = os.getenv("PAPERBOT_RESEARCH_WS") == "1"
        for name in ("db_path", "main_db_path", "live_state_path"):
            raw = os.getenv(f"PAPERBOT_RESEARCH_{name.upper()}")
            if raw is not None:
                updates[name] = raw
        result = replace(cfg, **updates)
        result.validate()
        return result

    def validate(self) -> None:
        if abs(self.allocation_per_strategy_usd * len(STRATEGIES)
               - self.starting_capital_usd) > 1e-9:
            raise ValueError("Strategy allocations must sum to the lab capital")
        if not 0 < self.max_risk_per_trade_usd <= 2.0:
            raise ValueError("Research per-trade planned risk capped at $2")
        if abs(self.strategy_lock_floor_usd - 30.0) > 1e-9:
            raise ValueError("Strategy lock floor is $30 ($20 cumulative loss from $50)")
        if not self.strategy_lock_floor_usd < self.strategy_warning_floor_usd < \
                self.allocation_per_strategy_usd:
            raise ValueError("Need lock < warning < allocation")
        if not 1 <= self.leverage <= 10:
            raise ValueError("Simulated leverage capped at 10x")
        if not 1 <= self.max_open_positions <= 5:
            raise ValueError("Shared concurrency 1..5")
        if not 10.0 <= self.trailing_drawdown_usd <= 100.0:
            raise ValueError("Lab trailing drawdown out of range")
        if self.atr_stop_multiplier <= 0 or self.trail_atr_multiplier <= 0:
            raise ValueError("Invalid stop parameters")
        if self.candle_timeframe != "1h" or self.timeframe_ms != 3_600_000:
            raise ValueError("Signal timeframe fixed to 1h in this version")
