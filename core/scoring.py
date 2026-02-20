from __future__ import annotations
from typing import Dict, List
from core.indicators import features_from_bars

class ScoreBoard:
    def __init__(self) -> None:
        self.scores: Dict[str, float] = {}

    def get(self, symbol: str) -> float:
        return self.scores.get(symbol, -1e9)

    def update(self, symbol: str, bars: List[dict]) -> None:
        f = features_from_bars(bars)
        if not f:
            return

        score = 0.0
        score += 1000.0 * f["ret_5"]
        score += 200.0 * (f["vol_ratio"] - 1.0)
        score += 100.0 * (1.0 if f["ema_5"] > f["ema_20"] else -1.0)

        if f["rsi_14"] >= 80:
            score -= 50.0
        elif f["rsi_14"] <= 30:
            score += 20.0

        self.scores[symbol] = score
