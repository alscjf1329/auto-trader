"""
brain.py - Claude AI 2단계 자동매매 엔진

[한국장 세션 - 09:05 KST]
Stage 1: 유니버스 KR(50종목) → Claude → 후보 풀(15종목)  [yfinance + KIS 수급]
Stage 2: 후보 풀(15종목)     → Claude → 매수 대상(2~3종목) [KIS 실시간]
Stage 3: 개별 최종 확인

[미국장 세션 - 23:00 KST]
Stage 1: 유니버스 US(22종목) → Claude → 후보 풀(8종목)   [yfinance 3개월]
Stage 2: 후보 풀(8종목)      → Claude → 매수 대상(3종목)  [KIS 해외 실시간]
Stage 3: 개별 최종 확인

후보 풀은 하루 1회 캐싱 (logs/pool_cache.json / logs/pool_cache_us.json)
"""

import json
from datetime import date, datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import numpy as np
import pandas as pd
import yfinance as yf

import settings
import kis_api

client = anthropic.Anthropic()

_POOL_CACHE      = Path(__file__).parent / "logs" / "pool_cache.json"
_STAGE2_CACHE    = Path(__file__).parent / "logs" / "stage2_cache.json"
_STAGE2_CACHE_US = Path(__file__).parent / "logs" / "stage2_cache_us.json"
_STAGE2_TTL_MIN  = 15  # 동일 풀이어도 N분 후 강제 재평가

# ══════════════════════════════════════════════════════════════
# tool_use 스키마 — JSON 파싱 에러 완전 차단
# 프롬프트에 "JSON으로 답하세요" 대신 tool_choice="any" 로 강제 구조화 출력
# ══════════════════════════════════════════════════════════════

_TOOL_SELECT_POOL = {
    "name": "select_pool",
    "description": "퀀트 팩터 모델 1차 선별 결과를 검토해 최종 후보 풀 종목 코드와 선정 근거를 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pool": {
                "type": "array",
                "items": {"type": "string"},
                "description": "선정된 종목 코드 목록 (한국: 6자리 숫자, 미국: 티커)",
            },
            "analysis": {
                "type": "string",
                "description": "선정 근거 및 팩터 모델 보정 사항 2~3줄",
            },
        },
        "required": ["pool", "analysis"],
    },
}

_TOOL_SELECT_TARGETS = {
    "name": "select_targets",
    "description": "당일 모멘텀 점수 기준 후보 풀에서 실제 매수 종목을 확정합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "items": {"type": "string"},
                "description": "선정된 종목 코드 목록 (이상 징후 없는 종목만)",
            },
            "reason": {
                "type": "string",
                "description": "이상 징후 필터 결과 한 문장 (없으면 '상위 종목 선택')",
            },
        },
        "required": ["selected", "reason"],
    },
}

_TOOL_SELL_DECISION = {
    "name": "sell_decision",
    "description": "보유 종목의 매도 여부와 판단 이유를 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sell": {
                "type": "boolean",
                "description": "true = 매도, false = 유지",
            },
            "reason": {
                "type": "string",
                "description": "판단 이유 한 문장",
            },
        },
        "required": ["sell", "reason"],
    },
}


def _extract_tool_result(msg) -> dict:
    """
    tool_use 블록에서 결과 추출.
    tool_use 블록이 없으면 텍스트에서 JSON 추출 시도 (fallback).
    어떤 경우에도 예외를 raise 하지 않음.
    """
    import re

    # 1순위: tool_use 블록 (항상 여기서 끝나야 정상)
    for block in msg.content:
        if hasattr(block, "type") and block.type == "tool_use":
            return dict(block.input)

    # 2순위: 텍스트 블록에서 JSON 추출 (fallback)
    for block in msg.content:
        if hasattr(block, "text") and block.text:
            text = block.text.strip()
            # ```json ... ``` 또는 ``` ... ``` 제거
            text = re.sub(r"```(?:json)?\s*", "", text)
            text = re.sub(r"```", "", text)
            # 첫 번째 { ... } 추출
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass

    print("[Brain] WARNING: tool_use 블록을 찾을 수 없어 빈 dict 반환")
    return {}


# ══════════════════════════════════════════════════════════════
# Stage2 캐시 — 동일 후보 풀이면 Claude 재호출 스킵
# ══════════════════════════════════════════════════════════════

