import unittest
from unittest.mock import patch

from services.reports import (
    REPORT_HEATMAPS_KEY,
    ReportGenerationError,
    _chart_exports,
    _rank_rows,
    _sector_heatmaps,
    build_report,
    get_report_by_snapshot,
    get_report_heatmap_snapshot,
    report_automation_config,
)


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

    def test_automation_config_is_simplified_to_indices_and_static_heatmaps(self):
        config = report_automation_config("http://127.0.0.1:5001")
        section_keys = [section["key"] for section in config["output"]["sections"]]
        self.assertEqual(section_keys, ["majorMarkets", "chartExports"])
        for job in config["jobs"]:
            workflow = " ".join(job["workflow"])
            self.assertIn("chartExports", workflow)
            self.assertIn("exportButtonId", workflow)
            self.assertIn("触发时点静态 PNG", workflow)
            self.assertIn("不得合成视频", workflow)
            self.assertIn("./start.sh start", workflow)
            self.assertIn("最多等待 60 秒", workflow)
            self.assertNotIn("renderHeatmapTimeline", job["requests"])

    def test_report_chart_exports_use_stable_ids(self):
        exports = _chart_exports("close", ["CN", "HK"], "snapshot-close-1")
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
            exports[0]["pageUrl"],
            "/?session=close&snapshotId=snapshot-close-1#report",
        )
        self.assertIn("当前点位", exports[0]["contentRequirements"])
        self.assertEqual(exports[1]["renderMode"], "full-market-hierarchy")
        self.assertIn("当前触发时点", exports[1]["contentRequirements"][1])
        self.assertEqual(exports[1]["minimumImageWidth"], 3000)
        self.assertEqual(exports[1]["minimumImageHeight"], 2600)

    @patch("services.reports._report_indices")
    @patch("services.reports.longbridge.fetch_industry_heatmap")
    def test_build_report_embeds_snapshot_id_and_heatmap_cache(
        self,
        mock_fetch_industry_heatmap,
        mock_report_indices,
    ):
        mock_report_indices.return_value = ([], {"CN": [], "HK": [], "US": []})

        def fake_heatmap(market, include_stocks=False):
            self.assertFalse(include_stocks)
            return {
                "market": market,
                "source": "Longbridge",
                "updatedAt": "2026-07-03T09:30:00+08:00",
                "groups": [
                    {
                        "name": f"{market} 一级",
                        "code": f"{market}-GROUP",
                        "changePercent": 1.25,
                        "marketValue": 1000,
                        "industries": [
                            {
                                "name": f"{market} 二级",
                                "code": f"{market}-INDUSTRY",
                                "parentName": f"{market} 一级",
                                "changePercent": 2.5,
                                "marketValue": 500,
                                "delayed": False,
                                "dayLeader": {
                                    "name": f"{market} 领涨股",
                                    "code": f"{market}-LEADER",
                                    "price": 12.34,
                                    "changePercent": 5.6,
                                },
                            },
                        ],
                    },
                ],
                "industries": [
                    {
                        "name": f"{market} 二级",
                        "code": f"{market}-INDUSTRY",
                        "parentName": f"{market} 一级",
                        "changePercent": 2.5,
                        "marketValue": 500,
                        "delayed": False,
                        "dayLeader": {
                            "name": f"{market} 领涨股",
                            "code": f"{market}-LEADER",
                            "price": 12.34,
                            "changePercent": 5.6,
                        },
                    },
                ],
            }

        mock_fetch_industry_heatmap.side_effect = fake_heatmap

        report = build_report("close")

        self.assertTrue(report["snapshotId"].startswith("close-"))
        self.assertIn(REPORT_HEATMAPS_KEY, report)
        self.assertEqual(set(report[REPORT_HEATMAPS_KEY].keys()), {"CN", "HK"})
        self.assertEqual(
            report["sectorRankings"][0]["primary"]["leaders"][0]["name"],
            "CN 一级",
        )
        self.assertEqual(
            report["sectorRankings"][0]["secondary"]["leaders"][0]["dayLeader"]["code"],
            "CN-LEADER",
        )
        for export in report["chartExports"]:
            self.assertIn(
                f"snapshotId={report['snapshotId']}",
                export["pageUrl"],
            )
        self.assertEqual(
            [item["kind"] for item in report["chartExports"]],
            ["trend", "heatmap", "trend", "heatmap"],
        )

    def test_snapshot_lookup_returns_public_report_and_heatmap_payload(self):
        report = {
            "schemaVersion": 10,
            "session": "close",
            "snapshotId": "snapshot-close-9",
            "label": "收盘 16:30",
            "scheduledAt": "16:30",
            "date": "2026-07-03",
            "generatedAt": "2026-07-03T16:30:00+08:00",
            "markets": ["CN", "HK"],
            "marketLabels": ["A 股", "港股"],
            "globalOverview": [],
            "majorMarkets": [],
            "sectorRankings": [],
            "chartExports": [],
            "sources": {
                "globalIndices": "Longbridge",
                "majorIndices": "Longbridge",
                "sectorRankings": "Longbridge",
            },
            REPORT_HEATMAPS_KEY: {
                "CN": {
                    "market": "CN",
                    "source": "Longbridge",
                    "updatedAt": "2026-07-03T16:30:00+08:00",
                    "groups": [{"name": "科技"}],
                    "industries": [{"name": "半导体"}],
                },
            },
        }
        cache = {"2026-07-03": {"close": report}}

        with patch("services.reports._read_cache", return_value=cache):
            public_report = get_report_by_snapshot("snapshot-close-9")
            heatmap = get_report_heatmap_snapshot("snapshot-close-9", "cn")

        self.assertEqual(public_report["snapshotId"], "snapshot-close-9")
        self.assertNotIn(REPORT_HEATMAPS_KEY, public_report)
        self.assertEqual(heatmap["market"], "CN")
        self.assertEqual(heatmap["industries"][0]["name"], "半导体")

    @patch("services.reports.longbridge.INDUSTRY_HEATMAP_CACHE", {})
    @patch("services.reports.longbridge.fetch_industry_heatmap")
    def test_sector_heatmaps_retry_empty_payload_before_failing(
        self,
        mock_fetch_industry_heatmap,
    ):
        mock_fetch_industry_heatmap.side_effect = [
            {
                "market": "CN",
                "source": "Longbridge",
                "updatedAt": "2026-07-03T16:30:00+08:00",
                "groups": [],
                "industries": [],
            },
            {
                "market": "CN",
                "source": "Longbridge",
                "updatedAt": "2026-07-03T16:30:01+08:00",
                "groups": [{"name": "科技"}],
                "industries": [{"name": "半导体"}],
            },
        ]

        heatmaps = _sector_heatmaps(["CN"], "2026-07-03T16:30:00+08:00")

        self.assertEqual(mock_fetch_industry_heatmap.call_count, 2)
        self.assertEqual(heatmaps["CN"]["groups"][0]["name"], "科技")

    @patch("services.reports.longbridge.INDUSTRY_HEATMAP_CACHE", {})
    @patch("services.reports.longbridge.fetch_industry_heatmap")
    def test_sector_heatmaps_fail_when_payload_stays_empty(
        self,
        mock_fetch_industry_heatmap,
    ):
        mock_fetch_industry_heatmap.return_value = {
            "market": "HK",
            "source": "Longbridge",
            "updatedAt": "2026-07-03T16:30:00+08:00",
            "groups": [],
            "industries": [],
        }

        with self.assertRaises(ReportGenerationError):
            _sector_heatmaps(["HK"], "2026-07-03T16:30:00+08:00")


if __name__ == "__main__":
    unittest.main()
