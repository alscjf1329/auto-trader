"""
strategies/regime_adaptive_us.py - 미국주식 변동성 레짐 적응형 전략

한국장 regime_adaptive.py 의 미국장 버전.
KIS 수급 데이터 없이 yfinance OHLCV 기반으로만 신호 생성.

저변동 국면: 볼린저 밴드 하단 터치 시 매수, 상단 터치 시 익절
고변동 국면: MA 골든크로스 매수, 데드크로스 청산

파라미터: settings.yaml → params.regime_adaptive_us
"""

from datetime import date
from strategies.base_us import BaseStrategyUS

import yfinance as yf
import pandas as pd
import numpy as np
import settings


class RegimeAdaptiveStrategyUS(BaseStrategyUS):

    def __init__(self):
        super().__init__()
        p = settings.get_params("regime_adaptive_us")
        self.ATR_WINDOW    = p.get("atr_window",    14)
        self.REGIME_WINDOW = p.get("regime_window",  60)
        self.BB_WINDOW     = p.get("bb_window",      20)
        self.BB_STD        = p.get("bb_std",        2.0)
        self.MA_SHORT      = p.get("ma_short",       20)
        self.MA_LONG       = p.get("ma_long",        60)
        self.STOP_LOSS     = p.get("stop_loss",    -5.0)

        self._cache: dict = {}
        self._cache_date  = None

    def get_targets(self) -> list[str]:
        return settings.STOCK_US_CODES

    def should_buy(self, data: dict) -> bool:
        ticker = data.get("ticker", data.get("code", ""))
        sig = self._get_signal(ticker)
        if sig is None:
            return False
        current = data["current"]

        if sig["low_vol"]:
            result = current <= sig["bb_lower"]
            if result:
                print(f"  [US저변동] {data.get('name', ticker)} "
                      f"볼린저 하단 → 매수 (${current:.2f} ≤ ${sig['bb_lower']:.2f})")
        else:
            result = sig["ma_cross_up"]
            if result:
                print(f"  [US고변동] {data.get('name', ticker)} "
                      f"골든크로스 → 매수 (ATR {sig['atr_ratio']:.2f}x)")
        return result

    def should_sell(self, data: dict, holding: dict) -> bool:
        ticker    = data.get("ticker", data.get("code", ""))
        current   = data["current"]
        avg_price = float(holding.get("pchs_avg_pric", 0))
        profit_pct = (current - avg_price) / avg_price * 100 if avg_price > 0 else 0

        if profit_pct <= self.STOP_LOSS:
            print(f"  [US손절] {data.get('name', ticker)} {profit_pct:+.2f}%")
            return True

        sig = self._get_signal(ticker)
        if sig is None:
            return False

        if sig["low_vol"]:
            result = current >= sig["bb_upper"]
            if result:
                print(f"  [US저변동] {data.get('name', ticker)} "
                      f"볼린저 상단 → 익절 (${current:.2f} ≥ ${sig['bb_upper']:.2f}, {profit_pct:+.2f}%)")
        else:
            result = sig["ma_cross_down"]
            if result:
                print(f"  [US고변동] {data.get('name', ticker)} "
                      f"데드크로스 → 청산 ({profit_pct:+.2f}%)")
        return result

    # ── 신호 계산 (하루 1회 캐싱) ─────────────────────────────

    def _get_signal(self, ticker: str) -> dict | None:
        today = date.today()
        if self._cache_date != today:
            self._cache = {}
            self._cache_date = today
        if ticker not in self._cache:
            self._cache[ticker] = self._calc_signal(ticker)
        return self._cache[ticker]

    def _calc_signal(self, ticker: str) -> dict | None:
        name = settings.STOCK_US_MAP.get(ticker, ticker)
        try:
            df = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            df = df[df["Close"] > 0]
            if len(df) < self.REGIME_WINDOW + 10:
                return None

            close = df["Close"]
            high  = df["High"]
            low   = df["Low"]

            prev_close = close.shift(1)
            tr  = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ], axis=1).max(axis=1)

            atr     = tr.rolling(self.ATR_WINDOW).mean()
            atr_avg = atr.rolling(self.REGIME_WINDOW).mean()

            mid = close.rolling(self.BB_WINDOW).mean()
            std = close.rolling(self.BB_WINDOW).std()
            ma_s = close.rolling(self.MA_SHORT).mean()
            ma_l = close.rolling(self.MA_LONG).mean()

            vals = dict(
                atr_now  = float(atr.iloc[-1]),
                atr_avg  = float(atr_avg.iloc[-1]),
                bb_upper = float(mid.iloc[-1] + self.BB_STD * std.iloc[-1]),
                bb_lower = float(mid.iloc[-1] - self.BB_STD * std.iloc[-1]),
                ma_s_now = float(ma_s.iloc[-1]),
                ma_l_now = float(ma_l.iloc[-1]),
                ma_s_prv = float(ma_s.iloc[-2]),
                ma_l_prv = float(ma_l.iloc[-2]),
            )
            if not all(np.isfinite(v) for v in vals.values()):
                return None

            low_vol   = vals["atr_now"] < vals["atr_avg"]
            atr_ratio = vals["atr_now"] / vals["atr_avg"] if vals["atr_avg"] else 1.0
            regime    = "저변동(역추세)" if low_vol else "고변동(모멘텀)"

            print(f"  [{ticker}] {name} | {regime} | ATR {atr_ratio:.2f}x "
                  f"| BB [${vals['bb_lower']:.2f}~${vals['bb_upper']:.2f}]")

            return {
                "low_vol":       low_vol,
                "atr_ratio":     atr_ratio,
                "bb_upper":      vals["bb_upper"],
                "bb_lower":      vals["bb_lower"],
                "ma_cross_up":   vals["ma_s_prv"] <= vals["ma_l_prv"] and vals["ma_s_now"] > vals["ma_l_now"],
                "ma_cross_down": vals["ma_s_prv"] >= vals["ma_l_prv"] and vals["ma_s_now"] < vals["ma_l_now"],
                "ma_above":      vals["ma_s_now"] > vals["ma_l_now"],
            }
        except Exception as e:
            print(f"  [{ticker}] {name} 신호 계산 오류: {e}")
            return None
