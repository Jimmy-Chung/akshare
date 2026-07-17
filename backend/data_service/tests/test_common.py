import unittest

from providers.common import merge_with_lazy_fallback


class LazyFallbackTests(unittest.TestCase):
    def test_fallback_is_not_called_when_primary_is_complete(self):
        calls = []

        def fallback():
            calls.append(True)
            return [{"code": "B", "price": 2}]

        rows = merge_with_lazy_fallback(
            [{"code": "A", "price": 1}, {"code": "B", "price": 2}],
            fallback,
            ["A", "B"],
        )

        self.assertEqual(calls, [])
        self.assertEqual([row["code"] for row in rows], ["A", "B"])
        self.assertTrue(all(row["isFallback"] is False for row in rows))

    def test_fallback_fills_only_codes_missing_from_primary(self):
        calls = []

        def fallback():
            calls.append(True)
            return [
                {"code": "A", "price": 99},
                {"code": "B", "price": 2},
            ]

        rows = merge_with_lazy_fallback(
            [{"code": "A", "price": 1}],
            fallback,
            ["A", "B"],
        )

        self.assertEqual(calls, [True])
        self.assertEqual(rows, [
            {"code": "A", "price": 1, "isFallback": False},
            {"code": "B", "price": 2, "isFallback": True},
        ])

    def test_fallback_is_called_when_primary_is_empty(self):
        calls = []

        def fallback():
            calls.append(True)
            return [{"code": "B", "price": 2}]

        rows = merge_with_lazy_fallback([], fallback, ["A", "B"])

        self.assertEqual(calls, [True])
        self.assertEqual(rows, [{"code": "B", "price": 2, "isFallback": True}])


if __name__ == "__main__":
    unittest.main()
