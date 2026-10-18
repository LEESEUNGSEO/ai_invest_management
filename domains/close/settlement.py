from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from core.state_manager import save_state
from core.kis_client import get_overseas_price
from domains.mid.order_executor import (
    reconcile_unfilled_orders,
    order_succeeded,
    order_result_message,
)


def _cancel_single_order(client, order: dict) -> Tuple[bool, str, Optional[dict]]:
    """단일 활성 주문에 대해 증권사 취소 API를 호출하고 결과를 반환합니다."""
    odno = order.get("odno")
    tk = order.get("ticker")
    qty = int(float(order.get("qty") or 0))
    exch = order.get("exchange")

    if not odno or not tk or qty <= 0:
        return False, "", None

    if not hasattr(client, "cancel_order"):
        return False, f"{tk}({odno})", order

    try:
        res = client.cancel_order(order_no=odno, symbol=tk, qty=qty, exch_code=exch)
        if order_succeeded(res):
            return True, "", None
        msg = order_result_message(res)
        print(f"[WARN] 미체결 취소 실패 ({tk}, 주문번호:{odno}): {msg}")
        return False, f"{tk}({odno})", order
    except Exception as e:
        print(f"[WARN] 주문 취소 통신 예외 ({odno}): {e}")
        return False, f"{tk}({odno})", order


def cancel_unfilled_orders(client, state: dict) -> Tuple[int, List[str]]:
    """
    실시간 미체결 내역을 동기화한 후, 남아있는 미체결 주문을 일괄 취소합니다.
    반환: (취소성공건수: int, 취소실패종목/주문번호목록: List[str])
    """
    reconcile_unfilled_orders(client, state)
    active_orders = state.get("active_orders", [])
    canceled_cnt = 0
    cancel_failures = []
    remaining_orders = []

    for order in active_orders:
        if not isinstance(order, dict):
            continue
        ok, failure_tag, remaining = _cancel_single_order(client, order)
        if ok:
            canceled_cnt += 1
        else:
            if failure_tag:
                cancel_failures.append(failure_tag)
            if remaining:
                remaining_orders.append(remaining)

    state["active_orders"] = remaining_orders
    save_state(state)
    return canceled_cnt, cancel_failures


def _format_single_holding_line(h: dict) -> str:
    """단일 보유 종목의 평단가, 현재가, 수익률을 포맷팅합니다."""
    tk = h.get("ticker", "")
    q = h.get("qty", 0)
    avg_p = float(h.get("avg_price", 0.0))
    cur_p = float(h.get("current_price", 0.0))
    if cur_p <= 0 and tk:
        cur_p = get_overseas_price(tk)
    profit_rate = ((cur_p - avg_p) / avg_p * 100) if avg_p > 0 else 0.0
    return f"• {tk}: {q}주 (평단: ${avg_p:.2f} / 현재: ${cur_p:.2f} / 수익률: {profit_rate:+.2f}%)"


def build_daily_settlement_report(
    available_cash: float,
    holdings: List[Dict[str, Any]],
    canceled_cnt: int,
    cancel_failures: List[str]
) -> str:
    """장 마감 일일 결산 보고서 문자열을 생성합니다."""
    report = [
        "🏁 [AI 퀀트 장 마감 일일 결산 보고서]",
        f"• 결산 일자: {datetime.now().strftime('%Y-%m-%d')}",
        f"• 최종 가용 예수금: ${available_cash:.2f}",
        f"• 당일 미체결 취소 완료: {canceled_cnt}건" + (f" (확인필요: {', '.join(cancel_failures)})" if cancel_failures else ""),
        "=" * 25
    ]

    if holdings:
        report.append("📦 [현재 최종 보유 잔고]")
        for h in holdings:
            report.append(_format_single_holding_line(h))
    else:
        report.append("📦 [현재 보유 잔고]: 전량 현금 보유 (관망 유지)")

    report.append("-" * 25)
    report.append("내일 개장 전 정규 분석 리포트로 다시 뵙겠습니다.")
    return "\n".join(report)
