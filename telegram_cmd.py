"""
telegram_cmd.py - 텔레그램 봇 명령어 핸들러

지원 명령어:
  /help                        명령어 목록
  /status                      현재 시스템 상태
  /holdings                    보유 종목 + 미실현 손익
  /pool                        오늘 후보 풀
  /pnl                         오늘 실현 손익
  /state                       현재 적용 중인 설정값 전체
  /pause                       신규 매수 일시 중단
  /resume                      매수 재개
  /mode                        현재 모드 확인
  /mode brain                  Brain(AI) 모드로 전환
  /mode strategy               Strategy(규칙) 모드로 전환
  /set stop_loss -5.0          손절 기준 변경 (%, -30~0)
  /set take_profit 7.0         익절 기준 변경 (%, 0~100)
  /set buy_limit [n]           한국장 최대 매수 종목 수 (1~10)
  /set buy_limit_us [n]        미국장 최대 매수 종목 수 (1~10)
  /reset                       모든 설정 초기화 (settings.yaml 기본값으로)
  /blacklist                   블랙리스트 조회
  /blacklist add KR 005930     한국 종목 매수 제외 추가
  /blacklist add US TSLA       미국 종목 매수 제외 추가
  /blacklist remove KR 005930  한국 종목 해제
  /blacklist remove US TSLA    미국 종목 해제
  /blacklist clear KR          한국 블랙리스트 전체 초기화
  /blacklist clear US          미국 블랙리스트 전체 초기화
  /blacklist clear             전체 초기화
"""

import os
import json
import time
import requests
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ── 환경변수 ──────────────────────────────────────────────
_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", ""))

_ROOT        = Path(__file__).parent
_STATE_PATH  = _ROOT / "logs" / "bot_state.json"
_TRADES_DIR  = _ROOT / "logs" / "trades"
_POOL_CACHE  = _ROOT / "logs" / "pool_cache.json"
_POOL_US     = _ROOT / "logs" / "pool_cache_us.json"
_REGIME      = _ROOT / "logs" / "regime_cache.json"

_BASE_URL = f"https://api.telegram.org/bot{_TOKEN}"
_DIV = "─" * 16


# ══════════════════════════════════════════════════════════
# 상태 파일 (bot_state.json)
# ══════════════════════════════════════════════════════════

def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return _default_state()
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()


def _save_state(state: dict):
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_state() -> dict:
    return {
        "paused":          False,
        "mode":            None,
        "stop_loss_pct":   None,
        "take_profit_pct": None,
        "buy_limit":       None,
        "buy_limit_us":    None,
        "blacklist":       {"kr": [], "us": []},
        "updated_at":      None,
    }


# ══════════════════════════════════════════════════════════
# Telegram API 헬퍼
# ══════════════════════════════════════════════════════════

