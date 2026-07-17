from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from services.heatmap_snapshots import (
    MARKET_TIMEZONES,
    get_heatmap_snapshot,
    list_heatmap_snapshot_dates,
    list_heatmap_snapshot_history,
)
from services.reports import REPORT_TIMEZONE, SESSION_LABELS, get_cached_report
from services.weekly_reports import (
    get_cached_weekly_market_context,
    get_latest_finalized_weekly_market_context,
    weekly_period_for_date,
)

from .schema import MarketQueryError, MarketQueryNotFound, normalize_query_spec


SECTOR_ALIASES = {
    "白酒": "酿酒业",
    "酒类": "酿酒业",
    "酿酒板块": "酿酒业",
}


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_index(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "name", "code", "price", "changeAmount", "changePercent", "open",
            "high", "low", "previousClose", "volume", "turnover", "tradeDate",
            "source", "isFallback",
        )
    }


def _report_query(query: Dict[str, Any]) -> Dict[str, Any]:
    target_date = query["time"]["date"] or datetime.now(REPORT_TIMEZONE).date().isoformat()
    sessions = query["report"]["sessions"]
    reports = []
    for session in sessions:
        report = get_cached_report(session, target_date)
        if not report:
            raise MarketQueryNotFound(f"{target_date} {SESSION_LABELS[session]}没有本地采集数据")
        reports.append({
            "date": report.get("date"),
            "session": session,
            "label": report.get("label") or SESSION_LABELS[session],
            "generatedAt": report.get("generatedAt"),
            "markets": report.get("markets") or [],
            "globalOverview": [
                {
                    "key": group.get("key"),
                    "title": group.get("title"),
                    "indices": [_compact_index(item) for item in group.get("indices") or []],
                }
                for group in report.get("globalOverview") or []
            ],
            "majorMarkets": [
                {
                    "market": group.get("market"),
                    "title": group.get("title"),
                    "indices": [_compact_index(item) for item in group.get("indices") or []],
                }
                for group in report.get("majorMarkets") or []
            ],
            "sources": report.get("sources") or {},
        })
    return {
        "resultType": "report" if len(reports) == 1 else "report_comparison",
        "data": {"reports": reports},
        "meta": {
            "source": "local.session_reports",
            "timezone": str(REPORT_TIMEZONE),
            "status": "complete",
            "warnings": [],
        },
    }


def _weekly_query(query: Dict[str, Any]) -> Dict[str, Any]:
    time_spec = query["time"]
    anchor_value = time_spec["date"] or time_spec["start"]
    requested_latest = not anchor_value
    if requested_latest:
        requested_period = weekly_period_for_date(datetime.now(REPORT_TIMEZONE).date())
        context = get_latest_finalized_weekly_market_context()
        period = context.get("period") or requested_period
    else:
        requested_period = weekly_period_for_date(date.fromisoformat(anchor_value))
        context = get_cached_weekly_market_context(requested_period)
        period = requested_period
    if not context:
        if requested_latest:
            raise MarketQueryNotFound("本地还没有任何已完成的周报数据")
        raise MarketQueryNotFound(f"{period['startDate']} 至 {period['endDate']} 没有本地周线数据")
    rows = {}
    for group in [*(context.get("globalOverview") or []), *(context.get("majorMarkets") or [])]:
        for item in group.get("indices") or []:
            if item.get("code"):
                rows[str(item["code"])] = item
    subjects = query["subjects"]
    selected = list(rows.values())
    if subjects:
        selected = []
        for subject in subjects:
            match = _resolve_named_item(rows.values(), subject, "指数")
            selected.append(match)
    metric = query["options"]["sortMetric"]
    reverse = query["options"]["sortDirection"] != "asc"
    if query["intent"]["operation"] == "rank":
        selected.sort(key=lambda item: _number(item.get(metric)) or float("-inf"), reverse=reverse)
        selected = selected[:query["options"]["limit"]]
    coverage = context.get("coverage") or {}
    warnings = []
    fallback_notice = ""
    if requested_latest and period.get("isoWeek") != requested_period.get("isoWeek"):
        fallback_notice = (
            f"当周周报尚未生成，已为你返回最近一份已完成周报："
            f"{period.get('startDate')} 至 {period.get('endDate')}"
        )
        warnings.append(fallback_notice)
    unavailable_count = int(coverage.get("unavailableIndexCount") or 0)
    if unavailable_count:
        warnings.append(f"有 {unavailable_count} 个目标指数没有本地周线覆盖")
    return {
        "resultType": "weekly_index",
        "resolvedSubjects": [
            {"id": item.get("code"), "name": item.get("name"), "type": "index"}
            for item in selected
        ],
        "data": {"period": context.get("period"), "indices": selected},
        "meta": {
            "source": "local.weekly_reports",
            "timezone": str(REPORT_TIMEZONE),
            "status": "partial" if period.get("isCurrentWeek") else "final",
            "coverage": coverage,
            "warnings": warnings,
            "fallbackNotice": fallback_notice,
        },
    }


