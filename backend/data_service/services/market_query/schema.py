from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any, Dict


SCHEMA_VERSION = "1.0"
VALID_OPERATIONS = {
    "report": {"get", "compare"},
    "weekly_index": {"get", "compare", "rank"},
    "sector": {"snapshot", "timeline", "compare", "rank", "children"},
}
VALID_MARKETS = {"CN", "HK", "US"}
VALID_SESSIONS = {"morning", "midday", "close", "us-night"}
MAX_QUERY_DAYS = 31
MAX_SUBJECTS = 10


class MarketQueryError(RuntimeError):
    pass


class MarketQueryNotFound(MarketQueryError):
    pass


def _date(value: Any, field: str) -> str:
    if value in {None, ""}:
        return ""
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise MarketQueryError(f"{field} 必须使用 YYYY-MM-DD 格式") from exc


def normalize_query_spec(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise MarketQueryError("query 必须是 JSON 对象")
    query = deepcopy(raw)
    intent = query.get("intent") or {}
    if not isinstance(intent, dict):
        raise MarketQueryError("intent 必须是对象")
    domain = str(intent.get("domain") or "").strip()
    operation = str(intent.get("operation") or "").strip()
    if domain not in VALID_OPERATIONS:
        raise MarketQueryError("intent.domain 只支持 report、weekly_index 或 sector")
    if operation not in VALID_OPERATIONS[domain]:
        raise MarketQueryError(f"{domain} 不支持 operation={operation}")

    subjects = query.get("subjects") or []
    if not isinstance(subjects, list) or len(subjects) > MAX_SUBJECTS:
        raise MarketQueryError(f"subjects 必须是数组且最多 {MAX_SUBJECTS} 项")
    normalized_subjects = []
    for subject in subjects:
        if not isinstance(subject, dict):
            raise MarketQueryError("subjects 中的每一项都必须是对象")
        market = str(subject.get("market") or "").upper()
        if market and market not in VALID_MARKETS:
            raise MarketQueryError(f"不支持的市场：{market}")
        level = subject.get("level")
        if level not in {None, "", 1, 2, "1", "2"}:
            raise MarketQueryError("板块 level 只支持 1 或 2")
        normalized_subjects.append({
            "type": str(subject.get("type") or ("sector" if domain == "sector" else "index")),
            "market": market,
            "level": int(level) if level not in {None, ""} else None,
            "name": str(subject.get("name") or "").strip(),
            "id": str(subject.get("id") or subject.get("code") or "").strip(),
            "parentId": str(subject.get("parentId") or "").strip(),
            "parentName": str(subject.get("parentName") or "").strip(),
        })

    time_spec = query.get("time") or {}
    if not isinstance(time_spec, dict):
        raise MarketQueryError("time 必须是对象")
    start = _date(time_spec.get("start"), "time.start")
    end = _date(time_spec.get("end"), "time.end")
    target_date = _date(time_spec.get("date"), "time.date")
    if start and end:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        if start_date > end_date:
            raise MarketQueryError("time.start 不能晚于 time.end")
        if (end_date - start_date).days > MAX_QUERY_DAYS:
            raise MarketQueryError(f"单次查询范围不能超过 {MAX_QUERY_DAYS} 天")

    report = query.get("report") or {}
    if not isinstance(report, dict):
        raise MarketQueryError("report 必须是对象")
    sessions = report.get("sessions") or []
    if isinstance(sessions, str):
        sessions = [sessions]
    session = str(report.get("session") or "").strip()
    if session:
        sessions = [session]
    if any(item not in VALID_SESSIONS for item in sessions):
        raise MarketQueryError("报告时段只支持 morning、midday、close、us-night")
    if domain == "report" and operation == "get" and len(sessions) != 1:
        raise MarketQueryError("report.get 必须指定一个报告时段")
    if domain == "sector" and not normalized_subjects:
        raise MarketQueryError(f"sector.{operation} 必须指定市场或板块")
    if domain == "sector" and operation in {"timeline", "compare", "snapshot", "children"}:
        if any(not (item["id"] or item["name"]) for item in normalized_subjects):
            raise MarketQueryError(f"sector.{operation} 的每个 subject 都必须指定板块名称或代码")
    if domain == "sector" and operation == "compare" and len(normalized_subjects) < 2:
        raise MarketQueryError("sector.compare 至少需要两个板块")
    if domain == "sector" and operation == "rank" and not normalized_subjects[0]["market"]:
        raise MarketQueryError("sector.rank 必须指定市场")
    if domain == "report" and operation == "compare" and len(sessions) < 2:
        raise MarketQueryError("report.compare 至少需要两个报告时段")

    comparison = query.get("comparison") or {}
    options = query.get("options") or {}
    if not isinstance(comparison, dict) or not isinstance(options, dict):
        raise MarketQueryError("comparison 和 options 必须是对象")
    try:
        limit = min(max(int(options.get("limit") or 20), 1), 100)
    except (TypeError, ValueError) as exc:
        raise MarketQueryError("options.limit 必须是整数") from exc

    return {
        "schemaVersion": SCHEMA_VERSION,
        "intent": {"domain": domain, "operation": operation},
        "subjects": normalized_subjects,
        "time": {
            "kind": str(time_spec.get("kind") or ("range" if start or end else "date")),
            "date": target_date,
            "start": start,
            "end": end,
            "at": str(time_spec.get("at") or "").strip(),
            "timezonePolicy": str(time_spec.get("timezonePolicy") or "market_local"),
        },
        "report": {"session": sessions[0] if len(sessions) == 1 else "", "sessions": sessions},
        "metrics": [str(item) for item in (query.get("metrics") or [])],
        "comparison": {
            "mode": str(comparison.get("mode") or ("first_to_last" if domain == "sector" else "none")),
            "includeAdjacentChanges": bool(comparison.get("includeAdjacentChanges", domain == "sector")),
        },
        "options": {
            "sourcePolicy": "local_only",
            "includeSeries": bool(options.get("includeSeries", operation in {"timeline", "compare"})),
            "includeSummary": bool(options.get("includeSummary", True)),
            "sortMetric": str(options.get("sortMetric") or "changePercent"),
            "sortDirection": str(options.get("sortDirection") or "desc").lower(),
            "limit": limit,
        },
    }
