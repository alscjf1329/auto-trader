"""
dashboard/data.py - 대시보드용 데이터 로더
KIS API 없이도 로컬 캐시 파일만으로 동작 가능.
"""

import json
import csv
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

ROOT     = Path(__file__).parent.parent
LOGS     = ROOT / "logs"
TRADES_CSV       = LOGS / "trades.csv"
TRADES_DIR       = LOGS / "trades"
POOL_CACHE       = LOGS / "pool_cache.json"
POOL_CACHE_US    = LOGS / "pool_cache_us.json"
RESEARCH         = LOGS / "research_cache.json"
RUNNER_LOG       = LOGS / "runner.log"
REGIME_CACHE     = LOGS / "regime_cache.json"
SNAPSHOT_PATH    = LOGS / "portfolio_snapshots.json"
TRAILING_PATH    = LOGS / "trailing_stops.json"


# ── 거래 이력 ─────────────────────────────────────────────────

def load_trades(days: int = 90) -> list[dict]:
    """trades.csv에서 최근 N일 거래 내역 로드"""
    if not TRADES_CSV.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    with open(TRADES_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("date", "") >= cutoff:
                rows.append(row)
    return rows


def load_today_trades() -> list[dict]:
    today_path = TRADES_DIR / f"{date.today().isoformat()}.json"
    if not today_path.exists():
        return []
    with open(today_path, encoding="utf-8") as f:
        return json.load(f)


# ── 후보 풀 캐시 ──────────────────────────────────────────────

def load_pool_cache() -> dict:
    """pool_cache.json 전체 로드"""
    if not POOL_CACHE.exists():
        return {}
    with open(POOL_CACHE, encoding="utf-8") as f:
        return json.load(f)


def load_pool_cache_us() -> dict:
    if not POOL_CACHE_US.exists():
        return {}
    with open(POOL_CACHE_US, encoding="utf-8") as f:
        return json.load(f)


def get_factor_data() -> list[dict]:
    """universe_data 에서 팩터 점수 추출"""
    cache = load_pool_cache()
    return cache.get("universe_data", [])


# ── 리서치 캐시 ───────────────────────────────────────────────

def load_research() -> dict:
    if not RESEARCH.exists():
        return {}
    with open(RESEARCH, encoding="utf-8") as f:
        return json.load(f)


# ── 러너 로그 ─────────────────────────────────────────────────

def load_regime() -> dict:
    """최신 시장 국면 로드"""
    if not REGIME_CACHE.exists():
        return {}
    with open(REGIME_CACHE, encoding="utf-8") as f:
        history = json.load(f)
    return history[-1] if history else {}


def load_regime_history() -> list[dict]:
    """시장 국면 이력 전체"""
    if not REGIME_CACHE.exists():
        return []
    with open(REGIME_CACHE, encoding="utf-8") as f:
        return json.load(f)


def load_portfolio_snapshots() -> list[dict]:
    """일별 자산 스냅샷 전체 로드"""
    if not SNAPSHOT_PATH.exists():
        return []
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_trailing_stops() -> dict:
    """현재 트레일링 스탑 추적 중인 종목 로드"""
    if not TRAILING_PATH.exists():
        return {}
    with open(TRAILING_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_runner_log(n_lines: int = 300) -> list[str]:
    if not RUNNER_LOG.exists():
        return ["[로그 없음] runner.py가 아직 실행되지 않았습니다."]
    with open(RUNNER_LOG, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [l.rstrip() for l in lines[-n_lines:]]


# ── 포트폴리오 성과 계산 ─────────────────────────────────────

def compute_portfolio_curve(
    trades: list[dict],
    initial_capital: float = 5_000_000,
) -> list[dict]:
    """
    거래 이력으로 누적 손익 커브 계산.
    매도 시 profit_amount 누적. 매수는 자본 감소 없음 (보유 자산 트래킹 미포함).
    """
    capital = initial_capital
    curve   = [{"date": trades[0]["date"] if trades else date.today().isoformat(),
                "value": capital, "pnl": 0.0}]
    cumulative = 0.0
    for t in sorted(trades, key=lambda x: x["datetime"]):
        if t["action"] == "SELL":
            pnl = float(t.get("profit_amount") or 0)
            cumulative += pnl
            curve.append({
                "date":  t["date"],
                "value": capital + cumulative,
                "pnl":   cumulative,
                "code":  t["code"],
                "name":  t["name"],
                "profit_pct": float(t.get("profit_pct") or 0),
            })
    return curve


def compute_stats(trades: list[dict]) -> dict:
    """거래 통계 계산"""
    sells = [t for t in trades if t["action"] == "SELL" and t.get("profit_pct")]
    if not sells:
        return {
            "total_trades": len(trades),
            "win_rate": 0,
            "avg_profit": 0,
            "avg_loss": 0,
            "total_pnl": 0,
            "best_trade": None,
            "worst_trade": None,
        }
    pcts = [float(t["profit_pct"]) for t in sells]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p <= 0]
    amounts = [float(t.get("profit_amount") or 0) for t in sells]

    return {
        "total_trades": len(trades),
        "sell_count":   len(sells),
        "win_rate":     len(wins) / len(sells) * 100 if sells else 0,
        "avg_profit":   sum(wins) / len(wins) if wins else 0,
        "avg_loss":     sum(losses) / len(losses) if losses else 0,
        "total_pnl":    sum(amounts),
        "best_trade":   max(sells, key=lambda x: float(x.get("profit_pct") or 0)),
        "worst_trade":  min(sells, key=lambda x: float(x.get("profit_pct") or 0)),
    }


def per_code_stats(trades: list[dict]) -> list[dict]:
    """종목별 거래 통계"""
    from collections import defaultdict
    stats = defaultdict(lambda: {"buy": 0, "sell": 0, "pnl": 0.0, "pnl_pct_sum": 0.0, "count": 0})
    for t in trades:
        code = t["code"]
        if t["action"] == "BUY":
            stats[code]["buy"] += 1
            stats[code]["name"] = t["name"]
            stats[code]["code"] = code
        elif t["action"] == "SELL":
            stats[code]["sell"] += 1
            stats[code]["pnl"] += float(t.get("profit_amount") or 0)
            stats[code]["pnl_pct_sum"] += float(t.get("profit_pct") or 0)
            stats[code]["count"] += 1
            stats[code]["name"] = t["name"]
            stats[code]["code"] = code
    result = []
    for code, s in stats.items():
        avg_pct = s["pnl_pct_sum"] / s["count"] if s["count"] else 0
        result.append({**s, "avg_pct": round(avg_pct, 2)})
    return sorted(result, key=lambda x: x["pnl"], reverse=True)
