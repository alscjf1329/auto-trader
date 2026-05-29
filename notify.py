"""
notify.py - 텔레그램 알림 모듈

사전 설정:
  1. BotFather 에서 봇 생성 후 TOKEN 발급
  2. 봇에게 메시지 한 번 보낸 뒤 CHAT_ID 확인:
       https://api.telegram.org/bot<TOKEN>/getUpdates
  3. .env 에 추가:
       TELEGRAM_BOT_TOKEN=<토큰>
       TELEGRAM_CHAT_ID=<채팅ID>
  4. settings.yaml telegram 섹션 활성화

알림 종류:
  ● 매수 실행    alert_buy()
  ● 매도 실행    alert_sell()
  ● 에러 발생    alert_error()
  ● 국면 전환    alert_regime()
  ● 후보 풀 선정 alert_pool()
  ● 일일 요약    daily_summary()
"""

import os
import json
import traceback
from datetime import datetime
from pathlib import Path

import requests

# ── 환경 변수 ──────────────────────────────────────────────
_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",  "")

# ── settings (순환 import 방지: 직접 yaml 로드) ────────────
_SETTINGS: dict = {}

def _load_settings():
    global _SETTINGS
    yaml_path = Path(__file__).parent / "settings.yaml"
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        _SETTINGS = cfg.get("telegram", {})
    except Exception:
        _SETTINGS = {}

_load_settings()


def _enabled(flag: str = "enabled") -> bool:
    """settings.yaml의 telegram.{flag} 값 반환 (기본 True)"""
    if not _TOKEN or not _CHAT_ID:
        return False
    return bool(_SETTINGS.get(flag, True))


# ── 국면 전환 추적 (프로세스 내 메모리) ────────────────────
_prev_regime: dict[str, bool | None] = {"KR": None, "US": None}


# ══════════════════════════════════════════════════════════
# 기본 전송 함수
# ══════════════════════════════════════════════════════════

