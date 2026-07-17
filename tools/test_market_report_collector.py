import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_report_collector import due_session


class ReportCollectorScheduleTests(unittest.TestCase):
    def test_midday_is_due_inside_grace_window(self):
        now = datetime(2026, 7, 17, 12, 32, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(due_session(now, set(), 300), "midday")

    def test_executed_session_is_not_repeated(self):
        now = datetime(2026, 7, 17, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertIsNone(due_session(now, {"close"}, 300))

    def test_old_session_is_not_backfilled_with_live_data(self):
        now = datetime(2026, 7, 17, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertIsNone(due_session(now, set(), 300))


if __name__ == "__main__":
    unittest.main()
