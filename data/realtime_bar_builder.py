from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict


@dataclass
class Bar:
    ts: str          # "YYYY-MM-DD HH:MM"
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class RealtimeBarBuilder:
    def __init__(self, on_bar: Callable[[Bar], None]) -> None:
        self.on_bar = on_bar
        self.cur: Dict[str, Bar] = {}
        self.last_minute: Dict[str, str] = {}

    def _minute_key(self, ts: str) -> str:
        return ts[:16]

    def on_tick(self, symbol: str, price: float, volume: int, ts: str) -> None:
        m = self._minute_key(ts)
        prev_m = self.last_minute.get(symbol)

        if prev_m and prev_m != m:
            b = self.cur.get(symbol)
            if b:
                self.on_bar(b)
            self.cur.pop(symbol, None)

        self.last_minute[symbol] = m

        b = self.cur.get(symbol)
        if not b:
            self.cur[symbol] = Bar(
                ts=m, symbol=symbol,
                open=price, high=price, low=price, close=price,
                volume=max(0, int(volume)),
            )
        else:
            b.high = max(b.high, price)
            b.low = min(b.low, price)
            b.close = price
            b.volume += max(0, int(volume))

    def flush(self, now_ts: str) -> None:
        m = self._minute_key(now_ts)
        for symbol, last_m in list(self.last_minute.items()):
            if last_m != m:
                b = self.cur.get(symbol)
                if b:
                    self.on_bar(b)
                    self.cur.pop(symbol, None)
                self.last_minute[symbol] = m
