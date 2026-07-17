from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from services.reports import (
    REPORT_TIMEZONE,
    SESSION_LABELS,
    SESSION_TIMES,
    get_cached_report,
    latest_session,
)
from services.market_query import execute_market_query, normalize_query_spec
from services.weekly_reports import (
    get_cached_weekly_market_context,
    get_latest_finalized_weekly_market_context,
)


class AssistantConfigurationError(RuntimeError):
    pass


class AssistantProviderError(RuntimeError):
    pass


PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "deepseek": {
        "name": "DeepSeek",
        "apiBase": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "keyEnvironment": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "name": "OpenAI",
        "apiBase": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "keyEnvironment": "OPENAI_API_KEY",
    },
    "custom": {
        "name": "OpenAI-compatible",
        "apiBase": "",
        "model": "",
        "keyEnvironment": "AI_ASSISTANT_API_KEY",
    },
}

DEEPSEEK_MODEL_ALIASES = {
    "deepseek-4-pro": "deepseek-v4-pro",
    "deepseek-4-flash": "deepseek-v4-flash",
}


DAILY_FORMAT = """# 市场日报｜日期与时点
> 数据覆盖、生成时间与有效市场

## 一句话结论
## 全球市场概览
## 重点市场表现
## 重点市场主要指数
## 下一时段观察
## 数据来源与缺口
"""

WEEKLY_FORMAT = """# 市场周报｜起止日期
> 券商周线覆盖范围、指数数量与数据缺口

## 本周一句话结论
## 全球市场周度表现
## A 股 / 港股 / 美股复盘
## A 股 / 港股 / 美股主要指数演变
## 下周观察清单
## 数据来源与缺口
"""

def provider_catalog() -> Dict[str, Any]:
    provider_id = "deepseek"
    preset = PROVIDER_PRESETS[provider_id]
    return {
        "defaultProvider": provider_id,
        "providers": [{
            "id": provider_id,
            "name": preset["name"],
            "apiBase": "",
            "model": _normalize_model(
                provider_id,
                _environment_value(provider_id, "MODEL") or preset["model"],
            ),
            "configured": bool(_environment_key(provider_id)),
            "editableEndpoint": False,
        }],
    }


def _environment_value(provider_id: str, suffix: str) -> str:
    if provider_id == "deepseek":
        return os.getenv(f"DEEPSEEK_{suffix}", "").strip()
    if provider_id == "openai":
        return os.getenv(f"OPENAI_{suffix}", "").strip()
    return os.getenv(f"AI_ASSISTANT_{suffix}", "").strip()


def _environment_key(provider_id: str) -> str:
    key_name = PROVIDER_PRESETS[provider_id]["keyEnvironment"]
    return os.getenv(key_name, "").strip()


def _normalize_model(provider_id: str, model: str) -> str:
    normalized = model.strip()
    if provider_id == "deepseek":
        return DEEPSEEK_MODEL_ALIASES.get(normalized.lower(), normalized)
    return normalized


def _provider_error_detail(response: Any) -> str:
    if response is None:
        return ""
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.JSONDecodeError):
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        detail = error.get("message") or error.get("type")
    else:
        detail = error
    if not isinstance(detail, str):
        return ""
    return " ".join(detail.split())[:240]


def _report_type(message: str) -> str:
    return "weekly" if "周报" in message else "daily"


def _report_session(payload: Dict[str, Any], message: str) -> str:
    requested = str(payload.get("session") or "").strip()
    if requested in SESSION_TIMES:
        return requested
    keyword_sessions = (
        ("夜报", "us-night"),
        ("晚报", "us-night"),
        ("收盘", "close"),
        ("午报", "midday"),
        ("早报", "morning"),
    )
    for keyword, session in keyword_sessions:
        if keyword in message:
            return session
    return latest_session()


def _has_explicit_report_session(payload: Dict[str, Any], message: str) -> bool:
    requested = str(payload.get("session") or "").strip()
    if requested in SESSION_TIMES:
        return True
    return any(keyword in message for keyword in ("夜报", "晚报", "收盘", "午报", "早报"))


