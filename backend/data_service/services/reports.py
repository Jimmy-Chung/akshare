from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from providers import legacy_market, longbridge
from providers.common import merge_preferred_rows
from providers.market_catalog import GLOBAL_INDEX_ORDER, GLOBAL_MARKET_REGIONS

REPORT_SCHEMA_VERSION = 11
REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")

SESSION_TIMES = {
    "morning": time(hour=9, minute=30),
    "midday": time(hour=12, minute=30),
    "close": time(hour=16, minute=30),
    "us-night": time(hour=22, minute=30),
}

SESSION_LABELS = {
    "morning": "早报 09:30",
    "midday": "午报 12:30",
    "close": "收盘报 16:30",
    "us-night": "夜报 22:30",
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

REPORT_CHART_INDEXES = {
    "CN": [
        {"code": item["code"], "title": f"{item['name']}走势"}
        for item in longbridge.A_INDEX_SYMBOLS
    ],
    "HK": [
        {"code": item["code"], "title": f"{item['name']}走势"}
        for item in longbridge.HK_INDEX_SYMBOLS
    ],
    "US": [
        {"code": item["code"], "title": f"{item['name']}走势"}
        for item in longbridge.US_INDEX_SYMBOLS
    ],
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
            "description": "按区域展示全球主要指数点位与涨跌幅",
        },
        {
            "key": "majorMarkets",
            "title": "主要市场主要指数",
            "description": "仅整理当前时段关注市场的主要指数点位、涨跌额和涨跌幅",
        },
        {
            "key": "chartExports",
            "title": "日报图表附件",
            "description": (
                "只处理 chartExports 列出的主要指数走势图，按 pageUrl 与 exportButtonId 导出"
            ),
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
                (
                    "执行任务前先检查 http://127.0.0.1:5001/api/system/status"
                    " 与 http://127.0.0.1:3005/；若任一服务不可用，从项目根目录"
                    "执行 ./start.sh start，仅补启动缺失服务，并每秒检查一次，"
                    "最多等待 60 秒；两个地址均返回成功后才继续生成日报。"
                    "若仍未就绪，返回脱敏错误并停止，不得虚构日报或附件"
                ),
                "使用 Bearer 凭证调用 generate 接口生成并保存当前时段日报",
                "根据返回 JSON 精简整理中文日报：只写生成时间、覆盖市场、全球指数总览、关注市场主要指数点位/涨跌额/涨跌幅、数据来源",
                "逐项按 pageUrl 与 exportButtonId 处理 chartExports 中的主要指数走势图，不采集或附加热点图",
                (
                    "按 renderMode 和 contentRequirements 验收附件，并确保图片"
                    "尺寸不低于 minimumImageWidth × minimumImageHeight"
                ),
                "保留备用数据源标记，不得将 fallback 数据描述为 Longbridge 数据",
                "在结果中注明数据生成时间及当前时段覆盖的市场",
                "报告不消费热点图、板块状态快照或热点图时间轴数据",
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


def _public_report(report: Dict[str, Any]) -> Dict[str, Any]:
    public = dict(report)
    # Schema 10 reports may still contain the retired private heatmap payload.
    public.pop("_sectorHeatmaps", None)
    public["sectorRankings"] = []
    public["chartExports"] = [
        item
        for item in public.get("chartExports") or []
        if item.get("kind") == "trend"
    ]
    sources = dict(public.get("sources") or {})
    sources["sectorRankings"] = "未采集（报告已与热点图解耦）"
    public["sources"] = sources
    return public


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
    return [
        {
            "key": group["key"],
            "title": group["title"],
            "subtitle": group["subtitle"],
            "indices": [
                rows_by_code[item["code"]]
                for item in group["indices"]  # type: ignore[index]
                if item["code"] in rows_by_code
            ],
        }
        for group in GLOBAL_MARKET_REGIONS
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


def _chart_exports(
    session: str,
    markets: List[str],
    snapshot_id: str,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    page_url = f"/?session={session}&snapshotId={snapshot_id}#report"
    for market in markets:
        for index in REPORT_CHART_INDEXES[market]:
            normalized_code = (
                index["code"].lower().replace(".", "-").strip("-")
            )
            trend_id = f"trend-{normalized_code}"
            result.append({
                "id": f"{session}-{market.lower()}-{trend_id}",
                "kind": "trend",
                "title": index["title"],
                "pageUrl": page_url,
                "chartId": trend_id,
                "exportButtonId": trend_id,
                "captureSelector": f'[data-chart-id="{trend_id}"]',
                "filename": f"{session}-{trend_id}.png",
                "market": market,
                "groupKey": market,
                "indexCode": index["code"],
                "contentRequirements": [
                    "指数名称与代码",
                    "当前点位",
                    "涨跌额与涨跌幅",
                    "带北京时间刻度的分时曲线",
                    "数据更新时间",
                ],
                "renderMode": "index-summary-card",
                "minimumImageWidth": 900,
                "minimumImageHeight": 760,
            })

    return result


def build_report(session: str, _news_digest: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if session not in SESSION_TIMES:
        session = latest_session()
    markets = SESSION_MARKETS[session]
    global_rows, major_rows = _report_indices(markets)
    now = datetime.now(REPORT_TIMEZONE)
    generated_at = now.isoformat()
    snapshot_id = f"{session}-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "session": session,
        "snapshotId": snapshot_id,
        "label": SESSION_LABELS[session],
        "scheduledAt": SESSION_TIMES[session].strftime("%H:%M"),
        "date": now.date().isoformat(),
        "generatedAt": generated_at,
        "markets": markets,
        "marketLabels": [MARKET_LABELS[item] for item in markets],
        "globalOverview": _global_groups(global_rows),
        "majorMarkets": _major_market_indices(major_rows, markets),
        "sectorRankings": [],
        "chartExports": _chart_exports(session, markets, snapshot_id),
        "sources": {
            "globalIndices": "Longbridge 优先，缺失项使用备用公开行情",
            "majorIndices": "Longbridge 优先，缺失项使用备用公开行情",
            "sectorRankings": "未采集（报告已与热点图解耦）",
        },
    }


def _is_current_schema(report: Any) -> bool:
    return (
        isinstance(report, dict)
        and report.get("schemaVersion") == REPORT_SCHEMA_VERSION
        and bool(report.get("snapshotId"))
        and "globalOverview" in report
        and "chartExports" in report
    )


def _is_indices_compatible(report: Any) -> bool:
    return (
        isinstance(report, dict)
        and int(report.get("schemaVersion") or 0) >= 10
        and bool(report.get("snapshotId"))
        and "globalOverview" in report
        and "majorMarkets" in report
        and "chartExports" in report
    )


def get_report_by_snapshot(snapshot_id: str) -> Dict[str, Any]:
    if not snapshot_id:
        return {}
    cache = _read_cache()
    for reports_by_session in cache.values():
        if not isinstance(reports_by_session, dict):
            continue
        for report in reports_by_session.values():
            if _is_indices_compatible(report) and report.get("snapshotId") == snapshot_id:
                return _public_report(report)
    return {}


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
        return _public_report(cached_report)
    report = build_report(session_name, news_digest)
    cached_day[session_name] = report
    cache[day_key] = cached_day
    _write_cache(cache)
    return _public_report(report)


def get_history_report(
    session: str,
    target_date: str,
    news_digest: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not target_date or target_date == datetime.now(REPORT_TIMEZONE).date().isoformat():
        return get_latest_report(session, news_digest)
    report = _read_cache().get(target_date, {}).get(session, {})
    return _public_report(report) if _is_indices_compatible(report) else {}


def get_cached_report(session: str, target_date: str = "") -> Dict[str, Any]:
    session_name = session if session in SESSION_TIMES else latest_session()
    day_key = target_date or datetime.now(REPORT_TIMEZONE).date().isoformat()
    report = (_read_cache().get(day_key) or {}).get(session_name)
    return _public_report(report) if _is_indices_compatible(report) else {}


def get_cached_reports_between(
    start_date: str,
    end_date: str,
) -> List[Dict[str, Any]]:
    """Return every compatible report package in an inclusive date range."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return []
    if start > end:
        return []

    cache = _read_cache()
    result: List[Dict[str, Any]] = []
    for day_key in sorted(cache):
        try:
            day = date.fromisoformat(day_key)
        except ValueError:
            continue
        if day < start or day > end:
            continue
        reports_by_session = cache.get(day_key)
        if not isinstance(reports_by_session, dict):
            continue
        sessions = {
            session_name: _public_report(report)
            for session_name in SESSION_TIMES
            if _is_indices_compatible(
                report := reports_by_session.get(session_name)
            )
        }
        if sessions:
            result.append({"date": day_key, "sessions": sessions})
    return result


def get_recent_reports(days: int = 7) -> List[Dict[str, Any]]:
    """Return close and US-night report packages for recent weekdays."""
    cache = _read_cache()
    today = datetime.now(REPORT_TIMEZONE).date()
    result: List[Dict[str, Any]] = []
    for day_key in sorted(cache, reverse=True):
        try:
            day = datetime.fromisoformat(day_key).date()
        except ValueError:
            continue
        if day > today or (today - day).days >= days or day.weekday() >= 5:
            continue
        reports_by_session = cache.get(day_key)
        if not isinstance(reports_by_session, dict):
            continue
        daily_reports = [
            reports_by_session.get(session_name)
            for session_name in ("close", "us-night")
            if _is_indices_compatible(reports_by_session.get(session_name))
        ]
        if not daily_reports:
            daily_reports = [
                report
                for session_name in ("midday", "morning")
                if _is_indices_compatible(report := reports_by_session.get(session_name))
            ][-1:]
        result.extend(_public_report(report) for report in daily_reports)
    return list(reversed(result))


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
    return _public_report(report)
