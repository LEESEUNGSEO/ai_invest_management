# AI 투자 관리 시스템 (AI Invest Management)

한국투자증권(KIS) OpenAPI와 Google Gemini(Search Grounding)를 결합하여 미국 주식을 분석, 주문, 보고하는 퀀트 트레이딩 봇입니다.

---

## 🏗️ 3대 도메인 아키텍처 (Domain Driven Architecture)

본 프로젝트는 트레이딩 라이프사이클에 맞춰 **분석(open)**, **주문(mid)**, **보고(close)** 3개의 도메인으로 명확하게 모듈화되어 있습니다.

```text
ai_invest_managment/
├── core/                       # [공통 코어 인프라 계층]
│   ├── config.py               # 중앙 집중식 환경 변수 및 설정 로더
│   ├── kis_client.py           # KIS OpenAPI 주문/잔고/시세 통신 및 토큰 캐시 매니저
│   ├── risk_engine.py          # 미수 방지(90%), 손익비(1:2), 슬리피지 검증 리스크 엔진
│   ├── notifier.py             # 카카오톡 '나에게 보내기' 메시지 분할 전송 및 토큰 자동 갱신
│   └── state_manager.py        # 로컬/GCS 간 trading_state 동기화 및 영속화
│
├── domains/                    # [비즈니스 도메인 계층 (유스케이스별 모듈 분리)]
│   ├── open/                   # [1. 분석 도메인 - Analysis & Strategy]
│   │   ├── analyzer.py         # OPEN 단계 전체 파이프라인 오케스트레이션 (run_open_phase)
│   │   ├── research_loader.py  # 시장 리서치 데이터 I/O 및 매크로 컨텍스트 로딩 (load_latest_market_research, save_market_research)
│   │   └── gemini_analyzer.py  # Gemini 실시간 검색(Search Grounding) 및 퀀트 전략 추론 (generate_trading_strategy)
│   │
│   ├── mid/                    # [2. 주문 도메인 - Order Execution & Monitoring]
│   │   ├── order.py            # MID 단계 실시간 감시/주문 총괄 오케스트레이션 (run_mid_phase)
│   │   ├── order_executor.py   # 안전 주문 제출, KIS 응답 검증, 미체결 동기화 (submit_order_safely, reconcile_unfilled_orders)
│   │   └── position_monitor.py # 4단계 포지션 방어 및 Watchlist 매수 진입 집행 (monitor_and_defend_positions, evaluate_and_execute_watchlist)
│   │
│   └── close/                  # [3. 보고 도메인 - Reporting & Settlement]
│       ├── reporter.py         # CLOSE 단계 장 마감 결산 총괄 및 최종 알림 발송 (run_close_phase)
│       ├── settlement.py       # 잔여 미체결 전량 취소 및 계좌 자산/수익률 결산 집계 (cancel_unfilled_orders, build_daily_settlement_report)
│       └── get_kakao_token.py  # 카카오 OAuth 초기 토큰 발급 대화형 CLI 도구
│
├── market_data/                # [데이터] 날짜별 시장 분석 리서치 보관 및 신선도 검증 (.gitkeep, us_market_data_YYYYMMDD.json)
├── state_data/                 # [상태] 매매 상태(strategy_state.json) 및 일별 전략 히스토리 아카이브(history/)
├── main.py                     # [CLI 엔트리포인트] 각 도메인 오케스트레이션 실행기 (--mode=OPEN|MID|CLOSE)
├── requirements.txt            # 프로덕션 실행에 필요한 최소 Python 패키지 (버전 고정)
├── Dockerfile                  # Cloud Run / Docker 컨테이너 빌드 명세서
├── .env.example                # GitHub 배포용 안전한 환경 변수 템플릿
├── .gitignore                  # 토큰, 키, 상태 데이터 유출 방지 보안 설정
├── .dockerignore
└── .gcloudignore
```

---

## 🎯 도메인별 유스케이스 구조 (Domain Architecture & Usecases)

