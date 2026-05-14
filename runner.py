from dotenv import load_dotenv
load_dotenv()

import schedule
import time
from datetime import datetime
import kis_api
import settings
from journal import logger

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


# ── Brain 모드 ────────────────────────────────────────────
def run_brain_mode():
    import brain
    print("\n===== [Brain] Claude AI 매매 =====")

    # ── Stage 1: AI가 유니버스에서 후보 풀 선정 (캐시 활용) ──
    pool_codes = brain.get_candidate_pool()
    if not pool_codes:
        print("[Brain] 후보 풀이 비어 있습니다. 종료.")
        return

    # ── Stage 2: 후보 풀 실시간 데이터 수집 (KIS) ───────────
    market_data = []
    for code in pool_codes:
        try:
            data = kis_api.get_stock_data(code)
            data["name"] = settings.UNIVERSE_MAP.get(code, code)
            market_data.append(data)
        except Exception as e:
            print(f"  [{code}] 데이터 수집 실패: {e}")

    if not market_data:
        print("[Brain] 시장 데이터를 가져올 수 없습니다. 종료.")
        return

    # ── Stage 3: AI가 후보 풀에서 최종 매수 종목 선정 ────────
    targets = brain.get_targets(market_data)

    # ── 매도 판단: 현재 보유 종목 전체 검토 ─────────────────
    balance = {b["pdno"]: b for b in kis_api.get_balance()}

    for code, holding in balance.items():
        try:
            # 보유 종목이 후보 풀에 없을 수도 있으므로 KIS에서 별도 조회
            held_data = next((d for d in market_data if d["code"] == code), None)
            if held_data is None:
                held_data = kis_api.get_stock_data(code)
                held_data["name"] = settings.UNIVERSE_MAP.get(code, code)

            if brain.should_sell(held_data, holding):
                qty        = int(holding["hldg_qty"])
                avg_price  = float(holding.get("pchs_avg_pric", 0))
                profit_pct = float(holding.get("evlu_pfls_rt", 0))
                print(f"  [{code}] 매도 {qty}주")
                kis_api.sell(code, qty)
                logger.log_trade("SELL", code=code, name=held_data["name"],
                                 price=held_data["current"], qty=qty, mode="brain",
                                 reason="Claude 매도 판단",
                                 avg_buy_price=avg_price, profit_pct=profit_pct)
        except Exception as e:
            print(f"  [{code}] 매도 오류: {e}")

    # ── 매수 실행: AI 선정 종목 ───────────────────────────────
    # 잔고를 다시 조회해 매도 후 상태 반영
    balance = {b["pdno"]: b for b in kis_api.get_balance()}

    for code in targets:
        if code in balance:
            print(f"  [{code}] 이미 보유 중 - 스킵")
            continue
        try:
            data = next((d for d in market_data if d["code"] == code), None)
            if data is None:
                data = kis_api.get_stock_data(code)
                data["name"] = settings.UNIVERSE_MAP.get(code, code)

            # Stage 4: 개별 최종 확인
            if brain.should_buy(data):
                qty_est = settings.MAX_BUY_AMOUNT // data["current"]
                print(f"  [{code}] 매수 {qty_est}주")
                kis_api.buy(code, settings.MAX_BUY_AMOUNT)
                logger.log_trade("BUY", code=code, name=data["name"],
                                 price=data["current"], qty=qty_est, mode="brain",
                                 reason="Claude 매수 판단")
        except Exception as e:
            print(f"  [{code}] 매수 오류: {e}")

    print("===== [Brain] 완료 =====\n")


