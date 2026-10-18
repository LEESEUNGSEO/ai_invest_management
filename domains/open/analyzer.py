from datetime import datetime
from typing import Dict, Any, List

from core.state_manager import load_state, save_state
from core.notifier import send_kakao_message
from domains.open.research_loader import (
    load_latest_market_research,
    save_market_research,
    get_macro_market_context,
)
from domains.open.gemini_analyzer import (
    call_gemini_with_search,
    generate_trading_strategy,
    build_open_strategy_prompt,
)


def _format_watchlist_lines(picks: List[Dict[str, Any]]) -> List[str]:
    """장중 감시 유망 관심 종목 목록을 메시지 줄 단위 리스트로 변환합니다."""
    if not picks:
        return ["• 당일 신규 진입 추천 종목 없음 (시장 리스크로 인한 현금 관망)"]

    lines = []
    for idx, p in enumerate(picks, 1):
        lines.append(
            f"{idx}. {p.get('ticker')} (진입권고: {p.get('action', 'BUY')})\n"
            f"   • 진입희망가: ${float(p.get('proposed_price', 0)):.2f} (수량: {p.get('proposed_qty', 1)}주)\n"
            f"   • 목표가: ${float(p.get('target_price', 0)):.2f} | 손절가: ${float(p.get('stop_loss', 0)):.2f}\n"
            f"   • 투자 근거: {p.get('rationale', '')}"
        )
    return lines


def _format_holdings_lines(hold_strats: List[Dict[str, Any]]) -> List[str]:
    """보유 포트폴리오 대응 전략 목록을 메시지 줄 단위 리스트로 변환합니다."""
    if not hold_strats:
        return []

    lines = ["\n💼 [보유 포트폴리오 대응 전략]"]
    for hs in hold_strats:
        lines.append(
            f"• {hs.get('ticker')}: [{hs.get('action')}]\n"
            f"   • 목표가: ${float(hs.get('target_price', 0)):.2f} | 손절가: ${float(hs.get('stop_loss', 0)):.2f}\n"
            f"   • 근거: {hs.get('rationale', '')}"
        )
    return lines


def format_open_briefing_message(available_cash: float, strategy_data: Dict[str, Any], has_research: bool = True) -> str:
    """OPEN 단계 카카오톡 상세 브리핑 메시지 전문을 생성합니다."""
    mode_text = "📑 사전 딥리서치 + 실시간 검색 결합" if has_research else "📡 실시간 구글 검색 전용 모드 (사전 리서치 미수신/만료)"
    msg_lines = [
        "📊 [미국 증시 OPEN 퀀트 분석 리포트]",
        f"⚙️ 분석 모드: {mode_text}",
        f"💵 실시간 가용 예수금: ${available_cash:.2f}",
        f"🌐 [거시 매크로 종합 분석]\n{strategy_data.get('macro_summary', '정보 없음')}",
        "\n🎯 [장중 감시 유망 관심 종목 (Watchlist Pick)]"
    ]

    picks = strategy_data.get("new_discoveries", [])
    hold_strats = strategy_data.get("holdings_strategy", [])

    msg_lines.extend(_format_watchlist_lines(picks))
    msg_lines.extend(_format_holdings_lines(hold_strats))
    return "\n".join(msg_lines)


def run_open_phase(client, risk_engine):
    """[분석 도메인] OPEN: 장 개장 전/초반 시장 분석 및 전략 수립"""
    print("\n=== [DOMAIN: OPEN (분석) 실시간 구글 검색 기반 전략 수립] ===")
    available_cash = client.get_available_cash_usd()
    balance = client.get_account_balance()
    holdings = balance.get("holdings", [])
    macro_context = get_macro_market_context()

    # 1. Deep Research 파일 로드
    r_data = load_latest_market_research()

    # 2. Gemini 실시간 검색 결합 퀀트 전략 도출
    strategy_data = generate_trading_strategy(
        available_cash=available_cash,
        holdings=holdings,
        macro_context=macro_context,
        research_data=r_data,
    )

    if not strategy_data:
        print("[ERROR] OPEN 전략 생성 실패로 단계를 종료합니다.")
        return

    # 3. state.json에 전략 및 Watchlist 영속화 (일일 히스토리 자동 아카이빙)
    state = load_state()
    state["date"] = datetime.now().strftime("%Y-%m-%d")
    state["strategy"] = strategy_data
    state["watchlist"] = strategy_data.get("new_discoveries", [])
    save_state(state, archive=True)

    # 4. 카카오톡 상세 브리핑 발송
    briefing_msg = format_open_briefing_message(available_cash, strategy_data, has_research=bool(r_data))
    send_kakao_message(briefing_msg)
    print("[OPEN Phase 완료] 퀀트 분석 및 전략 수립 브리핑 전송 완료.")