### 1. `domains/open` (분석 도메인 - Analysis & Strategy)
* **주요 역할**: 장 개장 전/초반 시장 상황을 다각도로 분석하여 당일의 매매 전략과 관심 종목(Watchlist)을 수립합니다.
* **유스케이스 및 SRP 모듈 구성**:
  * **`research_loader.py`**:
    * `load_latest_market_research()`: GCS → 로컬 → 환경변수 데이터 소스를 순차 탐색하여 로드 조율.
    * `_load_from_gcs()`, `_load_from_local()`, `_load_from_env()`: 단일 소스별 로딩 전담 헬퍼 (SRP).
    * `save_market_research()`: 리서치 보고서를 표준 스네이크 케이스 규격으로 저장.
    * `get_macro_market_context()`: 매크로 시장 동향 텍스트 로드.
  * **`gemini_analyzer.py`**:
    * `build_open_strategy_prompt()`: 거치식 포트폴리오 퀀트 프롬프트 텍스트 조립 전담 (SRP).
    * `call_gemini_with_search()`: 구글 실시간 웹 검색(Search Grounding)을 장착한 Gemini API 호출 및 다중 모델 자동 폴백.
    * `generate_trading_strategy()`: 프롬프트 생성, API 호출, 결과 JSON 파싱 조율.
  * **`analyzer.py`**:
    * `format_open_briefing_message()`: 카카오톡 브리핑 메시지 포맷팅 전담 (SRP).
    * `run_open_phase()`: 전체 분석 파이프라인 조율, 전략 상태(`strategy_state.json`) 저장 및 브리핑 전송.

### 2. `domains/mid` (주문 도메인 - Order Execution & Monitoring)
* **주요 역할**: 장중 실시간으로 시세를 감시하며 포지션을 방어하고, 조건 만족 시 안전하게 주문을 집행합니다.
* **유스케이스 및 SRP 모듈 구성**:
  * **`order_executor.py`**:
    * `submit_order_safely()`: 주문 의도(intent)를 상태 파일에 선행 저장하고, 주문 접수 응답 및 주문번호(ODNO)를 검증하여 중복 주문 및 고스트 주문 원천 차단.
    * `_register_order_intent()`, `_halt_on_exception()`: 주문 의도 기록 및 예외 시 거래 중단 처리 전담 (SRP).
    * `reconcile_unfilled_orders()`: KIS 실시간 미체결 내역과 로컬 상태 동기화.
    * `_merge_active_orders_with_live()`: 로컬 주문과 증권사 미체결 간의 대조 병합 전담 (SRP).
    * `order_succeeded()`, `order_result_message()`: 응답 코드 검증 및 메시지 포맷팅.
  * **`position_monitor.py`**:
    * `monitor_and_defend_positions()`: 4단계 보유 포지션 방어 (1. 목표가 익절, 2. 손절선 방어, 3. -3.5% 급락 시 Gemini 긴급 AI 진단, 4. 고점 대비 -3% 트레일링 스탑) 조율.
    * `_evaluate_single_holding_defense()`: 단일 보유 종목에 대한 4단계 방어 평가 및 매도 주문 집행 (SRP).
    * `_check_emergency_drop_ai()`: -3.5% 급락 종목 Gemini 실시간 검색 긴급 진단 전담 (SRP).
    * `evaluate_and_execute_watchlist()`: Watchlist 관심 종목 전체 순회 및 진입 조건 만족 시 매수 집행.
    * `_evaluate_single_watchlist_item()`: 단일 관심 종목 시세 비교, RiskEngine 검증, 매수 집행 (SRP).
  * **`order.py`**:
    * `_verify_mid_preconditions()`: 거래 중단 스위치 확인 및 미확인 주문 여부 사전 점검 (SRP).
    * `run_mid_phase()`: 안전 점검, 미체결 동기화, 포지션 방어 및 Watchlist 주문 일괄 조정, 카카오 실시간 리포트 발송.

