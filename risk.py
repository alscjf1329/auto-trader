"""
risk.py - 리스크 관리 엔진

포지션 사이징: 변동성(ATR) 기반
  qty = min(
      portfolio_value * risk_per_trade_pct / (ATR * atr_multiplier),  # 리스크 기반
      portfolio_value * max_position_pct / price,                      # 비중 한도
      max_buy_amount / price                                            # 고정 금액 한도
  )

ATR 우선순위:
  1. data["atr"]  — brain.py가 yfinance OHLCV 14일 실제 ATR 계산해서 넣어줌
  2. 52주 고저/252 — fallback (실시간 조회 시 ATR 없을 때)

포트폴리오 한도:
  - 최대 보유 종목 수 (max_positions)
  - 최대 총 주식 노출도 (max_total_exposure_pct)

트레일링 스탑 (TrailingStopTracker):
  - 매수 직후 on_buy() 호출 → 최고가 추적 시작
  - 매 사이클마다 update() 호출 → 최고가 갱신
  - check() → 현재가가 (최고가 × (1 - pct/100)) 이하이면 True
  - remove() → 매도 후 추적 제거
  - logs/trailing_stops.json 에 영속 저장 (재시작 후에도 유지)
"""

import json
from datetime import date
from pathlib import Path

import settings


# ══════════════════════════════════════════════════════════
# 트레일링 스탑 트래커
# ══════════════════════════════════════════════════════════

class TrailingStopTracker:
    """
    보유 종목별 최고가를 추적하고 트레일링 스탑 발동 여부를 판단.

    저장 형식 (logs/trailing_stops.json):
      {
        "005930": {"peak": 75000, "buy_price": 72000, "buy_date": "2026-05-26"},
        "NVDA":   {"peak": 145.5, "buy_price": 130.0, "buy_date": "2026-05-26"}
      }
    """

    def __init__(self, path: Path):
        self._path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 외부 호출 API ─────────────────────────────────────

    def on_buy(self, code: str, price: float):
        """매수 직후 호출 — 최고가 추적 시작"""
        self._data[code] = {
            "peak":      price,
            "buy_price": price,
            "buy_date":  date.today().isoformat(),
        }
        self._save()
        print(f"  [TrailingStop] {code} 추적 시작 — 매수가 {price:,.2f}")

    def update(self, code: str, current: float) -> float:
        """
        현재가로 최고가 업데이트.
        추적 중이지 않던 종목은 자동으로 추적 시작 (기존 보유 종목 대응).
        Returns: 현재 peak 가격
        """
        if code not in self._data:
            # 추적 파일에 없는 기존 보유 종목 → 현재가를 peak로 등록
            self._data[code] = {
                "peak":      current,
                "buy_price": current,
                "buy_date":  date.today().isoformat(),
            }
            self._save()
            return current

        if current > self._data[code]["peak"]:
            self._data[code]["peak"] = current
            self._save()
        return self._data[code]["peak"]

    def check(self, code: str, current: float) -> bool:
        """
        트레일링 스탑 발동 여부 판단.
        settings.RISK_TRAILING_STOP_ENABLED 가 False 면 항상 False.
        """
        if not settings.RISK_TRAILING_STOP_ENABLED:
            return False
        if code not in self._data:
            return False

        peak  = self._data[code]["peak"]
        stop  = peak * (1.0 - settings.RISK_TRAILING_STOP_PCT / 100.0)

        if current <= stop:
            print(
                f"  [TrailingStop] {code} 발동 — "
                f"현재 {current:,.2f} ≤ 스탑 {stop:,.2f} "
                f"(최고가 {peak:,.2f} - {settings.RISK_TRAILING_STOP_PCT}%)"
            )
            return True
        return False

    def get_stop_price(self, code: str) -> float:
        """현재 트레일링 스탑 가격 조회 (화면 표시용)"""
        if code not in self._data:
            return 0.0
        peak = self._data[code]["peak"]
        return peak * (1.0 - settings.RISK_TRAILING_STOP_PCT / 100.0)

    def remove(self, code: str):
        """매도 완료 후 추적 제거"""
        if code in self._data:
            del self._data[code]
            self._save()

    def all_data(self) -> dict:
        """대시보드 표시용 전체 데이터"""
        return dict(self._data)


# ── 모듈 레벨 싱글턴 (runner.py에서 import해서 사용) ──────
_TRAILING_STOP_PATH = Path(__file__).parent / "logs" / "trailing_stops.json"
trailing_stop = TrailingStopTracker(_TRAILING_STOP_PATH)


def _get_atr(data: dict) -> float:
    """
    ATR 반환. brain.py가 계산한 실제 14일 ATR 우선,
    없으면 52주 고저 범위 / 252 로 추정.
    """
    if data.get("atr", 0) > 0:
        return float(data["atr"])
    high = float(data.get("high_52w", 0))
    low  = float(data.get("low_52w",  0))
    curr = float(data.get("current",  1))
    rng  = high - low
    return rng / 252.0 if rng > 0 else curr * 0.02


