import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from providers import longbridge


class IndustryConcurrencyTests(unittest.TestCase):
    def test_sharelists_are_bounded_and_merged_in_source_order(self):
        sharelist_ids = [str(index) for index in range(1, 15)]
        chain = {
            "name": "测试行业",
            "next": [{"sharelist_id": sharelist_id} for sharelist_id in sharelist_ids],
        }
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_sharelist(sharelist_id):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                # Reverse completion order to prove result order is not completion order.
                time.sleep((15 - int(sharelist_id)) * 0.001)
                return [{"code": sharelist_id, "market": "CN"}]
            finally:
                with state_lock:
                    active -= 1

        with (
            patch.object(longbridge, "_industry_peers", return_value={"chain": chain}),
            patch.object(longbridge, "_sharelist_stocks", side_effect=fake_sharelist),
        ):
            result = longbridge._industry_members("CN", "industry")

        self.assertGreater(maximum_active, 1)
        self.assertLessEqual(maximum_active, longbridge.INDUSTRY_SHARELIST_WORKERS)
        self.assertEqual(
            [stock["code"] for stock in result["stocks"]],
            sharelist_ids,
        )
        self.assertEqual(result["constituentCount"], 14)

    def test_concurrent_same_industry_uses_single_flight_cache(self):
        cache_key = "CN:single-flight-test"
        longbridge.INDUSTRY_STOCK_CACHE.pop(cache_key, None)
        calls = 0
        calls_lock = threading.Lock()

        def fake_members(_market, _counter_id):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)
            return {
                "chain": {"name": "测试行业"},
                "stocks": [{"code": "1", "market": "CN"}],
                "constituentCount": 1,
            }

        with (
            patch.object(longbridge, "_industry_members", side_effect=fake_members),
            patch.object(longbridge, "_fetch_industry_stocks", return_value=[{"code": "1.CN"}]),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [
                executor.submit(
                    longbridge._industry_constituents,
                    "CN",
                    "single-flight-test",
                    {"code": "single-flight-test"},
                )
                for _ in range(2)
            ]
            results = [future.result() for future in futures]

        self.assertEqual(calls, 1)
        self.assertEqual(results[0], results[1])
        longbridge.INDUSTRY_STOCK_CACHE.pop(cache_key, None)


if __name__ == "__main__":
    unittest.main()
