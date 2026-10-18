# ⚙️ Core Infrastructure (공통 인프라 계층)

3대 비즈니스 도메인(`open`, `mid`, `close`)이 공통으로 사용하는 증권사 API 통신, 리스크 가드레일, 알림 전송, 환경변수 및 상태 영속화 모듈들이 응집된 코어 계층입니다.

---

## 📂 파일 구성 및 역할

```text
core/
├── __init__.py           # 코어 모듈 주요 클래스 및 함수 re-export
├── config.py             # 중앙 집중식 환경 변수 로더 (.env 및 시스템 환경변수 통합)
├── kis_client.py         # KIS OpenAPI 주문/시세 통신 클라이언트 및 토큰 캐시 매니저
├── risk_engine.py        # 미수 방지 버퍼(90%), 손익비(1:2), 시세 괴리율 검증 리스크 엔진
├── notifier.py           # 카카오톡 '나에게 보내기' 메시지 분할 전송 및 토큰 자동 갱신
├── state_manager.py      # 로컬 /tmp 파일과 Google Cloud Storage 간 trading_state 동기화
└── README.md             # 코어 계층 상세 가이드
```

---

## 🛠 모듈별 상세 역할

### 1. `config.py` (Config)
- 시스템의 모든 설정과 API 자격증명을 단일 클래스(`Config`)로 캡슐화합니다.
- 특정 사용자 로컬 경로를 제거하고, `GOOGLE_CLOUD_PROJECT`, `GEMINI_API_KEY`, `KIS_APP_KEY`, `KAKAO_TOKEN_FILE` 등을 체계적으로 로드합니다.

### 2. `kis_client.py` (`KISOrderClient`, `get_overseas_price`)
- **통합 토큰 캐싱 (`_shared_get_kis_token`)**: `/tmp/kis_token_cache.json` 및 GCS 버킷 동기화를 통해 KIS 접근 토큰 중복 발급(403 초과 에러)을 원천 차단합니다.
- **주문/잔고 메서드**:
  - `get_available_cash_usd()`: 가용 외화 예수금 조회.
  - `get_account_balance()`: 보유 종목 및 평가금액 조회.
  - `send_order()`, `buy_overseas_order()`, `sell_overseas_order()`: 지정가 주문 전송.
  - `get_unfilled_orders()`, `cancel_order()`: 미체결 조회 및 주문 취소.
- **시세 조회 (`get_overseas_price`)**: 미국 거래소(NASD, NYSE, AMEX) 시세를 조회합니다.

### 3. `risk_engine.py` (`RiskEngine`)
- **미수 차입 원천 차단 (`CASH_SAFETY_RATIO = 0.90`)**: 가용 현금의 최대 90% 이내에서만 주문 예산을 배정합니다.
- **시세 괴리율 방어 (`MAX_PRICE_DEVIATION = 0.03`)**: 실시간 시장가와 AI 제안가의 차이가 3%를 초과할 경우 환각으로 판단하여 주문을 거절합니다.
- **종목당 투자 한도 (`DEFAULT_MAX_ALLOCATION_RATIO = 0.20`)**: 단일 종목 집중 투자를 제한하고 분산 투자를 유도합니다.

### 4. `notifier.py` (`send_kakao_message`)
- 카카오톡 메시지 글자 수 제한을 고려하여 긴 리포트를 줄바꿈 단위로 안전하게 분할 전송합니다.
- Access Token 만료 시 Refresh Token을 사용해 자동으로 토큰을 갱신하고 파일/GCS에 저장합니다.
- 환경변수(`KAKAO_ACCESS_TOKEN`, `KAKAO_REFRESH_TOKEN`)를 통한 직접 주입을 지원합니다.

### 5. `state_manager.py` (`load_state`, `save_state`, `sync_state_*`)
- 서버리스(Cloud Run) 재시작 환경에서도 트레이딩 상태(`strategy_state.json`)가 유실되지 않도록 Google Cloud Storage와 로컬 `/tmp` 간 양방향 동기화를 수행합니다.
