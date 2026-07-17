from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import date, datetime
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Dict, List, Optional

from .common import compute_change_percent, safe_float, to_iso_time
from .market_catalog import flattened_global_indices

logger = logging.getLogger(__name__)

try:
    from longbridge.openapi import (
        AdjustType,
        Config,
        ContentContext,
        HttpClient,
        Market,
        MarketContext,
        OAuthBuilder,
        Period,
        QuoteContext,
        Security,
        TradeSessions,
    )
except Exception:  # pragma: no cover - handled by runtime fallback
    Config = None  # type: ignore[assignment]
    QuoteContext = None  # type: ignore[assignment]
    MarketContext = None  # type: ignore[assignment]
    ContentContext = None  # type: ignore[assignment]
    HttpClient = None  # type: ignore[assignment]
    Market = None  # type: ignore[assignment]
    OAuthBuilder = None  # type: ignore[assignment]
    AdjustType = None  # type: ignore[assignment]
    Period = None  # type: ignore[assignment]
    TradeSessions = None  # type: ignore[assignment]
    Security = None  # type: ignore[assignment]

A_INDEX_SYMBOLS = [
    {"name": "上证指数", "code": "000001.SH", "symbol": "000001.SH"},
    {"name": "深证成指", "code": "399001.SZ", "symbol": "399001.SZ"},
    {"name": "创业板指", "code": "399006.SZ", "symbol": "399006.SZ"},
    {"name": "科创50", "code": "000688.SH", "symbol": "000688.SH"},
    {"name": "沪深300", "code": "000300.SH", "symbol": "000300.SH"},
    {"name": "上证50", "code": "000016.SH", "symbol": "000016.SH"},
    {"name": "中证500", "code": "000905.SH", "symbol": "000905.SH"},
]

HK_INDEX_SYMBOLS = [
    {"name": "恒生指数", "code": "HSI.HK", "symbol": "HSI.HK"},
    {"name": "恒生科技指数", "code": "HSTECH.HK", "symbol": "HSTECH.HK"},
    {"name": "恒生中国企业指数", "code": "HSCEI.HK", "symbol": "HSCEI.HK"},
]

US_INDEX_SYMBOLS = [
    {"name": "道琼斯", "code": ".DJI.US", "symbol": ".DJI.US"},
    {"name": "标普500", "code": ".SPX.US", "symbol": ".SPX.US"},
    {"name": "纳斯达克综合指数", "code": ".IXIC.US", "symbol": ".IXIC.US"},
]

GLOBAL_INDEX_SYMBOLS = [
    {
        "name": item["name"],
        "code": item["code"],
        "symbol": item["longbridge"],
    }
    for item in flattened_global_indices()
    if item.get("longbridge")
]

HK_WEIGHT_SYMBOLS = [
    {"name": "汇丰控股", "code": "00005.HK", "symbol": "5.HK"},
    {"name": "腾讯控股", "code": "00700.HK", "symbol": "700.HK"},
    {"name": "阿里巴巴-W", "code": "09988.HK", "symbol": "9988.HK"},
    {"name": "美团-W", "code": "03690.HK", "symbol": "3690.HK"},
    {"name": "建设银行", "code": "00939.HK", "symbol": "939.HK"},
    {"name": "友邦保险", "code": "01299.HK", "symbol": "1299.HK"},
    {"name": "小米集团-W", "code": "01810.HK", "symbol": "1810.HK"},
    {"name": "工商银行", "code": "01398.HK", "symbol": "1398.HK"},
]

US_WEIGHT_SYMBOLS = [
    {"name": "Microsoft", "code": "MSFT.US", "symbol": "MSFT.US"},
    {"name": "NVIDIA", "code": "NVDA.US", "symbol": "NVDA.US"},
    {"name": "Apple", "code": "AAPL.US", "symbol": "AAPL.US"},
    {"name": "Amazon", "code": "AMZN.US", "symbol": "AMZN.US"},
    {"name": "Meta", "code": "META.US", "symbol": "META.US"},
    {"name": "Alphabet", "code": "GOOGL.US", "symbol": "GOOGL.US"},
    {"name": "Tesla", "code": "TSLA.US", "symbol": "TSLA.US"},
    {"name": "Broadcom", "code": "AVGO.US", "symbol": "AVGO.US"},
]

