import json
import os
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from services import heatmap_snapshots, weekly_reports
from services.ai_assistant import (
    generate_assistant_response,
    generate_market_query_response,
    plan_market_query,
)
from services.market_query import (
    MarketQueryError,
    MarketQueryNotFound,
    execute_market_query,
    normalize_query_spec,
)
from tools.market_report_collector import (
    due_weekly,
    latest_completed_week_anchor,
    weekly_execution_key,
)


def sector_query(operation="timeline", *, name="酿酒业", market="CN", level=2):
    return {
        "schemaVersion": "1.0",
        "intent": {"domain": "sector", "operation": operation},
        "subjects": [{
            "type": "sector",
            "market": market,
            "level": level,
            "name": name,
            "id": "",
        }],
        "time": {
            "kind": "date",
            "date": "2026-07-15",
            "timezonePolicy": "market_local",
        },
        "metrics": ["changePercent", "marketValue", "turnover"],
        "comparison": {"mode": "first_to_last", "includeAdjacentChanges": True},
        "options": {
            "sourcePolicy": "local_only",
            "includeSeries": True,
            "includeSummary": True,
            "sortMetric": "changePercent",
            "sortDirection": "desc",
            "limit": 5,
        },
    }


class MarketQueryTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"})
        environment.start()
        self.addCleanup(environment.stop)

    def _write_sector_snapshots(self, root: Path):
        date_dir = root / "CN" / "2026-07-15"
        date_dir.mkdir(parents=True)
        for snapshot_id, scheduled_at, trigger, change, market_value, turnover in (
            ("first", "2026-07-15T09:30:00+08:00", "scheduled", 0.4, 100.0, None),
            ("second", "2026-07-15T10:00:00+08:00", "scheduled", 0.8, 110.0, 18.0),
            ("manual", "2026-07-15T10:30:00+08:00", "manual", 9.9, 999.0, 999.0),
            ("close", "2026-07-15T15:00:00+08:00", "session-close", 2.1, 140.0, 52.0),
        ):
            payload = {
                "schemaVersion": 2,
                "snapshotId": snapshot_id,
                "market": "CN",
                "marketTimezone": "Asia/Shanghai",
                "trigger": trigger,
                "scheduledAt": scheduled_at,
                "capturedAt": scheduled_at,
                "groups": [{
                    "name": "必选消费",
                    "code": "group-consumer",
                    "changePercent": change / 2,
                    "marketValue": market_value * 10,
                }],
                "industries": [
                    {
                        "name": "酿酒业",
                        "code": "industry-wine",
                        "parentName": "必选消费",
                        "changePercent": change,
                        "marketValue": market_value,
                        "turnover": turnover,
                    },
                    {
                        "name": "食品零售商",
                        "code": "industry-food",
                        "parentName": "必选消费",
                        "changePercent": change - 1,
                        "marketValue": 50.0,
                        "turnover": 5.0,
                    },
                ],
                "turnoverCoverage": {
                    "industryCount": 1,
                    "totalIndustryCount": 2,
                    "selection": "largest-market-value",
                },
            }
            (date_dir / f"{snapshot_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

    def test_schema_rejects_invalid_market_and_range(self):
        query = sector_query()
        query["subjects"][0]["market"] = "JP"
        with self.assertRaisesRegex(MarketQueryError, "不支持的市场"):
            normalize_query_spec(query)

        query = sector_query()
        query["time"].update({"start": "2026-07-17", "end": "2026-07-15"})
        with self.assertRaisesRegex(MarketQueryError, "不能晚于"):
            normalize_query_spec(query)

    def test_weekly_collector_uses_latest_completed_market_week(self):
        timezone = ZoneInfo("Asia/Shanghai")
        self.assertEqual(
            latest_completed_week_anchor(datetime(2026, 7, 17, 22, tzinfo=timezone)),
            date(2026, 7, 10),
        )
        self.assertEqual(
            latest_completed_week_anchor(datetime(2026, 7, 18, 7, tzinfo=timezone)),
            date(2026, 7, 17),
        )
        self.assertEqual(
            latest_completed_week_anchor(datetime(2026, 7, 18, 2, tzinfo=timezone)),
            date(2026, 7, 10),
        )
        saturday = datetime(2026, 7, 18, 7, tzinfo=timezone)
        key = weekly_execution_key(date(2026, 7, 17))
        self.assertTrue(due_weekly(saturday, set(), 300))
        self.assertFalse(due_weekly(saturday, {key}, 300))
        self.assertFalse(due_weekly(
            datetime(2026, 7, 18, 5, 59, tzinfo=timezone),
            set(),
            300,
        ))

    @patch("services.market_query.engine.get_cached_report")
    def test_report_query_reads_fixed_local_session(self, mock_report):
        mock_report.return_value = {
            "schemaVersion": 10,
            "snapshotId": "midday-1",
            "date": "2026-07-15",
            "label": "午报 12:30",
            "generatedAt": "2026-07-15T12:30:00+08:00",
            "markets": ["CN", "HK"],
            "globalOverview": [],
            "majorMarkets": [],
            "sources": {"majorIndices": "Longbridge"},
        }
        query = {
            "schemaVersion": "1.0",
            "intent": {"domain": "report", "operation": "get"},
            "subjects": [],
            "time": {"kind": "date", "date": "2026-07-15"},
            "report": {"session": "midday"},
        }

        result = execute_market_query(query)

        mock_report.assert_called_once_with("midday", "2026-07-15")
        self.assertEqual(result["resultType"], "report")
        self.assertEqual(result["data"]["reports"][0]["markets"], ["CN", "HK"])
        self.assertEqual(result["meta"]["source"], "local.session_reports")

    def test_sector_timeline_uses_scheduled_frames_and_backend_calculations(self):
        with TemporaryDirectory() as tmp:
            snapshot_dir = Path(tmp) / "snapshots"
            self._write_sector_snapshots(snapshot_dir)
            with patch.object(heatmap_snapshots, "SNAPSHOT_DIR", snapshot_dir):
                result = execute_market_query(sector_query())

        timeline = result["data"]["timelines"][0]
        self.assertEqual([item["snapshotId"] for item in timeline["series"]], ["first", "second", "close"])
        self.assertEqual([item["adjacentChange"] for item in timeline["series"]], [None, 0.4, 1.3])
        self.assertAlmostEqual(timeline["summary"]["changePercentDelta"], 1.7)
        self.assertEqual(timeline["summary"]["direction"], "strengthening")
        self.assertEqual(timeline["summary"]["marketValueDelta"], 40.0)
        self.assertIsNone(timeline["summary"]["turnoverDelta"])
        self.assertEqual(result["meta"]["snapshotCount"], 3)
        self.assertIn("null 不代表零成交额", result["meta"]["warnings"][0])

    def test_sector_rank_returns_requested_level_and_limit(self):
        query = sector_query("rank", name="", level=2)
        with TemporaryDirectory() as tmp:
            snapshot_dir = Path(tmp) / "snapshots"
            self._write_sector_snapshots(snapshot_dir)
            with patch.object(heatmap_snapshots, "SNAPSHOT_DIR", snapshot_dir):
                result = execute_market_query(query)

        self.assertEqual(result["resultType"], "sector_rank")
        self.assertEqual(result["data"]["items"][0]["name"], "酿酒业")
        self.assertEqual(result["data"]["metric"], "changePercent")

    def test_weekly_query_is_local_only_and_reports_missing_packet(self):
        query = {
            "schemaVersion": "1.0",
            "intent": {"domain": "weekly_index", "operation": "get"},
            "subjects": [{"type": "index", "name": "恒生指数", "id": "HSI.HK", "market": "HK"}],
            "time": {"kind": "week", "date": "2026-07-15"},
        }
        with TemporaryDirectory() as tmp, patch.object(weekly_reports, "WEEKLY_CACHE_DIR", Path(tmp)):
            with self.assertRaisesRegex(MarketQueryNotFound, "没有本地周线数据"):
                execute_market_query(query)

            period = weekly_reports.weekly_period_for_date(date(2026, 7, 15), today=date(2026, 7, 17))
            weekly_reports.save_weekly_market_context({
                "schemaVersion": 2,
                "reportType": "weekly",
                "status": "final",
                "period": period,
                "coverage": {"availableIndexCount": 1, "complete": True},
                "globalOverview": [],
                "majorMarkets": [{
                    "market": "HK",
                    "indices": [{"name": "恒生指数", "code": "HSI.HK", "changePercent": 1.6}],
                }],
            })
            result = execute_market_query(query)

        self.assertEqual(result["data"]["indices"][0]["code"], "HSI.HK")
        self.assertEqual(result["meta"]["source"], "local.weekly_reports")

    def test_latest_week_falls_back_to_newest_finalized_packet(self):
        query = {
            "schemaVersion": "1.0",
            "intent": {"domain": "weekly_index", "operation": "get"},
            "subjects": [],
            "time": {"kind": "latest_finalized", "date": ""},
        }
        period = weekly_reports.weekly_period_for_date(
            date(2026, 7, 10),
            today=date(2026, 7, 17),
        )
        with TemporaryDirectory() as tmp, patch.object(weekly_reports, "WEEKLY_CACHE_DIR", Path(tmp)):
            weekly_reports.save_weekly_market_context({
                "schemaVersion": 2,
                "reportType": "weekly",
                "status": "final",
                "period": period,
                "coverage": {"availableIndexCount": 1, "complete": True},
                "globalOverview": [],
                "majorMarkets": [{
                    "market": "HK",
                    "indices": [{"name": "恒生指数", "code": "HSI.HK", "changePercent": 1.6}],
                }],
            })
            result = execute_market_query(query)

        self.assertEqual(result["data"]["period"]["isoWeek"], "2026-W28")
        self.assertIn("当周周报尚未生成", result["meta"]["fallbackNotice"])

    def test_latest_week_phrase_overrides_provider_current_date(self):
        planned = {
            "schemaVersion": "1.0",
            "intent": {"domain": "weekly_index", "operation": "get"},
            "subjects": [],
            "time": {"kind": "date", "date": "2026-07-17"},
        }
        with patch(
            "services.ai_assistant._provider_chat",
            return_value=json.dumps(planned, ensure_ascii=False),
        ):
            query = plan_market_query({
                "providerId": "custom",
                "apiBase": "http://127.0.0.1:11434/v1",
                "model": "test-model",
            }, "给我最新一份周报")

        self.assertEqual(query["time"]["kind"], "latest_finalized")
        self.assertEqual(query["time"]["date"], "")

    def test_provider_planning_and_direct_query_are_one_to_one(self):
        planned = sector_query()
        with TemporaryDirectory() as tmp:
            snapshot_dir = Path(tmp) / "snapshots"
            self._write_sector_snapshots(snapshot_dir)
            with (
                patch.object(heatmap_snapshots, "SNAPSHOT_DIR", snapshot_dir),
                patch(
                    "services.ai_assistant._provider_chat",
                    side_effect=[json.dumps(planned, ensure_ascii=False), "酿酒业全天走强。"],
                ),
            ):
                natural = generate_market_query_response({
                    "message": "给我 7 月 15 日酿酒业的变化",
                    "providerId": "custom",
                    "apiBase": "http://127.0.0.1:11434/v1",
                    "model": "test-model",
                })
                direct = execute_market_query(planned)

        self.assertEqual(natural["query"], direct["query"])
        self.assertEqual(natural["result"], direct)
        self.assertEqual(natural["content"], "酿酒业全天走强。")

    def test_provider_planner_repairs_invalid_schema_once(self):
        repaired = sector_query()
        with patch(
            "services.ai_assistant._provider_chat",
            side_effect=["{\"intent\":{}}", json.dumps(repaired, ensure_ascii=False)],
        ) as provider:
            query = plan_market_query({
                "providerId": "custom",
                "apiBase": "http://127.0.0.1:11434/v1",
                "model": "test-model",
            }, "给我 7 月 15 日酿酒业的变化")

        self.assertEqual(query["intent"], {"domain": "sector", "operation": "timeline"})
        self.assertEqual(provider.call_count, 2)
        self.assertIn("校验失败", provider.call_args.args[1][-1]["content"])

    @patch("services.ai_assistant.generate_market_report")
    def test_quick_action_bypasses_query_planner(self, mock_report):
        mock_report.return_value = {"content": "午报"}

        result = generate_assistant_response({
            "message": "请生成午报",
            "session": "midday",
            "quickAction": True,
        }, "http://localhost:3005")

        self.assertEqual(result, {"content": "午报"})
        mock_report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