def _normalize_name(value: str) -> str:
    return "".join(value.lower().replace("板块", "").split())


def _resolve_named_item(
    items: Iterable[Dict[str, Any]],
    subject: Dict[str, Any],
    label: str,
) -> Dict[str, Any]:
    candidates = list(items)
    subject_id = subject.get("id")
    if subject_id:
        exact = [item for item in candidates if str(item.get("code") or "") == subject_id]
        if len(exact) == 1:
            return exact[0]
    requested_name = str(subject.get("name") or "")
    requested_name = SECTOR_ALIASES.get(requested_name, requested_name)
    normalized = _normalize_name(requested_name)
    exact = [item for item in candidates if _normalize_name(str(item.get("name") or "")) == normalized]
    if len(exact) == 1:
        return exact[0]
    fuzzy = [
        item for item in candidates
        if normalized and (
            normalized in _normalize_name(str(item.get("name") or ""))
            or _normalize_name(str(item.get("name") or "")) in normalized
        )
    ]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if not exact and not fuzzy:
        raise MarketQueryNotFound(f"没有找到{label}“{requested_name or subject_id}”")
    options = [str(item.get("name") or item.get("code")) for item in (exact or fuzzy)[:8]]
    raise MarketQueryError(f"{label}名称存在歧义，请从以下候选中选择：{'、'.join(options)}")


def _sector_rows(snapshot: Dict[str, Any], level: int) -> List[Dict[str, Any]]:
    rows = snapshot.get("groups") if level == 1 else snapshot.get("industries")
    return [item for item in (rows or []) if isinstance(item, dict)]


def _market_date_and_frames(query: Dict[str, Any], market: str) -> tuple[str, List[Dict[str, Any]]]:
    target_date = query["time"]["date"]
    if not target_date:
        target_date = str(list_heatmap_snapshot_dates(market).get("latestDate") or "")
    if not target_date:
        raise MarketQueryNotFound(f"{market} 没有本地板块快照")
    history = list_heatmap_snapshot_history(market, target_date)
    frames = [
        get_heatmap_snapshot(str(item.get("snapshotId") or ""))
        for item in history.get("snapshots") or []
    ]
    frames = [item for item in frames if item]
    if not frames:
        raise MarketQueryNotFound(f"{market} {target_date} 没有可用的定时板块快照")
    return target_date, frames


def _resolve_sector(
    frames: List[Dict[str, Any]],
    subject: Dict[str, Any],
) -> Dict[str, Any]:
    level = int(subject.get("level") or 2)
    unique: Dict[str, Dict[str, Any]] = {}
    for frame in frames:
        for item in _sector_rows(frame, level):
            code = str(item.get("code") or item.get("name") or "")
            unique.setdefault(code, item)
    resolved = _resolve_named_item(unique.values(), subject, f"{level}级板块")
    return {
        "id": str(resolved.get("code") or ""),
        "name": str(resolved.get("name") or ""),
        "market": subject.get("market") or str(frames[0].get("market") or ""),
        "level": level,
        "parentName": str(resolved.get("parentName") or ""),
    }


