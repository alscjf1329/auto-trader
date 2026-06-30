"""
dart_bot.py - DART 공시 파싱 → 텔레그램 알림 + 자동 매수/매도

준비:
  1. https://opendart.fss.or.kr 에서 API 키 무료 발급
  2. .env 에 추가:
       DART_API_KEY=...
       DART_BOT_TOKEN=...   (텔레그램 봇 토큰, 기존 봇과 별개)
       DART_CHAT_ID=...

실행:
  python dart_bot.py
  python dart_bot.py --interval 2   # 2분마다 폴링
  python dart_bot.py --no-trade     # 알림만, 자동매매 비활성화
"""

import argparse
import json
import os
import time
from datetime import datetime, date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DART_KEY  = os.getenv("DART_API_KEY", "")
BOT_TOKEN = os.getenv("DART_BOT_TOKEN", "")
CHAT_ID   = os.getenv("DART_CHAT_ID", "")

# 자동매매 사용 금액 (공시 매수는 보수적으로 소액)
AUTO_BUY_AMOUNT = int(os.getenv("DART_AUTO_BUY_AMOUNT", "100000"))  # 원

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# ── 공시 분류 ─────────────────────────────────────────────────
# (report_nm 에 포함된 키워드 기준)
BULLISH = [
    "자기주식취득",       # 자사주 매입
    "자기주식 취득",
    "영업(잠정)실적",     # 어닝 서프라이즈 확인 후 판단
    "주요사항보고서(영업실적등)",
    "단일판매·공급계약체결",  # 대규모 계약
    "수주공시",
    "유형자산 취득",      # 설비 투자 = 성장 기대
    "주식배당",
    "현금배당",
    "자회사의주요사항보고",
]

BEARISH = [
    "주요사항보고서(유상증자)",   # 유상증자
    "유상증자",
    "전환사채",
    "신주인수권부사채",
    "교환사채",
    "주요사항보고서(회생절차)",
    "회생절차",
    "영업정지",
    "자기주식처분",               # 자사주 매각 (반대)
    "대규모손실",
    "불성실공시법인",
]

WATCHLIST: set[str] = set()  # 감시 종목 코드 (자동매매 대상)
_seen: set[str] = set()      # 이미 처리한 공시 ID


# ── 감시 종목 로드 ─────────────────────────────────────────────
def _load_watchlist():
    try:
        import yaml
        cfg_path = Path(__file__).parent / "settings.yaml"
        if not cfg_path.exists():
            return
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for s in cfg.get("stocks", []) + cfg.get("universe", []):
            WATCHLIST.add(s["code"])
        print(f"[DART] 감시 종목 {len(WATCHLIST)}개 로드")
    except Exception as e:
        print(f"[DART] settings.yaml 로드 실패: {e}")


# ── DART 공시 목록 조회 ───────────────────────────────────────
def _fetch_disclosures() -> list[dict]:
    """오늘 공시 목록 조회 (유가증권 + 코스닥)"""
    today = date.today().strftime("%Y%m%d")
    results = []
    for corp_cls in ("Y", "K"):  # Y=유가증권, K=코스닥
        try:
            res = requests.get(DART_LIST_URL, params={
                "crtfc_key": DART_KEY,
                "bgn_de":    today,
                "end_de":    today,
                "corp_cls":  corp_cls,
                "page_no":   1,
                "page_count": 40,
            }, timeout=10).json()

            if res.get("status") != "000":
                continue
            results.extend(res.get("list", []))
        except Exception as e:
            print(f"[DART] 조회 오류({corp_cls}): {e}")
    return results


# ── 공시 분류 ─────────────────────────────────────────────────
def _classify(report_nm: str) -> str | None:
    """호재/악재/None 반환"""
    for kw in BULLISH:
        if kw in report_nm:
            return "bullish"
    for kw in BEARISH:
        if kw in report_nm:
            return "bearish"
    return None


