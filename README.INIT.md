# Auto-Trader 초기 세팅 가이드

처음 설치하는 경우 이 문서를 순서대로 따라하세요.  
**모든 단계를 건너뛰지 말고** 진행하면 30분 안에 모의투자 첫 실행까지 완료할 수 있습니다.

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [저장소 준비](#2-저장소-준비)
3. [KIS API 발급](#3-kis-api-발급)
4. [Anthropic API 발급](#4-anthropic-api-발급)
5. [텔레그램 봇 설정](#5-텔레그램-봇-설정-선택)
6. [.env 파일 작성](#6-env-파일-작성)
7. [settings.yaml 핵심 설정](#7-settingsyaml-핵심-설정)
8. [설치 검증](#8-설치-검증)
9. [첫 실행 (모의투자)](#9-첫-실행-모의투자)
10. [정상 동작 확인](#10-정상-동작-확인)
11. [실전 전환 체크리스트](#11-실전-전환-체크리스트)
12. [문제 해결](#12-문제-해결)

---

## 1. 사전 요구사항

### Python 버전

```
Python 3.11 이상 필수
```

버전 확인:
```bash
python --version
# Python 3.11.x 또는 3.12.x 이어야 함
```

3.10 이하라면 [python.org](https://www.python.org/downloads/)에서 최신 버전 설치 후 진행하세요.

### 필수 계정

| 계정 | 용도 | 발급 링크 |
|------|------|----------|
| 한국투자증권 | KIS API (매매 실행) | https://www.truefriend.com |
| Anthropic | Claude AI API | https://console.anthropic.com |
| 텔레그램 | 알림 봇 (선택) | https://t.me/BotFather |

> **모의투자도 한국투자증권 계좌가 필요합니다.** 계좌가 없다면 먼저 개설하세요.

---

## 2. 저장소 준비

### 2-1. 코드 다운로드

```bash
git clone <repo-url>
cd auto-trader
```

또는 ZIP 다운로드 후 압축 해제.

### 2-2. 가상환경 생성 (강력 권장)

```bash
# 가상환경 생성
python -m venv venv

# 활성화 (Windows)
venv\Scripts\activate

# 활성화 (macOS/Linux)
source venv/bin/activate

# 활성화 확인 — 프롬프트 앞에 (venv) 표시되어야 함
(venv) C:\auto-trader>
```

### 2-3. 의존성 설치

```bash
pip install -r requirements.txt
```

설치 완료 확인:
```bash
pip list | grep -E "anthropic|streamlit|yfinance|schedule"
# anthropic, streamlit, yfinance, schedule 이 모두 보여야 함
```

---

## 3. KIS API 발급

> **모의투자와 실전투자는 APP KEY가 다릅니다.**  
> 처음에는 모의투자 키로 시작하고, 충분히 테스트한 뒤 실전 키로 교체하세요.

### 3-1. KIS Developers 접속

[https://apiportal.koreainvestment.com](https://apiportal.koreainvestment.com) → 로그인

> HTS 아이디/비밀번호로 로그인합니다. 별도 가입 불필요.

---

### ▶ 모의투자 API 발급

#### 3-2. 모의투자 앱 등록

```
상단 메뉴 → [개발자센터] → [애플리케이션] → [앱 등록]
```

- **앱 이름**: 임의 입력 (예: `my-autotrader-paper`)
- **서비스 종류**: `모바일`
- **사용 API**: `국내주식 주문`, `국내주식 시세`, `해외주식 주문`, `해외주식 시세` 체크
- 등록 완료 후 **APP KEY** 와 **APP SECRET** 복사해두기

#### 3-3. 모의투자 계좌 신청

```
상단 메뉴 → [모의투자] → [신청하기]
```

- 모의투자 계좌번호 발급 (8자리)
- 초기 가상 자금 설정 (기본 50,000,000원)
- **신청 후 약 1~2분 후 활성화**

---

### ▶ 실전투자 API 발급 (모의투자 충분히 테스트 후 진행)

#### 3-4. 실전투자 앱 등록

```
상단 메뉴 → [개발자센터] → [애플리케이션] → [앱 등록]
```

- **앱 이름**: 임의 입력 (예: `my-autotrader-live`)
- **서비스 종류**: `모바일`
- **사용 API**: `국내주식 주문`, `국내주식 시세`, `해외주식 주문`, `해외주식 시세` 체크
- **모의투자 앱과 별개로 새로 등록** — 발급되는 KEY/SECRET이 다름
- 등록 완료 후 **APP KEY** 와 **APP SECRET** 복사해두기

#### 3-5. 실전 계좌번호 확인

- HTS(영웅문) 또는 MTS에서 본인 계좌번호 8자리 확인
- 국내주식 계좌와 해외주식 계좌가 다를 경우 각각 메모

#### 3-6. IP 등록 (실전 전용, 필수)

실전투자 API는 **등록된 IP에서만 호출 가능**합니다.

```
KIS Developers → [개발자센터] → [애플리케이션] → 앱 선택 → [IP 등록]
```

- 봇을 실행할 서버/PC의 공인 IP 주소 입력
- 현재 내 IP 확인: https://whatismyipaddress.com
- 클라우드 서버(AWS, GCP 등)에서 실행 시 해당 서버의 외부 IP 등록
- IP가 바뀌면 재등록 필요

---

### 3-7. 필요한 정보 정리

| 항목 | 모의투자 | 실전투자 |
|------|---------|---------|
| APP KEY | 모의 앱에서 발급 | 실전 앱에서 발급 (다름) |
| APP SECRET | 모의 앱에서 발급 | 실전 앱에서 발급 (다름) |
| 계좌번호 | 모의투자 신청 후 발급 | 실제 증권 계좌 앞 8자리 |
| KIS_IS_PAPER | `true` | `false` |

메모장에 미리 정리해두세요:

```
KIS_APP_KEY     = (앱 등록에서 발급받은 APP KEY)
KIS_APP_SECRET  = (앱 등록에서 발급받은 APP SECRET)
KIS_ACCT_STOCK  = (계좌번호 앞 8자리, 예: 50123456)
KIS_ACCT_OVRS   = (해외주식 계좌번호, 없으면 위와 동일)
KIS_HTS_ID      = (HTS 로그인 아이디)
```

> **계좌번호 형식 주의**: KIS API에서는 `-` 없이 숫자 8자리만 사용합니다.  
> 예) `500-12-345678` → `50012345`

---

## 4. Anthropic API 발급

### 4-1. 콘솔 접속

[https://console.anthropic.com](https://console.anthropic.com) → 가입 또는 로그인

### 4-2. API Key 생성

```
좌측 메뉴 → [API Keys] → [Create Key]
```

- 키 이름: 임의 입력 (예: `auto-trader`)
- 생성 즉시 표시되는 `sk-ant-...` 형태의 키를 **복사해서 안전한 곳에 저장**  
  ⚠️ 이 화면을 닫으면 다시 볼 수 없습니다.

### 4-3. 크레딧 충전

```
좌측 메뉴 → [Billing] → [Add Credits]
```

- 최소 $10 충전 권장 (일반적으로 하루 $0.5~$2 소모)
- 잔액이 0이면 API 호출이 차단됩니다.

### 4-4. 한도 확인

```
[Rate Limits] 탭에서 현재 Tier 확인
```

- Tier 1 (기본): 분당 50 요청 — 자동매매 사용에 충분
- Usage Limit이 낮으면 [Billing] → [Usage Limits] 에서 월 한도 설정

---

## 5. 텔레그램 봇 설정 (선택)

텔레그램 없이도 실행됩니다. 단, 알림 수신을 위해 강력히 권장합니다.

### 5-1. BotFather로 봇 생성

1. 텔레그램 앱 열기 → 검색창에 `@BotFather` 입력 → 채팅 시작
2. `/newbot` 입력
3. 봇 이름 입력 (예: `My AutoTrader`)
4. 봇 사용자명 입력 (예: `my_autotrader_bot`, 반드시 `bot`으로 끝나야 함)
5. 완료 후 `봇 토큰` 발급:
   ```
   Use this token to access the HTTP API:
   1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   이 토큰 전체를 복사해두기

### 5-2. Chat ID 확인

1. 만든 봇에게 **먼저 아무 메시지 보내기** (예: `안녕`)  
   ⚠️ 이 단계를 건너뛰면 chat_id 조회가 안 됩니다.

2. 브라우저에서 아래 URL 열기 (토큰 교체):
   ```
   https://api.telegram.org/bot<여기에_토큰>/getUpdates
   ```

3. 응답 JSON에서 chat id 찾기:
   ```json
   {
     "result": [{
       "message": {
         "chat": {
           "id": 123456789,    ← 이 숫자가 CHAT_ID
           ...
         }
       }
     }]
   }
   ```

4. 숫자(음수일 수도 있음) 전체를 복사해두기

### 5-3. 테스트

브라우저에서 아래 URL 접속 시 텔레그램으로 메시지가 오면 정상:
```
https://api.telegram.org/bot<토큰>/sendMessage?chat_id=<챗ID>&text=테스트
```

---

## 6. .env 파일 작성

### 6-1. 예시 파일 복사

```bash
cp .env.example .env
```

### 6-2. .env 편집

아래 내용을 참고해 값을 입력합니다:

```dotenv
# ─────────────────────────────────────────────────────────
# KIS (한국투자증권) API
# ─────────────────────────────────────────────────────────
KIS_APP_KEY=PSxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_APP_SECRET=xxxxx/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_ACCT_STOCK=50123456
KIS_ACCT_OVRS=50123456
KIS_HTS_ID=myhtsuserid
KIS_IS_PAPER=true           # ← 반드시 true 로 시작!

# ─────────────────────────────────────────────────────────
# Anthropic Claude API
# ─────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxx

# ─────────────────────────────────────────────────────────
# 텔레그램 알림 (선택, 없으면 빈칸으로 두기)
# ─────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=123456789

# ─────────────────────────────────────────────────────────
# 실전 전환 시에만 아래 줄 주석 해제
# ─────────────────────────────────────────────────────────
# LIVE_TRADING_CONFIRMED=yes
```

### 6-3. 주의사항

- `.env` 파일을 **절대 git에 커밋하지 마세요** (`.gitignore`에 이미 포함됨)
- `KIS_IS_PAPER=true` 인 상태에서는 **실제 돈이 사용되지 않습니다**
- API 키에 공백이나 따옴표가 들어가지 않도록 주의

---

## 7. settings.yaml 핵심 설정

`settings.yaml`은 이미 즉시 실행 가능한 기본값으로 설정되어 있습니다.  
처음에는 아래 항목만 본인 상황에 맞게 조정하세요.

### 확인 필수 항목

```yaml
trading:
  mode: brain                  # brain(AI 자동선택) 또는 strategy(규칙 기반)
  max_buy_amount: 100000       # 1회 최대 매수금액 (원). 모의투자면 넉넉히 설정 가능
  max_buy_amount_usd: 100      # 미국주식 1회 최대 매수금액 (USD)

brain:
  buy_limit: 3                 # 하루에 최대 몇 종목까지 신규 매수할지
  buy_limit_us: 2              # 미국주식 하루 최대 신규 매수 종목 수

risk:
  max_positions: 5             # 동시 보유 최대 종목 수
  take_profit_pct: 7.0         # 익절 기준 %. 낮추면 더 자주 익절
  trailing_stop_pct: 5.0       # 최고가 대비 이 % 이상 하락 시 자동 매도

safety:
  daily_loss_limit_krw: 500000 # 하루 최대 손실 한도 (원). 초과 시 신규 매수 차단
```

### 변경 불필요 항목 (기본값 그대로 사용 권장)

```yaml
trading:
  market_open: "09:05"         # 한국장 시작 시각
  market_close: "15:20"        # 한국장 종료 시각
  market_open_us: "23:00"      # 미국장 시작 (KST)
  market_close_us: "04:30"     # 미국장 종료 (KST)
  interval_minutes: 30         # 매매 판단 주기 (분)
  stop_loss_pct: -5.0          # 즉시 손절 기준 (%)
  regime_filter: true          # Bear 시장에서 매수 차단 (끄지 말 것)

risk:
  risk_per_trade_pct: 1.0      # ATR 기반 포지션 사이징 위험도
  max_total_exposure_pct: 80.0 # 전체 포트폴리오 주식 비중 상한
  correlation_filter: true     # 유사 종목 중복 매수 방지 (끄지 말 것)
```

---

## 8. 설치 검증

실행 전에 각 모듈이 정상 임포트되는지 확인합니다.

### 8-1. 환경변수 로드 확인

```bash
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('KIS_APP_KEY:', os.getenv('KIS_APP_KEY', '❌ 없음')[:10], '...')
print('ANTHROPIC_API_KEY:', os.getenv('ANTHROPIC_API_KEY', '❌ 없음')[:15], '...')
print('KIS_IS_PAPER:', os.getenv('KIS_IS_PAPER'))
"
```

정상 출력 예:
```
KIS_APP_KEY: PSrxmRbDWM ...
ANTHROPIC_API_KEY: sk-ant-api03- ...
KIS_IS_PAPER: true
```

### 8-2. settings.yaml 파싱 확인

```bash
python -c "import settings; settings._print_summary()"
```

정상 출력 예:
```
[Settings] 모드: brain
  한국장: 유니버스 50종목 → 풀 15개 → 매수 3개 | 09:05 KST
  미국장: 유니버스 22종목 → 풀 8개 → 매수 3개 | 23:00 KST
```

### 8-3. KIS API 연결 확인

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
import kis_api
token = kis_api.get_access_token()
print('KIS 토큰 발급 성공:', token[:20], '...')
"
```

정상 출력:
```
KIS 토큰 발급 성공: eyJ0eXAiOiJKV1QiLCJh ...
```

오류가 나면 → [문제 해결 섹션](#12-문제-해결) 참조

### 8-4. Claude API 연결 확인

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
import anthropic
client = anthropic.Anthropic()
msg = client.messages.create(
    model='claude-haiku-4-5',
    max_tokens=10,
    messages=[{'role': 'user', 'content': 'ping'}]
)
print('Claude 연결 성공:', msg.content[0].text)
"
```

정상 출력:
```
Claude 연결 성공: pong
```

### 8-5. 텔레그램 연결 확인 (설정한 경우)

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
import notify
ok = notify.send('✅ Auto-Trader 설치 확인 테스트')
print('전송 결과:', ok)
"
```

텔레그램으로 메시지가 오면 성공.

---

## 9. 첫 실행 (모의투자)

### 9-1. logs 디렉토리 생성

```bash
mkdir -p logs/trades
```

> Windows:
> ```cmd
> mkdir logs\trades
> ```

### 9-2. 매매 봇 실행

```bash
python runner.py
```

시작 직후 출력 예:
```
[Settings] 모드: brain
  한국장: 유니버스 50종목 → 풀 15개 → 매수 3개 | 09:05 KST
  미국장: 유니버스 22종목 → 풀 8개 → 매수 3개 | 23:00 KST
[Runner] 모의투자 모드 확인
[Runner] Auto-Trader 시작 (brain 모드)
[Runner] 다음 한국장 매매: 09:05
[Runner] 스케줄러 실행 중 (Ctrl+C 종료)
```

**⚠️ 장 시간이 아니면 자동으로 대기합니다.** 즉시 실행 테스트가 필요하면 아래 참조.

### 9-3. 즉시 동작 테스트 (장 시간 외)

```bash
python -c "
from dotenv import load_dotenv
load_dotenv()
import runner
# 한국장 1사이클 즉시 실행
runner.run_kr()
"
```

> 이 방법은 실제 KIS API를 호출하지만 `KIS_IS_PAPER=true` 이므로 모의투자 계좌에만 영향을 줍니다.

### 9-4. 대시보드 동시 실행 (별도 터미널)

```bash
# 터미널 2
streamlit run dashboard/app.py
```

브라우저에서 `http://localhost:8501` 접속.  
거래 데이터가 아직 없으면 빈 화면이 정상입니다.

---

## 10. 정상 동작 확인

### 10-1. 로그 확인

```bash
tail -f logs/runner.log
```

장 시간 첫 실행 후 아래와 같은 흐름이 보여야 합니다:

```
[Runner] 한국장 매매 사이클 시작
[Factor] 유니버스 50개 팩터 계산 중...
[Factor] 팩터 계산 완료 — 상위 30개 선별
[Brain-Stage1] Claude Opus 4.7 pool 선정 중...
[Brain-Stage1] 풀 확정 — 15종목 캐시 저장
[Brain-Stage2] 후보 풀 15개 당일 모멘텀 스코어링...
[Brain-Stage2] 매수 대상 확정: ['005930', '000660', '035420']
[Risk] 포지션 사이징 — 005930: 3주 (ATR기반)
[KIS] 매수 주문 — 005930 삼성전자 3주 @ 74500
[Journal] 거래 기록 완료
[TrailingStop] 005930 추적 시작 — 매수가 74500.00
```

### 10-2. 매매 기록 확인

```bash
# CSV 확인
cat logs/trades.csv

# 오늘 JSON 확인
cat logs/trades/$(date +%Y-%m-%d).json
```

### 10-3. 텔레그램 알림 확인

매수 발생 시 다음과 같은 메시지가 와야 합니다:

```
🇰🇷 🟢 매수 체결
종목: 삼성전자 (005930)
수량: 3주  |  단가: ₩74,500
금액: ₩223,500
📝 모멘텀 상위, 외국인 순매수 지속
⏰ 09:17:32
```

### 10-4. 일반적인 첫날 일정

| 시각 (KST) | 동작 |
|-----------|------|
| 09:05 | Stage 1 — 후보 풀 선정 (약 2~5분 소요) |
| 09:10 | Stage 2 — 매수 종목 확정 + 주문 실행 |
| 09:10~ | 30분마다 매도 판단 반복 |
| 15:20 | 한국장 종료 |
| 16:00 | 일일 요약 텔레그램 전송 |
| 23:00 | 미국장 Stage 1 시작 |

---

## 11. 실전 전환 체크리스트

**최소 2주 모의투자 후** 아래를 전부 확인하고 전환하세요.

### 기능 검증

```
□ runner.py가 매일 정상 시작/종료됨
□ 매수/매도가 예상대로 실행됨
□ logs/trades.csv에 이상한 거래 없음
□ 텔레그램 알림 정상 수신 확인
□ 대시보드 손익 커브가 올바르게 그려짐
□ 트레일링 스탑이 실제로 발동되는 것 확인
□ Bear 국면에서 매수가 차단됨 확인
```

### 설정 조정

```
□ max_buy_amount를 실제 투자 금액에 맞게 수정
□ risk_per_trade_pct, max_positions 재검토
□ daily_loss_limit_krw를 하루 최대 허용 손실로 설정
□ 2주 모의 수익률 검토 후 전략 파라미터 조정
```

### 실전 전환

```bash
# 1. settings.yaml 매수 금액 조정
#    max_buy_amount: 500000  ← 실제 금액으로

# 2. .env 수정
KIS_IS_PAPER=false
LIVE_TRADING_CONFIRMED=yes   # ← 이 줄 없으면 프로그램이 즉시 종료됨
```

> ⚠️ `LIVE_TRADING_CONFIRMED=yes` 없이 `KIS_IS_PAPER=false`로 실행하면  
> 프로그램이 즉시 종료되고 텔레그램으로 경고 알림이 발송됩니다.  
> 이것은 의도된 이중 잠금 장치입니다.

---

## 12. 문제 해결

### KIS 토큰 발급 실패

```
Error: 접근토큰 발급 실패 — 401
```

**원인 및 해결:**
- APP KEY / APP SECRET 오타 → `.env` 다시 확인
- 계좌번호 형식 오류 → 8자리 숫자만 (대시 없음)
- 모의투자 신청 미완료 → KIS Developers에서 모의투자 신청 확인
- 실전 계좌 키로 모의투자 서버 호출 → `KIS_IS_PAPER`와 APP KEY가 맞는 환경인지 확인

### Anthropic API 오류

```
anthropic.AuthenticationError: 401
```

**해결:** `.env`의 `ANTHROPIC_API_KEY` 값 확인. `sk-ant-`로 시작해야 함.

```
anthropic.RateLimitError: 429
```

**해결:** Anthropic 콘솔에서 Usage Limits 확인 및 크레딧 충전.

### settings.yaml 파싱 오류

```
yaml.scanner.ScannerError: ...
```

**해결:** YAML은 들여쓰기에 민감합니다.
- 탭 대신 스페이스 사용 확인
- 들여쓰기 2칸 일관성 확인
- 온라인 YAML 검증기: https://yamlchecker.com

### yfinance 데이터 없음

```
[Factor] 005930: 데이터 없음 (거래일 아님?)
```

**해결:** 장이 열린 날 실행하거나, 공휴일/주말이면 정상입니다.

### 텔레그램 메시지 미수신

1. 토큰과 chat_id 재확인
2. 봇에게 먼저 메시지 보냈는지 확인
3. 테스트 URL로 직접 전송:
   ```
   https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=test
   ```
4. `settings.yaml`의 `telegram.enabled: true` 확인

### 장 시간 외 실행 시 매매 없음

정상입니다. 매매 봇은 장 시간에만 동작합니다.  
즉시 테스트하려면 [9-3. 즉시 동작 테스트](#9-3-즉시-동작-테스트-장-시간-외) 참조.

### 모듈 import 오류

```
ModuleNotFoundError: No module named 'xxx'
```

**해결:**
```bash
# 가상환경 활성화 확인
(venv) $ pip install -r requirements.txt
```

---

## 참고 링크

| 자료 | URL |
|------|-----|
| KIS Developers | https://apiportal.koreainvestment.com |
| KIS API 문서 | https://apiportal.koreainvestment.com/apiservice |
| Anthropic 콘솔 | https://console.anthropic.com |
| Anthropic 요금 | https://www.anthropic.com/pricing |
| Streamlit 문서 | https://docs.streamlit.io |
| 전체 시스템 문서 | [README.md](README.md) |
