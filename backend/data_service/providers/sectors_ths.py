from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Dict, List

import akshare as ak
import requests

from .common import safe_float
from .legacy_market import SINA_HEADERS

logger = logging.getLogger(__name__)

REPRESENTATIVE_STOCKS: Dict[str, List[Dict[str, str]]] = {
    "半导体": [
        {"name": "中芯国际", "code": "688981"},
        {"name": "北方华创", "code": "002371"},
        {"name": "韦尔股份", "code": "603501"},
    ],
    "白酒": [
        {"name": "贵州茅台", "code": "600519"},
        {"name": "五粮液", "code": "000858"},
        {"name": "泸州老窖", "code": "000568"},
    ],
    "证券": [
        {"name": "中信证券", "code": "600030"},
        {"name": "东方财富", "code": "300059"},
        {"name": "华泰证券", "code": "601688"},
    ],
    "银行": [
        {"name": "招商银行", "code": "600036"},
        {"name": "工商银行", "code": "601398"},
        {"name": "农业银行", "code": "601288"},
    ],
    "软件开发": [
        {"name": "金山办公", "code": "688111"},
        {"name": "用友网络", "code": "600588"},
        {"name": "科大讯飞", "code": "002230"},
    ],
    "消费电子": [
        {"name": "立讯精密", "code": "002475"},
        {"name": "工业富联", "code": "601138"},
        {"name": "歌尔股份", "code": "002241"},
    ],
    "通信设备": [
        {"name": "中兴通讯", "code": "000063"},
        {"name": "中际旭创", "code": "300308"},
        {"name": "新易盛", "code": "300502"},
    ],
    "汽车整车": [
        {"name": "比亚迪", "code": "002594"},
        {"name": "上汽集团", "code": "600104"},
        {"name": "长城汽车", "code": "601633"},
    ],
    "电池": [
        {"name": "宁德时代", "code": "300750"},
        {"name": "亿纬锂能", "code": "300014"},
        {"name": "国轩高科", "code": "002074"},
    ],
    "光伏设备": [
        {"name": "隆基绿能", "code": "601012"},
        {"name": "阳光电源", "code": "300274"},
        {"name": "通威股份", "code": "600438"},
    ],
    "有色金属": [
        {"name": "紫金矿业", "code": "601899"},
        {"name": "洛阳钼业", "code": "603993"},
        {"name": "中国铝业", "code": "601600"},
    ],
    "石油行业": [
        {"name": "中国石油", "code": "601857"},
        {"name": "中国海油", "code": "600938"},
        {"name": "中国石化", "code": "600028"},
    ],
    "航天航空": [
        {"name": "中航沈飞", "code": "600760"},
        {"name": "中航西飞", "code": "000768"},
        {"name": "航发动力", "code": "600893"},
    ],
    "生物制品": [
        {"name": "迈瑞医疗", "code": "300760"},
        {"name": "药明康德", "code": "603259"},
        {"name": "恒瑞医药", "code": "600276"},
    ],
    "化学制药": [
        {"name": "恒瑞医药", "code": "600276"},
        {"name": "药明康德", "code": "603259"},
        {"name": "科伦药业", "code": "002422"},
    ],
    "房地产开发": [
        {"name": "保利发展", "code": "600048"},
        {"name": "招商蛇口", "code": "001979"},
        {"name": "万科A", "code": "000002"},
    ],
    "电力行业": [
        {"name": "长江电力", "code": "600900"},
        {"name": "国电南瑞", "code": "600406"},
        {"name": "华能水电", "code": "600025"},
    ],
    "煤炭行业": [
        {"name": "中国神华", "code": "601088"},
        {"name": "陕西煤业", "code": "601225"},
        {"name": "中煤能源", "code": "601898"},
    ],
    "贵金属": [
        {"name": "山东黄金", "code": "600547"},
        {"name": "中金黄金", "code": "600489"},
        {"name": "紫金矿业", "code": "601899"},
    ],
    "人工智能": [
        {"name": "科大讯飞", "code": "002230"},
        {"name": "寒武纪", "code": "688256"},
        {"name": "海康威视", "code": "002415"},
    ],
}


def fetch_market_breadth() -> Dict[str, Any]:
    try:
        df = ak.stock_market_activity_legu()
        breadth: Dict[str, Any] = {}
        for _, row in df.iterrows():
            key = str(row["item"]).strip()
            breadth[key] = safe_float(row["value"], None)

        up_count = int(breadth.get("上涨") or 0)
        down_count = int(breadth.get("下跌") or 0)
        flat_count = int(breadth.get("平盘") or 0)
        limit_up = int(breadth.get("涨停") or 0)
        limit_down = int(breadth.get("跌停") or 0)
        total_stocks = up_count + down_count + flat_count + int(breadth.get("停牌") or 0)
        win_rate = round((up_count / (up_count + down_count) * 100), 2) if (up_count + down_count) else 0
        return {
            "upCount": up_count,
            "downCount": down_count,
            "flatCount": flat_count,
            "limitUp": limit_up,
            "limitDown": limit_down,
            "totalStocks": total_stocks,
            "winRate": win_rate,
            "updateTime": str(breadth.get("统计日期", "")),
        }
    except Exception as exc:
        logger.warning("获取市场广度失败: %s", exc)
        return {
            "upCount": 0,
            "downCount": 0,
            "flatCount": 0,
            "limitUp": 0,
            "limitDown": 0,
            "totalStocks": 0,
            "winRate": 0,
            "updateTime": "",
        }


