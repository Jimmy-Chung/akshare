import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

from app import _ACCESS_FAILURES, app
from tools.configure_dashboard_access import configure


REMOTE = {"REMOTE_ADDR": "203.0.113.10"}


class DashboardAccessTests(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            SERVER_NAME="localhost",
            SESSION_COOKIE_SECURE=False,
        )
        _ACCESS_FAILURES.clear()
        self.password = "correct horse battery staple"
        self.password_hash = generate_password_hash(self.password)
        self.environment = patch.dict(
            os.environ,
            {"DASHBOARD_ACCESS_PASSWORD_HASH": self.password_hash},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = app.test_client()

    def test_remote_api_requires_access_login_and_persists_session(self):
        blocked = self.client.get("/api/assistant/providers", environ_base=REMOTE)
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.get_json()["code"], "dashboard_access_required")

        wrong = self.client.post(
            "/api/access/login",
            json={"password": "wrong-password"},
            environ_base=REMOTE,
        )
        self.assertEqual(wrong.status_code, 401)

        login = self.client.post(
            "/api/access/login",
            json={"password": self.password},
            environ_base=REMOTE,
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("Expires=", login.headers.get("Set-Cookie", ""))
        self.assertIn("HttpOnly", login.headers.get("Set-Cookie", ""))

        allowed = self.client.get("/api/assistant/providers", environ_base=REMOTE)
        self.assertEqual(allowed.status_code, 200)

        self.client.post("/api/access/logout", environ_base=REMOTE)
        blocked_again = self.client.get("/api/assistant/providers", environ_base=REMOTE)
        self.assertEqual(blocked_again.status_code, 401)

    def test_remote_access_fails_closed_when_password_is_not_configured(self):
        with patch.dict(os.environ, {"DASHBOARD_ACCESS_PASSWORD_HASH": ""}):
            status = self.client.get("/api/access/status", environ_base=REMOTE)
            self.assertEqual(status.status_code, 200)
            self.assertFalse(status.get_json()["configured"])

            login = self.client.post(
                "/api/access/login",
                json={"password": self.password},
                environ_base=REMOTE,
            )
            self.assertEqual(login.status_code, 503)

            blocked = self.client.get("/api/dashboard/overview", environ_base=REMOTE)
            self.assertEqual(blocked.status_code, 401)

    def test_loopback_collectors_keep_access_and_cross_origin_is_not_enabled(self):
        local = self.client.get(
            "/api/assistant/providers",
            headers={"Host": "127.0.0.1:5001"},
        )
        self.assertEqual(local.status_code, 200)

        proxied_loopback = self.client.get(
            "/api/assistant/providers",
            headers={
                "Host": "127.0.0.1:5001",
                "X-Dashboard-Original-Host": "localhost:3005",
                "CF-Connecting-IP": "203.0.113.10",
                "CF-Ray": "review-LAX",
            },
        )
        self.assertEqual(proxied_loopback.status_code, 401)

        local_browser = self.client.get(
            "/api/assistant/providers",
            headers={"X-Dashboard-Original-Host": "localhost:3005"},
        )
        self.assertEqual(local_browser.status_code, 200)

        remote = self.client.post(
            "/api/access/login",
            json={"password": self.password},
            headers={"Origin": "https://example.invalid"},
            environ_base=REMOTE,
        )
        self.assertEqual(remote.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", remote.headers)

    @patch("app.generate_assistant_stream")
    def test_assistant_stream_endpoint_returns_sse_events(self, mock_stream):
        mock_stream.return_value = iter([
            {"type": "status", "message": "正在生成回答…"},
            {"type": "delta", "content": "你好"},
            {"type": "done", "response": {"content": "你好", "label": "测试"}},
        ])

        response = self.client.post(
            "/api/assistant/chat",
            json={"message": "测试", "stream": True},
            headers={"Host": "127.0.0.1:5001"},
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/event-stream"))
        self.assertIn('"type": "delta"', body)
        self.assertIn('"content": "你好"', body)
        self.assertEqual(response.headers["X-Accel-Buffering"], "no")

    def test_changing_password_hash_invalidates_existing_session(self):
        login = self.client.post(
            "/api/access/login",
            json={"password": self.password},
            environ_base=REMOTE,
        )
        self.assertEqual(login.status_code, 200)

        replacement_hash = generate_password_hash("a completely different password")
        with patch.dict(
            os.environ,
            {"DASHBOARD_ACCESS_PASSWORD_HASH": replacement_hash},
        ):
            blocked = self.client.get("/api/assistant/providers", environ_base=REMOTE)
        self.assertEqual(blocked.status_code, 401)

    def test_configuration_command_stores_only_a_password_hash(self):
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("PUBLIC_APP_URL=http://localhost:3005\n", encoding="utf-8")
            with patch(
                "tools.configure_dashboard_access.getpass.getpass",
                side_effect=[self.password, self.password],
            ):
                configure(env_path)
            content = env_path.read_text(encoding="utf-8")

        self.assertNotIn(self.password, content)
        values = dict(
            line.split("=", 1)
            for line in content.splitlines()
            if line and not line.startswith("#")
        )
        self.assertTrue(check_password_hash(
            values["DASHBOARD_ACCESS_PASSWORD_HASH"],
            self.password,
        ))
        self.assertEqual(values["DASHBOARD_ACCESS_SESSION_DAYS"], "30")


if __name__ == "__main__":
    unittest.main()
