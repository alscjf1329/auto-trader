from dotenv import load_dotenv
load_dotenv()

import json
import logging
import schedule
import time
from datetime import datetime
from pathlib import Path
import kis_api
import settings
from journal import logger

# ── 파일 로그 설정 (dashboard에서 읽음) ──────────────────────
_LOG_PATH = Path(__file__).parent / "logs" / "runner.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
_log = logging.getLogger("runner")


# ── stdout → log file Tee (brain.py/factor.py의 print()도 캡처) ──
class _Tee:
    """sys.stdout을 콘솔 + 파일 양쪽에 동시 출력"""
    def __init__(self, file_path: Path):
        self._file   = open(file_path, "a", encoding="utf-8")
        self._stdout = sys.__stdout__

    def write(self, data: str):
        self._stdout.write(data)
        if data.strip():                          # 빈 줄은 파일에 안 씀
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._file.write(f"{ts} {data}" if not data.startswith("\n") else data)
        self._file.flush()

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def __getattr__(self, name):                  # isatty 등 나머지 속성 위임
        return getattr(self._stdout, name)


import sys
sys.stdout = _Tee(_LOG_PATH)

import os
import notify   # 텔레그램 알림 (stdout Tee 설정 후 import)
from journal.snapshot import save_snapshot


# ══════════════════════════════════════════════════════════════
# 실전 안전장치 (7순위)
# ══════════════════════════════════════════════════════════════

def _check_live_safety():
    """
    KIS_IS_PAPER=false 인데 LIVE_TRADING_CONFIRMED=yes 가 없으면 강제 종료.
    실수로 실전 매매 전환하는 사고 방지.
    """
    is_paper = os.getenv("KIS_IS_PAPER", "true").lower() in ("true", "1", "yes")
    if is_paper:
        print("[Safety] 모의투자 모드 (KIS_IS_PAPER=true)")
        return

    confirmed = os.getenv("LIVE_TRADING_CONFIRMED", "").strip().lower()
    if confirmed != "yes":
        msg = (
            "\n" + "=" * 60 + "\n"
            "⛔  실전 매매 차단!\n"
            "  KIS_IS_PAPER=false 이지만 LIVE_TRADING_CONFIRMED가 없습니다.\n"
            "  실전 매매를 원하면 .env 에 아래를 추가하세요:\n"
            "    LIVE_TRADING_CONFIRMED=yes\n"
            "  (모의투자: KIS_IS_PAPER=true)\n"
            + "=" * 60
        )
        print(msg)
        notify.send("⛔ <b>실전 매매 차단</b>\n.env에 LIVE_TRADING_CONFIRMED=yes 필요")
        raise SystemExit(1)

    # 실전 매매 확인된 경우 경고 출력
    print("⚠️  [실전 매매 모드] KIS_IS_PAPER=false + LIVE_TRADING_CONFIRMED=yes")
    notify.send(
        "⚠️ <b>실전 매매 시작</b>\n"
        "실제 계좌로 거래합니다. 이상 감지 시 즉시 KIS_IS_PAPER=true 로 변경하세요."
    )


_check_live_safety()


# ══════════════════════════════════════════════════════════════
# 당일 손실 한도 체크 (7순위)
# ══════════════════════════════════════════════════════════════

