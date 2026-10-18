import json
from typing import Dict, Any, List, Set, Tuple, Optional
from core.kis_client import get_overseas_price
from domains.open.gemini_analyzer import call_gemini_with_search
from domains.mid.order_executor import submit_order_safely


def _check_emergency_drop_ai(symbol: str, avg_p: float, cur_price: float, profit_rate: float) -> Tuple[bool, str]:
    """급락(-3.5% 이하) 발생 시 Gemini 실시간 검색을 통해 돌발 악재 여부를 진단합니다."""
    print(f"[비상 감지] {symbol} 수익률 {profit_rate*100:.2f}% 급락 -> 긴급 AI 진단 호출")
    emergency_prompt = f"""당신은 리스크 관리 퀀트 매니저입니다.
보유 종목 {symbol}이 평단가 ${avg_p:.2f} 대비 현재 ${cur_price:.2f} ({profit_rate*100:.2f}%)로 급락했습니다.
실시간 구글 검색으로 오늘 이 종목에 치명적인 돌발 악재(실적 쇼크, 소송, 규제 등)가 발생했는지 확인하십시오.
단순 지수 동반 하락/일시적 흔들기라면 HOLD, 치명적 악재라면 EMERGENCY_SELL을 지시하십시오.
반드시 아래 JSON 형식으로만 답하십시오:
{{"action": "EMERGENCY_SELL | HOLD", "reason": "1~2문장 핵심 원인 요약"}}"""
    ai_res = call_gemini_with_search(emergency_prompt, json_mode=True)
    try:
        ai_data = json.loads(ai_res)
        reason = ai_data.get("reason", "")
        if ai_data.get("action") == "EMERGENCY_SELL":
            return True, reason
        print(f"[AI 판단] {symbol} 포지션 유지: {reason}")
    except Exception as e:
        print(f"[WARN] 비상 AI 응답 처리 오류: {e}")
    return False, ""


def _evaluate_single_holding_defense(
    client,
    state: dict,
    h: Dict[str, Any],
    strat_map: Dict[str, Dict[str, Any]],
    tracking_highs: Dict[str, float],
    pending_symbols: Set[str]
) -> Optional[str]:
    """단일 보유 종목에 대해 4단계 방어 규칙(목표가/손절선/비상AI/트레일링스탑)을 평가하고 매도 주문을 실행합니다."""
    symbol = h.get("ticker", "").upper()
    qty = int(float(h.get("qty", 0)))
    avg_p = float(h.get("avg_price", 0.0))
    if not symbol or qty <= 0:
        return None

    if symbol in pending_symbols:
        print(f"[MID Skip] {symbol}: 미체결 주문 존재로 매도 검사 건너뜀")
        return None

    cur_price = get_overseas_price(symbol)
    if cur_price <= 0:
        return None

    prev_high = tracking_highs.get(symbol, cur_price)
    cur_high = max(prev_high, cur_price)
    tracking_highs[symbol] = cur_high

    strat = strat_map.get(symbol, {})
    target_p = float(strat.get("target_price", 0.0))
    stop_p = float(strat.get("stop_loss", 0.0))

    # 1. 목표가 도달 시 익절 매도
    if target_p > 0 and cur_price >= target_p:
        ok, odno, msg = submit_order_safely(client, state, symbol, qty, cur_price, "SELL")
        if ok:
            pending_symbols.add(symbol)
            return f"🎉 {symbol} {qty}주 목표가(${target_p:.2f}) 도달 익절 매도 접수 (${cur_price:.2f}, 주문번호:{odno})"
        return f"❌ {symbol} 익절 매도 거절 ({msg})"

    # 2. 손절선 도달 시 방어 매도
    if stop_p > 0 and cur_price <= stop_p:
        ok, odno, msg = submit_order_safely(client, state, symbol, qty, cur_price, "SELL")
        if ok:
            pending_symbols.add(symbol)
            return f"⚠️ {symbol} {qty}주 손절선(${stop_p:.2f}) 도달 방어 매도 접수 (${cur_price:.2f}, 주문번호:{odno})"
        return f"❌ {symbol} 손절 매도 거절 ({msg})"

    # 3. 비상 급락(-3.5%) 시 Gemini 실시간 악재 진단
    profit_rate = ((cur_price - avg_p) / avg_p) if avg_p > 0 else 0
    if profit_rate <= -0.035:
        should_sell, reason = _check_emergency_drop_ai(symbol, avg_p, cur_price, profit_rate)
        if should_sell:
            ok, odno, msg = submit_order_safely(client, state, symbol, qty, cur_price, "SELL")
            if ok:
                pending_symbols.add(symbol)
                return f"🚨 {symbol} {qty}주 급락 악재 AI 긴급 손절 접수 ({reason}, 주문번호:{odno})"
            return f"❌ {symbol} AI 긴급 손절 거절 ({msg})"

    # 4. 트레일링 스탑: 최고가 대비 -3% 반락 시 수익 보존 매도
    if cur_high > 0:
        pullback = (cur_high - cur_price) / cur_high
        if pullback >= 0.03 and cur_price > avg_p:
            ok, odno, msg = submit_order_safely(client, state, symbol, qty, cur_price, "SELL")
            if ok:
                pending_symbols.add(symbol)
                return f"🛡️ {symbol} {qty}주 트레일링 스탑 고점(${cur_high:.2f}) 대비 -{pullback*100:.1f}% 하락 수익 보존 매도 접수 (${cur_price:.2f}, 주문번호:{odno})"
            return f"❌ {symbol} 트레일링 스탑 매도 거절 ({msg})"

    return None


