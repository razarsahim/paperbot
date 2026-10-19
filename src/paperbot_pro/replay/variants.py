"""Named, replay-only strategy VARIANTS (separately labelled experiments).

A variant overrides strategy constants inside the replay process only: the
production modules on disk, the live engines (separate processes) and their
databases are never touched. Every override is recorded in the run result so
a variant can never be mistaken for the deployed strategy.
"""
from __future__ import annotations
import importlib

VARIANTS: dict[str, dict] = {
    "crh_1m_24h": {
        "label": "EXPERIMENTAL VARIANT: Crash Reversal on 1m candles, 24h (1,440-bar) drop "
                 "lookback; all other rules unchanged",
        "strategies": ["crash_reversal"],
        "timeframe": "1m",
        # 1,440-bar lookback: the evaluator reads bars[-(1440+1)] and needs >= 1,442 bars
        "min_candle_limit": 1442,
        "overrides": {"paperbot_pro.lab.strategies": {"CRASH_WINDOW": 1440}},
        "unchanged": ["CRASH_DROP_PCT = -8.0", "hammer reversal: close > open and lower wick > body",
                      "initial stop 2.0 x ATR(14) of signal timeframe",
                      "trailing stop 2.5 x ATR(14) on each closed bar, never widened",
                      "$5 planned risk, 10x isolated, $50 sleeve, governor rails"],
    },
}


def apply_variant(name: str) -> dict:
    """Apply a variant's in-process overrides; returns a record of exactly
    what changed (old -> new) for the result file."""
    spec = VARIANTS[name]
    changed = []
    for mod_name, attrs in spec["overrides"].items():
        mod = importlib.import_module(mod_name)
        for attr, value in attrs.items():
            old = getattr(mod, attr)
            setattr(mod, attr, value)
            changed.append({"module": mod_name, "name": attr, "deployed": old, "variant": value})
    return {"name": name, "label": spec["label"], "timeframe": spec["timeframe"],
            "min_candle_limit": spec["min_candle_limit"], "overrides": changed,
            "unchanged": spec["unchanged"]}
