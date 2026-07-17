import unittest
from unittest.mock import Mock, patch

from providers.legacy_market import fetch_tradingview_indices


class TradingViewIndexTests(unittest.TestCase):
    @patch("providers.legacy_market.requests.post")
    def test_batch_response_is_normalized_to_dashboard_codes(self, mock_post):
        response = Mock()
        response.json.return_value = {
            "data": [
                {
                    "s": "XETR:DAX",
                    "d": [24735.52, -0.72, -179.97, 24755.09, 24850.75, 24692.51, 10019939],
                },
                {
                    "s": "UNKNOWN:INDEX",
                    "d": [100, 1, 1, 99, 101, 98, None],
                },
            ],
        }
        mock_post.return_value = response

        rows = fetch_tradingview_indices([
            {"name": "德国DAX", "code": "DAX.DE", "symbol": "XETR:DAX"},
        ])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "DAX.DE")
        self.assertEqual(rows[0]["source"], "TradingView")
        self.assertAlmostEqual(rows[0]["previousClose"], 24915.49)
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
