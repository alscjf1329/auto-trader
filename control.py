#!/usr/bin/env python3
"""
auto-trader 원격 제어 서버 — profit-board UI와 연동합니다.

실행:
  python control.py

환경변수:
  CONTROL_SECRET   Bearer 인증 토큰 (profit-board와 동일하게 설정)
  CONTROL_PORT     포트 (기본 5001)
"""
import json
import os
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

_ROOT       = Path(__file__).parent
_STATE_PATH = _ROOT / "logs" / "bot_state.json"
_TRADES_DIR = _ROOT / "logs" / "trades"
_POOL_KR    = _ROOT / "logs" / "pool_cache.json"
_POOL_US    = _ROOT / "logs" / "pool_cache_us.json"
_PORT       = int(os.getenv("CONTROL_PORT", 5001))
_SECRET     = os.getenv("CONTROL_SECRET", "")


def _default_state() -> dict:
    return {
        "paused": False, "mode": None,
        "stop_loss_pct": None, "take_profit_pct": None,
        "buy_limit": None, "buy_limit_us": None,
        "blacklist": {"kr": [], "us": []},
        "updated_at": None,
    }


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return _default_state()
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()


def _save_state(state: dict):
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_defaults() -> dict:
    try:
        import yaml
        with open(_ROOT / "settings.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return {
            "mode":            cfg["trading"]["mode"],
            "stop_loss_pct":   cfg["trading"].get("stop_loss_pct", -5.0),
            "take_profit_pct": cfg["risk"].get("take_profit_pct", 7.0),
            "buy_limit":       cfg["brain"].get("buy_limit", 3),
            "buy_limit_us":    cfg["brain"].get("buy_limit_us", 3),
        }
    except Exception:
        return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[Control] {fmt % args}")

    def _auth(self) -> bool:
        if not _SECRET:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {_SECRET}"

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self._auth():
            self._json({"error": "unauthorized"}, 401); return
        p = urlparse(self.path).path

        if p == "/api/state":
            self._json({"state": _load_state(), "defaults": _load_defaults()})

        elif p == "/api/pnl":
            path_file = _TRADES_DIR / f"{date.today().isoformat()}.json"
            try:
                trades = json.loads(path_file.read_text(encoding="utf-8")) if path_file.exists() else []
            except Exception:
                trades = []
            sells  = [t for t in trades if t.get("action") == "SELL"]
            buys   = [t for t in trades if t.get("action") == "BUY"]
            total  = sum(float(t.get("profit_amount") or 0) for t in sells)
            pcts   = [float(t.get("profit_pct") or 0) for t in sells if t.get("profit_pct")]
            self._json({
                "date":         date.today().isoformat(),
                "total_profit": total,
                "buys":         len(buys),
                "sells":        len(sells),
                "wins":         sum(1 for v in pcts if v > 0),
                "trades":       trades[-30:],
            })

        elif p == "/api/pool":
            out = {}
            for key, cache in [("kr", _POOL_KR), ("us", _POOL_US)]:
                try:
                    out[key] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
                except Exception:
                    out[key] = None
            self._json(out)

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._auth():
            self._json({"error": "unauthorized"}, 401); return
        p    = urlparse(self.path).path
        body = self._read_body()
        st   = _load_state()

        if p == "/api/pause":
            st["paused"] = True

        elif p == "/api/resume":
            st["paused"] = False

        elif p == "/api/mode":
            mode = body.get("mode", "").lower()
            if mode not in ("brain", "strategy"):
                self._json({"error": "brain 또는 strategy"}); return
            st["mode"] = mode

        elif p == "/api/set":
            key = body.get("key", "")
            val = body.get("value")
            if key == "stop_loss_pct":
                v = float(val)
                if not (-30 <= v <= 0):
                    self._json({"error": "-30~0 범위"}, 400); return
                st[key] = v
            elif key == "take_profit_pct":
                v = float(val)
                if not (0 < v <= 100):
                    self._json({"error": "0~100 범위"}, 400); return
                st[key] = v
            elif key in ("buy_limit", "buy_limit_us"):
                v = int(val)
                if not (1 <= v <= 10):
                    self._json({"error": "1~10 범위"}, 400); return
                st[key] = v
            else:
                self._json({"error": f"알 수 없는 키: {key}"}, 400); return

        elif p == "/api/blacklist/add":
            market = body.get("market", "").lower()
            code   = body.get("code", "").upper().strip()
            if market not in ("kr", "us") or not code:
                self._json({"error": "market(kr/us)와 code 필요"}, 400); return
            bl = st.setdefault("blacklist", {"kr": [], "us": []})
            if code not in bl[market]:
                bl[market].append(code)

        elif p == "/api/blacklist/remove":
            market = body.get("market", "").lower()
            code   = body.get("code", "").upper().strip()
            if market not in ("kr", "us"):
                self._json({"error": "market(kr/us) 필요"}, 400); return
            bl = st.setdefault("blacklist", {"kr": [], "us": []})
            bl[market] = [c for c in bl.get(market, []) if c != code]

        elif p == "/api/blacklist/clear":
            market = body.get("market", "").lower()
            bl = st.setdefault("blacklist", {"kr": [], "us": []})
            if market in ("kr", "us"):
                bl[market] = []
            else:
                bl["kr"] = []; bl["us"] = []

        elif p == "/api/reset":
            _save_state(_default_state())
            self._json({"ok": True}); return

        else:
            self._json({"error": "not found"}, 404); return

        st["updated_at"] = datetime.now().isoformat()
        _save_state(st)
        self._json({"ok": True, "state": st})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", _PORT), Handler)
    print(f"[Control] http://0.0.0.0:{_PORT}")
    if not _SECRET:
        print("[Control] ⚠️  CONTROL_SECRET 미설정 — 내부망에서만 사용하세요")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