def _bot_state() -> dict:
    """bot_state.json 로드 — 텔레그램 명령어로 변경된 설정값"""
    path = Path(__file__).parent / "logs" / "bot_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _daily_loss_exceeded(market: str = "KR") -> bool:
    """
    오늘 실현 손실이 settings.SAFETY_DAILY_LOSS_LIMIT 초과 여부 확인.
    초과 시 신규 매수를 막는다 (매도는 계속 허용).
    """
    if market == "KR":
        limit = settings.SAFETY_DAILY_LOSS_LIMIT_KRW
    else:
        limit = settings.SAFETY_DAILY_LOSS_LIMIT_USD * 1350  # USD → KRW 추정

    if limit <= 0:
        return False  # 0이면 비활성화

    from datetime import date as _date
    from journal.logger import TRADES_DIR
    today_path = TRADES_DIR / f"{_date.today().isoformat()}.json"
    if not today_path.exists():
        return False

    try:
        import json as _json
        trades = _json.loads(today_path.read_text(encoding="utf-8"))
        daily_loss = sum(
            float(t.get("profit_amount") or 0)
            for t in trades
            if t.get("action") == "SELL" and float(t.get("profit_amount") or 0) < 0
        )
        if abs(daily_loss) >= limit:
            msg = f"당일 손실 {daily_loss:,.0f}원 ≥ 한도 {limit:,.0f}원"
            print(f"[Safety] 🛑 {msg} — 신규 매수 중단")
            notify.alert_error("[Safety] 일일 손실 한도 초과", msg)
            return True
    except Exception:
        pass
    return False

# ── 전략 팩토리 ───────────────────────────────────────────
def _create_strategy():
    """settings.yaml의 strategy.name에 따라 전략 객체 생성"""
    name = settings.STRATEGY_NAME
    if name == "regime_adaptive":
        from strategies.regime_adaptive import RegimeAdaptiveStrategy
        return RegimeAdaptiveStrategy()
    elif name == "momentum":
        from strategies.momentum import MomentumStrategy
        return MomentumStrategy()
    elif name == "dual_momentum":
        from strategies.dual_momentum import DualMomentumStrategy
        return DualMomentumStrategy()
    else:
        raise ValueError(
            f"알 수 없는 전략: '{name}'\n"
            f"settings.yaml → strategy.name 을 확인하세요.\n"
            f"사용 가능: regime_adaptive, momentum, dual_momentum"
        )

strategy = _create_strategy()


# ── API 에러 공통 처리 ────────────────────────────────────
def _handle_api_error(where: str, e: Exception):
    """Anthropic API 에러 처리 — 크레딧 소진은 별도 알림"""
    err_msg = str(e)
    if "credit balance is too low" in err_msg or "credits" in err_msg.lower():
        msg = "Anthropic API 크레딧이 소진됐습니다.\nhttps://console.anthropic.com → Billing → Add Credits"
        print(f"[API] 크레딧 소진 — 매매 중단")
        notify.send(f"💳 <b>API 크레딧 소진</b>\n{msg}")
    else:
        notify.alert_error(where, e)
    print(f"[{where}] 오류: {e}")


