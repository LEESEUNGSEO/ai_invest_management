# 📊 Open Domain (분석 도메인)

미국 주식 정규장 개장 전/초반(23:00 KST)에 거시 경제 지표와 기업 뉴스를 다각도로 분석하고, **Google Gemini 실시간 웹 검색(Search Grounding)**을 활용하여 최적의 퀀트 매매 전략 및 관심 종목(Watchlist)을 수립하는 도메인입니다.

---

## 🎯 주요 역할 및 유스케이스

1. **사전 리서치 데이터 관리 (`research_loader.py`)**:
   - GCS 버킷(`gs://{PROJECT_ID}-trading-state/`) 또는 로컬 폴더 **`market_data/`**에서 장전 딥리서치 보고서(**`us_market_data_YYYYMMDD.json`**)를 최신순으로 탐색합니다.
   - **데이터 신선도(Freshness) 검증 (`is_research_fresh`)**: 기준일이 당일(또는 허용 경과일수 초과 시)이 아닌 오래된 과거 데이터는 편향 방지를 위해 자동 배제하며, **"실시간 구글 검색(Search Grounding) 단독 모드"**로 안전하게 폴백합니다.
   - `save_market_research(data, target_date)` 유틸리티를 통해 날짜별 스네이크 케이스 규격으로 일관성 있게 저장·관리합니다.
   - 매크로 시장 요약 텍스트(`latest_market_report.txt`)를 컨텍스트로 주입합니다.
2. **Gemini 실시간 검색 및 AI 전략 도출 (`gemini_analyzer.py`)**:
   - Deep Research 작성 시점 이후 장 개장 직전까지 발생한 최신 뉴스, 실적 발표, 프리마켓(Pre-market) 급등락을 구글 실시간 검색으로 교차 검증합니다.
   - 모델 혼잡/쿼터 한도(429/503) 발생 시 `gemini-4-argon` → `gemini-3.8-flash` → `gemini-3.7-flash` 순으로 자동 폴백합니다.
   - **거치식 포트폴리오 전략**: 자본 순환(Capital Recycling), 손익비 1:2 원칙, 온주 매수 적합성을 엄격히 적용합니다.
3. **분석 파이프라인 오케스트레이션 (`analyzer.py`)**:
   - 계좌 잔고 조회 ➔ 리서치 로딩 ➔ AI 전략 수립 ➔ 상태 영속화(`strategy_state.json`) ➔ 카카오톡 종합 브리핑 발송까지의 전체 플로우를 총괄 실행합니다.

---

## 📂 파일 및 유스케이스 구성

```text
domains/open/
├── __init__.py           # 공개 API re-export
├── analyzer.py           # [오케스트레이션] OPEN 단계 파이프라인 실행 (run_open_phase)
├── research_loader.py    # [리서치 I/O] market_data/ 및 GCS 리서치 저장/로드, 매크로 텍스트 조회
├── gemini_analyzer.py    # [AI 엔진] 실시간 검색 Grounding 연동 및 퀀트 전략 추론
└── README.md             # 분석 도메인 상세 가이드
```

---

## 🔧 주요 함수 인터페이스

| 모듈 | 함수 | 설명 |
|---|---|---|
| `analyzer.py` | `run_open_phase(client, risk_engine)` | 분석 도메인의 메인 실행 함수. 잔고 조회 → 리서치 로드 → AI 분석 → 상태 저장 → 알림 일괄 수행 |
| `analyzer.py` | `format_open_briefing_message(...) -> str` | Watchlist 및 보유 포트폴리오 전략을 조합한 카카오톡 브리핑 전문 생성 (SRP) |
| `research_loader.py` | `load_latest_market_research() -> dict` | GCS → 로컬 → 환경변수 순서로 최신 리서치 로드 조율 |
| `research_loader.py` | `_load_from_gcs()`, `_load_from_local()`, `_load_from_env()` | 각 출처별 단일 데이터 소스 조회 전담 헬퍼 (SRP) |
| `research_loader.py` | `save_market_research(data, target_date) -> str` | 리서치 데이터를 `market_data/us_market_data_YYYYMMDD.json` 규격으로 저장 |
| `research_loader.py` | `get_macro_market_context() -> str` | 매크로 시장 동향 파일 읽기 (부재 시 기본 컨텍스트 반환) |
| `gemini_analyzer.py` | `build_open_strategy_prompt(...) -> str` | 거치식 포트폴리오 퀀트 프롬프트 텍스트 조립 전담 (SRP) |
| `gemini_analyzer.py` | `call_gemini_with_search(prompt, json_mode) -> str` | 구글 실시간 검색 도구가 결합된 Gemini REST API 호출 및 JSON 응답 추출 |
| `gemini_analyzer.py` | `generate_trading_strategy(...) -> dict` | 프롬프트 생성, API 호출, 결과 JSON 파싱 조율 |

---

## 💻 실행 방법

```bash
# main.py를 통한 도메인 실행
python main.py --mode=OPEN
```
