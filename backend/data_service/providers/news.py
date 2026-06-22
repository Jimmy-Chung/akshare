from __future__ import annotations

import html
import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

import requests

from . import longbridge

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 180
NEWS_CACHE: Dict[tuple[str, int], tuple[float, List[Dict[str, Any]]]] = {}

RSS_QUERIES = {
    "all": [
        ("A股 港股 美股 市场 when:1d", ["A股", "港股", "美股"]),
        ("China stocks Hong Kong stocks US stocks market when:1d", ["A股", "港股", "美股"]),
        ("全球市场 宏观 央行 when:1d", ["宏观"]),
    ],
    "cn-hk": [
        ("A股 港股 市场 when:1d", ["A股", "港股"]),
        ("中国市场 港股 宏观 when:1d", ["A股", "港股", "宏观"]),
    ],
    "us": [
        ("US stocks market Federal Reserve when:1d", ["美股", "宏观"]),
        ("Nasdaq S&P 500 market when:1d", ["美股"]),
    ],
}


def _rss_url(query: str, zh: bool = True) -> str:
    if zh:
        return (
            "https://news.google.com/rss/search?"
            + urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
        )
    return (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    )


def _extract_source(title: str) -> tuple[str, str]:
    if " - " in title:
        headline, source = title.rsplit(" - ", 1)
        return headline.strip(), source.strip()
    return title.strip(), "Google News"


def _clean_summary(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_google_news(scope: str = "all", limit: int = 12) -> List[Dict[str, Any]]:
    cache_key = (scope, limit)
    cached = NEWS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    queries = RSS_QUERIES.get(scope, RSS_QUERIES["all"])
    articles: List[Dict[str, Any]] = []
    seen_titles = set()
    for query, tags in queries:
        zh = any(tag in {"A股", "港股", "宏观"} for tag in tags)
        try:
            response = requests.get(_rss_url(query, zh=zh), timeout=12)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            for item in root.findall("./channel/item"):
                raw_title = item.findtext("title", default="")
                title, source = _extract_source(raw_title)
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                link = item.findtext("link", default="")
                published_at = item.findtext("pubDate", default="")
                summary = _clean_summary(item.findtext("description", default=""))
                articles.append({
                    "id": f"google-news:{hash((title, link))}",
                    "title": title,
                    "source": source,
                    "publishedAt": published_at,
                    "url": link,
                    "marketTags": tags,
                    "summary": summary or title,
                    "isFallback": True,
                })
                if len(articles) >= limit:
                    NEWS_CACHE[cache_key] = (time.time(), articles[:limit])
                    return articles[:limit]
        except Exception as exc:
            logger.warning("获取新闻失败 %s: %s", query, exc)
    NEWS_CACHE[cache_key] = (time.time(), articles[:limit])
    return articles[:limit]


def fetch_market_news(scope: str = "all", limit: int = 12) -> List[Dict[str, Any]]:
    primary = longbridge.fetch_news(scope=scope, limit=limit)
    if len(primary) >= limit:
        return primary[:limit]

    fallback = fetch_google_news(scope=scope, limit=limit)
    seen_titles = {item["title"] for item in primary}
    combined = [*primary]
    combined.extend(item for item in fallback if item["title"] not in seen_titles)
    return combined[:limit]
