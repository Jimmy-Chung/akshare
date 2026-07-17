#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from datetime import date, datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "http://127.0.0.1:5001"
SNAPSHOT_LOCK_DIR = ROOT / "tmp" / "heatmap-snapshots" / ".locks"
MARKET_LABELS = {"CN": "A股", "HK": "港股", "US": "美股"}
MARKET_TIMEZONES = {
    "CN": ZoneInfo("Asia/Shanghai"),
    "HK": ZoneInfo("Asia/Hong_Kong"),
    "US": ZoneInfo("America/New_York"),
}
MARKET_TRADING_WINDOWS = {
    "CN": [(day_time(9, 30), day_time(11, 30)), (day_time(13, 0), day_time(15, 0))],
    "HK": [(day_time(9, 30), day_time(12, 0)), (day_time(13, 0), day_time(16, 0))],
    "US": [(day_time(9, 30), day_time(16, 0))],
}
WEEKEND_DAYS = {5, 6}


def ensure_backend(api_url: str) -> None:
    response = requests.get(f"{api_url}/api/system/status", timeout=5)
    response.raise_for_status()


def generate_heatmap_snapshot(
    api_url: str,
    market: str,
    trigger: str,
    scheduled_at: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{api_url}/api/heatmap-snapshots/generate",
        json={"market": market, "trigger": trigger, "scheduledAt": scheduled_at},
        timeout=150,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("snapshotId"):
        raise RuntimeError("heatmap snapshot did not include snapshotId")
    return payload


def is_market_open(market: str, moment: datetime | None = None) -> tuple[bool, str]:
    normalized_market = market.upper()
    timezone = MARKET_TIMEZONES[normalized_market]
    local_now = (moment or datetime.now(timezone)).astimezone(timezone)
    if local_now.weekday() in WEEKEND_DAYS:
        return False, f"{MARKET_LABELS[normalized_market]} weekend: {local_now.isoformat(timespec='seconds')}"
    for start, end in MARKET_TRADING_WINDOWS[normalized_market]:
        if start <= local_now.time() <= end:
            return True, f"{MARKET_LABELS[normalized_market]} open: {local_now.isoformat(timespec='seconds')}"
    windows = ", ".join(
        f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
        for start, end in MARKET_TRADING_WINDOWS[normalized_market]
    )
    return False, (
        f"{MARKET_LABELS[normalized_market]} closed: "
        f"{local_now.isoformat(timespec='seconds')} local, trading windows {windows}"
    )


def capture_check_moment(market: str, trigger: str, scheduled_at: str) -> datetime | None:
    if trigger not in {"scheduled", "session-close"} or not scheduled_at:
        return None
    try:
        moment = datetime.fromisoformat(scheduled_at)
    except ValueError as exc:
        raise ValueError(f"invalid scheduledAt: {scheduled_at}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=MARKET_TIMEZONES[market.upper()])
    return moment


def capture_once(args: argparse.Namespace) -> dict[str, Any]:
    """Collect one JSON snapshot. The historical PNG/video pipeline is intentionally retired."""
    if not args.force:
        check_moment = capture_check_moment(args.market, args.trigger, args.scheduled_at)
        open_now, reason = is_market_open(args.market, check_moment)
        if not open_now:
            return {
                "skipped": True,
                "reason": reason,
                "market": args.market,
                "collectedAt": datetime.now(MARKET_TIMEZONES[args.market]).isoformat(timespec="seconds"),
            }

    ensure_backend(args.api_url)
    SNAPSHOT_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_handle = (SNAPSHOT_LOCK_DIR / f"{args.market.lower()}.lock").open("w")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
    try:
        snapshot = generate_heatmap_snapshot(
            args.api_url,
            args.market,
            args.trigger,
            args.scheduled_at,
        )
        return {
            "market": snapshot["market"],
            "snapshotId": snapshot["snapshotId"],
            "trigger": snapshot.get("trigger"),
            "scheduledAt": snapshot.get("scheduledAt"),
            "capturedAt": snapshot.get("capturedAt"),
            "industryCount": len(snapshot.get("industries") or []),
            "storage": "snapshot-json",
        }
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def fetch_market_calendar(api_url: str, market: str, target_date: date) -> dict[str, Any]:
    response = requests.get(
        f"{api_url}/api/market-calendar",
        params={"market": market, "start": target_date.isoformat(), "end": target_date.isoformat()},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def calendar_slots(market: str, target_date: date, calendar: dict[str, Any]) -> list[datetime]:
    if target_date.isoformat() not in set(calendar.get("tradingDays") or []):
        return []
    timezone = MARKET_TIMEZONES[market]
    sessions = list(calendar.get("sessions") or [])
    if target_date.isoformat() in set(calendar.get("halfTradingDays") or []):
        half_close = {"CN": "11:30", "HK": "12:00", "US": "13:00"}[market]
        sessions = [{"open": sessions[0]["open"], "close": half_close}] if sessions else []
    slots: set[datetime] = set()
    for session in sessions:
        opening = datetime.combine(target_date, day_time.fromisoformat(session["open"]), timezone)
        closing = datetime.combine(target_date, day_time.fromisoformat(session["close"]), timezone)
        current = opening
        while current <= closing:
            slots.add(current)
            current += timedelta(minutes=30)
        slots.add(closing)
    return sorted(slots)


def watch(args: argparse.Namespace) -> None:
    executed: set[str] = set()
    calendar_date: date | None = None
    calendar: dict[str, Any] = {}
    while True:
        now = datetime.now(MARKET_TIMEZONES[args.market])
        if calendar_date != now.date():
            try:
                calendar = fetch_market_calendar(args.api_url, args.market, now.date())
                calendar_date = now.date()
                executed.clear()
            except Exception as exc:
                print(json.dumps({"ok": False, "error": f"calendar: {exc}"}), file=sys.stderr, flush=True)
                time.sleep(60)
                continue
        slots = calendar_slots(args.market, now.date(), calendar)
        due = next(
            (
                slot for slot in slots
                if slot.isoformat() not in executed
                and 0 <= (now - slot).total_seconds() <= args.grace_seconds
            ),
            None,
        )
        if due:
            args.scheduled_at = due.isoformat(timespec="seconds")
            args.trigger = "session-close" if due == slots[-1] else "scheduled"
            try:
                metadata = capture_once(args)
                executed.add(due.isoformat())
                print(json.dumps({"ok": True, **metadata}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(
                    json.dumps(
                        {"ok": False, "scheduledAt": args.scheduled_at, "error": str(exc)},
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
        time.sleep(args.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect market heatmap snapshots as JSON.")
    parser.add_argument("--market", choices=["CN", "HK", "US"], default="HK")
    parser.add_argument("--session", default="close", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=9233, help=argparse.SUPPRESS)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--force", action="store_true", help="Collect outside regular trading hours.")
    parser.add_argument("--trigger", default="scheduled", choices=["scheduled", "session-close", "manual"])
    parser.add_argument("--scheduled-at", default="")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capture", help="Collect one JSON snapshot.")
    watch_parser = subparsers.add_parser("watch", help="Collect scheduled JSON snapshots.")
    watch_parser.add_argument("--poll-seconds", type=int, default=10)
    watch_parser.add_argument("--grace-seconds", type=int, default=180)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.market = args.market.upper()
    if args.command == "capture":
        print(json.dumps(capture_once(args), ensure_ascii=False, indent=2))
    else:
        watch(args)


if __name__ == "__main__":
    main()