def send(text: str, parse_mode: str = "HTML") -> bool:
    """
    텔레그램 메시지 전송.
    실패해도 예외를 raise 하지 않아 메인 로직에 영향 없음.
    """
    if not _TOKEN or not _CHAT_ID:
        return False
    if not _SETTINGS.get("enabled", True):
        return False

    url = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
    payload = {
        "chat_id":    _CHAT_ID,
        "text":       text,
        "parse_mode": parse_mode,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            print(f"[Notify] 텔레그램 전송 실패 {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[Notify] 텔레그램 예외: {e}")
        return False


# ══════════════════════════════════════════════════════════
# 알림 유형별 함수
# ══════════════════════════════════════════════════════════

def alert_buy(
    name: str,
    code: str,
    qty: int,
    price: float,
    amount: float,
    mode: str = "brain",
    atr_src: str = "",
    reason: str = "",
) -> bool:
    """매수 실행 알림"""
    if not _enabled("on_buy"):
        return False

    market = "🇺🇸" if mode.endswith("_us") else "🇰🇷"
    currency = "$" if mode.endswith("_us") else "₩"
    amount_str = (
        f"${amount:,.2f}"  if mode.endswith("_us") else
        f"₩{int(amount):,}"
    )
    price_str = (
        f"${price:,.2f}"   if mode.endswith("_us") else
        f"₩{int(price):,}"
    )
    atr_tag  = f" <i>({atr_src})</i>" if atr_src else ""
    rsn_tag  = f"\n📝 <i>{reason}</i>" if reason else ""

    text = (
        f"{market} <b>🟢 매수 체결</b>\n"
        f"종목: <b>{name}</b> ({code})\n"
        f"수량: {qty:,}주  |  단가: {price_str}\n"
        f"금액: {amount_str}{atr_tag}{rsn_tag}\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send(text)


def alert_sell(
    name: str,
    code: str,
    qty: int,
    price: float,
    mode: str = "brain",
    avg_buy_price: float = 0.0,
    profit_pct: float = 0.0,
    profit_amount: float = 0.0,
    reason: str = "",
) -> bool:
    """매도 실행 알림"""
    if not _enabled("on_sell"):
        return False

    market   = "🇺🇸" if mode.endswith("_us") else "🇰🇷"
    is_us    = mode.endswith("_us")
    price_str = f"${price:,.2f}" if is_us else f"₩{int(price):,}"

    # 손익 표시
    if profit_pct > 0:
        pnl_icon = "📈"
        pnl_color = "+"
    elif profit_pct < 0:
        pnl_icon = "📉"
        pnl_color = ""
    else:
        pnl_icon = "➖"
        pnl_color = ""

    pnl_str = ""
    if profit_pct:
        amt_str = (
            f"${profit_amount:+,.2f}" if is_us else f"{int(profit_amount):+,}원"
        )
        pnl_str = f"\n손익: {pnl_icon} <b>{pnl_color}{profit_pct:.2f}%</b>  ({amt_str})"

    rsn_tag = f"\n📝 <i>{reason}</i>" if reason else ""

    text = (
        f"{market} <b>🔴 매도 체결</b>\n"
        f"종목: <b>{name}</b> ({code})\n"
        f"수량: {qty:,}주  |  단가: {price_str}{pnl_str}{rsn_tag}\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send(text)


def alert_error(
    where: str,
    error: Exception | str,
    traceback_str: str = "",
) -> bool:
    """에러 발생 알림"""
    if not _enabled("on_error"):
        return False

    tb = traceback_str[:300] if traceback_str else ""
    tb_tag = f"\n<pre>{tb}</pre>" if tb else ""

    text = (
        f"⚠️ <b>에러 발생</b>\n"
        f"위치: {where}\n"
        f"내용: <code>{str(error)[:300]}</code>{tb_tag}\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send(text)


def alert_regime(
    is_bull: bool,
    gap_pct: float,
    market: str = "KR",
) -> bool:
    """
    시장 국면 전환 알림.
    이전 상태와 비교해 변경된 경우에만 전송.
    """
    if not _enabled("on_regime"):
        return False

    prev = _prev_regime.get(market)
    _prev_regime[market] = is_bull   # 상태 업데이트

    # 아직 이전 상태 모름 (첫 실행) → 전송 안 함
    if prev is None:
        return False
    # 변화 없으면 전송 안 함
    if prev == is_bull:
        return False

    flag = "🇰🇷" if market == "KR" else "🇺🇸"
    idx  = "KODEX200" if market == "KR" else "QQQ"

    if is_bull:
        icon = "🔆"
        label = "상승 국면 전환 (Bull)"
        desc  = f"{idx} > SMA200 ({gap_pct:+.1f}%)\n신규 매수 재개"
    else:
        icon = "🌑"
        label = "하락 국면 전환 (Bear)"
        desc  = f"{idx} < SMA200 ({gap_pct:+.1f}%)\n신규 매수 차단"

    text = (
        f"{flag} {icon} <b>시장 국면 전환</b>\n"
        f"{label}\n"
        f"{desc}\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send(text)


def alert_pool(
    pool: list[dict],
    market: str = "KR",
) -> bool:
    """
    후보 풀 선정 완료 알림.
    pool: [{"code": ..., "name": ..., "factor_score": ...}, ...]
    """
    if not _enabled("on_pool"):
        return False

    flag = "🇰🇷" if market == "KR" else "🇺🇸"
    lines = []
    for i, s in enumerate(pool[:10], 1):  # 최대 10개
        code  = s.get("code") or s.get("ticker", "")
        name  = s.get("name", code)
        score = s.get("factor_score", 0)
        lines.append(f"{i}. {name} <code>({code})</code>  {score:.3f}")

    text = (
        f"{flag} <b>후보 풀 선정 완료</b> — {len(pool)}종목\n"
        + "\n".join(lines)
        + f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send(text)


def daily_summary(
    trades_today: list[dict] | None = None,
    portfolio_value: float = 0.0,
    market: str = "KR",
) -> bool:
    """
    일일 거래 요약 알림.
    trades_today: 오늘 거래 내역 (journal/logger 형식)
    """
    if not _enabled("daily_summary"):
        return False

    # 오늘 거래 로드 (파라미터 없으면 직접 로드)
    if trades_today is None:
        from datetime import date
        json_path = Path(__file__).parent / "logs" / "trades" / f"{date.today().isoformat()}.json"
        trades_today = []
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                trades_today = json.load(f)

    flag  = "🇰🇷" if market == "KR" else "🇺🇸"
    buys  = [t for t in trades_today if t.get("action") == "BUY"]
    sells = [t for t in trades_today if t.get("action") == "SELL"]

    # 손익 계산
    total_pnl   = sum(float(t.get("profit_amount") or 0) for t in sells)
    pnl_pcts    = [float(t.get("profit_pct") or 0) for t in sells if t.get("profit_pct")]
    wins        = [p for p in pnl_pcts if p > 0]
    losses      = [p for p in pnl_pcts if p <= 0]
    win_rate    = len(wins) / len(pnl_pcts) * 100 if pnl_pcts else 0

    pnl_icon    = "📈" if total_pnl > 0 else ("📉" if total_pnl < 0 else "➖")
    pv_str      = f"₩{int(portfolio_value):,}" if portfolio_value else "—"

    # 매도 상세
    sell_lines = []
    for t in sells:
        pct = float(t.get("profit_pct") or 0)
        icon = "▲" if pct > 0 else "▼"
        sell_lines.append(f"  {icon} {t.get('name','?')}  {pct:+.2f}%")

    sell_detail = "\n".join(sell_lines) if sell_lines else "  없음"

    text = (
        f"{flag} {pnl_icon} <b>일일 거래 요약</b> — {datetime.now().strftime('%Y-%m-%d')}\n"
        f"매수: {len(buys)}건  |  매도: {len(sells)}건\n"
        f"당일 손익: <b>{total_pnl:+,.0f}원</b>\n"
        f"승률: {win_rate:.0f}%  ({len(wins)}승 {len(losses)}패)\n"
        f"포트폴리오: {pv_str}\n"
        f"\n매도 내역:\n{sell_detail}"
    )
    return send(text)


def alert_startup(mode: str, market_open: str, interval: int) -> bool:
    """러너 시작 알림"""
    if not _enabled("on_startup"):
        return False
    text = (
        f"🚀 <b>Auto-Trader 시작</b>\n"
        f"모드: {mode}\n"
        f"장 시작: {market_open}  |  체크 주기: {interval}분\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send(text)