# ── Brain 모드 ────────────────────────────────────────────
def run_brain_mode():
    import brain
    import risk as risk_engine
    print("\n===== [Brain] Claude AI 매매 =====")

    # ── Stage 1: AI가 유니버스에서 후보 풀 선정 (캐시 활용) ──
    try:
        pool_codes = brain.get_candidate_pool()
    except Exception as e:
        _handle_api_error("[Brain] Stage1 풀 선정", e)
        return
    if not pool_codes:
        msg = "Stage1 후보 풀이 비어있습니다. AI 응답 이상 또는 유니버스 데이터 오류."
        print(f"[Brain] {msg}")
        notify.alert_error("[Brain] 후보 풀 비어있음", msg)
        return

    # ── Stage 2: 후보 풀 실시간 데이터 수집 (KIS) ───────────
    universe_cache = brain.get_universe_cache()   # ATR / 52w 캐시
    market_data = []
    fail_count = 0
    for code in pool_codes:
        try:
            data = kis_api.get_stock_data(code)
            data["name"] = settings.UNIVERSE_MAP.get(code, code)
            cached = universe_cache.get(code, {})
            data.setdefault("atr",      cached.get("atr", 0))
            data.setdefault("high_52w", cached.get("high_52w", data.get("high_52w", 0)))
            data.setdefault("low_52w",  cached.get("low_52w",  data.get("low_52w",  0)))
            market_data.append(data)
        except Exception as e:
            print(f"  [{code}] 데이터 수집 실패: {e}")
            fail_count += 1

    if not market_data:
        msg = f"KIS 시세 조회 전체 실패 ({fail_count}종목)"
        print(f"[Brain] {msg}")
        notify.alert_error("[Brain] 시장 데이터 전체 실패", msg)
        return
    elif fail_count > len(pool_codes) // 2:
        notify.alert_error("[Brain] 시세 조회 다수 실패", f"{fail_count}/{len(pool_codes)}종목 실패")

    # ── 시장 국면 체크 (SMA200) ─────────────────────────────
    regime = brain.get_market_regime()
    notify.alert_regime(regime["is_bull"], regime.get("gap_pct", 0), market="KR")

    # ── Stage 3: AI가 후보 풀에서 최종 매수 종목 선정 ────────
    try:
        targets = brain.get_targets(market_data)
    except Exception as e:
        _handle_api_error("[Brain] Stage2 매수 선정", e)
        targets = []

    # ── 포트폴리오 가치 계산 ─────────────────────────────────
    balance_list = kis_api.get_balance()
    balance = {b["pdno"]: b for b in balance_list}
    portfolio_value = sum(float(b.get("evlu_amt", 0)) for b in balance_list)
    if portfolio_value == 0:
        portfolio_value = settings.MAX_BUY_AMOUNT * settings.RISK_MAX_POSITIONS  # 초기 추정

    # ── 매도 판단: 현재 보유 종목 전체 검토 ─────────────────
    for code, holding in balance.items():
        try:
            # 보유 종목이 후보 풀에 없을 수도 있으므로 KIS에서 별도 조회
            held_data = next((d for d in market_data if d["code"] == code), None)
            if held_data is None:
                held_data = kis_api.get_stock_data(code)
                held_data["name"] = settings.UNIVERSE_MAP.get(code, code)

            current_price = held_data["current"]
            avg_price     = float(holding.get("pchs_avg_pric", 0))
            profit_pct    = float(holding.get("evlu_pfls_rt", 0))

            # ── 트레일링 스탑: 최고가 업데이트 → 발동 체크 ──────
            risk_engine.trailing_stop.update(code, current_price)

            should_sell_flag = False
            sell_reason      = ""

            if risk_engine.trailing_stop.check(code, current_price):
                should_sell_flag = True
                stop_price = risk_engine.trailing_stop.get_stop_price(code)
                sell_reason = (
                    f"트레일링 스탑 {settings.RISK_TRAILING_STOP_PCT}% "
                    f"(최고가 대비 {stop_price:,.0f}원 이탈)"
                )
            elif brain.should_sell(held_data, holding):
                should_sell_flag = True
                sell_reason = "AI 매도 판단"

            if should_sell_flag:
                qty = int(holding["hldg_qty"])
                print(f"  [{code}] 매도 {qty}주 — {sell_reason}")
                kis_api.sell(code, qty)
                logger.log_trade("SELL", code=code, name=held_data["name"],
                                 price=current_price, qty=qty, mode="brain",
                                 reason=sell_reason,
                                 avg_buy_price=avg_price, profit_pct=profit_pct)
                risk_engine.trailing_stop.remove(code)
        except Exception as e:
            print(f"  [{code}] 매도 오류: {e}")
            notify.alert_error(f"[Brain] 매도 {code}", e)

    # ── 매수 실행: AI 선정 종목 ───────────────────────────────
    # 잔고를 다시 조회해 매도 후 상태 반영
    balance_list = kis_api.get_balance()
    balance = {b["pdno"]: b for b in balance_list}

    # 텔레그램 봇 상태 로드
    bot = _bot_state()

    # 봇 명령어로 일시 중단된 경우
    if bot.get("paused"):
        print("[Brain] 텔레그램 봇 명령으로 매수 중단 중 (/resume 으로 재개)")
        targets = []

    # bear 국면이면 신규 매수 전체 차단
    if targets and settings.REGIME_FILTER and not regime["is_bull"]:
        print(f"[Brain] 하락장 국면 (KODEX200 < SMA200 {regime['gap_pct']:+.1f}%) — 신규 매수 차단")
        targets = []

    # 당일 손실 한도 초과 시 신규 매수 중단
    if targets and _daily_loss_exceeded(market="KR"):
        targets = []

    # 상관계수 필터 — 보유 종목과 상관 높은 종목 제거
    if targets and balance:
        targets = risk_engine.filter_correlated(
            targets, list(balance.keys()), market="KR"
        )

    for code in targets:
        if code in balance:
            print(f"  [{code}] 이미 보유 중 - 스킵")
            continue
        try:
            data = next((d for d in market_data if d["code"] == code), None)
            if data is None:
                data = kis_api.get_stock_data(code)
                data["name"] = settings.UNIVERSE_MAP.get(code, code)
                cached = universe_cache.get(code, {})
                data.setdefault("atr",      cached.get("atr", 0))
                data.setdefault("high_52w", cached.get("high_52w", 0))
                data.setdefault("low_52w",  cached.get("low_52w",  0))

            # 리스크 엔진: 포트폴리오 한도 체크
            if not risk_engine.can_open_position(balance_list, portfolio_value):
                print(f"  [{code}] 포트폴리오 한도 — 스킵")
                continue

            # ATR 기반 포지션 사이징
            qty = risk_engine.position_size_kr(data, portfolio_value)
            amount = qty * data["current"]
            atr_src = "실제ATR" if data.get("atr", 0) > 0 else "추정ATR"
            print(f"  [{code}] 매수 {qty}주 (₩{amount:,}, {atr_src})")
            kis_api.buy(code, amount)
            logger.log_trade("BUY", code=code, name=data["name"],
                             price=data["current"], qty=qty, mode="brain",
                             reason="퀀트+AI 매수 판단")
            risk_engine.trailing_stop.on_buy(code, data["current"])  # 트레일링 스탑 추적 시작
        except Exception as e:
            print(f"  [{code}] 매수 오류: {e}")
            notify.alert_error(f"[Brain] 매수 {code}", e)

    print("===== [Brain] 완료 =====\n")