# ── Brain 모드 (미국장) ───────────────────────────────────
def run_brain_mode_us():
    import brain
    print("\n===== [Brain-US] Claude AI 미국주식 매매 =====")

    # Stage 1: AI가 미국 유니버스에서 후보 풀 선정
    pool_tickers = brain.get_candidate_pool_us()
    if not pool_tickers:
        print("[Brain-US] 후보 풀이 비어 있습니다. 종료.")
        return

    # Stage 2: KIS 해외 실시간 데이터 수집
    market_data = []
    for ticker in pool_tickers:
        try:
            exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
            data = kis_api.get_stock_data_us(ticker, exchange)
            data["name"] = settings.UNIVERSE_US_MAP.get(ticker, ticker)
            market_data.append(data)
        except Exception as e:
            print(f"  [{ticker}] 데이터 수집 실패: {e}")

    if not market_data:
        print("[Brain-US] 시장 데이터를 가져올 수 없습니다. 종료.")
        return

    # Stage 3: AI가 최종 매수 종목 선정
    targets = brain.get_targets_us(market_data)

    # 매도 판단: 현재 미국주식 보유 종목 검토
    balance_us = {b["pdno"]: b for b in kis_api.get_balance_us()}

    for ticker, holding in balance_us.items():
        try:
            held_data = next((d for d in market_data if d["ticker"] == ticker), None)
            if held_data is None:
                exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
                held_data = kis_api.get_stock_data_us(ticker, exchange)
                held_data["name"] = settings.UNIVERSE_US_MAP.get(ticker, ticker)

            if brain.should_sell_us(held_data, holding):
                qty        = int(holding["hldg_qty"])
                avg_price  = float(holding.get("pchs_avg_pric", 0))
                profit_pct = float(holding.get("evlu_pfls_rt", 0))
                exchange   = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
                print(f"  [{ticker}] 매도 {qty}주")
                kis_api.sell_us(ticker, exchange, qty)
                logger.log_trade("SELL", code=ticker, name=held_data["name"],
                                 price=held_data["current"], qty=qty, mode="brain_us",
                                 reason="Claude 매도 판단 (US)",
                                 avg_buy_price=avg_price, profit_pct=profit_pct)
        except Exception as e:
            print(f"  [{ticker}] 매도 오류: {e}")

    # 잔고 재조회 후 매수 실행
    balance_us = {b["pdno"]: b for b in kis_api.get_balance_us()}

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

            if brain.should_buy_us(data):
                exchange = settings.UNIVERSE_US_EXCH.get(ticker, "NAS")
                qty_est  = int(settings.MAX_BUY_AMOUNT_USD / data["current"])
                print(f"  [{ticker}] 매수 {qty_est}주 (${settings.MAX_BUY_AMOUNT_USD})")
                kis_api.buy_us(ticker, exchange, settings.MAX_BUY_AMOUNT_USD)
                logger.log_trade("BUY", code=ticker, name=data["name"],
                                 price=data["current"], qty=qty_est, mode="brain_us",
                                 reason="Claude 매수 판단 (US)")
        except Exception as e:
            print(f"  [{ticker}] 매수 오류: {e}")

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
def run():
    """한국장 배치 실행 — 장 시간 내에만 동작"""
    if not _in_market_hours(settings.MARKET_OPEN, settings.MARKET_CLOSE):
        return   # 장 외 시간은 조용히 패스

    print(f"\n[{datetime.now().strftime('%H:%M')}] 한국장 체크")
    if settings.MODE == "brain":
        run_brain_mode()
    else:
        run_strategy_mode()


def run_us():
    """미국장 배치 실행 — 장 시간 내에만 동작"""
    if not _in_market_hours(settings.MARKET_OPEN_US, settings.MARKET_CLOSE_US):
        return

    print(f"\n[{datetime.now().strftime('%H:%M')}] 미국장 체크")
    if settings.MODE == "brain":
        run_brain_mode_us()
    else:
        print("[US] strategy 모드는 미국장 세션 미지원.")


# ── 스케줄 등록 ───────────────────────────────────────────
# 한국장: N분마다 실행 (장 시간 체크는 run() 내부에서)
schedule.every(settings.INTERVAL_MINUTES).minutes.do(run)

# 미국장: N분마다 실행
if settings.MODE == "brain":
    schedule.every(settings.INTERVAL_MINUTES_US).minutes.do(run_us)

mode_label = (
    "Claude AI Brain" if settings.MODE == "brain"
    else f"{strategy.__class__.__name__}"
)
print(f"모드: {mode_label}")
print(f"  한국장: {settings.MARKET_OPEN}~{settings.MARKET_CLOSE} KST | {settings.INTERVAL_MINUTES}분 간격")
if settings.MODE == "brain":
    print(f"  미국장: {settings.MARKET_OPEN_US}~{settings.MARKET_CLOSE_US} KST | {settings.INTERVAL_MINUTES_US}분 간격")
print()

# 테스트용 즉시 실행 (주석 해제)
# run()

while True:
    schedule.run_pending()
    time.sleep(30)   # 30초마다 스케줄 체크
