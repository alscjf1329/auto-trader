"""
journal/logger.py - 매매 이력 기록기

저장 위치:
  logs/trades/YYYY-MM-DD.json  ← 날짜별 상세 이력 (JSON)
  logs/trades.csv              ← 전체 이력 누적 (CSV, 엑셀 호환)
"""

import csv
import json
import os
from datetime import datetime
from pathlib import Path

# 로그 디렉터리 (프로젝트 루트 기준)
LOG_DIR = Path(__file__).parent.parent / "logs"
TRADES_DIR = LOG_DIR / "trades"
CSV_PATH = LOG_DIR / "trades.csv"

# CSV 컬럼 순서
CSV_COLUMNS = [
    "datetime",
    "date",
    "mode",
    "action",       # BUY / SELL
    "code",
    "name",
    "price",        # 체결 현재가
    "qty",          # 수량
    "amount",       # price * qty
    "avg_buy_price",  # 매수 평균가 (매도 시)
    "profit_pct",   # 평가손익률 % (매도 시)
    "profit_amount", # 수익 금액 추정 (매도 시)
    "reason",       # Claude 판단 이유 or 전략명
]


def _ensure_dirs():
    TRADES_DIR.mkdir(parents=True, exist_ok=True)


def _find_buy_date(code: str) -> str:
    """최근 30일 거래 이력에서 해당 종목의 가장 최근 매수일 조회"""
    from datetime import date, timedelta
    today = date.today()
    for delta in range(30):
        d = today - timedelta(days=delta)
        path = TRADES_DIR / f"{d.isoformat()}.json"
        if not path.exists():
            continue
        try:
            trades = json.loads(path.read_text(encoding="utf-8"))
            for t in reversed(trades):
                if t.get("code") == code and t.get("action") == "BUY":
                    return t.get("date", "")
        except Exception:
            continue
    return ""


def _ensure_csv_header():
    """CSV 파일이 없으면 헤더 생성"""
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()


def log_trade(
    action: str,          # "BUY" or "SELL"
    code: str,
    name: str,
    price: int,
    qty: int,
    mode: str = "unknown",
    reason: str = "",
    avg_buy_price: float = 0.0,
    profit_pct: float = 0.0,
):
    """
    매매 한 건을 기록한다.

    runner.py에서 매수/매도 직후 호출:
        logger.log_trade("BUY", code="005930", name="삼성전자", price=75000, qty=1, ...)
    """
    _ensure_dirs()
    _ensure_csv_header()

    now = datetime.now()
    amount = price * qty
    profit_amount = int((price - avg_buy_price) * qty) if action == "SELL" and avg_buy_price else 0

    record = {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "mode": mode,
        "action": action,
        "code": code,
        "name": name,
        "price": price,
        "qty": qty,
        "amount": amount,
        "avg_buy_price": round(avg_buy_price, 2) if avg_buy_price else "",
        "profit_pct": round(profit_pct, 2) if profit_pct else "",
        "profit_amount": profit_amount if profit_amount else "",
        "reason": reason,
    }

    # 1. 날짜별 JSON에 추가
    json_path = TRADES_DIR / f"{now.strftime('%Y-%m-%d')}.json"
    daily = []
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            daily = json.load(f)
    daily.append(record)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, indent=2)

    # 2. 누적 CSV에 한 줄 추가
    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writerow(record)

    action_label = "🟢 매수" if action == "BUY" else "🔴 매도"
    profit_str = f" | 손익 {profit_pct:+.2f}% ({profit_amount:+,}원)" if action == "SELL" and profit_pct else ""
    print(f"[Journal] {action_label} 기록 → {name}({code}) {qty}주 @ {price:,}원{profit_str}")

    # ── 텔레그램 알림 ──────────────────────────────────────
    try:
        import notify
        if action == "BUY":
            notify.alert_buy(
                name=name, code=code, qty=qty, price=price,
                amount=amount, mode=mode,
            )
        elif action == "SELL":
            notify.alert_sell(
                name=name, code=code, qty=qty, price=price,
                mode=mode,
                avg_buy_price=avg_buy_price,
                profit_pct=profit_pct,
                profit_amount=float(profit_amount) if profit_amount else 0.0,
                reason=reason,
                buy_date=_find_buy_date(code),
            )
    except Exception as _ne:
        print(f"[Journal] 텔레그램 알림 실패: {_ne}")
