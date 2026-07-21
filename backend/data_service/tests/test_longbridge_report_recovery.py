import unittest
from datetime import datetime

from providers.longbridge import _exchange_trading_date


class LongbridgeReportRecoveryTests(unittest.TestCase):
    def test_us_minutes_are_grouped_by_exchange_trading_date(self):
        self.assertEqual(
            _exchange_trading_date(datetime(2026, 7, 18, 3, 59), ".DJI.US").isoformat(),
            "2026-07-17",
        )

    def test_cn_minutes_keep_beijing_trading_date(self):
        self.assertEqual(
            _exchange_trading_date(datetime(2026, 7, 20, 9, 30), "000001.SH").isoformat(),
            "2026-07-20",
        )


if __name__ == "__main__":
    unittest.main()
