import unittest
from unittest.mock import patch

from services.reports import (
    REPORT_SCHEMA_VERSION,
    _chart_exports,
    build_report,
    get_cached_reports_between,
    get_report_by_snapshot,
    report_automation_config,
)


class ReportRankingTests(unittest.TestCase):
    def test_automation_config_is_indices_only(self):
        config = report_automation_config("http://127.0.0.1:5001")
        section_keys = [section["key"] for section in config["output"]["sections"]]
        self.assertEqual(
            section_keys,
            ["globalOverview", "majorMarkets", "chartExports"],
        )
        for job in config["jobs"]:
            workflow = " ".join(job["workflow"])
            self.assertIn("chartExports", workflow)
            self.assertIn("exportButtonId", workflow)
            self.assertIn("全球指数总览", workflow)
            self.assertIn("不消费热点图", workflow)
            self.assertNotIn("artifactPath", workflow)
            self.assertIn("./start.sh start", workflow)
            self.assertIn("最多等待 60 秒", workflow)
            self.assertNotIn("renderHeatmapTimeline", job["requests"])

    def test_report_chart_exports_use_stable_ids(self):
        exports = _chart_exports("close", ["CN", "HK"], "snapshot-close-1")
        self.assertEqual(
            [item["chartId"] for item in exports],
            [
                "trend-000001-sh",
                "trend-399001-sz",
                "trend-399006-sz",
                "trend-000688-sh",
                "trend-000300-sh",
                "trend-000016-sh",
                "trend-000905-sh",
                "trend-hsi-hk",
                "trend-hstech-hk",
                "trend-hscei-hk",
            ],
        )
        self.assertEqual(exports[0]["indexCode"], "000001.SH")
        self.assertEqual(exports[7]["indexCode"], "HSI.HK")
        self.assertEqual(
            exports[0]["captureSelector"],
            '[data-chart-id="trend-000001-sh"]',
        )
        self.assertEqual(
            exports[0]["pageUrl"],
            "/?session=close&snapshotId=snapshot-close-1#report",
        )
        self.assertIn("当前点位", exports[0]["contentRequirements"])
        self.assertTrue(all(item["kind"] == "trend" for item in exports))

    @patch("services.reports._report_indices")
    def test_build_report_is_independent_from_heatmap_cache(
        self,
        mock_report_indices,
    ):
        mock_report_indices.return_value = ([], {"CN": [], "HK": [], "US": []})

        report = build_report("close")

        self.assertTrue(report["snapshotId"].startswith("close-"))
        self.assertNotIn("_sectorHeatmaps", report)
        self.assertEqual(report["sectorRankings"], [])
        for export in [item for item in report["chartExports"] if item["kind"] == "trend"]:
            self.assertIn(
                f"snapshotId={report['snapshotId']}",
                export["pageUrl"],
            )
        kinds = [item["kind"] for item in report["chartExports"]]
        self.assertEqual(kinds.count("trend"), 10)
        self.assertEqual(kinds.count("heatmap"), 0)

    def test_snapshot_lookup_returns_indices_only_public_report(self):
        report = {
            "schemaVersion": REPORT_SCHEMA_VERSION,
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
        }
        cache = {"2026-07-03": {"close": report}}

        with patch("services.reports._read_cache", return_value=cache):
            public_report = get_report_by_snapshot("snapshot-close-9")

        self.assertEqual(public_report["snapshotId"], "snapshot-close-9")
        self.assertNotIn("_sectorHeatmaps", public_report)

    def test_cached_report_range_keeps_dates_and_sessions(self):
        compatible = {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "snapshotId": "snapshot-1",
            "globalOverview": [],
            "majorMarkets": [],
            "chartExports": [],
            "sources": {},
        }
        cache = {
            "2026-07-14": {"morning": {**compatible, "date": "2026-07-14"}},
            "2026-07-15": {"close": {**compatible, "date": "2026-07-15"}},
            "2026-07-18": {"close": {**compatible, "date": "2026-07-18"}},
        }

        with patch("services.reports._read_cache", return_value=cache):
            reports = get_cached_reports_between("2026-07-14", "2026-07-15")

        self.assertEqual([item["date"] for item in reports], ["2026-07-14", "2026-07-15"])
        self.assertEqual(list(reports[0]["sessions"]), ["morning"])
        self.assertEqual(list(reports[1]["sessions"]), ["close"])


if __name__ == "__main__":
    unittest.main()
