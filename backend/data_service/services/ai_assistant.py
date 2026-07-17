from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from services.reports import (
    REPORT_TIMEZONE,
    SESSION_LABELS,
    SESSION_TIMES,
    get_cached_report,
    get_recent_reports,
    latest_session,
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
> 实际数据覆盖日期与快照数量

## 本周一句话结论
## 全球市场周度表现
## A 股 / 港股 / 美股复盘
## A 股 / 港股 / 美股主要指数演变
## 下周观察清单
## 数据来源与缺口
"""


def provider_catalog() -> Dict[str, Any]:
    default_provider = os.getenv("AI_ASSISTANT_PROVIDER", "deepseek").strip().lower()
    if default_provider not in PROVIDER_PRESETS:
        default_provider = "deepseek"
    providers = []
    for provider_id, preset in PROVIDER_PRESETS.items():
        api_base = _environment_value(provider_id, "BASE_URL") or preset["apiBase"]
        model = _normalize_model(
            provider_id,
            _environment_value(provider_id, "MODEL") or preset["model"],
        )
        providers.append({
            "id": provider_id,
            "name": preset["name"],
            "apiBase": api_base,
            "model": model,
            "configured": bool(_environment_key(provider_id)),
            "editableEndpoint": True,
        })
    return {"defaultProvider": default_provider, "providers": providers}


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
        ("收盘", "close"),
        ("午报", "midday"),
        ("早报", "morning"),
    )
    for keyword, session in keyword_sessions:
        if keyword in message:
            return session
    return latest_session()


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
) -> List[Dict[str, Any]]:
    if report_type == "weekly":
        reports = get_recent_reports(7)
    else:
        reports = [get_cached_report(report_session)]
    return [_compact_report(report, public_app_url) for report in reports if report]


def _provider_config(payload: Dict[str, Any]) -> Dict[str, str]:
    provider_id = str(payload.get("providerId") or "deepseek").strip().lower()
    if provider_id not in PROVIDER_PRESETS:
        raise AssistantConfigurationError("不支持的 Provider")
    preset = PROVIDER_PRESETS[provider_id]
    api_base = (
        str(payload.get("apiBase") or "").strip()
        or _environment_value(provider_id, "BASE_URL")
        or preset["apiBase"]
    )
    model = _normalize_model(provider_id, (
        str(payload.get("model") or "").strip()
        or _environment_value(provider_id, "MODEL")
        or preset["model"]
    ))
    api_key = str(payload.get("apiKey") or "").strip() or _environment_key(provider_id)
    if not model:
        raise AssistantConfigurationError("请配置模型名称")
    if not api_key and urlparse(api_base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AssistantConfigurationError("请填写 API Key，或在服务端环境变量中配置")
    return {
        "id": provider_id,
        "name": preset["name"],
        "apiBase": api_base,
        "model": model,
        "apiKey": api_key,
    }


def generate_market_report(payload: Dict[str, Any], public_app_url: str) -> Dict[str, Any]:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise AssistantConfigurationError("请输入“日报”、“周报”或具体报告要求")
    report_type = _report_type(message)
    report_session = _report_session(payload, message)
    config = _provider_config(payload)
    reports = _report_context(report_type, public_app_url, report_session)
    if not reports:
        label = "周报" if report_type == "weekly" else SESSION_LABELS[report_session]
        raise AssistantConfigurationError(f"{label}的数据包尚未采集完成")

    report_format = WEEKLY_FORMAT if report_type == "weekly" else DAILY_FORMAT
    system_prompt = (
        "你是严谨的市场报告助手。你只能使用用户提供的结构化指数快照，不得自行补数、猜测或把备用源描述成长桥。"
        "报告已与热点图解耦，不得添加热点图、板块状态图或根据缺失的板块数据进行推断。"
        "如果某个市场或日期缺失，必须在“数据来源与缺口”中明确说明。涨跌方向和数值必须与数据完全一致。"
        "输出简体中文 Markdown，严格沿用给定标题顺序；不要添加寒暄、免责声明模板或与报告无关的内容。"
    )
    user_prompt = (
        f"用户指令：{message}\n\n"
        f"必须使用的输出格式：\n{report_format}\n"
        "结构化指数快照如下：\n"
        f"{json.dumps(reports, ensure_ascii=False, separators=(',', ':'))}"
    )
    headers = {"Content-Type": "application/json"}
    if config["apiKey"]:
        headers["Authorization"] = f"Bearer {config['apiKey']}"
    try:
        response = requests.post(
            _chat_url(config["apiBase"]),
            headers=headers,
            json={
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
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
        raise AssistantProviderError("Provider 没有返回报告内容")

    return {
        "content": content,
        "reportType": report_type,
        "session": report_session if report_type == "daily" else "weekly",
        "label": SESSION_LABELS[report_session] if report_type == "daily" else "周报",
        "provider": config["name"],
        "model": config["model"],
        "generatedAt": datetime.now(REPORT_TIMEZONE).isoformat(),
        "dataPeriods": list(dict.fromkeys(str(item.get("date") or "") for item in reports)),
    }
