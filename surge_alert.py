"""
surge_alert.py - 급등 예측 텔레그램 알림 봇

이미 오른 거 알리는 게 아니라, 오르기 직전/초입 신호를 감지합니다.

감지 조건 (독립적, 각각 알림):
  1. 거래량 폭증 돌파: 거래량 > N일 평균의 X배 + 가격 > 전일 고가
  2. BB 스퀴즈 돌파: 밴드 폭이 좁아졌다가 → 상단 돌파 (변동성 압축 후 폭발)
  3. 52주 신고가 돌파: 저항 없는 구간 진입 (모멘텀 가장 강한 시점)
  4. 장초반 거래량 폭발 (KR): 장 시작 30분 거래량 > 전일 총거래량 10%

.env 설정:
  SURGE_BOT_TOKEN=...
  SURGE_CHAT_ID=...

실행:
  python surge_alert.py
  python surge_alert.py --interval 3
"""

import argparse
import os
import time
from datetime import datetime

import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("SURGE_BOT_TOKEN", "")
CHAT_ID = os.getenv("SURGE_CHAT_ID",  "")

# ── 임계값 ────────────────────────────────────────────────────
VOL_RATIO      = float(os.getenv("SURGE_VOL_RATIO",    "3.0"))  # 거래량 평균 대비 배수
VOL_AVG_DAYS   = int(os.getenv("SURGE_VOL_AVG_DAYS",   "20"))   # 거래량 평균 기간
BB_SQUEEZE_THR = float(os.getenv("SURGE_BB_SQUEEZE",   "0.03")) # BB 폭/가격 비율 (3% 이하 = 스퀴즈)
COOLDOWN_MIN   = int(os.getenv("SURGE_COOLDOWN_MIN",   "120"))  # 재알림 방지(분)

_alerted: dict[str, dict] = {}  # {ticker: {signal: datetime}}


def _can_alert(key: str, signal: str) -> bool:
    last = _alerted.get(key, {}).get(signal)
    if last is None:
        return True
    return (datetime.now() - last).total_seconds() >= COOLDOWN_MIN * 60


def _mark_alerted(key: str, signal: str):
    _alerted.setdefault(key, {})[signal] = datetime.now()


def _send(text: str):
    if not TOKEN or not CHAT_ID:
        print(f"[미설정] {text[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[텔레그램 오류] {e}")


def _alert(ticker: str, name: str, signal: str, current: float,
           detail: str, is_us: bool = True):
    if not _can_alert(ticker, signal):
        return
    flag = "🇺🇸" if is_us else "🇰🇷"
    price_str = f"${current:,.2f}" if is_us else f"₩{int(current):,}"
    msg = (
        f"{flag} ⚡ <b>{signal}</b>  {datetime.now().strftime('%H:%M')}\n"
        f"<b>{name}</b>  <code>{ticker}</code>  {price_str}\n"
        f"{detail}"
    )
    _send(msg)
    _mark_alerted(ticker, signal)
    print(f"  → [{signal}] {name} ({ticker}) {price_str} | {detail}")


# ── 미국주식 체크 ─────────────────────────────────────────────
def check_us(watchlist: list[dict]):
    if not watchlist:
        return

    for item in watchlist:
        ticker = item["ticker"]
        name   = item["name"]
        try:
            # 일봉: 1년치 (거래량 평균, 52주 고가, BB 계산용)
            daily = yf.download(ticker, period="1y", interval="1d",
                                auto_adjust=True, progress=False)
            if isinstance(daily.columns, pd.MultiIndex):
                daily.columns = daily.columns.droplevel(1)
            daily = daily.dropna(subset=["Close", "Volume"])
            if len(daily) < VOL_AVG_DAYS + 5:
                continue

            close   = daily["Close"]
            volume  = daily["Volume"]
            high    = daily["High"]

            current    = float(close.iloc[-1])
            today_vol  = float(volume.iloc[-1])
            avg_vol    = float(volume.iloc[-(VOL_AVG_DAYS+1):-1].mean())
            prev_high  = float(high.iloc[-2])
            high_52w   = float(high.iloc[:-1].max())

            # BB
            mid = close.rolling(20).mean()
            std = close.rolling(20).std()
            bb_upper = float(mid.iloc[-1] + 2 * std.iloc[-1])
            bb_lower = float(mid.iloc[-1] - 2 * std.iloc[-1])
            bb_width  = (bb_upper - bb_lower) / float(mid.iloc[-1])
            bb_width_prev = float(
                (mid.iloc[-2] + 2*std.iloc[-2]) - (mid.iloc[-2] - 2*std.iloc[-2])
            ) / float(mid.iloc[-2])

            vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0

            print(f"  [{ticker}] {name} ${current:.2f} | 거래량 {vol_ratio:.1f}x | BB폭 {bb_width:.3f}")

            # ① 거래량 폭증 + 전일 고가 돌파
            if vol_ratio >= VOL_RATIO and current > prev_high:
                _alert(ticker, name, "거래량 폭증 돌파",
                       current,
                       f"거래량 {vol_ratio:.1f}x 평균 | 전일 고가(${prev_high:.2f}) 돌파",
                       is_us=True)

            # ② BB 스퀴즈 후 상단 돌파
            if bb_width_prev <= BB_SQUEEZE_THR and current > bb_upper:
                _alert(ticker, name, "BB스퀴즈 돌파",
                       current,
                       f"밴드폭 {bb_width_prev:.3f} 압축 후 상단(${bb_upper:.2f}) 돌파",
                       is_us=True)

            # ③ 52주 신고가 돌파
            if current > high_52w:
                _alert(ticker, name, "52주 신고가",
                       current,
                       f"전고점 ${high_52w:.2f} 돌파 — 저항 없는 구간 진입",
                       is_us=True)

        except Exception as e:
            print(f"  [{ticker}] 오류: {e}")