def _send(text: str, parse_mode: str = "HTML") -> bool:
    try:
        resp = requests.post(
            f"{_BASE_URL}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        return resp.ok
    except Exception as e:
        print(f"[TelegramCmd] 전송 실패: {e}")
        return False


def _get_updates(offset: int) -> list:
    try:
        resp = requests.get(
            f"{_BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 3, "allowed_updates": ["message"]},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("result", [])
    except Exception:
        pass
    return []


def _is_authorized(chat_id: str) -> bool:
    return str(chat_id) == _CHAT_ID


# ══════════════════════════════════════════════════════════
# 명령어 핸들러
# ══════════════════════════════════════════════════════════

def _cmd_help():
    text = (
        "🤖 <b>Auto-Trader 명령어</b>\n"
        f"{_DIV}\n"
        "<b>조회</b>\n"
        "  /status              시스템 상태\n"
        "  /holdings            보유 종목\n"
        "  /pool                오늘 후보 풀\n"
        "  /pnl                 오늘 손익\n"
        "\n<b>제어</b>\n"
        "  /pause               신규 매수 중단\n"
        "  /resume              매수 재개\n"
        "\n<b>설정</b>\n"
        "  /mode                현재 모드 확인\n"
        "  /mode brain          Brain(AI) 모드 전환\n"
        "  /mode strategy       Strategy(규칙) 모드 전환\n"
        "  /set stop_loss -5.0  손절 기준 (%, -30~0)\n"
        "  /set take_profit 7.0 익절 기준 (%)\n"
        "  /set buy_limit 3     한국 최대 매수\n"
        "  /set buy_limit_us 2  미국 최대 매수\n"
        "  /reset               설정 초기화\n"
        "  /state               현재 설정값 확인\n"
        "\n<b>블랙리스트</b>\n"
        "  /blacklist                     목록 조회\n"
        "  /blacklist add KR 005930       한국 종목 추가\n"
        "  /blacklist add US NVDA         미국 종목 추가\n"
        "  /blacklist remove KR 005930    한국 종목 해제\n"
        "  /blacklist remove US NVDA      미국 종목 해제\n"
        "  /blacklist clear KR            한국 전체 초기화\n"
        "  /blacklist clear US            미국 전체 초기화\n"
        "  /blacklist clear               전체 초기화"
    )
    _send(text)


def _cmd_status():
    import yaml
    state = _load_state()

    # settings.yaml 로드
    try:
        with open(_ROOT / "settings.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        mode      = cfg["trading"]["mode"]
        kr_open   = cfg["trading"].get("market_open",  "09:05")
        kr_close  = cfg["trading"].get("market_close", "15:20")
        us_open   = cfg["trading"].get("market_open_us",  "23:00")
        us_close  = cfg["trading"].get("market_close_us", "04:30")
    except Exception:
        mode, kr_open, kr_close, us_open, us_close = "?", "-", "-", "-", "-"

    # 시장 국면
    regime_kr = regime_us = "?"
    try:
        if _REGIME.exists():
            history = json.loads(_REGIME.read_text(encoding="utf-8"))
            if history:
                last = history[-1]
                kr = last.get("KR", {})
                us = last.get("US", {})
                regime_kr = f"{'🔆Bull' if kr.get('is_bull') else '🌑Bear'} ({kr.get('gap_pct', 0):+.1f}%)" if kr else "?"
                regime_us = f"{'🔆Bull' if us.get('is_bull') else '🌑Bear'} ({us.get('gap_pct', 0):+.1f}%)" if us else "?"
    except Exception:
        pass

    pause_str = "🚫 매수 중단 중" if state.get("paused") else "✅ 정상 운영"

    lines = [
        f"📊 <b>시스템 상태</b>  {datetime.now().strftime('%m/%d %H:%M')}",
        _DIV,
        f"모드  <b>{mode}</b>  |  {pause_str}",
        f"한국장  {kr_open}~{kr_close}  |  국면 {regime_kr}",
        f"미국장  {us_open}~{us_close}  |  국면 {regime_us}",
    ]
    if state.get("updated_at"):
        lines.append(f"마지막 설정변경  {state['updated_at'][:16]}")
    _send("\n".join(lines))


def _cmd_holdings():
    from dotenv import load_dotenv as _ld
    _ld(_ROOT / ".env")
    try:
        import sys
        sys.path.insert(0, str(_ROOT))
        import kis_api

        lines = [f"📦 <b>보유 종목</b>  {datetime.now().strftime('%H:%M')}", _DIV]

        # 한국
        kr = kis_api.get_balance()
        if kr:
            for h in kr:
                name   = h.get("prdt_name", h.get("pdno", "?"))
                pct    = float(h.get("evlu_pfls_rt", 0))
                amt    = int(float(h.get("evlu_pfls_amt", 0)))
                qty    = int(h.get("hldg_qty", 0))
                icon   = "▲" if pct > 0 else "▼"
                lines.append(f"🇰🇷 {name}  {qty}주  {icon}{abs(pct):.2f}%  ({amt:+,}원)")
        else:
            lines.append("🇰🇷 보유 없음")

        # 미국
        try:
            us = kis_api.get_balance_us()
            if us:
                for h in us:
                    name = h.get("ovrs_item_name", h.get("pdno", "?"))
                    pct  = float(h.get("evlu_pfls_rt", 0))
                    amt  = float(h.get("evlu_pfls_amt", 0))
                    qty  = int(h.get("hldg_qty", 0))
                    icon = "▲" if pct > 0 else "▼"
                    lines.append(f"🇺🇸 {name}  {qty}주  {icon}{abs(pct):.2f}%  (${amt:+.2f})")
            else:
                lines.append("🇺🇸 보유 없음")
        except Exception:
            pass

        _send("\n".join(lines))
    except Exception as e:
        _send(f"⚠️ 잔고 조회 실패\n<code>{e}</code>")


def _cmd_pool():
    lines = [f"🗂 <b>오늘 후보 풀</b>", _DIV]

    # 한국
    try:
        if _POOL_CACHE.exists():
            data  = json.loads(_POOL_CACHE.read_text(encoding="utf-8"))
            pool  = data.get("pool", [])
            udata = {d["code"]: d for d in data.get("universe_data", [])}
            lines.append(f"🇰🇷  {len(pool)}종목")
            for code in pool[:8]:
                d    = udata.get(code, {})
                name = d.get("name", code)
                sc   = d.get("factor_score", 0)
                m1   = d.get("ret_1m", 0)
                lines.append(f"  {name} ({code})  {sc:.3f}  1M {m1:+.1f}%")
        else:
            lines.append("🇰🇷 풀 없음 (장 시작 후 생성)")
    except Exception:
        lines.append("🇰🇷 로드 실패")

    # 미국
    try:
        if _POOL_US.exists():
            data  = json.loads(_POOL_US.read_text(encoding="utf-8"))
            pool  = data.get("pool", [])
            udata = {d["ticker"]: d for d in data.get("universe_data", [])}
            lines.append(f"🇺🇸  {len(pool)}종목")
            for ticker in pool[:6]:
                d    = udata.get(ticker, {})
                name = d.get("name", ticker)
                sc   = d.get("factor_score", 0)
                m1   = d.get("ret_1m", 0)
                lines.append(f"  {name} ({ticker})  {sc:.3f}  1M {m1:+.1f}%")
        else:
            lines.append("🇺🇸 풀 없음")
    except Exception:
        lines.append("🇺🇸 로드 실패")

    _send("\n".join(lines))


def _cmd_pnl():
    today = date.today().isoformat()
    path  = _TRADES_DIR / f"{today}.json"
    lines = [f"💰 <b>오늘 손익</b>  {today}", _DIV]

    if not path.exists():
        lines.append("오늘 거래 없음")
        _send("\n".join(lines))
        return

    try:
        trades = json.loads(path.read_text(encoding="utf-8"))
        buys   = [t for t in trades if t.get("action") == "BUY"]
        sells  = [t for t in trades if t.get("action") == "SELL"]
        total  = sum(float(t.get("profit_amount") or 0) for t in sells)
        pcts   = [float(t.get("profit_pct") or 0) for t in sells if t.get("profit_pct")]
        wins   = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p <= 0]

        pnl_icon = "📈" if total > 0 else ("📉" if total < 0 else "➖")
        lines.append(f"{pnl_icon} 실현손익  <b>{int(total):+,}원</b>")
        lines.append(f"매수 {len(buys)}건  |  매도 {len(sells)}건")
        if pcts:
            lines.append(f"승률  {len(wins)}/{len(pcts)}  ({len(wins)/len(pcts)*100:.0f}%)")
        if sells:
            lines.append(f"\n매도 내역")
            for t in sells:
                pct  = float(t.get("profit_pct") or 0)
                icon = "▲" if pct > 0 else "▼"
                lines.append(f"  {icon} {t.get('name','?')}  {pct:+.2f}%")
    except Exception as e:
        lines.append(f"로드 실패: {e}")

    _send("\n".join(lines))


def _cmd_pause():
    state = _load_state()
    if state.get("paused"):
        _send("⚠️ 이미 매수 중단 상태입니다.\n재개하려면 /resume")
        return
    state["paused"]     = True
    state["updated_at"] = datetime.now().isoformat()
    _save_state(state)
    _send("🚫 <b>신규 매수 중단</b>\n다음 사이클부터 매수를 건너뜁니다.\n재개: /resume")


def _cmd_resume():
    state = _load_state()
    if not state.get("paused"):
        _send("✅ 이미 정상 운영 중입니다.")
        return
    state["paused"]     = False
    state["updated_at"] = datetime.now().isoformat()
    _save_state(state)
    _send("✅ <b>매수 재개</b>\n다음 사이클부터 정상 매수합니다.")


def _cmd_set(args: list):
    if len(args) < 2:
        _send("사용법: /set [항목] [값]\n예: /set stop_loss 5.0")
        return

    key, val_str = args[0].lower(), args[1]
    state = _load_state()

    try:
        if key == "stop_loss":
            v = float(val_str)
            if not (-30 <= v <= 0):
                _send("⚠️ 손절 기준은 -30 ~ 0 사이로 입력하세요.\n예: /set stop_loss -5.0")
                return
            # 음수로 저장 (양수 입력도 허용)
            state["stop_loss_pct"] = -abs(v)
            _send(f"✅ 손절 기준 변경  →  <b>{-abs(v):.1f}%</b>")

        elif key == "take_profit":
            v = float(val_str)
            if not (0 < v <= 100):
                _send("⚠️ 익절 기준은 0 ~ 100 사이로 입력하세요.\n예: /set take_profit 7.0")
                return
            state["take_profit_pct"] = v
            _send(f"✅ 익절 기준 변경  →  <b>+{v:.1f}%</b>")

        elif key == "buy_limit":
            v = int(val_str)
            if not (1 <= v <= 10):
                _send("⚠️ 1 ~ 10 사이로 입력하세요.")
                return
            state["buy_limit"] = v
            _send(f"✅ 한국장 최대 매수 종목  →  <b>{v}개</b>")

        elif key == "buy_limit_us":
            v = int(val_str)
            if not (1 <= v <= 10):
                _send("⚠️ 1 ~ 10 사이로 입력하세요.")
                return
            state["buy_limit_us"] = v
            _send(f"✅ 미국장 최대 매수 종목  →  <b>{v}개</b>")

        else:
            _send(f"⚠️ 알 수 없는 항목: {key}\n설정 가능: stop_loss, take_profit, buy_limit, buy_limit_us")
            return

        state["updated_at"] = datetime.now().isoformat()
        _save_state(state)

    except ValueError:
        _send(f"⚠️ 값 형식 오류: <code>{val_str}</code>")


def _cmd_mode(args: list):
    import yaml
    state = _load_state()

    # 인수 없으면 현재 모드 조회
    if not args:
        try:
            with open(_ROOT / "settings.yaml", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            default_mode = cfg["trading"]["mode"]
        except Exception:
            default_mode = "?"
        override = state.get("mode")
        if override:
            _send(f"⚙️ 현재 모드: <b>{override}</b> <i>(봇 설정, 기본값: {default_mode})</i>")
        else:
            _send(f"⚙️ 현재 모드: <b>{default_mode}</b> <i>(settings.yaml 기본값)</i>")
        return

    new_mode = args[0].lower()
    if new_mode not in ("brain", "strategy"):
        _send("⚠️ 사용법: /mode brain  또는  /mode strategy")
        return

    state["mode"]       = new_mode
    state["updated_at"] = datetime.now().isoformat()
    _save_state(state)

    icon = "🧠" if new_mode == "brain" else "📐"
    _send(f"{icon} <b>모드 변경</b>  →  <b>{new_mode}</b>\n다음 사이클부터 적용됩니다.")


def _cmd_reset():
    _save_state(_default_state())
    _send("🔄 <b>설정 초기화</b>\nsettings.yaml 기본값으로 복원됐습니다.")


def _cmd_state():
    state = _load_state()
    import yaml
    try:
        with open(_ROOT / "settings.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        risk    = cfg.get("risk", {})
        trading = cfg.get("trading", {})
        brain   = cfg.get("brain", {})
        defaults = {
            "mode":            trading.get("mode",             "brain"),
            "stop_loss_pct":   trading.get("stop_loss_pct",   -5.0),
            "take_profit_pct": risk.get("take_profit_pct",     7.0),
            "buy_limit":       brain.get("buy_limit",           3),
            "buy_limit_us":    brain.get("buy_limit_us",        3),
        }
    except Exception:
        defaults = {}

    def _val(key):
        v = state.get(key)
        d = defaults.get(key, "?")
        return f"<b>{v}</b> <i>(기본 {d})</i>" if v is not None else f"{d} <i>(기본값)</i>"

    mode_override = state.get("mode")
    mode_str = f"<b>{mode_override}</b> <i>(봇 설정)</i>" if mode_override else f"{defaults.get('mode', '?')} <i>(기본값)</i>"

    lines = [
        "⚙️ <b>현재 설정</b>",
        _DIV,
        f"매수 상태     {'🚫 중단' if state.get('paused') else '✅ 정상'}",
        f"모드          {mode_str}",
        f"손절 기준     {_val('stop_loss_pct')}%",
        f"익절 기준     {_val('take_profit_pct')}%",
        f"한국 매수한도  {_val('buy_limit')}개",
        f"미국 매수한도  {_val('buy_limit_us')}개",
    ]
    bl = state.get("blacklist", {"kr": [], "us": []})
    kr_bl = bl.get("kr", [])
    us_bl = bl.get("us", [])
    lines.append(f"블랙리스트 KR  {', '.join(kr_bl) if kr_bl else '없음'}")
    lines.append(f"블랙리스트 US  {', '.join(us_bl) if us_bl else '없음'}")
    if state.get("updated_at"):
        lines.append(f"변경시각  {state['updated_at'][:16]}")
    _send("\n".join(lines))


def _cmd_blacklist(args: list):
    state = _load_state()
    bl = state.setdefault("blacklist", {"kr": [], "us": []})

    if not args:
        kr = bl.get("kr", [])
        us = bl.get("us", [])
        lines = [
            "🚫 <b>블랙리스트</b>",
            _DIV,
            f"🇰🇷 한국  {len(kr)}종목  " + (", ".join(kr) if kr else "(없음)"),
            f"🇺🇸 미국  {len(us)}종목  " + (", ".join(us) if us else "(없음)"),
            "",
            "<i>/blacklist add KR 005930</i>",
            "<i>/blacklist remove US NVDA</i>",
            "<i>/blacklist clear KR</i>",
        ]
        _send("\n".join(lines))
        return

    subcmd = args[0].lower()

    if subcmd == "add":
        if len(args) < 3:
            _send("사용법: /blacklist add [KR|US] [코드]\n예: /blacklist add KR 005930")
            return
        market = args[1].lower()
        code   = args[2].upper()
        if market not in ("kr", "us"):
            _send("⚠️ 시장은 KR 또는 US만 가능합니다.")
            return
        if code in bl[market]:
            _send(f"⚠️ <b>{code}</b> 는 이미 블랙리스트에 있습니다.")
            return
        bl[market].append(code)
        state["updated_at"] = datetime.now().isoformat()
        _save_state(state)
        flag = "🇰🇷" if market == "kr" else "🇺🇸"
        _send(f"🚫 {flag} <b>{code}</b> 블랙리스트 추가\n이후 매수 대상에서 제외됩니다.")

    elif subcmd == "remove":
        if len(args) < 3:
            _send("사용법: /blacklist remove [KR|US] [코드]\n예: /blacklist remove KR 005930")
            return
        market = args[1].lower()
        code   = args[2].upper()
        if market not in ("kr", "us"):
            _send("⚠️ 시장은 KR 또는 US만 가능합니다.")
            return
        if code not in bl.get(market, []):
            _send(f"⚠️ <b>{code}</b> 는 블랙리스트에 없습니다.")
            return
        bl[market].remove(code)
        state["updated_at"] = datetime.now().isoformat()
        _save_state(state)
        flag = "🇰🇷" if market == "kr" else "🇺🇸"
        _send(f"✅ {flag} <b>{code}</b> 블랙리스트 해제")

    elif subcmd == "clear":
        market = args[1].lower() if len(args) > 1 else None
        if market is None:
            bl["kr"].clear()
            bl["us"].clear()
            state["updated_at"] = datetime.now().isoformat()
            _save_state(state)
            _send("✅ 블랙리스트 전체 초기화")
        elif market in ("kr", "us"):
            bl[market].clear()
            state["updated_at"] = datetime.now().isoformat()
            _save_state(state)
            flag = "🇰🇷" if market == "kr" else "🇺🇸"
            _send(f"✅ {flag} 블랙리스트 초기화")
        else:
            _send("⚠️ 사용법: /blacklist clear  또는  /blacklist clear KR")

    else:
        _send(
            "⚠️ 사용법:\n"
            "  /blacklist\n"
            "  /blacklist add KR 005930\n"
            "  /blacklist remove KR 005930\n"
            "  /blacklist clear KR"
        )


# ══════════════════════════════════════════════════════════
# 메시지 라우터
# ══════════════════════════════════════════════════════════

def _handle(text: str):
    text = text.strip()
    parts = text.split()
    cmd   = parts[0].lower().lstrip("/").split("@")[0]
    args  = parts[1:]

    routes = {
        "help":       lambda: _cmd_help(),
        "status":     lambda: _cmd_status(),
        "holdings":   lambda: _cmd_holdings(),
        "pool":       lambda: _cmd_pool(),
        "pnl":        lambda: _cmd_pnl(),
        "pause":      lambda: _cmd_pause(),
        "resume":     lambda: _cmd_resume(),
        "mode":       lambda: _cmd_mode(args),
        "set":        lambda: _cmd_set(args),
        "reset":      lambda: _cmd_reset(),
        "state":      lambda: _cmd_state(),
        "blacklist":  lambda: _cmd_blacklist(args),
    }

    handler = routes.get(cmd)
    if handler:
        try:
            handler()
        except Exception as e:
            _send(f"⚠️ 명령 처리 오류\n<code>{e}</code>")
    else:
        _send(f"❓ 알 수 없는 명령어: /{cmd}\n전체 목록: /help")


# ══════════════════════════════════════════════════════════
# 폴링 루프
# ══════════════════════════════════════════════════════════

def run_forever(poll_interval: int = 2):
    if not _TOKEN or not _CHAT_ID:
        print("[TelegramCmd] TOKEN 또는 CHAT_ID 없음 — 종료")
        return

    print(f"[TelegramCmd] 봇 시작 (폴링 {poll_interval}초)")
    _send("🤖 <b>봇 명령어 핸들러 시작</b>\n명령어 목록: /help")

    offset = 0
    while True:
        updates = _get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text    = msg.get("text", "")

            if not text.startswith("/"):
                continue
            if not _is_authorized(chat_id):
                requests.post(
                    f"{_BASE_URL}/sendMessage",
                    json={"chat_id": chat_id, "text": "⛔ 권한 없음"},
                    timeout=5,
                )
                continue

            print(f"[TelegramCmd] 명령: {text}")
            _handle(text)

        time.sleep(poll_interval)


if __name__ == "__main__":
    run_forever()
