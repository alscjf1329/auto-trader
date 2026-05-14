import yfinance as yf
import pandas as pd
import numpy as np


def fetch_data(ticker: str, period: str = "5y") -> pd.DataFrame:
    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    df.columns = df.columns.droplevel(1) if isinstance(df.columns, pd.MultiIndex) else df.columns
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])  # NaN 행 제거
    df = df[df["Close"] > 0]  # 종가 0 제거
    return df


class BacktestEngine:

    def __init__(self, initial_cash: int = 10_000_000):
        self.initial_cash = initial_cash

    # ── 1. 52주 신고가 모멘텀 ──────────────────────────────────
    def run_momentum(self, tickers: list, period: str = "5y") -> dict:
        """52주 신고가 돌파 매수 / +5% 익절 -3% 손절"""
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                past = df.loc[df.index <= date].tail(252)
                high_52w = float(past["High"].max())

                if ticker in holdings:
                    buy_price = holdings[ticker]["buy_price"]
                    qty = holdings[ticker]["qty"]
                    profit_pct = (current - buy_price) / buy_price * 100
                    if profit_pct >= 5.0 or profit_pct <= -3.0:
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]
                elif current >= high_52w and cash > current:
                    qty = int(cash * 0.2 // current)
                    if qty > 0:
                        cash -= current * qty
                        holdings[ticker] = {"qty": qty, "buy_price": current}
                        trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                       "price": current, "qty": qty, "profit_pct": 0})

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": "52주 신고가 모멘텀", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 2. 듀얼 모멘텀 ────────────────────────────────────────
    def run_dual_momentum(self, tickers: list, period: str = "5y") -> dict:
        """12개월 수익률 양수면 매수, 월 1회 리밸런싱"""
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        all_dates = sorted(set().union(*[df.index for df in data.values()]))
        monthly_dates = pd.DatetimeIndex(all_dates).to_period("M")
        month_end_dates = []
        seen = set()
        for d, m in zip(reversed(all_dates), reversed(monthly_dates)):
            if m not in seen:
                month_end_dates.append(d)
                seen.add(m)
        month_end_dates = sorted(month_end_dates)

        for date in month_end_dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                past = df.loc[df.index <= date]
                if len(past) < 252:
                    continue
                return_12m = (current - float(past["Close"].iloc[-252])) / float(past["Close"].iloc[-252]) * 100

                if ticker in holdings and return_12m < 0:
                    qty = holdings[ticker]["qty"]
                    profit_pct = (current - holdings[ticker]["buy_price"]) / holdings[ticker]["buy_price"] * 100
                    cash += current * qty
                    trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                   "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                    del holdings[ticker]
                elif ticker not in holdings and return_12m > 0 and cash > current:
                    qty = int(cash * 0.5 // current)
                    if qty > 0:
                        cash -= current * qty
                        holdings[ticker] = {"qty": qty, "buy_price": current}
                        trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                       "price": current, "qty": qty, "profit_pct": 0})

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": "듀얼 모멘텀 (12개월)", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 3. RSI 과매도 반등 ────────────────────────────────────
    def run_rsi(self, tickers: list, period: str = "5y",
                rsi_buy: int = 30, rsi_sell: int = 70) -> dict:
        """RSI(14) < 30 매수 / RSI > 70 매도"""
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        def calc_rsi(series: pd.Series, window: int = 14) -> pd.Series:
            delta = series.diff()
            gain = delta.clip(lower=0).rolling(window).mean()
            loss = (-delta.clip(upper=0)).rolling(window).mean()
            rs = gain / loss.replace(0, 1e-10)
            return 100 - (100 / (1 + rs))

        rsi_data = {t: calc_rsi(data[t]["Close"]) for t in tickers}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                rsi = rsi_data[ticker].get(date)
                if rsi is None or pd.isna(rsi):
                    continue

                if ticker in holdings:
                    if rsi >= rsi_sell:
                        qty = holdings[ticker]["qty"]
                        buy_price = holdings[ticker]["buy_price"]
                        profit_pct = (current - buy_price) / buy_price * 100
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]
                else:
                    if rsi <= rsi_buy and cash > current:
                        qty = int(cash * 0.25 // current)
                        if qty > 0:
                            cash -= current * qty
                            holdings[ticker] = {"qty": qty, "buy_price": current}
                            trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                           "price": current, "qty": qty, "profit_pct": 0})

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": f"RSI 역추세 (매수<{rsi_buy} / 매도>{rsi_sell})", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 4. 골든크로스 (이동평균) ──────────────────────────────
    def run_golden_cross(self, tickers: list, period: str = "5y",
                         short: int = 20, long: int = 60) -> dict:
        """단기 MA가 장기 MA 상향 돌파 시 매수 (골든크로스), 하향 이탈 시 매도"""
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        ma_short = {t: data[t]["Close"].rolling(short).mean() for t in tickers}
        ma_long  = {t: data[t]["Close"].rolling(long).mean()  for t in tickers}

        prev_signal = {t: None for t in tickers}  # "above" / "below"

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                ms = ma_short[ticker].get(date)
                ml = ma_long[ticker].get(date)
                if ms is None or ml is None or pd.isna(ms) or pd.isna(ml):
                    continue

                signal = "above" if ms > ml else "below"
                prev = prev_signal[ticker]

                # 골든크로스: below → above
                if prev == "below" and signal == "above" and ticker not in holdings and cash > current:
                    qty = int(cash * 0.25 // current)
                    if qty > 0:
                        cash -= current * qty
                        holdings[ticker] = {"qty": qty, "buy_price": current}
                        trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                       "price": current, "qty": qty, "profit_pct": 0})

                # 데드크로스: above → below
                elif prev == "above" and signal == "below" and ticker in holdings:
                    qty = holdings[ticker]["qty"]
                    buy_price = holdings[ticker]["buy_price"]
                    profit_pct = (current - buy_price) / buy_price * 100
                    cash += current * qty
                    trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                   "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                    del holdings[ticker]

                prev_signal[ticker] = signal

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": f"골든크로스 (MA{short}/MA{long})", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 5. 볼린저 밴드 ────────────────────────────────────────
    def run_bollinger(self, tickers: list, period: str = "5y",
                      window: int = 20, num_std: float = 2.0) -> dict:
        """볼린저 밴드 하단 터치 매수 / 상단 터치 매도"""
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        bb = {}
        for t in tickers:
            close = data[t]["Close"]
            mid   = close.rolling(window).mean()
            std   = close.rolling(window).std()
            bb[t] = {"upper": mid + num_std * std, "lower": mid - num_std * std}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                upper = bb[ticker]["upper"].get(date)
                lower = bb[ticker]["lower"].get(date)
                if upper is None or lower is None or pd.isna(upper) or pd.isna(lower):
                    continue

                if ticker in holdings:
                    if current >= upper:
                        qty = holdings[ticker]["qty"]
                        buy_price = holdings[ticker]["buy_price"]
                        profit_pct = (current - buy_price) / buy_price * 100
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]
                else:
                    if current <= lower and cash > current:
                        qty = int(cash * 0.25 // current)
                        if qty > 0:
                            cash -= current * qty
                            holdings[ticker] = {"qty": qty, "buy_price": current}
                            trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                           "price": current, "qty": qty, "profit_pct": 0})

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": f"볼린저 밴드 ({window}일, {num_std}σ)", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 6. MACD ───────────────────────────────────────────────
    def run_macd(self, tickers: list, period: str = "5y",
                 fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
        """
        MACD(12,26,9) - 증권사 리포트에서 가장 많이 인용되는 추세 지표
        MACD선이 시그널선 상향 돌파 → 매수 / 하향 이탈 → 매도
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        indicators = {}
        for t in tickers:
            close = data[t]["Close"]
            ema_fast    = close.ewm(span=fast,   adjust=False).mean()
            ema_slow    = close.ewm(span=slow,   adjust=False).mean()
            macd_line   = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            # 히스토그램 부호로 크로스오버 감지
            histogram   = macd_line - signal_line
            indicators[t] = {"hist": histogram}

        prev_hist = {t: None for t in tickers}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                if not np.isfinite(current):
                    continue

                try:
                    hist = float(indicators[ticker]["hist"].loc[date])
                except KeyError:
                    continue
                if not np.isfinite(hist):
                    continue

                prev = prev_hist[ticker]

                # 골든 크로스: 히스토그램이 음→양 전환
                if prev is not None and prev < 0 and hist >= 0 and ticker not in holdings and cash > current:
                    qty = int(cash * 0.25 // current)
                    if qty > 0:
                        cash -= current * qty
                        holdings[ticker] = {"qty": qty, "buy_price": current}
                        trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                       "price": current, "qty": qty, "profit_pct": 0})

                # 데드 크로스: 히스토그램이 양→음 전환
                elif prev is not None and prev >= 0 and hist < 0 and ticker in holdings:
                    qty = holdings[ticker]["qty"]
                    profit_pct = (current - holdings[ticker]["buy_price"]) / holdings[ticker]["buy_price"] * 100
                    cash += current * qty
                    trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                   "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                    del holdings[ticker]

                prev_hist[ticker] = hist

        final_value = cash
        for ticker, h in holdings.items():
            last = float(data[ticker]["Close"].iloc[-1])
            final_value += last * h["qty"] if np.isfinite(last) else 0

        return {"strategy": f"MACD ({fast},{slow},{signal})", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 7. 터틀 트레이딩 (Donchian Channel) ──────────────────
    def run_turtle(self, tickers: list, period: str = "5y",
                   entry_days: int = 20, exit_days: int = 10) -> dict:
        """
        리처드 데니스의 터틀 트레이딩 - 헤지펀드 트렌드 추종의 원조
        20일 신고가 돌파 시 매수 (Donchian Channel)
        10일 신저가 이탈 시 청산
        ATR 기반 손절: 매수가 - 2×ATR
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        # ATR 계산
        def calc_atr(df, window=14):
            high, low, close = df["High"], df["Low"], df["Close"]
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs()
            ], axis=1).max(axis=1)
            return tr.rolling(window).mean()

        atr_data = {t: calc_atr(data[t]) for t in tickers}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                past = df.loc[df.index <= date]

                entry_high = float(past["High"].iloc[-(entry_days+1):-1].max()) if len(past) > entry_days else None
                exit_low   = float(past["Low"].iloc[-(exit_days+1):-1].min())  if len(past) > exit_days  else None
                atr = atr_data[ticker].get(date)

                # ATR 손절 확인 (보유 중)
                if ticker in holdings:
                    stop_price = holdings[ticker]["stop"]
                    if current <= stop_price or (exit_low and current <= exit_low):
                        qty = holdings[ticker]["qty"]
                        profit_pct = (current - holdings[ticker]["buy_price"]) / holdings[ticker]["buy_price"] * 100
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]

                # 20일 신고가 돌파 매수
                elif entry_high and current > entry_high and cash > current and atr and not pd.isna(atr):
                    qty = int(cash * 0.20 // current)
                    if qty > 0:
                        stop = current - 2 * float(atr)
                        cash -= current * qty
                        holdings[ticker] = {"qty": qty, "buy_price": current, "stop": stop}
                        trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                       "price": current, "qty": qty, "profit_pct": 0})

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": f"터틀 트레이딩 (Donchian {entry_days}/{exit_days}일)", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 8. 스토캐스틱 ─────────────────────────────────────────
    def run_stochastic(self, tickers: list, period: str = "5y",
                       k_period: int = 14, d_period: int = 3,
                       oversold: int = 20, overbought: int = 80) -> dict:
        """
        스토캐스틱 (Stochastic Oscillator) - 단기 과매수/과매도 판단
        %K가 oversold(20) 이하로 내려갔다가 다시 올라올 때 매수
        %K가 overbought(80) 이상이면 매도 (또는 -5% 손절)
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        stoch = {}
        for t in tickers:
            low_min  = data[t]["Low"].rolling(k_period).min()
            high_max = data[t]["High"].rolling(k_period).max()
            k = (data[t]["Close"] - low_min) / (high_max - low_min + 1e-10) * 100
            d = k.rolling(d_period).mean()
            stoch[t] = {"k": k, "d": d}

        was_oversold = {t: False for t in tickers}  # 과매도 진입 여부 추적

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                if not np.isfinite(current):
                    continue

                try:
                    k_val = float(stoch[ticker]["k"].loc[date])
                    d_val = float(stoch[ticker]["d"].loc[date])
                except KeyError:
                    continue
                if not np.isfinite(k_val) or not np.isfinite(d_val):
                    continue

                # 과매도 진입 기록
                if k_val <= oversold:
                    was_oversold[ticker] = True

                if ticker in holdings:
                    buy_price = holdings[ticker]["buy_price"]
                    profit_pct = (current - buy_price) / buy_price * 100
                    # 과매수 구간 도달 또는 손절(-5%)
                    if k_val >= overbought or profit_pct <= -5.0:
                        qty = holdings[ticker]["qty"]
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]
                        was_oversold[ticker] = False
                else:
                    # 과매도 이후 %K가 %D를 상향 돌파하면 매수
                    if was_oversold[ticker] and k_val > d_val and k_val > oversold and cash > current:
                        qty = int(cash * 0.25 // current)
                        if qty > 0:
                            cash -= current * qty
                            holdings[ticker] = {"qty": qty, "buy_price": current}
                            trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                           "price": current, "qty": qty, "profit_pct": 0})
                            was_oversold[ticker] = False

        final_value = cash
        for ticker, h in holdings.items():
            last = float(data[ticker]["Close"].iloc[-1])
            final_value += last * h["qty"] if np.isfinite(last) else 0

        return {"strategy": f"스토캐스틱 ({k_period},{d_period}) OS<{oversold}/OB>{overbought}", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 9. 변동성 돌파 (래리 윌리엄스) ──────────────────────
    def run_volatility_breakout(self, tickers: list, period: str = "5y", k: float = 0.5) -> dict:
        """
        래리 윌리엄스 변동성 돌파 전략 - 국내 퀀트들이 가장 많이 쓰는 단기 전략
        목표가 = 당일 시가 + 전일 변동폭(고가-저가) × K(0.5)
        당일 종가가 목표가 돌파 시 매수 → 다음날 시가에 매도
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        for i, date in enumerate(dates[1:], 1):
            prev_date = dates[i - 1]
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index or prev_date not in df.index:
                    continue

                row      = df.loc[date]
                prev_row = df.loc[prev_date]

                open_price  = float(row["Open"])
                close_price = float(row["Close"])
                prev_range  = float(prev_row["High"]) - float(prev_row["Low"])
                target      = open_price + prev_range * k

                # 전날 매수한 포지션 → 오늘 시가에 청산
                if ticker in holdings and holdings[ticker].get("sell_next"):
                    buy_price = holdings[ticker]["buy_price"]
                    qty = holdings[ticker]["qty"]
                    sell_price = open_price
                    profit_pct = (sell_price - buy_price) / buy_price * 100
                    cash += sell_price * qty
                    trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                   "price": sell_price, "qty": qty, "profit_pct": round(profit_pct, 2)})
                    del holdings[ticker]

                # 오늘 종가가 목표가 돌파 → 종가로 매수 기록 (다음날 시가 청산)
                if ticker not in holdings and close_price >= target and cash > close_price:
                    qty = int(cash * 0.20 // close_price)
                    if qty > 0:
                        cash -= close_price * qty
                        holdings[ticker] = {"qty": qty, "buy_price": close_price, "sell_next": True}
                        trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                       "price": close_price, "qty": qty, "profit_pct": 0})

        # 잔여 청산
        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": f"변동성 돌파 (래리 윌리엄스, K={k})", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 10. Z-Score 평균회귀 ─────────────────────────────────
    def run_zscore_mean_reversion(self, tickers: list, period: str = "5y",
                                  window: int = 20, z_buy: float = -2.0, z_sell: float = 1.0) -> dict:
        """
        Z-Score 평균회귀 - 헤지펀드 통계적 차익거래의 기본
        20일 이동평균 대비 Z-Score가 -2 이하로 떨어지면 매수 (극단적 저평가)
        Z-Score가 +1 이상 회복되면 매도 (평균 회귀 완료)
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        zscore = {}
        for t in tickers:
            close = data[t]["Close"].replace(0, np.nan)  # 0값 제거
            mean  = close.rolling(window, min_periods=window).mean()
            std   = close.rolling(window, min_periods=window).std()
            std   = std.replace(0, np.nan)  # std=0 제거
            zscore[t] = (close - mean) / std

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                if not np.isfinite(current) or current <= 0:
                    continue

                try:
                    z = float(zscore[ticker].loc[date])
                except KeyError:
                    continue
                if not np.isfinite(z):
                    continue

                if ticker in holdings:
                    if z >= z_sell:
                        qty = holdings[ticker]["qty"]
                        buy_price = holdings[ticker]["buy_price"]
                        profit_pct = (current - buy_price) / buy_price * 100
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]
                else:
                    if z <= z_buy and cash > current:
                        qty = int(cash * 0.25 // current)
                        if qty > 0:
                            cash -= current * qty
                            holdings[ticker] = {"qty": qty, "buy_price": current}
                            trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                           "price": current, "qty": qty, "profit_pct": 0})

        final_value = cash
        for ticker, h in holdings.items():
            final_value += float(data[ticker]["Close"].iloc[-1]) * h["qty"]

        return {"strategy": f"Z-Score 평균회귀 ({window}일, 매수≤{z_buy}/매도≥{z_sell})", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ══════════════════════════════════════════════════════════
    # 🔬 조합/변형 전략 (Quant-style)
    # ══════════════════════════════════════════════════════════

    # ── 11. 멀티 시그널 앙상블 ───────────────────────────────
    def run_ensemble(self, tickers: list, period: str = "5y",
                     required_signals: int = 2) -> dict:
        """
        멀티 시그널 앙상블 - 퀀트 펀드 기본 접근법
        MACD + RSI + 볼린저 밴드 3개 신호 중 N개 이상 일치할 때만 진입
        → 오신호(false signal) 대폭 감소, 진입 조건이 까다로운 만큼 정확도 상승

        required_signals=2 → 3개 중 2개 이상 동의해야 매수/매도
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        # ── 지표 사전 계산 ──
        signals = {}
        for t in tickers:
            close = data[t]["Close"]
            high  = data[t]["High"]
            low   = data[t]["Low"]

            # MACD 히스토그램
            macd_hist = (close.ewm(span=12, adjust=False).mean()
                         - close.ewm(span=26, adjust=False).mean())
            macd_hist = macd_hist - macd_hist.ewm(span=9, adjust=False).mean()

            # RSI
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

            # 볼린저 밴드
            mid   = close.rolling(20).mean()
            std   = close.rolling(20).std()
            bb_upper = mid + 2 * std
            bb_lower = mid - 2 * std
            bb_pct   = (close - bb_lower) / (bb_upper - bb_lower + 1e-10)  # 0=하단, 1=상단

            signals[t] = {
                "macd_hist": macd_hist,
                "rsi":       rsi,
                "bb_pct":    bb_pct,
            }

        prev_macd_hist = {t: None for t in tickers}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                if not np.isfinite(current):
                    continue

                try:
                    hist    = float(signals[ticker]["macd_hist"].loc[date])
                    rsi_val = float(signals[ticker]["rsi"].loc[date])
                    bb_val  = float(signals[ticker]["bb_pct"].loc[date])
                except KeyError:
                    continue
                if not all(np.isfinite(v) for v in [hist, rsi_val, bb_val]):
                    continue

                prev_hist = prev_macd_hist[ticker]

                # ── 매수 신호 집계 ──
                buy_signals = 0
                if prev_hist is not None and prev_hist < 0 and hist >= 0:
                    buy_signals += 1   # MACD 골든크로스
                if rsi_val < 35:
                    buy_signals += 1   # RSI 과매도
                if bb_val < 0.2:
                    buy_signals += 1   # 볼린저 하단 근접

                # ── 매도 신호 집계 ──
                sell_signals = 0
                if prev_hist is not None and prev_hist >= 0 and hist < 0:
                    sell_signals += 1  # MACD 데드크로스
                if rsi_val > 70:
                    sell_signals += 1  # RSI 과매수
                if bb_val > 0.85:
                    sell_signals += 1  # 볼린저 상단 근접

                if ticker not in holdings:
                    if buy_signals >= required_signals and cash > current:
                        qty = int(cash * 0.25 // current)
                        if qty > 0:
                            cash -= current * qty
                            holdings[ticker] = {"qty": qty, "buy_price": current}
                            trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                           "price": current, "qty": qty, "profit_pct": 0})
                else:
                    buy_price  = holdings[ticker]["buy_price"]
                    profit_pct = (current - buy_price) / buy_price * 100
                    if sell_signals >= required_signals or profit_pct <= -5.0:
                        qty = holdings[ticker]["qty"]
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]

                prev_macd_hist[ticker] = hist

        final_value = cash
        for ticker, h in holdings.items():
            last = float(data[ticker]["Close"].iloc[-1])
            final_value += last * h["qty"] if np.isfinite(last) else 0

        return {"strategy": f"앙상블 (MACD+RSI+BB, {required_signals}/3 신호)", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 12. 추세 필터 + MACD 타이밍 ─────────────────────────
    def run_trend_filter_macd(self, tickers: list, period: str = "5y",
                               trend_short: int = 60, trend_long: int = 120) -> dict:
        """
        추세 필터 + MACD 타이밍 - 기관 투자자들의 표준 2단계 접근법
        1단계 (상승장 판단): MA60 > MA120 이면 상승장, 아니면 관망
        2단계 (진입 타이밍): 상승장에서만 MACD 골든크로스 시 매수

        → 하락장 손실을 원천 차단하면서 상승장 모멘텀 포착
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        indicators = {}
        for t in tickers:
            close    = data[t]["Close"]
            ma_s     = close.rolling(trend_short).mean()
            ma_l     = close.rolling(trend_long).mean()
            macd_line   = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            macd_hist   = macd_line - macd_line.ewm(span=9, adjust=False).mean()
            indicators[t] = {"ma_s": ma_s, "ma_l": ma_l, "hist": macd_hist}

        prev_hist = {t: None for t in tickers}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                if not np.isfinite(current):
                    continue

                try:
                    ma_s = float(indicators[ticker]["ma_s"].loc[date])
                    ma_l = float(indicators[ticker]["ma_l"].loc[date])
                    hist = float(indicators[ticker]["hist"].loc[date])
                except KeyError:
                    continue
                if not all(np.isfinite(v) for v in [ma_s, ma_l, hist]):
                    continue

                in_uptrend = ma_s > ma_l   # 추세 필터: 상승장 여부
                ph = prev_hist[ticker]

                if ticker not in holdings:
                    # 상승장 + MACD 골든크로스만 매수
                    if in_uptrend and ph is not None and ph < 0 and hist >= 0 and cash > current:
                        qty = int(cash * 0.25 // current)
                        if qty > 0:
                            cash -= current * qty
                            holdings[ticker] = {"qty": qty, "buy_price": current}
                            trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                           "price": current, "qty": qty, "profit_pct": 0})
                else:
                    buy_price  = holdings[ticker]["buy_price"]
                    profit_pct = (current - buy_price) / buy_price * 100
                    # 하락장 전환 또는 MACD 데드크로스 또는 손절
                    if (not in_uptrend) or (ph is not None and ph >= 0 and hist < 0) or profit_pct <= -5.0:
                        qty = holdings[ticker]["qty"]
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]

                prev_hist[ticker] = hist

        final_value = cash
        for ticker, h in holdings.items():
            last = float(data[ticker]["Close"].iloc[-1])
            final_value += last * h["qty"] if np.isfinite(last) else 0

        return {"strategy": f"추세필터+MACD (MA{trend_short}/MA{trend_long})", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}

    # ── 13. 변동성 레짐 적응형 ───────────────────────────────
    def run_regime_adaptive(self, tickers: list, period: str = "5y",
                             atr_window: int = 14, regime_window: int = 60) -> dict:
        """
        변동성 레짐 적응형 - 시장 상태를 감지해 전략을 자동 전환
        ATR이 과거 평균보다 낮으면(조용한 장) → 볼린저 밴드 역추세
        ATR이 과거 평균보다 높으면(요동치는 장) → 모멘텀(MA 골든크로스)

        → 시장 국면을 '읽고' 그에 맞는 전략을 선택하는 방식
          헤지펀드 퀀트 팀의 레짐 감지(Regime Detection) 단순화 버전
        """
        cash = self.initial_cash
        holdings = {}
        trades = []

        data = {t: fetch_data(t, period) for t in tickers}
        dates = sorted(set().union(*[df.index for df in data.values()]))

        indicators = {}
        for t in tickers:
            close     = data[t]["Close"]
            high      = data[t]["High"]
            low       = data[t]["Low"]
            prev_close = close.shift(1)

            # ATR
            tr  = pd.concat([high - low,
                              (high - prev_close).abs(),
                              (low  - prev_close).abs()], axis=1).max(axis=1)
            atr = tr.rolling(atr_window).mean()
            atr_avg = atr.rolling(regime_window).mean()   # ATR의 장기 평균 = 보통 변동성

            # 볼린저 밴드
            mid      = close.rolling(20).mean()
            std      = close.rolling(20).std()
            bb_upper = mid + 2 * std
            bb_lower = mid - 2 * std

            # 모멘텀 (MA20/60)
            ma20 = close.rolling(20).mean()
            ma60 = close.rolling(60).mean()

            indicators[t] = {
                "atr": atr, "atr_avg": atr_avg,
                "bb_upper": bb_upper, "bb_lower": bb_lower,
                "ma20": ma20, "ma60": ma60,
            }

        prev_ma_above = {t: None for t in tickers}

        for date in dates:
            for ticker in tickers:
                df = data[ticker]
                if date not in df.index:
                    continue
                current = float(df.loc[date]["Close"])
                if not np.isfinite(current):
                    continue

                try:
                    atr     = float(indicators[ticker]["atr"].loc[date])
                    atr_avg = float(indicators[ticker]["atr_avg"].loc[date])
                    bb_u    = float(indicators[ticker]["bb_upper"].loc[date])
                    bb_l    = float(indicators[ticker]["bb_lower"].loc[date])
                    ma20    = float(indicators[ticker]["ma20"].loc[date])
                    ma60    = float(indicators[ticker]["ma60"].loc[date])
                except KeyError:
                    continue
                if not all(np.isfinite(v) for v in [atr, atr_avg, bb_u, bb_l, ma20, ma60]):
                    continue

                low_vol  = atr < atr_avg          # 저변동성 → 역추세 (볼린저)
                ma_above = ma20 > ma60             # 모멘텀 방향
                prev_ma  = prev_ma_above[ticker]

                if ticker not in holdings:
                    if low_vol:
                        # 저변동성 레짐: 볼린저 하단 터치 → 매수
                        if current <= bb_l and cash > current:
                            qty = int(cash * 0.25 // current)
                            if qty > 0:
                                cash -= current * qty
                                holdings[ticker] = {"qty": qty, "buy_price": current, "regime": "mean_revert"}
                                trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                               "price": current, "qty": qty, "profit_pct": 0})
                    else:
                        # 고변동성 레짐: MA 골든크로스 → 매수
                        if prev_ma is False and ma_above and cash > current:
                            qty = int(cash * 0.25 // current)
                            if qty > 0:
                                cash -= current * qty
                                holdings[ticker] = {"qty": qty, "buy_price": current, "regime": "momentum"}
                                trades.append({"date": date, "ticker": ticker, "action": "BUY",
                                               "price": current, "qty": qty, "profit_pct": 0})
                else:
                    buy_price  = holdings[ticker]["buy_price"]
                    profit_pct = (current - buy_price) / buy_price * 100
                    regime     = holdings[ticker]["regime"]

                    sell = False
                    if regime == "mean_revert" and (current >= bb_u or profit_pct <= -5.0):
                        sell = True   # 볼린저 상단 or 손절
                    elif regime == "momentum" and (prev_ma is True and not ma_above or profit_pct <= -5.0):
                        sell = True   # MA 데드크로스 or 손절

                    if sell:
                        qty = holdings[ticker]["qty"]
                        cash += current * qty
                        trades.append({"date": date, "ticker": ticker, "action": "SELL",
                                       "price": current, "qty": qty, "profit_pct": round(profit_pct, 2)})
                        del holdings[ticker]

                prev_ma_above[ticker] = ma_above

        final_value = cash
        for ticker, h in holdings.items():
            last = float(data[ticker]["Close"].iloc[-1])
            final_value += last * h["qty"] if np.isfinite(last) else 0

        return {"strategy": f"변동성 레짐 적응형 (ATR{atr_window}/{regime_window}일)", "initial_cash": self.initial_cash,
                "final_value": final_value, "trades": trades}