# ── Brain 모드 (미국장) ───────────────────────────────────
def run_brain_mode_us():
    import brain
    import risk as risk_engine
    print("\n===== [Brain-US] Claude AI 미국주식 매매 =====")

    # Stage 1: AI가 미국 유니버스에서 후보 풀 선정
    try:
        pool_tickers = brain.get_candidate_pool_us()
    except Exception as e:
        _handle_api_error("[Brain-US] Stage1 풀 선정", e)
        return
    if not pool_tickers:
        msg = "Stage1 후보 풀이 비어있습니다. AI 응답 이상 또는 유니버스 데이터 오류."
        print(f"[Brain-US] {msg}")
        notify.alert_error("[Brain-US] 후보 풀 비어있음", msg)
        return

    # Stage 2: KIS 해외 실시간 데이터 수집
    market_data = []
    fail_count = 0
    for ticker in pool_tickers:
        try:
            exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
            data = kis_api.get_stock_data_us(ticker, exchange)
            data["name"] = settings.UNIVERSE_US_MAP.get(ticker, ticker)
            market_data.append(data)
        except Exception as e:
            print(f"  [{ticker}] 데이터 수집 실패: {e}")
            fail_count += 1

    if not market_data:
        msg = f"KIS 해외 시세 조회 전체 실패 ({fail_count}종목)"
        print(f"[Brain-US] {msg}")
        notify.alert_error("[Brain-US] 시장 데이터 전체 실패", msg)
        return
    elif fail_count > len(pool_tickers) // 2:
        notify.alert_error("[Brain-US] 시세 조회 다수 실패", f"{fail_count}/{len(pool_tickers)}종목 실패")

    # 미국장 국면 체크 (QQQ SMA200)
    regime_us = brain.get_market_regime_us()
    notify.alert_regime(regime_us["is_bull"], regime_us.get("gap_pct", 0), market="US")

    # Stage 3: AI가 최종 매수 종목 선정
    try:
        targets = brain.get_targets_us(market_data)
    except Exception as e:
        _handle_api_error("[Brain-US] Stage2 매수 선정", e)
        targets = []

    # 포트폴리오 가치 계산 (USD)
    balance_us_list = kis_api.get_balance_us()
    balance_us = {b["pdno"]: b for b in balance_us_list}
    portfolio_value_usd = sum(float(b.get("evlu_amt", 0)) for b in balance_us_list)
    if portfolio_value_usd == 0:
        portfolio_value_usd = settings.MAX_BUY_AMOUNT_USD * settings.RISK_MAX_POSITIONS  # 초기 추정

    # 매도 판단: 현재 미국주식 보유 종목 검토
    for ticker, holding in balance_us.items():
        try:
            held_data = next((d for d in market_data if d["ticker"] == ticker), None)
            if held_data is None:
                exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
                held_data = kis_api.get_stock_data_us(ticker, exchange)
                held_data["name"] = settings.UNIVERSE_US_MAP.get(ticker, ticker)

            current_price = held_data["current"]
            avg_price     = float(holding.get("pchs_avg_pric", 0))
            profit_pct    = float(holding.get("evlu_pfls_rt", 0))

            # ── 트레일링 스탑 ────────────────────────────────────
            risk_engine.trailing_stop.update(ticker, current_price)

            should_sell_flag = False
            sell_reason      = ""

            if risk_engine.trailing_stop.check(ticker, current_price):
                should_sell_flag = True
                stop_price = risk_engine.trailing_stop.get_stop_price(ticker)
                sell_reason = (
                    f"트레일링 스탑 {settings.RISK_TRAILING_STOP_PCT}% "
                    f"(최고가 대비 ${stop_price:.2f} 이탈)"
                )
            elif brain.should_sell_us(held_data, holding):
                should_sell_flag = True
                sell_reason = "AI 매도 판단 (US)"

            if should_sell_flag:
                qty      = int(holding["hldg_qty"])
                exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
                print(f"  [{ticker}] 매도 {qty}주 — {sell_reason}")
                kis_api.sell_us(ticker, exchange, qty)
                logger.log_trade("SELL", code=ticker, name=held_data["name"],
                                 price=current_price, qty=qty, mode="brain_us",
                                 reason=sell_reason,
                                 avg_buy_price=avg_price, profit_pct=profit_pct)
                risk_engine.trailing_stop.remove(ticker)
        except Exception as e:
            print(f"  [{ticker}] 매도 오류: {e}")
            notify.alert_error(f"[Brain-US] 매도 {ticker}", e)

    # 잔고 재조회 후 매수 실행
    balance_us_list = kis_api.get_balance_us()
    balance_us = {b["pdno"]: b for b in balance_us_list}

    # 텔레그램 봇 상태 로드
    bot = _bot_state()

    # 봇 명령어로 일시 중단된 경우
    if bot.get("paused"):
        print("[Brain-US] 텔레그램 봇 명령으로 매수 중단 중 (/resume 으로 재개)")
        targets = []

    # bear 국면이면 신규 매수 차단
    if targets and settings.REGIME_FILTER and not regime_us["is_bull"]:
        print(f"[Brain-US] 하락장 국면 (QQQ < SMA200 {regime_us['gap_pct']:+.1f}%) — 신규 매수 차단")
        targets = []

    # 당일 손실 한도 초과 시 신규 매수 중단
    if targets and _daily_loss_exceeded(market="US"):
        targets = []

    # 상관계수 필터
    if targets and balance_us:
        targets = risk_engine.filter_correlated(
            targets, list(balance_us.keys()), market="US"
        )

    for ticker in targets:
        if ticker in balance_us:
            print(f"  [{ticker}] 이미 보유 중 - 스킵")
            continue
        try:
            data = next((d for d in market_data if d["ticker"] == ticker), None)
            if data is None:
                exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
                data = kis_api.get_stock_data_us(ticker, exchange)
                data["name"] = settings.UNIVERSE_US_MAP.get(ticker, ticker)

            # 리스크 엔진: 포트폴리오 한도 체크
            if not risk_engine.can_open_position(balance_us_list, portfolio_value_usd):
                print(f"  [{ticker}] 포트폴리오 한도 — 스킵")
                continue

            # ATR 기반 포지션 사이징
            exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
            qty = risk_engine.position_size_us(data, portfolio_value_usd)
            amount = qty * data["current"]
            atr_src = "실제ATR" if data.get("atr", 0) > 0 else "추정ATR"
            print(f"  [{ticker}] 매수 {qty}주 (${amount:.2f}, {atr_src})")
            kis_api.buy_us(ticker, exchange, amount)
            logger.log_trade("BUY", code=ticker, name=data["name"],
                             price=data["current"], qty=qty, mode="brain_us",
                             reason="퀀트+AI 매수 판단 (US)")
            risk_engine.trailing_stop.on_buy(ticker, data["current"])  # 트레일링 스탑 추적 시작
        except Exception as e:
            print(f"  [{ticker}] 매수 오류: {e}")
            notify.alert_error(f"[Brain-US] 매수 {ticker}", e)

    print("===== [Brain-US] 완료 =====\n")


