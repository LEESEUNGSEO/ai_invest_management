import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, List, Optional
from core.config import Config


def _shared_get_kis_token(base_url: str, appkey: str, appsecret: str, force_refresh: bool = False) -> str:
    """kis_prices와 kis_orders가 공통으로 사용하는 통합 토큰 캐시 (로컬 /tmp + GCS 영속화)"""
    now = time.time()
    cache_path = Config.KIS_TOKEN_CACHE_FILE
    project_id = Config.PROJECT_ID
    bucket_name = Config.GCS_BUCKET_NAME

    # 1. 로컬 /tmp 캐시 확인
    if not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                c = json.load(f)
            if c.get("access_token") and now < float(c.get("expires_at", 0)) - 300:
                return c["access_token"]
        except Exception:
            pass

    # 2. GCS 버킷 캐시 확인
    if not force_refresh and project_id and bucket_name:
        try:
            from google.cloud import storage
            st_client = storage.Client(project=project_id)
            st_blob = st_client.bucket(bucket_name).blob("kis_token_cache.json")
            if st_blob.exists():
                content = st_blob.download_as_text()
                c = json.loads(content)
                if c.get("access_token") and now < float(c.get("expires_at", 0)) - 300:
                    try:
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump(c, f)
                    except Exception:
                        pass
                    return c["access_token"]
        except Exception:
            pass

    # 3. KIS API 호출하여 신규 발급
    body = {
        "grant_type": "client_credentials",
        "appkey": appkey,
        "appsecret": appsecret,
    }
    req = urllib.request.Request(
        f"{base_url}/oauth2/tokenP",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            token = data.get("access_token")
            expires_in = int(data.get("expires_in", 86400))
            if not token:
                raise RuntimeError("KIS 토큰 응답에 access_token이 없습니다.")
            cache_data = {"access_token": token, "expires_at": now + expires_in, "base_url": base_url}
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f)
            except Exception:
                pass
            if project_id and bucket_name:
                try:
                    from google.cloud import storage
                    st_client = storage.Client(project=project_id)
                    st_blob = st_client.bucket(bucket_name).blob("kis_token_cache.json")
                    st_blob.upload_from_string(json.dumps(cache_data), content_type="application/json")
                except Exception:
                    pass
            return token
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"KIS 토큰 요청 실패: HTTP {exc.code}") from exc


def get_secret(secret_id: str) -> str:
    """Google Cloud Secret Manager에서 비밀값 조회 (환경변수 미설정 시 Fallback)"""
    project_id = Config.PROJECT_ID
    if not project_id:
        return ""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        res = client.access_secret_version(request={"name": name})
        return res.payload.data.decode("UTF-8").strip()
    except Exception:
        return ""


