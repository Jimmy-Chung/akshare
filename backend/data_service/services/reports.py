from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from providers import legacy_market, longbridge
from providers.common import merge_preferred_rows
from providers.market_catalog import GLOBAL_INDEX_ORDER, GLOBAL_MARKET_REGIONS

REPORT_SCHEMA_VERSION = 10
REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
REPORT_HEATMAPS_KEY = "_sectorHeatmaps"

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

REPORT_CHART_INDEXES = {
    "CN": {
        "groupKey": "CN",
        "code": "000001.SH",
        "title": "上证指数走势",
    },
    "HK": {
        "groupKey": "HK",
        "code": "HSI.HK",
        "title": "恒生指数走势",
    },
    "US": {
        "groupKey": "US",
        "code": ".SPX.US",
        "title": "标普 500 指数走势",
    },
}

CACHE_DIR = Path(__file__).resolve().parents[1] / "runtime_cache"
CACHE_FILE = CACHE_DIR / "session_reports.json"


class ReportGenerationError(RuntimeError):
    pass


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
            "key": "majorMarkets",
            "title": "主要市场主要指数",
            "description": "仅整理当前时段关注市场的主要指数点位、涨跌额和涨跌幅",
        },
        {
            "key": "chartExports",
            "title": "日报图表附件",
            "description": (
                "只处理 chartExports 列出的图表；按 pageUrl 打开日报页面，"
                "使用 exportButtonId 导出主要指数走势图 PNG 与触发时点静态热力图 PNG"
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
                "根据返回 JSON 精简整理中文日报：只写生成时间、覆盖市场、关注市场主要指数点位/涨跌额/涨跌幅、数据来源",
                (
                    "逐项处理 chartExports 中的图表：打开 pageUrl，等待 data-chart-id"
                    " 对应图表完成渲染，点击 data-export-chart-id 等于 exportButtonId"
                    " 的按钮导出 PNG，并将图片附在日报末尾；若下载文件不可访问，"
                    "则按 captureSelector 精确截取图表区域作为同名 PNG 附件"
                ),
                (
                    "按 renderMode 和 contentRequirements 验收附件，并确保图片"
                    "尺寸不低于 minimumImageWidth × minimumImageHeight；"
                    "renderMode=full-market-hierarchy 的热力图必须是触发时点静态 PNG，"
                    "不得合成视频、启动 watcher 或用错误市场图片替代"
                ),
                "保留备用数据源标记，不得将 fallback 数据描述为 Longbridge 数据",
                "在结果中注明数据生成时间及当前时段覆盖的市场",
                "在日报末尾附上热点图播放入口：https://workspace-akshare.jimmy-jam.com/#heatmap，供用户查看各市场从开盘到当前的热点图变化",
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
    return {
        key: value
        for key, value in report.items()
        if key != REPORT_HEATMAPS_KEY
    }


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
            "dayLeader": {
                "name": str((item.get("dayLeader") or {}).get("name") or ""),
                "code": str((item.get("dayLeader") or {}).get("code") or ""),
                "price": (item.get("dayLeader") or {}).get("price"),
                "changePercent": float(
                    (item.get("dayLeader") or {}).get("changePercent") or 0
                ),
            },
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


def _build_heatmap_snapshot(
    market: str,
    payload: Dict[str, Any],
    generated_at: str,
) -> Dict[str, Any]:
    return {
        "market": market,
        "source": str(payload.get("source") or "Longbridge"),
        "updatedAt": str(payload.get("updatedAt") or generated_at),
        "groups": payload.get("groups") or [],
        "industries": payload.get("industries") or [],
    }


def _has_heatmap_content(snapshot: Dict[str, Any]) -> bool:
    return bool(snapshot.get("groups")) and bool(snapshot.get("industries"))


def _sector_heatmaps(
    markets: List[str],
    generated_at: str,
) -> Dict[str, Dict[str, Any]]:
    def _fetch_market_heatmap(market: str) -> tuple[str, Dict[str, Any]]:
        payload = longbridge.fetch_industry_heatmap(
            market,
            include_stocks=False,
        )
        snapshot = _build_heatmap_snapshot(market, payload, generated_at)
        if not _has_heatmap_content(snapshot):
            longbridge.INDUSTRY_HEATMAP_CACHE.pop(market.upper(), None)
            payload = longbridge.fetch_industry_heatmap(
                market,
                include_stocks=False,
            )
            snapshot = _build_heatmap_snapshot(market, payload, generated_at)
        if not _has_heatmap_content(snapshot):
            label = MARKET_LABELS.get(market, market)
            raise ReportGenerationError(f"{label}行业热力图数据为空")
        return market, snapshot

    with ThreadPoolExecutor(max_workers=max(1, len(markets))) as executor:
        return dict(executor.map(_fetch_market_heatmap, markets))


def _sector_rankings(
    markets: List[str],
    heatmaps: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for market in markets:
        payload = heatmaps.get(market, {})
        result.append({
            "market": market,
            "title": f"{MARKET_LABELS[market]}板块涨跌幅前三",
            "source": "Longbridge",
            "primary": _rank_rows(payload.get("groups") or []),
            "secondary": _rank_rows(payload.get("industries") or []),
        })
    return result


def _chart_exports(
    session: str,
    markets: List[str],
    snapshot_id: str,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    page_url = f"/?session={session}&snapshotId={snapshot_id}#report"
    for market in markets:
        index = REPORT_CHART_INDEXES[market]
        normalized_code = (
            index["code"].lower().replace(".", "-").strip("-")
        )
        trend_id = f"trend-{normalized_code}"
        result.append({
            "id": f"{session}-{market.lower()}-trend",
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

        heatmap_id = f"heatmap-{market.lower()}"
        result.append({
            "id": f"{session}-{market.lower()}-heatmap",
            "kind": "heatmap",
            "title": f"{MARKET_LABELS[market]}板块热力图",
            "pageUrl": page_url,
            "chartId": heatmap_id,
            "exportButtonId": heatmap_id,
            "captureSelector": f'[data-chart-id="{heatmap_id}"]',
            "filename": f"{session}-{heatmap_id}.png",
            "market": market,
            "contentRequirements": [
                "市场名称",
                "当前触发时点该市场全部一级行业和全部二级行业",
                "一级行业名称与综合涨跌幅",
                "二级行业名称与涨跌幅",
                "红涨绿跌图例",
                "页脚明确显示一级行业总数和二级行业总数",
                "数据更新时间",
            ],
            "renderMode": "full-market-hierarchy",
            "minimumImageWidth": 3000,
            "minimumImageHeight": 2600,
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
    heatmaps = _sector_heatmaps(markets, generated_at)
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
        "sectorRankings": _sector_rankings(markets, heatmaps),
        "chartExports": _chart_exports(session, markets, snapshot_id),
        "sources": {
            "globalIndices": "Longbridge 优先，缺失项使用备用公开行情",
            "majorIndices": "Longbridge 优先，缺失项使用备用公开行情",
            "sectorRankings": "Longbridge OpenAPI 行业排行",
        },
        REPORT_HEATMAPS_KEY: heatmaps,
    }


def _is_current_schema(report: Any) -> bool:
    return (
        isinstance(report, dict)
        and report.get("schemaVersion") == REPORT_SCHEMA_VERSION
        and bool(report.get("snapshotId"))
        and "globalOverview" in report
        and "sectorRankings" in report
        and "chartExports" in report
        and REPORT_HEATMAPS_KEY in report
    )


def get_report_by_snapshot(snapshot_id: str) -> Dict[str, Any]:
    if not snapshot_id:
        return {}
    cache = _read_cache()
    for reports_by_session in cache.values():
        if not isinstance(reports_by_session, dict):
            continue
        for report in reports_by_session.values():
            if _is_current_schema(report) and report.get("snapshotId") == snapshot_id:
                return _public_report(report)
    return {}


def get_report_heatmap_snapshot(snapshot_id: str, market: str) -> Dict[str, Any]:
    if not snapshot_id:
        return {}
    normalized_market = market.upper()
    cache = _read_cache()
    for reports_by_session in cache.values():
        if not isinstance(reports_by_session, dict):
            continue
        for report in reports_by_session.values():
            if not _is_current_schema(report):
                continue
            if report.get("snapshotId") != snapshot_id:
                continue
            heatmaps = report.get(REPORT_HEATMAPS_KEY) or {}
            snapshot = heatmaps.get(normalized_market)
            return snapshot if isinstance(snapshot, dict) else {}
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
    return _public_report(report) if _is_current_schema(report) else {}


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
