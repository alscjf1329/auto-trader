import json
import time
import requests
from datetime import datetime
from pathlib import Path

import config

BASE_URL = "https://openapivts.koreainvestment.com:29443" if config.IS_PAPER else "https://openapi.koreainvestment.com:9443"
_access_token = None

# KIS API 초당 5회 제한 대응 (0.35초 간격 = 최대 2.8회/초, 여유있게)
_RATE_LIMIT_INTERVAL = 0.35
_last_call_time: float = 0.0
_RATE_LIMIT_ERROR   = "초당 거래건수를 초과"
_TOKEN_EXPIRED_ERROR = "만료된 token"


def _rate_limit():
    """KIS API 호출 간격 조절 (초당 거래건수 초과 방지)"""
    global _last_call_time
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < _RATE_LIMIT_INTERVAL:
        time.sleep(_RATE_LIMIT_INTERVAL - elapsed)
    _last_call_time = time.time()


def _kis_get(url: str, headers: dict, params: dict, retries: int = 3) -> dict:
    """GET 요청 + 속도 제한/토큰 만료 시 자동 재시도"""
    global _access_token
    for attempt in range(retries):
        _rate_limit()
        res = requests.get(url, headers=headers, params=params).json()
        msg = res.get("msg1", "") or res.get("message", "")
        if _RATE_LIMIT_ERROR in msg:
            wait = 1.0 * (attempt + 1)
            print(f"  [KIS] 속도 제한 → {wait:.0f}초 대기 후 재시도 ({attempt+1}/{retries})")
            time.sleep(wait)
            continue
        if _TOKEN_EXPIRED_ERROR in msg:
            _access_token = None
            if _TOKEN_CACHE.exists():
                _TOKEN_CACHE.unlink()
            new_token = get_access_token()
            headers = {**headers, "authorization": f"Bearer {new_token}"}
            print(f"  [KIS] 토큰 만료 → 재발급 후 재시도 ({attempt+1}/{retries})")
            continue
        return res
    return res  # 마지막 응답 그대로 반환

# 토큰 캐시 파일 (하루 1회 발급 제한 대응)
_TOKEN_CACHE = Path(__file__).parent / "logs" / ".kis_token_cache.json"


def _load_cached_token() -> str | None:
    """캐시 파일에서 유효한 토큰 로드"""
    if not _TOKEN_CACHE.exists():
        return None
    try:
        data    = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
        token   = data.get("access_token", "")
        expires = data.get("expires_at", "")
        if not token or not expires:
            return None
        # 만료 1시간 전까지 재사용
        exp_dt = datetime.strptime(expires, "%Y-%m-%d %H:%M:%S")
        if datetime.now() < exp_dt:
            print(f"[KIS] 캐시 토큰 사용 (만료: {expires})")
            return token
    except Exception:
        pass
    return None


def _save_token_cache(token: str, expires_at: str):
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(
        json.dumps({"access_token": token, "expires_at": expires_at},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def get_access_token():
    """액세스 토큰 발급 (캐시 우선, 만료 시 재발급)"""
    global _access_token

    # 1. 메모리 캐시
    if _access_token:
        return _access_token

    # 2. 파일 캐시
    cached = _load_cached_token()
    if cached:
        _access_token = cached
        return _access_token

    # 3. 신규 발급
    url  = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey":     config.APP_KEY,
        "appsecret":  config.APP_SECRET,
    }
    res  = requests.post(url, json=body)
    data = res.json()

    if "access_token" not in data:
        # 이미 유효한 토큰이 있는 경우 만료 시각만 반환되기도 함
        expires = data.get("access_token_token_expired", "")
        if expires and _TOKEN_CACHE.exists():
            # 기존 캐시 토큰 강제 사용
            try:
                cached_data = json.loads(_TOKEN_CACHE.read_text(encoding="utf-8"))
                token = cached_data.get("access_token", "")
                if token:
                    print(f"[KIS] 기존 토큰 재사용 (만료: {expires})")
                    _access_token = token
                    return _access_token
            except Exception:
                pass
        msg = data.get("msg1") or data.get("message") or str(data)
        raise ValueError(f"KIS 토큰 발급 실패: {msg}")

    _access_token = data["access_token"]
    expires_at    = data.get("access_token_token_expired", "")
    if expires_at:
        _save_token_cache(_access_token, expires_at)
        print(f"[KIS] 신규 토큰 발급 (만료: {expires_at})")

    return _access_token


def get_headers(tr_id):
    """공통 헤더"""
    token = _access_token or get_access_token()
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": config.APP_KEY,
        "appsecret": config.APP_SECRET,
        "tr_id": tr_id,
    }