class KISOrderClient:
    def __init__(self, is_paper: Optional[bool] = None):
        self.is_paper = Config.KIS_IS_PAPER if is_paper is None else is_paper
        self.base_url = Config.KIS_VTS_URL if self.is_paper else Config.KIS_BASE_URL
        self.app_key = Config.KIS_APP_KEY or get_secret("kis-live-app-key")
        self.app_secret = Config.KIS_APP_SECRET or get_secret("kis-live-app-secret")
        self.cano = Config.KIS_CANO or get_secret("kis-account-cano")
        self.acnt_prdt_cd = Config.KIS_PRDT_CD or get_secret("kis-account-prdt") or "01"

        self._token = None
        self._token_expired_at = 0

    def get_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and time.time() < self._token_expired_at:
            return self._token
        token = _shared_get_kis_token(self.base_url, self.app_key, self.app_secret, force_refresh=force_refresh)
        self._token = token
        self._token_expired_at = time.time() + 3600
        return token

    def get_available_cash_usd(self) -> float:
        """가용 외화 예수금 조회 (외화 + 미결제 예수금 반영)"""
        token = self.get_token()
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NASD",
            "NATN_CD": "840",
            "TR_CRCY_CD": "USD",
            "WCRC_FRCR_DVSN_CD": "02"
        }
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-psamount?{urllib.parse.urlencode(params)}"
        tr_id = "VTRP6504R" if self.is_paper else "TTTS3007R"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                output = data.get("output", {})
                cash = float(output.get("ovrs_ord_psbl_amt", 0.0))
                if cash <= 0:
                    cash = float(output.get("ord_psbl_frcr_amt", 0.0))
                return cash
        except Exception as e:
            print(f"[KIS] 가용 예수금 조회 예외: {e}")
            return 0.0

    def get_account_balance(self) -> Dict[str, Any]:
        """해외주식 잔고 조회"""
        if not all([self.app_key, self.app_secret, self.cano, self.acnt_prdt_cd]):
            return {"holdings": [], "total_eval_usd": 0.0}

        token = self.get_token()
        tr_id = "VTTS3012R" if self.is_paper else "TTTS3012R"
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NASD",
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance?{urllib.parse.urlencode(params)}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                holdings = []
                for item in data.get("output1", []):
                    qty = int(float(item.get("ovrs_cblc_qty", 0)))
                    if qty > 0:
                        holdings.append({
                            "ticker": item.get("ovrs_pdno", "").strip().upper(),
                            "name": item.get("ovrs_item_name", "").strip(),
                            "qty": qty,
                            "avg_price": float(item.get("pchs_avg_pric", 0.0)),
                            "current_price": float(item.get("now_pric2", 0.0)),
                            "eval_profit_rate": float(item.get("evlu_pfls_rt", 0.0))
                        })
                output2 = data.get("output2", {})
                tot_eval = float(output2.get("tot_evlu_pfls_amt", 0.0)) if isinstance(output2, dict) else 0.0
                return {"holdings": holdings, "total_eval_usd": tot_eval}
        except Exception as e:
            print(f"[KIS] 잔고 조회 실패: {e}")
            return {"holdings": [], "total_eval_usd": 0.0}

    def send_order(self, symbol: str, qty: int, price: float, order_type: str, exch_code: Optional[str] = None) -> Dict[str, Any]:
        """해외주식 지정가 주문 전송"""
        if order_type.upper() == "BUY":
            return self.buy_overseas_order(symbol, qty, price, exch_code)
        elif order_type.upper() == "SELL":
            return self.sell_overseas_order(symbol, qty, price, exch_code)
        else:
            raise ValueError(f"지원하지 않는 주문 타입: {order_type}")

    def buy_overseas_order(self, symbol: str, qty: int, price: float, exch_code: Optional[str] = None) -> Dict[str, Any]:
        token = self.get_token()
        exch = (exch_code or "NASD").upper()
        tr_id = "VTTT1002U" if self.is_paper else "TTTT1002U"
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "PDNO": symbol.upper(),
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                res["_exchange"] = exch
                return res
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="replace")
            return {"rt_cd": "1", "msg1": f"HTTP {exc.code}: {err_msg}", "_transport_error": True}
        except Exception as e:
            return {"rt_cd": "1", "msg1": str(e), "_transport_error": True}

    def sell_overseas_order(self, symbol: str, qty: int, price: float, exch_code: Optional[str] = None) -> Dict[str, Any]:
        token = self.get_token()
        exch = (exch_code or "NASD").upper()
        tr_id = "VTTT1006U" if self.is_paper else "TTTT1006U"
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "PDNO": symbol.upper(),
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                res["_exchange"] = exch
                return res
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="replace")
            return {"rt_cd": "1", "msg1": f"HTTP {exc.code}: {err_msg}", "_transport_error": True}
        except Exception as e:
            return {"rt_cd": "1", "msg1": str(e), "_transport_error": True}

    def get_unfilled_orders(self, exch_code: str = "NASD") -> List[Dict[str, Any]]:
        token = self.get_token()
        tr_id = "VTTT3018R" if self.is_paper else "TTTS3018R"
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch_code.upper(),
            "SORT_SQN": "DS",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-nccs?{urllib.parse.urlencode(params)}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                unfilled = []
                for item in data.get("output", []):
                    odno = item.get("odno")
                    qty = int(float(item.get("nccs_qty", 0)))
                    if odno and qty > 0:
                        unfilled.append({
                            "odno": str(odno),
                            "ticker": item.get("pdno", "").strip().upper(),
                            "qty": qty,
                            "price": float(item.get("ft_ord_unpr3", 0.0)),
                            "exchange": exch_code.upper(),
                            "order_type": "BUY" if item.get("sll_buy_dvsn_cd") == "02" else "SELL"
                        })
                return unfilled
        except Exception as e:
            print(f"[KIS] 미체결 조회 실패: {e}")
            return []

    def cancel_order(self, order_no: str, symbol: str, qty: int, exch_code: Optional[str] = None) -> Dict[str, Any]:
        token = self.get_token()
        exch = (exch_code or "NASD").upper()
        tr_id = "VTTT1004U" if self.is_paper else "TTTT1004U"
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order-rvsecncl"
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": exch,
            "PDNO": symbol.upper(),
            "ORGN_ODNO": str(order_no),
            "RVSE_CNCL_DVSN_CD": "02",  # 02: 취소
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": "0",
            "ORD_SVR_DVSN_CD": "0"
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="replace")
            return {"rt_cd": "1", "msg1": f"HTTP {exc.code}: {err_msg}"}
        except Exception as e:
            return {"rt_cd": "1", "msg1": str(e)}


def get_overseas_price(symbol: str, exchange: Optional[str] = None) -> float:
    """해외주식 실시간 시세 조회"""
    app_key = Config.KIS_APP_KEY or get_secret("kis-live-app-key")
    app_secret = Config.KIS_APP_SECRET or get_secret("kis-live-app-secret")
    if not app_key or not app_secret:
        return 0.0

    base_url = Config.KIS_BASE_URL
    token = _shared_get_kis_token(base_url, app_key, app_secret)

    exchanges = [exchange.upper()] if exchange else ["NASD", "NYSE", "AMEX"]
    for exch in exchanges:
        params = {
            "AUTH": "",
            "EXCD": exch,
            "SYMB": symbol.upper()
        }
        url = f"{base_url}/uapi/overseas-price/v1/quotations/price?{urllib.parse.urlencode(params)}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "HHDFS00000300"
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                output = data.get("output", {})
                last_price = float(output.get("last", 0.0))
                if last_price > 0:
                    return last_price
        except Exception:
            continue
    return 0.0
