from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import date, datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any, Dict, List

from providers import legacy_market, longbridge
from providers.market_catalog import GLOBAL_MARKET_REGIONS, flattened_global_indices
from services.reports import MARKET_LABELS, REPORT_TIMEZONE


WEEKLY_MARKET_SCHEMA_VERSION = 2
WEEKLY_CACHE_DIR = Path(__file__).resolve().parents[1] / "runtime_cache" / "weekly_reports"
WEEKLY_READY_TIME = day_time(6, 0)
logger = logging.getLogger(__name__)


class WeeklyReportError(RuntimeError):
    pass


def weekend_generation_anchor(now: datetime | None = None) -> date | None:
    """Return this week's Friday only after every configured market has closed."""
    current = now or datetime.now(REPORT_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=REPORT_TIMEZONE)
    else:
        current = current.astimezone(REPORT_TIMEZONE)
    days_since_friday = (current.weekday() - 4) % 7
    if days_since_friday == 0:
        days_since_friday = 7
    anchor = current.date() - timedelta(days=days_since_friday)
    ready_at = datetime.combine(anchor + timedelta(days=1), WEEKLY_READY_TIME, REPORT_TIMEZONE)
    if ready_at <= current < ready_at + timedelta(days=2):
        return anchor
    return None


def weekly_period_for_date(anchor: date, today: date | None = None) -> Dict[str, Any]:
    current = today or datetime.now(REPORT_TIMEZONE).date()
    start = anchor - timedelta(days=anchor.weekday())
    natural_end = start + timedelta(days=6)
    end = current if start <= current <= natural_end else natural_end
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "anchorDate": anchor.isoformat(),
        "timezone": str(REPORT_TIMEZONE),
        "isCurrentWeek": start <= current <= natural_end,
        "isoWeek": f"{start.isocalendar().year}-W{start.isocalendar().week:02d}",
    }


def _weekly_cache_path(period: Dict[str, Any]) -> Path:
    start = date.fromisoformat(str(period["startDate"]))
    iso = start.isocalendar()
    return WEEKLY_CACHE_DIR / str(iso.year) / f"{iso.year}-W{iso.week:02d}.json"