def get_stock_data(code: str) -> dict:
    """현재가 및 기본 데이터 조회"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = get_headers("FHKST01010100")
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code}
    res = _kis_get(url, headers, params)
    if "output" not in res:
        msg = res.get("msg1") or res.get("message") or str(res)
        raise ValueError(f"KIS API 오류 [{code}]: {msg}")
    output = res["output"]
    return {
        "code": code,
        "current": int(output["stck_prpr"]),       # 현재가
        "high_52w": int(output.get("d52_hgpr", 0)),   # 52주 최고가
        "low_52w":  int(output.get("d52_lwpr", 0)), # 52주 최저가
        "open": int(output["stck_oprc"]),           # 시가
        "volume": int(output["acml_vol"]),          # 거래량
        "change_pct": float(output["prdy_ctrt"]),   # 전일 대비 등락률
    }


def get_balance() -> list:
    """주식 잔고 조회"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    tr_id = "VTTC8434R" if config.IS_PAPER else "TTTC8434R"
    headers = get_headers(tr_id)
    params = {
        "CANO": config.ACCT_STOCK,
        "ACNT_PRDT_CD": "01",
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    res = _kis_get(url, headers, params)
    return res.get("output1", [])


def buy(code: str, amount: int):
    """시장가 매수"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    tr_id = "VTTC0802U" if config.IS_PAPER else "TTTC0802U"
    headers = get_headers(tr_id)

    # 현재가로 수량 계산
    current = get_stock_data(code)["current"]
    qty = amount // current
    if qty < 1:
        print(f"[{code}] 매수 금액 부족 (현재가: {current}원, 예산: {amount}원)")
        return

    _rate_limit()
    body = {
        "CANO": config.ACCT_STOCK,
        "ACNT_PRDT_CD": "01",
        "PDNO": code,
        "ORD_DVSN": "01",   # 시장가
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0",
    }
    res = requests.post(url, headers=headers, json=body).json()
    print(f"[{code}] 매수 {qty}주 → {res['msg1']}")


def sell(code: str, qty: int):
    """시장가 매도"""
    _rate_limit()
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    tr_id = "VTTC0801U" if config.IS_PAPER else "TTTC0801U"
    headers = get_headers(tr_id)
    body = {
        "CANO": config.ACCT_STOCK,
        "ACNT_PRDT_CD": "01",
        "PDNO": code,
        "ORD_DVSN": "01",   # 시장가
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0",
    }
    res = requests.post(url, headers=headers, json=body).json()
    print(f"[{code}] 매도 {qty}주 → {res['msg1']}")


# ══════════════════════════════════════════════════════════════
# 해외주식 (미국장)
# ══════════════════════════════════════════════════════════════

def get_stock_data_us(ticker: str, exchange: str) -> dict:
    """
    미국주식 현재가 조회
    exchange: NAS / NYS / AMS
    """
    url = f"{BASE_URL}/uapi/overseas-price/v1/quotations/price"
    headers = get_headers("HHDFS76200200")
    params = {
        "AUTH": "",
        "EXCD": exchange,
        "SYMB": ticker,
    }
    res = _kis_get(url, headers, params)
    out = res.get("output", {})
    def _f(key, default=0.0):
        v = out.get(key)
        return float(v) if v not in (None, "", "-") else default

    return {
        "ticker":     ticker,
        "code":       ticker,           # brain.py 공통 인터페이스 호환
        "exchange":   exchange,
        "current":    _f("last"),       # 현재가 (USD)
        "open":       _f("open"),       # 시가
        "high_52w":   _f("h52p"),       # 52주 최고
        "low_52w":    _f("l52p"),       # 52주 최저
        "volume":     int(out.get("tvol") or 0),       # 거래량
        "change_pct": _f("rate"),       # 등락률(%)
        "market":     "US",
    }


def get_balance_us() -> list:
    """미국주식 잔고 조회"""
    url = f"{BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance"
    tr_id = "VTTS3012R" if config.IS_PAPER else "TTTS3012R"
    headers = get_headers(tr_id)
    params = {
        "CANO":          config.ACCT_OVRS,
        "ACNT_PRDT_CD":  "01",
        "OVRS_EXCG_CD":  "NAS",   # 나스닥 기준 (전체 해외 잔고 포함)
        "TR_CRCY_CD":    "USD",
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": "",
    }
    res = _kis_get(url, headers, params)
    return res.get("output1", [])


def buy_us(ticker: str, exchange: str, amount_usd: float):
    """미국주식 시장가 매수 (달러 기준 금액)"""
    # 현재가로 수량 계산
    current = get_stock_data_us(ticker, exchange)["current"]
    if current <= 0:
        print(f"[{ticker}] 현재가 조회 실패")
        return
    qty = int(amount_usd / current)
    if qty < 1:
        print(f"[{ticker}] 매수 금액 부족 (현재가: ${current:.2f}, 예산: ${amount_usd})")
        return

    url = f"{BASE_URL}/uapi/overseas-stock/v1/trading/order"
    tr_id = "VTTT1002U" if config.IS_PAPER else "TTTT1002U"
    headers = get_headers(tr_id)
    body = {
        "CANO":         config.ACCT_OVRS,
        "ACNT_PRDT_CD": "01",
        "OVRS_EXCG_CD": exchange,
        "PDNO":         ticker,
        "ORD_DVSN":     "00",       # 지정가 (미국 시장가는 00으로 처리)
        "ORD_QTY":      str(qty),
        "OVRS_ORD_UNPR": "0",       # 시장가
        "ORD_SVR_DVSN_CD": "0",
        "ODNO": "",
    }
    res = requests.post(url, headers=headers, json=body).json()
    print(f"[{ticker}] 매수 {qty}주 @ ${current:.2f} → {res.get('msg1', '')}")


def sell_us(ticker: str, exchange: str, qty: int):
    """미국주식 시장가 매도"""
    url = f"{BASE_URL}/uapi/overseas-stock/v1/trading/order"
    tr_id = "VTTT1006U" if config.IS_PAPER else "TTTT1006U"
    headers = get_headers(tr_id)
    body = {
        "CANO":         config.ACCT_OVRS,
        "ACNT_PRDT_CD": "01",
        "OVRS_EXCG_CD": exchange,
        "PDNO":         ticker,
        "ORD_DVSN":     "00",
        "ORD_QTY":      str(qty),
        "OVRS_ORD_UNPR": "0",
        "ORD_SVR_DVSN_CD": "0",
        "ODNO": "",
    }
    res = requests.post(url, headers=headers, json=body).json()
    print(f"[{ticker}] 매도 {qty}주 → {res.get('msg1', '')}")


# ══════════════════════════════════════════════════════════════
# 수급 데이터 (Brain 모드 Stage 1용)
# ══════════════════════════════════════════════════════════════

def get_investor_flow(code: str) -> dict:
    """
    종목별 투자자별 매매동향 (외국인·기관·개인 순매수)
    TR: FHKST03010100
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = get_headers("FHKST03010100")
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code,
    }
    try:
        res = _kis_get(url, headers, params)
        out = res.get("output", {})
        return {
            "code": code,
            # 외국인 순매수 수량 (양수=순매수, 음수=순매도)
            "foreign_net": int(out.get("frgn_ntby_qty", 0)),
            # 기관 순매수 수량
            "inst_net": int(out.get("orgn_ntby_qty", 0)),
            # 개인 순매수 수량
            "retail_net": int(out.get("indv_ntby_qty", 0)),
        }
    except Exception:
        return {"code": code, "foreign_net": 0, "inst_net": 0, "retail_net": 0}


