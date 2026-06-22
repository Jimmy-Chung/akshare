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


if __name__ == "__main__":
    unittest.main()
