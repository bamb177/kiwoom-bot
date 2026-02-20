from __future__ import annotations
from dataclasses import dataclass
from typing import Dict

from core.logger import log_jsonl
from core.settings import LOG_DIR

@dataclass
class PositionLite:
    qty: int = 0
    avg_price: float = 0.0
    last_price: float = 0.0

class PnLTracker:
    def __init__(self, logger) -> None:
        self.log = logger
        self.pos: Dict[str, PositionLite] = {}

    def on_price(self, symbol: str, last_price: float) -> None:
        p = self.pos.get(symbol)
        if p:
            p.last_price = float(last_price)

    def on_fill(self, symbol: str, side: str, fill_qty: int, fill_price: float) -> None:
        p = self.pos.setdefault(symbol, PositionLite())
        fill_price = float(fill_price)
        if side == "BUY":
            new_qty = p.qty + int(fill_qty)
            if new_qty > 0:
                p.avg_price = (p.avg_price * p.qty + fill_price * fill_qty) / new_qty if p.qty > 0 else fill_price
            p.qty = new_qty
            p.last_price = fill_price
        else:
            p.qty -= int(fill_qty)
            p.last_price = fill_price
            if p.qty <= 0:
                p.qty = 0
                p.avg_price = 0.0

        log_jsonl(LOG_DIR / "fills.jsonl", {
            "symbol": symbol,
            "side": side,
            "fill_qty": int(fill_qty),
            "fill_price": float(fill_price),
            "pos_qty": p.qty,
            "pos_avg": p.avg_price,
        })

    def unrealized_bp(self, symbol: str) -> int:
        p = self.pos.get(symbol)
        if not p or p.qty <= 0 or p.avg_price <= 0 or p.last_price <= 0:
            return 0
        return int(((p.last_price - p.avg_price) / p.avg_price) * 10000)

    def snapshot_log(self) -> None:
        for s, p in self.pos.items():
            if p.qty > 0:
                log_jsonl(LOG_DIR / "pnl.jsonl", {
                    "symbol": s,
                    "qty": p.qty,
                    "avg": p.avg_price,
                    "last": p.last_price,
                    "unreal_bp": self.unrealized_bp(s),
                })
