import os

env_path = os.getenv("ENV_FILE", ".env")
try:
    from dotenv import load_dotenv
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    # python-dotenv 미설치 환경에서도 .env를 파싱하는 내장 Fallback
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
                        v = v[1:-1]
                    if k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass

class Config:
    # 1. Google Cloud 설정
    PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    GCS_BUCKET_NAME = os.getenv(
        "GCS_BUCKET_NAME",
        f"{PROJECT_ID}-trading-state" if PROJECT_ID else ""
    ).strip()

    # 2. Google Gemini 설정
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODELS = [
        m.strip() for m in os.getenv(
            "GEMINI_MODELS",
            "gemini-4-argon,gemini-3.8-flash,gemini-3.7-flash"
        ).split(",") if m.strip()
    ]

    # 3. 한국투자증권(KIS) OpenAPI 설정
    KIS_BASE_URL = os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443").strip()
    KIS_VTS_URL = os.getenv("KIS_VTS_URL", "https://openapivts.koreainvestment.com:29443").strip()
    KIS_IS_PAPER = os.getenv("KIS_IS_PAPER", "false").lower() in ("true", "1", "yes")

    KIS_APP_KEY = os.getenv("KIS_APP_KEY", "").strip()
    KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "").strip()
    KIS_CANO = os.getenv("KIS_CANO", "").strip()
    KIS_PRDT_CD = os.getenv("KIS_PRDT_CD", "01").strip()

    # 4. 카카오톡 알림 설정
    KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID", "").strip()
    KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "").strip()
    KAKAO_TOKEN_FILE = os.getenv(
        "KAKAO_TOKEN_FILE",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "kakao_token.json")
    ).strip()
    KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN", "").strip()
    KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "").strip()

    # 5. 상태 파일 및 리서치 경로 설정
    STATE_DIR = os.getenv("STATE_DIR", "state_data").strip()
    STATE_FILE = os.getenv(
        "STATE_FILE",
        os.path.join(STATE_DIR, "strategy_state.json") if os.path.exists(STATE_DIR) or not os.path.exists("/tmp") else "/tmp/strategy_state.json"
    ).strip()
    STATE_HISTORY_DIR = os.getenv(
        "STATE_HISTORY_DIR",
        os.path.join(STATE_DIR, "history")
    ).strip()
    INITIAL_STRATEGY_STATE = os.getenv("INITIAL_STRATEGY_STATE", "").strip()
    MARKET_DATA_DIR = os.getenv(
        "MARKET_DATA_DIR",
        "market_data" if os.path.exists("market_data") or not os.path.exists("marketData") else "marketData"
    ).strip()
    RESEARCH_PATH_PATTERN = os.getenv(
        "RESEARCH_PATH_PATTERN",
        os.path.join(MARKET_DATA_DIR, "us_market_data_*.json")
    ).strip()
    MARKET_RESEARCH_JSON = os.getenv("MARKET_RESEARCH_JSON", "").strip()
    MARKET_REPORT_PATH = os.getenv("MARKET_REPORT_PATH", "latest_market_report.txt").strip()
    KIS_TOKEN_CACHE_FILE = os.getenv("KIS_TOKEN_CACHE_FILE", "/tmp/kis_token_cache.json").strip()
    MAX_RESEARCH_AGE_DAYS = int(os.getenv("MAX_RESEARCH_AGE_DAYS", "1"))