# ── 한국주식 체크 ─────────────────────────────────────────────
def check_kr(watchlist: list[dict]):
    if not watchlist:
        return

    try:
        import kis_api
        import yfinance as yf
    except ImportError:
        return

    for item in watchlist:
        code = item["code"]
        name = item["name"]
        try:
            data    = kis_api.get_stock_data(code)
            current = data["current"]
            vol_today = data.get("volume", 0)

            # 일봉 거래량 평균은 yfinance KS 심볼로
            yf_ticker = f"{code}.KS"
            daily = yf.download(yf_ticker, period="60d", interval="1d",
                                auto_adjust=True, progress=False)
            if isinstance(daily.columns, pd.MultiIndex):
                daily.columns = daily.columns.droplevel(1)
            daily = daily.dropna(subset=["Close", "Volume"])

            if len(daily) < VOL_AVG_DAYS + 2:
                print(f"  [{code}] {name} ₩{current:,} | 데이터 부족")
                continue

            close     = daily["Close"]
            volume    = daily["Volume"]
            high      = daily["High"]
            prev_high = float(high.iloc[-2])
            high_52w  = float(high.max())
            avg_vol   = float(volume.iloc[-(VOL_AVG_DAYS+1):-1].mean())

            # BB
            mid = close.rolling(20).mean()
            std = close.rolling(20).std()
            bb_upper      = float(mid.iloc[-1] + 2 * std.iloc[-1])
            bb_width_prev = float(
                (mid.iloc[-2] + 2*std.iloc[-2]) - (mid.iloc[-2] - 2*std.iloc[-2])
            ) / float(mid.iloc[-2])

            vol_ratio = vol_today / avg_vol if avg_vol > 0 else 0
            print(f"  [{code}] {name} ₩{current:,} | 거래량 {vol_ratio:.1f}x | BB폭 {bb_width_prev:.3f}")

            # ① 거래량 폭증 + 전일 고가 돌파
            if vol_ratio >= VOL_RATIO and current > prev_high:
                _alert(code, name, "거래량 폭증 돌파",
                       current,
                       f"거래량 {vol_ratio:.1f}x 평균 | 전일 고가(₩{int(prev_high):,}) 돌파",
                       is_us=False)

            # ② BB 스퀴즈 후 상단 돌파
            if bb_width_prev <= BB_SQUEEZE_THR and current > bb_upper:
                _alert(code, name, "BB스퀴즈 돌파",
                       current,
                       f"밴드폭 {bb_width_prev:.3f} 압축 후 상단(₩{int(bb_upper):,}) 돌파",
                       is_us=False)

            # ③ 52주 신고가 돌파
            if current > high_52w:
                _alert(code, name, "52주 신고가",
                       current,
                       f"전고점 ₩{int(high_52w):,} 돌파",
                       is_us=False)

            # ④ 장초반 거래량 폭발 (9:00~9:30)
            now = datetime.now()
            if 9 <= now.hour < 10 and now.minute < 30:
                prev_total_vol = float(volume.iloc[-2]) if len(volume) >= 2 else 0
                if prev_total_vol > 0 and vol_today / prev_total_vol >= 0.10:
                    _alert(code, name, "장초반 거래량 폭발",
                           current,
                           f"30분 거래량 = 전일 총량의 {vol_today/prev_total_vol*100:.0f}%",
                           is_us=False)

        except Exception as e:
            print(f"  [{code}] 오류: {e}")


# ── 감시 종목 로드 ────────────────────────────────────────────
def _load_watchlist() -> tuple[list, list]:
    us, kr = [], []
    try:
        import yaml
        from pathlib import Path
        cfg_path = Path(__file__).parent / "settings.yaml"
        if not cfg_path.exists():
            return us, kr
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        seen_us, seen_kr = set(), set()
        for s in (cfg.get("stocks_us", []) + cfg.get("universe_us", [])):
            t = s.get("ticker", "")
            if t and t not in seen_us:
                us.append({"ticker": t, "name": s.get("name", t)})
                seen_us.add(t)
        for s in (cfg.get("stocks", []) + cfg.get("universe", [])):
            c = s.get("code", "")
            if c and c not in seen_kr:
                kr.append({"code": c, "name": s.get("name", c)})
                seen_kr.add(c)
    except Exception as e:
        print(f"[설정 로드 실패] {e}")
    return us, kr


# ── 메인 ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=5, help="체크 간격(분, 기본 5)")
    args = parser.parse_args()

    us_list, kr_list = _load_watchlist()
    print(f"[SurgeAlert] 감시 {len(us_list)}개 미국 | {len(kr_list)}개 한국")
    print(f"  조건: 거래량 {VOL_RATIO}x폭증+돌파 | BB스퀴즈돌파 | 52주신고가 | 장초반폭발")
    print(f"  쿨다운 {COOLDOWN_MIN}분 | {args.interval}분 간격\n")

    if not TOKEN:
        print("⚠️  SURGE_BOT_TOKEN 미설정 — 콘솔 출력만\n")

    while True:
        print(f"── {datetime.now().strftime('%H:%M:%S')} ──")
        check_us(us_list)
        check_kr(kr_list)
        print()
        time.sleep(args.interval * 60)


if __name__ == "__main__":
    main()
