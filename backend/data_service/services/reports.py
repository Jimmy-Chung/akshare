from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from providers import legacy_market, longbridge
from providers.common import merge_preferred_rows
from providers.market_catalog import GLOBAL_INDEX_ORDER, GLOBAL_MARKET_REGIONS

REPORT_SCHEMA_VERSION = 4
REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")

SESSION_TIMES = {
    "morning": time(hour=9, minute=30),
    "midday": time(hour=12, minute=30),
    "close": time(hour=16, minute=30),
    "us-night": time(hour=22, minute=30),
}

SESSION_LABELS = {
    "morning": "早盘 09:30",
    "midday": "午盘 12:30",
    "close": "收盘 16:30",
    "us-night": "美股夜盘 22:30",
}

SESSION_MARKETS = {
    "morning": ["US", "CN", "HK"],
    "midday": ["CN", "HK"],
    "close": ["CN", "HK"],
    "us-night": ["US"],
}

MARKET_LABELS = {
    "CN": "A 股",
    "HK": "港股",
    "US": "美股",
}

CACHE_DIR = Path(__file__).resolve().parents[1] / "runtime_cache"
CACHE_FILE = CACHE_DIR / "session_reports.json"


def latest_session(now: Optional[datetime] = None) -> str:
    current = (now or datetime.now(REPORT_TIMEZONE)).time()
    if current >= SESSION_TIMES["us-night"]:
        return "us-night"
    if current >= SESSION_TIMES["close"]:
        return "close"
    if current >= SESSION_TIMES["midday"]:
        return "midday"
    return "morning"


def report_schedule() -> List[Dict[str, Any]]:
    return [
        {
            "session": session,
            "label": SESSION_LABELS[session],
            "time": SESSION_TIMES[session].strftime("%H:%M"),
            "markets": SESSION_MARKETS[session],
            "marketLabels": [MARKET_LABELS[item] for item in SESSION_MARKETS[session]],
        }
        for session in ("morning", "midday", "close", "us-night")
    ]


def report_automation_config(api_base_url: str) -> Dict[str, Any]:
    base_url = api_base_url.rstrip("/")
    sections = [
        {
            "key": "globalOverview",
            "title": "全球指数总览",
            "description": "亚太、欧洲、美国主要指数",
        },
        {
            "key": "majorMarkets",
            "title": "主要市场主要指数",
            "description": "仅整理当前时段定义的主要市场",
        },
        {
            "key": "sectorRankings",
            "title": "主要市场板块涨跌幅前三",
            "description": "分别整理一级分类与二级行业的领涨、领跌前三",
        },
    ]
    jobs = []
    for item in report_schedule():
        session = item["session"]
        jobs.append({
            "id": f"market-report-{session}",
            "name": item["label"],
            "enabled": True,
            "schedule": {
                "timezone": "Asia/Shanghai",
                "localTime": item["time"],
                "days": [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                ],
            },
            "markets": item["markets"],
            "marketLabels": item["marketLabels"],
            "requests": {
                "generate": {
                    "method": "POST",
                    "url": (
                        f"{base_url}/api/codex/reports/generate"
                        f"?session={session}"
                    ),
                },
                "latest": {
                    "method": "GET",
                    "url": (
                        f"{base_url}/api/codex/reports/latest"
                        f"?session={session}"
                    ),
                },
            },
            "workflow": [
                "使用 Bearer 凭证调用 generate 接口生成并保存当前时段日报",
                "根据返回 JSON 的三个 sections 整理中文日报",
                "保留备用数据源标记，不得将 fallback 数据描述为 Longbridge 数据",
                "在结果中注明数据生成时间及当前时段覆盖的市场",
            ],
        })
    return {
        "schemaVersion": 1,
        "kind": "codex-market-report-automation",
        "timezone": "Asia/Shanghai",
        "authentication": {
            "type": "bearer",
            "header": "Authorization",
            "tokenEnvironmentVariable": "CODEX_REPORT_API_TOKEN",
            "sendAs": "Bearer ${CODEX_REPORT_API_TOKEN}",
            "redactFromOutput": True,
        },
        "output": {
            "language": "zh-CN",
            "format": "markdown",
            "sections": sections,
        },
        "jobs": jobs,
    }


def _ensure_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _read_cache() -> Dict[str, Any]:
    _ensure_cache()
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(payload: Dict[str, Any]) -> None:
    _ensure_cache()
    CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _report_indices(
    markets: List[str],
) -> tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        longbridge_future = executor.submit(longbridge.fetch_report_indices, markets)
        fallback_future = executor.submit(legacy_market.fetch_global_indices)
        longbridge_rows = longbridge_future.result()
        fallback_rows = fallback_future.result()

    global_rows = merge_preferred_rows(
        [item for item in longbridge_rows if item.get("code") in GLOBAL_INDEX_ORDER],
        fallback_rows,
        GLOBAL_INDEX_ORDER,
    )
    major_symbols = {
        "CN": longbridge.A_INDEX_SYMBOLS,
        "HK": longbridge.HK_INDEX_SYMBOLS,
        "US": longbridge.US_INDEX_SYMBOLS,
    }
    major_rows = {
        market: merge_preferred_rows(
            longbridge_rows,
            fallback_rows,
            [item["code"] for item in symbols],
        )
        for market, symbols in major_symbols.items()
    }
    return global_rows, major_rows