def _load_stage2_cache(path: Path) -> dict:
    """Stage2 결과 캐시 로드. 없거나 파싱 실패 시 빈 dict."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_stage2_cache(path: Path, top_codes: list, selected: list, reason: str):
    """Stage2 결과 캐시 저장."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date":      date.today().isoformat(),
        "timestamp": datetime.now().isoformat(),
        "top_codes": top_codes,
        "selected":  selected,
        "reason":    reason,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage2_cache_hit(path: Path, top_codes: list) -> tuple[bool, list, str]:
    """
    Stage2 캐시 히트 여부 판단.

    조건 (모두 충족 시 True):
      1. 오늘 날짜 캐시
      2. 상위 후보 코드 순서 동일
      3. 마지막 Claude 호출로부터 TTL(_STAGE2_TTL_MIN) 미경과

    Returns: (hit: bool, selected: list, reason: str)
    """
    cache = _load_stage2_cache(path)
    if not cache:
        return False, [], ""

    if cache.get("date") != date.today().isoformat():
        return False, [], ""

    if cache.get("top_codes") != top_codes:
        return False, [], ""

    try:
        last_ts = datetime.fromisoformat(cache["timestamp"])
        elapsed = (datetime.now() - last_ts).total_seconds() / 60
    except Exception:
        return False, [], ""

    if elapsed >= _STAGE2_TTL_MIN:
        print(
            f"[Brain] Stage2 TTL 만료 — {elapsed:.0f}분 경과 "
            f"(TTL {_STAGE2_TTL_MIN}분) → 재평가"
        )
        return False, [], ""

    return True, cache.get("selected", []), cache.get("reason", "")


_POOL_CACHE_US   = Path(__file__).parent / "logs" / "pool_cache_us.json"
_RESEARCH_CACHE  = Path(__file__).parent / "logs" / "research_cache.json"
_REGIME_CACHE    = Path(__file__).parent / "logs" / "regime_cache.json"


# ══════════════════════════════════════════════════════════════
# 글로벌 리서치 자동 수집 (Citi · GS · MS 등, 하루 1회 캐싱)
# ══════════════════════════════════════════════════════════════