# ── Strategy 모드 ─────────────────────────────────────────
def run_strategy_mode():
    name = strategy.__class__.__name__
    print(f"\n===== [{name}] 매매 =====")

    targets = strategy.get_targets()
    balance = {b["pdno"]: b for b in kis_api.get_balance()}
    print(f"감시 {len(targets)}종목 | 보유 {len(balance)}종목\n")

    for code in targets:
        try:
            data      = kis_api.get_stock_data(code)
            holding   = balance.get(code)
            avg_price = float(holding.get("pchs_avg_pric", 0)) if holding else 0
            profit_pct = (data["current"] - avg_price) / avg_price * 100 if avg_price else 0
            status    = f"보유 {profit_pct:+.2f}%" if holding else "미보유"

            print(f"[{code}] {settings.STOCK_MAP.get(code, code)} | "
                  f"{data['current']:,}원 | {data['change_pct']:+.2f}% | {status}")

            if holding:
                if strategy.should_sell(data, holding):
                    qty = int(holding["hldg_qty"])
                    print(f"  → 매도 {qty}주")
                    kis_api.sell(code, qty)
                    logger.log_trade("SELL", code=code, name=settings.STOCK_MAP.get(code, code),
                                     price=data["current"], qty=qty, mode=name,
                                     reason="전략 매도 조건 충족",
                                     avg_buy_price=avg_price, profit_pct=profit_pct)
                else:
                    print(f"  → 유지")
            else:
                if strategy.should_buy(data):
                    qty_est = settings.MAX_BUY_AMOUNT // data["current"]
                    print(f"  → 매수 {qty_est}주")
                    kis_api.buy(code, settings.MAX_BUY_AMOUNT)
                    logger.log_trade("BUY", code=code, name=settings.STOCK_MAP.get(code, code),
                                     price=data["current"], qty=qty_est, mode=name,
                                     reason="전략 매수 조건 충족")
                else:
                    print(f"  → 패스")

        except Exception as e:
            print(f"  [{code}] 오류: {e}")
            notify.alert_error(f"[Strategy:{name}] {code}", e)

    print(f"===== [{name}] 완료 =====\n")