def _sector_point(frame: Dict[str, Any], resolved: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    item = next(
        (
            row for row in _sector_rows(frame, int(resolved["level"]))
            if str(row.get("code") or "") == resolved["id"]
        ),
        None,
    )
    if not item:
        return None
    return {
        "snapshotId": frame.get("snapshotId"),
        "time": str(frame.get("scheduledAt") or frame.get("capturedAt") or ""),
        "changePercent": _number(item.get("changePercent")),
        "marketValue": _number(item.get("marketValue")),
        "turnover": _number(item.get("turnover")),
    }


def _delta(end: Optional[float], start: Optional[float]) -> Optional[float]:
    return end - start if end is not None and start is not None else None


def _series_summary(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    start = series[0]
    end = series[-1]
    changes = [item["changePercent"] for item in series if item["changePercent"] is not None]
    delta = _delta(end["changePercent"], start["changePercent"])
    direction_changes = 0
    previous_direction = 0
    for current, previous in zip(series[1:], series):
        step = _delta(current["changePercent"], previous["changePercent"])
        direction = 1 if step is not None and step > 0 else -1 if step is not None and step < 0 else 0
        if direction and previous_direction and direction != previous_direction:
            direction_changes += 1
        if direction:
            previous_direction = direction
    return {
        "startChangePercent": start["changePercent"],
        "endChangePercent": end["changePercent"],
        "changePercentDelta": delta,
        "direction": "strengthening" if delta is not None and delta > 0 else "weakening" if delta is not None and delta < 0 else "flat",
        "peakChangePercent": max(changes) if changes else None,
        "troughChangePercent": min(changes) if changes else None,
        "marketValueDelta": _delta(end["marketValue"], start["marketValue"]),
        "turnoverDelta": _delta(end["turnover"], start["turnover"]),
        "directionChangeCount": direction_changes,
    }


def _timeline_for_subject(
    frames: List[Dict[str, Any]],
    resolved: Dict[str, Any],
    include_adjacent: bool,
) -> Dict[str, Any]:
    series = [point for frame in frames if (point := _sector_point(frame, resolved))]
    if not series:
        raise MarketQueryNotFound(f"本地快照中没有板块“{resolved['name']}”")
    if include_adjacent:
        for index, point in enumerate(series):
            point["adjacentChange"] = (
                None if index == 0 else _delta(point["changePercent"], series[index - 1]["changePercent"])
            )
    return {"subject": resolved, "series": series, "summary": _series_summary(series)}


def _find_sector_market(query: Dict[str, Any]) -> str:
    markets = {str(item.get("market") or "") for item in query["subjects"] if item.get("market")}
    if len(markets) == 1:
        return next(iter(markets))
    if len(markets) > 1:
        raise MarketQueryError("一次板块查询只能使用同一个市场")
    matches = []
    for market in ("CN", "HK", "US"):
        try:
            _, frames = _market_date_and_frames(query, market)
            _resolve_sector(frames, query["subjects"][0])
            matches.append(market)
        except MarketQueryError:
            continue
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise MarketQueryNotFound("没有在本地板块数据中找到该实体")
    raise MarketQueryError(f"板块名称跨市场存在歧义，请指定市场：{'、'.join(matches)}")


def _sector_query(query: Dict[str, Any]) -> Dict[str, Any]:
    market = _find_sector_market(query)
    target_date, frames = _market_date_and_frames(query, market)
    operation = query["intent"]["operation"]
    warnings = []
    coverage = frames[-1].get("turnoverCoverage") or {}

    if operation == "rank":
        level = int((query["subjects"] or [{}])[0].get("level") or 2)
        rows = _sector_rows(frames[-1], level)
        parent_name = str((query["subjects"] or [{}])[0].get("parentName") or "")
        if parent_name:
            rows = [item for item in rows if str(item.get("parentName") or "") == parent_name]
        metric = query["options"]["sortMetric"]
        rows = [item for item in rows if _number(item.get(metric)) is not None]
        rows.sort(
            key=lambda item: _number(item.get(metric)) or 0,
            reverse=query["options"]["sortDirection"] != "asc",
        )
        data = {
            "date": target_date,
            "market": market,
            "level": level,
            "metric": metric,
            "items": rows[:query["options"]["limit"]],
        }
        resolved_subjects = []
    else:
        resolved_subjects = [_resolve_sector(frames, item) for item in query["subjects"]]
        timelines = [
            _timeline_for_subject(
                frames,
                subject,
                query["comparison"]["includeAdjacentChanges"],
            )
            for subject in resolved_subjects
        ]
        if any(
            point.get("turnover") is None
            for timeline in timelines
            for point in timeline["series"]
        ):
            warnings.append("部分快照没有该板块的成交额数据；null 不代表零成交额")
        if operation == "snapshot":
            data = {
                "date": target_date,
                "market": market,
                "items": [item["series"][-1] for item in timelines],
            }
        elif operation == "children":
            parent = resolved_subjects[0]
            if parent["level"] != 1:
                raise MarketQueryError("sector.children 的 subject 必须是一级板块")
            data = {
                "date": target_date,
                "market": market,
                "parent": parent,
                "items": [
                    item for item in _sector_rows(frames[-1], 2)
                    if str(item.get("parentName") or "") == parent["name"]
                ],
            }
        else:
            data = {"date": target_date, "market": market, "timelines": timelines}

    if coverage and int(coverage.get("industryCount") or 0) < int(coverage.get("totalIndustryCount") or 0):
        warnings.append("成交额只覆盖部分大市值二级板块；null 不代表零成交额")
    return {
        "resultType": f"sector_{operation}",
        "resolvedSubjects": resolved_subjects,
        "data": data,
        "meta": {
            "source": "local.heatmap_snapshots",
            "timezone": MARKET_TIMEZONES[market],
            "snapshotCount": len(frames),
            "turnoverCoverage": coverage,
            "warnings": list(dict.fromkeys(warnings)),
        },
    }


def execute_market_query(raw_query: Dict[str, Any]) -> Dict[str, Any]:
    query = normalize_query_spec(raw_query)
    domain = query["intent"]["domain"]
    if domain == "report":
        result = _report_query(query)
    elif domain == "weekly_index":
        result = _weekly_query(query)
    else:
        result = _sector_query(query)
    return {"query": query, **result}
