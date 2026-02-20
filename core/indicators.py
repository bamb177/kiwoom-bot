from __future__ import annotations
from typing import List, Dict

def ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e

def rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def pct_change(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a - b) / b

def features_from_bars(bars: List[dict]) -> Dict[str, float]:
    if len(bars) < 20:
        return {}
    closes = [float(x["close"]) for x in bars]
    vols = [float(x["volume"]) for x in bars]
    f: Dict[str, float] = {}
    f["ret_1"] = pct_change(closes[-1], closes[-2])
    f["ret_5"] = pct_change(closes[-1], closes[-6]) if len(closes) >= 6 else 0.0
    f["ema_5"] = ema(closes[-20:], 5)
    f["ema_20"] = ema(closes[-40:], 20) if len(closes) >= 40 else ema(closes, 20)
    f["rsi_14"] = rsi(closes, 14)
    avg5 = (sum(vols[-6:-1]) / 5) if len(vols) >= 6 else (sum(vols) / len(vols))
    f["vol_ratio"] = (vols[-1] / avg5) if avg5 > 0 else 1.0
    return f