A_WEIGHT_SYMBOLS = [
    {"name": "贵州茅台", "code": "600519.SH", "symbol": "600519.SH"},
    {"name": "宁德时代", "code": "300750.SZ", "symbol": "300750.SZ"},
    {"name": "中国平安", "code": "601318.SH", "symbol": "601318.SH"},
    {"name": "招商银行", "code": "600036.SH", "symbol": "600036.SH"},
    {"name": "美的集团", "code": "000333.SZ", "symbol": "000333.SZ"},
    {"name": "五粮液", "code": "000858.SZ", "symbol": "000858.SZ"},
    {"name": "比亚迪", "code": "002594.SZ", "symbol": "002594.SZ"},
    {"name": "紫金矿业", "code": "601899.SH", "symbol": "601899.SH"},
]

REQUIRED_ENV_KEYS = [
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
]
ENV_ALIAS_MAP = {
    "LONGPORT_APP_KEY": "LONGBRIDGE_APP_KEY",
    "LONGPORT_APP_SECRET": "LONGBRIDGE_APP_SECRET",
    "LONGPORT_ACCESS_TOKEN": "LONGBRIDGE_ACCESS_TOKEN",
}
ENV_CANDIDATES = [
    Path(__file__).resolve().parents[3] / ".env",
    Path(__file__).resolve().parents[3] / ".env.local",
    Path(__file__).resolve().parents[1] / ".env",
]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _load_runtime_env() -> None:
    for path in ENV_CANDIDATES:
        _load_env_file(path)

    for alias_key, canonical_key in ENV_ALIAS_MAP.items():
        if not os.getenv(canonical_key) and os.getenv(alias_key):
            os.environ[canonical_key] = os.environ[alias_key]


_load_runtime_env()


def has_api_credentials() -> bool:
    required = [os.getenv(key) for key in REQUIRED_ENV_KEYS]
    return Config is not None and hasattr(Config, "from_apikey_env") and all(required)


def has_oauth_credentials() -> bool:
    if Config is None or OAuthBuilder is None:
        return False
    from . import longbridge_oauth

    return longbridge_oauth.ensure_valid_token()


def has_credentials() -> bool:
    return has_api_credentials() or has_oauth_credentials()


@lru_cache(maxsize=1)
def get_config():
    if has_api_credentials():
        return Config.from_apikey_env()

    from . import longbridge_oauth

    client_id = longbridge_oauth.get_client_id()
    if not client_id or not longbridge_oauth.ensure_valid_token(client_id):
        return None
    oauth = OAuthBuilder(client_id).build(
        lambda _url: (_ for _ in ()).throw(
            RuntimeError("OAuth Token 不可用，请重新登录")
        )
    )
    return Config.from_oauth(oauth)


