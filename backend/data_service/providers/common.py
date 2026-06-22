from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests

SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}

NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
}


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, float) and math.isnan(value):
            return default
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned in {"", "-", "--", "N/A", "n/a", "None", "null"}:
                return default
            cleaned = (
                cleaned.replace("−", "-")
                .replace(",", "")
                .replace("$", "")
                .replace("%", "")
                .replace("HK$", "")
                .replace("US$", "")
            )
            cleaned = re.sub(r"^\((.*)\)$", r"-\1", cleaned)
            multiplier = 1.0
            if cleaned.endswith("T"):
                multiplier = 1_000_000_000_000
                cleaned = cleaned[:-1]
            elif cleaned.endswith("B"):
                multiplier = 1_000_000_000
                cleaned = cleaned[:-1]
            elif cleaned.endswith("M"):
                multiplier = 1_000_000
                cleaned = cleaned[:-1]
            elif cleaned.endswith("K"):
                multiplier = 1_000
                cleaned = cleaned[:-1]
            elif cleaned.endswith("万亿"):
                multiplier = 1_000_000_000_000
                cleaned = cleaned[:-2]
            elif cleaned.endswith("亿"):
                multiplier = 100_000_000
                cleaned = cleaned[:-1]
            elif cleaned.endswith("万"):
                multiplier = 10_000
                cleaned = cleaned[:-1]
            return float(cleaned) * multiplier
        return float(value)
    except Exception:
        return default


def compute_change_percent(
    price: Optional[float],
    change_amount: Optional[float],
    fallback: Optional[float] = 0.0,
) -> float:
    if price is not None and change_amount is not None:
        previous_close = price - change_amount
        if previous_close:
            return change_amount / previous_close * 100
    return fallback or 0.0


def parse_price_range(value: Any) -> tuple[Optional[float], Optional[float]]:
    if not isinstance(value, str) or " - " not in value:
        return None, None
    low_value, high_value = value.split(" - ", 1)
    return safe_float(low_value, None), safe_float(high_value, None)


def first_value(row: pd.Series, names: Iterable[str], default: Any = None) -> Any:
    for name in names:
        if name in row and not pd.isna(row[name]) and row[name] != "-":
            return row[name]
    return default


def request_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 8,
) -> Dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout, headers=headers)
    response.raise_for_status()
    return response.json()


def to_iso_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def compact_points(
    points: List[Dict[str, Any]],
    *,
    step: int = 8,
    fallback_value: Optional[float] = None,
) -> List[Dict[str, float]]:
    normalized = [
        {"time": str(point.get("time", "")), "value": safe_float(point.get("value"), fallback_value) or 0}
        for point in points
        if point.get("value") is not None or fallback_value is not None
    ]
    if len(normalized) <= 48:
        return normalized
    return normalized[::step]


def merge_preferred_rows(
    primary: List[Dict[str, Any]],
    fallback: List[Dict[str, Any]],
    order: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    primary_by_code = {
        str(item.get("code")): {**item, "isFallback": False}
        for item in primary
        if item.get("code")
    }
    fallback_by_code = {
        str(item.get("code")): {**item, "isFallback": True}
        for item in fallback
        if item.get("code")
    }
    codes = order or list(dict.fromkeys([*primary_by_code, *fallback_by_code]))
    return [
        primary_by_code.get(code) or fallback_by_code[code]
        for code in codes
        if code in primary_by_code or code in fallback_by_code
    ]
