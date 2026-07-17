from __future__ import annotations

from typing import Dict, List

GLOBAL_MARKET_REGIONS: List[Dict[str, object]] = [
    {
        "key": "americas",
        "title": "美洲",
        "subtitle": "美国、加拿大与拉丁美洲主要市场",
        "indices": [
            {"name": "道琼斯", "code": ".DJI.US", "longbridge": ".DJI.US", "fallback": "^DJI", "tradingview": "TVC:DJI"},
            {"name": "标普500", "code": ".SPX.US", "longbridge": ".SPX.US", "fallback": "^GSPC", "tradingview": "SP:SPX"},
            {"name": "纳斯达克", "code": ".IXIC.US", "longbridge": ".IXIC.US", "fallback": "^IXIC", "tradingview": "NASDAQ:IXIC"},
            {"name": "加拿大TSX", "code": "GSPTSE.CA", "fallback": "^GSPTSE", "tradingview": "TSX:TSX"},
            {"name": "巴西Bovespa", "code": "BVSP.BR", "fallback": "^BVSP", "tradingview": "BMFBOVESPA:IBOV"},
        ],
    },
    {
        "key": "europe",
        "title": "欧洲",
        "subtitle": "英国、德国、法国与欧元区主要市场",
        "indices": [
            {"name": "英国富时100", "code": "FTSE.UK", "fallback": "^FTSE", "tradingview": "TVC:UKX"},
            {"name": "德国DAX", "code": "DAX.DE", "fallback": "^GDAXI", "tradingview": "XETR:DAX"},
            {"name": "法国CAC40", "code": "CAC.FR", "fallback": "^FCHI", "tradingview": "EURONEXT:PX1"},
            {"name": "欧洲Stoxx50", "code": "STOXX50.EU", "fallback": "^STOXX50E", "tradingview": "TVC:SX5E"},
        ],
    },
    {
        "key": "asiaPacific",
        "title": "亚太",
        "subtitle": "大中华区、日韩、东南亚及澳洲市场",
        "indices": [
            {"name": "上证指数", "code": "000001.SH", "longbridge": "000001.SH", "fallback": "sh000001"},
            {"name": "恒生指数", "code": "HSI.HK", "longbridge": "HSI.HK", "fallback": "rt_hkHSI"},
            {"name": "日经225", "code": "N225.JP", "fallback": "^N225", "tradingview": "TVC:NI225"},
            {"name": "韩国综合", "code": "KOSPI.KR", "fallback": "^KS11", "tradingview": "KRX:KOSPI"},
            {"name": "台湾加权", "code": "TWII.TW", "fallback": "^TWII", "tradingview": "TWSE:IX0001"},
            {"name": "新加坡海峡时报", "code": "STI.SG", "fallback": "^STI", "tradingview": "TVC:STI"},
            {"name": "澳洲标普200", "code": "AS51.AU", "fallback": "^AXJO", "tradingview": "ASX:XJO"},
        ],
    },
    {
        "key": "southAsia",
        "title": "南亚",
        "subtitle": "印度主要市场指数",
        "indices": [
            {"name": "印度Nifty50", "code": "NIFTY.IN", "fallback": "^NSEI", "tradingview": "NSE:NIFTY"},
            {"name": "印度Sensex", "code": "SENSEX.IN", "fallback": "^BSESN", "tradingview": "BSE:SENSEX"},
        ],
    },
]


def flattened_global_indices() -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for region in GLOBAL_MARKET_REGIONS:
        for item in region["indices"]:  # type: ignore[index]
            result.append(dict(item))
    return result


GLOBAL_INDEX_ORDER = [item["code"] for item in flattened_global_indices()]
