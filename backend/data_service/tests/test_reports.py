import unittest

from services.reports import _rank_rows, report_automation_config


class ReportRankingTests(unittest.TestCase):
    def test_secondary_ranking_preserves_parent_and_day_leader(self):
        ranking = _rank_rows([
            {
                "name": "生物技术",
                "code": "BK/US/IN00261",
                "parentName": "医疗保健",
                "changePercent": 2.93,
                "marketValue": 100,
                "dayLeader": {
                    "name": "示例生物",
                    "code": "DEMO.US",
                    "price": 12.34,
                    "changePercent": 8.5,
                },
            },
        ])

        item = ranking["leaders"][0]
        self.assertEqual(item["parentName"], "医疗保健")
        self.assertEqual(item["dayLeader"]["name"], "示例生物")
        self.assertEqual(item["dayLeader"]["code"], "DEMO.US")
        self.assertEqual(item["dayLeader"]["price"], 12.34)
        self.assertEqual(item["dayLeader"]["changePercent"], 8.5)

    def test_automation_config_requires_industry_relationships(self):
        config = report_automation_config("http://127.0.0.1:5001")
        sector_section = next(
            section
            for section in config["output"]["sections"]
            if section["key"] == "sectorRankings"
        )
        self.assertIn("所属一级分类", sector_section["description"])
        for job in config["jobs"]:
            workflow = " ".join(job["workflow"])
            self.assertIn("dayLeader", workflow)
            self.assertIn("领涨股名称、代码、价格与涨跌幅", workflow)
            self.assertIn("chartExports", workflow)
            self.assertIn("exportButtonId", workflow)

    def test_report_chart_exports_use_stable_ids(self):
        from services.reports import _chart_exports

        exports = _chart_exports("close", ["CN", "HK"])
        self.assertEqual(
            [item["chartId"] for item in exports],
            [
                "trend-000001-sh",
                "heatmap-cn",
                "trend-hsi-hk",
                "heatmap-hk",
            ],
        )
        self.assertEqual(exports[0]["indexCode"], "000001.SH")
        self.assertEqual(exports[2]["indexCode"], "HSI.HK")
        self.assertEqual(
            exports[0]["captureSelector"],
            '[data-chart-id="trend-000001-sh"]',
        )
        self.assertEqual(
            exports[1]["pageUrl"],
            "/?session=close#report",
        )
        self.assertIn("当前点位", exports[0]["contentRequirements"])
        self.assertIn(
            "当前时段该市场全部一级行业和全部二级行业",
            exports[1]["contentRequirements"],
        )
        self.assertIn("一级行业名称与综合涨跌幅", exports[1]["contentRequirements"])
        self.assertEqual(exports[1]["renderMode"], "full-market-hierarchy")
        self.assertEqual(exports[1]["minimumImageWidth"], 1400)
        self.assertEqual(exports[1]["minimumImageHeight"], 1100)


if __name__ == "__main__":
    unittest.main()
