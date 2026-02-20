from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RiskState:
    kill_switch: bool = False
    defense_reduce_positions: bool = False
    allow_new_entries: bool = True


class RiskManager:
    def __init__(self, kill: float = -0.01, defense: float = -0.005) -> None:
        self.kill = kill
        self.defense = defense

    def update(self, day_pnl_ratio: float) -> RiskState:
        rs = RiskState()
        if day_pnl_ratio <= self.kill:
            rs.kill_switch = True
            rs.allow_new_entries = False
            return rs
        if day_pnl_ratio <= self.defense:
            rs.defense_reduce_positions = True
            rs.allow_new_entries = False
            return rs
        return rs
