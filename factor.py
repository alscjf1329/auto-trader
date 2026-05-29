"""
factor.py - 퀀트 팩터 스코어링 엔진

팩터:
  momentum_1m   : 1개월 수익률 백분위 랭크
  momentum_3m   : 3개월 수익률 백분위 랭크
  momentum_6m   : 6개월 수익률 백분위 랭크  ← IC 0.088, ICIR 0.37 (최강)
  volume_ratio  : 거래량 비율 백분위 랭크
  pos_52w       : 52주 위치 (30~70% 이상적, 역U자형 변환 후 랭크)
  foreign_flow  : 외국인 순매수 백분위 랭크
  inst_flow     : 기관 순매수 백분위 랭크
  sector        : 업종 강도 점수 (0~1)

각 팩터를 settings.FACTOR_WEIGHTS 비율로 가중합산 → composite score
"""

import pandas as pd
import settings


def _pct_rank(series: pd.Series) -> pd.Series:
    """0~1 백분위 랭크 (NaN은 최하위)"""
    return series.rank(pct=True, na_option="bottom")


def _sector_scores(sectors: list[dict]) -> dict:
    """업종별 등락률 → 0~1 점수 (min-max 정규화)"""
    if not sectors:
        return {}
    changes = {s["name"]: float(s.get("change_pct", 0)) for s in sectors}
    mn, mx = min(changes.values()), max(changes.values())
    rng = mx - mn or 1.0
    return {k: (v - mn) / rng for k, v in changes.items()}


def compute_scores(universe_data: list[dict], supply: dict) -> list[dict]:
    """
    유니버스 전체 팩터 점수 계산.
    입력: universe_data (brain._fetch_universe_data 결과),
          supply (brain._fetch_supply_demand 결과)
    출력: factor_score 필드 추가, 점수 내림차순 정렬된 리스트
    """
    if not universe_data:
        return []

    df = pd.DataFrame(universe_data)
    weights: dict = dict(settings.FACTOR_WEIGHTS)   # 복사본 (원본 수정 방지)

    # ── US 모드 재정규화 ────────────────────────────────────
    # supply.flow 가 없으면 미국장 → foreign_flow / inst_flow 를 가중치에서 제거 후 재정규화
    # (KR 전용 팩터가 0으로 고정돼 스코어 왜곡 방지)
    flow_map = supply.get("flow", {})
    if not flow_map:
        us_only_exclude = {"foreign_flow", "inst_flow"}
        weights = {k: v for k, v in weights.items() if k not in us_only_exclude}
        total_w = sum(weights.values()) or 1.0
        weights = {k: v / total_w for k, v in weights.items()}
        print(f"[Factor] US 모드 — 수급 팩터 제외 후 재정규화 "
              f"(유효 팩터: {list(weights.keys())})")
    df["foreign_flow"] = df["code"].map(
        lambda c: float(flow_map.get(c, {}).get("foreign_net", 0))
    )
    df["inst_flow"] = df["code"].map(
        lambda c: float(flow_map.get(c, {}).get("inst_net", 0))
    )

    # 섹터 강도
    sec_scores = _sector_scores(supply.get("sectors", []))
    df["sector_score"] = df["sector"].map(lambda s: sec_scores.get(s, 0.5))

    score = pd.Series(0.0, index=df.index)

    # 단순 백분위 랭크 팩터
    simple_factors = {
        "momentum_1m":  "ret_1m",
        "momentum_3m":  "ret_3m",
        "momentum_6m":  "ret_6m",
        "volume_ratio": "vol_ratio",
        "foreign_flow": "foreign_flow",
        "inst_flow":    "inst_flow",
    }
    for key, col in simple_factors.items():
        w = weights.get(key, 0)
        if w and col in df.columns:
            score += _pct_rank(df[col]) * w

    # 52주 위치: 30~70% 이상적 (역U자형)
    w_52 = weights.get("pos_52w", 0)
    if w_52 and "pos_52w" in df.columns:
        optimal = (1.0 - (df["pos_52w"] - 50.0).abs() / 50.0).clip(0, 1)
        score += _pct_rank(optimal) * w_52

    # 섹터 강도 (이미 0~1)
    w_sec = weights.get("sector", 0)
    if w_sec and "sector_score" in df.columns:
        score += df["sector_score"] * w_sec

    df["factor_score"] = score.round(4)
    df = df.sort_values("factor_score", ascending=False).reset_index(drop=True)
    return df.to_dict("records")


def select_pool(universe_data: list[dict], supply: dict, pool_size: int) -> tuple[list[dict], list[dict]]:
    """
    팩터 점수 상위 pool_size 개 선별.
    Returns: (pool candidates list, full scored list)
    """
    scored = compute_scores(universe_data, supply)
    return scored[:pool_size], scored


def score_intraday(market_data: list[dict]) -> list[dict]:
    """
    후보 풀의 당일 모멘텀 점수 계산.
    market_data: runner.py에서 KIS 실시간으로 가져온 데이터
    필드: current, change_pct, volume, high_52w, low_52w
    Returns: intraday_score 필드 추가, 점수 내림차순 정렬
    """
    if not market_data:
        return []

    df = pd.DataFrame(market_data)

    score = pd.Series(0.0, index=df.index)

    # 당일 등락률 (0.50 가중)
    if "change_pct" in df.columns:
        score += _pct_rank(df["change_pct"]) * 0.50

    # 거래량 (0.30 가중)
    if "volume" in df.columns:
        score += _pct_rank(df["volume"]) * 0.30

    # 52주 위치 (0.20 가중, 역U자형)
    if "high_52w" in df.columns and "low_52w" in df.columns and "current" in df.columns:
        rng = (df["high_52w"] - df["low_52w"]).replace(0, 1)
        pos = (df["current"] - df["low_52w"]) / rng * 100
        optimal = (1.0 - (pos - 50.0).abs() / 50.0).clip(0, 1)
        score += _pct_rank(optimal) * 0.20

    df["intraday_score"] = score.round(4)
    df = df.sort_values("intraday_score", ascending=False).reset_index(drop=True)
    return df.to_dict("records")
