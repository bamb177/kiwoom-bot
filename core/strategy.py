from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from core.types import Side, OrderType, Order
from core.settings import BotConfig

@dataclass
class Signal:
    symbol: str
    side: Side
    qty: int
    reason: str

class SimpleScoreStrategy:
    def __init__(self, logger, cfg: BotConfig, scoreboard, pnl_tracker) -> None:
        self.log = logger
        self.cfg = cfg
        self.sb = scoreboard
        self.pnl = pnl_tracker

    def _pos(self, symbol: str):
        return self.pnl.pos.get(symbol)

    def decide_entry(self, symbol: str, can_hold_more: bool, last_price: float) -> Optional[Signal]:
        if not can_hold_more:
            return None
        if self._pos(symbol) and self._pos(symbol).qty > 0:
            return None

        if float(self.sb.get(symbol)) < float(self.cfg.score_entry_threshold):
            return None

        if last_price <= 0:
            return None
        qty = int(self.cfg.entry_krw // last_price)
        if qty <= 0:
            return None
        return Signal(symbol=symbol, side=Side.BUY, qty=qty, reason="score_entry")

    def decide_exit(self, symbol: str) -> Optional[Signal]:
        p = self._pos(symbol)
        if not p or p.qty <= 0:
            return None
        u_bp = self.pnl.unrealized_bp(symbol)
        if u_bp <= -int(self.cfg.stop_loss_bp):
            return Signal(symbol=symbol, side=Side.SELL, qty=p.qty, reason="stop_loss")
        if u_bp >= int(self.cfg.take_profit_bp):
            return Signal(symbol=symbol, side=Side.SELL, qty=p.qty, reason="take_profit")
        return None

    def to_order(self, sig: Signal) -> Order:
        return Order(
            symbol=sig.symbol,
            side=sig.side,
            qty=int(sig.qty),
            order_type=OrderType.MARKET,
            price=None,
        )