### 3. `domains/close` (보고 도메인 - Reporting & Settlement)
* **주요 역할**: 장 마감 후 잔여 주문을 정리하고 계좌 손익을 결산하여 최종 일일 보고서를 작성합니다.
* **유스케이스 및 SRP 모듈 구성**:
  * **`settlement.py`**:
    * `cancel_unfilled_orders()`: 당일 체결되지 않은 모든 미체결 주문 일괄 취소 및 실패 목록 추적 조율.
    * `_cancel_single_order()`: 단일 미체결 주문 취소 API 호출 및 성공/실패 여부 반환 (SRP).
    * `build_daily_settlement_report()`: 최종 가용 예수금, 보유 잔고, 평가 손익률, 미체결 취소 내역을 결합한 일일 결산 보고서 생성.
    * `_format_single_holding_line()`: 단일 보유 종목 평단가/종가/수익률 한 줄 포맷팅 (SRP).
  * **`reporter.py`**:
    * `run_close_phase()`: 장 마감 정산 총괄 실행, 거래 상태 동기화 및 카카오톡 결산 리포트 최종 전송.
  * **`get_kakao_token.py`**:
    * `issue_kakao_token()`: 카카오 OAuth 인가 코드를 입력받아 Access/Refresh Token을 발급받는 대화형 CLI 도구.

---

## 🔐 보안 및 환경 변수 설정 (Security & Environment Variables)

모든 토큰, 계좌번호, API 키, 프로젝트 식별자는 코드에서 완전히 제거되었으며 환경 변수로 관리됩니다.

### 1. 환경 변수 설정 (`.env`)
`.env.example`을 복사하여 `.env` 파일을 생성하고 정보를 입력합니다:
```bash
cp .env.example .env
```

| 환경 변수명 | 설명 | 필수 여부 |
|---|---|:---:|
| `GOOGLE_CLOUD_PROJECT` | Google Cloud 프로젝트 ID | 필수 (GCS 연동 시) |
| `GCS_BUCKET_NAME` | 트레이딩 상태 저장용 GCS 버킷명 | 선택 (기본: `{PROJECT_ID}-trading-state`) |
| `GEMINI_API_KEY` | Google AI Studio Gemini API 키 | **필수** |
| `GEMINI_MODELS` | 사용할 Gemini 모델 우선순위 목록 | 선택 (기본: `gemini-4-argon,gemini-3.8-flash,gemini-3.7-flash`) |
| `KIS_APP_KEY` | 한국투자증권 OpenAPI App Key | **필수** |
| `KIS_APP_SECRET` | 한국투자증권 OpenAPI App Secret | **필수** |
| `KIS_CANO` | KIS 계좌번호 앞 8자리 | **필수** |
| `KIS_PRDT_CD` | KIS 계좌 상품코드 2자리 | 선택 (기본: `01`) |
| `KIS_IS_PAPER` | 모의투자 여부 (`true` / `false`) | 선택 (기본: `false`) |
| `KAKAO_CLIENT_ID` | 카카오 REST API 키 | 선택 (토큰 발급 시) |
| `KAKAO_TOKEN_FILE` | 카카오 토큰 JSON 파일 경로 | 선택 (기본: `kakao_token.json`) |
| `KAKAO_ACCESS_TOKEN` | 카카오 액세스 토큰 (환경변수 직접 주입 시) | 선택 |
| `KAKAO_REFRESH_TOKEN` | 카카오 리프레시 토큰 (환경변수 직접 주입 시) | 선택 |

> [!IMPORTANT]
> `.env`, `kakao_token.json`, `*token*.json` 등 실제 인증 시크릿이 포함된 파일들은 `.gitignore`에 등록되어 있어 GitHub에 절대 커밋되지 않으며, `market_data/` 및 `state_data/`의 기초 JSON 데이터는 서버 구동을 위해 Git에 안전하게 포함됩니다.

---

## 🚀 실행 가이드

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 카카오톡 초기 토큰 발급 (최초 1회)
```bash
python -m domains.close.get_kakao_token
```

### 3. 단계별 실행
* **분석 단계 (OPEN / 23:00 KST)**:
  ```bash
  python main.py --mode=OPEN
  ```
* **주문/감시 단계 (MID / 장중 20분 간격 실행)**:
  ```bash
  python main.py --mode=MID
  ```
* **보고/정산 단계 (CLOSE / 06:00 KST)**:
  ```bash
  python main.py --mode=CLOSE
  ```
