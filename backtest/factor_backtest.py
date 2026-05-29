"""
factor_backtest.py - 팩터 모델 백테스터

무엇을 검증하나:
  1. IC (Information Coefficient) — 각 팩터가 실제로 미래 수익률을 예측하는가
  2. 팩터 포트폴리오 수익률 — 상위 20% vs 하위 20% vs 코스피 벤치마크
  3. 현재 가중치의 백테스트 성과 — 샤프비율 / MDD / 연환산 수익률
  4. 최적 가중치 제안 — IC 기반 자동 계산

사용법:
  python -m backtest.factor_backtest
  python -m backtest.factor_backtest --period 3y --rebal monthly
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# auto-trader 루트 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))
import settings


# ── 팩터 계산 (yfinance 데이터 기반, KIS 수급 제외) ──────────
AVAILABLE_FACTORS = ["momentum_1m", "momentum_3m", "momentum_6m", "volume_ratio", "pos_52w", "volatility"]


def _compute_factors(price_df: pd.DataFrame, volume_df: pd.DataFrame) -> pd.DataFrame:
    """
    월별 팩터 스냅샷 생성.
    Returns DataFrame: index=날짜(월말), columns=MultiIndex(팩터, 종목코드)
    """
    monthly_dates = price_df.resample("ME").last().index

    records = []
    for dt in monthly_dates:
        past = price_df.loc[:dt]
        past_vol = volume_df.loc[:dt]
        if len(past) < 60:
            continue

        row = {"date": dt}
        for ticker in price_df.columns:
            col = past[ticker].dropna()
            vcol = past_vol[ticker].dropna()
            if len(col) < 60:
                continue

            curr = col.iloc[-1]
            # 모멘텀
            row[("momentum_1m",  ticker)] = (col.iloc[-1] / col.iloc[-21]  - 1) * 100 if len(col) >= 21  else np.nan
            row[("momentum_3m",  ticker)] = (col.iloc[-1] / col.iloc[-63]  - 1) * 100 if len(col) >= 63  else np.nan
            row[("momentum_6m",  ticker)] = (col.iloc[-1] / col.iloc[-126] - 1) * 100 if len(col) >= 126 else np.nan
            # 거래량 비율
            row[("volume_ratio", ticker)] = (
                float(vcol.iloc[-5:].mean()) / float(vcol.iloc[-21:].mean() or 1)
                if len(vcol) >= 21 else np.nan
            )
            # 52주 위치
            h52 = col.iloc[-252:].max() if len(col) >= 252 else col.max()
            l52 = col.iloc[-252:].min() if len(col) >= 252 else col.min()
            row[("pos_52w", ticker)] = (curr - l52) / (h52 - l52) * 100 if h52 != l52 else 50.0
            # 변동성 (역수 — 낮을수록 좋음)
            row[("volatility", ticker)] = col.pct_change().iloc[-21:].std() * np.sqrt(252) * 100 if len(col) >= 21 else np.nan

        records.append(row)

    df = pd.DataFrame(records).set_index("date")
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def _pct_rank_row(series: pd.Series) -> pd.Series:
    """한 시점의 팩터값을 백분위 랭크(0~1)로 변환"""
    return series.rank(pct=True, na_option="bottom")


def _composite_score(factor_snap: pd.DataFrame, weights: dict) -> pd.Series:
    """가중합산 팩터 점수 계산 (한 시점)"""
    score = pd.Series(0.0, index=factor_snap.columns.get_level_values(1).unique())

    for factor, w in weights.items():
        if factor not in factor_snap.columns.get_level_values(0) or w == 0:
            continue
        vals = factor_snap[factor].squeeze()  # 1-row DataFrame → Series
        if isinstance(vals, pd.DataFrame):
            vals = vals.iloc[0]
        if factor == "volatility":
            ranked = _pct_rank_row(-vals)   # 변동성은 낮을수록 좋음
        elif factor == "pos_52w":
            # 역U자형: 50% 근방이 이상적
            ranked = _pct_rank_row(-(vals - 50).abs())
        else:
            ranked = _pct_rank_row(vals)
        score = score.add(ranked * w, fill_value=0)

    return score


# ── IC 계산 ──────────────────────────────────────────────────

def compute_ic(factor_df: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.DataFrame:
    """
    각 팩터의 IC(Information Coefficient) = 팩터 점수와 다음달 수익률의 Spearman 상관계수.
    IC > 0.05 이면 유효한 팩터로 간주.
    """
    dates = factor_df.index.intersection(forward_returns.index)
    results = {f: [] for f in AVAILABLE_FACTORS}

    for dt in dates:
        if dt not in factor_df.index or dt not in forward_returns.index:
            continue
        fwd = forward_returns.loc[dt]
        for factor in AVAILABLE_FACTORS:
            if factor not in factor_df.columns.get_level_values(0):
                continue
            fval = factor_df[factor].loc[dt]
            common = fval.index.intersection(fwd.index)
            if len(common) < 5:
                continue
            ic = fval[common].corr(fwd[common], method="spearman")
            if not np.isnan(ic):
                results[factor].append(ic)

    summary = []
    for factor, ics in results.items():
        if not ics:
            continue
        ic_mean = np.mean(ics)
        ic_std  = np.std(ics) or 1e-10
        summary.append({
            "factor":   factor,
            "IC 평균":  round(ic_mean, 4),
            "IC 표준편차": round(ic_std, 4),
            "ICIR":     round(ic_mean / ic_std, 3),   # IC Information Ratio
            "유효 기간": len(ics),
            "IC > 0":   f"{sum(1 for x in ics if x > 0) / len(ics) * 100:.0f}%",
        })

    return pd.DataFrame(summary).sort_values("IC 평균", ascending=False)


# ── 거래비용 상수 (한국주식 기준) ───────────────────────────────
# 매수: 수수료 0.015% + 슬리피지 0.05%
# 매도: 수수료 0.015% + 증권거래세 0.18% + 슬리피지 0.05%
_BUY_COST  = 0.00015 + 0.0005   # 0.065%
_SELL_COST = 0.00015 + 0.0018 + 0.0005  # 0.245%


# ── 팩터 포트폴리오 시뮬레이션 ───────────────────────────────

def simulate_factor_portfolio(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    weights: dict,
    top_pct: float = 0.2,
    rebal_freq: str = "ME",
    initial_cash: float = 10_000_000,
    apply_costs: bool = True,
) -> dict:
    """
    상위 top_pct 종목 동일 가중 포트폴리오 시뮬레이션.
    rebal_freq: 'ME'=월말, 'QE'=분기말
    apply_costs: 거래비용(수수료+세금+슬리피지) 반영 여부
    """
    rebal_dates = factor_df.index
    price_monthly = price_df.resample(rebal_freq).last()

    portfolio_value = [initial_cash]
    portfolio_dates = [rebal_dates[0]]
    total_cost_paid = 0.0

    holdings = {}  # ticker → shares

    for i, dt in enumerate(rebal_dates[:-1]):
        next_dt = rebal_dates[i + 1]

        # 팩터 점수 계산
        score = _composite_score(factor_df.loc[dt:dt], weights)
        if score.empty:
            continue

        n_select = max(1, int(len(score) * top_pct))
        selected = score.nlargest(n_select).index.tolist()

        # 현재 포트폴리오 청산 (매도비용 차감)
        if i == 0:
            curr_value = initial_cash
        else:
            curr_value = 0.0
            for tkr, sh in holdings.items():
                if tkr in price_monthly.columns:
                    px = price_monthly[tkr].asof(dt)
                    if px and not np.isnan(float(px)):
                        gross = sh * float(px)
                        if apply_costs:
                            cost = gross * _SELL_COST
                            total_cost_paid += cost
                            curr_value += gross - cost
                        else:
                            curr_value += gross

        # 동일 가중 재구성 (매수비용 차감)
        holdings = {}
        if selected and curr_value > 0:
            alloc = curr_value / len(selected)
            if apply_costs:
                alloc_after_cost = alloc * (1 - _BUY_COST)
                total_cost_paid += alloc * _BUY_COST * len(selected)
            else:
                alloc_after_cost = alloc
            for tkr in selected:
                if tkr in price_monthly.columns:
                    px = price_monthly[tkr].asof(dt)
                    if px and not np.isnan(float(px)) and float(px) > 0:
                        holdings[tkr] = alloc_after_cost / float(px)

        # 다음 리밸런싱 시점 포트폴리오 가치
        next_value = 0.0
        for tkr, sh in holdings.items():
            if tkr in price_monthly.columns:
                px = price_monthly[tkr].asof(next_dt)
                next_value += sh * float(px) if px and not np.isnan(float(px)) else 0
        if not holdings:
            next_value = curr_value

        portfolio_value.append(next_value)
        portfolio_dates.append(next_dt)

    pf_series = pd.Series(portfolio_value, index=portfolio_dates)
    returns   = pf_series.pct_change().dropna()

    total_ret  = (pf_series.iloc[-1] / pf_series.iloc[0] - 1) * 100
    years      = len(returns) / 12
    cagr       = ((pf_series.iloc[-1] / pf_series.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
    sharpe     = returns.mean() / returns.std() * np.sqrt(12) if returns.std() > 0 else 0
    peak       = pf_series.cummax()
    drawdown   = (pf_series - peak) / peak * 100
    mdd        = drawdown.min()

    return {
        "series":      pf_series,
        "total_ret":   total_ret,
        "cagr":        cagr,
        "sharpe":      sharpe,
        "mdd":         mdd,
        "n_rebal":     len(rebal_dates),
        "total_cost":  total_cost_paid,
        "cost_drag":   total_cost_paid / initial_cash * 100,
    }


# ── IC 기반 최적 가중치 계산 ─────────────────────────────────

def suggest_weights(ic_df: pd.DataFrame) -> dict:
    """
    IC 평균이 양수인 팩터만 선택, ICIR 비례로 가중치 계산.
    음수 IC 팩터는 제외.
    """
    valid = ic_df[ic_df["IC 평균"] > 0].copy()
    if valid.empty:
        return {}

    # ICIR 기반 비례 배분
    valid["weight_raw"] = valid["ICIR"].clip(lower=0)
    total = valid["weight_raw"].sum()
    if total == 0:
        return {}
    valid["weight"] = (valid["weight_raw"] / total).round(2)

    # 합계를 정확히 1.0으로 맞춤
    weights = dict(zip(valid["factor"], valid["weight"]))
    diff = 1.0 - sum(weights.values())
    top_factor = valid.sort_values("ICIR", ascending=False)["factor"].iloc[0]
    weights[top_factor] = round(weights[top_factor] + diff, 2)

    return weights


# ── 메인 ─────────────────────────────────────────────────────

def run(period: str = "3y", rebal: str = "monthly", verbose: bool = True):
    print("\n" + "=" * 60)
    print("  팩터 백테스트 시작")
    print("=" * 60)

    # ── 1. 데이터 수집 ────────────────────────────────────────
    universe   = settings.UNIVERSE
    yf_tickers = [f"{s['code']}.KS" for s in universe]
    bench_tick = "069500.KS"   # KODEX 200

    print(f"\n[1] 유니버스 {len(universe)}종목 {period} 데이터 수집 중...")
    raw = yf.download(yf_tickers + [bench_tick], period=period,
                      auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        price_df  = raw["Close"].dropna(how="all", axis=1)
        volume_df = raw["Volume"].dropna(how="all", axis=1)
    else:
        print("  데이터 구조 오류 — 종목 수를 늘려 재시도하세요.")
        return

    # 벤치마크 분리
    bench_series = price_df.pop(bench_tick) if bench_tick in price_df.columns else None
    if bench_tick in volume_df.columns:
        volume_df.drop(columns=[bench_tick], inplace=True)

    tickers = price_df.columns.tolist()
    print(f"  수집 완료: {len(tickers)}종목 / {len(price_df)}일")

    # ── 2. 월별 팩터 스냅샷 ──────────────────────────────────
    print("\n[2] 팩터 스냅샷 생성 중...")
    factor_df = _compute_factors(price_df, volume_df)
    print(f"  {len(factor_df)}개 월별 스냅샷 생성")

    # ── 3. 선행 수익률 계산 ──────────────────────────────────
    monthly_price = price_df.resample("ME").last()
    forward_ret   = monthly_price.pct_change().shift(-1) * 100   # 다음달 수익률
    forward_ret   = forward_ret.reindex(factor_df.index)

    # ── 4. IC 분석 ───────────────────────────────────────────
    print("\n[3] IC(Information Coefficient) 분석...")
    ic_df = compute_ic(factor_df, forward_ret)
    print("\n  ┌─ 팩터별 IC 분석 결과 ─────────────────────────────")
    print(f"  │ {'팩터':<16} {'IC 평균':>8} {'ICIR':>7} {'IC>0':>6} {'기간':>5}")
    print("  │ " + "─" * 46)
    for _, row in ic_df.iterrows():
        flag = "✅" if row["IC 평균"] > 0.03 else ("⚠️ " if row["IC 평균"] > 0 else "❌")
        print(f"  │ {flag} {row['factor']:<14} {row['IC 평균']:>8.4f} {row['ICIR']:>7.3f} "
              f"{row['IC > 0']:>6} {row['유효 기간']:>4}개월")
    print("  └" + "─" * 48)

    # ── 5. 현재 가중치로 백테스트 ────────────────────────────
    current_weights = {
        k: v for k, v in settings.FACTOR_WEIGHTS.items()
        if k in AVAILABLE_FACTORS
    }
    # KIS 수급 팩터 제외 (백테스트에서 과거 데이터 없음)
    excluded = [k for k in settings.FACTOR_WEIGHTS if k not in AVAILABLE_FACTORS]
    if excluded:
        print(f"\n  ※ 수급 팩터 ({', '.join(excluded)}) 는 과거 데이터 없어 제외됨")
        # 나머지로 가중치 재정규화
        total_w = sum(current_weights.values()) or 1
        current_weights = {k: v / total_w for k, v in current_weights.items()}

    rebal_freq = "ME" if rebal == "monthly" else "QE"

    print(f"\n[4] 현재 가중치로 팩터 포트폴리오 백테스트 ({rebal})...")
    result_current      = simulate_factor_portfolio(
        factor_df, price_df, current_weights,
        top_pct=0.2, rebal_freq=rebal_freq, apply_costs=True,
    )
    result_current_gross = simulate_factor_portfolio(
        factor_df, price_df, current_weights,
        top_pct=0.2, rebal_freq=rebal_freq, apply_costs=False,
    )

    # ── 6. IC 기반 최적 가중치로 백테스트 ───────────────────
    suggested = suggest_weights(ic_df)
    result_suggested = None
    if suggested:
        print(f"[5] IC 기반 최적 가중치로 백테스트...")
        result_suggested = simulate_factor_portfolio(
            factor_df, price_df, suggested,
            top_pct=0.2, rebal_freq=rebal_freq, apply_costs=True,
        )

    # ── 7. 벤치마크 수익률 계산 ──────────────────────────────
    bench_ret = 0.0
    bench_sharpe = 0.0
    bench_mdd = 0.0
    if bench_series is not None:
        bench_monthly = bench_series.resample("ME").last().reindex(factor_df.index).dropna()
        if len(bench_monthly) > 1:
            bench_ret    = (bench_monthly.iloc[-1] / bench_monthly.iloc[0] - 1) * 100
            br = bench_monthly.pct_change().dropna()
            bench_sharpe = br.mean() / br.std() * np.sqrt(12) if br.std() > 0 else 0
            peak = bench_monthly.cummax()
            bench_mdd = ((bench_monthly - peak) / peak * 100).min()

    # ── 8. 결과 출력 ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  📊 백테스트 결과 요약 (거래비용 포함)")
    print("=" * 60)
    print(f"  거래비용: 매수 {_BUY_COST*100:.3f}% / 매도 {_SELL_COST*100:.3f}% "
          f"(수수료+세금+슬리피지)")

    rows = [
        ("KOSPI 벤치마크 (KODEX 200)",       bench_ret,    bench_sharpe,    bench_mdd,   None),
        ("현재 가중치 (비용 제외)",            result_current_gross["total_ret"],
         result_current_gross["sharpe"], result_current_gross["mdd"],          None),
        ("현재 가중치 (비용 포함)",            result_current["total_ret"],
         result_current["sharpe"],       result_current["mdd"],
         result_current["cost_drag"]),
    ]
    if result_suggested:
        rows.append(("IC 최적 가중치 (비용 포함)", result_suggested["total_ret"],
                     result_suggested["sharpe"], result_suggested["mdd"],
                     result_suggested["cost_drag"]))

    print(f"\n  {'전략':<30} {'총수익률':>9} {'샤프':>7} {'MDD':>8} {'비용드래그':>10}")
    print("  " + "─" * 68)
    for name, ret, sh, mdd, cost in rows:
        alpha = " ✅" if ret > bench_ret else ""
        cost_str = f"{cost:>8.1f}%" if cost is not None else "        -"
        print(f"  {name:<30} {ret:>+8.1f}%  {sh:>5.2f}  {mdd:>7.1f}%  {cost_str}{alpha}")

    # ── 9. 최적 가중치 제안 ──────────────────────────────────
    if suggested:
        print("\n" + "=" * 60)
        print("  💡 IC 기반 권장 가중치 (settings.yaml 업데이트 참고)")
        print("=" * 60)
        print("\n  factor_weights:")
        for factor, w in sorted(suggested.items(), key=lambda x: -x[1]):
            current_w = settings.FACTOR_WEIGHTS.get(factor, 0)
            arrow = "↑" if w > current_w else ("↓" if w < current_w else "=")
            print(f"    {factor:<16}: {w:.2f}   (현재: {current_w:.2f} {arrow})")
        print()
        print("  ⚠️  수급 팩터(foreign_flow, inst_flow)는 백테스트 제외됨.")
        print("     실전에서는 해당 팩터 가중치를 별도로 조정하세요.")

    print("\n" + "=" * 60)
    return {
        "ic": ic_df,
        "current": result_current,
        "suggested_weights": suggested,
        "suggested": result_suggested,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="팩터 백테스터")
    parser.add_argument("--period", default="3y", choices=["1y", "2y", "3y", "5y"],
                        help="백테스트 기간 (기본: 3y)")
    parser.add_argument("--rebal",  default="monthly", choices=["monthly", "quarterly"],
                        help="리밸런싱 주기 (기본: monthly)")
    args = parser.parse_args()
    run(period=args.period, rebal=args.rebal)
