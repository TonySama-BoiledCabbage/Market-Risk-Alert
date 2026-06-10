#!/usr/bin/env python3
"""
Local web control client for Market Risk Alert.

Runs on 127.0.0.1 and uses only Python stdlib. The UI edits local settings,
updates WATCH_SYMBOLS / QUOTE_SYMBOLS in .env, triggers reports, and installs
Windows scheduled tasks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "config" / "client_settings.json"
ENV_PATH = PROJECT_DIR / ".env"
UI_DIR = PROJECT_DIR / "ui"
MARKET_ALERT = PROJECT_DIR / "market_alert.py"
BUNDLED_PYTHON = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "python.exe"

EQUITY_SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "SOXX", "XLK", "XLY"]
MACRO_SYMBOLS = ["US10Y", "US2Y", "VIX"]
DEFAULT_SETTINGS = {
    "input_path": str(PROJECT_DIR / "data" / "latest_signals.json"),
    "symbols": ["NVDA", "TSLA"],
    "custom_symbols": "VFV,XQQC",
    "evening_time": "22:00",
    "morning_time": "09:45",
    "alert_start_time": "09:20",
    "alert_interval_minutes": 15,
    "alert_duration_hours": 8,
    "fetch_alpha_vantage": False,
}
OI_WATCH_THRESHOLD_PCT = 10
OI_ALERT_THRESHOLD_PCT = 20


def python_path() -> str:
    return str(BUNDLED_PYTHON) if BUNDLED_PYTHON.exists() else "python"


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return {**default, **data}
    except Exception:
        return dict(default)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def update_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, _ = line.split("=", 1)
        clean_key = key.strip()
        if clean_key in updates:
            output.append(f"{clean_key}={updates[clean_key]}")
            seen.add(clean_key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def current_settings() -> dict:
    settings = read_json(CONFIG_PATH, DEFAULT_SETTINGS)
    env = read_env(ENV_PATH)
    if env.get("WATCH_SYMBOLS"):
        settings["symbols"] = [item.strip().upper() for item in env["WATCH_SYMBOLS"].split(",") if item.strip()]
    if env.get("QUOTE_SYMBOLS"):
        base = set(EQUITY_SYMBOLS + MACRO_SYMBOLS)
        quotes = {item.strip().upper() for item in env["QUOTE_SYMBOLS"].split(",") if item.strip()}
        extras = sorted(quotes - base)
        if extras:
            settings["custom_symbols"] = ",".join(extras)
    return settings


def read_snapshot(settings: dict) -> dict:
    path = Path(str(settings.get("input_path", "")))
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def market_value(item: dict, *fields: str) -> object:
    for field in fields:
        if field in item and item[field] is not None:
            return item[field]
    return None


def to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def build_dashboard_cards(settings: dict) -> list[dict]:
    snapshot = read_snapshot(settings)
    market = snapshot.get("market", {})
    if not isinstance(market, dict):
        market = {}

    symbols = [str(item).strip().upper() for item in settings.get("symbols", []) if str(item).strip()]
    custom = [item.strip().upper() for item in str(settings.get("custom_symbols", "")).split(",") if item.strip()]
    cards = []
    for symbol in list(dict.fromkeys(symbols + custom)):
        item = market.get(symbol, {})
        if not isinstance(item, dict):
            item = {}
        price = market_value(item, "price", "last", "close")
        change_pct = to_float(market_value(item, "change_pct", "day_change_pct"))
        oi = market_value(item, "open_interest", "options_open_interest", "oi")
        oi_change_pct = to_float(market_value(item, "oi_change_pct", "open_interest_change_pct", "options_oi_change_pct"))
        alert = oi_change_pct is not None and abs(oi_change_pct) >= OI_ALERT_THRESHOLD_PCT
        watch = oi_change_pct is not None and abs(oi_change_pct) >= OI_WATCH_THRESHOLD_PCT
        if alert:
            note = "OI alert"
        elif watch:
            note = "OI watch"
        else:
            note = "Calm"
        cards.append(
            {
                "symbol": symbol,
                "price": price,
                "change_pct": change_pct,
                "open_interest": oi,
                "oi_change_pct": oi_change_pct,
                "alert": alert,
                "watch": watch,
                "note": note,
            }
        )
    return cards


def save_settings(payload: dict) -> dict:
    settings = {**DEFAULT_SETTINGS, **payload}
    symbols = [str(item).strip().upper() for item in settings.get("symbols", []) if str(item).strip()]
    custom = [item.strip().upper() for item in str(settings.get("custom_symbols", "")).split(",") if item.strip()]
    symbols = list(dict.fromkeys(symbols + custom))
    settings["symbols"] = symbols
    settings["custom_symbols"] = ",".join(custom)
    settings["fetch_alpha_vantage"] = bool(settings.get("fetch_alpha_vantage"))
    write_json(CONFIG_PATH, settings)

    quote_symbols = [symbol for symbol in symbols if not symbol.startswith("US") and symbol != "VIX"]
    update_env(ENV_PATH, {"WATCH_SYMBOLS": ",".join(symbols), "QUOTE_SYMBOLS": ",".join(quote_symbols)})
    return settings


def run_command(args: list[str]) -> dict:
    proc = subprocess.run(
        args,
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "command": " ".join(args),
    }


def create_sample_snapshot() -> dict:
    source = PROJECT_DIR / "examples" / "sample_signals.json"
    target = PROJECT_DIR / "data" / "latest_signals.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    settings = current_settings()
    settings["input_path"] = str(target)
    save_settings(settings)
    return {"ok": True, "path": str(target)}


def alpha_key_valid() -> bool:
    key = read_env(ENV_PATH).get("ALPHAVANTAGE_API_KEY", "")
    return bool(key and "optional" not in key.lower() and "replace" not in key.lower())


def latest_run_label() -> str:
    archive_dir = PROJECT_DIR / "archive"
    if not archive_dir.exists():
        return "-"
    files = sorted(archive_dir.rglob("*-telegram.txt"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        return "-"
    stamp = files[0].stat().st_mtime
    from datetime import datetime

    return "Sent at " + datetime.fromtimestamp(stamp).strftime("%H:%M")


def validate_ready(settings: dict, scheduled: bool = False) -> tuple[bool, str]:
    input_path = Path(str(settings.get("input_path", "")))
    if not input_path.exists():
        hint = "Generate sample data first." if not scheduled else "Create the snapshot before installing the task."
        return False, f"Input snapshot does not exist: {input_path}\n{hint}"
    if settings.get("fetch_alpha_vantage") and not alpha_key_valid():
        return False, "Alpha Vantage is enabled, but ALPHAVANTAGE_API_KEY is missing or still a placeholder."
    return True, ""


class Handler(BaseHTTPRequestHandler):
    server_version = "MarketRiskClient/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.serve_file(UI_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/app.css":
            self.serve_file(UI_DIR / "app.css", "text/css; charset=utf-8")
        elif path == "/app.js":
            self.serve_file(UI_DIR / "app.js", "application/javascript; charset=utf-8")
        elif path == "/api/settings":
            settings = current_settings()
            self.send_json(
                {
                    "settings": settings,
                    "equity_symbols": EQUITY_SYMBOLS,
                    "macro_symbols": MACRO_SYMBOLS,
                    "telegram_configured": bool(read_env(ENV_PATH).get("TELEGRAM_BOT_TOKEN")),
                    "alpha_key_valid": alpha_key_valid(),
                    "sample_exists": (PROJECT_DIR / "data" / "latest_signals.json").exists(),
                    "last_run": latest_run_label(),
                    "dashboard_cards": build_dashboard_cards(settings),
                }
            )
        else:
            self.send_error(404)

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self.read_body()

        if path == "/api/settings":
            self.send_json({"ok": True, "settings": save_settings(body)})
            return

        if path == "/api/sample":
            self.send_json(create_sample_snapshot())
            return

        settings = save_settings(body.get("settings", current_settings()))
        if path == "/api/run":
            ok, message = validate_ready(settings)
            if not ok:
                self.send_json({"ok": False, "stderr": message}, 400)
                return
            mode = body.get("mode", "evening")
            args = [python_path(), str(MARKET_ALERT), "--input", settings["input_path"], "--report-mode", mode]
            if settings.get("fetch_alpha_vantage"):
                args.append("--fetch-alpha-vantage")
            self.send_json(run_command(args))
            return

        if path == "/api/install-reports":
            ok, message = validate_ready(settings, scheduled=True)
            if not ok:
                self.send_json({"ok": False, "stderr": message}, 400)
                return
            script = PROJECT_DIR / "scripts" / "install_daily_reports_task.ps1"
            args = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-InputPath",
                settings["input_path"],
                "-EveningTime",
                settings["evening_time"],
                "-MorningTime",
                settings["morning_time"],
            ]
            if settings.get("fetch_alpha_vantage"):
                args.append("-FetchAlphaVantage")
            self.send_json(run_command(args))
            return

        if path == "/api/install-alerts":
            ok, message = validate_ready(settings, scheduled=True)
            if not ok:
                self.send_json({"ok": False, "stderr": message}, 400)
                return
            script = PROJECT_DIR / "scripts" / "install_windows_task.ps1"
            args = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-InputPath",
                settings["input_path"],
                "-StartTime",
                settings["alert_start_time"],
                "-IntervalMinutes",
                str(settings["alert_interval_minutes"]),
                "-DurationHours",
                str(settings["alert_duration_hours"]),
            ]
            if settings.get("fetch_alpha_vantage"):
                args.append("-FetchAlphaVantage")
            self.send_json(run_command(args))
            return

        self.send_error(404)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Market Risk Client running at http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
