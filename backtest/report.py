import pandas as pd


def print_report(result: dict, verbose: bool = True):
    strategy     = result["strategy"]
    initial      = result["initial_cash"]
    final        = result["final_value"]
    trades       = result["trades"]
    total_return = (final - initial) / initial * 100

    sells = [t for t in trades if t["action"] == "SELL"]
    wins  = [t for t in sells if t["profit_pct"] > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0

    # MDD 계산
    values = []
    running = initial
    for t in trades:
        if t["action"] == "SELL":
            running += t["price"] * t["qty"] * (t["profit_pct"] / 100)
        values.append(running)
    if values:
        peak = values[0]
        mdd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > mdd:
                mdd = dd
    else:
        mdd = 0.0

    print("=" * 55)
    print(f"  전략: {strategy}")
    print("=" * 55)
    print(f"  초기 자본    : {initial:>15,.0f} 원")
    print(f"  최종 자산    : {final:>15,.0f} 원")
    print(f"  총 수익률    : {total_return:>+14.2f} %")
    print(f"  MDD          : {mdd:>13.2f} %")
    print(f"  총 매도 횟수 : {len(sells):>14} 회")
    print(f"  승률         : {win_rate:>13.1f} %")
    print("=" * 55)

    if verbose and sells:
        df = pd.DataFrame(sells)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        out = df[["date", "ticker", "price", "qty", "profit_pct"]].copy()
        out.columns = ["날짜", "종목", "매도가", "수량", "수익률(%)"]
        print("\n  [매도 거래 내역]")
        print(out.to_string(index=False))

    print()


def print_summary(results: list):
    """전략 비교 요약표"""
    print("\n" + "=" * 72)
    print("  📊 전략 비교 요약 (수익률 순)")
    print("=" * 72)
    print(f"  {'전략':<36} {'수익률':>8}  {'MDD':>7}  {'승률':>6}  {'거래':>5}")
    print(f"  {'-'*68}")

    def get_mdd(r):
        values = []
        running = r["initial_cash"]
        for t in r["trades"]:
            if t["action"] == "SELL":
                running += t["price"] * t["qty"] * (t["profit_pct"] / 100)
            values.append(running)
        if not values:
            return 0.0
        peak, mdd = values[0], 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > mdd:
                mdd = dd
        return mdd

    sorted_results = sorted(results, key=lambda r: r["final_value"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(sorted_results):
        ret   = (r["final_value"] - r["initial_cash"]) / r["initial_cash"] * 100
        sells = [t for t in r["trades"] if t["action"] == "SELL"]
        wins  = [t for t in sells if t["profit_pct"] > 0]
        wr    = len(wins) / len(sells) * 100 if sells else 0
        mdd   = get_mdd(r)
        medal = medals[i] if i < 3 else "  "
        print(f"  {medal} {r['strategy']:<34} {ret:>+7.2f}%  -{mdd:>5.1f}%  {wr:>5.1f}%  {len(sells):>4}회")

    print("=" * 72)
    print()
