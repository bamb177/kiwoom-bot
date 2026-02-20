from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict

from core.types import Order, Position


class BrokerBase(ABC):
    def __init__(self) -> None:
        # optional callbacks
        self.on_price: Optional[Callable[[str, float, str], None]] = None
        self.on_fill: Optional[Callable[[str, int, float], None]] = None

    @abstractmethod
    def connect_and_login(self) -> None:
        ...

    @abstractmethod
    def get_account_no(self) -> str:
        ...

    @abstractmethod
    def place_order(self, order: Order) -> None:
        ...

    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        ...
