from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from core.settings import BotConfig

@dataclass
class UniverseState:
    all_symbols: List[str] = field(default_factory=list)
    realtime_symbols: List[str] = field(default_factory=list)
    last_refresh_ts: float = 0.0

class UniverseManager:
    def __init__(self, logger, broker, cfg: BotConfig) -> None:
        self.log = logger
        self.broker = broker
        self.cfg = cfg
        self.state = UniverseState()
        self._inflight = False

    def refresh_from_condition(self) -> None:
        if self._inflight:
            return
        self._inflight = True
        try:
            codes = self.broker.run_condition(self.cfg.universe_condition)
            self.state.all_symbols = codes
            self.state.last_refresh_ts = __import__("time").time()
            self.log.info(f"[UNIVERSE] condition={self.cfg.universe_condition} size={len(codes)}")
        finally:
            self._inflight = False

    def pick_realtime_top_n(self, scorer: Optional[object] = None) -> List[str]:
        base = list(self.state.all_symbols)
        if scorer is not None:
            base.sort(key=lambda s: float(scorer.get(s)), reverse=True)
        n = int(self.cfg.realtime_top_n)
        self.state.realtime_symbols = base[:n]
        return self.state.realtime_symbols

    def apply_realtime_registry(self) -> None:
        self.broker.subscribe_realtime(self.state.realtime_symbols)
        self.log.info(f"[UNIVERSE] realtime registered n={len(self.state.realtime_symbols)}")
