# auto-trader

Claude AI 기반 한국/미국 주식 자동매매 시스템.  
KIS(한국투자증권) Open API + Anthropic Claude API로 종목 발굴부터 매수/매도까지 자동화.

---

## 구조

```
auto-trader/
├── settings.yaml          # 전체 설정 (모드, 종목, 파라미터) ← 사용자가 편집하는 파일
├── settings.py            # YAML 로더
├── config.py              # KIS API 키 로더 (.env)
├── runner.py              # 매매 실행 엔진
├── brain.py               # Claude AI 종목 선정 엔진
├── kis_api.py             # KIS Open API 클라이언트 (국내 + 해외)
│
├── strategies/            # Strategy 모드 전략 모음
│   ├── base.py            # 전략 추상 클래스
│   ├── regime_adaptive.py # 변동성 레짐 적응형 (기본값)
│   ├── momentum.py
│   └── dual_momentum.py
│
├── backtest/              # 백테스트 엔진
│   ├── engine.py          # 12개 전략 백테스트
│   └── report.py          # 결과 리포트 (MDD, 수익률)
│
├── journal/               # 매매 일지
│   ├── logger.py          # 거래 기록 (JSON + CSV)
│   └── review.py          # 복기 CLI
│
└── logs/                  # 자동 생성
    ├── trades/            # 일별 거래 JSON
    ├── trades.csv         # 누적 거래 CSV
    ├── pool_cache.json    # 한국장 AI 후보 풀 캐시 (하루 1회)
    └── pool_cache_us.json # 미국장 AI 후보 풀 캐시 (하루 1회)
```

---

## 실행 모드

### Brain 모드 (기본값, 권장)

Claude AI가 유니버스에서 종목을 직접 발굴해 자동 매수/매도.

```
[한국장  09:05 ~ 15:20 KST]

유니버스 50종목 (settings.yaml → universe)
    ↓ Stage 1: Claude + KIS 수급 데이터   ← 하루 1회 캐시
후보 풀 15종목
    ↓ Stage 2: Claude + KIS 실시간 시세   ← 15분마다
매수 대상 최대 3종목
    ↓ Stage 3: Claude 개별 최종 확인
매수 / 매도 실행

[미국장  23:00 ~ 04:30 KST]

유니버스 22종목 (settings.yaml → universe_us)
    ↓ 동일 흐름
매수 / 매도 실행 (USD)
```

**Stage 1** — AI가 3개월 가격 모멘텀 + KIS 외국인·기관 순매수 + 업종별 수급을 종합해 후보 풀 선정  
**Stage 2** — 후보 풀의 실시간 데이터로 오늘 살 종목 최종 선정  
**Stage 3** — 종목별 개별 확인 후 주문 집행

### Strategy 모드

고정 종목에 기술적 전략 적용. `settings.yaml → strategy.name` 변경으로 전략 교체.

| 전략 | 설명 |
|---|---|
| `regime_adaptive` | 변동성 레짐 감지 → 저변동성: 볼린저 밴드 / 고변동성: MA 크로스 |
| `momentum` | 단기 가격 모멘텀 |
| `dual_momentum` | 절대·상대 모멘텀 혼합 |

---

## 설치

```bash
pip install -r requirements.txt
```

`.env` 파일 생성:

```env
KIS_APP_KEY=발급받은_앱키
KIS_APP_SECRET=발급받은_시크릿
KIS_ACCT_STOCK=국내주식_계좌번호   # 8자리
KIS_ACCT_OVRS=해외주식_계좌번호    # 없으면 국내와 동일하게 입력
KIS_HTS_ID=HTS_아이디
KIS_IS_PAPER=true                  # 모의투자: true / 실전: false

ANTHROPIC_API_KEY=Claude_API_키
```

> KIS API 키 발급: https://apiportal.koreainvestment.com  
> Claude API 키 발급: https://console.anthropic.com

---

## 실행

### batchron으로 실행 (권장)

스케줄링은 [batchron](../batchron)이 전담. auto-trader는 로직만 제공.

```bash
cd ../batchron
./run.sh
```

