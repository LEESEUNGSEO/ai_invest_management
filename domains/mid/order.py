from typing import Tuple, Optional
from core.state_manager import load_state, save_state
from core.notifier import send_kakao_message
from domains.mid.order_executor import (
    order_succeeded,
    order_result_message,
    submit_order_safely,
    reconcile_unfilled_orders,
)
from domains.mid.position_monitor import (
    monitor_and_defend_positions,
    evaluate_and_execute_watchlist,
)


def _verify_mid_preconditions(state: dict) -> Tuple[bool, Optional[str]]:
    """MID 단계 실행 전 안전 상태(거래 중단 스위치, 미확인 주문)를 검증합니다."""
    if state.get("trading_halt", False):
        reason = state.get("trading_halt_reason", "사유 미기록")
        return False, f"🛑 [자동매매 중단] 거래 중단 스위치가 켜져 있습니다.\n사유: {reason}"

    for o in state.get("active_orders", []):
        if isinstance(o, dict) and o.get("status") in ("SUBMITTING", "UNKNOWN"):
            reason = f"{o.get('ticker')} 미확인 주문(상태: {o.get('status')}) 존재. 계좌 확인 전 추가 주문 차단."
            return False, f"⚠️ [MID 주문 보류] {reason}"

    return True, None


def run_mid_phase(client, risk_engine):
    """[주문 도메인] MID: 장중 실시간 감시, 포지션 방어, 익절 및 조건 만족 시 매수 집행"""
    print("\n=== [DOMAIN: MID (주문/감시) 실시간 포트폴리오 감시 및 주문 실행] ===")
    state = load_state()

    # 1. 안전 선행 조건 확인
    is_safe, block_msg = _verify_mid_preconditions(state)
    if not is_safe and block_msg:
        print(f"[거래 차단] {block_msg}")
        try:
            send_kakao_message(block_msg)
        except Exception as e:
            print(f"[WARN] 알림 전송 실패: {e}")
        return

    # 2. 미체결 내역 동기화 및 기본 데이터 준비
    pending_symbols = reconcile_unfilled_orders(client, state)
    strategy_data = state.get("strategy", {})
    tracking_highs = state.get("tracking_highs", {})
    watchlist = state.get("watchlist", [])
    balance = client.get_account_balance()
    holdings = balance.get("holdings", [])
    available_cash = client.get_available_cash_usd()

    strat_map = {
        item.get("ticker", "").upper(): item
        for item in strategy_data.get("holdings_strategy", [])
        if isinstance(item, dict)
    }

    # 3. 기존 보유 종목 감시 (익절, 손절, 긴급AI, 트레일링스탑)
    actions_taken = monitor_and_defend_positions(
        client=client,
        state=state,
        holdings=holdings,
        strat_map=strat_map,
        tracking_highs=tracking_highs,
        pending_symbols=pending_symbols,
    )

    # 4. Watchlist 종목 매수 진입 검사
    holding_symbols = {h.get("ticker", "").upper() for h in holdings if float(h.get("qty", 0)) > 0}
    wl_actions, remaining_watchlist, available_cash = evaluate_and_execute_watchlist(
        client=client,
        risk_engine=risk_engine,
        state=state,
        watchlist=watchlist,
        available_cash=available_cash,
        pending_symbols=pending_symbols,
        holding_symbols=holding_symbols,
    )
    actions_taken.extend(wl_actions)

    # 5. 상태 영속화 및 알림 전송
    state["tracking_highs"] = tracking_highs
    state["watchlist"] = remaining_watchlist
    save_state(state)

    if actions_taken:
        send_kakao_message("⚡ [MID 실시간 대응 리포트]\n" + "\n".join(actions_taken))
    else:
        print("[MID Phase] 특이사항 없음 (모니터링 통과)")
