#!/usr/bin/env python3
"""
Professional market risk alert engine.

The script is intentionally dependency-free so it can run from Windows Task
Scheduler or a small VPS without package setup. Feed it your latest snapshot as
JSON, and it will compare professional macro, market, options, filing, company,
and alternative signals against the previous run, score cross-market
confirmation signals, and send Telegram alerts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path("state/last_snapshot.json")
DEFAULT_ARCHIVE_DIR = Path("archive")
DEFAULT_MIN_SCORE = 40
DEFAULT_HIGH_SCORE = 80
DEFAULT_QUOTE_SYMBOLS = ("SPY", "QQQ", "NVDA", "TSLA", "SOXX")
DEFAULT_WATCH_SYMBOLS = ("SPY", "QQQ", "NVDA", "TSLA", "SOXX", "XLK", "XLY", "US10Y", "US2Y", "VIX")


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


@dataclass
class EventScore:
    event_id: str
    title: str
    source: str
    source_tier: str
    value_text: str
    previous_value_text: str | None
    delta_text: str | None
    score: int
    severity: str
    reasons: list[str]
    suggested_action: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pct_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        if not text:
            return None
        number = float(text)
    else:
        number = float(value)
    return number / 100 if number > 1 else number


def numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace("%", "").replace("bps", "").replace("bp", "")
        if not text:
            return None
        return float(text)
    return float(value)


def default_thresholds(unit: str) -> dict[str, float]:
    unit = unit.lower()
    if unit in {"probability_pct", "probability", "pct_point", "percentage_point"}:
        return {"light": 5, "watch": 10, "strong": 15, "major": 20}
    if unit in {"bps", "bp", "basis_points"}:
        return {"light": 4, "watch": 8, "strong": 12, "major": 20}
    if unit in {"percent", "pct", "%"}:
        return {"light": 1, "watch": 3, "strong": 6, "major": 10}
    if unit in {"zscore", "z_score"}:
        return {"light": 1, "watch": 1.5, "strong": 2, "major": 3}
    return {"light": 1, "watch": 2, "strong": 3, "major": 5}


def source_tier_bonus(source_tier: str) -> int:
    tier = source_tier.lower()
    if tier in {"official", "exchange", "primary"}:
        return 12
    if tier in {"market", "options", "company", "filing"}:
        return 10
    if tier in {"professional", "terminal", "broker_research"}:
        return 8
    if tier in {"news", "credible_secondary"}:
        return 4
    if tier in {"alternative", "prediction_market", "polymarket"}:
        return 0
    return 3


def format_value(value: float | None, unit: str) -> str | None:
    if value is None:
        return None
    unit = unit.lower()
    if unit in {"probability_pct", "probability", "pct_point", "percentage_point", "percent", "pct", "%"}:
        return f"{value:.1f}%"
    if unit in {"bps", "bp", "basis_points"}:
        return f"{value:.0f} bps"
    if unit in {"zscore", "z_score"}:
        return f"{value:.2f}σ"
    return f"{value:.2f}"


def get_market_float(market: dict[str, Any], symbol: str, field: str) -> float | None:
    item = market.get(symbol)
    if not isinstance(item, dict):
        return None
    value = item.get(field)
    if value is None:
        return None
    return float(str(value).replace("%", ""))


def fetch_alpha_vantage_quotes(symbols: list[str], api_key: str) -> dict[str, dict[str, float]]:
    quotes: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        query = urllib.parse.urlencode(
            {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": api_key,
            }
        )
        url = f"https://www.alphavantage.co/query?{query}"
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        quote = payload.get("Global Quote", {})
        raw_change = quote.get("10. change percent")
        if raw_change:
            quotes[symbol] = {"change_pct": float(raw_change.replace("%", ""))}

        # Be gentle with free-tier rate limits.
        time.sleep(0.8)
    return quotes


def enrich_market_data(snapshot: dict[str, Any], fetch_alpha: bool) -> None:
    if not fetch_alpha:
        return

    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("Set ALPHAVANTAGE_API_KEY before using --fetch-alpha-vantage")

    symbols = os.getenv("QUOTE_SYMBOLS", ",".join(DEFAULT_QUOTE_SYMBOLS))
    quote_symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    fetched = fetch_alpha_vantage_quotes(quote_symbols, api_key)

    market = snapshot.setdefault("market", {})
    if not isinstance(market, dict):
        raise ValueError("snapshot.market must be an object when --fetch-alpha-vantage is used")

    for symbol, values in fetched.items():
        current = market.setdefault(symbol, {})
        if isinstance(current, dict):
            current.update(values)


def market_confirmations(market: dict[str, Any], tags: set[str]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    spy_change = get_market_float(market, "SPY", "change_pct")
    qqq_change = get_market_float(market, "QQQ", "change_pct")
    if spy_change is not None and qqq_change is not None:
        qqq_vs_spy = qqq_change - spy_change
        if qqq_vs_spy <= -0.8:
            score += 12
            reasons.append(f"QQQ 跑输 SPY {abs(qqq_vs_spy):.1f} pct，科技成长股相对大盘偏弱")
        elif qqq_vs_spy >= 0.8:
            score -= 6
            reasons.append(f"QQQ 跑赢 SPY {qqq_vs_spy:.1f} pct，市场仍愿意承接成长股风险")

    ten_year_bps = get_market_float(market, "US10Y", "change_bps")
    if ten_year_bps is not None:
        if ten_year_bps >= 8:
            score += 12
            reasons.append(f"10Y 美债收益率上行 {ten_year_bps:.0f} bps，高估值成长股会更容易承压")
        elif ten_year_bps <= -8:
            score -= 6
            reasons.append(f"10Y 美债收益率下行 {abs(ten_year_bps):.0f} bps，成长股的利率压力有所缓和")

    vix_change = get_market_float(market, "VIX", "change_pct")
    if vix_change is not None:
        if vix_change >= 8:
            score += 12
            reasons.append(f"VIX 上涨 {vix_change:.1f}%，市场对短线波动的担心上升")
        elif vix_change <= -8:
            score -= 5
            reasons.append(f"VIX 回落 {abs(vix_change):.1f}%，短线避险情绪降温")

    nvda_change = get_market_float(market, "NVDA", "change_pct")
    soxx_change = get_market_float(market, "SOXX", "change_pct")
    if "nvda" in tags and nvda_change is not None and soxx_change is not None:
        spread = nvda_change - soxx_change
        if spread <= -1:
            score += 8
            reasons.append(f"NVDA 跑输 SOXX {abs(spread):.1f} pct，AI 龙头相对半导体板块走弱")
        elif spread >= 1:
            score -= 4
            reasons.append(f"NVDA 跑赢 SOXX {spread:.1f} pct，AI 龙头仍有资金承接")

    tsla_change = get_market_float(market, "TSLA", "change_pct")
    if "tsla" in tags and tsla_change is not None and qqq_change is not None:
        spread = tsla_change - qqq_change
        if spread <= -1.5:
            score += 8
            reasons.append(f"TSLA 跑输 QQQ {abs(spread):.1f} pct，个股情绪弱于科技板块")
        elif spread >= 1.5:
            score -= 4
            reasons.append(f"TSLA 跑赢 QQQ {spread:.1f} pct，事件溢价仍在")

    return score, reasons


def probability_score(delta_pp: float | None, probability: float, category: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if delta_pp is not None:
        absolute_delta = abs(delta_pp)
        if absolute_delta >= 20:
            score += 35
            reasons.append(f"Polymarket 概率单次变化 {delta_pp:+.1f} pct，属于重大异动")
        elif absolute_delta >= 15:
            score += 26
            reasons.append(f"Polymarket 概率变化 {delta_pp:+.1f} pct，风险需要确认")
        elif absolute_delta >= 10:
            score += 18
            reasons.append(f"Polymarket 概率变化 {delta_pp:+.1f} pct，进入观察区")
        elif absolute_delta >= 5:
            score += 8
            reasons.append(f"Polymarket 概率变化 {delta_pp:+.1f} pct，记录为轻微信号")

    if category == "macro" and probability >= 0.65:
        score += 10
        reasons.append("宏观事件概率高于 65%，会影响大盘和成长股的估值环境")
    elif category in {"nvda", "tsla", "ai"} and probability >= 0.6:
        score += 6
        reasons.append("个股/产业事件概率高于 60%，会影响主题溢价")

    return score, reasons


def professional_signal_score(signal: dict[str, Any], previous_signal: dict[str, Any] | None) -> tuple[int, list[str], float | None, float | None, float | None]:
    source = str(signal.get("source") or "Unknown source").strip()
    source_tier = str(signal.get("source_tier") or signal.get("tier") or "market").lower()
    unit = str(signal.get("unit") or "percent").lower()
    category = str(signal.get("category") or "").lower()
    risk_direction = str(signal.get("risk_direction") or "absolute_change").lower()

    value = numeric_value(signal.get("value", signal.get("current")))
    previous_value = numeric_value(signal.get("previous_value", signal.get("previous")))
    if previous_value is None and previous_signal is not None:
        previous_value = numeric_value(previous_signal.get("value", previous_signal.get("current")))

    delta = None
    if value is not None and previous_value is not None:
        delta = value - previous_value

    score = source_tier_bonus(source_tier)
    reasons = [f"{source} 属于 {source_tier} 数据源，优先级高于预测市场"] if source_tier not in {"alternative", "prediction_market", "polymarket"} else [f"{source} 为另类/情绪信号，仅作辅助确认"]

    thresholds = default_thresholds(unit)
    custom_thresholds = signal.get("thresholds")
    if isinstance(custom_thresholds, dict):
        thresholds.update({key: float(value) for key, value in custom_thresholds.items() if key in thresholds})

    if delta is not None:
        risk_delta = abs(delta) if risk_direction == "absolute_change" else delta
        if risk_direction == "lower_is_risk":
            risk_delta = -delta

        absolute_delta = abs(delta)
        if risk_delta >= thresholds["major"]:
            score += 38
            reasons.append(f"核心指标变化 {format_value(delta, unit)}，达到重大异动阈值")
        elif risk_delta >= thresholds["strong"]:
            score += 28
            reasons.append(f"核心指标变化 {format_value(delta, unit)}，达到强信号阈值")
        elif risk_delta >= thresholds["watch"]:
            score += 18
            reasons.append(f"核心指标变化 {format_value(delta, unit)}，进入观察区")
        elif absolute_delta >= thresholds["light"]:
            score += 8
            reasons.append(f"核心指标变化 {format_value(delta, unit)}，记录为轻微信号")

    risk_level = str(signal.get("risk_level") or "").lower()
    if risk_level in {"high", "major", "critical"}:
        score += 18
        reasons.append("信号被上游数据标记为高风险")
    elif risk_level in {"medium", "elevated"}:
        score += 10
        reasons.append("信号被上游数据标记为中等风险")

    if category == "macro":
        score += 8
        reasons.append("利率、通胀或政策信号会直接影响成长股的估值环境")
    elif category in {"options", "volatility"}:
        score += 7
        reasons.append("期权/波动率信号显示市场正在提高下跌保护")
    elif category in {"filing", "company", "earnings"}:
        score += 6
        reasons.append("公司披露/财报信号优先级高于二级市场传闻")

    if source_tier in {"alternative", "prediction_market", "polymarket"}:
        score = min(score, 45)

    return max(0, min(100, score)), reasons, value, previous_value, delta


def event_tags(event: dict[str, Any]) -> set[str]:
    tags = {str(event.get("category", "")).lower()}
    for key in ("tags", "impact"):
        value = event.get(key, [])
        if isinstance(value, str):
            tags.add(value.lower())
        elif isinstance(value, list):
            tags.update(str(item).lower() for item in value)
    return {tag for tag in tags if tag}


def action_for(score: int, tags: set[str]) -> str:
    if score >= DEFAULT_HIGH_SCORE:
        if "macro" in tags:
            return "先降低追高意愿，检查 QQQ/NVDA/TSLA 是否需要保护；重点看 10Y 美债、VIX 与 QQQ/SPY。"
        if "nvda" in tags or "ai" in tags:
            return "核心仓可以保留，但短线要看 NVDA 是否继续强于 SOXX，以及云厂商资本开支是否支撑 AI 主线。"
        if "tsla" in tags:
            return "降低事件交易仓位，等待 FSD/Robotaxi/SpaceX 相关信号获得价格确认。"
        return "降低组合风险暴露，等价格、利率和波动率信号稳定后再提高仓位。"
    if score >= 60:
        return "进入强提醒区，暂不追高；已有仓位可以考虑降低杠杆，或用 QQQ/SPY 保护仓位。"
    if score >= 40:
        return "进入观察区，继续看价格、利率和波动率是否同时指向同一方向。"
    return "仅记录，不需要行动。"


def severity_for(score: int) -> str:
    if score >= 80:
        return "高风险"
    if score >= 60:
        return "中高风险"
    if score >= 40:
        return "观察"
    return "记录"


def score_events(snapshot: dict[str, Any], previous: dict[str, Any]) -> list[EventScore]:
    market = snapshot.get("market", {})
    if not isinstance(market, dict):
        market = {}

    previous_signals = {
        item.get("id"): item
        for item in previous.get("signals", [])
        if isinstance(item, dict) and item.get("id")
    }

    results: list[EventScore] = []
    for signal in snapshot.get("signals", []):
        if not isinstance(signal, dict):
            continue

        event_id = str(signal.get("id") or signal.get("title") or "").strip()
        title = str(signal.get("title") or event_id).strip()
        if not event_id or not title:
            continue

        source = str(signal.get("source") or "Unknown source").strip()
        source_tier = str(signal.get("source_tier") or signal.get("tier") or "market").strip()
        unit = str(signal.get("unit") or "percent")
        tags = event_tags(signal)
        previous_signal = previous_signals.get(event_id)

        score, reasons, value, previous_value, delta = professional_signal_score(signal, previous_signal)
        market_score, market_reasons = market_confirmations(market, tags)
        score = max(0, min(100, score + market_score))
        reasons.extend(market_reasons)

        results.append(
            EventScore(
                event_id=event_id,
                title=title,
                source=source,
                source_tier=source_tier,
                value_text=format_value(value, unit) or "n/a",
                previous_value_text=format_value(previous_value, unit),
                delta_text=format_value(delta, unit),
                score=score,
                severity=severity_for(score),
                reasons=reasons or ["没有达到显著阈值"],
                suggested_action=action_for(score, tags),
            )
        )

    previous_polymarket_events = {
        item.get("id"): item
        for item in previous.get("polymarket", [])
        if isinstance(item, dict) and item.get("id")
    }

    for event in snapshot.get("polymarket", []):
        if not isinstance(event, dict):
            continue

        event_id = str(event.get("id") or event.get("title") or "").strip()
        title = str(event.get("title") or event_id).strip()
        if not event_id or not title:
            continue

        probability = pct_to_float(event.get("probability"))
        if probability is None:
            continue

        previous_probability = pct_to_float(event.get("previous_probability"))
        if previous_probability is None and event_id in previous_polymarket_events:
            previous_probability = pct_to_float(previous_polymarket_events[event_id].get("probability"))

        delta_pp = None
        if previous_probability is not None:
            delta_pp = (probability - previous_probability) * 100

        category = str(event.get("category", "")).lower()
        tags = event_tags(event)
        score, reasons = probability_score(delta_pp, probability, category)
        score = min(score, 35)
        reasons.insert(0, "Polymarket 为另类事件概率信号，仅作辅助，不作为专业报告主结论")
        market_score, market_reasons = market_confirmations(market, tags)
        score = max(0, min(60, score + min(market_score, 25)))
        reasons.extend(market_reasons)

        results.append(
            EventScore(
                event_id=event_id,
                title=title,
                source="Polymarket",
                source_tier="alternative",
                value_text=f"{probability * 100:.1f}%",
                previous_value_text=f"{previous_probability * 100:.1f}%" if previous_probability is not None else None,
                delta_text=f"{delta_pp:+.1f} pct" if delta_pp is not None else None,
                score=score,
                severity=severity_for(score),
                reasons=reasons or ["没有达到显著阈值"],
                suggested_action=action_for(score, tags),
            )
        )

    return sorted(results, key=lambda item: item.score, reverse=True)


def format_alert(results: list[EventScore], min_score: int) -> str:
    triggered = [item for item in results if item.score >= min_score]
    if not triggered:
        top = results[0] if results else None
        if top is None:
            return "市场风险监控：本次没有可评分事件。"
        return (
            "市场风险监控：无提醒触发\n\n"
            f"最高事件：{top.title}\n"
            f"风险分：{top.score}/100 ({top.severity})"
        )

    top = triggered[0]
    lines = [
        f"🚨 市场风险提醒：{top.score}/100（{top.severity}）",
        "",
        f"核心信号：{top.title}",
        f"数据源：{top.source}（{top.source_tier}）",
        f"当前值：{top.value_text}",
    ]
    if top.previous_value_text is not None:
        lines.append(f"上次值：{top.previous_value_text}")
    if top.delta_text is not None:
        lines.append(f"变化：{top.delta_text}")

    lines.extend(["", "主要依据："])
    lines.extend(f"- {reason}" for reason in top.reasons[:5])
    lines.extend(["", f"行动建议：{top.suggested_action}"])

    if len(triggered) > 1:
        lines.extend(["", "其他触发事件："])
        for item in triggered[1:4]:
            lines.append(f"- {item.title}: {item.score}/100，当前值 {item.value_text}，来源 {item.source}")

    return "\n".join(lines)


def format_market_line(symbol: str, data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    pieces = []
    change_pct = data.get("change_pct")
    change_bps = data.get("change_bps")
    price = data.get("price")
    if price is not None:
        pieces.append(f"{float(price):.2f}")
    if change_pct is not None:
        pieces.append(f"{float(str(change_pct).replace('%', '')):+.1f}%")
    if change_bps is not None:
        pieces.append(f"{float(str(change_bps).replace('bps', '').replace('bp', '')):+.0f} bps")
    if not pieces:
        return None
    return f"{symbol}: {' / '.join(pieces)}"


def get_watch_symbols(snapshot: dict[str, Any]) -> tuple[str, ...]:
    raw = snapshot.get("watch_symbols") or os.getenv("WATCH_SYMBOLS")
    if isinstance(raw, list):
        symbols = [str(item).strip().upper() for item in raw if str(item).strip()]
    elif isinstance(raw, str):
        symbols = [item.strip().upper() for item in raw.split(",") if item.strip()]
    else:
        symbols = list(DEFAULT_WATCH_SYMBOLS)
    return tuple(dict.fromkeys(symbols))


def portfolio_bias(results: list[EventScore]) -> str:
    top_score = results[0].score if results else 0
    if top_score >= 80:
        return "防守优先：不要追高，优先检查 QQQ/NVDA/TSLA 是否需要保护。"
    if top_score >= 60:
        return "谨慎偏防守：先观察利率、VIX 与 QQQ/SPY 的方向是否继续恶化。"
    if top_score >= 40:
        return "中性观察：保留核心仓，关注是否出现跨市场共振。"
    return "风险温和：维持计划仓位，避免因单一噪音交易。"


def format_report(snapshot: dict[str, Any], results: list[EventScore], report_mode: str) -> str:
    market = snapshot.get("market", {})
    if not isinstance(market, dict):
        market = {}

    if report_mode == "evening":
        header = "🌙 22:00 每日市场复盘"
        purpose = "当天事件与持仓相关市场变化"
    elif report_mode == "morning":
        header = "☀️ 09:45 开盘后当日建议"
        purpose = "开盘后 15 分钟的组合行动建议"
    else:
        header = "📌 定时市场报告"
        purpose = "组合风险与市场变化"

    lines = [
        header,
        "",
        f"主题：{purpose}",
        f"组合判断：{portfolio_bias(results)}",
    ]

    market_lines = [line for symbol in get_watch_symbols(snapshot) if (line := format_market_line(symbol, market.get(symbol)))]
    if market_lines:
        lines.extend(["", "持仓与市场变化："])
        lines.extend(f"- {line}" for line in market_lines[:10])

    if results:
        lines.extend(["", "主要信号："])
        for item in results[:5]:
            lines.append(f"- {item.title}: {item.score}/100，{item.value_text}，来源 {item.source}")

        lines.extend(["", "判断依据："])
        for reason in results[0].reasons[:4]:
            lines.append(f"- {reason}")

    if report_mode == "morning":
        lines.extend(
            [
                "",
                "当日建议：",
                f"- 大盘/Nasdaq：{action_for(results[0].score if results else 0, {'macro'})}",
                "- NVDA：看 NVDA 是否强于 SOXX。若跑输板块，说明 AI 龙头短线承接不足。",
                "- TSLA：看 TSLA 是否弱于 QQQ/XLY。若继续弱势，不要过早把反弹当成趋势反转。",
            ]
        )
    elif report_mode == "evening":
        lines.extend(
            [
                "",
                "明日检查清单：",
                "- CME/Fed 利率预期、2Y/10Y 美债、VIX 是否延续。",
                "- QQQ vs SPY、NVDA vs SOXX、TSLA vs QQQ 是否出现确认或背离。",
                "- 公司披露、财报指引、期权保护需求是否支持调整仓位。",
            ]
        )

    return "\n".join(lines)


def send_telegram(message: str, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {payload}")


def save_current_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    snapshot = dict(snapshot)
    snapshot["saved_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, snapshot)


def archive_run(snapshot: dict[str, Any], results: list[EventScore], message: str, report_mode: str, archive_dir: Path) -> None:
    now = datetime.now()
    run_dir = archive_dir / now.strftime("%Y") / now.strftime("%m") / now.strftime("%Y-%m-%d")
    stamp = now.strftime("%H%M%S")
    prefix = f"{stamp}-{report_mode}"

    serializable_results = [
        {
            "event_id": item.event_id,
            "title": item.title,
            "source": item.source,
            "source_tier": item.source_tier,
            "value": item.value_text,
            "previous_value": item.previous_value_text,
            "delta": item.delta_text,
            "score": item.score,
            "severity": item.severity,
            "reasons": item.reasons,
            "suggested_action": item.suggested_action,
        }
        for item in results
    ]

    write_json(run_dir / f"{prefix}-snapshot.json", snapshot)
    write_json(run_dir / f"{prefix}-scores.json", {"report_mode": report_mode, "results": serializable_results})
    write_text(run_dir / f"{prefix}-telegram.txt", message)


def main() -> int:
    configure_console_encoding()

    parser = argparse.ArgumentParser(description="Send Telegram alerts for portfolio risk signals.")
    parser.add_argument("--input", type=Path, required=True, help="Path to latest JSON snapshot.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="Path to previous snapshot state.")
    parser.add_argument("--min-score", type=int, default=int(os.getenv("ALERT_MIN_SCORE", DEFAULT_MIN_SCORE)))
    parser.add_argument("--dry-run", action="store_true", help="Print alert instead of sending Telegram message.")
    parser.add_argument("--force", action="store_true", help="Send even if score is below min-score.")
    parser.add_argument("--report-mode", choices=["alert", "evening", "morning"], default="alert", help="Send scheduled reports regardless of thresholds.")
    parser.add_argument("--fetch-alpha-vantage", action="store_true", help="Fill equity change_pct from Alpha Vantage.")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR, help="Folder for snapshot, score, and report archives.")
    parser.add_argument("--no-archive", action="store_true", help="Disable run archive files.")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Optional .env file.")
    args = parser.parse_args()

    load_dotenv(args.env)

    snapshot = read_json(args.input)
    enrich_market_data(snapshot, args.fetch_alpha_vantage)
    previous = read_json(args.state) if args.state.exists() else {}
    results = score_events(snapshot, previous)
    if args.report_mode == "alert":
        min_score = 0 if args.force else args.min_score
        message = format_alert(results, min_score)
        should_send = args.force or any(item.score >= args.min_score for item in results)
    else:
        message = format_report(snapshot, results, args.report_mode)
        should_send = True

    if not args.no_archive:
        archive_run(snapshot, results, message, args.report_mode, args.archive_dir)

    if args.dry_run or not should_send:
        print(message)
    else:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment or .env")
        send_telegram(message, token, chat_id)
        print(f"Telegram alert sent at {int(time.time())}.")

    save_current_snapshot(snapshot, args.state)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
