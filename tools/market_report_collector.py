#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, time as day_time
from typing import Any
from zoneinfo import ZoneInfo

import requests


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
REPORT_SCHEDULE = {
    "morning": day_time(9, 30),
    "midday": day_time(12, 30),
    "close": day_time(16, 30),
    "us-night": day_time(22, 30),
}
SESSION_MARKETS = {
    "morning": ("CN", "HK"),
    "midday": ("CN", "HK"),
    "close": ("CN", "HK"),
    "us-night": ("US",),
}


def due_session(
    now: datetime,
    executed: set[str],
    grace_seconds: int,
) -> str | None:
    for session, scheduled_time in REPORT_SCHEDULE.items():
        scheduled_at = datetime.combine(now.date(), scheduled_time, REPORT_TIMEZONE)
        if session not in executed and 0 <= (now - scheduled_at).total_seconds() <= grace_seconds:
            return session
    return None


def fetch_calendar(api_url: str, market: str, target_date: date) -> dict[str, Any]:
    response = requests.get(
        f"{api_url}/api/market-calendar",
        params={
            "market": market,
            "start": target_date.isoformat(),
            "end": target_date.isoformat(),
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def is_report_day(api_url: str, session: str, target_date: date) -> bool:
    return any(
        target_date.isoformat() in set(fetch_calendar(api_url, market, target_date).get("tradingDays") or [])
        for market in SESSION_MARKETS[session]
    )


def already_captured(api_url: str, session: str, target_date: date) -> bool:
    response = requests.get(
        f"{api_url}/api/reports/captured",
        params={"session": session, "date": target_date.isoformat()},
        timeout=15,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return bool(response.json().get("snapshotId"))


def capture_report(api_url: str, session: str) -> dict[str, Any]:
    response = requests.post(
        f"{api_url}/api/reports/generate",
        params={"session": session},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def watch(args: argparse.Namespace) -> None:
    executed: set[str] = set()
    active_date: date | None = None
    while True:
        now = datetime.now(REPORT_TIMEZONE)
        if active_date != now.date():
            active_date = now.date()
            executed.clear()
        session = due_session(now, executed, args.grace_seconds)
        if session:
            try:
                if not is_report_day(args.api_url, session, now.date()):
                    result = {"ok": True, "skipped": True, "session": session, "reason": "non-trading-day"}
                elif already_captured(args.api_url, session, now.date()):
                    result = {"ok": True, "skipped": True, "session": session, "reason": "already-captured"}
                else:
                    report = capture_report(args.api_url, session)
                    result = {
                        "ok": True,
                        "session": session,
                        "snapshotId": report.get("snapshotId"),
                        "generatedAt": report.get("generatedAt"),
                        "markets": report.get("marketLabels"),
                    }
                executed.add(session)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({
                    "ok": False,
                    "session": session,
                    "error": str(exc),
                }, ensure_ascii=False), flush=True)
        time.sleep(args.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture fixed-session market report data packages.")
    parser.add_argument("--api-url", default="http://127.0.0.1:5001")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--grace-seconds", type=int, default=300)
    return parser


if __name__ == "__main__":
    watch(build_parser().parse_args())
