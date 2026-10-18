import argparse
import sys
from core.config import Config
from core.kis_client import KISOrderClient
from core.risk_engine import RiskEngine
from domains.open import run_open_phase
from domains.mid import run_mid_phase
from domains.close import run_close_phase


def main():
    parser = argparse.ArgumentParser(description="AI Quant Trading Engine")
    parser.add_argument(
        "--mode",
        choices=["OPEN", "MID", "CLOSE"],
        default="OPEN",
        help="실행 도메인 단계 선택 (OPEN: 분석 및 전략, MID: 주문 및 실시간 감시, CLOSE: 결산 및 보고)"
    )
    args = parser.parse_args()

    client = KISOrderClient()
    risk_engine = RiskEngine()

    try:
        if args.mode == "OPEN":
            run_open_phase(client, risk_engine)
        elif args.mode == "MID":
            run_mid_phase(client, risk_engine)
        elif args.mode == "CLOSE":
            run_close_phase(client, risk_engine)
    except Exception as e:
        print(f"[FATAL ERROR] {args.mode} 모드 실행 중 치명적 오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