@lru_cache(maxsize=1)
def get_quote_context() -> Optional["QuoteContext"]:
    if not has_credentials():
        return None
    try:
        config = get_config()
        return QuoteContext(config) if config else None
    except Exception as exc:
        logger.warning("Longbridge QuoteContext 不可用: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_market_context() -> Optional["MarketContext"]:
    if not has_credentials():
        return None
    try:
        config = get_config()
        return MarketContext(config) if config else None
    except Exception as exc:
        logger.warning("Longbridge MarketContext 不可用: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_content_context() -> Optional["ContentContext"]:
    if not has_credentials():
        return None
    try:
        config = get_config()
        return ContentContext(config) if config else None
    except Exception as exc:
        logger.warning("Longbridge ContentContext 不可用: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_http_client() -> Optional["HttpClient"]:
    if HttpClient is None:
        return None
    try:
        if has_api_credentials():
            return HttpClient.from_apikey_env()

        from . import longbridge_oauth

        client_id = longbridge_oauth.get_client_id()
        if not client_id or not longbridge_oauth.ensure_valid_token(client_id):
            return None
        oauth = OAuthBuilder(client_id).build(
            lambda _url: (_ for _ in ()).throw(
                RuntimeError("OAuth Token 不可用，请重新登录")
            )
        )
        return HttpClient.from_oauth(oauth)
    except Exception as exc:
        logger.warning("Longbridge HttpClient 不可用: %s", exc)
        return None


def diagnostics() -> Dict[str, Any]:
    from . import longbridge_oauth

    missing_keys = [key for key in REQUIRED_ENV_KEYS if not os.getenv(key)]
    auth_mode = (
        "api_key"
        if not missing_keys
        else "oauth"
        if longbridge_oauth.ensure_valid_token()
        else "none"
    )
    configured = auth_mode != "none"
    quote_context = get_quote_context() if configured else None
    return {
        "provider": "longbridge",
        "sdkAvailable": Config is not None,
        "configured": configured,
        "authMode": auth_mode,
        "missingKeys": missing_keys,
        "quoteContextReady": quote_context is not None,
        "usingLiveSource": quote_context is not None,
    }


def reset_contexts() -> None:
    get_config.cache_clear()
    get_quote_context.cache_clear()
    get_market_context.cache_clear()
    get_content_context.cache_clear()
    get_http_client.cache_clear()


def _pick_name(symbol: str, static_map: Dict[str, Any], fallback_name: str) -> str:
    info = static_map.get(symbol)
    if not info:
        return fallback_name
    return getattr(info, "name_cn", "") or getattr(info, "name_hk", "") or getattr(info, "name_en", "") or fallback_name


def _intraday_points(ctx: "QuoteContext", symbol: str) -> List[Dict[str, Any]]:
    try:
        lines = ctx.intraday(symbol, TradeSessions.Intraday)
        return [
            {"time": to_iso_time(item.timestamp), "value": safe_float(item.price, None)}
            for item in lines
            if safe_float(item.price, None) is not None
        ]
    except Exception:
        return []


def _fetch_snapshots(
    items: List[Dict[str, str]],
    *,
    include_intraday: bool = True,
    intraday_codes: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    ctx = get_quote_context()
    if not ctx:
        return []
    symbols = [item["symbol"] for item in items]
    try:
        quotes = ctx.quote(symbols)
        static_infos = ctx.static_info(symbols)
    except Exception as exc:
        logger.warning("Longbridge quote 失败: %s", exc)
        return []
    quote_map = {quote.symbol: quote for quote in quotes}
    static_map = {info.symbol: info for info in static_infos}
    result: List[Dict[str, Any]] = []
    for item in items:
        symbol = item["symbol"]
        quote = quote_map.get(symbol)
        if not quote:
            continue
        price = safe_float(getattr(quote, "last_done", None), None)
        previous_close = safe_float(getattr(quote, "prev_close", None), None)
        if price is None:
            continue
        change_amount = price - (previous_close or price)
        market_value = None
        static_info = static_map.get(symbol)
        if static_info:
            circulating_shares = safe_float(getattr(static_info, "circulating_shares", None), None)
            if circulating_shares:
                market_value = circulating_shares * price
        result.append({
            "name": _pick_name(symbol, static_map, item["name"]),
            "code": item["code"],
            "price": price,
            "changePercent": compute_change_percent(price, change_amount),
            "changeAmount": change_amount,
            "open": safe_float(getattr(quote, "open", None), None),
            "high": safe_float(getattr(quote, "high", None), None),
            "low": safe_float(getattr(quote, "low", None), None),
            "previousClose": previous_close,
            "volume": safe_float(getattr(quote, "volume", None), None),
            "turnover": safe_float(getattr(quote, "turnover", None), None),
            "marketValue": market_value,
            "intradayData": (
                _intraday_points(ctx, symbol)
                if include_intraday
                and (intraday_codes is None or item["code"] in intraday_codes)
                else []
            ),
            "tradeDate": to_iso_time(getattr(quote, "timestamp", "")),
            "source": "Longbridge",
            "isFallback": False,
        })
    return result


def fetch_a_indices() -> List[Dict[str, Any]]:
    return _fetch_snapshots(A_INDEX_SYMBOLS)


def fetch_hk_indices() -> List[Dict[str, Any]]:
    return _fetch_snapshots(HK_INDEX_SYMBOLS)


def fetch_us_indices() -> List[Dict[str, Any]]:
    return _fetch_snapshots(US_INDEX_SYMBOLS)


def fetch_global_indices() -> List[Dict[str, Any]]:
    return _fetch_snapshots(GLOBAL_INDEX_SYMBOLS)


def fetch_report_indices(markets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Fetch report indices with real Longbridge intraday points."""
    unique_items: Dict[str, Dict[str, str]] = {}
    for item in [
        *GLOBAL_INDEX_SYMBOLS,
        *A_INDEX_SYMBOLS,
        *HK_INDEX_SYMBOLS,
        *US_INDEX_SYMBOLS,
    ]:
        unique_items.setdefault(item["code"], item)
    market_symbols = {
        "CN": A_INDEX_SYMBOLS,
        "HK": HK_INDEX_SYMBOLS,
        "US": US_INDEX_SYMBOLS,
    }
    intraday_codes = {
        item["code"]
        for market in (markets or market_symbols.keys())
        for item in market_symbols.get(market, [])
    }
    return _fetch_snapshots(
        list(unique_items.values()),
        include_intraday=True,
        intraday_codes=intraday_codes,
    )


def fetch_a_weight_stocks() -> List[Dict[str, Any]]:
    data = _fetch_snapshots(A_WEIGHT_SYMBOLS)
    data.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
    return data


def fetch_hk_weight_stocks() -> List[Dict[str, Any]]:
    data = _fetch_snapshots(HK_WEIGHT_SYMBOLS)
    data.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
    return data


def fetch_us_weight_stocks() -> List[Dict[str, Any]]:
    data = _fetch_snapshots(US_WEIGHT_SYMBOLS)
    data.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
    return data


NEWS_SYMBOLS = {
    "all": [
        ("700.HK", ["港股"]),
        ("600519.SH", ["A股"]),
        ("AAPL.US", ["美股"]),
    ],
    "cn-hk": [
        ("700.HK", ["港股"]),
        ("600519.SH", ["A股"]),
    ],
    "us": [
        ("AAPL.US", ["美股"]),
        ("NVDA.US", ["美股"]),
    ],
}


def fetch_news(scope: str = "all", limit: int = 12) -> List[Dict[str, Any]]:
    ctx = get_content_context()
    if not ctx:
        return []

    result: List[Dict[str, Any]] = []
    seen = set()
    for symbol, tags in NEWS_SYMBOLS.get(scope, NEWS_SYMBOLS["all"]):
        try:
            items = ctx.news(symbol)
        except Exception as exc:
            logger.warning("Longbridge 新闻%s获取失败: %s", symbol, exc)
            continue
        for item in items:
            article_id = str(getattr(item, "id", "") or "")
            title = str(getattr(item, "title", "") or "").strip()
            if not title or article_id in seen:
                continue
            seen.add(article_id)
            published_at = getattr(item, "published_at", None)
            result.append({
                "id": f"longbridge-news:{article_id}",
                "title": title,
                "source": "Longbridge",
                "publishedAt": published_at.isoformat() if isinstance(published_at, datetime) else str(published_at or ""),
                "url": str(getattr(item, "url", "") or ""),
                "marketTags": tags,
                "summary": str(getattr(item, "description", "") or title),
                "isFallback": False,
            })

    result.sort(key=lambda item: item["publishedAt"], reverse=True)
    return result[:limit]


INDUSTRY_HEATMAP_CACHE_TTL = 60
INDUSTRY_HEATMAP_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
INDUSTRY_STOCK_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
INDUSTRY_GROUP_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
INDUSTRY_MEMBERS_CACHE_TTL = 6 * 60 * 60
INDUSTRY_MEMBERS_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
INDUSTRY_SHARELIST_WORKERS = 4
INDUSTRY_GROUP_WORKERS = 2
INDUSTRY_ACTIVITY_WORKERS = 6
INDUSTRY_ACTIVITY_LIMIT = 24
INDUSTRY_SHARELIST_MAX_IN_FLIGHT = 5
INDUSTRY_SHARELIST_SEMAPHORE = BoundedSemaphore(INDUSTRY_SHARELIST_MAX_IN_FLIGHT)
INDUSTRY_CACHE_LOCKS_GUARD = Lock()
INDUSTRY_CACHE_LOCKS: Dict[str, Lock] = {}


def _industry_cache_lock(cache_key: str) -> Lock:
    with INDUSTRY_CACHE_LOCKS_GUARD:
        return INDUSTRY_CACHE_LOCKS.setdefault(cache_key, Lock())


def _industry_rank(market: str, indicator: int) -> Dict[str, Any]:
    client = get_http_client()
    if not client:
        return {}
    path = (
        "/v1/quote/industry/rank"
        f"?market={market}&indicator={indicator}&sort_type=1&limit=20"
    )
    try:
        response = client.request("get", path)
        return response if isinstance(response, dict) else {}
    except Exception as exc:
        logger.warning("Longbridge %s 行业排行获取失败: %s", market, exc)
        return {}


def _industry_peers(market: str, counter_id: str) -> Dict[str, Any]:
    client = get_http_client()
    if not client or not counter_id:
        return {}
    path = (
        "/v1/quote/industries/peers"
        f"?type=1&market={market}&industry_id=&counter_id={counter_id}"
    )
    try:
        response = client.request("get", path)
        return response if isinstance(response, dict) else {}
    except Exception as exc:
        logger.warning("Longbridge %s 行业成分结构获取失败: %s", counter_id, exc)
        return {}


def _collect_sharelist_ids(node: Dict[str, Any]) -> List[str]:
    result: List[str] = []
    sharelist_id = str(node.get("sharelist_id") or "")
    if sharelist_id and sharelist_id != "0":
        result.append(sharelist_id)
    for child in node.get("next") or []:
        result.extend(_collect_sharelist_ids(child))
    return list(dict.fromkeys(result))


def _sharelist_stocks(sharelist_id: str) -> List[Dict[str, Any]]:
    client = get_http_client()
    if not client:
        return []
    try:
        # Bound aggregate traffic across concurrent industry requests. A request-level
        # executor alone would allow N pages to multiply the Longbridge concurrency.
        with INDUSTRY_SHARELIST_SEMAPHORE:
            response = client.request(
                "get",
                f"/v1/sharelists/{sharelist_id}"
                "?constituent=true&quote=true&subscription=true",
            )
        return (response.get("sharelist") or {}).get("stocks") or []
    except Exception as exc:
        logger.warning("Longbridge 行业股单 %s 获取失败: %s", sharelist_id, exc)
        return []


def _stock_symbol(stock: Dict[str, Any]) -> str:
    code = str(stock.get("code") or "")
    market = str(stock.get("market") or "").upper()
    return f"{code}.{market}" if code and market else ""


def _industry_members(market: str, counter_id: str) -> Dict[str, Any]:
    peers = _industry_peers(market, counter_id)
    chain = peers.get("chain") or {}
    sharelist_ids = _collect_sharelist_ids(chain)
    unique_stocks: Dict[str, Dict[str, Any]] = {}
    if sharelist_ids:
        # executor.map keeps input order even when requests complete out of order.
        # The pool queues IDs beyond max_workers, so callers do not need to batch them.
        with ThreadPoolExecutor(
            max_workers=min(INDUSTRY_SHARELIST_WORKERS, len(sharelist_ids))
        ) as executor:
            stocks_by_sharelist = executor.map(_sharelist_stocks, sharelist_ids)
            for stocks in stocks_by_sharelist:
                for stock in stocks:
                    symbol = _stock_symbol(stock)
                    if symbol:
                        unique_stocks[symbol] = stock
    return {
        "chain": chain,
        "stocks": list(unique_stocks.values()),
        "constituentCount": len(unique_stocks),
    }


def _cached_industry_members(market: str, counter_id: str) -> Dict[str, Any]:
    cache_key = f"{market}:{counter_id}"
    cached = INDUSTRY_MEMBERS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < INDUSTRY_MEMBERS_CACHE_TTL:
        return cached[1]
    with _industry_cache_lock(f"members:{cache_key}"):
        cached = INDUSTRY_MEMBERS_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < INDUSTRY_MEMBERS_CACHE_TTL:
            return cached[1]
        payload = _industry_members(market, counter_id)
        INDUSTRY_MEMBERS_CACHE[cache_key] = (time.time(), payload)
        return payload


def _fetch_industry_turnovers(
    market: str,
    industries: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    ctx = get_quote_context()
    if not ctx or not industries:
        return {}

    members_by_code: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(
        max_workers=min(INDUSTRY_ACTIVITY_WORKERS, len(industries))
    ) as executor:
        futures = {
            str(industry.get("code") or ""): executor.submit(
                _cached_industry_members,
                market,
                str(industry.get("code") or ""),
            )
            for industry in industries
            if industry.get("code")
        }
        for code, future in futures.items():
            try:
                members_by_code[code] = future.result()
            except Exception as exc:
                logger.warning("Longbridge 行业 %s 成交额成分获取失败: %s", code, exc)

    stock_by_symbol: Dict[str, Dict[str, Any]] = {}
    symbols_by_industry: Dict[str, List[str]] = {}
    for code, members in members_by_code.items():
        symbols: List[str] = []
        for stock in members.get("stocks") or []:
            symbol = _stock_symbol(stock)
            if not symbol:
                continue
            stock_by_symbol[symbol] = stock
            symbols.append(symbol)
        symbols_by_industry[code] = list(dict.fromkeys(symbols))

    turnover_by_symbol: Dict[str, float] = {}
    symbols = list(stock_by_symbol)
    try:
        for offset in range(0, len(symbols), 50):
            for quote in ctx.quote(symbols[offset:offset + 50]):
                turnover = safe_float(getattr(quote, "turnover", None), None)
                if turnover is not None:
                    turnover_by_symbol[str(getattr(quote, "symbol", ""))] = turnover
    except Exception as exc:
        logger.warning("Longbridge %s 行业成交额行情获取失败: %s", market, exc)

    result: Dict[str, Optional[float]] = {}
    for code, industry_symbols in symbols_by_industry.items():
        values = [
            turnover_by_symbol[symbol]
            for symbol in industry_symbols
            if symbol in turnover_by_symbol
        ]
        result[code] = sum(values) if values else None
    return result


def _fetch_industry_stocks(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ctx = get_quote_context()
    if not ctx:
        return []

    stock_by_symbol = {
        symbol: stock
        for stock in stocks
        if (symbol := _stock_symbol(stock))
    }
    symbols = list(stock_by_symbol)
    quote_map: Dict[str, Any] = {}
    static_map: Dict[str, Any] = {}
    try:
        for offset in range(0, len(symbols), 50):
            batch = symbols[offset:offset + 50]
            quote_map.update({item.symbol: item for item in ctx.quote(batch)})
            static_map.update({item.symbol: item for item in ctx.static_info(batch)})
    except Exception as exc:
        logger.warning("Longbridge 行业成分股行情获取失败: %s", exc)
        return []

    result: List[Dict[str, Any]] = []
    for symbol, stock in stock_by_symbol.items():
        quote = quote_map.get(symbol)
        if not quote:
            continue
        price = safe_float(getattr(quote, "last_done", None), None)
        previous_close = safe_float(getattr(quote, "prev_close", None), None)
        if price is None:
            continue
        change_amount = price - (previous_close or price)
        static_info = static_map.get(symbol)
        shares = None
        if static_info:
            shares = (
                safe_float(getattr(static_info, "total_shares", None), None)
                or safe_float(getattr(static_info, "circulating_shares", None), None)
            )
        result.append({
            "name": _pick_name(symbol, static_map, str(stock.get("name") or symbol)),
            "code": symbol,
            "price": price,
            "changePercent": compute_change_percent(price, change_amount),
            "changeAmount": change_amount,
            "marketValue": shares * price if shares else None,
            "turnover": safe_float(getattr(quote, "turnover", None), None),
            "tradeDate": to_iso_time(getattr(quote, "timestamp", "")),
            "source": "Longbridge",
            "isFallback": False,
        })

    result.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
    return result


def _industry_constituents(
    market: str,
    counter_id: str,
    industry_meta: Dict[str, Any],
) -> Dict[str, Any]:
    cache_key = f"{market}:{counter_id}"
    cached = INDUSTRY_STOCK_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < INDUSTRY_HEATMAP_CACHE_TTL:
        return cached[1]

    # Single-flight per industry: concurrent page requests wait for the first load
    # and then reuse its cache instead of duplicating all upstream calls.
    with _industry_cache_lock(cache_key):
        cached = INDUSTRY_STOCK_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < INDUSTRY_HEATMAP_CACHE_TTL:
            return cached[1]

        members = _industry_members(market, counter_id)
        chain = members["chain"]

        payload = {
            **industry_meta,
            "name": str(chain.get("name") or industry_meta.get("name") or ""),
            "stocks": _fetch_industry_stocks(members["stocks"]),
            "constituentCount": members["constituentCount"],
        }
        INDUSTRY_STOCK_CACHE[cache_key] = (time.time(), payload)
        return payload


def _industry_group_constituents(
    market: str,
    group: Dict[str, Any],
) -> Dict[str, Any]:
    group_code = str(group.get("code") or group.get("name") or "")
    cache_key = f"{market}:{group_code}"
    cached = INDUSTRY_GROUP_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < INDUSTRY_HEATMAP_CACHE_TTL:
        return cached[1]

    all_industries = group.get("industries") or []
    industries = all_industries[:6]
    members_by_code: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(
        max_workers=min(INDUSTRY_GROUP_WORKERS, max(1, len(industries)))
    ) as executor:
        futures = {
            str(industry.get("code") or ""): executor.submit(
                _industry_members,
                market,
                str(industry.get("code") or ""),
            )
            for industry in industries
            if industry.get("code")
        }
        for code, future in futures.items():
            try:
                members_by_code[code] = future.result()
            except Exception as exc:
                logger.warning("Longbridge 行业 %s 成分获取失败: %s", code, exc)

    all_stocks: Dict[str, Dict[str, Any]] = {}
    for members in members_by_code.values():
        for stock in members.get("stocks") or []:
            symbol = _stock_symbol(stock)
            if symbol:
                all_stocks[symbol] = stock
    snapshot_by_code = {
        item["code"]: item
        for item in _fetch_industry_stocks(list(all_stocks.values()))
    }

    populated: List[Dict[str, Any]] = []
    for industry in industries:
        code = str(industry.get("code") or "")
        members = members_by_code.get(code) or {}
        stocks = [
            snapshot_by_code[symbol]
            for stock in members.get("stocks") or []
            if (symbol := _stock_symbol(stock)) in snapshot_by_code
        ]
        stocks.sort(key=lambda item: item.get("marketValue") or 0, reverse=True)
        populated.append({
            **industry,
            "stocks": stocks[:35],
            "constituentCount": members.get("constituentCount", 0),
        })

    payload = {
        "name": group.get("name") or "",
        "code": group_code,
        "industries": populated,
        "industryCount": len(all_industries),
        "displayedIndustryCount": len(populated),
    }
    INDUSTRY_GROUP_CACHE[cache_key] = (time.time(), payload)
    return payload


def fetch_industry_heatmap(
    market: str = "CN",
    industry_code: str = "",
    group_code: str = "",
    include_stocks: bool = True,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    normalized_market = market.upper()
    if normalized_market not in {"CN", "HK", "US"}:
        normalized_market = "CN"

    cached = INDUSTRY_HEATMAP_CACHE.get(normalized_market)
    if not force_refresh and cached and time.time() - cached[0] < INDUSTRY_HEATMAP_CACHE_TTL:
        summary = cached[1]
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            gainers_future = executor.submit(_industry_rank, normalized_market, 0)
            market_caps_future = executor.submit(_industry_rank, normalized_market, 3)
            gainers = gainers_future.result()
            market_caps = market_caps_future.result()
        cap_by_id: Dict[str, float] = {}
        for parent in market_caps.get("items") or []:
            for item in parent.get("lists") or []:
                counter_id = str(item.get("counter_id") or "")
                if counter_id:
                    cap_by_id[counter_id] = safe_float(item.get("value_data"), 0) or 0

        groups: List[Dict[str, Any]] = []
        industries: List[Dict[str, Any]] = []
        for parent in gainers.get("items") or []:
            children: List[Dict[str, Any]] = []
            for item in parent.get("lists") or []:
                counter_id = str(item.get("counter_id") or "")
                child = {
                    "name": str(item.get("name") or ""),
                    "code": counter_id,
                    "parentName": str(parent.get("name") or ""),
                    "changePercent": (safe_float(item.get("chg"), 0) or 0) * 100,
                    "marketValue": cap_by_id.get(counter_id, 0),
                    "delayed": bool(item.get("delay")),
                    "dayLeader": {
                        "name": str(item.get("leading_name") or ""),
                        "code": str(item.get("leading_ticker") or ""),
                        "price": safe_float(item.get("leading_last_done"), None),
                        "changePercent": (safe_float(item.get("leading_chg"), 0) or 0) * 100,
                    },
                }
                if child["name"]:
                    children.append(child)
                    industries.append(child)
            if children:
                group_market_value = sum(item["marketValue"] for item in children)
                weighted_change = (
                    sum(
                        item["changePercent"] * item["marketValue"]
                        for item in children
                    ) / group_market_value
                    if group_market_value
                    else sum(item["changePercent"] for item in children) / len(children)
                )
                groups.append({
                    "name": str(parent.get("name") or ""),
                    "code": str(parent.get("counter_id") or parent.get("name") or ""),
                    "changePercent": weighted_change,
                    "marketValue": group_market_value,
                    "industries": children,
                })

        activity_industries = sorted(
            industries,
            key=lambda item: item.get("marketValue") or 0,
            reverse=True,
        )[:INDUSTRY_ACTIVITY_LIMIT]
        turnover_by_id = _fetch_industry_turnovers(
            normalized_market,
            activity_industries,
        )
        for industry in industries:
            industry["turnover"] = turnover_by_id.get(str(industry.get("code") or ""))
        for group in groups:
            turnovers = [
                item.get("turnover")
                for item in group["industries"]
                if item.get("turnover") is not None
            ]
            group["turnover"] = sum(turnovers) if turnovers else None

        summary = {
            "groups": groups,
            "industries": industries,
            "turnoverCoverage": {
                "industryCount": len(turnover_by_id),
                "totalIndustryCount": len(industries),
                "selection": "largest-market-value",
            },
        }
        INDUSTRY_HEATMAP_CACHE[normalized_market] = (time.time(), summary)

    if not include_stocks:
        return {
            "market": normalized_market,
            "source": "Longbridge",
            "updatedAt": datetime.now().isoformat(),
            **summary,
        }

    groups = summary.get("groups") or []
    selected_group = next(
        (item for item in groups if item.get("code") == group_code),
        None,
    )
    if not selected_group and industry_code:
        selected_group = next(
            (
                group
                for group in groups
                if any(
                    industry.get("code") == industry_code
                    for industry in group.get("industries") or []
                )
            ),
            None,
        )
    selected_group = selected_group or (groups[0] if groups else {})
    return {
        "market": normalized_market,
        "source": "Longbridge",
        "updatedAt": datetime.now().isoformat(),
        **summary,
        "selectedGroup": (
            _industry_group_constituents(normalized_market, selected_group)
            if selected_group
            else {}
        ),
    }


def fetch_industry_detail(
    market: str,
    industry_code: str,
) -> Dict[str, Any]:
    summary = fetch_industry_heatmap(market, include_stocks=False)
    industry_meta = next(
        (
            industry
            for industry in summary.get("industries") or []
            if industry.get("code") == industry_code
        ),
        {},
    )
    if not industry_meta:
        return {
            "market": summary["market"],
            "source": "Longbridge",
            "updatedAt": datetime.now().isoformat(),
            "industry": {},
        }
    return {
        "market": summary["market"],
        "source": "Longbridge",
        "updatedAt": datetime.now().isoformat(),
        "industry": _industry_constituents(
            summary["market"],
            industry_code,
            industry_meta,
        ),
    }


def fetch_market_calendar(market: str, start: date, end: date) -> Dict[str, Any]:
    normalized = market.upper()
    if normalized not in {"CN", "HK", "US"}:
        raise ValueError(f"unsupported market: {market}")
    ctx = get_quote_context()
    if not ctx or Market is None:
        return {"market": normalized, "tradingDays": [], "halfTradingDays": [], "sessions": []}
    market_value = {"CN": Market.CN, "HK": Market.HK, "US": Market.US}[normalized]
    days = ctx.trading_days(market_value, start, end)
    sessions = []
    for market_session in ctx.trading_session():
        if str(market_session.market).split(".")[-1] != normalized:
            continue
        for item in market_session.trade_sessions:
            if str(item.trade_session).split(".")[-1] != "Intraday":
                continue
            sessions.append({
                "open": item.begin_time.strftime("%H:%M"),
                "close": item.end_time.strftime("%H:%M"),
            })
    return {
        "market": normalized,
        "tradingDays": [item.isoformat() for item in days.trading_days],
        "halfTradingDays": [item.isoformat() for item in days.half_trading_days],
        "sessions": sessions,
    }
