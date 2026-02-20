from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from broker.kiwoom import KiwoomBroker
from core.execution_guard import ExecutionGuard, GuardConfig
from core.risk_manager import RiskManager
from core.types import Side
from core.settings import ensure_dirs, load_config, BotConfig
from core.logger import setup_logger, log_jsonl
from core.state_store import load_state, save_state
from core.universe import UniverseManager
from core.scoring import ScoreBoard
from core.strategy import SimpleScoreStrategy
from core.order_manager import OrderManager
from core.pnl_tracker import PnLTracker
from data.realtime_bar_builder import RealtimeBarBuilder, Bar


def _hm() -> str:
    return datetime.now().strftime("%H:%M")

def _hms() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PaperBotApp:
    def __init__(self, cfg: BotConfig):
        ensure_dirs()
        self.cfg = cfg
        self.log = setup_logger("paper-bot")

        self.broker = KiwoomBroker()

        # trackers
        self.pnl = PnLTracker(self.log)
        self.sb = ScoreBoard()
        self.strategy = SimpleScoreStrategy(self.log, cfg, self.sb, self.pnl)

        # guards
        gcfg = GuardConfig(
            max_orders_per_minute=int(cfg.max_orders_per_minute),
            min_seconds_between_orders=int(cfg.min_seconds_between_orders),
        )
        self.guard = ExecutionGuard(gcfg)
        self.order_mgr = OrderManager(self.log, self.broker, self.guard)
        self.risk = RiskManager(kill=-0.01, defense=-0.005)

        # universe
        self.universe = UniverseManager(self.log, self.broker, cfg)

        # bars
        self.bars_1m: Dict[str, List[dict]] = {}
        self.last_tick_ts: Dict[str, float] = {}

        self.bar_builder = RealtimeBarBuilder(self.on_bar)

        # open orders snapshot
        self.open_orders: Dict[str, dict] = {}

        # restore
        self._restore_state()

        # wire callbacks
        self.broker.on_tick = self.on_tick
        self.broker.on_price = self.on_price
        self.broker.on_fill = self.on_fill  # currently broker calls (code, filled_qty, filled_price) for 체결

        self._setup_timers()

    # --------- state ---------
    def _restore_state(self):
        st = load_state()
        if not st:
            return
        try:
            self.universe.state.all_symbols = st.get("universe_all", []) or []
            self.universe.state.realtime_symbols = st.get("universe_rt", []) or []
            positions = st.get("positions", {}) or {}
            for sym, p in positions.items():
                try:
                    from core.pnl_tracker import PositionLite
                    self.pnl.pos[sym] = PositionLite(
                        qty=int(p.get("qty", 0)),
                        avg_price=float(p.get("avg_price", 0.0)),
                        last_price=float(p.get("last_price", 0.0)),
                    )
                except Exception:
                    continue
            self.open_orders = st.get("open_orders", {}) or {}
            self.log.info(f"[STATE] restored pos={len(positions)} rt={len(self.universe.state.realtime_symbols)}")
        except Exception:
            return

    def _snapshot_state(self):
        positions = {
            s: {"qty": p.qty, "avg_price": p.avg_price, "last_price": p.last_price}
            for s, p in self.pnl.pos.items()
            if p.qty > 0
        }
        save_state({
            "universe_all": self.universe.state.all_symbols,
            "universe_rt": self.universe.state.realtime_symbols,
            "positions": positions,
            "open_orders": self.open_orders,
        })

    # --------- callbacks ---------
    def on_price(self, code: str, price: float, ts_hms: str) -> None:
        # update pnl last price
        self.pnl.on_price(code, price)

    def on_tick(self, code: str, price: float, volume: int, ts: str) -> None:
        # ts is "YYYY-MM-DD HH:MM:SS"
        self.last_tick_ts[code] = time.time()
        self.bar_builder.on_tick(code, price, volume, ts)

    def on_fill(self, code: str, filled_qty: int, filled_price: float) -> None:
        # BrokerBase.on_fill signature: (symbol, qty, price) - side는 chejan 기반으로 추가 로깅 권장
        # 여기서는 open_orders/positions는 broker가 유지하고 있으니, pnl만 업데이트는 체결 side를 chejan에서 받는게 정확.
        # 임시로: filled_qty>0이면 BUY로 가정하지 않음. (Chejan 쪽 로그는 broker 내부에서 이미 가능)
        pass

    def on_bar(self, b: Bar) -> None:
        arr = self.bars_1m.setdefault(b.symbol, [])
        arr.append({
            "ts": b.ts,
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": int(b.volume),
        })
        # keep last 200
        if len(arr) > 200:
            del arr[:-200]

        # score update on bar close
        self.sb.update(b.symbol, arr)

    # --------- timers ---------
    def _setup_timers(self):
        # universe refresh (minutes)
        self.t_universe = QTimer()
        self.t_universe.timeout.connect(self._on_universe_refresh)
        self.t_universe.start(int(self.cfg.universe_refresh_min) * 60 * 1000)

        # strategy tick
        self.t_strategy = QTimer()
        self.t_strategy.timeout.connect(self._on_strategy_tick)
        self.t_strategy.start(int(self.cfg.score_refresh_sec) * 1000)

        # open orders TR sync
        self.t_trsync = QTimer()
        self.t_trsync.timeout.connect(self._on_tr_sync)
        self.t_trsync.start(int(self.cfg.tr_sync_sec) * 1000)

        # status snapshot
        self.t_status = QTimer()
        self.t_status.timeout.connect(self._on_status)
        self.t_status.start(int(self.cfg.status_sec) * 1000)

        # keepalive realtime re-register
        self.t_keepalive = QTimer()
        self.t_keepalive.timeout.connect(self._on_rt_keepalive)
        self.t_keepalive.start(int(self.cfg.rt_keepalive_min) * 60 * 1000)

        # bar flush (1s)
        self.t_flush = QTimer()
        self.t_flush.timeout.connect(self._on_flush)
        self.t_flush.start(1000)

    # --------- operations ---------
    def start(self):
        self.log.info("[BOOT] connecting/login...")
        self.broker.connect_and_login()
        acc = self.broker.get_account_no()
        self.log.info(f"[BOOT] login ok account={acc}")

        # initial universe & realtime
        self._on_universe_refresh()

    def _on_universe_refresh(self):
        try:
            self.universe.refresh_from_condition()
            self.universe.pick_realtime_top_n(scorer=self.sb)
            self.universe.apply_realtime_registry()
        except Exception as e:
            self.log.exception(f"[UNIVERSE] refresh failed: {e}")

    def _on_rt_keepalive(self):
        # simply re-apply current realtime symbols
        try:
            self.universe.apply_realtime_registry()
            self.log.info("[RT_KEEPALIVE] re-registered realtime")
        except Exception as e:
            self.log.exception(f"[RT_KEEPALIVE] failed: {e}")

    def _on_tr_sync(self):
        try:
            self.open_orders = self.broker.sync_open_orders_tr()
            log_jsonl(Path("logs/open_orders.jsonl"), {"count": len(self.open_orders)})
        except Exception as e:
            self.log.exception(f"[TR_SYNC] opt10075 failed: {e}")

    def _within_force_close(self) -> bool:
        hm = _hm()
        return (self.cfg.force_close_start <= hm <= self.cfg.force_close_end)

    def _after_entry_cutoff(self) -> bool:
        return _hm() >= self.cfg.entry_cutoff

    def _on_strategy_tick(self):
        # force close window: let existing force close logic outside
        if self._within_force_close():
            self._force_close_step()
            return

        # risk state from broker day pnl (forced externally or 0)
        rs = self.risk.update(self.broker.get_day_pnl_ratio())
        if rs.kill_switch:
            self.log.warning("[RISK] kill_switch ON: no new entries")
        allow_new = rs.allow_new_entries and (not self._after_entry_cutoff())

        # exits first
        for sym in list(self.pnl.pos.keys()):
            sig = self.strategy.decide_exit(sym)
            if sig:
                self._send_signal(sig)

        if not allow_new:
            return

        # candidate symbols (top scores among realtime registered)
        syms = list(self.universe.state.realtime_symbols)
        syms.sort(key=lambda s: float(self.sb.get(s)), reverse=True)

        # enforce max positions
        cur_positions = sum(1 for p in self.pnl.pos.values() if p.qty > 0)
        can_hold_more = cur_positions < int(self.cfg.max_positions)

        for sym in syms[:10]:
            last = 0.0
            p = self.broker.get_positions().get(sym)
            if p and p.last_price > 0:
                last = float(p.last_price)
            else:
                # fallback: from pnl tracker last
                pl = self.pnl.pos.get(sym)
                if pl:
                    last = float(pl.last_price)

            sig = self.strategy.decide_entry(sym, can_hold_more=can_hold_more, last_price=last)
            if sig:
                if self._send_signal(sig):
                    # update can_hold_more
                    cur_positions += 1
                    can_hold_more = cur_positions < int(self.cfg.max_positions)

    def _send_signal(self, sig) -> bool:
        if self.cfg.dry_run:
            self.log.info(f"[DRY_RUN] {sig.side.value} {sig.symbol} x{sig.qty} reason={sig.reason}")
            return False
        ok = self.order_mgr.send(self.strategy.to_order(sig), reason=sig.reason, cooldown_sec=int(self.cfg.per_symbol_cooldown_sec))
        return ok

    def _force_close_step(self):
        # 1) 미체결 조회 + 정정/취소 + 2) 보유 포지션 전량 매도
        try:
            oo = self.broker.get_open_orders()
            # sync broker positions -> pnl tracker (chejan 기반 avg/qty 반영)
            try:
                from core.pnl_tracker import PositionLite
                for s, p in pos.items():
                    if int(p.qty) > 0:
                        self.pnl.pos[s] = PositionLite(qty=int(p.qty), avg_price=float(p.avg_price), last_price=float(p.last_price))
                    else:
                        # remove empty
                        if s in self.pnl.pos:
                            self.pnl.pos.pop(s, None)
            except Exception:
                pass
            if oo:
                for order_no, o in oo.items():
                    unfilled = int(o.get("unfilled", 0))
                    if unfilled <= 0:
                        continue
                    code = str(o.get("code", "")).strip()
                    # 정정: 시장가로 전환 시도, 실패하면 취소
                    try:
                        self.broker.modify_order_to_market(order_no, code, unfilled)
                        self.log.info(f"[FORCE] modify_to_market order_no={order_no} code={code} unfilled={unfilled}")
                    except Exception:
                        try:
                            self.broker.cancel_order(order_no, code, unfilled)
                            self.log.info(f"[FORCE] cancel order_no={order_no} code={code} unfilled={unfilled}")
                        except Exception as e2:
                            self.log.exception(f"[FORCE] cancel failed order_no={order_no} err={e2}")

            # positions sell
            pos = self.broker.get_positions()
            for code, p in pos.items():
                if int(p.qty) > 0:
                    from core.types import Order, OrderType
                    o = Order(symbol=code, side=Side.SELL, qty=int(p.qty), order_type=OrderType.MARKET, price=None)
                    if not self.cfg.dry_run:
                        try:
                            self.broker.place_order(o)
                            self.log.info(f"[FORCE] SELL {code} x{p.qty}")
                        except Exception as e:
                            self.log.exception(f"[FORCE] SELL failed {code} err={e}")
        except Exception as e:
            self.log.exception(f"[FORCE] step failed: {e}")

    def _on_flush(self):
        # flush bars to close minutes
        self.bar_builder.flush(_now_ts())

    def _on_status(self):
        try:
            pos = self.broker.get_positions()
            oo = self.broker.get_open_orders()
            # sync broker positions -> pnl tracker (chejan 기반 avg/qty 반영)
            try:
                from core.pnl_tracker import PositionLite
                for s, p in pos.items():
                    if int(p.qty) > 0:
                        self.pnl.pos[s] = PositionLite(qty=int(p.qty), avg_price=float(p.avg_price), last_price=float(p.last_price))
                    else:
                        # remove empty
                        if s in self.pnl.pos:
                            self.pnl.pos.pop(s, None)
            except Exception:
                pass
            self.open_orders = oo
            self.log.info(f"[STATUS] t={_hms()} rt={len(self.universe.state.realtime_symbols)} pos={sum(1 for p in pos.values() if p.qty>0)} oo={len(oo)}")
            # snapshot logs
            log_jsonl(Path("logs/status.jsonl"), {
                "rt_n": len(self.universe.state.realtime_symbols),
                "pos_n": sum(1 for p in pos.values() if p.qty>0),
                "oo_n": len(oo),
            })
            self.pnl.snapshot_log()
            self._snapshot_state()
        except Exception as e:
            self.log.exception(f"[STATUS] failed: {e}")


def main():
    cfg = load_config("config.json")
    app = QApplication([])
    bot = PaperBotApp(cfg)
    bot.start()
    app.exec_()


if __name__ == "__main__":
    main()
