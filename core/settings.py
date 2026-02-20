from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

@dataclass(frozen=True)
class BotConfig:
    # universe
    universe_condition: str = "TV_TOP200"
    universe_refresh_min: int = 10
    realtime_top_n: int = 80

    # trading
    max_positions: int = 2
    entry_krw: int = 200_000
    entry_cutoff: str = "15:20"          # 신규 진입 컷오프(시:분)

    # ops
    dry_run: bool = False
    force_close_start: str = "15:20"
    force_close_end: str = "15:25"
    force_loop_sec: int = 3
    tr_sync_sec: int = 30
    status_sec: int = 30
    rt_keepalive_min: int = 5

    # execution guard
    max_orders_per_minute: int = 10
    min_seconds_between_orders: int = 1
    per_symbol_cooldown_sec: int = 3

    # strategy
    score_refresh_sec: int = 5
    score_entry_threshold: float = 30.0
    stop_loss_bp: int = 80        # 0.8%
    take_profit_bp: int = 150     # 1.5%

CFG = BotConfig()

def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_config(path: str | Path) -> BotConfig:
    p = Path(path)
    if not p.exists():
        return CFG
    obj = json.loads(p.read_text(encoding="utf-8"))
    # merge into defaults
    data = {**CFG.__dict__, **obj}
    return BotConfig(**data)
