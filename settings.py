"""
settings.py - settings.yaml 로더
"""

import yaml
from pathlib import Path

_YAML_PATH = Path(__file__).parent / "settings.yaml"


def _load() -> dict:
    if not _YAML_PATH.exists():
        raise FileNotFoundError(f"settings.yaml 없음: {_YAML_PATH}")
    with open(_YAML_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


_cfg = _load()

# ── 매매 기본 ──────────────────────────────────────────────
MODE                : str = _cfg["trading"]["mode"]
MARKET_OPEN         : str = _cfg["trading"].get("market_open",  "09:05")
MARKET_CLOSE        : str = _cfg["trading"].get("market_close", "15:20")
MARKET_OPEN_US      : str = _cfg["trading"].get("market_open_us",  "23:00")
MARKET_CLOSE_US     : str = _cfg["trading"].get("market_close_us", "04:30")
INTERVAL_MINUTES    : int = int(_cfg["trading"].get("interval_minutes",    30))
INTERVAL_MINUTES_US : int = int(_cfg["trading"].get("interval_minutes_us", 30))
MAX_BUY_AMOUNT      : int   = int(_cfg["trading"]["max_buy_amount"])
MAX_BUY_AMOUNT_USD  : int   = int(_cfg["trading"].get("max_buy_amount_usd", 100))
STOP_LOSS_PCT       : float = float(_cfg["trading"].get("stop_loss_pct",    -5.0))
STOP_LOSS_PCT_US    : float = float(_cfg["trading"].get("stop_loss_pct_us", -7.0))
REGIME_FILTER       : bool  = bool( _cfg["trading"].get("regime_filter",    True))

# 하위 호환 (기존 코드에서 SCHEDULE_TIME 쓰는 곳 대비)
SCHEDULE_TIME    : str = MARKET_OPEN
SCHEDULE_TIME_US : str = MARKET_OPEN_US

# ── 전략 ───────────────────────────────────────────────────
STRATEGY_NAME  : str = _cfg["strategy"]["name"]

# ── Brain 설정 ─────────────────────────────────────────────
_brain              = _cfg.get("brain", {})
BRAIN_POOL_SIZE     : int = int(_brain.get("pool_size",    15))
BRAIN_POOL_SIZE_US  : int = int(_brain.get("pool_size_us",  8))
BRAIN_BUY_LIMIT     : int = int(_brain.get("buy_limit",     3))
BRAIN_BUY_LIMIT_US  : int = int(_brain.get("buy_limit_us",  3))
BRAIN_REFRESH       : str = _brain.get("pool_refresh", "daily")
BRAIN_MODEL_STAGE1  : str = _brain.get("model_stage1", "claude-opus-4-7")
BRAIN_MODEL_STAGE2  : str = _brain.get("model_stage2", "claude-sonnet-4-6")
BRAIN_MODEL_STAGE3  : str = _brain.get("model_stage3", "claude-haiku-4-5")

# ── Strategy 모드 종목 ─────────────────────────────────────
STOCKS      : list = _cfg.get("stocks", [])
STOCK_CODES : list = [s["code"] for s in STOCKS]
STOCK_MAP   : dict = {s["code"]: s["name"] for s in STOCKS}
YF_MAP      : dict = {s["code"]: f"{s['code']}.KS" for s in STOCKS}

# ── Brain 모드 한국 유니버스 ───────────────────────────────
UNIVERSE      : list = _cfg.get("universe", [])
UNIVERSE_CODES: list = [s["code"] for s in UNIVERSE]
UNIVERSE_MAP  : dict = {s["code"]: s["name"] for s in UNIVERSE}
UNIVERSE_YF   : dict = {s["code"]: f"{s['code']}.KS" for s in UNIVERSE}

# ── Brain 모드 미국 유니버스 ───────────────────────────────
UNIVERSE_US         : list = _cfg.get("universe_us", [])
UNIVERSE_US_TICKERS : list = [s["ticker"] for s in UNIVERSE_US]
UNIVERSE_US_MAP     : dict = {s["ticker"]: s["name"] for s in UNIVERSE_US}
UNIVERSE_US_EXCH    : dict = {s["ticker"]: s["exchange"] for s in UNIVERSE_US}

# ── 팩터 가중치 ─────────────────────────────────────────────
FACTOR_WEIGHTS : dict = _cfg.get("factor_weights", {
    "momentum_6m":  0.21,
    "pos_52w":      0.18,
    "volume_ratio": 0.15,
    "momentum_3m":  0.09,
    "momentum_1m":  0.07,
    "foreign_flow": 0.15,
    "inst_flow":    0.10,
    "sector":       0.05,
})

# ── 텔레그램 알림 ──────────────────────────────────────────
_tg = _cfg.get("telegram", {})
TELEGRAM_ENABLED          : bool = bool(_tg.get("enabled",           True))
TELEGRAM_ON_BUY           : bool = bool(_tg.get("on_buy",            True))
TELEGRAM_ON_SELL          : bool = bool(_tg.get("on_sell",           True))
TELEGRAM_ON_ERROR         : bool = bool(_tg.get("on_error",          True))
TELEGRAM_ON_REGIME        : bool = bool(_tg.get("on_regime",         True))
TELEGRAM_ON_POOL          : bool = bool(_tg.get("on_pool",           False))
TELEGRAM_ON_STARTUP       : bool = bool(_tg.get("on_startup",        True))
TELEGRAM_DAILY_SUMMARY    : bool = bool(_tg.get("daily_summary",     True))
TELEGRAM_SUMMARY_TIME     : str  = _tg.get("daily_summary_time",    "16:00")

# ── 리스크 파라미터 ─────────────────────────────────────────
_risk = _cfg.get("risk", {})
RISK_PER_TRADE_PCT         : float = float(_risk.get("risk_per_trade_pct",      1.0))
RISK_ATR_MULTIPLIER        : float = float(_risk.get("atr_multiplier",          2.0))
RISK_MAX_POSITION_PCT      : float = float(_risk.get("max_position_pct",       20.0))
RISK_MAX_TOTAL_EXPOSURE_PCT: float = float(_risk.get("max_total_exposure_pct", 80.0))
RISK_MAX_POSITIONS         : int   = int(  _risk.get("max_positions",           5))
RISK_TAKE_PROFIT_PCT       : float = float(_risk.get("take_profit_pct",         7.0))
RISK_TRAILING_STOP_PCT     : float = float(_risk.get("trailing_stop_pct",       5.0))
RISK_TRAILING_STOP_ENABLED : bool  = bool( _risk.get("trailing_stop_enabled",   True))
RISK_CORRELATION_FILTER    : bool  = bool( _risk.get("correlation_filter",       True))
RISK_CORRELATION_THRESHOLD : float = float(_risk.get("correlation_threshold",   0.70))

# ── 안전장치 ────────────────────────────────────────────────
_safety = _cfg.get("safety", {})
SAFETY_DAILY_LOSS_LIMIT_KRW : int   = int(  _safety.get("daily_loss_limit_krw", 500_000))
SAFETY_DAILY_LOSS_LIMIT_USD  : float = float(_safety.get("daily_loss_limit_usd", 300.0))

# ── 파라미터 ───────────────────────────────────────────────
_all_params : dict = _cfg.get("params", {})


def get_params(strategy_name: str | None = None) -> dict:
    return _all_params.get(strategy_name or STRATEGY_NAME, {})


def reload():
    global _cfg, MODE, SCHEDULE_TIME, SCHEDULE_TIME_US, MAX_BUY_AMOUNT, MAX_BUY_AMOUNT_USD
    global STOP_LOSS_PCT, STOP_LOSS_PCT_US, REGIME_FILTER
    global MARKET_OPEN, MARKET_CLOSE, MARKET_OPEN_US, MARKET_CLOSE_US
    global INTERVAL_MINUTES, INTERVAL_MINUTES_US
    global STRATEGY_NAME
    global BRAIN_POOL_SIZE, BRAIN_POOL_SIZE_US, BRAIN_BUY_LIMIT, BRAIN_BUY_LIMIT_US, BRAIN_REFRESH
    global BRAIN_MODEL_STAGE1, BRAIN_MODEL_STAGE2, BRAIN_MODEL_STAGE3
    global STOCKS, STOCK_CODES, STOCK_MAP, YF_MAP
    global UNIVERSE, UNIVERSE_CODES, UNIVERSE_MAP, UNIVERSE_YF
    global UNIVERSE_US, UNIVERSE_US_TICKERS, UNIVERSE_US_MAP, UNIVERSE_US_EXCH
    global _all_params
    global FACTOR_WEIGHTS
    global RISK_PER_TRADE_PCT, RISK_ATR_MULTIPLIER, RISK_MAX_POSITION_PCT
    global RISK_MAX_TOTAL_EXPOSURE_PCT, RISK_MAX_POSITIONS, RISK_TAKE_PROFIT_PCT
    global RISK_TRAILING_STOP_PCT, RISK_TRAILING_STOP_ENABLED
    global RISK_CORRELATION_FILTER, RISK_CORRELATION_THRESHOLD
    global SAFETY_DAILY_LOSS_LIMIT_KRW, SAFETY_DAILY_LOSS_LIMIT_USD
    global TELEGRAM_ENABLED, TELEGRAM_ON_BUY, TELEGRAM_ON_SELL, TELEGRAM_ON_ERROR
    global TELEGRAM_ON_REGIME, TELEGRAM_ON_POOL, TELEGRAM_ON_STARTUP
    global TELEGRAM_DAILY_SUMMARY, TELEGRAM_SUMMARY_TIME

    _cfg                = _load()
    MODE                = _cfg["trading"]["mode"]
    MARKET_OPEN         = _cfg["trading"].get("market_open",  "09:05")
    MARKET_CLOSE        = _cfg["trading"].get("market_close", "15:20")
    MARKET_OPEN_US      = _cfg["trading"].get("market_open_us",  "23:00")
    MARKET_CLOSE_US     = _cfg["trading"].get("market_close_us", "04:30")
    INTERVAL_MINUTES    = int(_cfg["trading"].get("interval_minutes",    30))
    INTERVAL_MINUTES_US = int(_cfg["trading"].get("interval_minutes_us", 30))
    MAX_BUY_AMOUNT      = int(_cfg["trading"]["max_buy_amount"])
    MAX_BUY_AMOUNT_USD  = int(_cfg["trading"].get("max_buy_amount_usd", 100))
    STOP_LOSS_PCT       = float(_cfg["trading"].get("stop_loss_pct",    -5.0))
    STOP_LOSS_PCT_US    = float(_cfg["trading"].get("stop_loss_pct_us", -7.0))
    REGIME_FILTER       = bool( _cfg["trading"].get("regime_filter",    True))
    SCHEDULE_TIME       = MARKET_OPEN
    SCHEDULE_TIME_US    = MARKET_OPEN_US
    STRATEGY_NAME       = _cfg["strategy"]["name"]
    _b                  = _cfg.get("brain", {})
    BRAIN_POOL_SIZE     = int(_b.get("pool_size",    15))
    BRAIN_POOL_SIZE_US  = int(_b.get("pool_size_us",  8))
    BRAIN_BUY_LIMIT     = int(_b.get("buy_limit",     3))
    BRAIN_BUY_LIMIT_US  = int(_b.get("buy_limit_us",  3))
    BRAIN_REFRESH       = _b.get("pool_refresh", "daily")
    BRAIN_MODEL_STAGE1  = _b.get("model_stage1", "claude-opus-4-7")
    BRAIN_MODEL_STAGE2  = _b.get("model_stage2", "claude-sonnet-4-6")
    BRAIN_MODEL_STAGE3  = _b.get("model_stage3", "claude-haiku-4-5")
    STOCKS              = _cfg.get("stocks", [])
    STOCK_CODES         = [s["code"] for s in STOCKS]
    STOCK_MAP           = {s["code"]: s["name"] for s in STOCKS}
    YF_MAP              = {s["code"]: f"{s['code']}.KS" for s in STOCKS}
    UNIVERSE            = _cfg.get("universe", [])
    UNIVERSE_CODES      = [s["code"] for s in UNIVERSE]
    UNIVERSE_MAP        = {s["code"]: s["name"] for s in UNIVERSE}
    UNIVERSE_YF         = {s["code"]: f"{s['code']}.KS" for s in UNIVERSE}
    UNIVERSE_US         = _cfg.get("universe_us", [])
    UNIVERSE_US_TICKERS = [s["ticker"] for s in UNIVERSE_US]
    UNIVERSE_US_MAP     = {s["ticker"]: s["name"] for s in UNIVERSE_US}
    UNIVERSE_US_EXCH    = {s["ticker"]: s["exchange"] for s in UNIVERSE_US}
    _all_params         = _cfg.get("params", {})
    FACTOR_WEIGHTS      = _cfg.get("factor_weights", {
        "momentum_6m":  0.21,
        "pos_52w":      0.18,
        "volume_ratio": 0.15,
        "momentum_3m":  0.09,
        "momentum_1m":  0.07,
        "foreign_flow": 0.15,
        "inst_flow":    0.10,
        "sector":       0.05,
    })
    _r = _cfg.get("risk", {})
    RISK_PER_TRADE_PCT          = float(_r.get("risk_per_trade_pct",      1.0))
    RISK_ATR_MULTIPLIER         = float(_r.get("atr_multiplier",          2.0))
    RISK_MAX_POSITION_PCT       = float(_r.get("max_position_pct",       20.0))
    RISK_MAX_TOTAL_EXPOSURE_PCT = float(_r.get("max_total_exposure_pct", 80.0))
    RISK_MAX_POSITIONS          = int(  _r.get("max_positions",           5))
    RISK_TAKE_PROFIT_PCT        = float(_r.get("take_profit_pct",         7.0))
    RISK_TRAILING_STOP_PCT      = float(_r.get("trailing_stop_pct",       5.0))
    RISK_TRAILING_STOP_ENABLED  = bool( _r.get("trailing_stop_enabled",   True))
    RISK_CORRELATION_FILTER     = bool( _r.get("correlation_filter",       True))
    RISK_CORRELATION_THRESHOLD  = float(_r.get("correlation_threshold",   0.70))
    _s = _cfg.get("safety", {})
    SAFETY_DAILY_LOSS_LIMIT_KRW = int(  _s.get("daily_loss_limit_krw", 500_000))
    SAFETY_DAILY_LOSS_LIMIT_USD = float(_s.get("daily_loss_limit_usd", 300.0))
    _tg = _cfg.get("telegram", {})
    TELEGRAM_ENABLED       = bool(_tg.get("enabled",           True))
    TELEGRAM_ON_BUY        = bool(_tg.get("on_buy",            True))
    TELEGRAM_ON_SELL       = bool(_tg.get("on_sell",           True))
    TELEGRAM_ON_ERROR      = bool(_tg.get("on_error",          True))
    TELEGRAM_ON_REGIME     = bool(_tg.get("on_regime",         True))
    TELEGRAM_ON_POOL       = bool(_tg.get("on_pool",           False))
    TELEGRAM_ON_STARTUP    = bool(_tg.get("on_startup",        True))
    TELEGRAM_DAILY_SUMMARY = bool(_tg.get("daily_summary",     True))
    TELEGRAM_SUMMARY_TIME  = _tg.get("daily_summary_time",    "16:00")


def _print_summary():
    if MODE == "brain":
        print(f"[Settings] 모드: brain")
        print(f"  한국장: 유니버스 {len(UNIVERSE)}종목 → 풀 {BRAIN_POOL_SIZE}개 → 매수 {BRAIN_BUY_LIMIT}개 | {SCHEDULE_TIME} KST")
        print(f"  미국장: 유니버스 {len(UNIVERSE_US)}종목 → 풀 {BRAIN_POOL_SIZE_US}개 → 매수 {BRAIN_BUY_LIMIT_US}개 | {SCHEDULE_TIME_US} KST")
    else:
        print(f"[Settings] 모드: strategy({STRATEGY_NAME}) | 종목 {len(STOCKS)}개 | {SCHEDULE_TIME}")

_print_summary()