def position_size_kr(data: dict, portfolio_value: float) -> int:
    """
    한국주식 포지션 크기 (주 수).
    portfolio_value: 원화 총자산 (현금 + 주식 평가액)
    """
    price = float(data.get("current", 1))
    if price <= 0:
        return 0

    atr = _get_atr(data)

    # 리스크 기반 수량: qty * atr * mult ≤ portfolio * risk_pct
    risk_amount = portfolio_value * (settings.RISK_PER_TRADE_PCT / 100)
    qty_risk    = int(risk_amount / (atr * settings.RISK_ATR_MULTIPLIER)) if atr > 0 else 9999

    # 비중 한도
    qty_weight = int(portfolio_value * (settings.RISK_MAX_POSITION_PCT / 100) / price)

    # 고정 금액 한도
    qty_fixed = int(settings.MAX_BUY_AMOUNT / price)

    qty = min(qty_risk, qty_weight, qty_fixed)
    return max(1, qty)


def position_size_us(data: dict, portfolio_value_usd: float) -> int:
    """미국주식 포지션 크기 (주 수)"""
    price = float(data.get("current", 1))
    if price <= 0:
        return 0

    atr = _get_atr(data)

    risk_amount = portfolio_value_usd * (settings.RISK_PER_TRADE_PCT / 100)
    qty_risk    = int(risk_amount / (atr * settings.RISK_ATR_MULTIPLIER)) if atr > 0 else 9999
    qty_weight  = int(portfolio_value_usd * (settings.RISK_MAX_POSITION_PCT / 100) / price)
    qty_fixed   = int(settings.MAX_BUY_AMOUNT_USD / price)

    qty = min(qty_risk, qty_weight, qty_fixed)
    return max(1, qty)


def filter_correlated(
    candidate_codes: list[str],
    holding_codes:   list[str],
    threshold:       float | None = None,
    market:          str = "KR",
    period:          str = "3mo",
) -> list[str]:
    """
    보유 종목과 상관계수가 threshold 이상인 후보 종목을 제거.

    Parameters
    ----------
    candidate_codes : 매수 후보 코드 목록
    holding_codes   : 현재 보유 종목 코드 목록
    threshold       : 상관계수 임계값 (None → settings 값 사용)
    market          : "KR" (6자리 코드 + .KS) / "US" (티커 그대로)
    period          : yfinance 다운로드 기간

    Returns
    -------
    threshold 미만 종목만 포함한 후보 코드 목록
    """
    if not settings.RISK_CORRELATION_FILTER:
        return candidate_codes
    if not holding_codes or not candidate_codes:
        return candidate_codes

    th = threshold if threshold is not None else settings.RISK_CORRELATION_THRESHOLD

    try:
        import yfinance as yf
        import pandas as pd

        all_codes = list(dict.fromkeys(candidate_codes + holding_codes))

        if market == "KR":
            yf_tickers = [f"{c}.KS" for c in all_codes]
            code_map   = {f"{c}.KS": c for c in all_codes}
        else:
            yf_tickers = all_codes
            code_map   = {c: c for c in all_codes}

        raw = yf.download(yf_tickers, period=period, auto_adjust=True, progress=False)

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"].copy()
        else:
            close = raw[["Close"]].copy() if "Close" in raw.columns else pd.DataFrame()

        if close.empty:
            return candidate_codes

        close.columns = [code_map.get(str(c), str(c)) for c in close.columns]
        returns = close.pct_change().dropna()
        corr    = returns.corr()

        filtered: list[str] = []
        skipped:  list[str] = []

        for cand in candidate_codes:
            blocked = False
            for held in holding_codes:
                if cand not in corr.columns or held not in corr.columns:
                    continue
                r = abs(float(corr.loc[cand, held]))
                if r >= th:
                    print(
                        f"[Risk] 상관계수 차단 — {cand} ↔ {held}: "
                        f"{r:.2f} ≥ {th} → 제외"
                    )
                    blocked = True
                    skipped.append(cand)
                    break
            if not blocked:
                filtered.append(cand)

        if skipped:
            print(f"[Risk] 상관계수 필터 — {len(skipped)}종목 제외: {skipped}")
        return filtered

    except Exception as e:
        print(f"[Risk] 상관계수 필터 실패 (원본 반환): {e}")
        return candidate_codes


def can_open_position(holdings: list[dict], portfolio_value: float) -> bool:
    """
    새 포지션 진입 가능 여부:
    - 보유 종목 수 < RISK_MAX_POSITIONS
    - 총 주식 노출도 < RISK_MAX_TOTAL_EXPOSURE_PCT
    """
    active = [h for h in holdings if int(h.get("hldg_qty", 0)) > 0]

    if len(active) >= settings.RISK_MAX_POSITIONS:
        print(f"[Risk] 종목 수 한도 ({len(active)}/{settings.RISK_MAX_POSITIONS}) → 매수 스킵")
        return False

    if portfolio_value > 0:
        total_eval   = sum(float(h.get("evlu_amt", 0)) for h in active)
        exposure_pct = total_eval / portfolio_value * 100
        if exposure_pct >= settings.RISK_MAX_TOTAL_EXPOSURE_PCT:
            print(f"[Risk] 노출도 한도 ({exposure_pct:.1f}% >= {settings.RISK_MAX_TOTAL_EXPOSURE_PCT}%) → 매수 스킵")
            return False

    return True
