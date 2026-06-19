"""
AKShare 数据服务
只返回真实数据源取得的数据；接口失败时返回空数组，不使用模拟行情。
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import quote

import akshare as ak
import pandas as pd
import requests
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return default
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned in {"", "-", "--", "N/A", "n/a"}:
                return default
            cleaned = cleaned.replace("−", "-").replace(",", "").replace("$", "").replace("%", "")
            cleaned = re.sub(r"^\((.*)\)$", r"-\1", cleaned)
            if cleaned in {"", "-", "--"}:
                return default
            return float(cleaned)
        return float(value)
    except Exception:
        return default


def compute_change_percent(price: Optional[float], change_amount: Optional[float], fallback: Optional[float] = 0.0) -> float:
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


def real_or_empty(fetcher: Callable[[], List[Dict[str, Any]]], label: str):
    try:
        return jsonify(fetcher())
    except Exception as exc:
        logger.exception("获取%s真实数据失败: %s", label, exc)
        return jsonify([])


def normalize_quote(row: pd.Series, *, default_name: Optional[str] = None, default_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    name = str(first_value(row, ["名称", "name", "股票名称", "指数名称"], default_name) or "")
    code = str(first_value(row, ["代码", "code", "股票代码", "symbol"], default_code) or "")
    price = safe_float(first_value(row, ["最新价", "最新", "当前价", "price", "收盘"], None), None)

    if not name or not code or price is None:
        return None

    previous_close = safe_float(first_value(row, ["昨收", "previousClose"], None), None)
    fallback_percent = safe_float(first_value(row, ["涨跌幅", "changePercent", "涨幅"], None), None)
    change_amount = safe_float(first_value(row, ["涨跌额", "changeAmount", "涨跌"], None), None)
    if change_amount is None and previous_close is not None:
        change_amount = price - previous_close
    change_percent = compute_change_percent(price, change_amount, fallback_percent)
    market_value = safe_float(first_value(row, ["总市值", "市值", "marketValue"], None), None)
    net_inflow = safe_float(first_value(row, ["主力净流入", "净流入", "netInflow"], None), None)

    return {
        "name": name,
        "code": code,
        "price": price,
        "changePercent": change_percent,
        "changeAmount": change_amount or 0,
        "open": safe_float(first_value(row, ["今开", "开盘", "open"], None), None),
        "high": safe_float(first_value(row, ["最高", "high"], None), None),
        "low": safe_float(first_value(row, ["最低", "low"], None), None),
        "previousClose": previous_close,
        "volume": safe_float(first_value(row, ["成交量", "volume"], None), None),
        "turnover": safe_float(first_value(row, ["成交额", "turnover"], None), None),
        "marketValue": market_value,
        "netInflow": net_inflow,
        "source": "AKShare",
    }


def normalize_index_row(row: pd.Series, default_name: Optional[str] = None, default_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    quote = normalize_quote(row, default_name=default_name, default_code=default_code)
    if not quote:
        return None

    return {
        key: quote[key]
        for key in [
            "name",
            "code",
            "price",
            "changePercent",
            "changeAmount",
            "open",
            "high",
            "low",
            "previousClose",
            "volume",
            "source",
        ]
        if quote.get(key) is not None
    }


def request_json(url: str, *, params: Optional[Dict[str, Any]] = None, referer: str = "https://www.nasdaq.com/", timeout: int = 8) -> Dict[str, Any]:
    response = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": referer,
        },
    )
    response.raise_for_status()
    return response.json()


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
    if price is None or previous_close is None:
        return None

    change_amount = price - previous_close
    return {
        "name": name or fields[0],
        "code": code or symbol,
        "price": price,
        "changePercent": compute_change_percent(price, change_amount),
        "changeAmount": change_amount,
        "open": open_price,
        "high": high,
        "low": low,
        "previousClose": previous_close,
        "volume": volume,
        "turnover": turnover,
        "source": "Sina",
    }


def normalize_sina_hk_index(symbol: str, name: str, code: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    if len(fields) < 13:
        return None

    open_price = safe_float(fields[2], None)
    previous_close = safe_float(fields[3], None)
    high = safe_float(fields[4], None)
    low = safe_float(fields[5], None)
    price = safe_float(fields[6], None)
    change_amount = safe_float(fields[7], None)
    fallback_percent = safe_float(fields[8], None)
    volume = safe_float(fields[11], None)
    turnover = safe_float(fields[12], None)
    if price is None or previous_close is None:
        return None
    if change_amount is None:
        change_amount = price - previous_close

    return {
        "name": name or fields[1],
        "code": code or fields[0] or symbol.replace("rt_hk", ""),
        "price": price,
        "changePercent": compute_change_percent(price, change_amount, fallback_percent),
        "changeAmount": change_amount,
        "open": open_price,
        "high": high,
        "low": low,
        "previousClose": previous_close,
        "volume": volume,
        "turnover": turnover,
        "source": "Sina",
    }


def normalize_yahoo_chart(symbol: str, name: str, code: str) -> Optional[Dict[str, Any]]:
    data = request_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
        params={"range": "1d", "interval": "1m"},
        referer=f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/",
        timeout=6,
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
        "source": "Yahoo Finance",
    }


def fetch_yahoo_indices(desired: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    result = []
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


def normalize_nasdaq_index(symbol: str, name: str, code: str) -> Optional[Dict[str, Any]]:
    data = request_json(
        f"https://api.nasdaq.com/api/quote/{symbol}/info",
        params={"assetclass": "index"},
        referer=f"https://www.nasdaq.com/market-activity/index/{symbol.lower()}",
        timeout=6,
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
        "source": "Nasdaq",
    }


def fetch_nasdaq_indices(desired: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    result = []
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
    used_codes = set()

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

        normalized = normalize_index_row(match.iloc[0], default_name=name, default_code=code)
        if normalized and normalized["code"] not in used_codes:
            normalized["name"] = name
            normalized["code"] = code
            result.append(normalized)
            used_codes.add(normalized["code"])

    return result


def fetch_a_indices() -> List[Dict[str, Any]]:
    desired = [
        {"name": "上证指数", "code": "sh000001", "symbol": "sh000001"},
        {"name": "深证成指", "code": "sz399001", "symbol": "sz399001"},
        {"name": "创业板指", "code": "sz399006", "symbol": "sz399006"},
        {"name": "科创50", "code": "sh000688", "symbol": "sh000688"},
        {"name": "北证50", "code": "bj899050", "symbol": "bj899050"},
    ]
    try:
        quotes = fetch_sina_quotes([item["symbol"] for item in desired])
        result = []
        for item in desired:
            normalized = normalize_sina_cn_index(
                item["symbol"],
                item["name"],
                item["code"],
                quotes.get(item["symbol"], []),
            )
            if normalized:
                result.append(normalized)
        if result:
            return result
    except Exception as exc:
        logger.warning("获取新浪A股指数失败: %s", exc)

    df = ak.stock_zh_index_spot_sina()
    return pick_rows(df, [{"name": item["name"], "code": item["code"]} for item in desired])


def fetch_hk_indices() -> List[Dict[str, Any]]:
    desired = [
        {"name": "恒生指数", "code": "HSI", "symbol": "rt_hkHSI"},
        {"name": "恒生科技", "code": "HSTECH", "symbol": "rt_hkHSTECH"},
        {"name": "国企指数", "code": "HSCEI", "symbol": "rt_hkHSCEI"},
        {"name": "红筹指数", "code": "HSCCI", "symbol": "rt_hkHSCCI"},
    ]
    try:
        quotes = fetch_sina_quotes([item["symbol"] for item in desired])
        result = []
        for item in desired:
            normalized = normalize_sina_hk_index(
                item["symbol"],
                item["name"],
                item["code"],
                quotes.get(item["symbol"], []),
            )
            if normalized:
                result.append(normalized)
        if result:
            return result
    except Exception as exc:
        logger.warning("获取新浪港股指数失败: %s", exc)

    for fetcher in (ak.stock_hk_index_spot_sina, ak.stock_hk_index_spot_em):
        try:
            picked = pick_rows(fetcher(), [{"name": item["name"], "code": item["code"]} for item in desired])
            if picked:
                return picked
        except Exception as exc:
            logger.warning("获取港股指数失败: %s", exc)

    return fetch_yahoo_indices([
        {"name": "恒生指数", "code": "HSI", "symbol": "^HSI"},
        {"name": "国企指数", "code": "HSCEI", "symbol": "^HSCE"},
        {"name": "红筹指数", "code": "HSCCI", "symbol": "^HSCC"},
    ])


def fetch_global_indices() -> List[Dict[str, Any]]:
    result = fetch_a_indices()[:5]

    try:
        result.extend(fetch_hk_indices()[:2])
    except Exception as exc:
        logger.warning("获取港股指数失败: %s", exc)

    try:
        result.extend(fetch_us_indices()[:3])
    except Exception as exc:
        logger.warning("获取美股指数失败: %s", exc)

    try:
        result.extend(fetch_yahoo_indices([
            {"name": "日经225", "code": "N225", "symbol": "^N225"},
            {"name": "富时100", "code": "FTSE", "symbol": "^FTSE"},
            {"name": "DAX30", "code": "GDAXI", "symbol": "^GDAXI"},
            {"name": "CAC40", "code": "FCHI", "symbol": "^FCHI"},
            {"name": "孟买指数", "code": "BSESN", "symbol": "^BSESN"},
            {"name": "S&P/ASX 200", "code": "AXJO", "symbol": "^AXJO"},
        ]))
    except Exception as exc:
        logger.warning("获取国际指数失败: %s", exc)

    return result


def fetch_us_indices() -> List[Dict[str, Any]]:
    yahoo_indices = fetch_yahoo_indices([
        {"name": "道琼斯", "code": "DJIA", "symbol": "^DJI"},
        {"name": "标普500", "code": "GSPC", "symbol": "^GSPC"},
    ])
    nasdaq_indices = fetch_nasdaq_indices([
        {"name": "纳斯达克", "code": "COMP", "symbol": "COMP"},
        {"name": "费城半导体", "code": "SOX", "symbol": "SOX"},
    ])
    by_code = {item["code"]: item for item in [*yahoo_indices, *nasdaq_indices]}
    result = [
        by_code[code]
        for code in ["DJIA", "COMP", "GSPC", "SOX"]
        if code in by_code
    ]
    if result:
        return result

    df = ak.index_global_spot_em()
    return pick_rows(df, [
        {"name": "道琼斯", "code": "DJIA"},
        {"name": "纳斯达克", "code": "NDX"},
        {"name": "标普500", "code": "SPX"},
        {"name": "费城半导体", "code": "SOX"},
    ])


def normalize_stock_table(df: pd.DataFrame, limit: int = 80) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        quote = normalize_quote(row)
        if not quote:
            continue

        # 个股热力图的面积按市值计算；没有真实市值就不展示，避免误导。
        if not quote.get("marketValue"):
            continue

        result.append(quote)

    result.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
    return result[:limit]


def fetch_hk_stocks() -> List[Dict[str, Any]]:
    return normalize_stock_table(ak.stock_hk_spot_em(), 100)


def normalize_nasdaq_stock(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    code = str(row.get("symbol") or "").strip().upper()
    name = str(row.get("name") or "").strip()
    price = safe_float(row.get("lastsale"), None)
    change_amount = safe_float(row.get("netchange"), 0) or 0
    market_value = safe_float(row.get("marketCap"), None)
    fallback_percent = safe_float(row.get("pctchange"), 0) or 0

    if not code or not name or price is None or not market_value:
        return None

    return {
        "name": clean_nasdaq_name(name),
        "code": code,
        "price": price,
        "changePercent": compute_change_percent(price, change_amount, fallback_percent),
        "changeAmount": change_amount,
        "marketValue": market_value,
        "source": "Nasdaq",
    }


def clean_nasdaq_name(name: str) -> str:
    cleaned = name.strip()
    replacements = [
        r"\s+Common Stock.*$",
        r"\s+Capital Stock.*$",
        r"\s+Class [A-Z] Ordinary Shares.*$",
        r"\s+American Depositary Shares.*$",
        r"\s+New York Registry Shares.*$",
        r"\s+Ordinary Shares.*$",
    ]

    for pattern in replacements:
        cleaned = re.sub(pattern, "", cleaned)

    return cleaned.strip() or name


def fetch_us_stocks_nasdaq(limit: int = 100) -> List[Dict[str, Any]]:
    url = "https://api.nasdaq.com/api/screener/stocks"
    rows: List[Dict[str, Any]] = []

    for market_cap in ("mega", "large"):
        data = request_json(
            url,
            params={"tableonly": "true", "limit": limit, "offset": 0, "marketcap": market_cap},
            referer="https://www.nasdaq.com/market-activity/stocks/screener",
        )
        table = data.get("data", {}).get("table") or data.get("data", {})
        rows.extend(table.get("rows") or [])
        if len(rows) >= limit:
            break

    result_by_code: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        stock = normalize_nasdaq_stock(row)
        if stock:
            result_by_code[stock["code"]] = stock

    result = sorted(result_by_code.values(), key=lambda item: item.get("marketValue") or 0, reverse=True)
    return result[:limit]


def fetch_us_stocks() -> List[Dict[str, Any]]:
    try:
        result = fetch_us_stocks_nasdaq(100)
        if result:
            return result
    except Exception as exc:
        logger.warning("获取Nasdaq美股数据失败: %s", exc)

    try:
        df = ak.stock_us_spot_em()
    except Exception:
        df = ak.stock_us_famous_spot_em()
    return normalize_stock_table(df, 100)


def _fetch_top_a_stocks_from_sina(limit: int = 10) -> List[Dict[str, Any]]:
    """从新浪获取全 A 股 top 股票（按市值排序），作为板块成分股不可用时的兜底"""
    try:
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData"
        )
        all_stocks: List[Dict[str, Any]] = []
        for page in range(1, 4):
            params = {
                "page": str(page),
                "num": "40",
                "sort": "mktcap",
                "asc": "0",
                "node": "hs_a",
            }
            resp = requests.get(url, params=params, timeout=12, headers=SINA_HEADERS)
            resp.raise_for_status()
            text = resp.text.strip()
            if not text or text in ("null", "[]"):
                break
            data = json.loads(text)
            if not isinstance(data, list) or len(data) == 0:
                break
            for item in data:
                price = safe_float(item.get("trade"), None)
                market_value = safe_float(item.get("mktcap"), None)
                if not price or not market_value:
                    continue
                stock_name = str(item.get("name", "")).strip()
                stock_code = str(item.get("code", "") or item.get("symbol", "")).strip()
                if not stock_name or not stock_code:
                    continue
                change_percent = safe_float(item.get("changepercent"), 0)
                all_stocks.append({
                    "name": stock_name,
                    "code": stock_code,
                    "price": price,
                    "changePercent": change_percent or 0,
                    "changeAmount": safe_float(item.get("pricechange"), 0) or 0,
                    "marketValue": market_value,
                    "source": "Sina",
                })
            if len(data) < 40:
                break
        all_stocks.sort(key=lambda s: s.get("marketValue") or 0, reverse=True)
        return all_stocks[:limit]
    except Exception as exc:
        logger.debug("新浪全A股数据获取失败: %s", exc)
        return []


# 新浪概念板块 node 动态匹配缓存
_sina_nodes_cache: Optional[Dict[str, str]] = None


def _load_sina_nodes() -> Dict[str, str]:
    """加载新浪行业/概念节点树，返回 {名称: node码} 映射"""
    global _sina_nodes_cache
    if _sina_nodes_cache is not None:
        return _sina_nodes_cache

    nodes: Dict[str, str] = {}
    try:
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodes"
        )
        resp = requests.get(url, timeout=10, headers=SINA_HEADERS)
        resp.raise_for_status()
        tree = json.loads(resp.text.strip())

        def walk(tag: Any, depth: int = 0) -> None:
            if depth > 4 or not isinstance(tag, list) or len(tag) < 2:
                return
            children = tag[1]
            if not isinstance(children, list):
                return
            for child in children:
                if not isinstance(child, list) or len(child) < 2:
                    continue
                name = str(child[0] if isinstance(child[0], str) else "")
                if len(child) >= 3 and isinstance(child[2], str) and child[2]:
                    code = child[2]
                    if code.startswith(("gn_", "new_", "chgn_", "sw1_", "sw2_")):
                        nodes[name] = code
                if isinstance(child[1], list):
                    walk(child)

        walk(tree)
    except Exception as exc:
        logger.warning("加载新浪节点树失败: %s", exc)

    _sina_nodes_cache = nodes
    return nodes


def _match_sina_node(board_name: str) -> Optional[str]:
    """用模糊匹配找一个最佳新浪节点码"""
    nodes = _load_sina_nodes()
    if not nodes:
        return None

    # 精确匹配
    if board_name in nodes:
        return nodes[board_name]

    # 包含匹配
    for name, code in nodes.items():
        if board_name in name or name in board_name:
            return code

    # 相似度匹配
    from difflib import SequenceMatcher

    best_code: Optional[str] = None
    best_score = 0.0
    for name, code in nodes.items():
        score = SequenceMatcher(None, board_name, name).ratio()
        if score > best_score:
            best_score = score
            best_code = code

    if best_score > 0.5:
        return best_code
    return None


def fetch_board_stocks_from_sina(board_name: str) -> List[Dict[str, Any]]:
    """通过新浪概念板块 API 获取成分股（动态匹配节点码）"""
    node = _match_sina_node(board_name)
    if not node:
        logger.debug("未找到板块 %s 的匹配新浪节点", board_name)
        return []

    try:
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData"
        )
        all_stocks: List[Dict[str, Any]] = []
        for page in range(1, 6):
            params = {
                "page": str(page),
                "num": "40",
                "sort": "mktcap",
                "asc": "0",
                "node": node,
            }
            resp = requests.get(url, params=params, timeout=12, headers=SINA_HEADERS)
            resp.raise_for_status()
            text = resp.text.strip()
            if not text or text == "null" or text == "[]":
                break

            data = json.loads(text)
            if not isinstance(data, list) or len(data) == 0:
                break

            for item in data:
                price = safe_float(item.get("trade"), None)
                change_amount = safe_float(item.get("pricechange"), None)
                market_value = safe_float(item.get("mktcap"), None)
                if not price or not market_value:
                    continue

                stock_name = str(item.get("name", "")).strip()
                stock_code = str(item.get("code", "") or item.get("symbol", "")).strip()
                if not stock_name or not stock_code:
                    continue

                change_percent = safe_float(item.get("changepercent"), 0)
                all_stocks.append({
                    "name": stock_name,
                    "code": stock_code,
                    "price": price,
                    "changePercent": change_percent or 0,
                    "changeAmount": change_amount or 0,
                    "marketValue": market_value,
                    "source": "Sina",
                })

            if len(data) < 40:
                break

        all_stocks.sort(key=lambda s: s.get("marketValue") or 0, reverse=True)
        return all_stocks[:10]
    except Exception as exc:
        logger.debug("新浪板块成分股 %s 失败: %s", board_name, exc)
        return []


def fetch_board_stocks_from_eastmoney(board_code: str) -> List[Dict[str, Any]]:
    """通过东方财富 29.push2 接口获取板块成分股"""
    if not board_code or not board_code.startswith("BK"):
        return []

    try:
        url = "http://29.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "50",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f20",
            "fs": f"b:{board_code} f:!50",
            "fields": "f2,f3,f4,f12,f14,f20,f62",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        stocks: List[Dict[str, Any]] = []
        for item in (data.get("data", {}).get("diff") or []):
            price = safe_float(item.get("f2"), None)
            market_value = safe_float(item.get("f20"), None)
            if not price or not market_value:
                continue
            stock_name = str(item.get("f14", "")).strip()
            stock_code = str(item.get("f12", "")).strip()
            if not stock_name or not stock_code:
                continue
            stocks.append({
                "name": stock_name,
                "code": stock_code,
                "price": price,
                "changePercent": safe_float(item.get("f3"), 0) or 0,
                "changeAmount": safe_float(item.get("f4"), 0) or 0,
                "marketValue": market_value,
                "netInflow": safe_float(item.get("f62"), None),
                "source": "东方财富",
            })
        stocks.sort(key=lambda s: s.get("marketValue") or 0, reverse=True)
        return stocks[:10]
    except Exception as exc:
        logger.debug("东方财富成分股 %s 失败: %s", board_code, exc)
        return []


def fetch_board_top_stocks(board_name: str) -> List[Dict[str, Any]]:
    # 从同花顺板块名称查领涨股（已在 boards 接口里返回 topStocks）
    # 这里做兜底：尝试从东方财富取成分股
    # 1. 先试 BK 代码
    code_map = _load_board_code_map()
    board_code = code_map.get(board_name, "")
    if board_code:
        em_stocks = fetch_board_stocks_from_eastmoney(board_code)
        if em_stocks:
            return em_stocks

    # 2. 东方财富不可用 → 返回空
    logger.info("板块 %s 成分股不可用(东财不通)", board_name)
    return []


_board_code_map_cache: Optional[Dict[str, str]] = None


def _load_board_code_map() -> Dict[str, str]:
    """从 push2ex 原始接口提取 板块名称 -> BK代码 映射（带缓存）"""
    global _board_code_map_cache
    if _board_code_map_cache is not None:
        return _board_code_map_cache
    try:
        url = "https://push2ex.eastmoney.com/getAllBKChanges"
        params = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wzchanges",
            "pageindex": "0",
            "pagesize": "5000",
        }
        resp = requests.get(url, params=params, timeout=10, headers=SINA_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        code_map: Dict[str, str] = {}
        for item in data.get("data", {}).get("allbk", []):
            name = str(item.get("n", "")).strip()
            code = str(item.get("c", "")).strip()
            if name and code:
                code_map[name] = code
        _board_code_map_cache = code_map
        return code_map
    except Exception as exc:
        logger.warning("加载板块代码映射失败: %s", exc)
        return {}


def fetch_a_boards() -> List[Dict[str, Any]]:
    """行业板块列表（同花顺），按涨跌幅排序，取 Top 90"""
    try:
        df = ak.stock_board_industry_summary_ths()
        result: List[Dict[str, Any]] = []
        name_code_df = ak.stock_board_industry_name_ths()
        code_map: Dict[str, str] = {}
        for _, row in name_code_df.iterrows():
            n = str(row.get("name", "")).strip()
            c = str(row.get("code", "")).strip()
            if n and c:
                code_map[n] = c

        for _, row in df.iterrows():
            name = str(row.get("板块", "")).strip()
            if not name:
                continue
            ths_code = code_map.get(name, "")
            leader_name = str(row.get("领涨股", "")).strip()
            leader_chg = safe_float(row.get("领涨股-涨跌幅"), None)
            leader_price = safe_float(row.get("领涨股-最新价"), None)

            top_stocks = []
            if leader_name:
                top_stocks.append({
                    "name": leader_name,
                    "code": "",
                    "price": leader_price or 0,
                    "changePercent": leader_chg or 0,
                    "changeAmount": 0,
                    "marketValue": None,
                    "source": "同花顺",
                })

            result.append({
                "name": name,
                "code": ths_code,
                "changePercent": safe_float(row.get("涨跌幅"), 0) or 0,
                "netInflow": (safe_float(row.get("净流入"), None) or 0) * 1e8,
                "marketValue": None,
                "eventCount": None,
                "upCount": int(safe_float(row.get("上涨家数"), 0) or 0),
                "downCount": int(safe_float(row.get("下跌家数"), 0) or 0),
                "totalTurnover": (safe_float(row.get("总成交额"), None) or 0) * 1e8,
                "topStocks": top_stocks,
                "source": "同花顺",
            })
        return result
    except Exception as exc:
        logger.exception("同花顺行业板块失败: %s", exc)
        return []


@app.route("/api/global-indices", methods=["GET"])
def get_global_indices():
    return real_or_empty(fetch_global_indices, "全球指数")


@app.route("/api/market-breadth", methods=["GET"])
def get_market_breadth():
    """A 股市场总览：涨跌家数、成交额、赚钱效应"""
    try:
        # 涨跌家数从乐咕乐股获取
        df = ak.stock_market_activity_legu()
        breadth: Dict[str, Any] = {}
        for _, row in df.iterrows():
            key = str(row["item"]).strip()
            val = safe_float(row["value"], None)
            breadth[key] = val

        # 成交额从新浪获取
        sina_symbols = ["s_sh000001", "s_sz399001"]
        quotes = fetch_sina_quotes(sina_symbols)
        total_turnover = 0.0
        for sym in sina_symbols:
            fields = quotes.get(sym, [])
            if len(fields) >= 6:
                # hq.sinajs.cn 格式: fields[4]=成交量(手), fields[5]=成交额(万元)
                turnover = safe_float(fields[5], 0) or 0
                total_turnover += turnover * 10000  # 万元 -> 元

        up_count = breadth.get("上涨") or 0
        down_count = breadth.get("下跌") or 0
        flat_count = breadth.get("平盘") or 0
        total_stocks = up_count + down_count + float(breadth.get("停牌") or 0) + flat_count
        win_rate = (up_count / (up_count + down_count) * 100) if (up_count + down_count) > 0 else 0

        return jsonify({
            "upCount": int(up_count),
            "downCount": int(down_count),
            "flatCount": int(flat_count),
            "limitUp": int(breadth.get("涨停") or 0),
            "limitDown": int(breadth.get("跌停") or 0),
            "totalStocks": int(total_stocks),
            "winRate": round(win_rate, 2),
            "totalTurnover": total_turnover,
            "updateTime": str(breadth.get("统计日期", "")),
        })
    except Exception as exc:
        logger.exception("获取市场总览失败: %s", exc)
        return jsonify({})


@app.route("/api/a-indices", methods=["GET"])
def get_a_indices():
    return real_or_empty(fetch_a_indices, "A股指数")


@app.route("/api/hk-indices", methods=["GET"])
def get_hk_indices():
    return real_or_empty(fetch_hk_indices, "港股指数")


@app.route("/api/us-indices", methods=["GET"])
def get_us_indices():
    return real_or_empty(fetch_us_indices, "美股指数")


@app.route("/api/a-boards", methods=["GET"])
def get_a_boards():
    return real_or_empty(fetch_a_boards, "A股板块")


@app.route("/api/a-board-stocks", methods=["GET"])
def get_a_board_stocks():
    from flask import request

    board_name = request.args.get("board", "").strip()
    if not board_name:
        return jsonify({"error": "缺少板块名称参数", "stocks": []}), 400

    return real_or_empty(lambda: fetch_board_top_stocks(board_name), f"板块成分股 {board_name}")


@app.route("/api/hk-stocks", methods=["GET"])
def get_hk_stocks():
    return real_or_empty(fetch_hk_stocks, "港股个股")


@app.route("/api/us-stocks", methods=["GET"])
def get_us_stocks():
    return real_or_empty(fetch_us_stocks, "美股个股")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
