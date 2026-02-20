from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Order:
    symbol: str
    side: Side
    qty: int
    order_type: OrderType
    price: float | None = None


@dataclass
class Position:
    symbol: str
    qty: int = 0
    avg_price: float = 0.0
    last_price: float = 0.0

    def pnl_ratio(self) -> float:
        if self.qty <= 0 or self.avg_price <= 0 or self.last_price <= 0:
            return 0.0
        return (self.last_price / self.avg_price) - 1.0
