import os
import json
import urllib.parse
import requests
from core.config import Config


def issue_kakao_token():
    """카카오 OAuth 2.0 인증을 거쳐 kakao_token.json 초기 토큰을 발급받는 대화형 함수"""
    default_client_id = Config.KAKAO_CLIENT_ID
    prompt_msg = (
        f"1. 카카오 REST API 키를 입력하세요 (기본값: {default_client_id or '없음'}): "
        if default_client_id
        else "1. 카카오 REST API 키를 입력하세요: "
    )
    user_input = input(prompt_msg).strip()
    client_id = user_input or default_client_id

    if not client_id:
        print("[오류] 카카오 REST API 키가 입력되지 않았습니다.")
        return False

    redirect_uri = "http://localhost:5000/oauth"
    auth_url = (
        f"https://kauth.kakao.com/oauth/authorize?client_id={client_id}"
        f"&redirect_uri={redirect_uri}&response_type=code&scope=talk_message"
    )

    print("\n" + "=" * 70)
    print("2. 아래 링크를 복사하여 브라우저 주소창에 넣고 로그인/동의를 진행하십시오:")
    print(auth_url)
    print("=" * 70 + "\n")

    print("로그인 완료 후 브라우저가 '연결할 수 없음' 또는 빈 화면으로 멈춥니다. 정상입니다.")
    redirected_url = input("3. 멈춘 브라우저 주소창의 전체 URL을 복사하여 여기에 붙여넣으세요: ").strip()

    if "code=" in redirected_url:
        code = redirected_url.split("code=")[1].split("&")[0]
    else:
        code = redirected_url

    token_url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code
    }

    try:
        res = requests.post(token_url, data=data, timeout=15).json()
    except Exception as e:
        print("\n[오류] 카카오 토큰 서버 통신 실패:", e)
        return False

    if "access_token" in res:
        token_data = {
            "client_id": client_id,
            "access_token": res["access_token"],
            "refresh_token": res["refresh_token"]
        }
        save_path = Config.KAKAO_TOKEN_FILE or "kakao_token.json"
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)
        print(f"\n[성공] {save_path} 파일이 성공적으로 생성되었습니다!")
        print(f"access_token: {res['access_token'][:10]}...")
        print(f"refresh_token: {res['refresh_token'][:10]}...")
        print("\n[안내] GitHub 업로드 시 kakao_token.json은 .gitignore에 포함되어 커밋되지 않으므로,")
        print("환경변수 KAKAO_ACCESS_TOKEN / KAKAO_REFRESH_TOKEN으로 등록해 사용하실 수도 있습니다.")
        return True
    else:
        print("\n[오류] 토큰 발급 실패:", res)
        return False


if __name__ == "__main__":
    issue_kakao_token()
