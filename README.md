# Auto-Trader

Claude AI 기반 한국·미국 주식 자동매매 시스템.  
퀀트 팩터 스코어링 → Claude AI 3단계 보정 → KIS API 자동 체결.

---

## 목차

1. [빠른 시작](#빠른-시작)
2. [아키텍처](#아키텍처)
3. [파일 구조](#파일-구조)
4. [설정 파일 상세](#설정-파일-상세)
5. [매매 로직 흐름](#매매-로직-흐름)
6. [리스크 관리](#리스크-관리)
7. [안전장치](#안전장치)
8. [텔레그램 명령어](#텔레그램-명령어)
9. [텔레그램 알림](#텔레그램-알림)
10. [전략 시스템](#전략-시스템)
11. [Profit Board 연동](#profit-board-연동)
12. [원격 제어 서버](#원격-제어-서버)
13. [DART 공시 봇](#dart-공시-봇)
14. [급등 알림 봇](#급등-알림-봇)
15. [모니터링 대시보드](#모니터링-대시보드)
16. [의존성](#의존성)
17. [FAQ](#faq)

---

## 빠른 시작

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# → .env 열어서 KIS / Anthropic / 텔레그램 키 입력

# 3. 모의투자로 실행 (KIS_IS_PAPER=true 기본)
python runner.py

# 4. (별도 터미널) 텔레그램 봇 명령어 핸들러
python telegram_cmd.py

# 5. (선택) profit-board 연동 원격 제어 서버
python control.py

# 6. (선택) DART 공시 알림 봇
python dart_bot.py

# 7. (선택) 급등 예측 알림 봇
python surge_alert.py

# 8. (선택) 모니터링 대시보드
streamlit run dashboard/app.py   # → http://localhost:8501
```

> **반드시 모의투자(KIS_IS_PAPER=true)로 2주 이상 검증 후 실전 전환하세요.**

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
  │  brain.py   │  Claude Opus — Stage 1 (AI 보정·섹터 분산)
  └─────┬───────┘
        │ 후보 풀 → pool_cache.json 하루 1회 캐시
        ▼  KIS 실시간 시세
  ┌─────────────┐
  │  brain.py   │  Claude Sonnet — Stage 2 (당일 모멘텀 + 이상 징후 필터)
  └─────┬───────┘
        │ 최종 매수 대상 (최대 3종목)
        ▼
  ┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
  │  runner.py  │────►│  KIS API 체결    │────►│  verify.py   │
  │  (스케줄러) │     └──────────────────┘     │  (HMAC 서명) │
  └─────┬───────┘                              └──────────────┘
        │ 매도 판단 (30분마다)
        ▼
  ① 트레일링 스탑 (risk.py)  — 최고가 대비 5% 이탈 시 즉시 매도
  ② 익절 규칙                — +7% 즉시 매도
  ③ Claude Haiku — Stage 3  — 정성 판단 (애매 구간)
```

**실행 모드:**

| 모드 | 설명 |
|------|------|
| `brain` | Claude AI 3단계 엔진 (기본) |
| `strategy` | `strategies/` 폴더의 규칙 기반 전략 실행 |

---

## 파일 구조

```
auto-trader/
├── runner.py                   # 스케줄러 + 매매 실행 루프 (진입점)
├── brain.py                    # Claude AI 3단계 매매 엔진
├── factor.py                   # 퀀트 팩터 스코어링 (IC 검증)
├── risk.py                     # 포지션 사이징, 트레일링 스탑, 상관계수 필터
├── settings.py                 # settings.yaml 로더
├── settings.yaml               # 전체 설정 파일
├── notify.py                   # 텔레그램 알림
├── telegram_cmd.py             # 텔레그램 명령어 봇 (별도 프로세스)
├── control.py                  # profit-board 연동 원격 제어 HTTP 서버 (선택)
├── dart_bot.py                 # DART 공시 파싱 → 텔레그램 알림 + 자동매매 (선택)
├── surge_alert.py              # 급등 예측 알림 봇 — 거래량/BB/52주신고가 (선택)
├── kis_api.py                  # KIS (한국투자증권) API 래퍼
├── verify.py                   # Profit Board HMAC 서명 전송
├── install_strategy.py         # 마켓플레이스 전략 설치 CLI
│
├── strategies/                 # 규칙 기반 전략 모음
│   ├── base.py                 # BaseStrategy ABC (공통 인터페이스)
│   ├── regime_adaptive.py
│   ├── momentum.py
│   └── dual_momentum.py
│
├── journal/
│   ├── logger.py               # 매매 이력 기록 (CSV + JSON)
│   └── snapshot.py             # 일별 포트폴리오 자산 스냅샷
│
├── dashboard/
│   ├── app.py                  # Streamlit 모니터링 대시보드
│   └── data.py                 # 대시보드용 데이터 로더
│
├── backtest/
│   └── factor_backtest.py      # 팩터 IC/ICIR/성과 백테스트
│
├── logs/                       # 런타임 생성 (git 제외)
│   ├── trades.csv
│   ├── trades/YYYY-MM-DD.json
│   ├── pool_cache.json
│   ├── pool_cache_us.json
│   ├── stage2_cache.json
│   ├── stage2_cache_us.json
│   ├── regime_cache.json
│   ├── portfolio_snapshots.json
│   ├── trailing_stops.json
│   ├── research_cache.json
│   ├── bot_state.json          # 텔레그램 봇 런타임 설정 (pause/mode/blacklist)
│   └── runner.log
│
├── .env                        # API 키 (git 제외)
├── .env.example
└── requirements.txt
```

---

## 설정 파일 상세

### .env

```dotenv
# ── KIS (한국투자증권) API ────────────────────────────────
# 발급: https://apiportal.koreainvestment.com → 앱 등록
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCT_STOCK=계좌번호8자리
KIS_ACCT_OVRS=계좌번호8자리
KIS_HTS_ID=
KIS_IS_PAPER=true              # 반드시 true로 시작

# ── Anthropic Claude API ─────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...

# ── 텔레그램 알림 ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── Profit Board 수익 인증 (선택) ─────────────────────────
VERIFY_ENDPOINT=https://your-profit-board.com
VERIFY_SECRET=
VERIFY_USER_ID=

# ── 원격 제어 서버 control.py (선택) ──────────────────────
CONTROL_PORT=5001
CONTROL_SECRET=

# ── DART 공시 봇 dart_bot.py (선택) ───────────────────────
DART_API_KEY=                    # https://opendart.fss.or.kr 무료 발급
DART_BOT_TOKEN=                  # BotFather에서 별도 봇 생성
DART_CHAT_ID=
DART_AUTO_BUY_AMOUNT=100000      # 공시 자동매수 금액 (원)

# ── 급등 알림 봇 surge_alert.py (선택) ────────────────────
SURGE_BOT_TOKEN=                 # BotFather에서 별도 봇 생성
SURGE_CHAT_ID=
# SURGE_VOL_RATIO=3.0            # 거래량 평균 대비 배수 (기본 3.0x)
# SURGE_VOL_AVG_DAYS=20          # 거래량 평균 산정 기간 (기본 20일)
# SURGE_BB_SQUEEZE=0.03          # BB 스퀴즈 판단 밴드폭/가격 비율 (기본 3%)
# SURGE_COOLDOWN_MIN=120         # 재알림 방지 시간(분, 기본 120)

# ── 실전 전환 시에만 추가 ──────────────────────────────────
# LIVE_TRADING_CONFIRMED=yes
```

텔레그램 `CHAT_ID` 확인 방법: 봇에 아무 메시지 전송 후  
`https://api.telegram.org/bot<TOKEN>/getUpdates` → `"chat":{"id": 숫자}` 에서 확인.

### settings.yaml — 주요 섹션

#### trading

| 키 | 기본값 | 설명 |
|----|--------|------|
| `mode` | `brain` | `brain` = AI, `strategy` = 규칙 기반 |
| `market_open` | `"09:05"` | 한국장 시작 (KST) |
| `market_close` | `"15:20"` | 한국장 종료 (KST) |
| `market_open_us` | `"23:00"` | 미국장 시작 (KST) |
| `market_close_us` | `"04:30"` | 미국장 종료 (KST) |
| `interval_minutes` | `30` | 체크 주기 (분) |
| `max_buy_amount` | `100000` | 1회 최대 매수 (원) |
| `max_buy_amount_usd` | `100` | 1회 최대 매수 (USD) |
| `regime_filter` | `true` | Bear 국면 매수 차단 |

#### brain

| 키 | 기본값 | 설명 |
|----|--------|------|
| `pool_size` | `15` | 한국 후보 풀 크기 |
| `pool_size_us` | `8` | 미국 후보 풀 크기 |
| `buy_limit` | `3` | 동시 최대 매수 (KR) |
| `buy_limit_us` | `3` | 동시 최대 매수 (US) |
| `pool_refresh` | `daily` | 후보 풀 갱신 주기 |
| `model_stage1` | `claude-opus-4-7` | Stage 1 모델 |
| `model_stage2` | `claude-sonnet-4-6` | Stage 2 모델 |
| `model_stage3` | `claude-haiku-4-5` | Stage 3 모델 |

#### risk

| 키 | 기본값 | 설명 |
|----|--------|------|
| `risk_per_trade_pct` | `1.0` | 1회 최대 손실: 포트폴리오의 1% |
| `atr_multiplier` | `2.0` | ATR 손절 배수 |
| `max_position_pct` | `20.0` | 단일 종목 최대 비중 (%) |
| `max_positions` | `5` | 최대 동시 보유 종목 수 |
| `take_profit_pct` | `7.0` | 익절 기준 (%) |
| `trailing_stop_pct` | `5.0` | 트레일링 스탑: 최고가 대비 허용 이탈 (%) |
| `correlation_threshold` | `0.70` | 상관계수 이상 종목 제외 |

#### blacklist

매수를 제외할 종목 목록. `settings.yaml` 정적 목록 + 텔레그램 `/blacklist add` 런타임 추가분이 합산 적용됩니다.

```yaml
blacklist:
  kr:
    - "035720"   # 카카오 — 변동성 과다
  us:
    - "TSLA"     # 테슬라 — 이벤트 리스크
```

#### factor_weights

IC 백테스트로 최적화된 가중치입니다. 합계 = 1.0.

| 팩터 | 가중치 | IC | ICIR | 설명 |
|------|--------|-----|------|------|
| `momentum_6m` | 0.21 | 0.088 | 0.37 | 6개월 수익률 백분위 |
| `pos_52w` | 0.18 | 0.086 | 0.32 | 52주 위치 (30~70% 선호) |
| `volume_ratio` | 0.15 | 0.044 | 0.25 | 5일/20일 거래량 비율 |
| `foreign_flow` | 0.15 | — | — | 외국인 순매수 (KR 전용) |
| `inst_flow` | 0.10 | — | — | 기관 순매수 (KR 전용) |
| `momentum_3m` | 0.09 | 0.041 | 0.16 | 3개월 수익률 백분위 |
| `momentum_1m` | 0.07 | 0.027 | 0.12 | 1개월 수익률 백분위 |
| `sector` | 0.05 | — | — | 섹터 강도 |

> 미국장에서는 `foreign_flow`, `inst_flow`가 자동 제외되고 나머지로 재정규화됩니다.

#### safety

| 키 | 기본값 | 설명 |
|----|--------|------|
| `daily_loss_limit_krw` | `500000` | 당일 손실 한도 (원), `0` = 비활성화 |
| `daily_loss_limit_usd` | `300` | 당일 손실 한도 (USD) |

---

## 매매 로직 흐름

```
[09:05 KST] 장 시작
│
├─ Stage 1: 후보 풀 선정 (하루 1회, 이후 캐시 재사용)
│   ├─ yfinance 6개월 OHLCV + KIS 수급 데이터 병렬 수집
│   ├─ 팩터 스코어링 → 상위 pool_size×2개 선별
│   └─ Claude Opus (tool_use) → pool_size개 확정
│       ※ 섹터 분산, 악재 뉴스, 글로벌 리서치 반영
│
├─ Stage 2: 매수 대상 선정 (30분 주기)
│   ├─ KIS 실시간 시세 조회
│   ├─ 당일 모멘텀 스코어링
│   ├─ [안전장치] Bear 국면 / 손실 한도 초과 / 블랙리스트 → 매수 차단
│   ├─ [비용 절감] 순위 동일 + TTL 15분 이내 → Claude 스킵, 캐시 재사용
│   └─ Claude Sonnet (tool_use) → 최대 3종목 확정
│
├─ Stage 3: 매도 판단 (30분마다)
│   ├─ [우선] 트레일링 스탑: 최고가 대비 5% 이탈 → 즉시 매도
│   ├─ [우선] 익절 +7% → 즉시 매도
│   └─ Claude Haiku → 정성 판단 (애매 구간)
│
└─ 체결 후 verify.py → Profit Board HMAC 서명 전송 (선택)

[16:00 KST]
├─ 포트폴리오 자산 스냅샷 저장
└─ 텔레그램 일일 요약 전송
```

**ATR 기반 포지션 사이징:**

```
qty = min(
    portfolio × 1% / (ATR14 × 2),    # 리스크 기반
    portfolio × 20% / price,           # 비중 한도
    max_buy_amount / price             # 금액 한도
)
```

---

## 리스크 관리

### 트레일링 스탑

매수 후 주가가 오를수록 손절선도 함께 상승합니다.

```
매수: 100,000원
→ 120,000원 최고가 갱신
→ 스탑 = 120,000 × (1 - 5%) = 114,000원
→ 114,000원 이하 하락 시 즉시 매도 (수익 보전)
```

`logs/trailing_stops.json`에 영속 저장 — 프로세스 재시작 후에도 유지됩니다.

### 상관계수 다양화 필터

보유 종목과 3개월 일간 수익률 상관계수 ≥ 0.70이면 신규 매수에서 제외합니다.

### 시장 국면 필터 (SMA200)

```
KODEX200 > SMA200 → Bull → 정상 매매
KODEX200 < SMA200 → Bear → 신규 매수 전면 차단
```

미국장은 QQQ 기준 동일하게 판단. 전환 시 텔레그램 알림 발송.

---

## 안전장치

### 실전 매매 이중 잠금

`KIS_IS_PAPER=false` 실전 전환은 `.env`에 두 항목이 **동시에** 있어야 합니다:

```dotenv
KIS_IS_PAPER=false
LIVE_TRADING_CONFIRMED=yes
```

`LIVE_TRADING_CONFIRMED` 없이 실행하면 러너가 즉시 종료됩니다.

### 실전 전환 체크리스트

```
□ 최소 2주 이상 모의투자 정상 동작 확인
□ logs/trades.csv 이상 거래 없음 확인
□ 텔레그램 알림 정상 수신 확인
□ max_buy_amount 실전에 맞게 조정
□ .env에 LIVE_TRADING_CONFIRMED=yes 추가
□ KIS_IS_PAPER=false 로 변경
```

---

## 텔레그램 명령어

`python telegram_cmd.py`를 별도 프로세스로 실행합니다.

### 조회

| 명령어 | 설명 |
|--------|------|
| `/status` | 시스템 상태, 시장 국면, 마지막 설정 변경 시각 |
| `/holdings` | 보유 종목 + 미실현 손익 (한국·미국 통합) |
| `/pool` | 오늘 후보 풀 + 팩터 점수 |
| `/pnl` | 오늘 실현 손익·승률·매도 내역 |
| `/state` | 현재 적용 중인 설정값 전체 |

### 제어

| 명령어 | 설명 |
|--------|------|
| `/pause` | 신규 매수 즉시 중단 (매도는 계속) |
| `/resume` | 매수 재개 |
| `/mode` | 현재 모드 확인 |
| `/mode brain` | Brain(AI) 모드 전환 |
| `/mode strategy` | Strategy(규칙) 모드 전환 |

### 설정 변경

| 명령어 | 설명 | 범위 |
|--------|------|------|
| `/set stop_loss -5.0` | 손절 기준 변경 (%) | -30 ~ 0 |
| `/set take_profit 7.0` | 익절 기준 변경 (%) | 0 ~ 100 |
| `/set buy_limit 3` | 한국장 최대 매수 종목 수 | 1 ~ 10 |
| `/set buy_limit_us 2` | 미국장 최대 매수 종목 수 | 1 ~ 10 |
| `/reset` | 모든 봇 설정 초기화 (settings.yaml 기본값 복원) | — |

### 블랙리스트

매수 제외 종목을 실시간으로 관리합니다. `logs/bot_state.json`에 저장되어 재시작 후에도 유지됩니다.

| 명령어 | 설명 |
|--------|------|
| `/blacklist` | 현재 블랙리스트 조회 |
| `/blacklist add KR 005930` | 한국 종목 추가 |
| `/blacklist add US NVDA` | 미국 종목 추가 |
| `/blacklist remove KR 005930` | 한국 종목 해제 |
| `/blacklist remove US NVDA` | 미국 종목 해제 |
| `/blacklist clear KR` | 한국 블랙리스트 전체 초기화 |
| `/blacklist clear US` | 미국 블랙리스트 전체 초기화 |
| `/blacklist clear` | 전체 초기화 |

> 영구 제외가 필요한 종목은 `settings.yaml`의 `blacklist.kr` / `blacklist.us`에 직접 추가하세요.  
> `settings.yaml` 정적 목록 + 텔레그램 추가분이 **합산** 적용됩니다.

---

## 텔레그램 알림

| 알림 | 트리거 | 기본 |
|------|--------|------|
| 🚀 러너 시작 | `python runner.py` 실행 | ON |
| 🟢 매수 체결 | 매수 실행 직후 | ON |
| 🔴 매도 체결 | 매도 실행 직후 (손익 포함) | ON |
| ⚠️ 오류 발생 | 예외 catch 시 | ON |
| 🔆🌑 국면 전환 | Bull↔Bear 전환 감지 시 | ON |
| 📋 일일 요약 | 매일 16:00 KST | ON |
| 📊 후보 풀 선정 | 풀 갱신 완료 시 | OFF |

### 알림 예시

**매수:**
```
🇰🇷 🟢 매수  09:17
삼성전자  005930
────────────────
💰 ₩74,500 × 3주  =  ₩223,500
🎯 목표  ₩79,715  (+7%)
🛡 손절  ₩70,775  (-5%)
📉 트레일  최고가 -5% 이탈 시
📝 외국인 순매수 지속, 반도체 섹터 강세
```

**매도:**
```
🇰🇷 🔴 매도  11:42
삼성전자  005930
────────────────
📈 +7.23%  (+16,100원)  |  보유 3일
💵 ₩74,500 → ₩79,883  (3주)
📝 트레일링 스탑 발동
```

---

## 전략 시스템

`trading.mode: strategy` 로 설정하면 `strategies/` 폴더의 규칙 기반 전략이 실행됩니다.

### BaseStrategy 인터페이스

모든 전략은 `BaseStrategy`를 상속해야 합니다:

```python
from strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def get_targets(self) -> list:
        """매매 대상 종목 코드/티커 목록 반환"""
        return ["005930", "000660"]

    def should_buy(self, data: dict) -> bool:
        """매수 여부 판단"""
        return data["change_rate"] > 1.0

    def should_sell(self, data: dict, holding: dict) -> bool:
        """매도 여부 판단"""
        return holding["profit_pct"] >= 7.0
```

### 전략 등록 방법

**방법 1 — settings.yaml에 이름 지정:**
```yaml
strategy:
  name: my_strategy   # → strategies/my_strategy.py 자동 로드
```

전략 파일을 `strategies/my_strategy.py`에 저장하면 `runner.py`가 자동으로 `BaseStrategy` 서브클래스를 탐지해 주입합니다.

**방법 2 — 마켓플레이스에서 설치:**
```bash
python install_strategy.py <전략ID>
# → strategies/<이름>.py 자동 저장
# → settings.yaml에 strategy.name만 추가하면 즉시 사용
```

---

## Profit Board 연동

거래 결과를 HMAC-SHA256 서명으로 Profit Board에 전송해 **수익을 공개 검증**합니다.

### 설정

1. Profit Board(`profit-board/`)를 배포합니다.
2. `/register` 페이지에서 `VERIFY_USER_ID`와 `VERIFY_SECRET`을 발급받습니다.
3. `.env`에 추가합니다:

```dotenv
VERIFY_ENDPOINT=https://your-profit-board.com
VERIFY_USER_ID=발급받은_USER_ID
VERIFY_SECRET=발급받은_SECRET
```

이후 매매가 체결될 때마다 `verify.py`가 HMAC 서명과 함께 거래 데이터를 자동 전송합니다.

### 보안 구조

| 보안 레이어 | 설명 |
|------------|------|
| HMAC-SHA256 서명 | `X-Signature` 헤더로 위변조 불가 |
| 타임스탬프 검증 | 5분 초과 또는 1분 이상 미래 타임스탬프 거절 (소급 입력 차단) |
| Nonce 중복 체크 | 동일 논스 재전송 차단 (replay attack 방지) |
| Rate limiting | 유저당 10건/분 제한 |

> `VERIFY_ENDPOINT`가 없으면 `verify.py`는 조용히 스킵합니다 — 거래에 영향 없음.

### Profit Board 배포 (Docker)

```bash
cd profit-board
docker compose up -d   # → http://localhost:3000
```

데이터는 `profit-board/data/trades.db`(SQLite)에 저장됩니다.

---

## 원격 제어 서버

`control.py`는 profit-board UI와 연동하는 HTTP 서버입니다. 텔레그램 명령어 대신 웹 UI로 봇을 제어합니다.

```bash
python control.py   # 기본 포트 5001
```

`.env` 설정:

```dotenv
CONTROL_PORT=5001
CONTROL_SECRET=비밀토큰   # profit-board와 동일하게 설정
```

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `GET /api/state` | GET | 현재 봇 상태 + settings.yaml 기본값 조회 |
| `GET /api/pnl` | GET | 오늘 실현 손익·매매 내역 |
| `GET /api/pool` | GET | 한국·미국 후보 풀 캐시 조회 |
| `/api/pause` | POST | 신규 매수 중단 |
| `/api/resume` | POST | 매수 재개 |
| `/api/mode` | POST | `{"mode": "brain"}` or `"strategy"` |
| `/api/set` | POST | `stop_loss_pct`, `take_profit_pct`, `buy_limit`, `buy_limit_us` 변경 |
| `/api/blacklist/add` | POST | `{"market": "kr", "code": "005930"}` |
| `/api/blacklist/remove` | POST | 블랙리스트 해제 |
| `/api/blacklist/clear` | POST | `{"market": "kr"}` or 전체 초기화 |
| `/api/reset` | POST | 모든 설정 초기화 |

모든 요청에 `Authorization: Bearer <CONTROL_SECRET>` 헤더가 필요합니다. `CONTROL_SECRET` 미설정 시 인증 없이 접근 가능하므로 내부망에서만 사용하세요.

---

## DART 공시 봇

`dart_bot.py`는 DART 공시를 N분마다 폴링해 호재/악재를 분류하고 텔레그램으로 알립니다. 감시 종목의 유의미한 공시는 자동으로 매수/매도까지 실행합니다.

```bash
python dart_bot.py                # 기본 3분 간격, 자동매매 ON
python dart_bot.py --interval 2   # 2분마다 폴링
python dart_bot.py --no-trade     # 알림만, 자동매매 비활성화
```

`.env` 설정:

```dotenv
DART_API_KEY=         # https://opendart.fss.or.kr 무료 발급 (하루 10만 건)
DART_BOT_TOKEN=       # BotFather에서 별도 봇 생성 권장
DART_CHAT_ID=
DART_AUTO_BUY_AMOUNT=100000   # 공시 자동매수 금액 (원)
```

| 구분 | 키워드 예시 |
|------|-----------|
| 🟢 호재 | 자기주식취득, 수주공시, 단일판매·공급계약체결, 주식배당 등 |
| 🔴 악재 | 유상증자, 전환사채, 회생절차, 불성실공시법인 등 |

- 감시 종목은 `settings.yaml`의 `stocks` / `universe` 목록에서 자동 로드
- 자동매매는 감시 종목 중 호재→매수 / 악재→매도만 실행 (보수적 소액 운용)

---

## 급등 알림 봇

`surge_alert.py`는 이미 오른 종목이 아닌 **오르기 직전** 신호를 감지해 텔레그램으로 알립니다.

```bash
python surge_alert.py              # 기본 5분 간격
python surge_alert.py --interval 3
```

`.env` 설정:

```dotenv
SURGE_BOT_TOKEN=              # BotFather에서 별도 봇 생성 권장
SURGE_CHAT_ID=
# SURGE_VOL_RATIO=3.0         # 거래량 평균 대비 배수 (기본 3.0x)
# SURGE_VOL_AVG_DAYS=20       # 거래량 평균 산정 기간 (기본 20일)
# SURGE_BB_SQUEEZE=0.03       # BB 스퀴즈 판단 밴드폭/가격 비율 (기본 3%)
# SURGE_COOLDOWN_MIN=120      # 재알림 방지 시간(분, 기본 120)
```

| 신호 | 조건 | 대상 |
|------|------|------|
| 거래량 폭증 돌파 | 거래량 > N일 평균 3x + 전일 고가 돌파 | 한·미 |
| BB 스퀴즈 돌파 | 밴드폭 ≤ 3% 압축 후 상단 돌파 | 한·미 |
| 52주 신고가 | 52주 고점 돌파 (저항 없는 구간 진입) | 한·미 |
| 장초반 거래량 폭발 | 9:00~9:30 거래량 > 전일 총량 10% | 한국만 |

감시 종목은 `settings.yaml`의 `stocks_us` / `universe_us` (미국), `stocks` / `universe` (한국)에서 자동 로드. 동일 종목·동일 신호는 쿨다운 120분 내 재알림 안 함.

---

## 모니터링 대시보드

```bash
streamlit run dashboard/app.py   # http://localhost:8501
```

| 페이지 | 주요 내용 |
|--------|----------|
| 📊 메인 | 누적손익·승률·오늘거래·국면, 팩터 상위 종목, IB 리서치 |
| 📈 분석 | 자산 커브, 실현손익 커브, 트레일링 스탑, 팩터 레이더, 섹터 분포 |
| 📋 거래 이력 | 기간·종류·모드·종목 필터, 종목별 손익 바 차트, P&L 히스토그램 |
| 📜 로그 & 캐시 | 컬러 러너 로그, pool_cache 뷰어, 리서치 캐시 |

---

## 의존성

```
anthropic             Claude API
requests              HTTP (텔레그램 Bot API)
schedule              스케줄러
python-dotenv         .env 로더
yfinance              주가 데이터 (팩터 계산)
pandas                데이터 처리
numpy                 ATR 계산
scipy                 백테스트 통계
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
| `logs/runner.log` | 전체 stdout 로그 |
| `logs/trades.csv` | 전체 거래 이력 (엑셀 호환) |
| `logs/trades/YYYY-MM-DD.json` | 날짜별 거래 JSON |
| `logs/pool_cache.json` | 한국 후보 풀 + 팩터 점수 |
| `logs/pool_cache_us.json` | 미국 후보 풀 + 팩터 점수 |
| `logs/stage2_cache.json` | 한국 Stage 2 결과 캐시 (TTL 15분) |
| `logs/stage2_cache_us.json` | 미국 Stage 2 결과 캐시 (TTL 15분) |
| `logs/regime_cache.json` | 시장 국면 이력 |
| `logs/portfolio_snapshots.json` | 일별 자산 스냅샷 |
| `logs/trailing_stops.json` | 트레일링 스탑 추적 중인 종목 |
| `logs/research_cache.json` | 글로벌 IB 리서치 요약 캐시 |
| `logs/bot_state.json` | 텔레그램 봇 설정 (pause/mode/blacklist 등) |

---

## FAQ

**Q. 모의투자와 실전 차이?**  
`KIS_IS_PAPER=true`이면 KIS 모의투자 서버로 주문이 전달되어 실제 돈이 빠져나가지 않습니다.

**Q. 후보 풀이 매일 바뀌나요?**  
`pool_refresh: daily`이면 매 장 시작 시 새로 선정, `weekly`이면 월요일에만 갱신됩니다.

**Q. Claude API 비용은?**  
Stage 1(Opus) → Stage 2(Sonnet) → Stage 3(Haiku) 단계별 비용 최적화.  
Stage 2는 순위 변동 또는 TTL 만료 시에만 호출 (하루 ~26회). 일반적으로 하루 $1~$3.

**Q. 텔레그램 없이도 되나요?**  
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 비워두면 알림 없이 정상 실행됩니다.

**Q. 내가 만든 전략을 바로 쓸 수 있나요?**  
`BaseStrategy`를 상속한 클래스를 `strategies/<이름>.py`에 저장하고 `settings.yaml`에서 `strategy.name: <이름>`으로 설정하면 즉시 주입됩니다.

**Q. Profit Board 없이도 되나요?**  
`VERIFY_ENDPOINT`를 설정하지 않으면 `verify.py`는 완전히 비활성화됩니다. 거래에 영향 없음.
