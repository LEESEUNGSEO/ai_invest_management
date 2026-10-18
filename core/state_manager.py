import os
import json
from datetime import datetime
from core.config import Config

STATE_FILE = Config.STATE_FILE
PROJECT_ID = Config.PROJECT_ID
BUCKET_NAME = Config.GCS_BUCKET_NAME


def sync_state_from_gcs():
    """GCS 상태 다운로드 (SDK 사용)"""
    if not PROJECT_ID or not BUCKET_NAME:
        return
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob("strategy_state.json")
        if blob.exists():
            os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)), exist_ok=True)
            blob.download_to_filename(STATE_FILE)
            print(f"[State] GCS 상태 다운로드 완료 (gs://{BUCKET_NAME}/strategy_state.json)")
        else:
            print(f"[INFO] GCS에 strategy_state.json이 아직 없습니다 ({BUCKET_NAME}).")
    except Exception as e:
        raise RuntimeError(
            f"GCS 상태 다운로드 실패. 자동매매를 진행하면 안 됩니다: {type(e).__name__}: {e}"
        ) from e


def sync_state_to_gcs():
    """로컬 상태 파일을 GCS에 영속화 (SDK 사용)"""
    if not PROJECT_ID or not BUCKET_NAME:
        return
    if not os.path.exists(STATE_FILE):
        raise RuntimeError("GCS 업로드할 로컬 상태 파일이 없습니다.")
    try:
        from google.cloud import storage
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob("strategy_state.json")
        blob.upload_from_filename(STATE_FILE)
        print(f"[State] GCS 상태 업로드 완료 (gs://{BUCKET_NAME}/strategy_state.json)")
    except Exception as e:
        raise RuntimeError(
            f"GCS 상태 업로드 실패. 상태 영속성을 확인해야 합니다: {type(e).__name__}: {e}"
        ) from e


def load_state() -> dict:
    """상태를 안전하게 읽습니다. 파일 부재 시 환경변수 또는 기본 상태로 초기화합니다."""
    sync_state_from_gcs()

    if not os.path.exists(STATE_FILE):
        # 1) 로컬 디렉토리(state_data/strategy_state.json 등)에서 fallback 로드
        local_candidates = [
            os.path.join("state_data", "strategy_state.json"),
            "strategy_state.json",
        ]
        for candidate in local_candidates:
            if os.path.exists(candidate) and os.path.abspath(candidate) != os.path.abspath(STATE_FILE):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    print(f"[State] 로컬 상태 파일 로드 완료: {candidate}")
                    save_state(state)
                    return state
                except Exception as e:
                    print(f"[State WARN] {candidate} 로드 실패: {e}")

        # 2) 환경변수에 초기 상태가 정의되어 있으면 자동 복원/초기화
        if Config.INITIAL_STRATEGY_STATE:
            try:
                state = json.loads(Config.INITIAL_STRATEGY_STATE)
                print("[State] 환경변수 INITIAL_STRATEGY_STATE 기반 상태 초기화 완료")
                save_state(state)
                return state
            except Exception as e:
                print(f"[State WARN] INITIAL_STRATEGY_STATE 환경변수 파싱 실패: {e}")

        # 2) 기본 상태 템플릿 생성
        default_state = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "strategy": {
                "macro_summary": "당일 매매 시작 대기",
                "holdings_strategy": [],
                "new_discoveries": []
            },
            "active_orders": [],
            "tracking_highs": {},
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        print(f"[State] 초기 상태 파일이 없어 기본 템플릿으로 생성합니다: {STATE_FILE}")
        save_state(default_state)
        return default_state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        raise RuntimeError(
            f"거래 상태 파일을 읽을 수 없습니다: {type(e).__name__}"
        ) from e

    if not isinstance(state, dict):
        raise RuntimeError("거래 상태 파일의 최상위 구조가 올바르지 않습니다.")

    return state


def archive_daily_state(state: dict, target_date: str = None) -> str:
    """당일 매매 전략 및 상태를 사후 검증/성과 비교용으로 날짜별 아카이브(히스토리) 파일로 저장합니다."""
    history_dir = Config.STATE_HISTORY_DIR
    os.makedirs(history_dir, exist_ok=True)

    if not target_date:
        target_date = state.get("date") or datetime.now().strftime("%Y-%m-%d")
    date_str = str(target_date).replace("-", "").strip()

    file_name = f"strategy_state_{date_str}.json"
    file_path = os.path.join(history_dir, file_name)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"[State History] [OK] 전략 일일 히스토리 로그 저장 완료: {file_path}")
    except Exception as e:
        print(f"[State History WARN] 로컬 히스토리 저장 실패: {e}")
        return ""

    # GCS 버킷 동기화 (설정된 경우)
    if PROJECT_ID and BUCKET_NAME:
        try:
            from google.cloud import storage
            client = storage.Client(project=PROJECT_ID)
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(f"history/{file_name}")
            blob.upload_from_filename(file_path)
            print(f"[State History] [OK] GCS 아카이브 업로드 완료 (gs://{BUCKET_NAME}/history/{file_name})")
        except Exception as e:
            print(f"[State History WARN] GCS 아카이브 업로드 실패: {e}")

    return file_path


def save_state(state: dict, archive: bool = True):
    """상태 저장, GCS 영속화 및 일별 히스토리 아카이브"""
    state_dir = os.path.dirname(os.path.abspath(STATE_FILE))
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
    if isinstance(state, dict):
        if not state.get("date"):
            state["date"] = datetime.now().strftime("%Y-%m-%d")
        state["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    sync_state_to_gcs()

    if archive and isinstance(state, dict):
        archive_daily_state(state)
