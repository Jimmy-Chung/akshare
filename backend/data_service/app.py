from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request, session
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from providers import legacy_market, longbridge, longbridge_oauth, news, sectors_ths
from providers.common import merge_preferred_rows, merge_with_lazy_fallback
from providers.market_catalog import GLOBAL_INDEX_ORDER
from services.dashboard import build_dashboard_overview
from services.ai_assistant import (
    AssistantConfigurationError,
    AssistantProviderError,
    generate_assistant_response,
    provider_catalog,
)
from services.market_query import (
    MarketQueryError,
    MarketQueryNotFound,
    execute_market_query,
)
from services.heatmap_snapshots import (
    HeatmapSnapshotError,
    create_heatmap_snapshot,
    get_heatmap_snapshot,
    latest_heatmap_snapshot,
    list_heatmap_snapshot_dates,
    list_heatmap_snapshot_history,
)
from services.reports import (
    get_history_report,
    get_cached_report,
    get_report_by_snapshot,
    get_latest_report,
    latest_session,
    regenerate_report,
    report_automation_config,
    report_schedule,
)
from services.weekly_reports import (
    WeeklyReportError,
    capture_weekly_market_context,
    get_cached_weekly_market_context,
    weekly_period_for_date,
)

def _load_flask_secret() -> str:
    configured = os.getenv("FLASK_SECRET_KEY", "").strip()
    if configured:
        return configured

    path = Path(__file__).resolve().parent / "runtime_cache" / ".flask_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        value = secrets.token_hex(32)
        try:
            with path.open("x", encoding="utf-8") as secret_file:
                secret_file.write(value)
            os.chmod(path, 0o600)
            return value
        except FileExistsError:
            return path.read_text(encoding="utf-8").strip()


app = Flask(__name__)
app.secret_key = _load_flask_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower()
    in {"1", "true", "yes"},
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _public_app_url() -> str:
    configured = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if configured:
        return configured
    local_host = request.host.split(":")[0]
    if local_host in {"localhost", "127.0.0.1"}:
        return f"http://{local_host}:3005"
    return request.host_url.rstrip("/")


