"""
verify.py — profit-board 수익 인증 웹훅 전송

거래 발생 시 HMAC-SHA256 서명된 페이로드를 profit-board로 전송.
VERIFY_ENDPOINT / VERIFY_SECRET / VERIFY_USER_ID 미설정 시 무음 스킵.
"""

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone

import requests

_ENDPOINT = os.getenv("VERIFY_ENDPOINT", "").rstrip("/")
_SECRET   = os.getenv("VERIFY_SECRET", "").encode()
_USER_ID  = os.getenv("VERIFY_USER_ID", "")


def report_trade(
    action: str,
    code: str,
    name: str,
    price: float,
    qty: int,
    profit_pct: float = 0.0,
    profit_amount: float = 0.0,
    mode: str = "",
    is_paper: bool = True,
):
    if not (_ENDPOINT and _SECRET and _USER_ID):
        return

    body = {
        "user_id":   _USER_ID,
        "nonce":     str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trade": {
            "action":         action,
            "code":           code,
            "name":           name,
            "price":          price,
            "qty":            qty,
            "profit_pct":     profit_pct,
            "profit_amount":  profit_amount,
            "mode":           mode,
            "is_paper":       is_paper,
        },
    }
    # 서명 대상: 정렬된 compact JSON (공백 없음)
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    sig = hmac.new(_SECRET, payload, hashlib.sha256).hexdigest()

    try:
        requests.post(
            f"{_ENDPOINT}/api/webhook",
            data=payload,
            headers={"Content-Type": "application/json", "X-Signature": sig},
            timeout=5,
        )
    except Exception:
        pass  # ponytail: 인증 실패가 매매를 막아선 안 됨