def save_weekly_market_context(context: Dict[str, Any]) -> Dict[str, Any]:
    path = _weekly_cache_path(context["period"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(context, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return context


def get_cached_weekly_market_context(period: Dict[str, Any]) -> Dict[str, Any]:
    path = _weekly_cache_path(period)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("reportType") != "weekly"
        or payload.get("status") != "final"
        or not bool((payload.get("coverage") or {}).get("complete"))
    ):
        return {}
    return payload


def get_latest_finalized_weekly_market_context() -> Dict[str, Any]:
    """Return the newest complete local weekly packet, never a draft."""
    if not WEEKLY_CACHE_DIR.exists():
        return {}
    for path in sorted(WEEKLY_CACHE_DIR.rglob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("reportType") == "weekly"
            and payload.get("status") == "final"
            and bool((payload.get("coverage") or {}).get("complete"))
        ):
            return payload
    return {}


def capture_weekly_market_context(
    anchor: date,
    now: datetime | None = None,
) -> Dict[str, Any]:
    current = now or datetime.now(REPORT_TIMEZONE)
    expected_anchor = weekend_generation_anchor(current)
    if expected_anchor is None or anchor != expected_anchor:
        raise WeeklyReportError("周报只能在周六 06:00 至周一 06:00（北京时间）生成刚结束的一周")
    period = weekly_period_for_date(anchor, today=anchor)
    period["endDate"] = anchor.isoformat()
    period["isCurrentWeek"] = False
    context = build_weekly_market_context(period)
    coverage = context.get("coverage") or {}
    if not coverage.get("complete"):
        missing = int(coverage.get("unavailableIndexCount") or 0)
        raise WeeklyReportError(f"周报指数尚未完整，仍缺少 {missing} 项；本次不会写入正式数据")
    finalized_at = current.astimezone(REPORT_TIMEZONE).isoformat()
    return save_weekly_market_context({
        **context,
        "status": "final",
        "finalizedAt": finalized_at,
    })


def _major_market_groups(rows_by_code: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    symbols = {
        "CN": longbridge.A_INDEX_SYMBOLS,
        "HK": longbridge.HK_INDEX_SYMBOLS,
        "US": longbridge.US_INDEX_SYMBOLS,
    }
    subtitles = {
        "CN": "A 股主要指数周线",
        "HK": "港股主要指数周线",
        "US": "美股主要指数周线",
    }
    return [
        {
            "market": market,
            "title": f"{MARKET_LABELS[market]}主要指数",
            "subtitle": subtitles[market],
            "indices": [
                rows_by_code[item["code"]]
                for item in market_symbols
                if item["code"] in rows_by_code
            ],
        }
        for market, market_symbols in symbols.items()
    ]


def build_weekly_market_context(period: Dict[str, Any]) -> Dict[str, Any]:
    start = date.fromisoformat(str(period["startDate"]))
    end = date.fromisoformat(str(period["endDate"]))
    primary_rows = longbridge.fetch_weekly_report_indices(start, end)
    primary_codes = {str(item.get("code") or "") for item in primary_rows}
    fallback_catalog = [
        {
            "name": str(item["name"]),
            "code": str(item["code"]),
            "symbol": str(item["tradingview"]),
        }
        for item in flattened_global_indices()
        if item.get("tradingview") and str(item["code"]) not in primary_codes
    ]
    try:
        fallback_rows = legacy_market.fetch_tradingview_weekly_indices(
            fallback_catalog,
            start,
            end,
        )
    except Exception as exc:
        logger.warning("TradingView 周线备用源获取失败: %s", exc)
        fallback_rows = []
    weekly_rows = [*primary_rows]
    merged_codes = set(primary_codes)
    for item in fallback_rows:
        code = str(item.get("code") or "")
        if code and code not in merged_codes:
            weekly_rows.append(item)
            merged_codes.add(code)
    sina_catalog = []
    for item in longbridge.A_INDEX_SYMBOLS:
        if item["code"] in merged_codes:
            continue
        exchange = "sh" if item["code"].endswith(".SH") else "sz"
        sina_catalog.append({
            "name": item["name"],
            "code": item["code"],
            "market": "CN",
            "symbol": f"{exchange}{item['code'].split('.')[0]}",
        })
    for item in longbridge.HK_INDEX_SYMBOLS:
        if item["code"] not in merged_codes:
            sina_catalog.append({
                "name": item["name"],
                "code": item["code"],
                "market": "HK",
                "symbol": item["code"].split(".")[0],
            })
    try:
        sina_rows = legacy_market.fetch_sina_weekly_indices(sina_catalog, start, end)
    except Exception as exc:
        logger.warning("新浪周线备用源获取失败: %s", exc)
        sina_rows = []
    for item in sina_rows:
        code = str(item.get("code") or "")
        if code and code not in merged_codes:
            weekly_rows.append(item)
            merged_codes.add(code)
    rows_by_code = {
        str(item["code"]): {
            **item,
            "isPartial": bool(period.get("isCurrentWeek")) and end.weekday() < 5,
        }
        for item in weekly_rows
        if item.get("code")
    }

    global_overview = []
    unavailable_indices: List[Dict[str, str]] = []
    for region in GLOBAL_MARKET_REGIONS:
        indices = []
        for item in region["indices"]:  # type: ignore[index]
            row = rows_by_code.get(str(item["code"]))
            if row:
                indices.append(row)
            else:
                unavailable_indices.append({
                    "name": str(item["name"]),
                    "code": str(item["code"]),
                    "scope": "globalOverview",
                    "reason": (
                        "Longbridge and the configured weekly fallback were unavailable"
                    ),
                })
        global_overview.append({
            "key": region["key"],
            "title": region["title"],
            "subtitle": region["subtitle"],
            "indices": indices,
        })

    major_markets = _major_market_groups(rows_by_code)
    requested_codes = {
        str(item["code"])
        for region in GLOBAL_MARKET_REGIONS
        for item in region["indices"]  # type: ignore[index]
    } | {
        item["code"]
        for item in [
            *longbridge.A_INDEX_SYMBOLS,
            *longbridge.HK_INDEX_SYMBOLS,
            *longbridge.US_INDEX_SYMBOLS,
        ]
    }
    unavailable_codes = {
        item["code"]
        for item in unavailable_indices
    }
    requested_items = {
        item["code"]: item
        for item in [
            *longbridge.A_INDEX_SYMBOLS,
            *longbridge.HK_INDEX_SYMBOLS,
            *longbridge.US_INDEX_SYMBOLS,
        ]
    }
    for code in sorted(requested_codes - set(rows_by_code) - unavailable_codes):
        item = requested_items.get(code, {"name": code})
        unavailable_indices.append({
            "name": str(item["name"]),
            "code": code,
            "scope": "majorMarkets",
            "reason": "Longbridge weekly candle was unavailable",
        })
    source_counts = Counter(str(item.get("source") or "Unknown") for item in weekly_rows)
    return {
        "schemaVersion": WEEKLY_MARKET_SCHEMA_VERSION,
        "reportType": "weekly",
        "status": "draft",
        "period": period,
        "generatedAt": datetime.now(REPORT_TIMEZONE).isoformat(),
        "sourcePolicy": {
            "mode": "preferred-weekly-candlestick-with-fallback",
            "primary": "Longbridge",
            "fallback": ["TradingView", "Sina"],
            "changeDefinition": "current weekly close versus previous weekly close",
        },
        "coverage": {
            "requestedIndexCount": len(requested_codes),
            "availableIndexCount": len(rows_by_code),
            "unavailableIndexCount": len(requested_codes - set(rows_by_code)),
            "sourceCounts": dict(source_counts),
            "unavailableIndices": unavailable_indices,
            "complete": requested_codes.issubset(rows_by_code),
        },
        "globalOverview": global_overview,
        "majorMarkets": major_markets,
    }
