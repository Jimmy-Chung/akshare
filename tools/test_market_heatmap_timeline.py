import argparse
from datetime import date, datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_heatmap_timeline import calendar_slots, capture_once, is_market_open


class MarketScheduleTests(unittest.TestCase):
    def test_cn_slots_are_fixed_and_include_session_close(self):
        slots = calendar_slots(
            "CN",
            date(2026, 7, 13),
            {
                "tradingDays": ["2026-07-13"],
                "halfTradingDays": [],
                "sessions": [
                    {"open": "09:30", "close": "11:30"},
                    {"open": "13:00", "close": "14:57"},
                ],
            },
        )
        self.assertEqual(slots[0].strftime("%H:%M"), "09:30")
        self.assertIn("10:00", [item.strftime("%H:%M") for item in slots])
        self.assertEqual(slots[-1].strftime("%H:%M"), "14:57")

    def test_us_half_day_stops_at_1300(self):
        slots = calendar_slots(
            "US",
            date(2026, 11, 27),
            {
                "tradingDays": ["2026-11-27"],
                "halfTradingDays": ["2026-11-27"],
                "sessions": [{"open": "09:30", "close": "16:00"}],
            },
        )
        self.assertEqual(slots[-1].strftime("%H:%M"), "13:00")

    def test_closed_day_has_no_slots(self):
        self.assertEqual(
            calendar_slots(
                "HK",
                date(2026, 7, 1),
                {"tradingDays": [], "halfTradingDays": [], "sessions": []},
            ),
            [],
        )

    def test_session_close_uses_scheduled_slot_for_market_check(self):
        args = argparse.Namespace(
            force=False,
            market="HK",
            trigger="session-close",
            scheduled_at="2026-07-14T16:00:00+08:00",
            app_url="http://127.0.0.1:3005",
            api_url="http://127.0.0.1:5001",
        )
        actual_execution_time = datetime(
            2026,
            7,
            14,
            16,
            0,
            5,
            tzinfo=ZoneInfo("Asia/Hong_Kong"),
        )
        self.assertFalse(is_market_open("HK", actual_execution_time)[0])

        with patch(
            "market_heatmap_timeline.is_market_open",
            wraps=is_market_open,
        ) as market_check, patch(
            "market_heatmap_timeline.ensure_services",
            side_effect=RuntimeError("stop after market check"),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop after market check"):
                capture_once(args)

        checked_moment = market_check.call_args.args[1]
        self.assertEqual(checked_moment.isoformat(), "2026-07-14T16:00:00+08:00")
        self.assertTrue(is_market_open("HK", checked_moment)[0])


if __name__ == "__main__":
    unittest.main()
