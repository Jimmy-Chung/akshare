import unittest
from unittest.mock import Mock, patch

import requests

from services.ai_assistant import (
    AssistantConfigurationError,
    AssistantProviderError,
    _chat_url,
    _normalize_model,
    _report_session,
    _report_type,
    generate_market_report,
)


class AiAssistantTests(unittest.TestCase):
    def test_deepseek_v4_alias_is_normalized(self):
        self.assertEqual(
            _normalize_model("deepseek", "deepseek-4-pro"),
            "deepseek-v4-pro",
        )
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
        prompt = call.kwargs["json"]["messages"][1]["content"]
        self.assertIn("必须使用的输出格式", prompt)
        self.assertIn("结构化指数快照", prompt)
        response.raise_for_status.assert_called_once_with()

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
