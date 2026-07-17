from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from providers import legacy_market, longbridge, sectors_ths
from providers.common import merge_with_lazy_fallback
from providers.market_catalog import GLOBAL_INDEX_ORDER, GLOBAL_MARKET_REGIONS

OVERVIEW_CACHE_TTL = 120
OVERVIEW_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}


def _source_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fallback_count = sum(1 for item in rows if item.get("isFallback"))
    return {
        "total": len(rows),
        "longbridge": len(rows) - fallback_count,
        "fallback": fallback_count,
    }


def _global_groups(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_code = {item["code"]: item for item in rows}
    return [
        {
            "key": region["key"],
            "title": region["title"],
            "subtitle": region["subtitle"],
            "indices": [
                by_code[item["code"]]
                for item in region["indices"]
                if item["code"] in by_code
            ],
        }
        for region in GLOBAL_MARKET_REGIONS
    ]


def _slice_top_bottom(boards: List[Dict[str, Any]], count: int = 6) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ordered = sorted(boards, key=lambda item: item.get("changePercent", 0), reverse=True)
    if not ordered:
        return [], []
    return ordered[:count], list(reversed(ordered[-count:]))


def _enrich_boards(boards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for board in boards:
        enriched.append({
            **board,
            "topStocks": sectors_ths.fetch_board_top_stocks(board["name"]),
        })
    return enriched


def build_dashboard_overview(*, news_digest: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    cache_key = "market-only"
    cached = OVERVIEW_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < OVERVIEW_CACHE_TTL:
        return cached[1]

    longbridge_global = longbridge.fetch_global_indices()
    longbridge_a = longbridge.fetch_a_indices()
    longbridge_hk = longbridge.fetch_hk_indices()
    longbridge_us = longbridge.fetch_us_indices()
    global_indices = merge_with_lazy_fallback(
        longbridge_global,
        legacy_market.fetch_global_indices,
        GLOBAL_INDEX_ORDER,
    )
    a_indices = merge_with_lazy_fallback(
        longbridge_a,
        legacy_market.fetch_a_indices,
        [item["code"] for item in longbridge.A_INDEX_SYMBOLS],
    )
    hk_indices = merge_with_lazy_fallback(
        longbridge_hk,
        legacy_market.fetch_hk_indices,
        [item["code"] for item in longbridge.HK_INDEX_SYMBOLS],
    )
    us_indices = merge_with_lazy_fallback(
        longbridge_us,
        legacy_market.fetch_us_indices,
        [item["code"] for item in longbridge.US_INDEX_SYMBOLS],
    )
    boards = sectors_ths.fetch_a_boards()
    breadth = sectors_ths.fetch_market_breadth()
    leaders, laggards = _slice_top_bottom(boards)
    leaders = _enrich_boards(leaders)
    laggards = _enrich_boards(laggards)

    payload = {
        "globalIndices": global_indices,
        "globalMarketGroups": _global_groups(global_indices),
        "majorIndices": {
            "aShares": a_indices,
            "hk": hk_indices,
            "us": us_indices,
        },
        "aShareSectors": {
            "breadth": breadth,
            "heatmap": boards,
            "leaders": leaders,
            "laggards": laggards,
        },
        "newsDigest": [],
        "updatedAt": datetime.now().isoformat(),
        "sources": {
            "market": "longbridge-first",
            "sectors": "ths",
        },
        "sourceSummary": {
            "global": _source_summary(global_indices),
            "majorIndices": _source_summary([*a_indices, *hk_indices, *us_indices]),
        },
        "sourceStatus": {
            "longbridge": longbridge.diagnostics(),
        },
    }
    OVERVIEW_CACHE[cache_key] = (time.time(), payload)
    return payload
