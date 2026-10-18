import json
import time
import requests
from typing import Dict, Any, List, Tuple
from core.config import Config


def _extract_json_block(text: str) -> str:
    """텍스트 내에서 가장 바깥쪽 JSON 블록({ ... })을 추출합니다."""
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1].strip()
    return text.strip()


def _request_gemini_model(model_name: str, api_key: str, payload: dict, attempt: int) -> Tuple[int, str]:
    """단일 Gemini 모델에 HTTP 요청을 전송하고 응답 코드 및 텍스트를 반환합니다."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    print(f"[Gemini] {model_name} 실시간 검색 분석 요청 중 (시도 {attempt}/2)...")
    try:
        res = requests.post(url, json=payload, timeout=180)
        if res.status_code == 200:
            data = res.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            raw_text = "".join([p.get("text", "") for p in parts if "text" in p])
            return 200, raw_text
        return res.status_code, res.text
    except Exception as e:
        print(f"[Gemini 통신 예외 - {model_name} 시도 {attempt}/2]: {e}")
        return 0, str(e)


def call_gemini_with_search(prompt: str, json_mode: bool = True) -> str:
    """구글 실시간 검색(Search Grounding)을 장착한 Gemini API 호출 (우선순위 모델 순차 폴백)"""
    api_key = Config.GEMINI_API_KEY
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
        return ""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2}
    }

    for model_name in Config.GEMINI_MODELS:
        for attempt in range(1, 3):
            status_code, response_text = _request_gemini_model(model_name, api_key, payload, attempt)
            if status_code == 200:
                print(f"[Gemini] ✅ {model_name} 응답 수신 성공!")
                return _extract_json_block(response_text) if json_mode else response_text.strip()
            elif status_code in (429, 503):
                print(f"[Gemini] ⚠️ {model_name} 한도/혼잡(HTTP {status_code}) -> 다음 모델/시도로 전환")
                if status_code == 429:
                    break
                time.sleep(3)
            else:
                print(f"[Gemini 호출 실패 HTTP {status_code}]: {response_text[:300]}")
                break
    return ""


def build_open_strategy_prompt(
    available_cash: float,
    holdings: List[Dict[str, Any]],
    macro_context: str,
    research_data: Dict[str, Any]
) -> str:
    """OPEN 단계 퀀트 매매 전략 수립을 위한 프롬프트 문자열을 조립합니다."""
    macro_view = research_data.get('macro_view', {})
    guardrails = research_data.get('risk_guardrails', {})
    focus_stocks = research_data.get('focus_stocks', [])

    if research_data:
        research_context = f"""
[사전 Deep Research 분석 결과]
- 거시 경제 평가: {macro_view.get('summary', 'N/A')} (전망: {macro_view.get('outlook', 'N/A')})
- 운용 가이드라인: {guardrails.get('tactical_directives', 'N/A')} (권장 현금 버퍼: {guardrails.get('recommended_cash_buffer_pct', 20)}%)
- 리서치 추천 관심 종목군(Focus Stocks):
{json.dumps(focus_stocks, ensure_ascii=False, indent=2)}
"""
    else:
        research_context = """
[사전 Deep Research 분석 결과: 미수신 (실시간 구글 검색 단독 모드)]
- 금일 사전 리서치 파일이 제공되지 않았거나 만료되었습니다.
- 구글 검색 도구(Google Search)를 적극 활용하여 최신 미국 시장(S&P 500, 나스닥) 동향, 10년물 국채 금리, 프리마켓(Pre-market) 상승 섹터 및 뉴스 속보를 직접 탐색하고 이를 기반으로 퀀트 전략을 도출하십시오.
"""

    return f"""
당신은 월스트리트 헤지펀드의 수석 퀀트 트레이더이자 리스크 관리자입니다.
수익 극대화보다는 철저한 '원금 보존'과 '손익비(Risk-Reward) 우위'를 원칙으로 거치식 포트폴리오를 운용합니다.

[계좌 재무 상태]
- 실시간 가용 외화 예수금: ${available_cash:.2f} USD
- 현재 보유 종목 및 수량: {json.dumps(holdings, ensure_ascii=False)}

[시장 매크로 컨텍스트]
{macro_context}

{research_context}

[거치식 펀드 운용 핵심 지침]
1. 자본 순환 및 교체 매매 (Capital Recycling):
   - 본 계좌는 정기적 추가 입금이 제한된 '거치식 자본'입니다. 현금 잠김(Lock-up)을 엄격히 경계하십시오.
   - 신규 발굴 종목 또는 리서치 관심 종목의 모멘텀/손익비가 매우 우수한데 가용 현금이 부족하다면, 기존 보유 종목 중 모멘텀이 둔화되거나 지지부진한 종목을 매도(SELL)하여 현금을 확보하십시오.
2. 포트폴리오 분산 및 현금 버퍼:
   - 총자산의 10~20%는 항상 현금 버퍼로 유지하십시오.
   - 단일 종목 집중 배수를 지양하고, 가용 자금 규모에 맞춰 2~3개 종목으로 분산하십시오.
3. 온주 매수 가능 여부 실시간 확인:
   - Deep Research의 대형주(PLTR, NVDA, TSLA 등)는 시장 전체의 모멘텀 지표로 관찰하십시오.
   - 실제 매수 주문은 현재 실시간 가용 예수금 범위 내에서 온주 1주 이상 매수 가능한 종목군(예: $10~$100 구간)을 최우선 검토하십시오.
4. 구글 실시간 검색을 통한 교차 검증:
   - Deep Research 보고서 작성 시점 이후 장 개장 직전까지 발생한 최신 뉴스, 실적 공시, 프리마켓(Pre-market) 시세를 검색 도구로 반드시 재확인하십시오.
   - 돌발 악재가 발견된 종목은 즉시 매수 대상에서 제외하십시오.
5. 손익비 1:2 원칙:
   - (목표가 - 매수가) >= 2 * (매수가 - 손절가) 조건을 엄격히 준수하십시오.

[반환 JSON 스키마 (반드시 마크다운 없이 순수 JSON만 반환)]:
{{
  "macro_summary": "당일 거시 경제 핵심 한 줄 요약",
  "holdings_strategy": [
    {{
      "ticker": "종목코드",
      "action": "BUY | SELL | HOLD",
      "target_price": 0.0,
      "stop_loss": 0.0,
      "rationale": "보유 대응 및 자금 회수/유지 사유"
    }}
  ],
  "new_discoveries": [
    {{
      "ticker": "종목코드",
      "action": "BUY | HOLD",
      "proposed_price": 0.0,
      "proposed_qty": 1,
      "target_price": 0.0,
      "stop_loss": 0.0,
      "rationale": "리서치 결합 및 실시간 프리마켓 검증 기반 선정 사유"
    }}
  ]
}}
"""


def generate_trading_strategy(
    available_cash: float,
    holdings: List[Dict[str, Any]],
    macro_context: str,
    research_data: Dict[str, Any]
) -> Dict[str, Any]:
    """실시간 검색과 리서치 데이터를 바탕으로 Gemini를 통해 퀀트 매매 전략을 생성합니다."""
    prompt = build_open_strategy_prompt(
        available_cash=available_cash,
        holdings=holdings,
        macro_context=macro_context,
        research_data=research_data,
    )
    raw_json = call_gemini_with_search(prompt, json_mode=True)
    if not raw_json:
        print("[ERROR] Gemini 분석 결과 수신 실패")
        return {}

    try:
        return json.loads(raw_json)
    except Exception as e:
        print(f"[JSON 파싱 실패]: {e} | 응답: {raw_json[:200]}")
        return {}