def fetch_a_boards() -> List[Dict[str, Any]]:
    try:
        df = ak.stock_board_industry_summary_ths()
        names = ak.stock_board_industry_name_ths()
        code_map = {
            str(row.get("name", "")).strip(): str(row.get("code", "")).strip()
            for _, row in names.iterrows()
            if str(row.get("name", "")).strip()
        }
        result: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            name = str(row.get("板块", "")).strip()
            if not name:
                continue
            leader_name = str(row.get("领涨股", "")).strip()
            leader_price = safe_float(row.get("领涨股-最新价"), None)
            leader_change = safe_float(row.get("领涨股-涨跌幅"), None)
            top_stocks = []
            if leader_name:
                top_stocks.append({
                    "name": leader_name,
                    "code": "",
                    "price": leader_price or 0,
                    "changePercent": leader_change or 0,
                    "changeAmount": 0,
                    "marketValue": None,
                    "source": "同花顺",
                })
            result.append({
                "name": name,
                "code": code_map.get(name, ""),
                "changePercent": safe_float(row.get("涨跌幅"), 0) or 0,
                "netInflow": (safe_float(row.get("净流入"), None) or 0) * 100_000_000,
                "marketValue": None,
                "eventCount": None,
                "upCount": int(safe_float(row.get("上涨家数"), 0) or 0),
                "downCount": int(safe_float(row.get("下跌家数"), 0) or 0),
                "totalTurnover": (safe_float(row.get("总成交额"), None) or 0) * 100_000_000,
                "topStocks": top_stocks,
                "source": "同花顺",
            })
        return result
    except Exception as exc:
        logger.warning("获取A股板块失败: %s", exc)
        return []


def _to_sina_symbol(code: str) -> str:
    return f"sh{code}" if code.startswith(("6", "9")) or code.startswith("688") else f"sz{code}"


@lru_cache(maxsize=128)
def _fetch_stock_quotes(codes_key: str) -> List[Dict[str, Any]]:
    codes = [code for code in codes_key.split(",") if code]
    if not codes:
        return []
    symbols = [_to_sina_symbol(code) for code in codes]
    response = requests.get(
        "https://hq.sinajs.cn/list=" + ",".join(symbols),
        headers=SINA_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    result: List[Dict[str, Any]] = []
    for match in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', response.text):
        symbol, payload = match.groups()
        fields = payload.split(",")
        if len(fields) < 32:
            continue
        code = symbol[2:]
        previous_close = safe_float(fields[2], None)
        price = safe_float(fields[3], None)
        if previous_close is None or price is None:
            continue
        change_amount = price - previous_close
        change_percent = (change_amount / previous_close * 100) if previous_close else 0
        result.append({
            "name": fields[0] or code,
            "code": code,
            "price": price,
            "changePercent": round(change_percent, 2),
            "changeAmount": round(change_amount, 2),
            "open": safe_float(fields[1], None),
            "high": safe_float(fields[4], None),
            "low": safe_float(fields[5], None),
            "previousClose": previous_close,
            "volume": safe_float(fields[8], None),
            "turnover": safe_float(fields[9], None),
            "source": "Sina",
        })
    return result


def _representative_mapping(board_name: str) -> List[Dict[str, str]]:
    if board_name in REPRESENTATIVE_STOCKS:
        return REPRESENTATIVE_STOCKS[board_name]
    for key, stocks in REPRESENTATIVE_STOCKS.items():
        if key in board_name or board_name in key:
            return stocks
    return []


def fetch_board_top_stocks(board_name: str) -> List[Dict[str, Any]]:
    boards = fetch_a_boards()
    board = next((item for item in boards if item["name"] == board_name), None)
    fallback = board.get("topStocks", []) if board else []
    mapped = _representative_mapping(board_name)
    if not mapped:
        return fallback
    try:
        quotes = _fetch_stock_quotes(",".join(stock["code"] for stock in mapped[:3]))
        quote_map = {item["code"]: item for item in quotes}
        result: List[Dict[str, Any]] = []
        for stock in mapped[:3]:
            quote = quote_map.get(stock["code"])
            if quote:
                result.append({**quote, "name": stock["name"]})
        if len(result) < 2:
            for item in fallback:
                if item["name"] not in {stock["name"] for stock in result}:
                    result.append(item)
        return result[:3] or fallback
    except Exception as exc:
        logger.warning("获取板块代表股失败 %s: %s", board_name, exc)
        return fallback
