# ⚡ Mid Domain (주문 및 실시간 감시 도메인)

미국 주식 정규장 운영 시간 동안 주기적(예: 20분 간격)으로 실행되어 보유 포지션의 수익을 보존하고, 목표 진입가에 도달한 관심 종목(Watchlist)을 안전하게 분할 매수하는 주문 집행 도메인입니다.

---

## 🎯 주요 역할 및 유스케이스

1. **안전 주문 집행 및 동기화 (`order_executor.py`)**:
   - **안전 주문 접수 (`submit_order_safely`)**: 주문 의도(intent)를 상태 파일에 선행 저장(`SUBMITTING`)하고, KIS 응답 코드(`rt_cd == 0`) 및 주문번호(`ODNO`) 검증 후 `ACCEPTED`로 전환합니다. 통신 장애 시 즉시 거래 중단(`trading_halt=True`)을 발동하여 중복 주문을 방지합니다.
   - **미체결 동기화 (`reconcile_unfilled_orders`)**: 증권사 실시간 미체결 내역과 로컬 `active_orders`를 동기화하여 중복 주문을 원천 방지합니다.
2. **포지션 감시 & Watchlist 매수 진입 (`position_monitor.py`)**:
   - **4단계 포지션 방어 (`monitor_and_defend_positions`)**:
     1. *목표가 도달*: 즉시 익절 매도 주문 제출.
     2. *손절선 도달*: 방어 매도 주문 제출.
     3. *비상 급락(-3.5%)*: Gemini 실시간 검색 긴급 진단 후 치명적 악재 시 `EMERGENCY_SELL` 집행.
     4. *트레일링 스탑*: 고점 대비 -3.0% 반락 시 수익 보존 매도.
   - **Watchlist 진입 (`evaluate_and_execute_watchlist`)**: 관심 종목 현재가가 제안가 이하일 때 `RiskEngine` 검증 후 신규 매수 주문을 집행합니다.
3. **MID 오케스트레이션 (`order.py`)**:
   - 거래 중단 스위치 점검 ➔ 미확인 주문 확인 ➔ 미체결 동기화 ➔ 포지션 방어 ➔ 신규 매수 집행 ➔ 카카오 실시간 리포트 발송 플로우를 총괄 실행합니다.

---

## 📂 파일 및 유스케이스 구성

```text
domains/mid/
├── __init__.py           # 공개 API re-export
├── order.py              # [오케스트레이션] MID 단계 실시간 감시/주문 총괄 실행 (run_mid_phase)
├── order_executor.py     # [주문 집행] 주문 의도 선저장, KIS API 호출, ODNO 검증, 미체결 동기화
├── position_monitor.py   # [포지션 감시] 4단계 방어(익절/손절/비상AI/트레일링) 및 Watchlist 매수 진입
└── README.md             # 주문 도메인 상세 가이드
```

---

## 🔧 주요 함수 인터페이스

| 모듈 | 함수 | 설명 |
|---|---|---|
| `order.py` | `run_mid_phase(client, risk_engine)` | 주문 도메인의 메인 실행 함수. 안전 점검 → 미체결 동기화 → 포지션 방어 → 신규 매수 → 알림 전송 |
| `order.py` | `_verify_mid_preconditions(state) -> Tuple[bool, str]` | 거래 중단 스위치 및 미확인 주문 여부 사전 점검 (SRP) |
| `order_executor.py` | `submit_order_safely(...) -> Tuple[bool, str, str]` | 주문 의도 선저장 및 증권사 주문 전송/응답 검증 안전 함수 |
| `order_executor.py` | `_register_order_intent(...)`, `_halt_on_exception(...)` | 주문 의도 기록 및 예외 발생 시 안전 중단 전담 헬퍼 (SRP) |
| `order_executor.py` | `reconcile_unfilled_orders(client, state) -> set` | 증권사 실시간 미체결 내역과 상태 동기화 및 미체결 종목 집합 반환 |
| `order_executor.py` | `_merge_active_orders_with_live(...)` | 로컬 활성 주문과 증권사 미체결 간의 대조 병합 전담 (SRP) |
| `order_executor.py` | `order_succeeded(res: dict) -> bool` | KIS 응답의 성공 여부 검증 (`rt_cd == "0"`) |
| `order_executor.py` | `order_result_message(res: dict) -> str` | 주문 응답 결과 메시지 요약 |
| `position_monitor.py`| `monitor_and_defend_positions(...) -> List[str]` | 보유 종목에 대한 실시간 시세 조회 및 4단계 방어/익절 규칙 조율 |
| `position_monitor.py`| `_evaluate_single_holding_defense(...) -> str` | 단일 보유 종목에 대한 4단계 방어 평가 및 매도 주문 집행 (SRP) |
| `position_monitor.py`| `_check_emergency_drop_ai(...) -> Tuple[bool, str]` | -3.5% 급락 종목 Gemini 실시간 검색 긴급 진단 전담 (SRP) |
| `position_monitor.py`| `evaluate_and_execute_watchlist(...) -> Tuple[...]` | 관심 종목 전체 순회 및 진입 조건 만족 시 매수 집행 |
| `position_monitor.py`| `_evaluate_single_watchlist_item(...) -> Tuple[...]` | 단일 관심 종목 시세 비교, RiskEngine 검증, 매수 집행 (SRP) |

---

## 💻 실행 방법

```bash
# main.py를 통한 도메인 실행 (Cloud Scheduler 또는 Cron 20분 주기 권장)
python main.py --mode=MID
```