def _oauth_redirect_uri() -> str:
    configured = os.getenv("LONGBRIDGE_OAUTH_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return f"{_public_app_url()}/api/auth/longbridge/callback"


def _public_api_url() -> str:
    configured = os.getenv("PUBLIC_API_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return request.host_url.rstrip("/")


def _safe_next_path(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/#dashboard"


def _oauth_result_redirect(error: str = ""):
    query = f"?{urlencode({'oauth_error': error})}" if error else ""
    fragment = "connect" if error else "dashboard"
    return redirect(f"{_public_app_url()}/{query}#{fragment}")


def real_or_empty(fetcher: Callable[[], List[Dict[str, Any]]], label: str):
    try:
        return jsonify(fetcher())
    except Exception as exc:
        logger.exception("获取%s失败: %s", label, exc)
        return jsonify([])


def _major_indices(group: str) -> List[Dict[str, Any]]:
    if group == "a":
        return merge_with_lazy_fallback(
            longbridge.fetch_a_indices(),
            legacy_market.fetch_a_indices,
            [item["code"] for item in longbridge.A_INDEX_SYMBOLS],
        )
    if group == "hk":
        return merge_with_lazy_fallback(
            longbridge.fetch_hk_indices(),
            legacy_market.fetch_hk_indices,
            [item["code"] for item in longbridge.HK_INDEX_SYMBOLS],
        )
    return merge_with_lazy_fallback(
        longbridge.fetch_us_indices(),
        legacy_market.fetch_us_indices,
        [item["code"] for item in longbridge.US_INDEX_SYMBOLS],
    )


@app.route("/api/dashboard/overview", methods=["GET"])
def dashboard_overview():
    return jsonify(build_dashboard_overview())


@app.route("/api/assistant/providers", methods=["GET"])
def assistant_providers():
    return jsonify(provider_catalog())


@app.route("/api/assistant/chat", methods=["POST"])
def assistant_chat():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(generate_assistant_response(payload, _public_app_url()))
    except MarketQueryNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except MarketQueryError as exc:
        return jsonify({"error": str(exc)}), 422
    except AssistantConfigurationError as exc:
        return jsonify({"error": str(exc)}), 422
    except AssistantProviderError as exc:
        logger.warning("AI 市场助手调用失败: %s", exc)
        return jsonify({"error": str(exc)}), 502


@app.route("/api/market-query/execute", methods=["POST"])
def market_query_execute():
    payload = request.get_json(silent=True) or {}
    raw_query = payload.get("query") if isinstance(payload.get("query"), dict) else payload
    try:
        return jsonify(execute_market_query(raw_query))
    except MarketQueryNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except MarketQueryError as exc:
        return jsonify({"error": str(exc)}), 422


@app.route("/api/weekly-reports/generate", methods=["POST"])
def weekly_reports_generate():
    from datetime import date

    anchor_value = request.args.get("date") or date.today().isoformat()
    try:
        return jsonify(capture_weekly_market_context(date.fromisoformat(anchor_value)))
    except ValueError:
        return jsonify({"error": "date 必须使用 YYYY-MM-DD 格式"}), 422
    except WeeklyReportError as exc:
        return jsonify({"error": str(exc)}), 409


@app.route("/api/weekly-reports/captured", methods=["GET"])
def weekly_reports_captured():
    from datetime import date

    anchor_value = request.args.get("date") or date.today().isoformat()
    try:
        context = get_cached_weekly_market_context(
            weekly_period_for_date(date.fromisoformat(anchor_value))
        )
    except ValueError:
        return jsonify({"error": "date 必须使用 YYYY-MM-DD 格式"}), 422
    return jsonify(context) if context else (jsonify({"error": "该周周线尚未采集"}), 404)


@app.route("/api/reports/latest", methods=["GET"])
def reports_latest():
    session = request.args.get("session") or latest_session()
    return jsonify(get_latest_report(session))


@app.route("/api/reports/history", methods=["GET"])
def reports_history():
    session = request.args.get("session") or latest_session()
    target_date = request.args.get("date") or ""
    return jsonify(get_history_report(session, target_date))


@app.route("/api/reports/captured", methods=["GET"])
def reports_captured():
    session_name = request.args.get("session") or latest_session()
    target_date = request.args.get("date") or ""
    report = get_cached_report(session_name, target_date)
    if not report:
        return jsonify({"error": "该时段数据包尚未采集"}), 404
    return jsonify(report)


@app.route("/api/reports/snapshot", methods=["GET"])
def reports_snapshot():
    snapshot_id = request.args.get("snapshotId", "").strip()
    report = get_report_by_snapshot(snapshot_id)
    if not report:
        return jsonify({"error": "未找到对应的报告快照"}), 404
    return jsonify(report)


@app.route("/api/reports/generate", methods=["POST"])
def reports_generate():
    session = request.args.get("session") or latest_session()
    return jsonify(regenerate_report(session))


@app.route("/api/reports/schedule", methods=["GET"])
def reports_schedule():
    return jsonify({"timezone": "Asia/Shanghai", "schedule": report_schedule()})


@app.route("/api/market-calendar", methods=["GET"])
def market_calendar():
    from datetime import date

    market = request.args.get("market", "CN")
    start_value = request.args.get("start") or date.today().isoformat()
    end_value = request.args.get("end") or start_value
    try:
        return jsonify(
            longbridge.fetch_market_calendar(
                market,
                date.fromisoformat(start_value),
                date.fromisoformat(end_value),
            )
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 422


@app.route("/api/heatmap-snapshots/generate", methods=["POST"])
def generate_heatmap_snapshot_api():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(create_heatmap_snapshot(
            str(payload.get("market") or request.args.get("market") or "CN"),
            trigger=str(payload.get("trigger") or "scheduled"),
            scheduled_at=str(payload.get("scheduledAt") or ""),
        ))
    except HeatmapSnapshotError as exc:
        return jsonify({"error": str(exc)}), 503


@app.route("/api/heatmap-snapshots/latest", methods=["GET"])
def latest_heatmap_snapshot_api():
    try:
        snapshot = latest_heatmap_snapshot(
            request.args.get("market", "CN"),
            at_or_before=request.args.get("before", ""),
            scheduled_only=request.args.get("scheduledOnly", "") in {"1", "true", "yes"},
        )
    except HeatmapSnapshotError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(snapshot) if snapshot else (jsonify({"error": "暂无热点图快照"}), 404)


@app.route("/api/heatmap-snapshots/snapshot", methods=["GET"])
def heatmap_snapshot_api():
    snapshot = get_heatmap_snapshot(request.args.get("snapshotId", ""))
    return jsonify(snapshot) if snapshot else (jsonify({"error": "未找到热点图快照"}), 404)


@app.route("/api/heatmap-snapshots/dates", methods=["GET"])
def heatmap_snapshot_dates_api():
    try:
        return jsonify(list_heatmap_snapshot_dates(request.args.get("market", "CN")))
    except HeatmapSnapshotError as exc:
        return jsonify({"error": str(exc)}), 422


@app.route("/api/heatmap-snapshots/history", methods=["GET"])
def heatmap_snapshot_history_api():
    try:
        return jsonify(list_heatmap_snapshot_history(
            request.args.get("market", "CN"),
            request.args.get("date", ""),
        ))
    except HeatmapSnapshotError as exc:
        return jsonify({"error": str(exc)}), 422


def _codex_report_authorized() -> tuple[bool, str]:
    configured = os.getenv("CODEX_REPORT_API_TOKEN", "").strip()
    if not configured:
        return False, "日报查询凭证尚未配置"
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return False, "缺少 Bearer 凭证"
    supplied = authorization[len(prefix):].strip()
    if not supplied or not secrets.compare_digest(configured, supplied):
        return False, "日报查询凭证无效"
    return True, ""


@app.route("/api/codex/reports/latest", methods=["GET"])
def codex_reports_latest():
    authorized, message = _codex_report_authorized()
    if not authorized:
        status = 503 if not os.getenv("CODEX_REPORT_API_TOKEN", "").strip() else 401
        return jsonify({"error": message}), status
    report_session = request.args.get("session") or latest_session()
    return jsonify(get_latest_report(report_session))


@app.route("/api/codex/reports/config", methods=["GET"])
def codex_reports_config():
    authorized, message = _codex_report_authorized()
    if not authorized:
        status = 503 if not os.getenv("CODEX_REPORT_API_TOKEN", "").strip() else 401
        return jsonify({"error": message}), status
    return jsonify(report_automation_config(_public_api_url()))


@app.route("/api/codex/reports/history", methods=["GET"])
def codex_reports_history():
    authorized, message = _codex_report_authorized()
    if not authorized:
        status = 503 if not os.getenv("CODEX_REPORT_API_TOKEN", "").strip() else 401
        return jsonify({"error": message}), status
    report_session = request.args.get("session") or latest_session()
    target_date = request.args.get("date") or ""
    return jsonify(get_history_report(report_session, target_date))


@app.route("/api/codex/reports/generate", methods=["POST"])
def codex_reports_generate():
    authorized, message = _codex_report_authorized()
    if not authorized:
        status = 503 if not os.getenv("CODEX_REPORT_API_TOKEN", "").strip() else 401
        return jsonify({"error": message}), status
    report_session = request.args.get("session") or latest_session()
    return jsonify(regenerate_report(report_session))


@app.route("/api/news", methods=["GET"])
def get_news():
    scope = request.args.get("scope", "all")
    limit = int(request.args.get("limit", 12) or 12)
    return jsonify(news.fetch_market_news(scope=scope, limit=limit))


@app.route("/api/system/status", methods=["GET"])
def get_system_status():
    return jsonify({
        "marketSource": longbridge.diagnostics(),
        "openaiConfigured": bool(__import__("os").getenv("OPENAI_API_KEY")),
    })


@app.route("/api/auth/longbridge/status", methods=["GET"])
def longbridge_auth_status():
    market_status = longbridge.diagnostics()
    oauth_status = longbridge_oauth.auth_status()
    return jsonify(
        {
            "authenticated": market_status["configured"],
            "authMode": market_status["authMode"],
            "sdkAvailable": market_status["sdkAvailable"],
            "oauth": oauth_status,
            "loginUrl": "/api/auth/longbridge/login",
        }
    )


@app.route("/api/auth/longbridge/login", methods=["GET"])
def longbridge_auth_login():
    if longbridge.has_api_credentials():
        return redirect(f"{_public_app_url()}{_safe_next_path(request.args.get('next', ''))}")

    redirect_uri = _oauth_redirect_uri()
    try:
        client_id = longbridge_oauth.ensure_client(redirect_uri)
    except longbridge_oauth.LongbridgeOAuthError as exc:
        logger.exception("准备 Longbridge OAuth 登录失败")
        return _oauth_result_redirect(str(exc))

    state = secrets.token_urlsafe(32)
    session["longbridge_oauth_state"] = state
    session["longbridge_oauth_next"] = _safe_next_path(
        request.args.get("next", "/#dashboard")
    )
    session["longbridge_oauth_redirect_uri"] = redirect_uri
    return redirect(
        longbridge_oauth.build_authorization_url(client_id, redirect_uri, state)
    )


@app.route("/api/auth/longbridge/callback", methods=["GET"])
def longbridge_auth_callback():
    error = request.args.get("error")
    if error:
        detail = request.args.get("error_description") or error
        return _oauth_result_redirect(detail)

    expected_state = session.pop("longbridge_oauth_state", "")
    actual_state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not expected_state or not secrets.compare_digest(expected_state, actual_state):
        return _oauth_result_redirect(
            "登录会话已失效。请始终使用同一个地址访问，例如只使用 localhost，不要和 127.0.0.1 混用。"
        )
    if not code:
        return _oauth_result_redirect("Longbridge 回调缺少 authorization code")

    redirect_uri = session.pop(
        "longbridge_oauth_redirect_uri",
        _oauth_redirect_uri(),
    )
    next_path = session.pop("longbridge_oauth_next", "/#dashboard")
    try:
        client_id = longbridge_oauth.get_client_id()
        longbridge_oauth.exchange_code(client_id, code, redirect_uri)
        longbridge.reset_contexts()
    except longbridge_oauth.LongbridgeOAuthError as exc:
        logger.exception("Longbridge OAuth 回调处理失败")
        return _oauth_result_redirect(str(exc))

    return redirect(f"{_public_app_url()}{next_path}")


@app.route("/api/global-indices", methods=["GET"])
def get_global_indices():
    return jsonify(
        merge_with_lazy_fallback(
            longbridge.fetch_global_indices(),
            legacy_market.fetch_global_indices,
            GLOBAL_INDEX_ORDER,
        )
    )


@app.route("/api/market-breadth", methods=["GET"])
def get_market_breadth():
    return jsonify(sectors_ths.fetch_market_breadth())


@app.route("/api/a-indices", methods=["GET"])
def get_a_indices():
    return jsonify(_major_indices("a"))


@app.route("/api/hk-indices", methods=["GET"])
def get_hk_indices():
    return jsonify(_major_indices("hk"))


@app.route("/api/us-indices", methods=["GET"])
def get_us_indices():
    return jsonify(_major_indices("us"))


@app.route("/api/a-boards", methods=["GET"])
def get_a_boards():
    return jsonify(sectors_ths.fetch_a_boards())


@app.route("/api/sector-heatmap", methods=["GET"])
def get_sector_heatmap():
    market = request.args.get("market", "CN")
    industry = request.args.get("industry", "")
    group = request.args.get("group", "")
    summary_only = request.args.get("summary", "") in {"1", "true", "yes"}
    payload = longbridge.fetch_industry_heatmap(
        market,
        industry,
        group,
        include_stocks=not summary_only,
    )
    if not payload.get("groups"):
        return jsonify({"error": "Longbridge 板块接口当前未返回数据", **payload}), 503
    return jsonify(payload)


@app.route("/api/sector-heatmap/industry", methods=["GET"])
def get_sector_heatmap_industry():
    market = request.args.get("market", "CN")
    industry = request.args.get("industry", "").strip()
    if not industry:
        return jsonify({"error": "缺少行业参数", "industry": {}}), 400
    payload = longbridge.fetch_industry_detail(market, industry)
    if not payload.get("industry"):
        return jsonify({"error": "Longbridge 行业成分接口当前未返回数据", **payload}), 503
    return jsonify(payload)


@app.route("/api/a-board-stocks", methods=["GET"])
def get_a_board_stocks():
    board_name = request.args.get("board", "").strip()
    if not board_name:
        return jsonify({"error": "缺少板块名称参数", "stocks": []}), 400
    return jsonify(sectors_ths.fetch_board_top_stocks(board_name))


@app.route("/api/hk-stocks", methods=["GET"])
def get_hk_stocks():
    return jsonify(
        merge_with_lazy_fallback(
            longbridge.fetch_hk_weight_stocks(),
            legacy_market.fetch_hk_weight_stocks,
            [item["code"] for item in longbridge.HK_WEIGHT_SYMBOLS],
        )
    )


@app.route("/api/us-stocks", methods=["GET"])
def get_us_stocks():
    return jsonify(
        merge_with_lazy_fallback(
            longbridge.fetch_us_weight_stocks(),
            legacy_market.fetch_us_weight_stocks,
            [item["code"] for item in longbridge.US_WEIGHT_SYMBOLS],
        )
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