def _global_groups(global_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows_by_code = {
        str(item.get("code")): item
        for item in global_rows
        if item.get("code")
    }
    catalog_groups = {
        str(group["key"]): [
            rows_by_code[item["code"]]
            for item in group["indices"]  # type: ignore[index]
            if item["code"] in rows_by_code
        ]
        for group in GLOBAL_MARKET_REGIONS
    }
    us_codes = {".DJI.US", ".SPX.US", ".IXIC.US"}
    return [
        {
            "key": "asiaPacific",
            "title": "亚太",
            "subtitle": "大中华区、日韩、东南亚及澳洲主要指数",
            "indices": catalog_groups.get("asiaPacific", []),
        },
        {
            "key": "europe",
            "title": "欧洲",
            "subtitle": "英国、德国、法国及欧元区主要指数",
            "indices": catalog_groups.get("europe", []),
        },
        {
            "key": "us",
            "title": "美国",
            "subtitle": "道琼斯、标普 500 与纳斯达克",
            "indices": [
                item
                for item in catalog_groups.get("americas", [])
                if item.get("code") in us_codes
            ],
        },
    ]


def _major_market_indices(
    major_rows: Dict[str, List[Dict[str, Any]]],
    markets: List[str],
) -> List[Dict[str, Any]]:
    subtitles = {
        "CN": "上证、深成指、创业板及主要宽基指数",
        "HK": "恒生指数、恒生科技及国企指数",
        "US": "道琼斯、标普 500 与纳斯达克",
    }
    return [
        {
            "market": market,
            "title": f"{MARKET_LABELS[market]}主要指数",
            "subtitle": subtitles[market],
            "indices": major_rows[market],
        }
        for market in markets
    ]


def _rank_rows(
    rows: List[Dict[str, Any]],
    count: int = 3,
) -> Dict[str, List[Dict[str, Any]]]:
    cleaned = [
        {
            "name": str(item.get("name") or ""),
            "code": str(item.get("code") or ""),
            "parentName": str(item.get("parentName") or ""),
            "changePercent": float(item.get("changePercent") or 0),
            "marketValue": float(item.get("marketValue") or 0),
            "source": "Longbridge",
        }
        for item in rows
        if item.get("name")
    ]
    descending = sorted(cleaned, key=lambda item: item["changePercent"], reverse=True)
    ascending = sorted(cleaned, key=lambda item: item["changePercent"])
    return {
        "leaders": descending[:count],
        "laggards": ascending[:count],
    }


def _sector_rankings(markets: List[str]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for market in markets:
        payload = longbridge.fetch_industry_heatmap(
            market,
            include_stocks=False,
        )
        result.append({
            "market": market,
            "title": f"{MARKET_LABELS[market]}板块涨跌幅前三",
            "source": "Longbridge",
            "primary": _rank_rows(payload.get("groups") or []),
            "secondary": _rank_rows(payload.get("industries") or []),
        })
    return result


def build_report(session: str, _news_digest: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if session not in SESSION_TIMES:
        session = latest_session()
    markets = SESSION_MARKETS[session]
    global_rows, major_rows = _report_indices(markets)
    now = datetime.now(REPORT_TIMEZONE)
    generated_at = now.isoformat()
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "session": session,
        "label": SESSION_LABELS[session],
        "scheduledAt": SESSION_TIMES[session].strftime("%H:%M"),
        "date": now.date().isoformat(),
        "generatedAt": generated_at,
        "markets": markets,
        "marketLabels": [MARKET_LABELS[item] for item in markets],
        "globalOverview": _global_groups(global_rows),
        "majorMarkets": _major_market_indices(major_rows, markets),
        "sectorRankings": _sector_rankings(markets),
        "sources": {
            "globalIndices": "Longbridge 优先，缺失项使用备用公开行情",
            "majorIndices": "Longbridge 优先，缺失项使用备用公开行情",
            "sectorRankings": "Longbridge OpenAPI 行业排行",
        },
    }


def _is_current_schema(report: Any) -> bool:
    return (
        isinstance(report, dict)
        and report.get("schemaVersion") == REPORT_SCHEMA_VERSION
        and "globalOverview" in report
        and "sectorRankings" in report
    )


def get_latest_report(
    session: Optional[str],
    news_digest: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    session_name = session if session in SESSION_TIMES else latest_session()
    cache = _read_cache()
    day_key = datetime.now(REPORT_TIMEZONE).date().isoformat()
    cached_day = cache.get(day_key, {})
    cached_report = cached_day.get(session_name)
    if _is_current_schema(cached_report):
        return cached_report
    report = build_report(session_name, news_digest)
    cached_day[session_name] = report
    cache[day_key] = cached_day
    _write_cache(cache)
    return report


def get_history_report(
    session: str,
    target_date: str,
    news_digest: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not target_date or target_date == datetime.now(REPORT_TIMEZONE).date().isoformat():
        return get_latest_report(session, news_digest)
    report = _read_cache().get(target_date, {}).get(session, {})
    return report if _is_current_schema(report) else {}


def regenerate_report(
    session: str,
    news_digest: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    session_name = session if session in SESSION_TIMES else latest_session()
    cache = _read_cache()
    day_key = datetime.now(REPORT_TIMEZONE).date().isoformat()
    report = build_report(session_name, news_digest)
    cached_day = cache.get(day_key, {})
    cached_day[session_name] = report
    cache[day_key] = cached_day
    _write_cache(cache)
    return report
