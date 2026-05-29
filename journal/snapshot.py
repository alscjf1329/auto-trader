"""
journal/snapshot.py - 일일 포트폴리오 자산 스냅샷

장 마감 후 KIS 잔고를 조회해 logs/portfolio_snapshots.json에 누적 저장.
대시보드의 "실제 자산 커브" 차트에 사용.

저장 형식 (배열, 날짜당 1개):
  [
    {
      "datetime": "2026-05-26 16:00:00",
      "date": "2026-05-26",
      "kr_stock_value": 3_000_000,
      "us_stock_value_usd": 500.0,
      "us_stock_value_krw": 675_000,
      "total_krw": 3_675_000
    },
    ...
  ]
"""

import json
from datetime import datetime
from pathlib import Path

_SNAPSHOT_PATH = Path(__file__).parent.parent / "logs" / "portfolio_snapshots.json"

# KRW/USD 기본 환율 (실시간 갱신 미구현 시 사용)
_DEFAULT_USD_KRW = 1_350.0


def save_snapshot(
    kr_balance: list[dict],
    us_balance: list[dict] | None = None,
    usd_to_krw: float = _DEFAULT_USD_KRW,
) -> dict:
    """
    KIS 잔고 → 자산 스냅샷 저장.

    Parameters
    ----------
    kr_balance  : kis_api.get_balance() 결과
    us_balance  : kis_api.get_balance_us() 결과 (없으면 [])
    usd_to_krw  : 환율 (기본 1,350원)

    Returns
    -------
    저장된 스냅샷 dict
    """
    if us_balance is None:
        us_balance = []

    now = datetime.now()

    kr_stock_value     = sum(float(b.get("evlu_amt", 0)) for b in kr_balance)
    us_stock_value_usd = sum(float(b.get("evlu_amt", 0)) for b in us_balance)
    us_stock_value_krw = us_stock_value_usd * usd_to_krw
    total_krw          = kr_stock_value + us_stock_value_krw

    snapshot = {
        "datetime":          now.strftime("%Y-%m-%d %H:%M:%S"),
        "date":              now.strftime("%Y-%m-%d"),
        "kr_stock_value":    round(kr_stock_value),
        "us_stock_value_usd": round(us_stock_value_usd, 2),
        "us_stock_value_krw": round(us_stock_value_krw),
        "total_krw":          round(total_krw),
        "usd_to_krw":         usd_to_krw,
    }

    # ── 파일 누적 (오늘 날짜 기존 항목은 덮어씀) ───────────────
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if _SNAPSHOT_PATH.exists():
        try:
            history = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = []

    today   = now.strftime("%Y-%m-%d")
    history = [h for h in history if h.get("date") != today]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x["date"])
    history = history[-365:]          # 최근 1년만 유지

    _SNAPSHOT_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"[Snapshot] 자산 기록 — "
        f"KR ₩{kr_stock_value:,.0f} | "
        f"US ${us_stock_value_usd:,.2f} (₩{us_stock_value_krw:,.0f}) | "
        f"합계 ₩{total_krw:,.0f}"
    )
    return snapshot


def load_snapshots() -> list[dict]:
    """저장된 스냅샷 전체 로드"""
    if not _SNAPSHOT_PATH.exists():
        return []
    try:
        return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
