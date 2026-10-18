import os
import json
import requests
from core.config import Config

TOKEN_FILE = Config.KAKAO_TOKEN_FILE
TMP_TOKEN_FILE = "/tmp/kakao_token_runtime.json"
PROJECT_ID = Config.PROJECT_ID
BUCKET_NAME = Config.GCS_BUCKET_NAME

# Kakao 텍스트 템플릿 제한에 여유를 둔 분할 길이
CHUNK_LIMIT = 160


def _load_token_dict():
    # 0) 환경변수에 토큰이 직접 명시되어 있으면 최우선 사용
    if Config.KAKAO_ACCESS_TOKEN:
        return {
            "access_token": Config.KAKAO_ACCESS_TOKEN,
            "refresh_token": Config.KAKAO_REFRESH_TOKEN,
            "client_id": Config.KAKAO_CLIENT_ID,
        }

    # 1) GCS에 최신 갱신된 카카오 토큰이 있으면 우선 로드
    if PROJECT_ID and BUCKET_NAME:
        try:
            from google.cloud import storage
            client = storage.Client(project=PROJECT_ID)
            blob = client.bucket(BUCKET_NAME).blob("kakao_token.json")
            if blob.exists():
                return json.loads(blob.download_as_text(encoding="utf-8"))
        except Exception:
            pass

    # 2) /tmp 런타임 토큰 확인
    if os.path.exists(TMP_TOKEN_FILE):
        try:
            with open(TMP_TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # 3) 기본 TOKEN_FILE 로드
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[카카오 알림] 토큰 파일 로드 실패: {type(e).__name__}")
    return None


def _save_token_dict(token_data: dict):
    # 1) 항상 쓰기 가능한 /tmp에 우선 저장
    try:
        with open(TMP_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 2) 로컬 TOKEN_FILE이 쓰기 가능하면 저장
    try:
        token_dir = os.path.dirname(os.path.abspath(TOKEN_FILE))
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    # 3) GCS에 영속화
    if PROJECT_ID and BUCKET_NAME:
        try:
            from google.cloud import storage
            client = storage.Client(project=PROJECT_ID)
            blob = client.bucket(BUCKET_NAME).blob("kakao_token.json")
            blob.upload_from_string(
                json.dumps(token_data, ensure_ascii=False, indent=2),
                content_type="application/json"
            )
        except Exception:
            pass


def get_valid_access_token():
    token_data = _load_token_dict()
    if not token_data:
        print("[카카오 알림] kakao_token 데이터를 찾을 수 없습니다. (환경변수 또는 kakao_token.json 필요)")
        return None

    # 만료 여부 검사 (API 호출)
    test_url = "https://kapi.kakao.com/v1/user/access_token_info"
    headers = {"Authorization": f"Bearer {token_data.get('access_token')}"}
    try:
        res = requests.get(test_url, headers=headers, timeout=5)
        if res.status_code == 200:
            return token_data.get("access_token")
    except Exception:
        pass

    # 만료된 경우 refresh_token으로 재발급
    refresh_token = token_data.get("refresh_token")
    client_id = token_data.get("client_id") or Config.KAKAO_CLIENT_ID
    if not refresh_token:
        print("[카카오 알림] refresh_token이 없어 토큰을 자동 갱신할 수 없습니다.")
        return None

    refresh_url = "https://kauth.kakao.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token
    }
    try:
        res = requests.post(refresh_url, data=payload, timeout=10)
        data = res.json()
        if "access_token" in data:
            token_data["access_token"] = data["access_token"]
            if "refresh_token" in data:
                token_data["refresh_token"] = data["refresh_token"]
            _save_token_dict(token_data)
            print("[카카오 알림] Access Token 자동 재발급 완료")
            return token_data["access_token"]
        else:
            print(f"[카카오 알림] 토큰 갱신 실패: {data}")
    except Exception as e:
        print(f"[카카오 알림] 토큰 갱신 통신 오류: {e}")

    return token_data.get("access_token")


def split_message(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """긴 메시지를 줄바꿈 단위로 안전하게 분할"""
    if len(text) <= limit:
        return [text]

    lines = text.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > limit and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def send_kakao_message(text: str) -> bool:
    """카카오톡 '나에게 보내기' 메시지 발송"""
    token = get_valid_access_token()
    if not token:
        print("[카카오 알림 전송 실패] 유효한 액세스 토큰이 없습니다.")
        return False

    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    chunks = split_message(text, limit=CHUNK_LIMIT)
    all_success = True

    for idx, chunk in enumerate(chunks):
        title_prefix = f"({idx+1}/{len(chunks)})\n" if len(chunks) > 1 else ""
        payload = {
            "template_object": json.dumps({
                "object_type": "text",
                "text": title_prefix + chunk,
                "link": {
                    "web_url": "https://www.google.com",
                    "mobile_web_url": "https://www.google.com"
                }
            })
        }
        try:
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            if response.status_code != 200:
                print(f"[카카오 메시지 발송 실패 HTTP {response.status_code}]: {response.text}")
                all_success = False
        except Exception as e:
            print(f"[카카오 메시지 전송 예외]: {e}")
            all_success = False

    return all_success
