"""CRH replay configuration.

BASELINE = the deployed Extreme Lab rules for the crash_reversal sleeve,
verbatim: 1h candles, -8% over 24 bars, hammer on a closed candle,
2.0xATR(14) initial stop, 2.5xATR trail on each closed bar, $5 planned risk
on a $50 sleeve, 10x isolated, 3 slots, $15 combined planned risk, $50
trailing drawdown lock, no per-strategy loss trigger (extreme cohort),
0.05% slippage, 0.3% spread gate, 90s quote freshness, 0.06% taker.

Anything else is an EXPERIMENT and is labelled as such in every result.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, dataclass, field, replace

CONFIG_VERSION = 1


@dataclass(frozen=True)
class CRHConfig:
    # capital / leverage
    starting_capital_usd: float = 50.0
    leverage: float = 10.0
    # rails (absolute dollars; the UI derives them from capital fractions)
    risk_per_trade_usd: float = 5.0
    max_open_positions: int = 3
    max_combined_risk_usd: float = 15.0
    trailing_drawdown_usd: float = 50.0
    strategy_loss_trigger_usd: float | None = None   # e.g. 20.0 => lock at equity <= capital-20
    # signal rules (deployed baseline values)
    signal_timeframe: str = "1h"
    crash_window_bars: int = 24
    crash_drop_pct: float = -8.0
    require_hammer: bool = True
    min_bars: int = 60
    candle_limit: int = 200          # engine fetches 200 bars => 199 closed + forming
    # execution rules
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    trail_atr_multiplier: float = 2.5
    slippage_rate: float = 0.0005
    max_spread_pct: float = 0.003
    price_fresh_seconds: int = 90
    taker_fee_default: float = 0.0006
    min_notional_usd: float = 5.0
    reward_risk: float = 2.0         # unused (no fixed target), kept for perp.plan_entry
    funding_interval_ms: int = 8 * 3_600_000
    cycle_offset_ms: int = 5_000     # engine cycles at minute + 5s, like the live loop
    # replay fidelity: "exact" needs archived L2 quotes; "approximate" uses
    # 1m opens +/- a conservative synthetic half-spread
    fidelity: str = "exact"
    approx_half_spread: float = 0.0005
    label: str = "BASELINE (deployed crash_reversal rules)"

    def fingerprint(self) -> str:
        raw = json.dumps({"v": CONFIG_VERSION, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_baseline(self) -> bool:
        base = CRHConfig()
        for k in ("crash_window_bars", "crash_drop_pct", "require_hammer", "atr_period",
                  "atr_stop_multiplier", "trail_atr_multiplier", "slippage_rate",
                  "max_spread_pct", "taker_fee_default", "signal_timeframe", "min_bars",
                  "candle_limit", "leverage"):
            if getattr(self, k) != getattr(base, k):
                return False
        return True

    def validate(self) -> None:
        if self.starting_capital_usd <= 0:
            raise ValueError("capital must be positive")
        if not 1 <= self.leverage <= 25:
            raise ValueError("simulated leverage must be within 1..25x")
        if not 0 < self.risk_per_trade_usd <= self.starting_capital_usd:
            raise ValueError("risk per trade must be within (0, capital]")
        if not 1 <= self.max_open_positions <= 10:
            raise ValueError("max open positions 1..10")
        if self.max_combined_risk_usd < self.risk_per_trade_usd:
            raise ValueError("combined risk cap below the per-trade budget")
        if self.trailing_drawdown_usd <= 0:
            raise ValueError("trailing drawdown must be positive")
        if self.strategy_loss_trigger_usd is not None and not (
                0 < self.strategy_loss_trigger_usd < self.starting_capital_usd):
            raise ValueError("loss trigger must be within (0, capital)")
        if self.signal_timeframe not in ("1h", "1m"):
            raise ValueError("signal timeframe 1h or 1m")
        if self.fidelity not in ("exact", "approximate"):
            raise ValueError("fidelity exact|approximate")
        if self.crash_window_bars < 1 or self.crash_drop_pct >= 0:
            raise ValueError("invalid crash rule")

    @property
    def timeframe_ms(self) -> int:
        return {"1h": 3_600_000, "1m": 60_000}[self.signal_timeframe]


def scaled_baseline(capital: float, leverage: float = 10.0, **overrides) -> CRHConfig:
    """Deployed rails scaled proportionally to a different capital: risk 10%
    of capital per trade, 30% combined, trailing drawdown 100% of capital
    (= the deployed $5 / $15 / $50 on a $50 sleeve)."""
    cfg = CRHConfig(starting_capital_usd=capital, leverage=leverage,
                    risk_per_trade_usd=round(capital * 0.10, 6),
                    max_combined_risk_usd=round(capital * 0.30, 6),
                    trailing_drawdown_usd=capital)
    cfg = replace(cfg, **overrides)
    if capital != 50.0 or leverage != 10.0 or overrides:
        cfg = replace(cfg, label=("BASELINE rules, capital/leverage scaled"
                                  if cfg.is_baseline() else "EXPERIMENT"))
    cfg.validate()
    return cfg
