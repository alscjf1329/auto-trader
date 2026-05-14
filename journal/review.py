"""
journal/review.py - 투자 이력 복기 리포트

사용법:
    python -m journal.review           # 전체 요약
    python -m journal.review --month 2026-05   # 월별 요약
    python -m journal.review --date 2026-05-12 # 특정일 상세
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
TRADES_DIR = LOG_DIR / "trades"
CSV_PATH = LOG_DIR / "trades.csv"


def _load_all() -> list[dict]:
    """CSV에서 전체 이력 로드"""
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _load_day(date_str: str) -> list[dict]:
    """특정 날짜 JSON 로드"""
    path = TRADES_DIR / f"{date_str}.json"
    if not path.exists():
        print(f"[{date_str}] 이력 없음")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fmt_pct(v) -> str:
    try:
        f = float(v)
        return f"{f:+.2f}%"
    except (ValueError, TypeError):
        return "-"


def _fmt_won(v) -> str:
    try:
        return f"{int(v):+,}원"
    except (ValueError, TypeError):
        return "-"


# ──────────────────────────────────────────
# 리포트 함수들
# ──────────────────────────────────────────

def report_day(date_str: str):
    """특정일 상세 이력"""
    records = _load_day(date_str)
    if not records:
        return

    print(f"\n{'='*55}")
    print(f"  📅 {date_str} 매매 이력")
    print(f"{'='*55}")

    for r in records:
        action_icon = "🟢" if r["action"] == "BUY" else "🔴"
        profit_str = ""
        if r["action"] == "SELL" and r.get("profit_pct"):
            profit_str = f"  손익 {_fmt_pct(r['profit_pct'])} ({_fmt_won(r['profit_amount'])})"
        print(f"  {action_icon} {r['datetime']}  [{r['code']}] {r['name']}")
        print(f"     {r['action']} {r['qty']}주 @ {int(r['price']):,}원 = {int(r['amount']):,}원{profit_str}")
        if r.get("reason"):
            print(f"     💬 {r['reason']}")
        print()


def report_month(month_str: str):
    """월별 요약 (형식: YYYY-MM)"""
    all_records = _load_all()
    records = [r for r in all_records if r["date"].startswith(month_str)]

    if not records:
        print(f"[{month_str}] 이력 없음")
        return

    sells = [r for r in records if r["action"] == "SELL" and r.get("profit_pct")]
    wins = [r for r in sells if float(r.get("profit_pct") or 0) > 0]
    losses = [r for r in sells if float(r.get("profit_pct") or 0) <= 0]

    total_profit = sum(int(r.get("profit_amount") or 0) for r in sells)
    win_rate = len(wins) / len(sells) * 100 if sells else 0

    best = max(sells, key=lambda r: float(r.get("profit_pct") or 0), default=None)
    worst = min(sells, key=lambda r: float(r.get("profit_pct") or 0), default=None)

    # 날짜별 거래일 수
    trading_days = len(set(r["date"] for r in records))

    print(f"\n{'='*55}")
    print(f"  📊 {month_str} 월간 리포트")
    print(f"{'='*55}")
    print(f"  거래일: {trading_days}일 | 총 매매: {len(records)}건 (매수 {len([r for r in records if r['action']=='BUY'])}, 매도 {len(sells)})")
    print(f"  승률:   {win_rate:.1f}%  ({len(wins)}승 {len(losses)}패)")
    print(f"  실현손익: {total_profit:+,}원")

    if best:
        print(f"\n  🏆 최고 수익: [{best['code']}] {best['name']}  {_fmt_pct(best['profit_pct'])} ({_fmt_won(best['profit_amount'])})")
    if worst:
        print(f"  💀 최대 손실: [{worst['code']}] {worst['name']}  {_fmt_pct(worst['profit_pct'])} ({_fmt_won(worst['profit_amount'])})")

    # 종목별 집계
    by_code = defaultdict(lambda: {"name": "", "buys": 0, "sells": 0, "profit": 0})
    for r in records:
        by_code[r["code"]]["name"] = r["name"]
        by_code[r["code"]]["buys" if r["action"] == "BUY" else "sells"] += 1
        by_code[r["code"]]["profit"] += int(r.get("profit_amount") or 0)

    print(f"\n  {'종목':<18} {'매수':>4} {'매도':>4} {'손익':>12}")
    print(f"  {'-'*42}")
    for code, v in sorted(by_code.items(), key=lambda x: x[1]["profit"], reverse=True):
        print(f"  [{code}] {v['name']:<12} {v['buys']:>4} {v['sells']:>4} {v['profit']:>+12,}원")

    print()


def report_all():
    """전체 요약"""
    records = _load_all()

    if not records:
        print("\n매매 이력이 없습니다. 거래 후 자동으로 기록됩니다.")
        return

    sells = [r for r in records if r["action"] == "SELL" and r.get("profit_pct")]
    wins = [r for r in sells if float(r.get("profit_pct") or 0) > 0]
    losses = [r for r in sells if float(r.get("profit_pct") or 0) <= 0]
    total_profit = sum(int(r.get("profit_amount") or 0) for r in sells)
    win_rate = len(wins) / len(sells) * 100 if sells else 0

    first_date = records[0]["date"] if records else "-"
    last_date = records[-1]["date"] if records else "-"
    trading_days = len(set(r["date"] for r in records))

    # 월별 손익
    monthly = defaultdict(int)
    for r in sells:
        month = r["date"][:7]
        monthly[month] += int(r.get("profit_amount") or 0)

    print(f"\n{'='*55}")
    print(f"  📈 전체 투자 이력 요약")
    print(f"{'='*55}")
    print(f"  기간: {first_date} ~ {last_date}  ({trading_days}거래일)")
    print(f"  총 매매: {len(records)}건 (매수 {len([r for r in records if r['action']=='BUY'])}, 매도 {len(sells)})")
    print(f"  승률:    {win_rate:.1f}%  ({len(wins)}승 {len(losses)}패)")
    print(f"  총 실현손익: {total_profit:+,}원")

    if monthly:
        print(f"\n  📅 월별 손익")
        for month in sorted(monthly):
            bar = "▓" * min(abs(monthly[month]) // 10000, 20)
            sign = "+" if monthly[month] >= 0 else ""
            print(f"  {month}  {sign}{monthly[month]:,}원  {bar}")

    print()


# ──────────────────────────────────────────
# CLI 진입점
# ──────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--date" in args:
        idx = args.index("--date")
        report_day(args[idx + 1])
    elif "--month" in args:
        idx = args.index("--month")
        report_month(args[idx + 1])
    else:
        report_all()
