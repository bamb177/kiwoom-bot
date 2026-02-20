from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, Optional, Any, List

from PyQt5.QtCore import QEventLoop
from PyQt5.QAxContainer import QAxWidget

from broker.base import BrokerBase
from core.types import Order, Side, OrderType, Position


class KiwoomBroker(BrokerBase):
    def __init__(self) -> None:
        super().__init__()

        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")

        self.ocx.OnEventConnect.connect(self._on_event_connect)
        self.ocx.OnReceiveTrData.connect(self._on_receive_tr_data)
        self.ocx.OnReceiveChejanData.connect(self._on_receive_chejan_data)
        self.ocx.OnReceiveRealData.connect(self._on_receive_real_data)

        # 조건검색 이벤트
        self.ocx.OnReceiveConditionVer.connect(self._on_receive_condition_ver)
        self.ocx.OnReceiveTrCondition.connect(self._on_receive_tr_condition)

        self._login_loop: Optional[QEventLoop] = None
        self._tr_loop: Optional[QEventLoop] = None
        self._cond_loop: Optional[QEventLoop] = None

        self._account_no: Optional[str] = None
        self._positions: Dict[str, Position] = {}
        self._day_pnl_ratio_forced: float = 0.0

        # on_tick callback (symbol, price, vol, ts)
        self.on_tick = None

        # open orders: order_no -> dict
        self._open_orders: Dict[str, Dict[str, Any]] = {}

        # TR result store
        self._tr_store: Dict[str, Any] = {}

        # conditions
        self._conditions: Dict[int, str] = {}
        self._last_condition_codes: List[str] = []

    # ------------------ login ------------------
    def connect_and_login(self) -> None:
        self.ocx.dynamicCall("CommConnect()")
        self._login_loop = QEventLoop()
        self._login_loop.exec_()

        acc_list = self.ocx.dynamicCall("GetLoginInfo(QString)", "ACCNO")
        accounts = [a for a in str(acc_list).split(";") if a.strip()]
        if not accounts:
            raise RuntimeError("로그인은 성공했지만 계좌번호(ACCNO)를 가져오지 못했습니다.")
        self._account_no = accounts[0]

    def get_account_no(self) -> str:
        if not self._account_no:
            raise RuntimeError("계좌가 설정되지 않았습니다. connect_and_login() 먼저 호출하세요.")
        return self._account_no

    # ------------------ positions / pnl ------------------
    def get_positions(self) -> Dict[str, Position]:
        return self._positions

    def set_day_pnl_ratio(self, pnl_ratio: float) -> None:
        try:
            self._day_pnl_ratio_forced = float(pnl_ratio)
        except Exception:
            self._day_pnl_ratio_forced = 0.0

    def get_day_pnl_ratio(self) -> float:
        return float(self._day_pnl_ratio_forced)

    # ------------------ realtime subscribe ------------------
    def subscribe_realtime(self, codes: list[str]) -> None:
        screen = "0202"
        code_list = ";".join(codes)
        fid_list = "10;15"  # 현재가, 거래량
        self.ocx.dynamicCall("SetRealReg(QString, QString, QString, QString)", screen, code_list, fid_list, "0")

    # ------------------ order ------------------
    def place_order(self, order: Order) -> None:
        acc = self.get_account_no()
        rqname = "AUTO_ORDER"
        screen = "0101"

        code = order.symbol.strip()
        if len(code) != 6:
            raise ValueError(f"Kiwoom requires 6-digit code. got: {code}")

        order_type = 1 if order.side == Side.BUY else 2  # 1:신규매수, 2:신규매도
        hoga = "03" if order.order_type == OrderType.MARKET else "00"
        price = 0 if order.order_type == OrderType.MARKET else int(order.price or 0)
        qty = int(order.qty)

        ret = self.ocx.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            [rqname, screen, acc, order_type, code, qty, price, hoga, ""],
        )
        if int(ret) != 0:
            raise RuntimeError(f"SendOrder failed ret={ret}")

    def get_open_orders(self) -> Dict[str, Dict[str, Any]]:
        dead = [ono for ono, o in self._open_orders.items() if int(o.get("unfilled", 0)) <= 0]
        for ono in dead:
            self._open_orders.pop(ono, None)
        return dict(self._open_orders)

    def _send_order_raw(
        self,
        rqname: str,
        order_type: int,
        code: str,
        qty: int,
        price: int,
        hoga: str,
        org_order_no: str = "",
    ) -> None:
        acc = self.get_account_no()
        screen = "0101"
        ret = self.ocx.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            [rqname, screen, acc, int(order_type), code, int(qty), int(price), hoga, org_order_no],
        )
        if int(ret) != 0:
            raise RuntimeError(f"SendOrder failed ret={ret}")

    def cancel_order(self, order_no: str, code: str, orig_side: Side, qty: int) -> None:
        order_type = 3 if orig_side == Side.BUY else 4  # 매수취소 / 매도취소
        self._send_order_raw("CANCEL", order_type, code, qty, 0, "00", org_order_no=order_no)

    def modify_order_to_market(self, order_no: str, code: str, orig_side: Side, qty: int) -> None:
        order_type = 5 if orig_side == Side.BUY else 6  # 매수정정 / 매도정정
        self._send_order_raw("MODIFY_MKT", order_type, code, qty, 0, "03", org_order_no=order_no)

    # ------------------ TR helpers ------------------
    def _set_input(self, key: str, value: str) -> None:
        self.ocx.dynamicCall("SetInputValue(QString, QString)", key, value)

    def _comm_rq_data(self, rqname: str, trcode: str, prev_next: int, screen: str) -> None:
        self._tr_loop = QEventLoop()
        self.ocx.dynamicCall("CommRqData(QString, QString, int, QString)", rqname, trcode, prev_next, screen)
        self._tr_loop.exec_()

    def _get_comm_data(self, trcode: str, rqname: str, idx: int, item: str) -> str:
        v = self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, idx, item)
        return str(v).strip()

    def _get_repeat_cnt(self, trcode: str, rqname: str) -> int:
        try:
            return int(self.ocx.dynamicCall("GetRepeatCnt(QString, QString)", trcode, rqname))
        except Exception:
            return 0

    # ------------------ opt10075 미체결요청 (2중 검증) ------------------
    def sync_open_orders_tr(self) -> Dict[str, Dict[str, Any]]:
        acc = self.get_account_no()

        rqname = "OPT10075_REQ"
        trcode = "opt10075"
        screen = "5075"

        self._tr_store.pop(rqname, None)

        self._set_input("계좌번호", acc)
        self._set_input("전체종목구분", "0")
        self._set_input("매매구분", "0")
        self._set_input("체결구분", "1")  # 미체결
        self._comm_rq_data(rqname, trcode, 0, screen)

        rows: List[Dict[str, Any]] = self._tr_store.get(rqname, [])
        new_open: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            ono = r.get("order_no", "")
            if not ono:
                continue
            unfilled = int(r.get("unfilled", 0))
            if unfilled <= 0:
                continue
            new_open[ono] = {
                "code": r.get("code", ""),
                "side": r.get("side", None),
                "status": r.get("status", ""),
                "unfilled": unfilled,
                "order_qty": int(r.get("order_qty", 0)),
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "src": "TR",
            }

        if new_open:
            self._open_orders = new_open
        else:
            self._open_orders = {k: v for k, v in self._open_orders.items() if int(v.get("unfilled", 0)) > 0}
        return dict(self._open_orders)

    # ------------------ 조건검색 ------------------
    def load_conditions(self) -> Dict[int, str]:
        self._conditions = {}
        ok = int(self.ocx.dynamicCall("GetConditionLoad()"))
        if ok != 1:
            raise RuntimeError("GetConditionLoad() 실패. HTS 조건식 저장/로그인 상태 확인 필요")
        self._cond_loop = QEventLoop()
        self._cond_loop.exec_()
        return dict(self._conditions)

    def run_condition(self, condition_name: str, screen: str = "0900") -> List[str]:
        if not self._conditions:
            self.load_conditions()

        cond_index = None
        for idx, nm in self._conditions.items():
            if nm == condition_name:
                cond_index = idx
                break
        if cond_index is None:
            raise RuntimeError(f"조건식 '{condition_name}' 을(를) 찾지 못함. HTS 조건식 이름 확인 필요")

        self._last_condition_codes = []

        ret = int(self.ocx.dynamicCall(
            "SendCondition(QString, QString, int, int)",
            screen, condition_name, int(cond_index), 0
        ))
        if ret != 1:
            raise RuntimeError("SendCondition() 실패")

        self._cond_loop = QEventLoop()
        self._cond_loop.exec_()

        codes = [c.replace("A", "").strip() for c in self._last_condition_codes if c.strip()]
        seen = set()
        out = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    # ------------------ events ------------------
    def _on_event_connect(self, err_code: int) -> None:
        if self._login_loop:
            self._login_loop.exit()
        if int(err_code) != 0:
            raise RuntimeError(f"Kiwoom login failed err_code={err_code}")

    def _on_receive_tr_data(self, screen_no, rqname, trcode, recordname, prev_next, data_len, err_code, msg1, msg2):
        if str(rqname).strip() == "OPT10075_REQ" and str(trcode).strip() == "opt10075":
            out: List[Dict[str, Any]] = []
            cnt = self._get_repeat_cnt(trcode, rqname)

            for i in range(cnt):
                order_no = self._get_comm_data(trcode, rqname, i, "주문번호")
                code = self._get_comm_data(trcode, rqname, i, "종목코드").replace("A", "").strip()
                status = self._get_comm_data(trcode, rqname, i, "주문상태")
                gubun = self._get_comm_data(trcode, rqname, i, "주문구분")
                unfilled = self._get_comm_data(trcode, rqname, i, "미체결수량")
                oqty = self._get_comm_data(trcode, rqname, i, "주문수량")

                def _to_int(x: str) -> int:
                    try:
                        return int(str(x).strip())
                    except Exception:
                        return 0

                side: Optional[Side] = None
                if "매수" in gubun:
                    side = Side.BUY
                elif "매도" in gubun:
                    side = Side.SELL

                out.append({
                    "order_no": order_no.strip(),
                    "code": code,
                    "status": status.strip(),
                    "side": side,
                    "unfilled": abs(_to_int(unfilled)),
                    "order_qty": abs(_to_int(oqty)),
                })

            self._tr_store[rqname] = out

        if self._tr_loop:
            self._tr_loop.exit()

    def _on_receive_condition_ver(self, ret, msg):
        raw = self.ocx.dynamicCall("GetConditionNameList()")
        items = [x for x in str(raw).split(";") if x.strip()]
        conds = {}
        for it in items:
            try:
                idx_s, name = it.split("^")
                conds[int(idx_s)] = name
            except Exception:
                continue
        self._conditions = conds
        if self._cond_loop:
            self._cond_loop.exit()

    def _on_receive_tr_condition(self, screen_no, code_list, condition_name, condition_index, next):
        codes = [c for c in str(code_list).split(";") if c.strip()]
        self._last_condition_codes = codes
        if self._cond_loop:
            self._cond_loop.exit()

    def _on_receive_chejan_data(self, gubun, item_cnt, fid_list):
        def _to_int_safe(x: str) -> int:
            try:
                return int(str(x).strip())
            except Exception:
                return 0

        code = self.ocx.dynamicCall("GetChejanData(int)", 9001).strip().replace("A", "").strip()
        if not code:
            return

        order_no = self.ocx.dynamicCall("GetChejanData(int)", 9203).strip()
        order_status = self.ocx.dynamicCall("GetChejanData(int)", 913).strip()
        order_gubun = self.ocx.dynamicCall("GetChejanData(int)", 905).strip()
        unfilled_raw = self.ocx.dynamicCall("GetChejanData(int)", 902).strip()
        order_qty_raw = self.ocx.dynamicCall("GetChejanData(int)", 900).strip()

        unfilled = abs(_to_int_safe(unfilled_raw))
        oqty = abs(_to_int_safe(order_qty_raw))

        side: Optional[Side] = None
        if "매수" in order_gubun:
            side = Side.BUY
        elif "매도" in order_gubun:
            side = Side.SELL

        if order_no:
            if unfilled > 0:
                self._open_orders[order_no] = {
                    "code": code,
                    "side": side,
                    "status": order_status,
                    "unfilled": unfilled,
                    "order_qty": oqty,
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "src": "CHEJAN",
                }
            else:
                self._open_orders.pop(order_no, None)

        holding_qty = abs(_to_int_safe(self.ocx.dynamicCall("GetChejanData(int)", 930).strip()))
        avg_price = abs(_to_int_safe(self.ocx.dynamicCall("GetChejanData(int)", 931).strip()))
        cur_price = abs(_to_int_safe(self.ocx.dynamicCall("GetChejanData(int)", 10).strip()))

        pos = self._positions.get(code) or Position(symbol=code)
        if holding_qty > 0:
            pos.qty = holding_qty
        if avg_price > 0:
            pos.avg_price = float(avg_price)
        if cur_price > 0:
            pos.last_price = float(cur_price)

        if pos.qty <= 0:
            pos.qty = 0
            pos.avg_price = 0.0

        self._positions[code] = pos

    def _on_receive_real_data(self, code, real_type, real_data):
        cur = self.ocx.dynamicCall("GetCommRealData(QString, int)", code, 10)
        vol = self.ocx.dynamicCall("GetCommRealData(QString, int)", code, 15)
        if not str(cur).strip():
            return

        try:
            price = abs(int(str(cur).strip()))
        except Exception:
            return

        try:
            volume = abs(int(str(vol).strip())) if str(vol).strip() else 0
        except Exception:
            volume = 0

        pos = self._positions.get(code) or Position(symbol=code)
        pos.last_price = float(price)
        self._positions[code] = pos

        if self.on_price:
            self.on_price(code, float(price), time.strftime("%H:%M:%S"))

        if getattr(self, "on_tick", None):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.on_tick(code, float(price), int(volume), ts)
