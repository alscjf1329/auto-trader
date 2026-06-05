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
"""

import os
import json
from datetime import datetime, date
from pathlib import Path

import requests

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",  "")

_SETTINGS: dict = {}

def _load_settings():
    global _SETTINGS
    yaml_path = Path(__file__).parent / "settings.yaml"
    try:
        import yaml
        with open(yaml_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        _SETTINGS = cfg.get("telegram", {})
        _SETTINGS["_trading"] = cfg.get("trading", {})
        _SETTINGS["_risk"]    = cfg.get("risk", {})
    except Exception:
        _SETTINGS = {}

_load_settings()

_prev_regime: dict[str, bool | None] = {"KR": None, "US": None}

_DIV = "─" * 16


def _enabled(flag: str = "enabled") -> bool:
    if not _TOKEN or not _CHAT_ID:
        return False
    return bool(_SETTINGS.get(flag, True))


# ══════════════════════════════════════════════════════════
# 기본 전송
# ══════════════════════════════════════════════════════════

def send(text: str, parse_mode: str = "HTML") -> bool:
    if not _TOKEN or not _CHAT_ID:
        return False
    if not _SETTINGS.get("enabled", True):
        return False
    url = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if not resp.ok:
            print(f"[Notify] 전송 실패 {resp.status_code}: {resp.text[:100]}")
            return False
        return True
    except Exception as e:
        print(f"[Notify] 예외: {e}")
        return False


# ══════════════════════════════════════════════════════════
# 매수 알림
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
    if not _enabled("on_buy"):
        return False

    is_us   = mode.endswith("_us")
    flag    = "🇺🇸" if is_us else "🇰🇷"
    cur     = "$" if is_us else "₩"

    # 목표가 / 손절가 계산
    tp_pct  = float(_SETTINGS.get("_risk", {}).get("take_profit_pct",   7.0))
    sl_pct  = float(_SETTINGS.get("_trading", {}).get("stop_loss_pct", -5.0))
    ts_pct  = float(_SETTINGS.get("_risk", {}).get("trailing_stop_pct", 5.0))

    target_price = price * (1 + tp_pct / 100)
    stop_price   = price * (1 + sl_pct / 100)

    def fmt(v):
        return f"${v:,.2f}" if is_us else f"₩{int(v):,}"

    lines = [
        f"{flag} <b>🟢 매수</b>  {datetime.now().strftime('%H:%M')}",
        f"<b>{name}</b>  <code>{code}</code>",
        _DIV,
        f"💰 {fmt(price)} × {qty:,}주  =  <b>{fmt(amount)}</b>",
        f"🎯 목표  {fmt(target_price)}  <i>(+{tp_pct:.0f}%)</i>",
        f"🛡 손절  {fmt(stop_price)}  <i>({sl_pct:.0f}%)</i>",
        f"📉 트레일  최고가 -{ts_pct:.0f}% 이탈 시",
    ]
    if reason:
        lines.append(f"📝 <i>{reason}</i>")

    return send("\n".join(lines))


# ══════════════════════════════════════════════════════════
# 매도 알림
# ══════════════════════════════════════════════════════════

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
    buy_date: str = "",
) -> bool:
    if not _enabled("on_sell"):
        return False

    is_us = mode.endswith("_us")
    flag  = "🇺🇸" if is_us else "🇰🇷"

    def fmt(v):
        return f"${v:,.2f}" if is_us else f"₩{int(v):,}"

    # 손익 아이콘
    if profit_pct > 0:
        pnl_icon = "📈"
        pnl_sign = "+"
    elif profit_pct < 0:
        pnl_icon = "📉"
        pnl_sign = ""
    else:
        pnl_icon = "➖"
        pnl_sign = ""

    # 보유기간
    hold_str = ""
    if buy_date:
        try:
            days = (date.today() - date.fromisoformat(buy_date)).days
            hold_str = f"  |  보유 {days}일"
        except Exception:
            pass

    amt_str = (
        f"${profit_amount:+,.2f}" if is_us else f"{int(profit_amount):+,}원"
    )

    lines = [
        f"{flag} <b>🔴 매도</b>  {datetime.now().strftime('%H:%M')}",
        f"<b>{name}</b>  <code>{code}</code>",
        _DIV,
        f"{pnl_icon} <b>{pnl_sign}{profit_pct:.2f}%</b>  ({amt_str}){hold_str}",
        f"💵 {fmt(avg_buy_price)} → {fmt(price)}  ({qty:,}주)",
    ]
    if reason:
        lines.append(f"📝 <i>{reason}</i>")

    return send("\n".join(lines))


# ══════════════════════════════════════════════════════════
# 에러 알림
# ══════════════════════════════════════════════════════════

def alert_error(
    where: str,
    error: Exception | str,
    traceback_str: str = "",
) -> bool:
    if not _enabled("on_error"):
        return False

    # 에러 메시지 핵심만 추출 (첫 줄)
    err_msg = str(error).split("\n")[0][:200]

    lines = [
        f"⚠️ <b>오류 발생</b>  {datetime.now().strftime('%H:%M:%S')}",
        f"📍 {where}",
        f"<code>{err_msg}</code>",
    ]
    return send("\n".join(lines))


# ══════════════════════════════════════════════════════════
# 시장 국면 전환 알림
# ══════════════════════════════════════════════════════════

def alert_regime(
    is_bull: bool,
    gap_pct: float,
    market: str = "KR",
) -> bool:
    if not _enabled("on_regime"):
        return False

    prev = _prev_regime.get(market)
    _prev_regime[market] = is_bull

    if prev is None or prev == is_bull:
        return False

    flag = "🇰🇷" if market == "KR" else "🇺🇸"
    idx  = "KODEX200" if market == "KR" else "QQQ"

    if is_bull:
        lines = [
            f"{flag} 🔆 <b>Bull 전환</b>  {datetime.now().strftime('%m/%d %H:%M')}",
            f"{idx} > SMA200  ({gap_pct:+.1f}%)",
            "✅ 신규 매수 재개",
        ]
    else:
        lines = [
            f"{flag} 🌑 <b>Bear 전환</b>  {datetime.now().strftime('%m/%d %H:%M')}",
            f"{idx} < SMA200  ({gap_pct:+.1f}%)",
            "🚫 신규 매수 전면 차단",
        ]

    return send("\n".join(lines))


# ══════════════════════════════════════════════════════════
# 후보 풀 선정 알림
# ══════════════════════════════════════════════════════════

def alert_pool(
    pool: list[dict],
    market: str = "KR",
) -> bool:
    if not _enabled("on_pool"):
        return False

    flag = "🇰🇷" if market == "KR" else "🇺🇸"
    lines = [f"{flag} <b>후보 풀 선정</b>  {len(pool)}종목", _DIV]

    for i, s in enumerate(pool[:10], 1):
        code  = s.get("code") or s.get("ticker", "")
        name  = s.get("name", code)
        score = s.get("factor_score", 0)
        m1    = s.get("ret_1m", 0)
        lines.append(f"{i}. <b>{name}</b> ({code})  점수 {score:.3f}  1M {m1:+.1f}%")

    return send("\n".join(lines))


# ══════════════════════════════════════════════════════════
# 일일 요약
# ══════════════════════════════════════════════════════════

def daily_summary(
    trades_today: list[dict] | None = None,
    portfolio_value: float = 0.0,
    holdings: list[dict] | None = None,
    market: str = "KR",
) -> bool:
    if not _enabled("daily_summary"):
        return False

    if trades_today is None:
        json_path = Path(__file__).parent / "logs" / "trades" / f"{date.today().isoformat()}.json"
        trades_today = []
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                trades_today = json.load(f)

    flag  = "🇰🇷" if market == "KR" else "🇺🇸"
    is_us = market == "US"
    buys  = [t for t in trades_today if t.get("action") == "BUY"]
    sells = [t for t in trades_today if t.get("action") == "SELL"]

    total_pnl = sum(float(t.get("profit_amount") or 0) for t in sells)
    pnl_pcts  = [float(t.get("profit_pct") or 0) for t in sells if t.get("profit_pct")]
    wins      = [p for p in pnl_pcts if p > 0]
    losses    = [p for p in pnl_pcts if p <= 0]
    win_rate  = len(wins) / len(pnl_pcts) * 100 if pnl_pcts else 0

    pnl_icon = "📈" if total_pnl > 0 else ("📉" if total_pnl < 0 else "➖")
    pnl_str  = f"${total_pnl:+,.2f}" if is_us else f"{int(total_pnl):+,}원"
    pv_str   = f"${portfolio_value:,.2f}" if is_us else f"₩{int(portfolio_value):,}"

    lines = [
        f"{flag} <b>일일 요약</b>  {datetime.now().strftime('%m/%d (%a)')}",
        _DIV,
        f"{pnl_icon} 실현손익  <b>{pnl_str}</b>",
        f"🎯 승률  {win_rate:.0f}%  ({len(wins)}승 {len(losses)}패)",
        f"📋 매수 {len(buys)}건  |  매도 {len(sells)}건",
        f"💼 포트폴리오  {pv_str}",
    ]

    # 매수 내역
    if buys:
        lines.append(f"\n<b>오늘 매수</b>")
        for t in buys:
            p = float(t.get("price", 0))
            q = int(t.get("qty", 0))
            price_str = f"${p:,.2f}" if is_us else f"₩{int(p):,}"
            lines.append(f"  🟢 {t.get('name','?')}  {price_str} × {q}주")

    # 매도 내역
    if sells:
        lines.append(f"\n<b>오늘 매도</b>")
        for t in sells:
            pct  = float(t.get("profit_pct") or 0)
            icon = "▲" if pct > 0 else "▼"
            lines.append(f"  🔴 {t.get('name','?')}  {icon}{abs(pct):.2f}%")

    # 현재 보유 종목 미실현 손익
    if holdings:
        unrealized = sum(float(h.get("evlu_pfls_amt", 0)) for h in holdings)
        ur_str = f"${unrealized:+,.2f}" if is_us else f"{int(unrealized):+,}원"
        ur_icon = "📈" if unrealized > 0 else "📉"
        lines.append(f"\n<b>보유 종목</b>  {len(holdings)}개  {ur_icon} 미실현 {ur_str}")
        for h in holdings[:5]:
            name = h.get("prdt_name", h.get("ovrs_item_name", "?"))
            pct  = float(h.get("evlu_pfls_rt", 0))
            icon = "▲" if pct > 0 else "▼"
            lines.append(f"  {icon} {name}  {pct:+.2f}%")

    return send("\n".join(lines))


# ══════════════════════════════════════════════════════════
# 시작 알림
# ══════════════════════════════════════════════════════════

def alert_startup(mode: str, market_open: str, interval: int) -> bool:
    if not _enabled("on_startup"):
        return False
    lines = [
        f"🚀 <b>Auto-Trader 시작</b>  {datetime.now().strftime('%m/%d %H:%M')}",
        f"모드  {mode}",
        f"한국장  {market_open} KST  |  {interval}분 간격",
    ]
    return send("\n".join(lines))