# ── 거래 시간 체크 ────────────────────────────────────────
def _in_market_hours(open_str: str, close_str: str) -> bool:
    """현재 시각이 장 시간 내인지 확인 (자정 넘기는 미국장 대응)"""
    now  = datetime.now()
    # 평일만
    if now.weekday() >= 5:
        return False

    def _to_minutes(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    now_m   = now.hour * 60 + now.minute
    open_m  = _to_minutes(open_str)
    close_m = _to_minutes(close_str)

    if open_m <= close_m:
        # 일반 (한국장: 09:05 ~ 15:20)
        return open_m <= now_m <= close_m
    else:
        # 자정 넘기는 경우 (미국장: 23:00 ~ 04:30)
        return now_m >= open_m or now_m <= close_m


# ── 메인 실행 함수 ────────────────────────────────────────
def run(force: bool = False):
    """한국장 배치 실행 — 장 시간 내에만 동작 (force=True 시 시간 무시)"""
    if not force and not _in_market_hours(settings.MARKET_OPEN, settings.MARKET_CLOSE):
        return

    print(f"\n[{datetime.now().strftime('%H:%M')}] 한국장 체크{'(강제)' if force else ''}")
    mode = _bot_state().get("mode") or settings.MODE
    if mode == "brain":
        run_brain_mode()
    else:
        run_strategy_mode()


def run_us(force: bool = False):
    """미국장 배치 실행 — 장 시간 내에만 동작 (force=True 시 시간 무시)"""
    if not force and not _in_market_hours(settings.MARKET_OPEN_US, settings.MARKET_CLOSE_US):
        return

    print(f"\n[{datetime.now().strftime('%H:%M')}] 미국장 체크{'(강제)' if force else ''}")
    mode = _bot_state().get("mode") or settings.MODE
    if mode == "brain":
        run_brain_mode_us()
    else:
        print("[US] strategy 모드는 미국장 세션 미지원.")


# ── 일일 요약 함수 ────────────────────────────────────────
def run_daily_summary():
    """장 마감 후 ① 포트폴리오 스냅샷 저장  ② 텔레그램 일일 요약 전송"""
    print(f"[{datetime.now().strftime('%H:%M')}] 일일 마감 처리")

    # ── 잔고 조회 ─────────────────────────────────────────────
    kr_balance, us_balance = [], []
    try:
        kr_balance = kis_api.get_balance()
        pv_kr = sum(float(b.get("evlu_amt", 0)) for b in kr_balance)
    except Exception as e:
        notify.alert_error("[Daily] 한국 잔고 조회 실패", e)
        pv_kr = 0.0

    if settings.MODE == "brain":
        try:
            us_balance = kis_api.get_balance_us()
            pv_us  = sum(float(b.get("evlu_amt", 0)) for b in us_balance)
        except Exception as e:
            notify.alert_error("[Daily] 미국 잔고 조회 실패", e)
            pv_us = 0.0
    else:
        pv_us = 0.0

    # ── 포트폴리오 스냅샷 저장 (5순위) ───────────────────────
    try:
        save_snapshot(kr_balance, us_balance)
    except Exception as e:
        print(f"[Snapshot] 저장 실패: {e}")

    # ── 텔레그램 일일 요약 ────────────────────────────────────
    if settings.TELEGRAM_DAILY_SUMMARY:
        notify.daily_summary(
            portfolio_value=pv_kr,
            holdings=kr_balance,
            market="KR",
        )
        if settings.MODE == "brain":
            notify.daily_summary(
                portfolio_value=pv_us,
                holdings=us_balance,
                market="US",
            )


# ── 직접 실행 시에만 (batchron import 시 실행 안 됨) ─────────
if __name__ == "__main__":
    # 스케줄 등록
    schedule.every(settings.INTERVAL_MINUTES).minutes.do(run)
    if settings.MODE == "brain":
        schedule.every(settings.INTERVAL_MINUTES_US).minutes.do(run_us)
    schedule.every().day.at(settings.TELEGRAM_SUMMARY_TIME).do(run_daily_summary)

    mode_label = (
        "Claude AI Brain" if settings.MODE == "brain"
        else f"{strategy.__class__.__name__}"
    )
    print(f"모드: {mode_label}")
    print(f"  한국장: {settings.MARKET_OPEN}~{settings.MARKET_CLOSE} KST | {settings.INTERVAL_MINUTES}분 간격")
    if settings.MODE == "brain":
        print(f"  미국장: {settings.MARKET_OPEN_US}~{settings.MARKET_CLOSE_US} KST | {settings.INTERVAL_MINUTES_US}분 간격")
    print(f"  일일요약: {settings.TELEGRAM_SUMMARY_TIME} KST")
    print()

    notify.alert_startup(
        mode=mode_label,
        market_open=settings.MARKET_OPEN,
        interval=settings.INTERVAL_MINUTES,
    )

    while True:
        schedule.run_pending()
        time.sleep(30)
