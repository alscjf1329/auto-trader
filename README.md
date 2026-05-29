# Auto-Trader

Claude AI 기반 한국·미국 주식 자동매매 시스템.  
퀀트 팩터 스코어링으로 1차 선별 → Claude AI가 2차 보정 → KIS API로 자동 체결.

---

## 목차

1. [아키텍처](#아키텍처)
2. [파일 구조](#파일-구조)
3. [초기 세팅 (필수)](#초기-세팅-필수)
4. [실행 방법](#실행-방법)
5. [설정 파일 상세](#설정-파일-상세)
6. [매매 로직 흐름](#매매-로직-흐름)
7. [리스크 관리](#리스크-관리)
8. [안전장치](#안전장치)
9. [텔레그램 알림](#텔레그램-알림)
10. [모니터링 대시보드](#모니터링-대시보드)
11. [팩터 모델](#팩터-모델)
12. [의존성](#의존성)

---

## 아키텍처

```
유니버스 (KR 50종목 / US 22종목)
        │
        ▼  yfinance 6개월 OHLCV + KIS 수급 데이터
  ┌─────────────┐
  │  factor.py  │  퀀트 팩터 스코어링 (IC 검증 8개 팩터)
  └─────┬───────┘
        │ 상위 pool_size×2 종목
        ▼
  ┌─────────────┐
  │  brain.py   │  Claude Opus 4.7 — Stage 1 (AI 보정·섹터 분산)
  └─────┬───────┘
        │ 후보 풀 (KR 15종목 / US 8종목) → pool_cache.json 하루 1회 캐시
        ▼  KIS 실시간 시세
  ┌─────────────┐
  │  brain.py   │  Claude Sonnet 4.6 — Stage 2 (당일 모멘텀 + 이상 징후 필터)
  └─────┬───────┘
        │ 최종 매수 대상 (최대 3종목)
        ▼
  ┌─────────────┐     ┌──────────────────┐
  │  runner.py  │────►│  KIS API 체결    │
  │  (스케줄러) │     └──────────────────┘
  └─────┬───────┘
        │ 매도 판단 (30분마다)
        ▼
  ① 트레일링 스탑 (risk.py)  — 최고가 대비 5% 이탈 시 즉시 매도
  ② 익절 규칙                — +7% 즉시 매도
  ③ Claude Haiku — Stage 3  — 정성 판단 (애매 구간)
```

---

## 파일 구조

```
auto-trader/
├── runner.py                   # 스케줄러 + 매매 실행 루프 (진입점)
├── brain.py                    # Claude AI 3단계 매매 엔진
├── factor.py                   # 퀀트 팩터 스코어링 (IC 검증)
├── risk.py                     # 포지션 사이징, 트레일링 스탑, 상관계수 필터
├── settings.py                 # settings.yaml 로더 (상수 제공)
├── settings.yaml               # 전체 설정 파일
├── notify.py                   # 텔레그램 알림 모듈
├── kis_api.py                  # KIS (한국투자증권) API 래퍼
│
├── journal/
│   ├── logger.py               # 매매 이력 기록 (CSV + JSON)
│   └── snapshot.py             # 일별 포트폴리오 자산 스냅샷
│
├── dashboard/
│   ├── app.py                  # Streamlit 모니터링 대시보드 (4페이지)
│   └── data.py                 # 대시보드용 데이터 로더
│
├── strategies/                 # Strategy 모드 전략 모음
│   ├── regime_adaptive.py
│   ├── momentum.py
│   └── ...
│
├── backtest/
│   └── factor_backtest.py      # 팩터 IC/ICIR/성과 백테스트
│
├── logs/                       # 런타임 생성 (git 제외)
│   ├── trades.csv                  # 전체 거래 이력
│   ├── trades/YYYY-MM-DD.json      # 날짜별 거래 JSON
│   ├── pool_cache.json             # 한국 후보 풀 캐시
│   ├── pool_cache_us.json          # 미국 후보 풀 캐시
│   ├── regime_cache.json           # 시장 국면 이력
│   ├── portfolio_snapshots.json    # 일별 자산 스냅샷
│   ├── trailing_stops.json         # 트레일링 스탑 추적 데이터
│   ├── research_cache.json         # 글로벌 IB 리서치 캐시
│   └── runner.log                  # 실행 로그
│
├── .env                        # API 키 (git 제외)
├── .env.example                # 환경변수 예시
└── requirements.txt
```

---

## 초기 세팅 (필수)

### 1단계 — 저장소 클론 & 의존성 설치

```bash
git clone <repo-url>
cd auto-trader
pip install -r requirements.txt
```

### 2단계 — .env 파일 생성

```bash
cp .env.example .env
```

`.env` 를 열어 값을 채웁니다:

```dotenv
# ── KIS (한국투자증권) API ─────────────────────────────────
# 발급: https://apiportal.koreainvestment.com → 앱 등록
KIS_APP_KEY=여기에_앱키_입력
KIS_APP_SECRET=여기에_앱시크릿_입력
KIS_ACCT_STOCK=계좌번호8자리
KIS_ACCT_OVRS=계좌번호8자리   # 해외주식 계좌 (없으면 위와 동일)
KIS_HTS_ID=HTS아이디
KIS_IS_PAPER=true             # 반드시 true로 시작 (모의투자)

# ── Anthropic Claude API ──────────────────────────────────
# 발급: https://console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...

# ── 텔레그램 알림 (선택, 강력 권장) ───────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── 실전 전환 시에만 추가 ─────────────────────────────────
# LIVE_TRADING_CONFIRMED=yes
```

### 3단계 — 텔레그램 봇 설정 (선택)

```
1. 텔레그램에서 @BotFather 검색
2. /newbot 명령 → 봇 이름 입력 → TOKEN 발급
3. 만든 봇에게 아무 메시지 전송 (먼저 해야 chat_id 조회 가능)
4. 아래 URL에서 chat_id 확인 (숫자 부분):
   https://api.telegram.org/bot<TOKEN>/getUpdates
   응답 예: "chat":{"id": 12345678, ...}
5. .env에 입력:
   TELEGRAM_BOT_TOKEN=1234567890:AAF...
   TELEGRAM_CHAT_ID=12345678
```

### 4단계 — settings.yaml 확인

기본값으로 바로 실행 가능합니다. 최소한 아래만 확인하세요:

```yaml
trading:
  mode: brain              # brain(AI) 또는 strategy(규칙 기반)
  max_buy_amount: 100000   # 1회 최대 매수 금액 (원)

brain:
  pool_size: 15            # 한국 후보 풀 크기
  buy_limit: 3             # 동시 최대 매수 종목 수

risk:
  max_positions: 5         # 최대 보유 종목 수
  take_profit_pct: 7.0     # 익절 기준 (%)
  trailing_stop_pct: 5.0   # 트레일링 스탑 (최고가 대비 %)
```

### 5단계 — 모의투자 실행

```bash
# 터미널 1: 매매 봇
python runner.py

# 터미널 2: 대시보드 (선택)
streamlit run dashboard/app.py
# → 브라우저 http://localhost:8501
```

---

## 실행 방법

### 매매 봇

```bash
python runner.py
```

- 평일 장 시간에만 자동 실행 (한국 09:05~15:20, 미국 23:00~04:30 KST)
- 30분마다 매매 판단 반복
- Ctrl+C 로 종료

### 대시보드

```bash
streamlit run dashboard/app.py
```

### 팩터 백테스트

```bash
python backtest/factor_backtest.py
```

---

## 설정 파일 상세

### telegram

| 키 | 기본값 | 설명 |
|----|--------|------|
| `enabled` | `true` | 전체 알림 마스터 스위치 |
| `on_buy` | `true` | 매수 체결 알림 |
| `on_sell` | `true` | 매도 체결 알림 (손익 포함) |
| `on_error` | `true` | 에러 발생 알림 |
| `on_regime` | `true` | 시장 국면 전환 알림 (bull↔bear) |
| `on_pool` | `false` | 후보 풀 선정 알림 (장황해서 기본 OFF) |
| `on_startup` | `true` | 러너 시작 알림 |
| `daily_summary` | `true` | 일일 거래 요약 |
| `daily_summary_time` | `"16:00"` | 요약 전송 시각 (KST) |

### trading

| 키 | 기본값 | 설명 |
|----|--------|------|
| `mode` | `brain` | `brain` = AI 자동매매, `strategy` = 규칙 기반 |
| `market_open` | `"09:05"` | 한국장 시작 시각 (KST) |
| `market_close` | `"15:20"` | 한국장 종료 시각 (KST) |
| `market_open_us` | `"23:00"` | 미국장 시작 시각 (KST) |
| `market_close_us` | `"04:30"` | 미국장 종료 시각 (KST) |
| `interval_minutes` | `30` | 한국장 체크 주기 (분) |
| `max_buy_amount` | `100000` | 1회 최대 매수 금액 (원) |
| `max_buy_amount_usd` | `100` | 1회 최대 매수 금액 (USD) |
| `stop_loss_pct` | `-5.0` | 손절 기준 (%) |
| `regime_filter` | `true` | Bear 국면 신규 매수 차단 |

### brain

| 키 | 기본값 | 설명 |
|----|--------|------|
| `pool_size` | `15` | 한국 후보 풀 크기 |
| `pool_size_us` | `8` | 미국 후보 풀 크기 |
| `buy_limit` | `3` | 최대 동시 매수 종목 수 (KR) |
| `buy_limit_us` | `3` | 최대 동시 매수 종목 수 (US) |
| `pool_refresh` | `daily` | 후보 풀 갱신 주기 (`daily` / `weekly`) |
| `model_stage1` | `claude-opus-4-7` | Stage 1 모델 (유니버스→풀) |
| `model_stage2` | `claude-sonnet-4-6` | Stage 2 모델 (풀→매수) |
| `model_stage3` | `claude-haiku-4-5` | Stage 3 모델 (매도 판단) |

### factor_weights

IC(Information Coefficient) 백테스트로 최적화된 가중치입니다.  
합계가 1.0이 되도록 조정하세요.

| 팩터 | 기본 가중치 | IC | ICIR | 설명 |
|------|------------|-----|------|------|
| `momentum_6m` | 0.21 | 0.088 | 0.37 | 6개월 수익률 백분위 |
| `pos_52w` | 0.18 | 0.086 | 0.32 | 52주 위치 (30~70% 선호) |
| `volume_ratio` | 0.15 | 0.044 | 0.25 | 5일/20일 거래량 비율 |
| `foreign_flow` | 0.15 | — | — | 외국인 순매수 (KR 전용) |
| `inst_flow` | 0.10 | — | — | 기관 순매수 (KR 전용) |
| `momentum_3m` | 0.09 | 0.041 | 0.16 | 3개월 수익률 백분위 |
| `momentum_1m` | 0.07 | 0.027 | 0.12 | 1개월 수익률 백분위 |
| `sector` | 0.05 | — | — | 섹터 강도 |

> 미국장에서는 `foreign_flow`, `inst_flow` 가 자동 제외되고 나머지로 재정규화됩니다.

### risk

| 키 | 기본값 | 설명 |
|----|--------|------|
| `risk_per_trade_pct` | `1.0` | 1회 최대 손실: 포트폴리오의 1% |
| `atr_multiplier` | `2.0` | ATR 손절 배수 |
| `max_position_pct` | `20.0` | 단일 종목 최대 비중 (%) |
| `max_total_exposure_pct` | `80.0` | 전체 주식 최대 노출도 (%) |
| `max_positions` | `5` | 최대 동시 보유 종목 수 |
| `take_profit_pct` | `7.0` | 익절 기준 (%) |
| `trailing_stop_pct` | `5.0` | 트레일링 스탑: 최고가 대비 허용 이탈 (%) |
| `trailing_stop_enabled` | `true` | 트레일링 스탑 활성화 |
| `correlation_filter` | `true` | 상관계수 필터 활성화 |
| `correlation_threshold` | `0.70` | 이 이상이면 '동일 방향 종목'으로 제외 |

### safety

| 키 | 기본값 | 설명 |
|----|--------|------|
| `daily_loss_limit_krw` | `500000` | 당일 손실 한도 (원), `0` = 비활성화 |
| `daily_loss_limit_usd` | `300` | 당일 손실 한도 (USD), `0` = 비활성화 |

---

## 매매 로직 흐름

```
[09:05 KST] 장 시작
│
├─ Stage 1: 후보 풀 선정 (하루 1회, 이후 캐시 재사용)
│   ├─ yfinance 6개월 OHLCV 수집 (유니버스 전체 병렬)
│   ├─ KIS API 수급 데이터 수집 (외국인/기관 순매수)
│   ├─ 팩터 스코어링 → 상위 pool_size×2개 선별
│   └─ Claude Opus 4.7 (tool_use) → 최종 pool_size개 확정
│       ※ 섹터 분산, 악재 뉴스, 글로벌 리서치 반영
│
├─ Stage 2: 매수 대상 선정 (30분마다)
│   ├─ KIS 실시간 시세 조회
│   ├─ 당일 모멘텀 스코어링 (등락률 50% + 거래량 30% + 52주위치 20%)
│   ├─ [안전장치] Bear 국면 → 매수 전면 차단
│   ├─ [안전장치] 당일 손실 한도 초과 → 매수 전면 차단
│   ├─ [안전장치] 상관계수 필터 → r≥0.70 종목 제외
│   └─ Claude Sonnet 4.6 (tool_use) → 이상 징후 필터 후 최대 3종목 확정
│
├─ Stage 3: 매도 판단 (30분마다, 보유 종목 전체)
│   ├─ [우선] 트레일링 스탑: 최고가 대비 5% 이탈 → 즉시 매도
│   ├─ [우선] 익절 +7% → 즉시 매도
│   └─ Claude Haiku 4.5 (tool_use) → 정성 판단 (애매 구간)
│
└─ ATR 기반 포지션 사이징
    qty = min(
        portfolio × 1% / (ATR14 × 2),    # 리스크 기반
        portfolio × 20% / price,           # 비중 한도
        max_buy_amount / price             # 금액 한도
    )

[16:00 KST] 장 마감 후
├─ 포트폴리오 자산 스냅샷 저장 (logs/portfolio_snapshots.json)
└─ 텔레그램 일일 요약 전송
```

---

## 리스크 관리

### ATR 기반 포지션 사이징

```
손실 한도 = 포트폴리오 × 1%
손절 폭   = ATR14 × 2.0
매수 수량 = min(손실한도 / 손절폭, 비중한도, 금액한도)
```

ATR 계산 우선순위:
1. yfinance 14일 실제 ATR (`max(H-L, |H-Cprev|, |L-Cprev|)` 14일 평균)
2. 52주 고저 범위 / 252 (fallback)

### 트레일링 스탑

```
매수 후 주가가 오를수록 손절선도 함께 올라감:

  매수: 100,000원
  → 120,000원 도달 (최고가 갱신)
  → 스탑 = 120,000 × (1 - 5%) = 114,000원
  → 114,000원 이하로 하락 시 즉시 매도 (수익 보전)
```

`logs/trailing_stops.json` 에 영속 저장 → 프로세스 재시작 후에도 유지.

### 상관계수 다양화 필터

보유 종목과 3개월 일간 수익률 상관계수 ≥ 0.70이면 제외.  
동일 섹터 집중 포지션 방지.

### 시장 국면 필터 (SMA200)

```
KODEX200 > SMA200 → Bull → 정상 매매
KODEX200 < SMA200 → Bear → 신규 매수 전면 차단
```

미국장은 QQQ 기준으로 동일하게 판단. 국면 전환 시 텔레그램 알림 발송.

---

## 안전장치

### 실전 매매 이중 잠금

`KIS_IS_PAPER=false` (실전) 로 전환하려면 `.env` 에 다음을 **별도로** 추가해야 합니다:

```dotenv
KIS_IS_PAPER=false
LIVE_TRADING_CONFIRMED=yes
```

`LIVE_TRADING_CONFIRMED=yes` 없이 실행하면 러너가 즉시 종료됩니다.

### 당일 손실 한도

당일 실현 손실이 `daily_loss_limit_krw(50만원)` 초과 시  
신규 매수를 전면 중단합니다 (보유 종목 매도는 계속).

### 모의투자 → 실전 전환 체크리스트

```
□ 최소 2주 이상 모의투자 정상 동작 확인
□ logs/trades.csv 이상 거래 없음 확인
□ 텔레그램 알림 정상 수신 확인
□ max_buy_amount 실전에 맞게 조정
□ .env 에 LIVE_TRADING_CONFIRMED=yes 추가
□ KIS_IS_PAPER=false 로 변경
```

---

## 텔레그램 알림

| 알림 | 트리거 | 기본 |
|------|--------|------|
| 🚀 러너 시작 | `python runner.py` 실행 | ON |
| 🟢 매수 체결 | 매수 실행 직후 | ON |
| 🔴 매도 체결 | 매도 실행 직후 (손익 포함) | ON |
| ⚠️ 에러 발생 | 예외 catch 시 | ON |
| 🔆🌑 국면 전환 | Bull↔Bear 전환 감지 시 | ON |
| 📋 일일 요약 | 매일 16:00 KST | ON |
| 📊 후보 풀 선정 | 풀 갱신 완료 시 | OFF |

---

## 모니터링 대시보드

```bash
streamlit run dashboard/app.py
# http://localhost:8501
```

| 페이지 | 주요 내용 |
|--------|----------|
| 📊 메인 | 누적손익·승률·오늘거래·국면 메트릭, 팩터 상위 종목, IB 리서치 |
| 📈 분석 | 실제 자산 커브(스냅샷), 실현손익 커브, 트레일링 스탑 현황, 팩터 레이더, 섹터 분포, 시장 국면 이력 |
| 📋 거래 이력 | 기간·종류·모드·종목 필터, 종목별 손익 바 차트, P&L 히스토그램 |
| 📜 로그 & 캐시 | 컬러 러너 로그, pool_cache 뷰어, 리서치 캐시 |

---

## 팩터 모델

### 백테스트 결과 (3년, KOSPI 유니버스)

| 팩터 | IC | ICIR | 설명 |
|------|-----|------|------|
| momentum_6m | **0.088** | **0.37** | 6개월 수익률 백분위 |
| pos_52w | 0.086 | 0.32 | 52주 위치 (중간값 선호) |
| volume_ratio | 0.044 | 0.25 | 5일/20일 거래량 비율 |
| momentum_3m | 0.041 | 0.16 | 3개월 수익률 백분위 |
| momentum_1m | 0.027 | 0.12 | 1개월 수익률 백분위 |
| volatility | -0.060 | — | ❌ 음의 IC → 제외됨 |

**IC 최적화 포트폴리오 성과 (거래비용 포함):**

| | 3년 누적 | 연환산 |
|--|---------|--------|
| IC 최적 포트폴리오 | +298% | ~100% |
| KOSPI 기준 | +259% | ~87% |
| 거래비용 drag | -43% | — |

---

## 의존성

```
requests              HTTP (텔레그램 Bot API)
schedule              스케줄러
python-dotenv         .env 로더
yfinance              주가 데이터 (팩터 계산)
pandas                데이터 처리
numpy                 ATR 계산
scipy                 백테스트 통계
anthropic             Claude API
pyyaml                settings.yaml 파서
streamlit             모니터링 대시보드
streamlit-autorefresh 대시보드 자동 새로고침
plotly                차트
```

```bash
pip install -r requirements.txt
```

---

## 주요 로그 파일

| 파일 | 내용 |
|------|------|
| `logs/runner.log` | runner.py + brain.py + factor.py 전체 stdout |
| `logs/trades.csv` | 전체 거래 이력 (엑셀 호환) |
| `logs/trades/YYYY-MM-DD.json` | 날짜별 거래 JSON |
| `logs/pool_cache.json` | 당일 한국 후보 풀 + 팩터 점수 |
| `logs/pool_cache_us.json` | 당일 미국 후보 풀 + 팩터 점수 |
| `logs/regime_cache.json` | 시장 국면 이력 (최근 90일) |
| `logs/portfolio_snapshots.json` | 일별 자산 스냅샷 (최근 365일) |
| `logs/trailing_stops.json` | 트레일링 스탑 추적 중인 종목 |
| `logs/research_cache.json` | 글로벌 IB 리서치 요약 캐시 |

---

## FAQ

**Q. 모의투자와 실전투자 차이?**  
`KIS_IS_PAPER=true` 이면 KIS 모의투자 서버로 주문이 전달되어 실제 돈이 빠져나가지 않습니다.

**Q. 후보 풀이 매일 바뀌나요?**  
`pool_refresh: daily` 이면 매일 장 시작 시 새로 선정, `weekly` 이면 월요일에만 갱신됩니다.

**Q. Claude API 비용은?**  
Stage 1(Opus 4.7) → Stage 2(Sonnet 4.6) → Stage 3(Haiku 4.5) 단계별 비용 최적화.  
일반적으로 하루 $0.5 ~ $2 수준.

**Q. 미국장은 언제 실행되나요?**  
`market_open_us: "23:00"` ~ `market_close_us: "04:30"` KST (나스닥 기준).

**Q. 텔레그램 없이도 되나요?**  
`.env` 에서 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 를 비워두면 알림 없이 정상 실행됩니다.

**Q. 미국장 팩터 가중치가 다른가요?**  
미국장에서는 `foreign_flow`, `inst_flow` (KIS 전용 수급 데이터)가 자동으로 제외되고  
나머지 팩터의 가중치가 합계 1.0이 되도록 자동 재정규화됩니다.
