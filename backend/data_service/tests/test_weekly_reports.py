import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from providers import longbridge
from services import weekly_reports
from services.weekly_reports import WeeklyReportError, build_weekly_market_context


class WeeklyReportSchemaTests(unittest.TestCase):
    def test_longbridge_weekly_candle_uses_previous_week_close(self):
        candles = [
            SimpleNamespace(
                timestamp=datetime(2026, 7, 6),
                open=4059.19,
                high=4100,
                low=3950,
                close=3996.16,
                volume=100,
                turnover=1000,
            ),
            SimpleNamespace(
                timestamp=datetime(2026, 7, 13),
                open=3966.02,
                high=4030,
                low=3700,
                close=3764.16,
                volume=200,
                turnover=2000,
            ),
        ]

        class FakeContext:
            def history_candlesticks_by_date(self, *_args):
                return candles

        fake_period = SimpleNamespace(Week="week")
        fake_adjust = SimpleNamespace(NoAdjust="none")
        fake_sessions = SimpleNamespace(Intraday="intraday")
        with (
            patch.object(longbridge, "get_quote_context", return_value=FakeContext()),
            patch.object(longbridge, "Period", fake_period),
            patch.object(longbridge, "AdjustType", fake_adjust),
            patch.object(longbridge, "TradeSessions", fake_sessions),
            patch.object(longbridge, "GLOBAL_INDEX_SYMBOLS", [
                {"name": "上证指数", "code": "000001.SH", "symbol": "000001.SH"},
            ]),
            patch.object(longbridge, "A_INDEX_SYMBOLS", []),
            patch.object(longbridge, "HK_INDEX_SYMBOLS", []),
            patch.object(longbridge, "US_INDEX_SYMBOLS", []),
        ):
            rows = longbridge.fetch_weekly_report_indices(
                date(2026, 7, 13),
                date(2026, 7, 17),
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["barStartDate"], "2026-07-13")
        self.assertEqual(rows[0]["barEndDate"], "2026-07-17")
        self.assertAlmostEqual(rows[0]["previousWeekClose"], 3996.16)
        self.assertAlmostEqual(rows[0]["changeAmount"], -232.0)
        self.assertAlmostEqual(rows[0]["changePercent"], -5.805573, places=6)
        self.assertEqual(rows[0]["source"], "Longbridge Weekly Candlestick")

    @patch("services.weekly_reports.legacy_market.fetch_sina_weekly_indices", return_value=[])
    @patch("services.weekly_reports.legacy_market.fetch_tradingview_weekly_indices", return_value=[])
    @patch("services.weekly_reports.longbridge.fetch_weekly_report_indices")
    def test_weekly_schema_groups_broker_candles_and_reports_gaps(
        self,
        mock_fetch,
        _mock_tradingview,
        _mock_sina,
    ):
        mock_fetch.return_value = [
            {
                "name": "上证指数",
                "code": "000001.SH",
                "barStartDate": "2026-07-13",
                "barEndDate": "2026-07-17",
                "open": 3966.02,
                "high": 4030.0,
                "low": 3700.0,
                "close": 3764.16,
                "previousWeekClose": 3996.16,
                "changeAmount": -232.0,
                "changePercent": -5.805,
                "volume": 2932831757,
                "turnover": 6203620662534.8,
                "source": "Longbridge Weekly Candlestick",
                "isFallback": False,
            },
        ]
        period = {
            "startDate": "2026-07-13",
            "endDate": "2026-07-17",
            "anchorDate": "2026-07-17",
            "timezone": "Asia/Shanghai",
            "isCurrentWeek": True,
        }

        context = build_weekly_market_context(period)

        self.assertEqual(context["schemaVersion"], 2)
        self.assertEqual(context["sourcePolicy"]["mode"], "preferred-weekly-candlestick-with-fallback")
        self.assertEqual(context["coverage"]["requestedIndexCount"], 26)
        self.assertEqual(context["coverage"]["availableIndexCount"], 1)
        self.assertEqual(context["coverage"]["unavailableIndexCount"], 25)
        self.assertFalse(context["coverage"]["complete"])
        asia = next(item for item in context["globalOverview"] if item["key"] == "asiaPacific")
        self.assertEqual(asia["indices"][0]["code"], "000001.SH")
        self.assertTrue(asia["indices"][0]["isPartial"])
        cn = next(item for item in context["majorMarkets"] if item["market"] == "CN")
        self.assertEqual(cn["indices"][0]["code"], "000001.SH")
        self.assertEqual(len(context["coverage"]["unavailableIndices"]), 25)

    def test_weekend_window_starts_after_all_markets_close(self):
        timezone = ZoneInfo("Asia/Shanghai")
        self.assertIsNone(weekly_reports.weekend_generation_anchor(
            datetime(2026, 7, 18, 5, 59, tzinfo=timezone)
        ))
        self.assertEqual(
            weekly_reports.weekend_generation_anchor(
                datetime(2026, 7, 18, 6, 0, tzinfo=timezone)
            ),
            date(2026, 7, 17),
        )
        self.assertIsNone(weekly_reports.weekend_generation_anchor(
            datetime(2026, 7, 20, 6, 0, tzinfo=timezone)
        ))

    @patch("services.weekly_reports.build_weekly_market_context")
    def test_incomplete_week_is_never_saved_as_final(self, mock_build):
        mock_build.return_value = {
            "schemaVersion": 2,
            "reportType": "weekly",
            "status": "draft",
            "period": weekly_reports.weekly_period_for_date(date(2026, 7, 17)),
            "coverage": {"complete": False, "unavailableIndexCount": 1},
        }
        now = datetime(2026, 7, 18, 6, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
        with TemporaryDirectory() as tmp, patch.object(weekly_reports, "WEEKLY_CACHE_DIR", Path(tmp)):
            with self.assertRaises(WeeklyReportError):
                weekly_reports.capture_weekly_market_context(date(2026, 7, 17), now=now)
            self.assertEqual(list(Path(tmp).rglob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
