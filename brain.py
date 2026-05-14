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
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import pandas as pd
import yfinance as yf

import settings
import kis_api

client = anthropic.Anthropic()

_POOL_CACHE    = Path(__file__).parent / "logs" / "pool_cache.json"
_POOL_CACHE_US = Path(__file__).parent / "logs" / "pool_cache_us.json"


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


def _save_pool_cache(pool: list):
    _POOL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timedelta
    today_dt = datetime.today()
    monday   = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
    payload  = {
        "date": date.today().isoformat(),
        "week": monday,
        "pool": pool,
    }
    _POOL_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════
# Stage 1 — 유니버스 → 후보 풀
# ══════════════════════════════════════════════════════════════

def _fetch_universe_data() -> list[dict]:
    """yfinance 배치로 유니버스 전체 3개월 데이터 수집"""
    universe  = settings.UNIVERSE
    yf_list   = [f"{s['code']}.KS" for s in universe]
    code_map  = {f"{s['code']}.KS": s for s in universe}

    print(f"[Brain] 유니버스 {len(universe)}종목 데이터 수집 중...")
    raw = yf.download(yf_list, period="3mo", auto_adjust=True, progress=False)

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
            ret_3m  = (close.iloc[-1] / close.iloc[0]  - 1) * 100
            h52     = float(high.max())
            l52     = float(low.min())
            pos_52w = (current - l52) / (h52 - l52) * 100 if h52 != l52 else 50
            vol_r   = float(volume.iloc[-5:].mean()) / float(volume.iloc[-20:].mean() or 1)

            results.append({
                "code":    stock["code"],
                "name":    stock["name"],
                "sector":  stock.get("sector", ""),
                "current": round(current),
                "ret_1m":  round(ret_1m, 2),
                "ret_3m":  round(ret_3m, 2),
                "pos_52w": round(pos_52w, 1),
                "vol_ratio": round(vol_r, 2),
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
    """Claude에게 유니버스 데이터 + 수급 데이터를 주고 후보 풀 선정"""
    pool_size = settings.BRAIN_POOL_SIZE

    # ── 가격 모멘텀 데이터 ──────────────────────────────────
    price_info = "\n".join(
        f"- {d['name']}({d['code']}) [{d['sector']}] "
        f"| 1개월 {d['ret_1m']:+.1f}% | 3개월 {d['ret_3m']:+.1f}% "
        f"| 52주위치 {d['pos_52w']:.0f}% | 거래량비율 {d['vol_ratio']:.1f}x"
        for d in universe_data
    )

    # ── 수급 데이터 ─────────────────────────────────────────
    idx   = supply.get("index", {})
    kospi = idx.get("KOSPI", {})
    kosdaq = idx.get("KOSDAQ", {})
    index_info = (
        f"KOSPI {kospi.get('current', 0):,.2f} ({kospi.get('change_pct', 0):+.2f}%) | "
        f"KOSDAQ {kosdaq.get('current', 0):,.2f} ({kosdaq.get('change_pct', 0):+.2f}%)"
    )

    sector_rows = supply.get("sectors", [])
    sector_info = "\n".join(
        f"  {s['name']}: {s['change_pct']:+.2f}%"
        for s in sorted(sector_rows, key=lambda x: x["change_pct"], reverse=True)[:10]
    ) or "  (데이터 없음)"

    flow_map = supply.get("flow", {})
    flow_lines = []
    for d in universe_data:
        f = flow_map.get(d["code"], {})
        fn, inst = f.get("foreign_net", 0), f.get("inst_net", 0)
        if fn != 0 or inst != 0:
            flow_lines.append(
                f"  {d['name']}({d['code']}): 외국인 {fn:+,}주 | 기관 {inst:+,}주"
            )
    flow_info = "\n".join(flow_lines) or "  (데이터 없음)"

    prompt = f"""당신은 한국 주식 퀀트 펀드매니저입니다.
아래 데이터를 종합해 오늘 집중 모니터링할 후보 풀 {pool_size}개를 선정하세요.

=== 오늘 시장 지수 ===
{index_info}

=== 업종별 등락 (상위 10) ===
{sector_info}

=== 종목별 외국인·기관 순매수 ===
{flow_info}

=== 유니버스 가격 모멘텀 (최근 3개월) ===
{price_info}

=== 선정 기준 (우선순위 순) ===
1. 수급 우선: 외국인 또는 기관이 오늘 순매수 중인 종목
2. 섹터 모멘텀: 오늘 강세 업종에 속한 종목
3. 가격 모멘텀: 1개월·3개월 수익률 양호
4. 거래량 확인: 거래량비율 1.2x 이상
5. 52주 위치: 20~85% 구간 선호
6. 섹터 분산: 최소 3개 섹터에서 선정

반드시 아래 JSON 형식으로만 답하세요.
{{
  "pool": ["코드1", "코드2", ...],
  "analysis": "시장 상황 및 수급 기반 선정 근거 3~5줄"
}}

정확히 {pool_size}개를 선정하세요."""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = json.loads(msg.content[-1].text.strip())
    pool     = result.get("pool", [])
    analysis = result.get("analysis", "")

    print(f"\n[Brain] ── 1단계: 후보 풀 선정 ──────────────────")
    print(f"  선정 종목: {pool}")
    for line in analysis.split("\n"):
        if line.strip():
            print(f"  {line.strip()}")
    print()
    return pool


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

    supply = _fetch_supply_demand()
    pool   = _select_candidate_pool(universe_data, supply)
    _save_pool_cache(pool)
    return pool


# ══════════════════════════════════════════════════════════════
# Stage 2 — 후보 풀 → 매수 대상
# ══════════════════════════════════════════════════════════════

def get_targets(market_data: list[dict]) -> list[str]:
    """
    후보 풀의 실시간 데이터를 보고 오늘 매수할 종목 선정.
    runner.py에서 호출.
    """
    buy_limit = settings.BRAIN_BUY_LIMIT

    info = "\n".join(
        f"- {d['name']}({d['code']}): {d['current']:,}원 "
        f"| 등락 {d['change_pct']:+.2f}% | 거래량 {d['volume']:,} "
        f"| 52주고 {d['high_52w']:,} / 52주저 {d['low_52w']:,}"
        for d in market_data
    )

    prompt = f"""당신은 단기 트레이딩 전문 퀀트입니다.
오늘 후보 풀에서 실제 매수할 종목을 최종 선정하세요.

=== 후보 풀 실시간 데이터 ===
{info}

=== 매수 기준 ===
- 오늘 상승 모멘텀이 살아있는 종목
- 거래량이 뒷받침되는 종목
- 52주 고점 대비 합리적인 가격대
- 리스크 대비 기대수익이 명확한 종목

반드시 아래 JSON 형식으로만 답하세요.
{{
  "selected": ["코드1", "코드2"],
  "reason": "선정 이유 한 문장"
}}

최대 {buy_limit}개. 조건 미충족 시 빈 배열."""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = json.loads(msg.content[-1].text.strip())
    selected = result.get("selected", [])
    reason   = result.get("reason", "")

    print(f"[Brain] ── 2단계: 매수 종목 선정 ──────────────────")
    print(f"  선정: {[settings.UNIVERSE_MAP.get(c, c) for c in selected]}")
    print(f"  이유: {reason}\n")
    return selected


# ══════════════════════════════════════════════════════════════
# Stage 3 — 개별 최종 확인
# ══════════════════════════════════════════════════════════════

def should_buy(data: dict) -> bool:
    """선정된 종목 매수 최종 확인"""
    prompt = f"""종목: {data.get('name', data['code'])}({data['code']})
현재가: {data['current']:,}원 | 전일대비: {data['change_pct']:+.2f}%
시가: {data['open']:,}원 | 거래량: {data['volume']:,}
52주 최고: {data['high_52w']:,}원 / 최저: {data['low_52w']:,}원

지금 시장가 매수를 실행해도 괜찮습니까?
{{"buy": true, "reason": "이유"}}"""

    msg    = client.messages.create(
        model="claude-opus-4-7", max_tokens=256,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result = json.loads(msg.content[-1].text.strip())
    buy    = result.get("buy", False)
    print(f"  [3단계] {data['code']} 최종확인: "
          f"{'✅ 매수' if buy else '❌ 패스'} — {result.get('reason', '')}")
    return buy


def should_sell(data: dict, holding: dict) -> bool:
    """보유 종목 매도 판단"""
    avg_price  = float(holding.get("pchs_avg_pric", 0))
    qty        = int(holding.get("hldg_qty", 0))
    profit_pct = float(holding.get("evlu_pfls_rt", 0))

    prompt = f"""보유 종목: {data.get('name', data['code'])}({data['code']})
보유 {qty}주 | 평균매수가 {avg_price:,.0f}원 | 현재가 {data['current']:,}원
평가손익: {profit_pct:+.2f}% | 전일대비: {data['change_pct']:+.2f}%

원칙: +7% 이상 익절 / -5% 이하 손절 / 그 외 추세 종합 판단
{{"sell": false, "reason": "이유"}}"""

    msg    = client.messages.create(
        model="claude-opus-4-7", max_tokens=256,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result = json.loads(msg.content[-1].text.strip())
    sell   = result.get("sell", False)
    print(f"  [매도판단] {data['code']}: "
          f"{'✅ 매도' if sell else '🔒 유지'} — {result.get('reason', '')}")
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


def _save_pool_cache_us(pool: list):
    _POOL_CACHE_US.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timedelta
    today_dt = datetime.today()
    monday   = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
    payload  = {"date": date.today().isoformat(), "week": monday, "pool": pool}
    _POOL_CACHE_US.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_universe_data_us() -> list[dict]:
    """yfinance로 미국 유니버스 3개월 데이터 수집"""
    universe = settings.UNIVERSE_US
    tickers  = [s["ticker"] for s in universe]
    ticker_map = {s["ticker"]: s for s in universe}

    print(f"[Brain-US] 미국 유니버스 {len(universe)}종목 데이터 수집 중...")
    raw = yf.download(tickers, period="3mo", auto_adjust=True, progress=False)

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
            ret_3m  = (close.iloc[-1] / close.iloc[0]  - 1) * 100
            h52     = float(high.max())
            l52     = float(low.min())
            pos_52w = (current - l52) / (h52 - l52) * 100 if h52 != l52 else 50
            vol_r   = float(volume.iloc[-5:].mean()) / float(volume.iloc[-20:].mean() or 1)

            results.append({
                "ticker":    ticker,
                "code":      ticker,
                "name":      stock["name"],
                "sector":    stock.get("sector", ""),
                "exchange":  stock.get("exchange", "NAS"),
                "current":   round(current, 2),
                "ret_1m":    round(ret_1m, 2),
                "ret_3m":    round(ret_3m, 2),
                "pos_52w":   round(pos_52w, 1),
                "vol_ratio": round(vol_r, 2),
            })
        except Exception:
            continue

    print(f"[Brain-US] 데이터 수집 완료: {len(results)}/{len(universe)}종목")
    return results


def _select_candidate_pool_us(universe_data: list[dict]) -> list[str]:
    """Claude에게 미국 유니버스 데이터를 주고 후보 풀 선정"""
    pool_size = settings.BRAIN_POOL_SIZE_US

    info = "\n".join(
        f"- {d['name']}({d['ticker']}) [{d['sector']}] "
        f"| 1개월 {d['ret_1m']:+.1f}% | 3개월 {d['ret_3m']:+.1f}% "
        f"| 52주위치 {d['pos_52w']:.0f}% | 거래량비율 {d['vol_ratio']:.1f}x"
        for d in universe_data
    )

    prompt = f"""당신은 미국 주식 퀀트 트레이더입니다.
아래 {len(universe_data)}개 종목에서 오늘 밤 집중 모니터링할 후보 풀 {pool_size}개를 선정하세요.

=== 미국 유니버스 데이터 (최근 3개월) ===
{info}

=== 선정 기준 ===
- AI/반도체/빅테크 테마 모멘텀 우선
- 1개월·3개월 수익률 상위 종목
- 거래량비율 1.2x 이상 긍정 신호
- 52주 위치 20~90% 구간 선호
- ETF는 시장 방향성 판단용으로 1개 이하로 제한
- 섹터 분산: 최소 2개 섹터 이상

반드시 아래 JSON 형식으로만 답하세요.
{{
  "pool": ["TICKER1", "TICKER2", ...],
  "analysis": "미국 시장 상황 및 선정 근거 3~5줄"
}}

정확히 {pool_size}개를 선정하세요."""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = json.loads(msg.content[-1].text.strip())
    pool     = result.get("pool", [])
    analysis = result.get("analysis", "")

    print(f"\n[Brain-US] ── 1단계: 미국 후보 풀 선정 ──────────")
    print(f"  선정 종목: {pool}")
    for line in analysis.split("\n"):
        if line.strip():
            print(f"  {line.strip()}")
    print()
    return pool


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

    pool = _select_candidate_pool_us(universe_data)
    _save_pool_cache_us(pool)
    return pool


def get_targets_us(market_data: list[dict]) -> list[str]:
    """미국 후보 풀 실시간 데이터 → 최종 매수 종목 선정"""
    buy_limit = settings.BRAIN_BUY_LIMIT_US

    info = "\n".join(
        f"- {d['name']}({d['ticker']}): ${d['current']:.2f} "
        f"| 등락 {d['change_pct']:+.2f}% | 거래량 {d['volume']:,} "
        f"| 52주고 ${d['high_52w']:.2f} / 52주저 ${d['low_52w']:.2f}"
        for d in market_data
    )

    prompt = f"""당신은 미국 주식 단기 트레이딩 전문 퀀트입니다.
오늘 밤 후보 풀에서 실제 매수할 종목을 최종 선정하세요.

=== 후보 풀 실시간 데이터 (USD) ===
{info}

=== 매수 기준 ===
- 장 시작 후 상승 모멘텀이 살아있는 종목
- 거래량이 평소 대비 높은 종목
- 52주 고점 대비 합리적인 가격대
- AI/반도체 섹터 강세 시 해당 종목 우선

반드시 아래 JSON 형식으로만 답하세요.
{{
  "selected": ["TICKER1", "TICKER2"],
  "reason": "선정 이유 한 문장"
}}

최대 {buy_limit}개. 조건 미충족 시 빈 배열."""

    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result   = json.loads(msg.content[-1].text.strip())
    selected = result.get("selected", [])
    reason   = result.get("reason", "")

    print(f"[Brain-US] ── 2단계: 미국 매수 종목 선정 ──────────")
    print(f"  선정: {[settings.UNIVERSE_US_MAP.get(t, t) for t in selected]}")
    print(f"  이유: {reason}\n")
    return selected


def should_buy_us(data: dict) -> bool:
    """미국주식 매수 최종 확인"""
    prompt = f"""종목: {data.get('name', data['ticker'])}({data['ticker']})
현재가: ${data['current']:.2f} | 전일대비: {data['change_pct']:+.2f}%
시가: ${data['open']:.2f} | 거래량: {data['volume']:,}
52주 최고: ${data['high_52w']:.2f} / 최저: ${data['low_52w']:.2f}

지금 시장가 매수를 실행해도 괜찮습니까?
{{"buy": true, "reason": "이유"}}"""

    msg    = client.messages.create(
        model="claude-opus-4-7", max_tokens=256,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result = json.loads(msg.content[-1].text.strip())
    buy    = result.get("buy", False)
    print(f"  [3단계-US] {data['ticker']} 최종확인: "
          f"{'✅ 매수' if buy else '❌ 패스'} — {result.get('reason', '')}")
    return buy


def should_sell_us(data: dict, holding: dict) -> bool:
    """미국주식 매도 판단"""
    avg_price  = float(holding.get("pchs_avg_pric", 0))
    qty        = int(holding.get("hldg_qty", 0))
    profit_pct = float(holding.get("evlu_pfls_rt", 0))

    prompt = f"""보유 종목: {data.get('name', data['ticker'])}({data['ticker']})
보유 {qty}주 | 평균매수가 ${avg_price:.2f} | 현재가 ${data['current']:.2f}
평가손익: {profit_pct:+.2f}% | 전일대비: {data['change_pct']:+.2f}%

원칙: +10% 이상 익절 / -7% 이하 손절 / 그 외 추세 종합 판단
{{"sell": false, "reason": "이유"}}"""

    msg    = client.messages.create(
        model="claude-opus-4-7", max_tokens=256,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    result = json.loads(msg.content[-1].text.strip())
    sell   = result.get("sell", False)
    print(f"  [매도판단-US] {data['ticker']}: "
          f"{'✅ 매도' if sell else '🔒 유지'} — {result.get('reason', '')}")
    return sell