def _fetch_research() -> str:
    """
    Claude가 웹검색으로 최신 글로벌 IB 리서치를 수집해 한국어로 요약.
    하루 1회만 실행하고 logs/research_cache.json에 캐싱.
    실패 시 빈 문자열 반환 (매매 로직에는 영향 없음).
    """
    # ── 캐시 확인 ────────────────────────────────────────────
    if _RESEARCH_CACHE.exists():
        try:
            data = json.loads(_RESEARCH_CACHE.read_text(encoding="utf-8"))
            if data.get("date") == date.today().isoformat():
                content = data.get("content", "")
                if content:
                    print("[Brain] 리서치 캐시 사용")
                    return content
        except Exception:
            pass

    print("[Brain] 글로벌 리서치 수집 중 (Citi / GS / MS 웹검색)...")

    query = (
        f"오늘 날짜 기준({date.today().isoformat()}) Citi, Goldman Sachs, Morgan Stanley의 "
        "최신 주식 투자 리서치를 검색하세요. "
        "다음을 포함해 한국어로 간결하게 요약하세요:\n"
        "1. Citi 추천 섹터 및 테마\n"
        "2. GS / MS 주요 Top Pick 종목\n"
        "3. 공통적으로 언급되는 2026년 핵심 투자 테마\n"
        "불확실한 내용은 생략하고, 확인된 내용만 3~5줄로 요약하세요."
    )

    try:
        messages = [{"role": "user", "content": query}]

        # ── web_search 툴로 Claude가 직접 검색 ───────────────
        while True:
            response = client.messages.create(
                model=settings.BRAIN_MODEL_STAGE1,
                max_tokens=1024,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=messages,
                extra_headers={"anthropic-beta": "web-search-2025-03-05"},
            )

            if response.stop_reason == "end_turn":
                content = ""
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        content += block.text
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = [
                    {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                    for b in response.content
                    if hasattr(b, "type") and b.type == "tool_use"
                ]
                messages.append({"role": "user", "content": tool_results})
            else:
                content = ""
                break

        content = content.strip()
        print(f"[Brain] 리서치 수집 완료:\n  {content[:120]}...")

        # ── 캐시 저장 ─────────────────────────────────────────
        _RESEARCH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _RESEARCH_CACHE.write_text(
            json.dumps({"date": date.today().isoformat(), "content": content},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return content

    except Exception as e:
        print(f"[Brain] 리서치 수집 실패 (무시하고 계속): {e}")
        return ""


# ══════════════════════════════════════════════════════════════
# 캐시
# ══════════════════════════════════════════════════════════════

def _load_pool_cache() -> list:
    if not _POOL_CACHE.exists():
        return []
    try:
        data = json.loads(_POOL_CACHE.read_text(encoding="utf-8"))
        today = date.today().isoformat()
        # weekly 모드: 이번 주 월요일 날짜로 비교
        if settings.BRAIN_REFRESH == "weekly":
            from datetime import datetime, timedelta
            today_dt = datetime.today()
            monday   = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
            if data.get("week") == monday:
                return data.get("pool", [])
        else:
            if data.get("date") == today:
                return data.get("pool", [])
    except Exception:
        pass
    return []


def _save_pool_cache(pool: list, universe_data: list = None):
    _POOL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timedelta
    today_dt = datetime.today()
    monday   = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
    payload  = {
        "date": date.today().isoformat(),
        "week": monday,
        "pool": pool,
        "universe_data": universe_data or [],
    }
    _POOL_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_universe_cache() -> dict:
    """pool_cache에서 종목별 ATR/52w 데이터 로드 (코드 → dict)"""
    if not _POOL_CACHE.exists():
        return {}
    try:
        data = json.loads(_POOL_CACHE.read_text(encoding="utf-8"))
        if data.get("date") == date.today().isoformat():
            return {d["code"]: d for d in data.get("universe_data", [])}
    except Exception:
        pass
    return {}


# ══════════════════════════════════════════════════════════════
# 시장 국면 감지 (SMA200 기반)
# ══════════════════════════════════════════════════════════════

def get_market_regime() -> dict:
    """
    KODEX 200 종가 기준 SMA200 비교 → bull/bear 국면 판단.
    bear 국면에서는 신규 매수 차단 (runner.py에서 사용).
    """
    try:
        raw   = yf.download("069500.KS", period="1y", auto_adjust=True, progress=False)
        close = raw["Close"].squeeze().dropna()
        sma200 = close.rolling(200).mean()
        current = float(close.iloc[-1])
        sma     = float(sma200.iloc[-1])
        is_bull = current > sma
        gap_pct = (current - sma) / sma * 100
        regime  = "bull" if is_bull else "bear"
        result = {"regime": regime, "is_bull": is_bull,
                  "kospi": round(current, 2), "sma200": round(sma, 2),
                  "gap_pct": round(gap_pct, 2),
                  "updated_at": date.today().isoformat()}
        print(f"[Brain] 시장 국면: {regime} | KODEX200 {current:,.2f} vs SMA200 {sma:,.2f} ({gap_pct:+.1f}%)")
        _REGIME_CACHE.parent.mkdir(parents=True, exist_ok=True)
        # 이력 누적 (최근 90일)
        history = []
        if _REGIME_CACHE.exists():
            try:
                history = json.loads(_REGIME_CACHE.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history = [h for h in history if h.get("updated_at", "") > (date.today().isoformat()[:7] + "-01")]
        if not history or history[-1].get("updated_at") != date.today().isoformat():
            history.append(result)
        _REGIME_CACHE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    except Exception as e:
        print(f"[Brain] 국면 판단 실패 (bull 가정): {e}")
        return {"regime": "bull", "is_bull": True, "kospi": 0, "sma200": 0, "gap_pct": 0}


def get_market_regime_us() -> dict:
    """QQQ SMA200 기준 미국장 국면 판단"""
    try:
        raw   = yf.download("QQQ", period="1y", auto_adjust=True, progress=False)
        close = raw["Close"].squeeze().dropna()
        sma200 = close.rolling(200).mean()
        current = float(close.iloc[-1])
        sma     = float(sma200.iloc[-1])
        is_bull = current > sma
        gap_pct = (current - sma) / sma * 100
        regime  = "bull" if is_bull else "bear"
        print(f"[Brain-US] 시장 국면: {regime} | QQQ {current:.2f} vs SMA200 {sma:.2f} ({gap_pct:+.1f}%)")
        return {"regime": regime, "is_bull": is_bull, "qqq": current, "sma200": sma, "gap_pct": gap_pct}
    except Exception as e:
        print(f"[Brain-US] 국면 판단 실패 (bull 가정): {e}")
        return {"regime": "bull", "is_bull": True, "qqq": 0, "sma200": 0, "gap_pct": 0}


# ══════════════════════════════════════════════════════════════
# Stage 1 — 유니버스 → 후보 풀
# ══════════════════════════════════════════════════════════════

def _fetch_universe_data() -> list[dict]:
    """yfinance 배치로 유니버스 전체 3개월 데이터 수집"""
    universe  = settings.UNIVERSE
    yf_list   = [f"{s['code']}.KS" for s in universe]
    code_map  = {f"{s['code']}.KS": s for s in universe}

    print(f"[Brain] 유니버스 {len(universe)}종목 데이터 수집 중...")
    raw = yf.download(yf_list, period="6mo", auto_adjust=True, progress=False)

    results = []
    for yf_ticker, stock in code_map.items():
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close  = raw["Close"][yf_ticker].dropna()
                volume = raw["Volume"][yf_ticker].dropna()
                high   = raw["High"][yf_ticker].dropna()
                low    = raw["Low"][yf_ticker].dropna()
            else:
                continue

            if len(close) < 20:
                continue

            current = float(close.iloc[-1])
            ret_1m  = (close.iloc[-1] / close.iloc[-20] - 1) * 100
            ret_3m  = (close.iloc[-1] / close.iloc[-63] - 1) * 100 if len(close) >= 63 else ret_1m
            ret_6m  = (close.iloc[-1] / close.iloc[0]   - 1) * 100
            h52     = float(high.max())
            l52     = float(low.min())
            pos_52w = (current - l52) / (h52 - l52) * 100 if h52 != l52 else 50
            vol_r   = float(volume.iloc[-5:].mean()) / float(volume.iloc[-20:].mean() or 1)

            # 14일 실제 ATR (True Range = max(H-L, |H-Cprev|, |L-Cprev|))
            hi = high.values
            lo = low.values
            cl = close.values
            tr = np.maximum(hi[1:] - lo[1:],
                            np.maximum(np.abs(hi[1:] - cl[:-1]),
                                       np.abs(lo[1:] - cl[:-1])))
            atr14 = float(tr[-14:].mean()) if len(tr) >= 14 else current * 0.02

            results.append({
                "code":    stock["code"],
                "name":    stock["name"],
                "sector":  stock.get("sector", ""),
                "current": round(current),
                "ret_1m":  round(ret_1m, 2),
                "ret_3m":  round(ret_3m, 2),
                "ret_6m":  round(ret_6m, 2),
                "pos_52w": round(pos_52w, 1),
                "vol_ratio": round(vol_r, 2),
                "atr":     round(atr14, 2),
                "high_52w": round(h52),
                "low_52w":  round(l52),
            })
        except Exception:
            continue

    print(f"[Brain] 데이터 수집 완료: {len(results)}/{len(universe)}종목")
    return results


def _fetch_supply_demand() -> dict:
    """
    KIS API로 수급 데이터 수집:
      - 코스피/코스닥 지수 현황
      - 업종별 등락
      - 유니버스 종목별 외국인·기관 순매수
    병렬 요청으로 속도 최적화.
    """
    print("[Brain] 수급 데이터 수집 중 (KIS)...")

    # 1) 시장 지수
    index = kis_api.get_market_index()

    # 2) 업종 흐름
    sectors = kis_api.get_sector_flow()

    # 3) 종목별 외국인·기관 순매수 — 병렬 호출
    codes = settings.UNIVERSE_CODES
    flow_map: dict[str, dict] = {}

    def _fetch_one(code):
        return kis_api.get_investor_flow(code)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_one, c): c for c in codes}
        for fut in as_completed(futures):
            r = fut.result()
            flow_map[r["code"]] = r

    print(f"[Brain] 수급 수집 완료 — "
          f"KOSPI {index.get('KOSPI', {}).get('change_pct', 0):+.2f}% / "
          f"KOSDAQ {index.get('KOSDAQ', {}).get('change_pct', 0):+.2f}%")
    return {"index": index, "sectors": sectors, "flow": flow_map}


def _select_candidate_pool(universe_data: list[dict], supply: dict) -> list[str]:
    """
    팩터 점수로 1차 선별 → Claude가 애널리스트 역할로 보정.
    """
    import factor as factor_engine
    pool_size = settings.BRAIN_POOL_SIZE

    # ── 팩터 스코어링 (퀀트 모델) ──────────────────────────
    # 상위 pool_size*2 개를 1차 선별 (Claude 검토 범위 축소)
    candidates, all_scored = factor_engine.select_pool(
        universe_data, supply, pool_size=pool_size * 2
    )

    # ── 팩터 결과 포매팅 ────────────────────────────────────
    factor_info = "\n".join(
        f"- {d['name']}({d['code']}) [{d['sector']}] "
        f"| 팩터점수 {d['factor_score']:.3f} "
        f"| 1M {d['ret_1m']:+.1f}% | 3M {d['ret_3m']:+.1f}% | 6M {d.get('ret_6m', 0):+.1f}% "
        f"| 외국인 {supply.get('flow',{}).get(d['code'],{}).get('foreign_net',0):+,}주 "
        f"| 기관 {supply.get('flow',{}).get(d['code'],{}).get('inst_net',0):+,}주 "
        f"| 섹터강도 {d.get('sector_score', 0):.2f}"
        for d in candidates
    )

    # ── 시장 컨텍스트 ───────────────────────────────────────
    idx    = supply.get("index", {})
    kospi  = idx.get("KOSPI",  {})
    kosdaq = idx.get("KOSDAQ", {})
    index_info = (
        f"KOSPI {kospi.get('current',0):,.2f} ({kospi.get('change_pct',0):+.2f}%) | "
        f"KOSDAQ {kosdaq.get('current',0):,.2f} ({kosdaq.get('change_pct',0):+.2f}%)"
    )

    # ── 리서치 컨텍스트 ────────────────────────────────────
    research_ctx = _fetch_research()
    research_section = f"\n=== 글로벌 IB 리서치 (Citi·GS·MS) ===\n{research_ctx}\n" if research_ctx else ""

    prompt = f"""당신은 퀀트 펀드의 시니어 애널리스트입니다.
퀀트 팩터 모델이 1차 선별한 {len(candidates)}개 후보에서 최종 {pool_size}개를 선정하세요.

=== 오늘 시장 지수 ===
{index_info}
{research_section}
=== 팩터 모델 1차 선별 결과 (점수 내림차순) ===
{factor_info}

=== 당신의 역할 ===
- 팩터 점수는 이미 수치 검증 완료. 기본적으로 상위 종목을 선택.
- 단, 아래 경우 하위 종목으로 대체:
  * 최근 악재 뉴스 (회계부정, 대규모 소송, 경영진 리스크)
  * 글로벌 리서치와 정반대 섹터
  * 급등 후 과열 징후 (팩터는 못 잡는 정성 판단)
- 섹터 분산: 동일 섹터 3개 이상 금지

select_pool 도구를 호출해 선정 결과를 반환하세요.
정확히 {pool_size}개를 선정하세요."""

    msg = client.messages.create(
        model=settings.BRAIN_MODEL_STAGE1,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        tools=[_TOOL_SELECT_POOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = _extract_tool_result(msg)
    pool     = result.get("pool", [])
    analysis = result.get("analysis", "")

    # ── 팩터 점수 상위 종목 출력 ────────────────────────────
    print(f"\n[Brain] ── 1단계: 팩터 스코어링 결과 ──────────────")
    for d in all_scored[:10]:
        print(f"  {d['factor_score']:.3f} | {d['name']}({d['code']}) [{d['sector']}]")
    print(f"\n[Brain] ── AI 보정 후 최종 후보 풀 ─────────────────")
    print(f"  선정: {pool}")
    for line in analysis.split("\n"):
        if line.strip():
            print(f"  {line.strip()}")
    print()
    return pool, all_scored   # all_scored = factor_score 포함한 전체 유니버스


def get_universe_cache() -> dict:
    """runner.py에서 ATR/52w 데이터를 꺼내 쓸 수 있도록 공개"""
    return _load_universe_cache()


def get_candidate_pool() -> list[str]:
    """
    오늘의 후보 풀 반환.
    캐시가 있으면 재사용, 없으면 AI가 유니버스에서 선정.
    """
    cached = _load_pool_cache()
    if cached:
        names = [settings.UNIVERSE_MAP.get(c, c) for c in cached]
        print(f"[Brain] 후보 풀 캐시 사용: {list(zip(cached, names))}")
        return cached

    universe_data = _fetch_universe_data()
    if not universe_data:
        print("[Brain] 유니버스 데이터 수집 실패 — 빈 풀 반환")
        return []

    supply         = _fetch_supply_demand()
    pool, all_scored = _select_candidate_pool(universe_data, supply)
    # all_scored: factor_score / sector_score / foreign_flow / inst_flow 포함한 전체 유니버스
    _save_pool_cache(pool, all_scored)
    return pool


# ══════════════════════════════════════════════════════════════
# Stage 2 — 후보 풀 → 매수 대상
# ══════════════════════════════════════════════════════════════

def get_targets(market_data: list[dict]) -> list[str]:
    """
    당일 모멘텀 팩터로 1차 순위 → Claude가 이상 징후 필터.

    비용 절감: 상위 후보 코드 순서가 직전 호출과 동일하고 TTL 이내면
    Claude 재호출 없이 이전 결과를 반환.
    """
    import factor as factor_engine
    buy_limit = settings.BRAIN_BUY_LIMIT

    # ── 당일 모멘텀 스코어링 ────────────────────────────────
    scored = factor_engine.score_intraday(market_data)

    # 캐시 비교 기준: 상위 buy_limit*2 코드 순서
    top_codes = [d["code"] for d in scored[: buy_limit * 2]]

    # ── Stage2 캐시 히트 체크 ───────────────────────────────
    hit, cached_selected, cached_reason = _stage2_cache_hit(_STAGE2_CACHE, top_codes)
    if hit:
        elapsed = (datetime.now() - datetime.fromisoformat(
            _load_stage2_cache(_STAGE2_CACHE)["timestamp"]
        )).total_seconds() / 60
        print(
            f"[Brain] Stage2 캐시 재사용 — 상위 풀 동일 "
            f"({elapsed:.0f}분 경과 / TTL {_STAGE2_TTL_MIN}분)\n"
            f"  → {cached_reason}\n"
        )
        return cached_selected

    # ── Claude Stage2 호출 ──────────────────────────────────
    info = "\n".join(
        f"- {d['name']}({d['code']}): {d['current']:,}원 "
        f"| 등락 {d['change_pct']:+.2f}% | 거래량 {d['volume']:,} "
        f"| 당일점수 {d['intraday_score']:.3f}"
        for d in scored
    )

    prompt = f"""당신은 퀀트 펀드의 트레이딩 담당 애널리스트입니다.
당일 모멘텀 점수 기준으로 정렬된 후보 풀에서 실제 매수 종목을 확정하세요.

=== 후보 풀 당일 데이터 (점수 내림차순) ===
{info}

=== 역할 ===
- 기본적으로 점수 상위 {buy_limit}개를 선택.
- 단, 명백한 이상 징후(갭 하락, 비정상 거래량 급락 등)가 있는 종목은 제외.
- 조건 미충족 종목이 있으면 빈 배열로 반환 (억지로 채우지 마세요).

select_targets 도구를 호출해 결과를 반환하세요.
최대 {buy_limit}개."""

    msg = client.messages.create(
        model=settings.BRAIN_MODEL_STAGE2,
        max_tokens=512,
        output_config={"effort": "medium"},
        tools=[_TOOL_SELECT_TARGETS],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = _extract_tool_result(msg)
    selected = result.get("selected", [])
    reason   = result.get("reason", "")

    # 결과 캐시 저장
    _save_stage2_cache(_STAGE2_CACHE, top_codes, selected, reason)

    print(f"[Brain] ── 2단계: 당일 모멘텀 스코어 + AI 필터 ──────")
    for d in scored:
        mark = "O" if d["code"] in selected else " "
        print(f"  [{mark}] {d['intraday_score']:.3f} | {d['name']}({d['code']}) {d['change_pct']:+.2f}%")
    print(f"  → {reason}\n")
    return selected


# ══════════════════════════════════════════════════════════════
# Stage 3 — 매도 판단
# ══════════════════════════════════════════════════════════════

def should_sell(data: dict, holding: dict) -> bool:
    """
    매도 판단:
    1. 규칙 기반 (즉시): 익절 기준 초과 → 바로 true
    2. Claude (Haiku): 그 외 정성 판단
    """
    profit_pct = float(holding.get("evlu_pfls_rt", 0))
    avg_price  = float(holding.get("pchs_avg_pric", 0))
    qty        = int(holding.get("hldg_qty", 0))

    # ── 규칙 기반: 익절 ────────────────────────────────────
    if profit_pct >= settings.RISK_TAKE_PROFIT_PCT:
        print(f"  [익절] {data['code']} {profit_pct:+.2f}% >= {settings.RISK_TAKE_PROFIT_PCT}% → 즉시 매도")
        return True

    # ── Claude: 정성 판단 (애매한 구간만) ─────────────────
    prompt = f"""보유 종목: {data.get('name', data['code'])}({data['code']})
보유 {qty}주 | 평균매수가 {avg_price:,.0f}원 | 현재가 {data['current']:,}원
평가손익: {profit_pct:+.2f}% | 전일대비: {data['change_pct']:+.2f}%
52주 최고: {data['high_52w']:,}원 / 최저: {data['low_52w']:,}원

익절({settings.RISK_TAKE_PROFIT_PCT}%) 미달, 손절(-{abs(settings.STOP_LOSS_PCT)}%) 미달 구간.
추세가 꺾였거나 보유 가치가 없으면 매도(sell=true), 유지할만하면 매도하지 마세요(sell=false).
sell_decision 도구를 호출해 판단 결과를 반환하세요."""

    msg    = client.messages.create(
        model=settings.BRAIN_MODEL_STAGE3,
        max_tokens=256,
        tools=[_TOOL_SELL_DECISION],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )
    result = _extract_tool_result(msg)
    sell   = result.get("sell", False)
    print(f"  [매도판단] {data['code']}: "
          f"{'매도' if sell else '유지'} — {result.get('reason', '')}")
    return sell


# ══════════════════════════════════════════════════════════════
# 미국장 세션 (US)
# ══════════════════════════════════════════════════════════════

def _load_pool_cache_us() -> list:
    if not _POOL_CACHE_US.exists():
        return []
    try:
        data  = json.loads(_POOL_CACHE_US.read_text(encoding="utf-8"))
        today = date.today().isoformat()
        if settings.BRAIN_REFRESH == "weekly":
            from datetime import datetime, timedelta
            today_dt = datetime.today()
            monday   = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
            if data.get("week") == monday:
                return data.get("pool", [])
        else:
            if data.get("date") == today:
                return data.get("pool", [])
    except Exception:
        pass
    return []


def _save_pool_cache_us(pool: list, universe_data: list = None):
    _POOL_CACHE_US.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timedelta
    today_dt = datetime.today()
    monday   = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
    payload  = {
        "date": date.today().isoformat(),
        "week": monday,
        "pool": pool,
        "universe_data": universe_data or [],
    }
    _POOL_CACHE_US.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_universe_data_us() -> list[dict]:
    """yfinance로 미국 유니버스 3개월 데이터 수집"""
    universe = settings.UNIVERSE_US
    tickers  = [s["ticker"] for s in universe]
    ticker_map = {s["ticker"]: s for s in universe}

    print(f"[Brain-US] 미국 유니버스 {len(universe)}종목 데이터 수집 중...")
    raw = yf.download(tickers, period="6mo", auto_adjust=True, progress=False)

    results = []
    for ticker, stock in ticker_map.items():
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close  = raw["Close"][ticker].dropna()
                volume = raw["Volume"][ticker].dropna()
                high   = raw["High"][ticker].dropna()
                low    = raw["Low"][ticker].dropna()
            else:
                continue

            if len(close) < 20:
                continue

            current = float(close.iloc[-1])
            ret_1m  = (close.iloc[-1] / close.iloc[-20] - 1) * 100
            ret_3m  = (close.iloc[-1] / close.iloc[-63] - 1) * 100 if len(close) >= 63 else ret_1m
            ret_6m  = (close.iloc[-1] / close.iloc[0]   - 1) * 100
            h52     = float(high.max())
            l52     = float(low.min())
            pos_52w = (current - l52) / (h52 - l52) * 100 if h52 != l52 else 50
            vol_r   = float(volume.iloc[-5:].mean()) / float(volume.iloc[-20:].mean() or 1)

            hi = high.values
            lo = low.values
            cl = close.values
            tr = np.maximum(hi[1:] - lo[1:],
                            np.maximum(np.abs(hi[1:] - cl[:-1]),
                                       np.abs(lo[1:] - cl[:-1])))
            atr14 = float(tr[-14:].mean()) if len(tr) >= 14 else current * 0.02

            results.append({
                "ticker":    ticker,
                "code":      ticker,
                "name":      stock["name"],
                "sector":    stock.get("sector", ""),
                "exchange":  stock.get("exchange", "NAS"),
                "current":   round(current, 2),
                "ret_1m":    round(ret_1m, 2),
                "ret_3m":    round(ret_3m, 2),
                "ret_6m":    round(ret_6m, 2),
                "pos_52w":   round(pos_52w, 1),
                "vol_ratio": round(vol_r, 2),
                "atr":       round(atr14, 4),
                "high_52w":  round(h52, 2),
                "low_52w":   round(l52, 2),
            })
        except Exception:
            continue

    print(f"[Brain-US] 데이터 수집 완료: {len(results)}/{len(universe)}종목")
    return results


def _select_candidate_pool_us(universe_data: list[dict]) -> list[str]:
    """
    팩터 점수로 1차 선별 → Claude가 애널리스트 역할로 보정 (미국장 버전).
    US는 수급 데이터 없으므로 supply={} 로 넘기고 momentum/volume/pos_52w만 사용.
    """
    import factor as factor_engine
    pool_size = settings.BRAIN_POOL_SIZE_US

    # ── 팩터 스코어링 (퀀트 모델) ──────────────────────────
    candidates, all_scored = factor_engine.select_pool(
        universe_data, supply={}, pool_size=pool_size * 2
    )

    # ── 팩터 결과 포매팅 ────────────────────────────────────
    factor_info = "\n".join(
        f"- {d['name']}({d['ticker']}) [{d['sector']}] "
        f"| 팩터점수 {d['factor_score']:.3f} "
        f"| 1M {d['ret_1m']:+.1f}% | 3M {d['ret_3m']:+.1f}% | 6M {d.get('ret_6m', 0):+.1f}% "
        f"| 거래량비율 {d['vol_ratio']:.1f}x | 52주위치 {d['pos_52w']:.0f}%"
        for d in candidates
    )

    research_ctx = _fetch_research()
    research_section = f"\n=== 글로벌 IB 리서치 (Citi·GS·MS) ===\n{research_ctx}\n" if research_ctx else ""

    prompt = f"""당신은 퀀트 펀드의 시니어 미국주식 애널리스트입니다.
퀀트 팩터 모델이 1차 선별한 {len(candidates)}개 후보에서 최종 {pool_size}개를 선정하세요.

{research_section}
=== 팩터 모델 1차 선별 결과 (점수 내림차순) ===
{factor_info}

=== 당신의 역할 ===
- 팩터 점수는 이미 수치 검증 완료. 기본적으로 상위 종목을 선택.
- 단, 아래 경우 하위 종목으로 대체:
  * 최근 악재 뉴스 또는 실적 쇼크
  * 글로벌 리서치와 정반대 섹터
  * 급등 후 과열 징후
- ETF는 1개 이하로 제한
- 섹터 분산: 최소 2개 섹터 이상

select_pool 도구를 호출해 선정 결과를 반환하세요.
정확히 {pool_size}개를 선정하세요."""

    msg = client.messages.create(
        model=settings.BRAIN_MODEL_STAGE1,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        tools=[_TOOL_SELECT_POOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = _extract_tool_result(msg)
    pool     = result.get("pool", [])
    analysis = result.get("analysis", "")

    print(f"\n[Brain-US] ── 1단계: 팩터 스코어링 결과 ──────────")
    for d in all_scored[:10]:
        print(f"  {d['factor_score']:.3f} | {d['name']}({d['ticker']}) [{d['sector']}]")
    print(f"\n[Brain-US] ── AI 보정 후 최종 후보 풀 ─────────────")
    print(f"  선정: {pool}")
    for line in analysis.split("\n"):
        if line.strip():
            print(f"  {line.strip()}")
    print()
    return pool, all_scored


def get_candidate_pool_us() -> list[str]:
    """오늘의 미국주식 후보 풀 반환 (캐시 우선)"""
    cached = _load_pool_cache_us()
    if cached:
        names = [settings.UNIVERSE_US_MAP.get(t, t) for t in cached]
        print(f"[Brain-US] 후보 풀 캐시 사용: {list(zip(cached, names))}")
        return cached

    universe_data = _fetch_universe_data_us()
    if not universe_data:
        print("[Brain-US] 유니버스 데이터 수집 실패 — 빈 풀 반환")
        return []

    pool, all_scored = _select_candidate_pool_us(universe_data)
    _save_pool_cache_us(pool, all_scored)
    return pool


def get_targets_us(market_data: list[dict]) -> list[str]:
    """
    당일 모멘텀 팩터로 1차 순위 → Claude가 이상 징후 필터 (미국장 버전).

    비용 절감: 상위 후보 티커 순서가 직전 호출과 동일하고 TTL 이내면
    Claude 재호출 없이 이전 결과를 반환.
    """
    import factor as factor_engine
    buy_limit = settings.BRAIN_BUY_LIMIT_US

    # ── 당일 모멘텀 스코어링 ────────────────────────────────
    scored = factor_engine.score_intraday(market_data)

    # 캐시 비교 기준: 상위 buy_limit*2 티커 순서
    top_codes = [d["ticker"] for d in scored[: buy_limit * 2]]

    # ── Stage2 캐시 히트 체크 ───────────────────────────────
    hit, cached_selected, cached_reason = _stage2_cache_hit(_STAGE2_CACHE_US, top_codes)
    if hit:
        elapsed = (datetime.now() - datetime.fromisoformat(
            _load_stage2_cache(_STAGE2_CACHE_US)["timestamp"]
        )).total_seconds() / 60
        print(
            f"[Brain-US] Stage2 캐시 재사용 — 상위 풀 동일 "
            f"({elapsed:.0f}분 경과 / TTL {_STAGE2_TTL_MIN}분)\n"
            f"  → {cached_reason}\n"
        )
        return cached_selected

    # ── Claude Stage2 호출 ──────────────────────────────────
    info = "\n".join(
        f"- {d['name']}({d['ticker']}): ${d['current']:.2f} "
        f"| 등락 {d['change_pct']:+.2f}% | 거래량 {d['volume']:,} "
        f"| 당일점수 {d['intraday_score']:.3f}"
        for d in scored
    )

    prompt = f"""당신은 퀀트 펀드의 미국주식 트레이딩 담당 애널리스트입니다.
당일 모멘텀 점수 기준으로 정렬된 후보 풀에서 실제 매수 종목을 확정하세요.

=== 후보 풀 당일 데이터 (점수 내림차순) ===
{info}

=== 역할 ===
- 기본적으로 점수 상위 {buy_limit}개를 선택.
- 단, 명백한 이상 징후(갭 하락, 비정상 거래량 급락 등)가 있는 종목은 제외.
- 조건 미충족 종목이 있으면 빈 배열로 반환 (억지로 채우지 마세요).

select_targets 도구를 호출해 결과를 반환하세요.
최대 {buy_limit}개."""

    msg = client.messages.create(
        model=settings.BRAIN_MODEL_STAGE2,
        max_tokens=512,
        output_config={"effort": "medium"},
        tools=[_TOOL_SELECT_TARGETS],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = _extract_tool_result(msg)
    selected = result.get("selected", [])
    reason   = result.get("reason", "")

    # 결과 캐시 저장
    _save_stage2_cache(_STAGE2_CACHE_US, top_codes, selected, reason)

    print(f"[Brain-US] ── 2단계: 당일 모멘텀 스코어 + AI 필터 ──")
    for d in scored:
        mark = "O" if d["ticker"] in selected else " "
        print(f"  [{mark}] {d['intraday_score']:.3f} | {d['name']}({d['ticker']}) {d['change_pct']:+.2f}%")
    print(f"  → {reason}\n")
    return selected


def should_sell_us(data: dict, holding: dict) -> bool:
    """
    미국주식 매도 판단:
    1. 규칙 기반 (즉시): 익절 기준 초과 → 바로 true
    2. Claude (Haiku): 그 외 정성 판단
    """
    profit_pct = float(holding.get("evlu_pfls_rt", 0))
    avg_price  = float(holding.get("pchs_avg_pric", 0))
    qty        = int(holding.get("hldg_qty", 0))

    # ── 규칙 기반: 익절 ────────────────────────────────────
    if profit_pct >= settings.RISK_TAKE_PROFIT_PCT:
        print(f"  [익절-US] {data['ticker']} {profit_pct:+.2f}% >= {settings.RISK_TAKE_PROFIT_PCT}% → 즉시 매도")
        return True

    # ── Claude: 정성 판단 (애매한 구간만) ─────────────────
    prompt = f"""보유 종목: {data.get('name', data['ticker'])}({data['ticker']})
보유 {qty}주 | 평균매수가 ${avg_price:.2f} | 현재가 ${data['current']:.2f}
평가손익: {profit_pct:+.2f}% | 전일대비: {data['change_pct']:+.2f}%
52주 최고: ${data['high_52w']:.2f} / 최저: ${data['low_52w']:.2f}

익절({settings.RISK_TAKE_PROFIT_PCT}%) 미달, 손절(-{abs(settings.STOP_LOSS_PCT_US)}%) 미달 구간.
추세가 꺾였거나 보유 가치가 없으면 매도(sell=true), 유지할만하면 매도하지 마세요(sell=false).
sell_decision 도구를 호출해 판단 결과를 반환하세요."""

    msg    = client.messages.create(
        model=settings.BRAIN_MODEL_STAGE3,
        max_tokens=256,
        tools=[_TOOL_SELL_DECISION],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )
    result = _extract_tool_result(msg)
    sell   = result.get("sell", False)
    print(f"  [매도판단-US] {data['ticker']}: "
          f"{'매도' if sell else '유지'} — {result.get('reason', '')}")
    return sell