def get_market_index() -> dict:
    """
    코스피·코스닥 지수 현황 (시장 전체 분위기 파악용)
    TR: FHPUP02100000
    """
    result = {}
    for market_code, label in [("0001", "KOSPI"), ("1001", "KOSDAQ")]:
        url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-index-price"
        headers = get_headers("FHPUP02100000")
        params = {
            "fid_cond_mrkt_div_code": "U",
            "fid_input_iscd": market_code,
        }
        try:
            out = _kis_get(url, headers, params).get("output", {})
            result[label] = {
                "current": float(out.get("bstp_nmix_prpr", 0)),
                "change_pct": float(out.get("bstp_nmix_prdy_ctrt", 0)),
                "volume": int(out.get("acml_vol", 0)),
            }
        except Exception:
            result[label] = {"current": 0, "change_pct": 0, "volume": 0}
    return result


def get_sector_flow() -> list[dict]:
    """
    업종별 등락 현황 — 어떤 섹터에 수급이 몰리는지
    TR: FHPUP02280000
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    # 업종 시세는 별도 TR 사용
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-index-category-price"
    headers = get_headers("FHPUP02280000")
    params = {
        "fid_cond_mrkt_div_code": "U",
        "fid_input_iscd": "0001",   # 코스피 전 업종
        "fid_trgt_cls_code": "0",
    }
    try:
        res = _kis_get(url, headers, params)
        rows = res.get("output", []) or []
        sectors = []
        for r in rows[:15]:   # 상위 15개 업종
            sectors.append({
                "name": r.get("hts_kor_isnm", ""),
                "change_pct": float(r.get("bstp_nmix_prdy_ctrt", 0)),
                "volume": int(r.get("acml_vol", 0)),
            })
        return sectors
    except Exception:
        return []