def monitor_and_defend_positions(
    client,
    state: dict,
    holdings: List[Dict[str, Any]],
    strat_map: Dict[str, Dict[str, Any]],
    tracking_highs: Dict[str, float],
    pending_symbols: Set[str]
) -> List[str]:
    """모든 보유 종목에 대해 4단계 방어/익절 규칙을 순차 적용하고 조치 목록을 반환합니다."""
    actions_taken = []
    for h in holdings:
        action_msg = _evaluate_single_holding_defense(
            client=client,
            state=state,
            h=h,
            strat_map=strat_map,
            tracking_highs=tracking_highs,
            pending_symbols=pending_symbols,
        )
        if action_msg:
            actions_taken.append(action_msg)
    return actions_taken


def _evaluate_single_watchlist_item(
    client,
    risk_engine,
    state: dict,
    item: Dict[str, Any],
    available_cash: float,
    pending_symbols: Set[str],
    holding_symbols: Set[str]
) -> Tuple[Optional[str], Optional[Dict[str, Any]], float]:
    """단일 Watchlist 종목의 가격 조건을 검사하고 매수를 집행합니다."""
    ticker = item.get("ticker", "").upper()
    proposed_p = float(item.get("proposed_price", 0.0))
    req_qty = int(item.get("proposed_qty", 1))

    if item.get("action") != "BUY" or proposed_p <= 0 or not ticker:
        return None, None, available_cash

    if ticker in pending_symbols or ticker in holding_symbols:
        print(f"[MID Watchlist Skip] {ticker}: 이미 보유 중이거나 미체결 주문 존재")
        return None, None, available_cash

    cur_p = get_overseas_price(ticker)
    if cur_p <= 0 or cur_p > proposed_p:
        return None, item, available_cash

    # 리스크 엔진 검증
    is_valid, approved_qty, reason = risk_engine.validate_buy_order(
        symbol=ticker,
        proposed_price=cur_p,
        current_market_price=cur_p,
        available_cash_usd=available_cash,
    )
    if not is_valid or approved_qty < 1:
        print(f"[RiskEngine 거절] {ticker}: {reason}")
        return None, item, available_cash

    buy_qty = min(req_qty, approved_qty) if req_qty > 0 else approved_qty
    print(f"[장중 진입 시도] {ticker} 현재가 ${cur_p:.2f} <= 목표가 ${proposed_p:.2f} (승인수량: {buy_qty}주)")
    ok, odno, msg = submit_order_safely(client, state, ticker, buy_qty, cur_p, "BUY")
    if ok:
        pending_symbols.add(ticker)
        new_cash = available_cash - (cur_p * buy_qty)
        return f"🎯 [장중 Pick 매수 주문 접수] {ticker} {buy_qty}주 (${cur_p:.2f}, 주문번호:{odno})", None, new_cash

    return f"❌ [장중 Pick 매수 거절] {ticker} {buy_qty}주 ({msg})", item, available_cash


def evaluate_and_execute_watchlist(
    client,
    risk_engine,
    state: dict,
    watchlist: List[Dict[str, Any]],
    available_cash: float,
    pending_symbols: Set[str],
    holding_symbols: Set[str]
) -> Tuple[List[str], List[Dict[str, Any]], float]:
    """Watchlist 종목 전체를 순회하며 진입 조건 만족 시 매수를 집행합니다."""
    actions_taken = []
    remaining_watchlist = []

    for item in watchlist:
        if not isinstance(item, dict):
            continue
        act_msg, keep_item, available_cash = _evaluate_single_watchlist_item(
            client=client,
            risk_engine=risk_engine,
            state=state,
            item=item,
            available_cash=available_cash,
            pending_symbols=pending_symbols,
            holding_symbols=holding_symbols,
        )
        if act_msg:
            actions_taken.append(act_msg)
        if keep_item:
            remaining_watchlist.append(keep_item)

    return actions_taken, remaining_watchlist, available_cash
