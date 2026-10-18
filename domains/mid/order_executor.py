from datetime import datetime
from typing import Dict, Any, List, Set, Tuple, Optional
from core.state_manager import save_state


def order_succeeded(res: dict) -> bool:
    """KIS 주문 응답이 명시적으로 성공한 경우에만 True."""
    return isinstance(res, dict) and str(res.get("rt_cd", "")) == "0"


def order_result_message(res: dict) -> str:
    """주문 응답 결과 요약."""
    if not isinstance(res, dict):
        return "응답 형식 오류"
    code = str(res.get("rt_cd", ""))
    msg = str(res.get("msg1", "응답 메시지 없음"))
    return f"rt_cd={code or '없음'}, 메시지={msg[:200]}"


def _check_trading_halt(state: dict) -> None:
    """거래 중단 스위치가 켜져 있으면 예외를 발생시킵니다."""
    if state.get("trading_halt", False):
        raise RuntimeError("거래 중단 스위치(trading_halt)가 켜져 있어 주문을 차단했습니다.")


def _register_order_intent(
    state: dict,
    symbol: str,
    qty: int,
    price: float,
    order_type: str,
    exch_code: Optional[str]
) -> dict:
    """주문 전 의도를 state에 등록하고 저장합니다."""
    active_orders = state.setdefault("active_orders", [])
    if not isinstance(active_orders, list):
        active_orders = []
        state["active_orders"] = active_orders

    intent = {
        "ticker": str(symbol).upper(),
        "qty": int(qty),
        "price": float(price),
        "order_type": str(order_type).upper(),
        "exchange": exch_code or "NASD",
        "status": "SUBMITTING",
        "created_at": datetime.now().isoformat(),
        "odno": None,
    }
    active_orders.append(intent)
    save_state(state)
    return intent


def _halt_on_exception(state: dict, intent: dict, symbol: str, exc: Exception) -> None:
    """주문 통신 예외 시 상태를 UNKNOWN으로 변경하고 거래를 중단합니다."""
    intent["status"] = "UNKNOWN"
    state["trading_halt"] = True
    state["trading_halt_reason"] = f"{symbol} 주문 호출 중 예외 발생({type(exc).__name__}). 계좌 확인 필요."
    save_state(state)


def _halt_on_transport_error(state: dict, intent: dict, symbol: str, msg: str) -> None:
    """주문 통신 타임아웃/오류 시 상태를 UNKNOWN으로 변경하고 거래를 중단합니다."""
    intent["status"] = "UNKNOWN"
    state["trading_halt"] = True
    state["trading_halt_reason"] = f"{symbol} 주문 통신 타임아웃/오류({msg}). 중복 방지 위해 중단."
    save_state(state)


def submit_order_safely(
    client,
    state: dict,
    symbol: str,
    qty: int,
    price: float,
    order_type: str,
    exch_code: Optional[str] = None
) -> Tuple[bool, str, str]:
    """
    주문 전 의도를 state에 저장하고 KIS 응답(rt_cd 및 ODNO)을 검증합니다.
    반환: (성공여부: bool, 주문번호: str, 결과메시지: str)
    통신 예외 시 trading_halt=True 설정 후 예외 발생.
    """
    _check_trading_halt(state)
    intent = _register_order_intent(state, symbol, qty, price, order_type, exch_code)

    try:
        res = client.send_order(
            symbol=str(symbol).upper(),
            qty=int(qty),
            price=float(price),
            order_type=str(order_type).upper(),
            exch_code=exch_code,
        )
    except Exception as exc:
        _halt_on_exception(state, intent, symbol, exc)
        raise RuntimeError(state["trading_halt_reason"]) from exc

    if isinstance(res, dict) and res.get("_transport_error"):
        _halt_on_transport_error(state, intent, symbol, res.get("msg1", ""))
        raise RuntimeError(state["trading_halt_reason"])

    if not order_succeeded(res):
        active_orders = state.get("active_orders", [])
        if intent in active_orders:
            active_orders.remove(intent)
        save_state(state)
        msg = order_result_message(res)
        print(f"[주문 거절] {order_type} {symbol} {qty}주: {msg}")
        return False, "", msg

    output = res.get("output") if isinstance(res.get("output"), dict) else {}
    odno = str(output.get("ODNO") or output.get("odno") or res.get("ODNO") or "").strip()
    if not odno:
        intent["status"] = "UNKNOWN"
        state["trading_halt"] = True
        state["trading_halt_reason"] = f"{symbol} 주문 성공 응답이나 주문번호(ODNO) 누락. 계좌 대조 전 중단."
        save_state(state)
        raise RuntimeError(state["trading_halt_reason"])

    intent["odno"] = odno
    intent["status"] = "ACCEPTED"
    intent["exchange"] = res.get("_exchange") or exch_code or "NASD"
    intent["accepted_at"] = datetime.now().isoformat()
    save_state(state)

    print(f"[주문 접수 확인] {order_type} {symbol} {qty}주 (주문번호: {odno})")
    return True, odno, order_result_message(res)


def _merge_active_orders_with_live(
    active_orders: List[dict],
    live_unfilled: List[dict]
) -> Tuple[List[dict], Set[str]]:
    """로컬 활성 주문과 증권사 실시간 미체결 주문을 대조 병합합니다."""
    pending_symbols: Set[str] = set()
    live_by_odno = {str(u["odno"]): u for u in live_unfilled if u.get("odno")}
    synced_orders = []

    for o in active_orders:
        if not isinstance(o, dict):
            continue
        status = o.get("status")
        odno = str(o.get("odno") or "").strip()
        if status in ("SUBMITTING", "UNKNOWN"):
            synced_orders.append(o)
            if o.get("ticker"):
                pending_symbols.add(str(o["ticker"]).upper())
        elif odno and odno in live_by_odno:
            live_item = live_by_odno.pop(odno)
            o["qty"] = live_item.get("qty", o.get("qty", 1))
            o["exchange"] = live_item.get("exchange", o.get("exchange", "NASD"))
            synced_orders.append(o)
            pending_symbols.add(str(o.get("ticker", "")).upper())

    # 로컬에 없던 신규 미체결 건 동기화
    for odno, live_item in live_by_odno.items():
        synced_orders.append({
            "ticker": live_item["ticker"],
            "qty": live_item["qty"],
            "price": 0.0,
            "order_type": live_item.get("order_type", "UNKNOWN"),
            "exchange": live_item.get("exchange", "NASD"),
            "status": "ACCEPTED",
            "odno": odno,
            "created_at": datetime.now().isoformat(),
        })
        pending_symbols.add(live_item["ticker"].upper())

    return synced_orders, pending_symbols


def reconcile_unfilled_orders(client, state: dict) -> Set[str]:
    """KIS 실시간 미체결 내역과 state['active_orders']를 동기화하고 미체결 종목 집합을 반환합니다."""
    active_orders = state.get("active_orders", [])
    if not isinstance(active_orders, list):
        active_orders = []

    if not hasattr(client, "get_unfilled_orders"):
        return {
            str(o.get("ticker")).upper()
            for o in active_orders
            if isinstance(o, dict) and o.get("ticker")
        }

    try:
        live_unfilled = client.get_unfilled_orders()
        synced_orders, pending_symbols = _merge_active_orders_with_live(active_orders, live_unfilled)
        state["active_orders"] = synced_orders
        return pending_symbols
    except Exception as e:
        print(f"[WARN] 실시간 미체결 동기화 실패 (기존 상태 유지): {e}")
        return {
            str(o.get("ticker")).upper()
            for o in active_orders
            if isinstance(o, dict) and o.get("ticker")
        }
