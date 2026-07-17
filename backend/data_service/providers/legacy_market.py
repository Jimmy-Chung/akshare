from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import akshare as ak
import pandas as pd
import requests

from .common import (
    NASDAQ_HEADERS,
    SINA_HEADERS,
    compute_change_percent,
    first_value,
    parse_price_range,
    request_json,
    safe_float,
)
from .market_catalog import flattened_global_indices

logger = logging.getLogger(__name__)

TRADINGVIEW_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}
TRADINGVIEW_COLUMNS = [
    "close",
    "change",
    "change_abs",
    "open",
    "high",
    "low",
    "volume",
]

A_INDEX_SYMBOLS = [
    {"name": "上证指数", "code": "000001.SH", "symbol": "sh000001"},
    {"name": "深证成指", "code": "399001.SZ", "symbol": "sz399001"},
    {"name": "创业板指", "code": "399006.SZ", "symbol": "sz399006"},
    {"name": "科创50", "code": "000688.SH", "symbol": "sh000688"},
    {"name": "沪深300", "code": "000300.SH", "symbol": "sh000300"},
    {"name": "上证50", "code": "000016.SH", "symbol": "sh000016"},
    {"name": "中证500", "code": "000905.SH", "symbol": "sh000905"},
]

HK_INDEX_SYMBOLS = [
    {"name": "恒生指数", "code": "HSI.HK", "symbol": "rt_hkHSI"},
    {"name": "恒生科技指数", "code": "HSTECH.HK", "symbol": "rt_hkHSTECH"},
    {"name": "恒生中国企业指数", "code": "HSCEI.HK", "symbol": "rt_hkHSCEI"},
]

HK_WEIGHT_SYMBOLS = [
    {"name": "汇丰控股", "code": "00005.HK", "symbol": "rt_hk00005"},
    {"name": "腾讯控股", "code": "00700.HK", "symbol": "rt_hk00700"},
    {"name": "阿里巴巴-W", "code": "09988.HK", "symbol": "rt_hk09988"},
    {"name": "美团-W", "code": "03690.HK", "symbol": "rt_hk03690"},
    {"name": "建设银行", "code": "00939.HK", "symbol": "rt_hk00939"},
    {"name": "友邦保险", "code": "01299.HK", "symbol": "rt_hk01299"},
    {"name": "小米集团-W", "code": "01810.HK", "symbol": "rt_hk01810"},
    {"name": "工商银行", "code": "01398.HK", "symbol": "rt_hk01398"},
    {"name": "中国移动", "code": "00941.HK", "symbol": "rt_hk00941"},
    {"name": "比亚迪股份", "code": "01211.HK", "symbol": "rt_hk01211"},
]

US_WEIGHT_SYMBOLS = [
    "MSFT",
    "NVDA",
    "AAPL",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "BRK.B",
    "AVGO",
    "JPM",
]


def fetch_sina_quotes(symbols: List[str]) -> Dict[str, List[str]]:
    response = requests.get(
        "https://hq.sinajs.cn/list=" + ",".join(symbols),
        headers=SINA_HEADERS,
        timeout=12,
    )
    response.raise_for_status()
    quotes: Dict[str, List[str]] = {}
    for match in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', response.text):
        symbol, payload = match.groups()
        if payload:
            quotes[symbol] = payload.split(",")
    return quotes


