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

# ── 파라미터 ───────────────────────────────────────────────
_all_params : dict = _cfg.get("params", {})


def get_params(strategy_name: str | None = None) -> dict:
    return _all_params.get(strategy_name or STRATEGY_NAME, {})


def reload():
    global _cfg, MODE, SCHEDULE_TIME, SCHEDULE_TIME_US, MAX_BUY_AMOUNT, MAX_BUY_AMOUNT_USD
    global STRATEGY_NAME
    global BRAIN_POOL_SIZE, BRAIN_POOL_SIZE_US, BRAIN_BUY_LIMIT, BRAIN_BUY_LIMIT_US, BRAIN_REFRESH
    global STOCKS, STOCK_CODES, STOCK_MAP, YF_MAP
    global UNIVERSE, UNIVERSE_CODES, UNIVERSE_MAP, UNIVERSE_YF
    global UNIVERSE_US, UNIVERSE_US_TICKERS, UNIVERSE_US_MAP, UNIVERSE_US_EXCH
    global _all_params

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
    SCHEDULE_TIME       = MARKET_OPEN
    SCHEDULE_TIME_US    = MARKET_OPEN_US
    STRATEGY_NAME       = _cfg["strategy"]["name"]
    _b                  = _cfg.get("brain", {})
    BRAIN_POOL_SIZE     = int(_b.get("pool_size",    15))
    BRAIN_POOL_SIZE_US  = int(_b.get("pool_size_us",  8))
    BRAIN_BUY_LIMIT     = int(_b.get("buy_limit",     3))
    BRAIN_BUY_LIMIT_US  = int(_b.get("buy_limit_us",  3))
    BRAIN_REFRESH       = _b.get("pool_refresh", "daily")
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


def _print_summary():
    if MODE == "brain":
        print(f"[Settings] 모드: brain")
        print(f"  한국장: 유니버스 {len(UNIVERSE)}종목 → 풀 {BRAIN_POOL_SIZE}개 → 매수 {BRAIN_BUY_LIMIT}개 | {SCHEDULE_TIME} KST")
        print(f"  미국장: 유니버스 {len(UNIVERSE_US)}종목 → 풀 {BRAIN_POOL_SIZE_US}개 → 매수 {BRAIN_BUY_LIMIT_US}개 | {SCHEDULE_TIME_US} KST")
    else:
        print(f"[Settings] 모드: strategy({STRATEGY_NAME}) | 종목 {len(STOCKS)}개 | {SCHEDULE_TIME}")

_print_summary()
