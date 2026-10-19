"""Find which universe members can produce a Crash Reversal signal at all in the
window, using the strategy's own evaluator on the same 199 closed 1h bars the
engine sees. Only those symbols need archived order books (entry quotes and
position monitoring); every other symbol is skipped by the engine either way
(no signal => no quote needed), so this changes no result. Output:
signal_symbols.json."""
import json
from pathlib import Path

from paperbot.models import Candle
from paperbot_pro.lab.config import LabSettings
from paperbot_pro.lab.strategies import _base, _crash_reversal

D = Path(__file__).parent
T0, T1, H = 1792195200000, 1792368000000, 3_600_000
universe = json.loads((D / "universe_daily.json").read_text())
cfg = LabSettings()
hits = {}
for sym in sorted({s for v in universe.values() for s in v}):
    bid = sym.split("/")[0] + "USDT"
    rows = json.loads((D / "data/kline_1h" / f"{bid}.json").read_text())["rows"]
    bars = [Candle(int(r[0]), *r[1:6]) for r in rows]
    for i, b in enumerate(bars):
        close = b.timestamp + H
        if not (T0 <= close < T1):
            continue
        day = __import__("datetime").datetime.utcfromtimestamp(close / 1000).strftime("%Y-%m-%d")
        if sym not in universe.get(day, []):
            continue
        w = bars[max(0, i - 198):i + 1]
        if len(w) < cfg.min_bars:
            continue
        vol = _base(w, cfg)
        if vol is None:
            continue
        s = _crash_reversal(w, cfg, {}, vol)
        if s.action:
            hits.setdefault(bid, []).append({"candle_close_ms": close, "reason": s.reason})
(D / "signal_symbols.json").write_text(json.dumps(hits, indent=1))
print(len(hits), "symbols with signals:", {k: len(v) for k, v in hits.items()})
