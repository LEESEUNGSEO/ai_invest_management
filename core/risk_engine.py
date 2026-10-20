import os
from typing import Dict, Any, Tuple

# 1. 안전 계수 (미수/신용 차입 원천 차단: 가용 현금 100% 전액 활용)
CASH_SAFETY_RATIO = float(os.getenv("CASH_SAFETY_RATIO", "1.00"))

# 2. 1회 주문 당 가능 현금 대비 최대 투자 비중 (기본 20% = 0.20)
DEFAULT_MAX_ALLOCATION_RATIO = float(os.getenv("MAX_TRADE_RATIO", "0.20"))

# 3. 실시간 시세 대비 Gemini 제안가의 허용 오차 (슬리피지/환각 방어: 3% 이내)
MAX_PRICE_DEVIATION = float(os.getenv("MAX_PRICE_DEVIATION", "0.03"))

# 4. 예상 매매 수수료 및 제비용 버퍼 (한투 해외주식 기본 수수료 및 SEC fee 약 0.1%)
ESTIMATED_FEE_RATE = 0.001


class RiskEngine:
    @staticmethod
    def validate_buy_order(
        symbol: str,
        proposed_price: float,
        current_market_price: float,
        available_cash_usd: float,
        allocation_ratio: float = DEFAULT_MAX_ALLOCATION_RATIO
    ) -> Tuple[bool, int, str]:
        """
        가용 현금(100%) 기반으로 미수 차입 없이 안전 주문 가능한 수량을 결정론적으로 계산합니다.
        절대 원칙: 주문금액 + 수수료가 계좌 가용 현금을 1센트라도 초과할 수 없음 (미수 발생 원천 차단)
        반환: (통과 여부, 승인 수량, 사유 메시지)
        """
        # 1. 가격 적합성 검증
        if proposed_price <= 0 or current_market_price <= 0:
            return False, 0, f"비정상적 가격: 주문가={proposed_price}, 현재가={current_market_price}"

        # 2. 실시간 시세 대비 괴리율 체크 (Gemini 환각 방어)
        deviation = abs(proposed_price - current_market_price) / current_market_price
        if deviation > MAX_PRICE_DEVIATION:
            return False, 0, f"시세 괴리율 초과 ({deviation*100:.2f}% > {MAX_PRICE_DEVIATION*100}%): 주문 거절"

        # 3. 예수 현금 풀 (100% 가용 현금 활용)
        safe_cash_pool = available_cash_usd * CASH_SAFETY_RATIO
        if safe_cash_pool <= 0:
            return False, 0, f"가용 외화 현금 부족: ${available_cash_usd:.2f}"

        # 4. 종목별 할당 비중 적용 (기본 20%)
        allocated_budget = safe_cash_pool * allocation_ratio
        
        # 소액 초기 단계 예외 처리: 할당 예산(20%)이 1주 가격보다 작지만, 전체 현금 범위 안에는 들어오는 경우 (최대 1주 한정 허용)
        if allocated_budget < proposed_price and proposed_price <= safe_cash_pool:
            effective_budget = safe_cash_pool
            max_allowed_qty = 1
        else:
            effective_budget = allocated_budget
            max_allowed_qty = int(effective_budget // proposed_price)

        # 5. 수량 계산 및 엄격한 미수 차단 검증
        calculated_qty = int(effective_budget // proposed_price)
        final_qty = min(calculated_qty, max_allowed_qty)

        # 수수료(약 0.1%)를 포함한 총 필요 금액이 가용 현금을 1센트라도 초과하면 수량을 축소
        while final_qty > 0:
            total_order_cost = final_qty * proposed_price
            estimated_fee = total_order_cost * ESTIMATED_FEE_RATE
            if (total_order_cost + estimated_fee) <= available_cash_usd:
                break
            final_qty -= 1

        if final_qty < 1:
            return False, 0, (
                f"잔고 부족: 1주 가격(${proposed_price:.2f})이 "
                f"가용 현금(${available_cash_usd:.2f})을 초과함 (미수 방지)"
            )

        total_cost = final_qty * proposed_price
        return True, final_qty, (
            f"리스크 검증 승인: {final_qty}주 주문 허용 "
            f"(예상 체결액: ${total_cost:.2f} / 총 가용현금: ${available_cash_usd:.2f})"
        )