def _validated_report_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise AssistantConfigurationError("无法识别报告日期，请使用如“2026-07-15”或“7月15日”的格式") from exc


def _report_date(message: str, now: datetime | None = None) -> str:
    current = now or datetime.now(REPORT_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=REPORT_TIMEZONE)
    today = current.astimezone(REPORT_TIMEZONE).date()
    if "前天" in message:
        return (today - timedelta(days=2)).isoformat()
    if "昨天" in message or "昨日" in message:
        return (today - timedelta(days=1)).isoformat()
    if "今天" in message or "今日" in message:
        return today.isoformat()

    full_patterns = (
        r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
        r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?",
    )
    for pattern in full_patterns:
        match = re.search(pattern, message)
        if match:
            return _validated_report_date(*(int(value) for value in match.groups()))

    month_day = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", message)
    if not month_day:
        month_day = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", message)
    if month_day:
        month, day = (int(value) for value in month_day.groups())
        candidate = date.fromisoformat(_validated_report_date(today.year, month, day))
        if candidate > today:
            candidate = date.fromisoformat(_validated_report_date(today.year - 1, month, day))
        return candidate.isoformat()
    return ""


def _weekly_period(
    message: str,
    target_date: str = "",
    now: datetime | None = None,
) -> Dict[str, Any]:
    current = now or datetime.now(REPORT_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=REPORT_TIMEZONE)
    today = current.astimezone(REPORT_TIMEZONE).date()
    if target_date:
        anchor = date.fromisoformat(target_date)
    elif "上周" in message:
        anchor = today - timedelta(days=7)
    else:
        anchor = today
    start = anchor - timedelta(days=anchor.weekday())
    natural_end = start + timedelta(days=6)
    end = today if start <= today <= natural_end else natural_end
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "anchorDate": anchor.isoformat(),
        "timezone": str(REPORT_TIMEZONE),
        "isCurrentWeek": start <= today <= natural_end,
    }


def _chat_url(api_base: str) -> str:
    base = api_base.strip().rstrip("/")
    if not base:
        raise AssistantConfigurationError("请配置 Provider API 地址")
    parsed = urlparse(base)
    is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
        raise AssistantConfigurationError("Provider 必须使用 HTTPS；本机服务可使用 localhost HTTP")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _compact_index(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": item.get("name"),
        "code": item.get("code"),
        "price": item.get("price"),
        "changeAmount": item.get("changeAmount"),
        "changePercent": item.get("changePercent"),
        "source": item.get("source"),
        "isFallback": bool(item.get("isFallback")),
    }


def _public_chart_links(report: Dict[str, Any], public_app_url: str) -> List[Dict[str, str]]:
    result = []
    for item in report.get("chartExports") or []:
        page_url = str(item.get("pageUrl") or "")
        if not page_url:
            continue
        result.append({
            "title": str(item.get("title") or "图表"),
            "market": str(item.get("market") or ""),
            "kind": str(item.get("kind") or ""),
            "url": f"{public_app_url.rstrip('/')}{page_url}",
        })
    return result


def _compact_report(report: Dict[str, Any], public_app_url: str) -> Dict[str, Any]:
    return {
        "date": report.get("date"),
        "label": report.get("label"),
        "generatedAt": report.get("generatedAt"),
        "markets": report.get("marketLabels") or [],
        "globalOverview": [
            {
                "region": group.get("title"),
                "indices": [_compact_index(item) for item in group.get("indices") or []],
            }
            for group in report.get("globalOverview") or []
        ],
        "majorMarkets": [
            {
                "market": group.get("title"),
                "indices": [_compact_index(item) for item in group.get("indices") or []],
            }
            for group in report.get("majorMarkets") or []
        ],
        "chartLinks": _public_chart_links(report, public_app_url),
        "sources": report.get("sources") or {},
    }


def _report_context(
    report_type: str,
    public_app_url: str,
    report_session: str,
    target_date: str = "",
) -> List[Dict[str, Any]]:
    reports = [get_cached_report(report_session, target_date)]
    return [_compact_report(report, public_app_url) for report in reports if report]


