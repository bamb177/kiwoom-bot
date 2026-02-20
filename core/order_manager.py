from __future__ import annotations
import time
from collections import defaultdict, deque
from typing import Tuple

from core.execution_guard import ExecutionGuard
from core.logger import log_jsonl
from core.settings import LOG_DIR
from core.types import Order

class OrderManager:
    def __init__(self, logger, broker, guard: ExecutionGuard) -> None:
        self.log = logger
        self.broker = broker
        self.guard = guard
        self._last_symbol_ts = defaultdict(float)

    def can_order(self, symbol: str, cooldown_sec: int, ts_str: str, order: Order) -> Tuple[bool, str]:
        now = time.time()
        if now - self._last_symbol_ts[symbol] < cooldown_sec:
            return False, "symbol_cooldown"
        ok, reason = self.guard.allow_order(ts_str, order)
        return ok, reason

    def record_order(self, symbol: str, ts_str: str) -> None:
        self._last_symbol_ts[symbol] = time.time()
        self.guard.record_order(ts_str, symbol)

    def send(self, order: Order, reason: str, cooldown_sec: int = 3) -> bool:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        ok, why = self.can_order(order.symbol, cooldown_sec, ts, order)
        if not ok:
            self.log.info(f"[ORDER_BLOCK] {order.symbol} {order.side.value} qty={order.qty} why={why}")
            return False

        log_jsonl(LOG_DIR / "orders.jsonl", {
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": int(order.qty),
            "type": order.order_type.value,
            "price": order.price,
            "reason": reason,
        })
        try:
            self.broker.place_order(order)
            self.record_order(order.symbol, ts)
            self.log.info(f"[ORDER] {order.side.value} {order.symbol} x{order.qty} reason={reason}")
            return True
        except Exception as e:
            self.log.exception(f"[ORDER_FAIL] {order.side.value} {order.symbol} x{order.qty} reason={reason} err={e}")
            return False
