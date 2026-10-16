"""Pure isolated-margin linear-perp SIMULATION math. No exchange calls.

Conventions and conservatism:
- Liquidation estimate uses the standard isolated approximation
  liq = entry*(1 - 1/L + mmr) for longs (mirrored for shorts), with the
  exchange's published tier-1 maintenance margin rate. Real liquidation also
  depends on fees/funding and tiering; the estimate is for simulation and is
  never claimed exact.
- When an observed price gaps past both stop and liquidation, LIQUIDATION
  wins (the worse outcome). Stops fill at the observed price, not the stop.
- Target fills are never better than the target price.
- A liquidated position loses its entire margin plus paid fees/funding.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import floor
from .config import ProSettings


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    taker_fee: float
    maint_margin_rate: float
    tick_size: float
    lot_size: float


@dataclass(frozen=True)
class PlannedEntry:
    ok: bool
    reason: str
    side: str = ""
    entry_price: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    liq_price_est: float = 0.0
    qty: float = 0.0
    notional_usd: float = 0.0
    margin_usd: float = 0.0
    entry_fee_usd: float = 0.0
    planned_risk_usd: float = 0.0
    leverage: float = 0.0


@dataclass(frozen=True)
class ExitEvent:
    reason: str
    exit_price: float
    pnl_usd: float
    exit_fee_usd: float


def direction(side: str) -> int:
    return 1 if side == "long" else -1


def liquidation_price(side: str, entry: float, leverage: float, mmr: float) -> float:
    if side == "long":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def unrealized_pnl(side: str, entry: float, mark: float, qty: float) -> float:
    return direction(side) * (mark - entry) * qty


def realized_pnl(side: str, entry: float, exit_fill: float, qty: float,
                 entry_fee: float, exit_fee: float, funding: float) -> float:
    return direction(side) * (exit_fill - entry) * qty - entry_fee - exit_fee - funding


def funding_cost(side: str, rate: float, mark: float, qty: float) -> float:
    """Signed funding cost: positive = the position pays. Longs pay positive
    rates; shorts receive them."""
    return direction(side) * rate * mark * qty


def plan_entry(side: str, price: float, atr_value: float, spec: ContractSpec,
               cfg: ProSettings, equity: float, available_margin: float,
               risk_rate: float) -> PlannedEntry:
    """Risk-based sizing: the planned worst-case loss at the stop (slippage
    and both taker fees included) stays within risk_rate of total equity, and
    the required margin plus entry fee must fit the sleeve's available cash.
    """
    if atr_value <= 0 or price <= 0:
        return PlannedEntry(False, "invalid price/ATR input")
    slip, fee, lev = cfg.slippage_rate, spec.taker_fee, cfg.leverage
    sign = direction(side)
    fill = price * (1 + sign * slip)
    stop = fill - sign * cfg.atr_stop_multiplier * atr_value
    if stop <= 0:
        return PlannedEntry(False, "ATR-derived stop below zero")
    liq = liquidation_price(side, fill, lev, spec.maint_margin_rate)
    if (side == "long" and stop <= liq) or (side == "short" and stop >= liq):
        return PlannedEntry(
            False, f"stop {stop:.6g} at/beyond liquidation estimate {liq:.6g} "
                   f"at {lev:.0f}x — volatility too high for this leverage")
    stop_fill = stop * (1 - sign * slip)
    loss_per_unit = sign * (fill - stop_fill) + fill * fee + stop_fill * fee
    if loss_per_unit <= 0:
        return PlannedEntry(False, "invalid planned loss per unit")
    qty_risk = equity * risk_rate / loss_per_unit
    # cash needed per unit = margin (fill/leverage) + entry fee (fill*fee)
    qty_margin = available_margin / (fill * (1 / lev + fee))
    qty = floor(min(qty_risk, qty_margin) / spec.lot_size) * spec.lot_size
    notional = qty * fill
    if qty <= 0 or notional < cfg.min_notional_usd:
        return PlannedEntry(False, "position too small after margin/lot constraints")
    return PlannedEntry(
        ok=True, reason="", side=side, entry_price=fill, stop=stop,
        target=fill + sign * cfg.reward_risk * abs(fill - stop),
        liq_price_est=liq, qty=qty, notional_usd=notional,
        margin_usd=notional / lev, entry_fee_usd=notional * fee,
        planned_risk_usd=qty * loss_per_unit, leverage=lev)


def check_exit(pos: dict, observed_price: float, cfg: ProSettings,
               taker_fee: float) -> ExitEvent | None:
    """Evaluate one observed price against liquidation, stop and target.
    Liquidation is checked FIRST: when a gap crosses both, the worse outcome
    is taken. Returns None when the position simply holds."""
    side = pos["side"]
    sign = direction(side)
    p = observed_price
    hit_liq = p <= pos["liq_price_est"] if side == "long" else p >= pos["liq_price_est"]
    if hit_liq:
        loss = pos["margin_usd"] + pos["entry_fee_usd"] + pos["funding_paid_usd"]
        return ExitEvent("LIQUIDATION", pos["liq_price_est"], -loss, 0.0)
    hit_stop = p <= pos["stop"] if side == "long" else p >= pos["stop"]
    if hit_stop:
        fill = p * (1 - sign * cfg.slippage_rate)
        exit_fee = abs(fill * pos["qty"] * taker_fee)
        gapped = (p < pos["stop"]) if side == "long" else (p > pos["stop"])
        pnl = realized_pnl(side, pos["entry_price"], fill, pos["qty"],
                           pos["entry_fee_usd"], exit_fee, pos["funding_paid_usd"])
        return ExitEvent("STOP (gap)" if gapped else "STOP", fill, pnl, exit_fee)
    hit_target = p >= pos["target"] if side == "long" else p <= pos["target"]
    if hit_target:
        fill = pos["target"] * (1 - sign * cfg.slippage_rate)  # never better than target
        exit_fee = abs(fill * pos["qty"] * taker_fee)
        pnl = realized_pnl(side, pos["entry_price"], fill, pos["qty"],
                           pos["entry_fee_usd"], exit_fee, pos["funding_paid_usd"])
        return ExitEvent("TARGET", fill, pnl, exit_fee)
    return None