| 잡 | 주기 | 역할 |
|---|---|---|
| `trade_kr` | 15분 (장중) | 한국장 AI 매수/매도 판단 |
| `trade_us_*` | 15분 (장중) | 미국장 AI 매수/매도 판단 |
| `stop_loss_kr` | 3분 (장중) | 한국장 손절 감시 — Claude 없이 즉시 컷 |
| `stop_loss_us_*` | 3분 (장중) | 미국장 손절 감시 |

### 단독 실행

```bash
python runner.py
```

### 즉시 테스트

`runner.py` 하단 주석 해제 후 실행:

```python
# run()       # 한국장 즉시 1회 실행
# run_us()    # 미국장 즉시 1회 실행
```

---

## 설정 (`settings.yaml`)

모든 설정은 `settings.yaml` 한 파일에서 관리. Python 코드 수정 불필요.

### 매매 기본

```yaml
trading:
  mode: brain                  # brain / strategy
  market_open:  "09:05"        # 한국장 시작 (KST)
  market_close: "15:20"        # 한국장 종료 (KST)
  market_open_us:  "23:00"     # 미국장 시작 (KST)
  market_close_us: "04:30"     # 미국장 종료 (KST)
  max_buy_amount: 100000       # 1회 최대 매수 금액 (원)
  max_buy_amount_usd: 100      # 1회 최대 매수 금액 (달러)
  stop_loss_pct: -5.0          # 한국장 손절 기준 (%)
  stop_loss_pct_us: -7.0       # 미국장 손절 기준 (%)
```

### Brain 설정

```yaml
brain:
  pool_size: 15                # 한국 유니버스 → 후보 풀 크기
  pool_size_us: 8              # 미국 유니버스 → 후보 풀 크기
  buy_limit: 3                 # 한국장 최대 매수 종목 수
  buy_limit_us: 3              # 미국장 최대 매수 종목 수
  pool_refresh: daily          # 후보 풀 갱신 주기: daily / weekly
```

### 유니버스 편집

```yaml
universe:                      # 한국장 유니버스 (현재 50종목)
  - { code: "005930", name: "삼성전자", sector: "반도체" }
  - { code: "000660", name: "SK하이닉스", sector: "반도체" }
  ...

universe_us:                   # 미국장 유니버스 (현재 22종목)
  - { ticker: "NVDA", name: "엔비디아", exchange: "NAS", sector: "AI반도체" }
  - { ticker: "AAPL", name: "애플",     exchange: "NAS", sector: "빅테크" }
  ...
```

> exchange: `NAS`(나스닥) / `NYS`(뉴욕증권거래소) / `AMS`(아멕스)

---

## 손절

손절은 Claude를 거치지 않고 기계적으로 즉시 실행.

| 구분 | 기준 | 감시 주기 |
|---|---|---|
| 한국장 | `stop_loss_pct: -5.0%` | 3분 |
| 미국장 | `stop_loss_pct_us: -7.0%` | 3분 |

---

## 백테스트

```bash
# Windows
bin\windows\trade.bat backtest

# Linux / Mac
bin/linux/trade.sh backtest
```

지원 전략 (12개):

```
momentum / dual_momentum / rsi / golden_cross / bollinger
macd / turtle / volatility_breakout / zscore_mean_reversion
ensemble / trend_filter_macd / regime_adaptive
```

---

## 매매 복기

```bash
# 전체 요약
python -m journal.review

# 월별
python -m journal.review --month 2026-05

# 일별
python -m journal.review --date 2026-05-14
```

거래 기록:
- `logs/trades/YYYY-MM-DD.json` — 일별 상세 기록
- `logs/trades.csv` — 전체 누적 (Excel 등으로 열기 가능)

---

## 의존성

| 패키지 | 용도 |
|---|---|
| `anthropic` | Claude AI API |
| `yfinance` | 과거 주가 데이터 (Stage 1) |
| `pandas` | 데이터 처리 |
| `requests` | KIS API 호출 |
| `python-dotenv` | 환경변수 관리 |
| `pyyaml` | 설정 파일 파싱 |
| `schedule` | 단독 실행 시 스케줄러 |
