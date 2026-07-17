import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

from services.ai_assistant import (
    AssistantConfigurationError,
    AssistantProviderError,
    _chat_url,
    _normalize_model,
    _provider_config,
    _report_date,
    _report_session,
    _report_type,
    _weekly_period,
    _weekly_report_context,
    generate_market_report,
)


class AiAssistantTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_deepseek_v4_alias_is_normalized(self):
        self.assertEqual(
            _normalize_model("deepseek", "deepseek-4-pro"),
            "deepseek-v4-pro",
        )

    def test_browser_can_only_override_model(self):
        config = _provider_config({
            "providerId": "custom",
            "apiBase": "https://example.invalid",
            "apiKey": "browser-secret",
            "model": "deepseek-v4-flash",
        })
        self.assertEqual(config["id"], "deepseek")
        self.assertEqual(config["apiBase"], "https://api.deepseek.com")
        self.assertEqual(config["apiKey"], "test-key")
        self.assertEqual(config["model"], "deepseek-v4-flash")
        self.assertEqual(
            _normalize_model("deepseek", "deepseek-4-flash"),
            "deepseek-v4-flash",
        )

    def test_report_keyword_selects_daily_or_weekly_template(self):
        self.assertEqual(_report_type("请生成日报"), "daily")
        self.assertEqual(_report_type("复盘一下本周周报"), "weekly")

    def test_quick_action_session_is_explicit_and_keyword_aware(self):
        self.assertEqual(_report_session({"session": "midday"}, "日报"), "midday")
        self.assertEqual(_report_session({}, "请生成收盘报"), "close")
        self.assertEqual(_report_session({}, "请生成夜报"), "us-night")

    def test_natural_language_report_date_is_resolved_in_report_timezone(self):
        now = datetime(2026, 7, 17, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(_report_date("给我 7 月 15 号的午报", now), "2026-07-15")
        self.assertEqual(_report_date("查看2025年12月31日夜报", now), "2025-12-31")
        self.assertEqual(_report_date("昨天的收盘报", now), "2026-07-16")
        self.assertEqual(_report_date("请生成午报", now), "")

    def test_weekly_period_uses_monday_and_supports_last_week(self):
        now = datetime(2026, 7, 17, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            _weekly_period("请生成本周周报", now=now),
            {
                "startDate": "2026-07-13",
                "endDate": "2026-07-17",
                "anchorDate": "2026-07-17",
                "timezone": "Asia/Shanghai",
                "isCurrentWeek": True,
            },
        )
        previous = _weekly_period("请生成上周周报", now=now)
        self.assertEqual(previous["startDate"], "2026-07-06")
        self.assertEqual(previous["endDate"], "2026-07-12")
        self.assertFalse(previous["isCurrentWeek"])

    @patch("services.ai_assistant.get_cached_weekly_market_context")
    def test_weekly_context_uses_broker_weekly_schema(self, mock_context):
        period = {
            "startDate": "2026-07-13",
            "endDate": "2026-07-17",
            "anchorDate": "2026-07-15",
            "timezone": "Asia/Shanghai",
            "isCurrentWeek": True,
        }
        mock_context.return_value = {
            "schemaVersion": 2,
            "reportType": "weekly",
            "period": period,
            "coverage": {"availableIndexCount": 13},
            "globalOverview": [],
            "majorMarkets": [],
        }

        context = _weekly_report_context(period)

        self.assertEqual(context["schemaVersion"], 2)
        self.assertEqual(context["coverage"]["availableIndexCount"], 13)
        mock_context.assert_called_once_with(period)

    @patch("services.ai_assistant._weekly_period")
    @patch("services.ai_assistant._weekly_report_context")
    @patch("services.ai_assistant.requests.post")
    def test_weekly_report_returns_range_and_coverage(
        self,
        mock_post,
        mock_weekly_context,
        mock_weekly_period,
    ):
        period = {
            "startDate": "2026-07-13",
            "endDate": "2026-07-17",
            "anchorDate": "2026-07-17",
            "timezone": "Asia/Shanghai",
            "isCurrentWeek": True,
        }
        coverage = {
            "requestedIndexCount": 26,
            "availableIndexCount": 13,
            "unavailableIndexCount": 13,
            "sourceCounts": {"Longbridge Weekly Candlestick": 13},
            "unavailableIndices": [],
            "complete": False,
        }
        mock_weekly_period.return_value = period
        mock_weekly_context.return_value = {
            "schemaVersion": 2,
            "reportType": "weekly",
            "period": period,
            "coverage": coverage,
            "globalOverview": [],
            "majorMarkets": [],
        }
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "# 市场周报｜2026-07-13 至 2026-07-17"}}],
        }
        mock_post.return_value = response

        result = generate_market_report({
            "message": "请生成本周周报",
            "providerId": "deepseek",
            "apiBase": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
            "apiKey": "test-key",
        }, "https://workspace-akshare.jimmy-jam.com")

        self.assertEqual(result["reportType"], "weekly")
        self.assertEqual(result["session"], "weekly")
        self.assertEqual(result["dataPeriods"], ["2026-07-13 至 2026-07-17"])
        self.assertEqual(result["targetDate"], "2026-07-17")
        self.assertEqual(result["period"], period)
        self.assertEqual(result["coverage"], coverage)
        prompt = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("本次数据区间：2026-07-13 至 2026-07-17", prompt)
        self.assertIn("结构化券商周线", prompt)
        self.assertIn('"schemaVersion":2', prompt)

    def test_historical_date_requires_explicit_report_session(self):
        with self.assertRaisesRegex(AssistantConfigurationError, "同时说明"):
            generate_market_report({
                "message": "给我 7 月 15 日的报告",
                "providerId": "deepseek",
            }, "https://workspace-akshare.jimmy-jam.com")

    def test_external_plain_http_provider_is_rejected(self):
        with self.assertRaises(AssistantConfigurationError):
            _chat_url("http://example.com/v1")
        self.assertEqual(
            _chat_url("http://127.0.0.1:11434/v1"),
            "http://127.0.0.1:11434/v1/chat/completions",
        )

    @patch("services.ai_assistant._report_context")
    @patch("services.ai_assistant.requests.post")
    def test_deepseek_receives_structured_snapshot_and_fixed_format(
        self,
        mock_post,
        mock_report_context,
    ):
        mock_report_context.return_value = [{
            "date": "2026-07-17",
            "globalOverview": [{"region": "欧洲", "indices": []}],
        }]
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "# 市场日报｜2026-07-17"}}],
        }
        mock_post.return_value = response

        result = generate_market_report({
            "message": "日报",
            "providerId": "deepseek",
            "apiBase": "https://api.deepseek.com",
            "model": "deepseek-4-pro",
            "apiKey": "test-key",
        }, "https://workspace-akshare.jimmy-jam.com")

        self.assertEqual(result["reportType"], "daily")
        self.assertEqual(result["provider"], "DeepSeek")
        self.assertEqual(result["dataPeriods"], ["2026-07-17"])
        call = mock_post.call_args
        self.assertEqual(call.args[0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(call.kwargs["json"]["model"], "deepseek-v4-pro")
        self.assertEqual(result["model"], "deepseek-v4-pro")
        self.assertEqual(result["targetDate"], "2026-07-17")
        prompt = call.kwargs["json"]["messages"][1]["content"]
        self.assertIn("必须使用的输出格式", prompt)
        self.assertIn("结构化指数快照", prompt)
        response.raise_for_status.assert_called_once_with()

    @patch("services.ai_assistant._report_context")
    @patch("services.ai_assistant.requests.post")
    def test_natural_language_date_loads_matching_historical_session(
        self,
        mock_post,
        mock_report_context,
    ):
        mock_report_context.return_value = [{"date": "2026-07-15", "majorMarkets": []}]
        response = Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "# 市场午报｜2026-07-15"}}],
        }
        mock_post.return_value = response

        result = generate_market_report({
            "message": "给我 7 月 15 号的午报",
            "providerId": "deepseek",
            "apiBase": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
            "apiKey": "test-key",
        }, "https://workspace-akshare.jimmy-jam.com")

        mock_report_context.assert_called_once_with(
            "daily",
            "https://workspace-akshare.jimmy-jam.com",
            "midday",
            "2026-07-15",
        )
        self.assertEqual(result["session"], "midday")
        self.assertEqual(result["targetDate"], "2026-07-15")
        self.assertEqual(result["dataPeriods"], ["2026-07-15"])
        prompt = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("本次数据日期：2026-07-15", prompt)

    @patch("services.ai_assistant._report_context")
    @patch("services.ai_assistant.requests.post")
    def test_provider_error_includes_safe_upstream_message(
        self,
        mock_post,
        mock_report_context,
    ):
        mock_report_context.return_value = [{"date": "2026-07-17"}]
        response = Mock(status_code=400)
        response.json.return_value = {
            "error": {"message": "Model Not Exist", "type": "invalid_request_error"},
        }
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        mock_post.return_value = response

        with self.assertRaisesRegex(
            AssistantProviderError,
            "HTTP 400：Model Not Exist",
        ):
            generate_market_report({
                "message": "早报",
                "providerId": "deepseek",
                "apiBase": "https://api.deepseek.com",
                "model": "unknown-model",
                "apiKey": "test-key",
                "session": "morning",
            }, "https://workspace-akshare.jimmy-jam.com")


if __name__ == "__main__":
    unittest.main()