def _weekly_report_context(
    period: Dict[str, Any],
) -> Dict[str, Any]:
    return get_cached_weekly_market_context(period)


def _provider_config(payload: Dict[str, Any]) -> Dict[str, str]:
    provider_id = "deepseek"
    preset = PROVIDER_PRESETS[provider_id]
    api_base = (
        _environment_value(provider_id, "BASE_URL")
        or preset["apiBase"]
    )
    model = _normalize_model(provider_id, (
        str(payload.get("model") or "").strip()
        or _environment_value(provider_id, "MODEL")
        or preset["model"]
    ))
    api_key = _environment_key(provider_id)
    if not model:
        raise AssistantConfigurationError("请配置模型名称")
    if not api_key and urlparse(api_base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AssistantConfigurationError("请先通过 ./start.sh configure-deepseek 配置本机 API Key")
    return {
        "id": provider_id,
        "name": preset["name"],
        "apiBase": api_base,
        "model": model,
        "apiKey": api_key,
    }


def _provider_chat(
    config: Dict[str, str],
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.1,
) -> str:
    headers = {"Content-Type": "application/json"}
    if config["apiKey"]:
        headers["Authorization"] = f"Bearer {config['apiKey']}"
    try:
        response = requests.post(
            _chat_url(config["apiBase"]),
            headers=headers,
            json={
                "model": config["model"],
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            },
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        content = str((((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
    except requests.RequestException as exc:
        upstream_response = getattr(exc, "response", None)
        status = getattr(upstream_response, "status_code", None)
        detail = _provider_error_detail(upstream_response)
        detail_suffix = f"：{detail}" if detail else ""
        suffix = f"（HTTP {status}{detail_suffix}）" if status else ""
        raise AssistantProviderError(f"Provider 请求失败{suffix}") from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise AssistantProviderError("Provider 返回了无法识别的响应") from exc
    if not content:
        raise AssistantProviderError("Provider 没有返回内容")
    return content


def _json_from_provider(content: str) -> Dict[str, Any]:
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        payload = json.loads(candidate)
    except ValueError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise AssistantProviderError("Provider 没有返回可识别的查询 Schema")
        try:
            payload = json.loads(candidate[start:end + 1])
        except ValueError as exc:
            raise AssistantProviderError("Provider 返回的查询 Schema 不是合法 JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("query"), dict):
        payload = payload["query"]
    if not isinstance(payload, dict):
        raise AssistantProviderError("Provider 返回的查询 Schema 不是 JSON 对象")
    return payload


def _query_planner_messages(message: str) -> List[Dict[str, str]]:
    today = datetime.now(REPORT_TIMEZONE).date().isoformat()
    system_prompt = f"""你是本地金融数据查询规划器。今天是 {today}，默认时区为 Asia/Shanghai。
你的唯一任务是把用户输入转换成 QuerySpec 1.0 JSON；不得回答行情、不得补数、不得输出 Markdown。

intent.domain 只支持：report、weekly_index、sector。
operation：
- report: get、compare
- weekly_index: get、compare、rank
- sector: snapshot、timeline、compare、rank、children

报告 session 只支持 morning、midday、close、us-night。早报=morning，午报=midday，收盘报=close，夜报/晚报=us-night。
市场只支持 CN、HK、US；A股=CN，港股=HK，美股=US。板块 level 只支持 1 或 2。
历史查询 sourcePolicy 必须为 local_only。板块日期使用 market_local。
“本周/最近一周/最新一周/最新一份周报”使用 weekly_index，并把 time.kind 设为 latest_finalized、date/start/end 留空；后端会选择最近一份已经完成的周报。
用户说“变化/走势”时使用 sector.timeline、comparison.mode=first_to_last、includeAdjacentChanges=true。
用户说“最强/最高/前几名”时使用 rank，并设置 sortMetric、sortDirection 和 limit。
不知道板块 code 时保留 id 为空并填写 name；不要虚构 code。

输出结构：
{{"schemaVersion":"1.0","intent":{{"domain":"sector","operation":"timeline"}},"subjects":[{{"type":"sector","market":"CN","level":2,"name":"酿酒业","id":""}}],"time":{{"kind":"date","date":"2026-07-15","start":"","end":"","timezonePolicy":"market_local"}},"report":{{"session":"","sessions":[]}},"metrics":["changePercent","marketValue","turnover"],"comparison":{{"mode":"first_to_last","includeAdjacentChanges":true}},"options":{{"sourcePolicy":"local_only","includeSeries":true,"includeSummary":true,"sortMetric":"changePercent","sortDirection":"desc","limit":20}}}}
只输出一个 JSON 对象。"""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]


def plan_market_query(payload: Dict[str, Any], message: str) -> Dict[str, Any]:
    config = _provider_config(payload)
    messages = _query_planner_messages(message)
    content = _provider_chat(config, messages, temperature=0)
    try:
        query = normalize_query_spec(_json_from_provider(content))
    except RuntimeError as exc:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": f"上面的 JSON 校验失败：{exc}。请修正后只输出一个完整 QuerySpec JSON。",
            },
        ]
        repaired = _provider_chat(config, repair_messages, temperature=0)
        try:
            query = normalize_query_spec(_json_from_provider(repaired))
        except RuntimeError as repaired_exc:
            raise AssistantProviderError(f"查询 Schema 校验失败：{repaired_exc}") from repaired_exc
    if query["intent"]["domain"] == "weekly_index" and any(
        keyword in message
        for keyword in ("本周", "最近一周", "最新一周", "最新一份", "最近一份")
    ):
        query["time"].update({
            "kind": "latest_finalized",
            "date": "",
            "start": "",
            "end": "",
        })
    return query


def _query_periods(result: Dict[str, Any]) -> List[str]:
    result_type = str(result.get("resultType") or "")
    data = result.get("data") or {}
    if result_type.startswith("report"):
        return list(dict.fromkeys(str(item.get("date") or "") for item in data.get("reports") or []))
    if result_type == "weekly_index":
        period = data.get("period") or {}
        return [f"{period.get('startDate')} 至 {period.get('endDate')}"]
    return [str(data.get("date") or "")]


def generate_market_query_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise AssistantConfigurationError("请输入查询内容")
    config = _provider_config(payload)
    query = plan_market_query(payload, message)
    result = execute_market_query(query)
    answer_prompt = (
        "你是金融数据结果解释器。只能使用 ResultEnvelope 中的数据，不得联网补数或猜测。"
        "null 表示没有覆盖，绝不能写成 0。所有派生数值已经由后端计算，不要重新计算。"
        "优先直接回答用户问题；如果 meta.warnings、coverage 或 status 显示不完整，必须说明。"
        "输出简体中文 Markdown，并说明数据日期、市场当地时区和本地数据来源。\n\n"
        f"用户问题：{message}\n\n"
        f"ResultEnvelope：{json.dumps(result, ensure_ascii=False, separators=(',', ':'))}"
    )
    content = _provider_chat(
        config,
        [
            {"role": "system", "content": "你只解释给定的本地结构化金融查询结果。"},
            {"role": "user", "content": answer_prompt},
        ],
        temperature=0.1,
    )
    fallback_notice = str((result.get("meta") or {}).get("fallbackNotice") or "")
    if fallback_notice:
        content = f"> {fallback_notice}\n\n{content}"
    periods = [item for item in _query_periods(result) if item]
    return {
        "content": content,
        "responseType": "query",
        "reportType": "query",
        "session": "query",
        "label": {
            "report": "历史报告查询",
            "weekly_index": "周线查询",
            "sector": "板块查询",
        }[query["intent"]["domain"]],
        "provider": config["name"],
        "model": config["model"],
        "generatedAt": datetime.now(REPORT_TIMEZONE).isoformat(),
        "dataPeriods": periods,
        "query": query,
        "result": result,
    }


def generate_assistant_response(payload: Dict[str, Any], public_app_url: str) -> Dict[str, Any]:
    if bool(payload.get("quickAction")):
        return generate_market_report(payload, public_app_url)
    return generate_market_query_response(payload)


def generate_market_report(payload: Dict[str, Any], public_app_url: str) -> Dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise AssistantConfigurationError("请输入“日报”、“周报”或具体报告要求")
    report_type = _report_type(message)
    report_session = _report_session(payload, message)
    target_date = _report_date(message)
    if target_date and report_type == "daily" and not _has_explicit_report_session(payload, message):
        raise AssistantConfigurationError("已识别到历史日期，请同时说明要查看早报、午报、收盘报还是夜报")
    config = _provider_config(payload)
    weekly_context: Dict[str, Any] = {}
    weekly_period: Dict[str, Any] = {}
    weekly_fallback_notice = ""
    if report_type == "weekly":
        weekly_period = _weekly_period(message, target_date)
        weekly_context = _weekly_report_context(weekly_period)
        if not weekly_context and not target_date and "上周" not in message:
            weekly_context = get_latest_finalized_weekly_market_context()
            served_period = weekly_context.get("period") or {}
            if served_period:
                weekly_fallback_notice = (
                    "当周周报尚未生成，已为你返回最近一份已完成周报："
                    f"{served_period.get('startDate')} 至 {served_period.get('endDate')}"
                )
                weekly_period = served_period
        reports = [weekly_context] if weekly_context.get("coverage", {}).get("availableIndexCount") else []
    else:
        reports = _report_context(report_type, public_app_url, report_session, target_date)
    if not reports:
        label = "周报" if report_type == "weekly" else SESSION_LABELS[report_session]
        date_prefix = f"{target_date} " if target_date else ""
        if report_type == "weekly":
            raise AssistantConfigurationError(
                f"{weekly_period['startDate']} 至 {weekly_period['endDate']} 暂无可用的券商周线数据"
            )
        raise AssistantConfigurationError(f"{date_prefix}{label}的数据包尚未采集完成")

    report_format = WEEKLY_FORMAT if report_type == "weekly" else DAILY_FORMAT
    system_prompt = (
        "你是严谨的市场报告助手。你只能使用用户提供的结构化市场数据，不得自行补数、猜测或把备用源描述成长桥。"
        "报告已与热点图解耦，不得添加热点图、板块状态图或根据缺失的板块数据进行推断。"
        "如果某个市场或日期缺失，必须在“数据来源与缺口”中明确说明。涨跌方向和数值必须与数据完全一致。"
        "输出简体中文 Markdown，严格沿用给定标题顺序；不要添加寒暄、免责声明模板或与报告无关的内容。"
    )
    data_period_label = (
        f"{weekly_period['startDate']} 至 {weekly_period['endDate']}"
        if report_type == "weekly"
        else (target_date or "当天最新固化数据")
    )
    data_period_heading = "本次数据区间" if report_type == "weekly" else "本次数据日期"
    user_prompt = (
        f"用户指令：{message}\n\n"
        f"{data_period_heading}：{data_period_label}\n\n"
        f"必须使用的输出格式：\n{report_format}\n"
        f"{'结构化券商周线' if report_type == 'weekly' else '结构化指数快照'}如下：\n"
        f"{json.dumps(reports, ensure_ascii=False, separators=(',', ':'))}"
    )
    content = _provider_chat(
        config,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    if weekly_fallback_notice:
        content = f"> {weekly_fallback_notice}\n\n{content}"

    data_periods = (
        [f"{weekly_period['startDate']} 至 {weekly_period['endDate']}"]
        if report_type == "weekly"
        else list(dict.fromkeys(str(item.get("date") or "") for item in reports))
    )
    result = {
        "content": content,
        "reportType": report_type,
        "session": report_session if report_type == "daily" else "weekly",
        "label": SESSION_LABELS[report_session] if report_type == "daily" else "周报",
        "provider": config["name"],
        "model": config["model"],
        "generatedAt": datetime.now(REPORT_TIMEZONE).isoformat(),
        "dataPeriods": data_periods,
        "targetDate": (
            str(weekly_period.get("endDate") or "")
            if report_type == "weekly"
            else (target_date or str(reports[-1].get("date") or ""))
        ),
    }
    if report_type == "weekly":
        result["period"] = weekly_period
        result["coverage"] = weekly_context.get("coverage") or {}
        result["fallbackNotice"] = weekly_fallback_notice
    return result