def normalize_sina_cn_index(symbol: str, name: str, code: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    if len(fields) < 10:
        return None
    open_price = safe_float(fields[1], None)
    previous_close = safe_float(fields[2], None)
    price = safe_float(fields[3], None)
    high = safe_float(fields[4], None)
    low = safe_float(fields[5], None)
    volume = safe_float(fields[8], None)
    turnover = safe_float(fields[9], None)
    date = fields[30] if len(fields) > 30 else ""
    time = fields[31] if len(fields) > 31 else ""
    if price is None or previous_close is None:
        return None
    change_amount = price - previous_close
    return {
        "name": name,
        "code": code,
        "price": price,
        "changePercent": compute_change_percent(price, change_amount),
        "changeAmount": change_amount,
        "open": open_price,
        "high": high,
        "low": low,
        "previousClose": previous_close,
        "volume": volume,
        "turnover": turnover,
        "tradeDate": date,
        "tradeTime": time,
        "source": "Sina",
        "isFallback": True,
    }


def normalize_sina_hk_quote(symbol: str, name: str, code: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    if len(fields) < 18:
        return None
    previous_close = safe_float(fields[3], None)
    price = safe_float(fields[6], None)
    change_amount = safe_float(fields[7], None)
    change_percent = safe_float(fields[8], None)
    market_value = safe_float(fields[13], None)
    volume = safe_float(fields[11], None)
    turnover = safe_float(fields[12], None)
    open_price = safe_float(fields[2], None)
    high = safe_float(fields[4], None)
    low = safe_float(fields[5], None)
    date = fields[17].replace("/", "-") if len(fields) > 17 else ""
    time = fields[18] if len(fields) > 18 else ""
    if price is None:
        return None
    return {
        "name": name,
        "code": code,
        "price": price,
        "changePercent": change_percent or compute_change_percent(price, change_amount),
        "changeAmount": change_amount or 0,
        "open": open_price,
        "high": high,
        "low": low,
        "previousClose": previous_close,
        "volume": volume,
        "turnover": turnover,
        "marketValue": market_value,
        "tradeDate": date,
        "tradeTime": time,
        "source": "Sina",
        "isFallback": True,
    }


def normalize_yahoo_chart(symbol: str, name: str, code: str) -> Optional[Dict[str, Any]]:
    data = request_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
        params={"range": "1d", "interval": "1m"},
        headers={**NASDAQ_HEADERS, "Referer": f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/"},
        timeout=8,
    )
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta") or {}
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    closes = quote_data.get("close") or []
    highs = quote_data.get("high") or []
    lows = quote_data.get("low") or []
    opens = quote_data.get("open") or []
    intraday = [
        {"time": str(timestamp), "value": float(close)}
        for timestamp, close in zip(timestamps, closes)
        if close is not None
    ]
    price = safe_float(meta.get("regularMarketPrice"), None)
    previous_close = safe_float(meta.get("previousClose") or meta.get("chartPreviousClose"), None)
    if price is None or previous_close is None:
        return None
    change_amount = price - previous_close
    return {
        "name": name,
        "code": code,
        "price": price,
        "changePercent": compute_change_percent(price, change_amount),
        "changeAmount": change_amount,
        "open": next((safe_float(value, None) for value in opens if value is not None), None),
        "high": max((safe_float(value, 0) or 0 for value in highs if value is not None), default=price),
        "low": min((safe_float(value, price) or price for value in lows if value is not None), default=price),
        "previousClose": previous_close,
        "volume": safe_float(meta.get("regularMarketVolume"), None),
        "intradayData": intraday,
        "tradeDate": str(meta.get("regularMarketTime", "")),
        "source": "Yahoo Finance",
        "isFallback": True,
    }


def fetch_yahoo_indices(desired: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(normalize_yahoo_chart, item["symbol"], item["name"], item["code"]): item
            for item in desired
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                normalized = future.result(timeout=10)
                if normalized:
                    result.append(normalized)
            except Exception as exc:
                logger.warning("获取Yahoo指数%s失败: %s", item["name"], exc)
    return result


def fetch_tradingview_indices(desired: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Fetch global index quotes in one batch and map them to the app's stable codes."""
    if not desired:
        return []

    symbol_map = {item["symbol"]: item for item in desired}
    response = requests.post(
        "https://scanner.tradingview.com/global/scan",
        json={
            "symbols": {"tickers": list(symbol_map), "query": {"types": []}},
            "columns": TRADINGVIEW_COLUMNS,
        },
        headers=TRADINGVIEW_HEADERS,
        timeout=12,
    )
    response.raise_for_status()
    rows = response.json().get("data") or []
    result: List[Dict[str, Any]] = []

    for row in rows:
        item = symbol_map.get(str(row.get("s", "")))
        values = row.get("d") or []
        if not item or len(values) < len(TRADINGVIEW_COLUMNS):
            continue
        price = safe_float(values[0], None)
        change_percent = safe_float(values[1], 0) or 0
        change_amount = safe_float(values[2], None)
        if price is None:
            continue
        previous_close = price - change_amount if change_amount is not None else None
        result.append({
            "name": item["name"],
            "code": item["code"],
            "price": price,
            "changePercent": change_percent,
            "changeAmount": change_amount or 0,
            "open": safe_float(values[3], None),
            "high": safe_float(values[4], None),
            "low": safe_float(values[5], None),
            "previousClose": previous_close,
            "volume": safe_float(values[6], None),
            "tradeDate": "",
            "source": "TradingView",
            "isFallback": True,
        })
    return result


def normalize_nasdaq_index(symbol: str, name: str, code: str) -> Optional[Dict[str, Any]]:
    data = request_json(
        f"https://api.nasdaq.com/api/quote/{symbol}/info",
        params={"assetclass": "index"},
        headers={**NASDAQ_HEADERS, "Referer": f"https://www.nasdaq.com/market-activity/index/{symbol.lower()}"},
        timeout=8,
    ).get("data")
    if not data:
        return None
    primary = data.get("primaryData") or {}
    key_stats = data.get("keyStats") or {}
    price = safe_float(primary.get("lastSalePrice"), None)
    change_amount = safe_float(primary.get("netChange"), None)
    fallback_percent = safe_float(primary.get("percentageChange"), None)
    previous_close = safe_float((key_stats.get("previousclose") or {}).get("value"), None)
    day_low, day_high = parse_price_range((key_stats.get("dayrange") or {}).get("value"))
    if price is None:
        return None
    if change_amount is None and previous_close is not None:
        change_amount = price - previous_close
    return {
        "name": name,
        "code": code,
        "price": price,
        "changePercent": compute_change_percent(price, change_amount, fallback_percent),
        "changeAmount": change_amount or 0,
        "high": day_high,
        "low": day_low,
        "previousClose": previous_close,
        "tradeDate": primary.get("lastTradeTimestamp", ""),
        "source": "Nasdaq",
        "isFallback": True,
    }


def fetch_nasdaq_indices(desired: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(normalize_nasdaq_index, item["symbol"], item["name"], item["code"]): item
            for item in desired
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                normalized = future.result(timeout=10)
                if normalized:
                    result.append(normalized)
            except Exception as exc:
                logger.warning("获取Nasdaq指数%s失败: %s", item["name"], exc)
    return result


def pick_rows(df: pd.DataFrame, desired: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in desired:
        code = item["code"]
        name = item["name"]
        match = pd.DataFrame()
        if "代码" in df.columns:
            match = df[df["代码"].astype(str).str.upper().str.contains(code.upper(), regex=False)]
        if match.empty and "名称" in df.columns:
            match = df[df["名称"].astype(str).str.contains(name, regex=False)]
        if match.empty:
            continue
        row = match.iloc[0]
        price = safe_float(first_value(row, ["最新价", "最新", "当前价", "收盘"], None), None)
        previous_close = safe_float(first_value(row, ["昨收"], None), None)
        change_amount = safe_float(first_value(row, ["涨跌额"], None), None)
        if price is None:
            continue
        result.append({
            "name": name,
            "code": code,
            "price": price,
            "changePercent": compute_change_percent(price, change_amount, safe_float(first_value(row, ["涨跌幅"], 0), 0)),
            "changeAmount": change_amount or 0,
            "open": safe_float(first_value(row, ["今开"], None), None),
            "high": safe_float(first_value(row, ["最高"], None), None),
            "low": safe_float(first_value(row, ["最低"], None), None),
            "previousClose": previous_close,
            "volume": safe_float(first_value(row, ["成交量"], None), None),
            "turnover": safe_float(first_value(row, ["成交额"], None), None),
            "source": "AKShare",
            "isFallback": True,
        })
    return result


def fetch_a_indices() -> List[Dict[str, Any]]:
    try:
        quotes = fetch_sina_quotes([item["symbol"] for item in A_INDEX_SYMBOLS])
        result = [
            normalized
            for item in A_INDEX_SYMBOLS
            if (normalized := normalize_sina_cn_index(item["symbol"], item["name"], item["code"], quotes.get(item["symbol"], [])))
        ]
        if result:
            return result
    except Exception as exc:
        logger.warning("获取新浪A股指数失败: %s", exc)
    try:
        df = ak.stock_zh_index_spot_sina()
        return pick_rows(df, [{"name": item["name"], "code": item["code"]} for item in A_INDEX_SYMBOLS])
    except Exception as exc:
        logger.warning("获取AKShare A股指数失败: %s", exc)
        return []


def fetch_hk_indices() -> List[Dict[str, Any]]:
    try:
        quotes = fetch_sina_quotes([item["symbol"] for item in HK_INDEX_SYMBOLS])
        result = [
            normalized
            for item in HK_INDEX_SYMBOLS
            if (normalized := normalize_sina_hk_quote(item["symbol"], item["name"], item["code"], quotes.get(item["symbol"], [])))
        ]
        if result:
            return result
    except Exception as exc:
        logger.warning("获取新浪港股指数失败: %s", exc)
    return []


def fetch_us_indices() -> List[Dict[str, Any]]:
    yahoo_indices = fetch_yahoo_indices([
        {"name": "道琼斯", "code": ".DJI.US", "symbol": "^DJI"},
        {"name": "标普500", "code": ".SPX.US", "symbol": "^GSPC"},
        {"name": "纳斯达克综合指数", "code": ".IXIC.US", "symbol": "^IXIC"},
    ])
    by_code = {item["code"]: item for item in yahoo_indices}
    order = [".DJI.US", ".SPX.US", ".IXIC.US"]
    return [by_code[code] for code in order if code in by_code]


def fetch_global_indices() -> List[Dict[str, Any]]:
    catalog = flattened_global_indices()
    result: List[Dict[str, Any]] = []

    a_by_code = {item["code"]: item for item in fetch_a_indices()}
    hk_by_code = {item["code"]: item for item in fetch_hk_indices()}
    us_by_code = {item["code"]: item for item in fetch_us_indices()}
    result.extend([*a_by_code.values(), *hk_by_code.values(), *us_by_code.values()])

    existing_codes = {row["code"] for row in result}
    tradingview_items = [
        {
            "name": item["name"],
            "code": item["code"],
            "symbol": item["tradingview"],
        }
        for item in catalog
        if item.get("tradingview") and item["code"] not in existing_codes
    ]
    try:
        result.extend(fetch_tradingview_indices(tradingview_items))
    except Exception as exc:
        logger.warning("获取TradingView全球指数失败: %s", exc)

    existing_codes = {row["code"] for row in result}
    yahoo_items = [
        {
            "name": item["name"],
            "code": item["code"],
            "symbol": item["fallback"],
        }
        for item in catalog
        if str(item.get("fallback", "")).startswith("^")
        and item["code"] not in existing_codes
    ]
    result.extend(fetch_yahoo_indices(yahoo_items))
    return result


def fetch_hk_weight_stocks() -> List[Dict[str, Any]]:
    try:
        quotes = fetch_sina_quotes([item["symbol"] for item in HK_WEIGHT_SYMBOLS])
        result = [
            normalized
            for item in HK_WEIGHT_SYMBOLS
            if (normalized := normalize_sina_hk_quote(item["symbol"], item["name"], item["code"], quotes.get(item["symbol"], [])))
        ]
        result.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
        return result
    except Exception as exc:
        logger.warning("获取港股权重股失败: %s", exc)
        return []


def fetch_nasdaq_stock_quote(symbol: str) -> Optional[Dict[str, Any]]:
    data = request_json(
        f"https://api.nasdaq.com/api/quote/{quote(symbol, safe='')}/info",
        params={"assetclass": "stocks"},
        headers={**NASDAQ_HEADERS, "Referer": f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}"},
        timeout=8,
    ).get("data")
    if not data:
        return None
    primary = data.get("primaryData") or {}
    key_stats = data.get("keyStats") or {}
    price = safe_float(primary.get("lastSalePrice"), None)
    change_amount = safe_float(primary.get("netChange"), None)
    change_percent = safe_float(primary.get("percentageChange"), 0) or 0
    market_value = safe_float((key_stats.get("marketCap") or {}).get("value"), None)
    previous_close = safe_float((key_stats.get("previousclose") or {}).get("value"), None)
    day_low, day_high = parse_price_range((key_stats.get("dayrange") or {}).get("value"))
    if price is None:
        return None
    return {
        "name": data.get("companyName") or symbol,
        "code": symbol,
        "price": price,
        "changePercent": change_percent or compute_change_percent(price, change_amount),
        "changeAmount": change_amount or 0,
        "high": day_high,
        "low": day_low,
        "previousClose": previous_close,
        "marketValue": market_value,
        "tradeDate": primary.get("lastTradeTimestamp", ""),
        "source": "Nasdaq",
        "isFallback": True,
    }


def fetch_us_weight_stocks() -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_nasdaq_stock_quote, symbol): symbol for symbol in US_WEIGHT_SYMBOLS}
        for future in as_completed(futures):
            try:
                stock = future.result(timeout=10)
                if stock:
                    result.append(stock)
            except Exception as exc:
                logger.warning("获取美股权重股失败: %s", exc)
    result.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
    return result
