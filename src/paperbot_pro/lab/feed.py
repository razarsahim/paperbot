"""Bybit v5 PUBLIC linear ticker WebSocket client. Read-only market data:
no authentication, no private topics, no order entry — the endpoint cannot
accept orders. One bounded connection; ping/pong heartbeats; reconnect with
backoff and full resubscribe; subscription set changes trigger a clean
reconnect (rare: only when the open-position/universe set changes)."""
from __future__ import annotations
import asyncio
import json
import threading
import time


def parse_message(raw: str):
    """Returns (symbol, fields, exchange_ts_ms, kind) for ticker messages,
    None for heartbeats/acks/other topics/garbage."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    topic = msg.get("topic", "")
    if not topic.startswith("tickers."):
        return None
    data = msg.get("data")
    ts = msg.get("ts")
    if not isinstance(data, dict) or ts is None:
        return None
    return (topic.split(".", 1)[1], data, int(ts),
            "snapshot" if msg.get("type") == "snapshot" else "delta")


class BybitTickerFeed(threading.Thread):
    """Daemon thread owning the WS connection. on_ticker(symbol, fields,
    ts_ms, kind) is invoked from this thread for every accepted message."""
    def __init__(self, symbols: list[str], on_ticker, on_status=None,
                 url: str = "wss://stream.bybit.com/v5/public/linear",
                 ping_interval: float = 20.0):
        super().__init__(daemon=True, name="bybit-ticker-feed")
        self._symbols = list(dict.fromkeys(symbols))
        self.on_ticker = on_ticker
        self.on_status = on_status or (lambda status, detail: None)
        self.url = url
        self.ping_interval = ping_interval
        self._stop = threading.Event()
        self._resubscribe = threading.Event()

    def set_symbols(self, symbols: list[str]) -> None:
        new = list(dict.fromkeys(symbols))
        if new != self._symbols:
            self._symbols = new
            self._resubscribe.set()

    def stop(self) -> None:
        self._stop.set()

    # ---------------- internals ----------------
    def run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        import websockets
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=None,
                                              close_timeout=3) as ws:
                    self._resubscribe.clear()
                    topics = [f"tickers.{s}" for s in self._symbols]
                    if topics:
                        await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                    self.on_status("connected", f"{len(topics)} topics")
                    backoff = 1.0
                    last_ping = time.monotonic()
                    while not self._stop.is_set() and not self._resubscribe.is_set():
                        if time.monotonic() - last_ping > self.ping_interval:
                            await ws.send(json.dumps({"op": "ping"}))
                            last_ping = time.monotonic()
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        except asyncio.TimeoutError:
                            continue
                        parsed = parse_message(raw)
                        if parsed is not None:
                            self.on_ticker(*parsed)
                    if self._resubscribe.is_set():
                        self.on_status("resubscribing", "symbol set changed")
                        continue
            except Exception as exc:
                self.on_status("disconnected", f"{type(exc).__name__}: {exc}")
                if self._stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
        self.on_status("stopped", "")