# ── 텔레그램 전송 ─────────────────────────────────────────────
def _send(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[미설정] {text[:100]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[텔레그램 오류] {e}")


# ── 자동 매수/매도 ────────────────────────────────────────────
def _auto_trade(corp_code: str, corp_name: str, sentiment: str, report_nm: str,
                trade_enabled: bool):
    if not trade_enabled:
        return
    if corp_code not in WATCHLIST:
        return

    try:
        import kis_api
        import settings

        data = kis_api.get_stock_data(corp_code)
        current = data["current"]
        balance_list = kis_api.get_balance()
        balance = {b["pdno"]: b for b in balance_list}

        if sentiment == "bullish" and corp_code not in balance:
            qty = AUTO_BUY_AMOUNT // current
            if qty < 1:
                print(f"  [{corp_code}] 수량 부족 — 매수 스킵")
                return
            print(f"  [{corp_code}] 공시 매수 {qty}주 (₩{current:,})")
            kis_api.buy(corp_code, AUTO_BUY_AMOUNT)
            _send(
                f"🟢 <b>공시 자동매수</b>\n"
                f"<b>{corp_name}</b> ({corp_code})\n"
                f"₩{current:,} × {qty}주\n"
                f"📋 {report_nm}"
            )

        elif sentiment == "bearish" and corp_code in balance:
            holding = balance[corp_code]
            qty = int(holding["hldg_qty"])
            if qty < 1:
                return
            print(f"  [{corp_code}] 공시 매도 {qty}주 (₩{current:,})")
            kis_api.sell(corp_code, qty)
            _send(
                f"🔴 <b>공시 자동매도</b>\n"
                f"<b>{corp_name}</b> ({corp_code})\n"
                f"₩{current:,} × {qty}주\n"
                f"📋 {report_nm}"
            )

    except Exception as e:
        print(f"  [{corp_code}] 자동매매 오류: {e}")


# ── 공시 처리 메인 ────────────────────────────────────────────
def process(disclosures: list[dict], trade_enabled: bool):
    new_count = 0
    for d in disclosures:
        rcept_no  = d.get("rcept_no", "")
        if rcept_no in _seen:
            continue
        _seen.add(rcept_no)
        new_count += 1

        corp_code  = d.get("stock_code", "").zfill(6)
        corp_name  = d.get("corp_name", "")
        report_nm  = d.get("report_nm", "")
        rcept_dt   = d.get("rcept_dt", "")  # YYYYMMDD
        rcept_time = datetime.now().strftime("%H:%M")
        dart_url   = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

        sentiment = _classify(report_nm)
        in_watchlist = corp_code in WATCHLIST

        # 감시 종목이거나 호재/악재 공시면 알림
        if sentiment or in_watchlist:
            icon = "🟢" if sentiment == "bullish" else ("🔴" if sentiment == "bearish" else "📋")
            label = "호재" if sentiment == "bullish" else ("악재" if sentiment == "bearish" else "공시")
            watch_tag = " ⭐감시종목" if in_watchlist else ""

            msg = (
                f"{icon} <b>[{label}]{watch_tag}</b>  {rcept_time}\n"
                f"<b>{corp_name}</b>  <code>{corp_code}</code>\n"
                f"{report_nm}\n"
                f'<a href="{dart_url}">공시 바로가기</a>'
            )
            _send(msg)
            print(f"  [{icon}] {corp_name}({corp_code}) — {report_nm}")

            if sentiment and in_watchlist:
                _auto_trade(corp_code, corp_name, sentiment, report_nm, trade_enabled)
        else:
            # 비감시 + 중립 공시는 로그만
            print(f"  [  ] {corp_name} — {report_nm}")

    if new_count == 0:
        print("  신규 공시 없음")
    else:
        print(f"  신규 공시 {new_count}건 처리")


# ── 메인 루프 ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval",  type=int, default=3,    help="폴링 간격(분, 기본 3)")
    parser.add_argument("--no-trade",  action="store_true",    help="자동매매 비활성화")
    args = parser.parse_args()

    if not DART_KEY:
        print("⚠️  DART_API_KEY 미설정")
        print("   https://opendart.fss.or.kr 에서 무료 발급 후 .env에 추가\n")

    _load_watchlist()

    trade_enabled = not args.no_trade
    print(f"[DART] 시작 — {args.interval}분 간격 | 자동매매: {'ON' if trade_enabled else 'OFF'}")
    print(f"  호재 키워드: {len(BULLISH)}개 | 악재 키워드: {len(BEARISH)}개\n")

    if not BOT_TOKEN:
        print("⚠️  DART_BOT_TOKEN 미설정 — 콘솔 출력만\n")

    while True:
        now = datetime.now()
        print(f"── {now.strftime('%H:%M:%S')} DART 폴링 ──")
        disclosures = _fetch_disclosures()
        process(disclosures, trade_enabled)
        print()
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
