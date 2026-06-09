#!/usr/bin/env python3
"""
Minimal desktop client for the market risk alert project.

Uses only Python stdlib + Tkinter. It edits local config, updates WATCH_SYMBOLS
and QUOTE_SYMBOLS in .env, triggers reports manually, and installs scheduled
tasks with user-selected times.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
import shutil
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "config" / "client_settings.json"
ENV_PATH = PROJECT_DIR / ".env"
MARKET_ALERT = PROJECT_DIR / "market_alert.py"
BUNDLED_PYTHON = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "python.exe"

EQUITY_SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "SOXX", "XLK", "XLY"]
MACRO_SYMBOLS = ["US10Y", "US2Y", "VIX"]
DEFAULT_SETTINGS = {
    "input_path": str(PROJECT_DIR / "data" / "latest_signals.json"),
    "symbols": EQUITY_SYMBOLS + MACRO_SYMBOLS,
    "custom_symbols": "",
    "evening_time": "22:00",
    "morning_time": "09:45",
    "alert_start_time": "09:20",
    "alert_interval_minutes": 15,
    "alert_duration_hours": 8,
    "fetch_alpha_vantage": False,
}

BG = "#070707"
SURFACE = "#0f0f0f"
FIELD = "#101010"
FG = "#f4f1ec"
MUTED = "#a7a7a7"
DIM = "#696969"
BORDER = "#3a3a3a"
ACCENT = "#ffffff"
FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Georgia", 19)
FONT_SECTION = ("Georgia", 15)
FONT_MONO = ("Consolas", 9)


def python_path() -> str:
    return str(BUNDLED_PYTHON) if BUNDLED_PYTHON.exists() else "python"


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return {**default, **data}
    except Exception:
        return dict(default)


def save_json(path: Path, data: dict) -> None:
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
    seen: set[str] = set()
    output: list[str] = []

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


def validate_time(value: str) -> bool:
    pieces = value.split(":")
    if len(pieces) != 2:
        return False
    try:
        hour, minute = int(pieces[0]), int(pieces[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


class MarketClient(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Market Risk Alert")
        self.geometry("920x760")
        self.minsize(760, 640)
        self.configure(bg=BG)
        self.option_add("*Font", FONT_BODY)

        self.settings = load_json(CONFIG_PATH, DEFAULT_SETTINGS)
        env = read_env(ENV_PATH)
        if env.get("WATCH_SYMBOLS"):
            self.settings["symbols"] = [item.strip().upper() for item in env["WATCH_SYMBOLS"].split(",") if item.strip()]
        if env.get("QUOTE_SYMBOLS"):
            quote_set = {item.strip().upper() for item in env["QUOTE_SYMBOLS"].split(",") if item.strip()}
            self.settings["custom_symbols"] = ",".join(sorted(quote_set - set(EQUITY_SYMBOLS) - set(MACRO_SYMBOLS)))

        self.symbol_vars: dict[str, tk.BooleanVar] = {}
        self.input_path = tk.StringVar(value=self.settings["input_path"])
        self.custom_symbols = tk.StringVar(value=self.settings["custom_symbols"])
        self.evening_time = tk.StringVar(value=self.settings["evening_time"])
        self.morning_time = tk.StringVar(value=self.settings["morning_time"])
        self.alert_start_time = tk.StringVar(value=self.settings["alert_start_time"])
        self.alert_interval = tk.IntVar(value=int(self.settings["alert_interval_minutes"]))
        self.alert_duration = tk.IntVar(value=int(self.settings["alert_duration_hours"]))
        self.fetch_alpha = tk.BooleanVar(value=bool(self.settings["fetch_alpha_vantage"]))

        self._build()

    def section(self, parent: tk.Widget, title: str, row: int, top: int = 28) -> tk.Frame:
        shell = tk.Frame(parent, bg=BG)
        shell.grid(row=row, column=0, sticky="ew", pady=(top, 0))
        shell.columnconfigure(0, weight=1)
        tk.Label(shell, text=title, bg=BG, fg=FG, font=FONT_SECTION).grid(row=0, column=0, sticky="w")
        tk.Frame(shell, bg=BORDER, width=48, height=1).grid(row=1, column=0, sticky="w", pady=(14, 18))
        content = tk.Frame(shell, bg=BG)
        content.grid(row=2, column=0, sticky="ew")
        content.columnconfigure(1, weight=1)
        return content

    def label(self, parent: tk.Widget, text: str, row: int, column: int = 0, **grid: object) -> tk.Label:
        widget = tk.Label(parent, text=text, bg=BG, fg=FG, font=FONT_BODY)
        widget.grid(row=row, column=column, sticky=grid.pop("sticky", "w"), **grid)
        return widget

    def muted(self, parent: tk.Widget, text: str, row: int, column: int = 0, **grid: object) -> tk.Label:
        widget = tk.Label(parent, text=text, bg=BG, fg=MUTED, font=FONT_SMALL)
        widget.grid(row=row, column=column, sticky=grid.pop("sticky", "w"), **grid)
        return widget

    def entry(self, parent: tk.Widget, variable: tk.Variable, width: int | None = None) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width or 20,
            bg=FIELD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=FONT_BODY,
        )

    def button(self, parent: tk.Widget, text: str, command: object, subtle: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=BG if subtle else SURFACE,
            fg=FG,
            activebackground="#181818",
            activeforeground=FG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=12,
            pady=7,
            cursor="hand2",
            font=FONT_SMALL,
        )

    def check(self, parent: tk.Widget, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=BG,
            fg=FG,
            activebackground=BG,
            activeforeground=FG,
            selectcolor=BG,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=FONT_BODY,
        )

    def _build(self) -> None:
        root = tk.Frame(self, bg=BG, padx=52, pady=34)
        root.pack(anchor="nw", fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(7, weight=1)

        title = tk.Label(root, text="Market Risk Alert", bg=BG, fg=FG, font=FONT_TITLE)
        title.grid(row=0, column=0, sticky="w")
        tk.Frame(root, bg=BORDER, width=48, height=1).grid(row=1, column=0, sticky="w", pady=(18, 24))
        intro = (
            "A quiet local console for selecting watched tickers, triggering Telegram reports, "
            "and scheduling market-risk checks."
        )
        tk.Label(root, text=intro, bg=BG, fg=MUTED, font=FONT_BODY, wraplength=580, justify="left").grid(row=2, column=0, sticky="w")

        self._build_input(root)
        self._build_symbols(root)
        self._build_schedule(root)
        self._build_actions(root)
        self._build_log(root)

    def _build_input(self, root: ttk.Frame) -> None:
        frame = self.section(root, "Data", 3, top=36)
        frame.columnconfigure(1, weight=1)

        self.muted(frame, "Snapshot JSON", 0, 0, padx=(0, 14))
        self.entry(frame, self.input_path).grid(row=0, column=1, sticky="ew")
        self.button(frame, "Browse", self.pick_input, subtle=True).grid(row=0, column=2, padx=(10, 0))
        self.check(frame, "Alpha Vantage quotes", self.fetch_alpha).grid(row=1, column=1, sticky="w", pady=(12, 0))

    def _build_symbols(self, root: ttk.Frame) -> None:
        frame = self.section(root, "Watchlist", 4)

        selected = set(self.settings["symbols"])
        for idx, symbol in enumerate(EQUITY_SYMBOLS + MACRO_SYMBOLS):
            var = tk.BooleanVar(value=symbol in selected)
            self.symbol_vars[symbol] = var
            self.check(frame, symbol, var).grid(row=idx // 5, column=idx % 5, sticky="w", padx=(0, 22), pady=3)

        self.muted(frame, "Custom symbols", 3, 0, pady=(14, 0))
        self.entry(frame, self.custom_symbols, width=46).grid(row=3, column=1, columnspan=4, sticky="ew", pady=(14, 0))

    def _build_schedule(self, root: ttk.Frame) -> None:
        frame = self.section(root, "Schedule", 5)

        self.muted(frame, "Evening recap", 0, 0)
        self.entry(frame, self.evening_time, width=8).grid(row=0, column=1, sticky="w", padx=(14, 30))
        self.muted(frame, "Open advice", 0, 2)
        self.entry(frame, self.morning_time, width=8).grid(row=0, column=3, sticky="w", padx=(14, 0))

        self.muted(frame, "Alert start", 1, 0, pady=(12, 0))
        self.entry(frame, self.alert_start_time, width=8).grid(row=1, column=1, sticky="w", padx=(14, 30), pady=(12, 0))
        self.muted(frame, "Interval", 1, 2, pady=(12, 0))
        tk.Spinbox(
            frame,
            from_=5,
            to=60,
            textvariable=self.alert_interval,
            width=7,
            bg=FIELD,
            fg=FG,
            buttonbackground=SURFACE,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            insertbackground=FG,
            font=FONT_BODY,
        ).grid(row=1, column=3, sticky="w", padx=(14, 30), pady=(12, 0))
        self.muted(frame, "Duration", 1, 4, pady=(12, 0))
        tk.Spinbox(
            frame,
            from_=1,
            to=16,
            textvariable=self.alert_duration,
            width=7,
            bg=FIELD,
            fg=FG,
            buttonbackground=SURFACE,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            insertbackground=FG,
            font=FONT_BODY,
        ).grid(row=1, column=5, sticky="w", padx=(14, 0), pady=(12, 0))

    def _build_actions(self, root: ttk.Frame) -> None:
        frame = self.section(root, "Actions", 6)

        actions = [
            ("Save", self.save_settings),
            ("Evening recap", lambda: self.run_report("evening")),
            ("Open advice", lambda: self.run_report("morning")),
            ("Sample data", self.create_sample_snapshot),
            ("Install reports", self.install_reports),
            ("Install alerts", self.install_alerts),
        ]
        for idx, (label, command) in enumerate(actions):
            self.button(frame, label, command, subtle=idx == 0).grid(row=idx // 3, column=idx % 3, sticky="ew", padx=(0, 10), pady=(0, 10))

    def _build_log(self, root: ttk.Frame) -> None:
        frame = self.section(root, "Output", 7)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.output = tk.Text(
            frame,
            height=11,
            wrap="word",
            bg=BG,
            fg=MUTED,
            insertbackground=FG,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            font=FONT_MONO,
            padx=12,
            pady=10,
        )
        self.output.grid(row=0, column=0, sticky="nsew")
        scroll = tk.Scrollbar(frame, command=self.output.yview, bg=BG, troughcolor=BG, activebackground=SURFACE, relief="flat")
        scroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scroll.set)

    def pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 latest_signals.json",
            initialdir=PROJECT_DIR,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)

    def selected_symbols(self) -> list[str]:
        symbols = [symbol for symbol, var in self.symbol_vars.items() if var.get()]
        custom = [item.strip().upper() for item in self.custom_symbols.get().split(",") if item.strip()]
        return list(dict.fromkeys(symbols + custom))

    def save_settings(self) -> bool:
        for label, value in {
            "晚间复盘": self.evening_time.get(),
            "开盘建议": self.morning_time.get(),
            "盘中报警开始": self.alert_start_time.get(),
        }.items():
            if not validate_time(value):
                messagebox.showerror("时间格式错误", f"{label} 需要 HH:MM 格式")
                return False

        symbols = self.selected_symbols()
        settings = {
            "input_path": self.input_path.get(),
            "symbols": symbols,
            "custom_symbols": self.custom_symbols.get(),
            "evening_time": self.evening_time.get(),
            "morning_time": self.morning_time.get(),
            "alert_start_time": self.alert_start_time.get(),
            "alert_interval_minutes": int(self.alert_interval.get()),
            "alert_duration_hours": int(self.alert_duration.get()),
            "fetch_alpha_vantage": bool(self.fetch_alpha.get()),
        }
        save_json(CONFIG_PATH, settings)

        quote_symbols = [symbol for symbol in symbols if not symbol.startswith("US") and symbol != "VIX"]
        update_env(
            ENV_PATH,
            {
                "WATCH_SYMBOLS": ",".join(symbols),
                "QUOTE_SYMBOLS": ",".join(quote_symbols),
            },
        )
        self.log(f"Saved settings to {CONFIG_PATH}")
        return True

    def create_sample_snapshot(self) -> None:
        sample = PROJECT_DIR / "examples" / "sample_signals.json"
        target = PROJECT_DIR / "data" / "latest_signals.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample, target)
        self.input_path.set(str(target))
        self.log(f"Created sample snapshot at {target}")

    def input_exists_or_warn(self, scheduled: bool = False) -> bool:
        path = Path(self.input_path.get())
        if path.exists():
            return True
        if scheduled:
            messagebox.showerror(
                "缺少数据文件",
                f"定时任务会读取这个文件，但它现在不存在：\n{path}\n\n请先让抓取脚本写入该文件，或点击“生成样例数据”测试。",
            )
            return False
        use_sample = messagebox.askyesno(
            "缺少数据文件",
            f"找不到输入文件：\n{path}\n\n是否用样例数据生成 latest_signals.json 并继续测试？",
        )
        if use_sample:
            self.create_sample_snapshot()
            return True
        return False

    def alpha_key_ok_or_warn(self) -> bool:
        if not self.fetch_alpha.get():
            return True
        key = read_env(ENV_PATH).get("ALPHAVANTAGE_API_KEY", "")
        invalid = not key or "optional" in key.lower() or "replace" in key.lower()
        if invalid:
            messagebox.showerror(
                "缺少 Alpha Vantage API Key",
                "你勾选了 Alpha Vantage 自动补行情，但 .env 里没有真实 ALPHAVANTAGE_API_KEY。\n\n先取消这个勾，或填入真实 key。",
            )
            return False
        return True

    def run_report(self, mode: str) -> None:
        if not self.save_settings():
            return
        if not self.input_exists_or_warn():
            return
        if not self.alpha_key_ok_or_warn():
            return
        args = [
            python_path(),
            str(MARKET_ALERT),
            "--input",
            self.input_path.get(),
            "--report-mode",
            mode,
        ]
        if self.fetch_alpha.get():
            args.append("--fetch-alpha-vantage")
        self.run_command(args)

    def install_reports(self) -> None:
        if not self.save_settings():
            return
        if not self.input_exists_or_warn(scheduled=True):
            return
        if not self.alpha_key_ok_or_warn():
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
            self.input_path.get(),
            "-EveningTime",
            self.evening_time.get(),
            "-MorningTime",
            self.morning_time.get(),
        ]
        if self.fetch_alpha.get():
            args.append("-FetchAlphaVantage")
        self.run_command(args)

    def install_alerts(self) -> None:
        if not self.save_settings():
            return
        if not self.input_exists_or_warn(scheduled=True):
            return
        if not self.alpha_key_ok_or_warn():
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
            self.input_path.get(),
            "-StartTime",
            self.alert_start_time.get(),
            "-IntervalMinutes",
            str(int(self.alert_interval.get())),
            "-DurationHours",
            str(int(self.alert_duration.get())),
        ]
        if self.fetch_alpha.get():
            args.append("-FetchAlphaVantage")
        self.run_command(args)

    def run_command(self, args: list[str]) -> None:
        self.log(f"> {' '.join(args)}")

        def worker() -> None:
            try:
                proc = subprocess.run(
                    args,
                    cwd=PROJECT_DIR,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                )
                output = proc.stdout.strip()
                error = proc.stderr.strip()
                if output:
                    self.log(output)
                if error:
                    self.log(error)
                self.log(f"exit code: {proc.returncode}")
            except Exception as exc:
                self.log(f"ERROR: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def log(self, text: str) -> None:
        def append() -> None:
            self.output.insert("end", text + "\n")
            self.output.see("end")

        self.after(0, append)


if __name__ == "__main__":
    app = MarketClient()
    app.mainloop()
