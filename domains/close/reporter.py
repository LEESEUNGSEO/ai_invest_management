from core.state_manager import load_state
from core.notifier import send_kakao_message
from domains.close.settlement import (
    cancel_unfilled_orders,
    build_daily_settlement_report,
)


def run_close_phase(client, risk_engine):
    """[보고 도메인] CLOSE: 장 마감 결산, 미체결 정리 및 일일 수익률 종합 보고"""
    print("\n=== [DOMAIN: CLOSE (보고/정산) 장 마감 결산 및 리포트 발송] ===")
    state = load_state()

    # 1. 실시간 미체결 내역 동기화 후 전량 취소
    canceled_cnt, cancel_failures = cancel_unfilled_orders(client, state)

    # 2. 계좌 상태 조회
    available_cash = client.get_available_cash_usd()
    balance = client.get_account_balance()
    holdings = balance.get("holdings", [])

    # 3. 결산 보고서 작성 및 발송
    report_text = build_daily_settlement_report(
        available_cash=available_cash,
        holdings=holdings,
        canceled_cnt=canceled_cnt,
        cancel_failures=cancel_failures,
    )

    send_kakao_message(report_text)
    print("[CLOSE Phase 완료] 일일 결산 완료 및 최종 보고서 전송 완료.")
