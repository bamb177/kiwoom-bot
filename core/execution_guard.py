from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import time

from core.types import Order


@dataclass
class GuardConfig:
    max_orders_per_minute: int = 10
    min_seconds_between_orders: int = 1


class ExecutionGuard:
    """주문 폭주/중복 방지용 가드"""

    def __init__(self, cfg: GuardConfig) -> None:
        self.cfg = cfg
        self._count_by_min: Dict[str, int] = {}
        self._last_order_ts: float = 0.0

    def begin_tick(self, ts_sec: str) -> None:
        minute_key = ts_sec[:16]
        if minute_key not in self._count_by_min:
            # 오래된 키 정리
            keys = sorted(self._count_by_min.keys())
            if len(keys) > 10:
                for k in keys[:-5]:
                    self._count_by_min.pop(k, None)

    def allow_order(self, ts_sec: str, order: Order) -> Tuple[bool, str]:
        self.begin_tick(ts_sec)

        # 1) 전역 주문 간 최소 간격
        now = time.time()
        if now - self._last_order_ts < float(self.cfg.min_seconds_between_orders):
            return False, "min_seconds_between_orders"

        # 2) 분당 주문 제한
        minute_key = ts_sec[:16]
        cnt = self._count_by_min.get(minute_key, 0)
        if cnt >= int(self.cfg.max_orders_per_minute):
            return False, "rate_limit_per_minute"

        return True, "ok"

    def record_order(self, ts_sec: str, symbol: str) -> None:
        minute_key = ts_sec[:16]
        self._count_by_min[minute_key] = self._count_by_min.get(minute_key, 0) + 1
        self._last_order_ts = time.time()
