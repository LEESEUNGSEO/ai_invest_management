# 🏁 Close Domain (보고 및 정산 도메인)

미국 주식 정규장 마감 시점(익일 06:00 KST)에 실행되어 당일 미체결된 잔여 주문을 전량 취소하고, 최종 포트폴리오 평가 손익과 가용 현금을 정산하여 관리자에게 종합 보고서를 발행하는 도메인입니다. 또한 카카오톡 알림을 위한 초기 OAuth 인증 유틸리티를 포함합니다.

---

## 🎯 주요 역할 및 유스케이스

1. **미체결 정리 및 결산 집계 (`settlement.py`)**:
   - **미체결 취소 (`cancel_unfilled_orders`)**: 장 마감 직전까지 체결되지 않은 모든 활성 주문(`active_orders`)을 증권사 OpenAPI(`cancel_order`)를 통해 일괄 취소하고 실패 목록을 추적합니다.
   - **결산 리포트 생성 (`build_daily_settlement_report`)**: 가용 외화 예수금, 보유 종목별 평단가/종가 대조 평가 손익률(%), 미체결 취소 건수를 취합하여 가독성 높은 일일 결산 보고서 문자열을 구성합니다.
2. **CLOSE 오케스트레이션 (`reporter.py`)**:
   - 미체결 취소 ➔ 계좌 잔고/예수금 조회 ➔ 결산 리포트 생성 ➔ 카카오톡 최종 전송 플로우를 총괄 실행합니다.
3. **카카오톡 OAuth 초기 인증 (`get_kakao_token.py`)**:
   - 카카오톡 메시지 발송에 필요한 최초 OAuth 2.0 Access/Refresh Token을 발급받아 `kakao_token.json`을 생성하는 대화형 CLI 도구를 제공합니다.

---

## 📂 파일 및 유스케이스 구성

```text
domains/close/
├── __init__.py           # 공개 API re-export
├── reporter.py           # [오케스트레이션] CLOSE 단계 장 마감 결산 총괄 및 최종 알림 발송 (run_close_phase)
├── settlement.py         # [결산 집계] 잔여 미체결 일괄 취소 및 일일 결산 리포트 텍스트 생성
├── get_kakao_token.py    # [인증 도구] 카카오 OAuth 초기 토큰 발급 대화형 CLI
└── README.md             # 보고 도메인 상세 가이드
```

---

## 🔧 주요 함수 인터페이스

| 모듈 | 함수 | 설명 |
|---|---|---|
| `reporter.py` | `run_close_phase(client, risk_engine)` | 보고 도메인의 메인 실행 함수. 미체결 정리 → 잔고 조회 → 결산 생성 → 카카오톡 발송 조율 |
| `settlement.py` | `cancel_unfilled_orders(client, state) -> Tuple[int, List[str]]` | 미체결 주문 일괄 취소 및 상태 갱신 조율 |
| `settlement.py` | `_cancel_single_order(client, order) -> Tuple[bool, str, dict]` | 단일 미체결 주문 취소 API 호출 및 성공/실패 여부 반환 (SRP) |
| `settlement.py` | `build_daily_settlement_report(...) -> str` | 일일 결산 종합 보고서 전문 문자열 조립 |
| `settlement.py` | `_format_single_holding_line(h: dict) -> str` | 단일 보유 종목 평단가/종가/수익률 한 줄 포맷팅 (SRP) |
| `get_kakao_token.py` | `issue_kakao_token() -> bool` | 카카오 OAuth 브리핑 인증 코드를 입력받아 초기 `kakao_token.json`을 생성하는 대화형 함수 |

---

## 💻 실행 방법

### 1. 장 마감 결산 보고 실행
```bash
python main.py --mode=CLOSE
```

### 2. 카카오톡 초기 토큰 발급 (최초 1회 셋업)
```bash
python -m domains.close.get_kakao_token
# 또는
python domains/close/get_kakao_token.py
```
