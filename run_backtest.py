from backtest.engine import BacktestEngine
from backtest.report import print_report, print_summary

engine = BacktestEngine(initial_cash=10_000_000)

PERIOD = "5y"

TICKERS = [
    "005930.KS",   # 삼성전자
    "000660.KS",   # SK하이닉스
    "035420.KS",   # NAVER
    "005380.KS",   # 현대차
    "068270.KS",   # 셀트리온
    "105560.KS",   # KB금융
    "005490.KS",   # POSCO홀딩스
    "035720.KS",   # 카카오
]

print(f"\n백테스팅 시작 (기간: {PERIOD} / 초기자본: 1,000만원)\n")

results = []

# ── 기존 단일 전략 (비교 기준) ──────────────────
for r in [
    engine.run_golden_cross(TICKERS, period=PERIOD),
    engine.run_macd(TICKERS, period=PERIOD),
    engine.run_dual_momentum(TICKERS, period=PERIOD),
    engine.run_bollinger(TICKERS, period=PERIOD),
    engine.run_volatility_breakout(TICKERS, period=PERIOD),
]:
    print_report(r, verbose=False)
    results.append(r)

# ── 조합/변형 전략 ───────────────────────────────
print("\n" + "─"*55)
print("  🔬 조합/변형 전략")
print("─"*55 + "\n")

for r in [
    engine.run_ensemble(TICKERS, period=PERIOD, required_signals=2),
    engine.run_trend_filter_macd(TICKERS, period=PERIOD),
    engine.run_regime_adaptive(TICKERS, period=PERIOD),
]:
    print_report(r, verbose=False)
    results.append(r)

print_summary(results)
