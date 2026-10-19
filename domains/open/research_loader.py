import os
import glob
import json
import re
from datetime import datetime, date
from typing import Optional, List, Tuple
from core.config import Config


def is_research_fresh(data: dict, file_identifier: str = "", max_age_days: Optional[int] = None) -> Tuple[bool, str]:
    """리서치 데이터가 당일 혹은 최근 유효 영업일 데이터인지 신선도(Freshness)를 검증합니다.

    Args:
        data: 리서치 JSON 데이터 딕셔너리
        file_identifier: 파일 경로 또는 blob 이름
        max_age_days: 허용 최대 경과 일수 (미지정 시 Config.MAX_RESEARCH_AGE_DAYS)

    Returns:
        (is_fresh, reason_message)
    """
    if max_age_days is None:
        max_age_days = Config.MAX_RESEARCH_AGE_DAYS

    target_date_str = None
    if isinstance(data, dict):
        target_date_str = (
            data.get("target_trade_date")
            or data.get("date")
            or data.get("target_date")
            or data.get("trade_date")
        )
        if not target_date_str and "generated_at" in data:
            target_date_str = str(data["generated_at"])[:10]

    if not target_date_str and file_identifier:
        m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", file_identifier)
        if m:
            target_date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    if not target_date_str:
        return False, "데이터 또는 파일명에서 기준 일자를 확인할 수 없음"

    try:
        clean_date_str = str(target_date_str).replace("/", "-").strip()[:10]
        target_dt = datetime.strptime(clean_date_str, "%Y-%m-%d").date()
    except Exception as e:
        return False, f"기준 날짜 포맷 파싱 실패({target_date_str}): {e}"

    today = datetime.now().date()
    diff_days = (today - target_dt).days

    # 미래 날짜는 시차 감안 최대 1일까지 허용
    if diff_days < -1:
        return False, f"미래 일자 데이터 감지 (기준일: {target_dt}, 현재: {today})"

    # 월요일 장 개장 전의 경우 주말(금요일자) 리서치 최대 3일까지 허용
    allowed_days = max_age_days
    if today.weekday() == 0 and allowed_days == 1:
        allowed_days = 3

    if diff_days > allowed_days:
        return False, f"과거 데이터 만료 (기준일: {target_dt}, {diff_days}일 경과 / 허용 한도: {allowed_days}일)"

    return True, f"유효한 최신 데이터 확인 (기준일: {target_dt}, {diff_days}일 전)"


def save_market_research(data: dict, target_date: str = None) -> str:
    """리서치 데이터를 market_data/us_market_data_YYYYMMDD.json 형태의 스네이크 케이스 날짜별 파일로 저장"""
    save_dir = Config.MARKET_DATA_DIR
    os.makedirs(save_dir, exist_ok=True)

    if not target_date:
        target_date = data.get("target_trade_date") or datetime.now().strftime("%Y-%m-%d")
    date_str = str(target_date).replace("-", "").strip()

    file_name = f"us_market_data_{date_str}.json"
    file_path = os.path.join(save_dir, file_name)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[Research 저장] 스네이크 케이스 리서치 데이터 저장 완료: {file_path}")
    return file_path


def _load_from_gcs() -> Optional[dict]:
    """GCS 버킷에서 가장 최신의 유효한 리서치 JSON을 탐색하여 로드합니다."""
    project_id = Config.PROJECT_ID
    bucket_name = Config.GCS_BUCKET_NAME
    if not project_id or not bucket_name:
        return None

    try:
        from google.cloud import storage
        client = storage.Client(project=project_id)
        bucket = client.bucket(bucket_name)
        blobs = (
            list(bucket.list_blobs(prefix="us_market_data")) +
            list(bucket.list_blobs(prefix="usMarketData")) +
            list(bucket.list_blobs(prefix="US_Market_Data"))
        )
        for blob in sorted(blobs, key=lambda b: b.name, reverse=True):
            try:
                content = blob.download_as_text(encoding="utf-8")
                parsed = json.loads(content)
                is_fresh, reason = is_research_fresh(parsed, blob.name)
                if is_fresh:
                    print(f"[Research 로드] [OK] GCS 최신 유효 파일 로드: gs://{bucket_name}/{blob.name} ({reason})")
                    return parsed
                else:
                    print(f"[Research 로드 WARN] GCS 파일 만료 배제: gs://{bucket_name}/{blob.name} -> {reason}")
            except Exception as blob_err:
                print(f"[Research 로드 WARN] GCS 개별 파일 읽기 실패 ({blob.name}): {blob_err}")
    except Exception as e:
        print(f"[Research 로드 WARN] GCS 버킷 탐색 실패: {e}")
    return None


def _find_local_candidate_files() -> List[str]:
    """로컬 디렉토리에서 리서치 후보 파일 목록을 최신순(역순)으로 탐색합니다."""
    local_files = glob.glob(Config.RESEARCH_PATH_PATTERN)
    if not local_files:
        search_dirs = [Config.MARKET_DATA_DIR, "market_data", "marketData"]
        candidates = []
        for sdir in set(search_dirs):
            if os.path.exists(sdir):
                candidates.extend(glob.glob(os.path.join(sdir, "us_market_data_*.json")))
                candidates.extend(glob.glob(os.path.join(sdir, "usMarketData*.json")))
                candidates.extend(glob.glob(os.path.join(sdir, "*.json")))
        candidates.extend(glob.glob("us_market_data_*.json"))
        candidates.extend(glob.glob("US_Market_Data_*.json"))
        candidates.extend(glob.glob("usMarketData*.json"))
        local_files = candidates

    if local_files:
        return sorted(set(local_files), reverse=True)
    return []


def _load_from_local() -> Optional[dict]:
    """로컬 파일시스템에서 최신 유효 리서치 데이터를 로드합니다."""
    candidates = _find_local_candidate_files()
    for local_file in candidates:
        try:
            with open(local_file, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            is_fresh, reason = is_research_fresh(parsed, local_file)
            if is_fresh:
                print(f"[Research 로드] [OK] 로컬 최신 유효 파일 로드: {local_file} ({reason})")
                return parsed
            else:
                print(f"[Research 로드 WARN] 로컬 파일 만료 배제: {local_file} -> {reason}")
        except Exception as e:
            print(f"[Research 로드 WARN] 로컬 파일 읽기 실패 ({local_file}): {e}")
    return None


def _load_from_env() -> Optional[dict]:
    """환경변수 MARKET_RESEARCH_JSON 에서 데이터를 로드합니다."""
    if not Config.MARKET_RESEARCH_JSON:
        return None
    try:
        parsed = json.loads(Config.MARKET_RESEARCH_JSON)
        is_fresh, reason = is_research_fresh(parsed, "ENV")
        if is_fresh:
            print(f"[Research 로드] [OK] 환경변수 MARKET_RESEARCH_JSON 로드 ({reason})")
            return parsed
        else:
            print(f"[Research 로드 WARN] 환경변수 MARKET_RESEARCH_JSON 만료 배제 -> {reason}")
            return None
    except Exception as e:
        print(f"[Research 로드 WARN] MARKET_RESEARCH_JSON 파싱 실패: {e}")
        return None



def _get_or_create_drive_folder(drive_service, folder_name: str = "US_Market_Deep_Research") -> Optional[str]:
    """구글 드라이브 내 지정 폴더 ID 조회 혹은 생성"""
    try:
        q = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res = drive_service.files().list(
            q=q,
            fields="files(id, name)",
            spaces="drive",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        body = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        created = drive_service.files().create(body=body, fields="id", supportsAllDrives=True).execute()
        print(f"[Google Drive] 폴더 생성 완료: {folder_name} (ID: {created.get('id')})")
        return created.get("id")
    except Exception as e:
        print(f"[Google Drive WARN] 폴더 확인/생성 실패: {e}")
        return None


def _load_from_google_drive() -> Optional[dict]:
    """
    서비스 계정과 공유된 구글 드라이브에서 리서치 JSON을 탐색:
    1. root(루트)에 있는 리서치 JSON 파일 우선 탐색
    2. 유효한 파일 발견 시 파싱 후 'US_Market_Deep_Research' 폴더로 이동 (아카이빙)
    3. 루트에 없으면 이미 'US_Market_Deep_Research' 폴더에 보관된 당일 최신 파일 탐색
    """
    try:
        import google.auth
        from googleapiclient.discovery import build
        import io
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        print("[Google Drive WARN] google-api-python-client 미설치로 Drive 탐색 스킵")
        return None

    try:
        scopes = [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file"
        ]
        credentials, _ = google.auth.default(scopes=scopes)
        drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)

        q = "mimeType != 'application/vnd.google-apps.folder' and trashed = false and name contains '.json'"
        res = drive_service.files().list(
            q=q,
            fields="files(id, name, parents, createdTime, modifiedTime)",
            orderBy="modifiedTime desc",
            pageSize=30,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        files = res.get("files", [])
        if not files:
            print("[Google Drive] 공유된 JSON 파일이 없습니다.")
            return None

        target_folder_name = "US_Market_Deep_Research"
        archive_folder_id = _get_or_create_drive_folder(drive_service, target_folder_name)

        candidates_in_root = []
        candidates_in_archive = []

        for f in files:
            fname = f.get("name", "")
            parents = f.get("parents", [])
            if not any(k in fname.lower() for k in ["market", "research", "deep", "data", "us_"]):
                continue

            if archive_folder_id and archive_folder_id in parents:
                candidates_in_archive.append(f)
            else:
                candidates_in_root.append(f)

        ordered_candidates = candidates_in_root + candidates_in_archive

        for file_info in ordered_candidates:
            fid = file_info["id"]
            fname = file_info["name"]
            try:
                request = drive_service.files().get_media(fileId=fid)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()

                content = fh.getvalue().decode("utf-8")
                parsed = json.loads(content)

                is_fresh, reason = is_research_fresh(parsed, fname)
                if is_fresh:
                    print(f"[Google Drive 로드] [OK] 구글 드라이브 최신 유효 리서치 확인: {fname} ({reason})")

                    if archive_folder_id and (archive_folder_id not in file_info.get("parents", [])):
                        try:
                            prev_parents = ",".join(file_info.get("parents", []))
                            drive_service.files().update(
                                fileId=fid,
                                addParents=archive_folder_id,
                                removeParents=prev_parents if prev_parents else None,
                                fields="id, parents",
                                supportsAllDrives=True
                            ).execute()
                            print(f"[Google Drive 이동] [OK] {fname} 파일을 '{target_folder_name}' 폴더로 이동 완료!")
                        except Exception as move_err:
                            print(f"[Google Drive WARN] 파일 이동 실패: {move_err}")

                    try:
                        save_market_research(parsed)
                    except Exception:
                        pass

                    return parsed
                else:
                    print(f"[Google Drive WARN] {fname} 만료/부적합: {reason}")
            except Exception as file_err:
                print(f"[Google Drive WARN] {fname} 다운로드/파싱 실패: {file_err}")

    except Exception as e:
        print(f"[Google Drive WARN] 구글 드라이브 연동 예외: {e}")

    return None

def load_latest_market_research() -> dict:
    """Google Drive -> GCS -> 로컬 -> 환경변수 순으로 최신 리서치 데이터를 로드합니다."""
    drive_data = _load_from_google_drive()
    if drive_data:
        return drive_data

    gcs_data = _load_from_gcs()
    if gcs_data:
        return gcs_data

    local_data = _load_from_local()
    if local_data:
        return local_data

    env_data = _load_from_env()
    if env_data:
        return env_data

    print("[Research 로드] [INFO] 유효한 최신 리서치가 없어 '실시간 구글 검색(Search Grounding) 단독 모드'로 안전하게 운용합니다.")
    return {}


def get_macro_market_context() -> str:
    """매크로 리포트 파일 로드"""
    report_path = Config.MARKET_REPORT_PATH
    if os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            print(f"[매크로 리포트] 파일 읽기 실패: {e}")
    return "미국 주요 지수 변동성 구간, 국채 금리 및 인플레이션 지표 주시 국면."
