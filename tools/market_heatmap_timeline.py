#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time as day_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import websockets
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "tmp" / "heatmap-timeline"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_APP_URL = "http://127.0.0.1:3005"
DEFAULT_API_URL = "http://127.0.0.1:5001"
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
SYSTEM_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CaptureTarget:
    market: str
    session: str
    snapshot_id: str
    page_url: str
    chart_id: str
    export_button_id: str
    filename: str


class CdpClient:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self._sequence = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._socket: Any = None
        self._reader_task: asyncio.Task | None = None

    async def __aenter__(self) -> "CdpClient":
        self._socket = await websockets.connect(self.websocket_url, max_size=100 * 1024 * 1024)
        self._reader_task = asyncio.create_task(self._read_messages())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._socket:
            await self._socket.close()

    async def _read_messages(self) -> None:
        async for raw in self._socket:
            message = json.loads(raw)
            message_id = message.get("id")
            if message_id in self._pending:
                self._pending.pop(message_id).set_result(message)

    async def send(self, method: str, params: dict[str, Any] | None = None, timeout: float = 45) -> dict[str, Any]:
        self._sequence += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[self._sequence] = future
        await self._socket.send(json.dumps({"id": self._sequence, "method": method, "params": params or {}}))
        result = await asyncio.wait_for(future, timeout=timeout)
        if "error" in result:
            raise RuntimeError(f"{method} failed: {result['error']}")
        return result.get("result", {})


def ensure_services(app_url: str, api_url: str) -> None:
    checks = [
        ("frontend", app_url),
        ("backend", f"{api_url}/api/system/status"),
    ]
    for name, url in checks:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        print(f"{name} ok: {url}", file=sys.stderr)


def generate_report(api_url: str, session: str) -> dict[str, Any]:
    response = requests.post(f"{api_url}/api/reports/generate", params={"session": session}, timeout=90)
    response.raise_for_status()
    payload = response.json()
    if payload.get("session") != session:
        raise RuntimeError(f"unexpected report session: {payload.get('session')}")
    if not payload.get("snapshotId"):
        raise RuntimeError("generated report did not include snapshotId")
    return payload


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


def target_from_report(report: dict[str, Any], market: str) -> CaptureTarget:
    normalized_market = market.upper()
    for export in report.get("chartExports", []):
        if export.get("kind") == "heatmap" and export.get("market") == normalized_market:
            return CaptureTarget(
                market=normalized_market,
                session=report["session"],
                snapshot_id=report["snapshotId"],
                page_url=export["pageUrl"],
                chart_id=export["chartId"],
                export_button_id=export["exportButtonId"],
                filename=export["filename"],
            )
    if report.get("snapshotId") and report.get("session"):
        return target_from_snapshot(report["session"], report["snapshotId"], normalized_market)
    raise RuntimeError(f"report has no heatmap export target for {normalized_market}")


def target_from_snapshot(session: str, snapshot_id: str, market: str) -> CaptureTarget:
    normalized_market = market.upper()
    chart_id = f"heatmap-{normalized_market.lower()}"
    return CaptureTarget(
        market=normalized_market,
        session=session,
        snapshot_id=snapshot_id,
        page_url=f"/?session={session}&snapshotId={snapshot_id}#report",
        chart_id=chart_id,
        export_button_id=chart_id,
        filename=f"{session}-{chart_id}.png",
    )


def target_from_heatmap_snapshot(snapshot: dict[str, Any]) -> CaptureTarget:
    market = str(snapshot["market"]).upper()
    snapshot_id = str(snapshot["snapshotId"])
    chart_id = f"heatmap-{market.lower()}"
    return CaptureTarget(
        market=market,
        session=str(snapshot.get("trigger") or "scheduled"),
        snapshot_id=snapshot_id,
        page_url=(
            f"/?market={market}&heatmapSnapshotId={snapshot_id}&heatmapExport=1#dashboard"
        ),
        chart_id=chart_id,
        export_button_id=chart_id,
        filename=f"{snapshot_id}-{chart_id}.png",
    )


def output_paths(
    output_dir: Path,
    target: CaptureTarget,
    captured_at: datetime,
    target_date: str = "",
) -> tuple[Path, Path]:
    market_time = captured_at.astimezone(MARKET_TIMEZONES[target.market])
    date_key = target_date or market_time.strftime("%Y-%m-%d")
    stamp = market_time.strftime("%H%M%S")
    frame_dir = output_dir / target.market / date_key / "frames"
    meta_dir = output_dir / target.market / date_key / "metadata"
    frame_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    base = f"{stamp}-{target.session}-{target.snapshot_id}-{target.chart_id}"
    return frame_dir / f"{base}.png", meta_dir / f"{base}.json"


def validate_png(path: Path, min_width: int = 2400, min_height: int = 1800) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if width < min_width or height < min_height:
            raise RuntimeError(f"PNG too small: {width}x{height}, expected at least {min_width}x{min_height}")
        return {"width": width, "height": height, "mode": image.mode}


def is_market_open(market: str, moment: datetime | None = None) -> tuple[bool, str]:
    normalized_market = market.upper()
    timezone = MARKET_TIMEZONES[normalized_market]
    local_now = (moment or datetime.now(timezone)).astimezone(timezone)
    if local_now.weekday() in WEEKEND_DAYS:
        return False, f"{MARKET_LABELS.get(normalized_market, normalized_market)} weekend: {local_now.isoformat(timespec='seconds')}"
    current_time = local_now.time()
    windows = MARKET_TRADING_WINDOWS[normalized_market]
    for start, end in windows:
        if start <= current_time <= end:
            return True, f"{MARKET_LABELS.get(normalized_market, normalized_market)} open: {local_now.isoformat(timespec='seconds')}"
    window_text = ", ".join(f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}" for start, end in windows)
    return False, (
        f"{MARKET_LABELS.get(normalized_market, normalized_market)} closed: "
        f"{local_now.isoformat(timespec='seconds')} local, trading windows {window_text}"
    )


def capture_check_moment(
    market: str,
    trigger: str,
    scheduled_at: str,
) -> datetime | None:
    if trigger not in {"scheduled", "session-close"} or not scheduled_at:
        return None
    try:
        moment = datetime.fromisoformat(scheduled_at)
    except ValueError as exc:
        raise ValueError(f"invalid scheduledAt: {scheduled_at}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=MARKET_TIMEZONES[market.upper()])
    return moment


async def export_heatmap_png(
    websocket_url: str,
    app_url: str,
    target: CaptureTarget,
    destination: Path,
    wait_ms: int,
) -> dict[str, Any]:
    async with CdpClient(websocket_url) as cdp:
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Page.navigate", {"url": f"{app_url}{target.page_url}"})

        selector = f'[data-chart-id="{target.chart_id}"]'
        button_selector = f'button[data-export-chart-id="{target.export_button_id}"]'
        deadline = time.time() + 60
        last_state: dict[str, Any] | None = None
        while time.time() < deadline:
            state_result = await cdp.send(
                "Runtime.evaluate",
                {
                    "returnByValue": True,
                    "expression": f"""
(() => {{
  const card = document.querySelector({json.dumps(selector)});
  const button = document.querySelector({json.dumps(button_selector)});
  const canvas = card?.querySelector('canvas');
  const text = card?.textContent || '';
  const rect = card?.getBoundingClientRect();
  return {{
    ready: !!card && !!button && !button.disabled && !!canvas &&
      canvas.width > 0 && canvas.height > 0 &&
      rect.width >= 600 && rect.height >= 400 &&
      !/加载中|暂无/.test(text),
    card: rect ? {{ width: Math.round(rect.width), height: Math.round(rect.height) }} : null,
    canvas: canvas ? {{ width: canvas.width, height: canvas.height }} : null,
    textLength: text.length,
  }};
}})()
""",
                },
            )
            last_state = state_result.get("result", {}).get("value")
            if last_state and last_state.get("ready"):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError(f"heatmap did not become ready: {last_state}")

        export_result = await cdp.send(
            "Runtime.evaluate",
            {
                "awaitPromise": True,
                "returnByValue": True,
                "timeout": 60000,
                "expression": f"""
(async () => {{
  const card = document.querySelector({json.dumps(selector)});
  const stage = card?.closest('.report-heatmap-export-stage');
  const button = document.querySelector({json.dumps(button_selector)});
  card?.scrollIntoView({{ block: 'center', inline: 'start' }});
  if (stage) stage.scrollLeft = 0;
  window.dispatchEvent(new Event('resize'));
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await new Promise((resolve) => setTimeout(resolve, {wait_ms}));

  window.__heatmapTimelineDownload = null;
  const originalClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function() {{
    window.__heatmapTimelineDownload = {{ href: this.href, download: this.download }};
  }};
  button.scrollIntoView({{ block: 'center', inline: 'nearest' }});
  await new Promise((resolve) => requestAnimationFrame(resolve));
  button.click();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  HTMLAnchorElement.prototype.click = originalClick;

  const captured = window.__heatmapTimelineDownload;
  let base64 = '';
  if (captured?.href) {{
    const buffer = await fetch(captured.href).then((response) => response.arrayBuffer());
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    let binary = '';
    for (let i = 0; i < bytes.length; i += chunkSize) {{
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }}
    base64 = btoa(binary);
  }}
  const rect = card?.getBoundingClientRect();
  const canvas = card?.querySelector('canvas');
  return {{
    download: captured,
    base64,
    card: rect ? {{ width: Math.round(rect.width), height: Math.round(rect.height), x: Math.round(rect.x), y: Math.round(rect.y) }} : null,
    canvas: canvas ? {{ width: canvas.width, height: canvas.height }} : null,
    annotationPrefix: card?.querySelector('.report-heatmap-annotation')?.textContent?.slice(0, 120) || '',
  }};
}})()
""",
            },
            timeout=75,
        )
        payload = export_result.get("result", {}).get("value") or {}
        encoded = payload.get("base64") or ""
        if not encoded:
            raise RuntimeError(f"export did not produce PNG bytes: {payload}")
        tmp = destination.with_suffix(".tmp.png")
        tmp.write_bytes(base64.b64decode(encoded))
        tmp.replace(destination)
        return payload


def start_chrome(chrome_path: str, port: int, profile_dir: Path) -> subprocess.Popen:
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    command = [
        chrome_path,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--window-size=4096,3200",
        "about:blank",
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_chrome(port: int) -> None:
    version_url = f"http://127.0.0.1:{port}/json/version"
    for _ in range(60):
        try:
            requests.get(version_url, timeout=0.5).raise_for_status()
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Chrome remote debugging did not start")


def new_chrome_tab(port: int, url: str) -> str:
    encoded_url = urllib.parse.quote(url, safe=":/?=&%#")
    response = requests.put(f"http://127.0.0.1:{port}/json/new?{encoded_url}", timeout=5)
    response.raise_for_status()
    return response.json()["webSocketDebuggerUrl"]


def capture_once(args: argparse.Namespace) -> dict[str, Any]:
    if not args.force:
        check_moment = capture_check_moment(
            args.market,
            args.trigger,
            args.scheduled_at,
        )
        open_now, reason = is_market_open(args.market, check_moment)
        if not open_now:
            return {
                "skipped": True,
                "reason": reason,
                "market": args.market,
                "session": args.session,
                "capturedAt": datetime.now(SYSTEM_TIMEZONE).isoformat(timespec="seconds"),
            }

    ensure_services(args.app_url, args.api_url)
    captured_at = datetime.now(SYSTEM_TIMEZONE)
    lock_dir = args.output_dir / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = (lock_dir / f"{args.market.lower()}.lock").open("w")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
    try:
        snapshot = generate_heatmap_snapshot(
            args.api_url,
            args.market,
            args.trigger,
            args.scheduled_at,
        )
        target = target_from_heatmap_snapshot(snapshot)
        existing_image = snapshot.get("image") or {}
        if (
            existing_image.get("path")
            and Path(existing_image["path"]).exists()
            and not args.force
        ):
            return {
                "reused": True,
                "market": args.market,
                "snapshotId": snapshot["snapshotId"],
                "scheduledAt": snapshot.get("scheduledAt"),
                "path": existing_image["path"],
                "png": existing_image,
            }

        destination, metadata_path = output_paths(args.output_dir, target, captured_at, args.target_date)
        profile_dir = args.output_dir / f".chrome-profile-{args.market.lower()}-{args.port}"
        chrome = start_chrome(args.chrome, args.port, profile_dir)
        try:
            wait_for_chrome(args.port)
            websocket_url = new_chrome_tab(args.port, f"{args.app_url}{target.page_url}")
            export_payload = asyncio.run(
                export_heatmap_png(
                    websocket_url,
                    args.app_url,
                    target,
                    destination,
                    args.wait_ms,
                )
            )
        finally:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()

        try:
            png = validate_png(destination, args.min_width, args.min_height)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        response = requests.post(
            f"{args.api_url}/api/heatmap-snapshots/image",
            json={
                "snapshotId": target.snapshot_id,
                "path": str(destination),
                "width": png["width"],
                "height": png["height"],
                "size": destination.stat().st_size,
            },
            timeout=15,
        )
        response.raise_for_status()
        metadata = {
            "capturedAt": captured_at.isoformat(timespec="seconds"),
            "marketCapturedAt": captured_at.astimezone(MARKET_TIMEZONES[target.market]).isoformat(timespec="seconds"),
            "scheduledAt": snapshot.get("scheduledAt"),
            "trigger": snapshot.get("trigger"),
            "market": target.market,
            "marketLabel": MARKET_LABELS.get(target.market, target.market),
            "session": target.session,
            "snapshotId": target.snapshot_id,
            "pageUrl": target.page_url,
            "chartId": target.chart_id,
            "path": str(destination),
            "png": png,
            "export": {
                key: value
                for key, value in export_payload.items()
                if key not in {"base64"}
            },
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def render_video(args: argparse.Namespace) -> Path:
    date_key = args.date or datetime.now().strftime("%Y-%m-%d")
    frame_dir = args.output_dir / args.market.upper() / date_key / "frames"
    frames = sorted(frame_dir.glob("*.png"))
    if not frames:
        raise RuntimeError(f"no frames found in {frame_dir}")
    video_dir = args.output_dir / args.market.upper() / date_key / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    concat_path = video_dir / "frames.txt"
    frame_duration = 1 / args.fps
    with concat_path.open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(f"file '{frame}'\n")
            handle.write(f"duration {frame_duration:.6f}\n")
        handle.write(f"file '{frames[-1]}'\n")
    output_path = video_dir / f"{date_key}-{args.market.upper()}-heatmap-timeline.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-vf",
        "scale=1920:-2,format=yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    subprocess.run(command, check=True)
    return output_path


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
                print(json.dumps({"ok": False, "scheduledAt": args.scheduled_at, "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        time.sleep(args.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture market heatmap frames and render a timeline video.")
    parser.add_argument("--market", choices=["CN", "HK", "US"], default="HK")
    parser.add_argument("--session", default="close", help="Report session to generate or open.")
    parser.add_argument("--snapshot-id", default="", help="Use an existing report snapshot instead of regenerating.")
    parser.add_argument("--app-url", default=DEFAULT_APP_URL)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--chrome", default=DEFAULT_CHROME)
    parser.add_argument("--port", type=int, default=9233)
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--min-width", type=int, default=3000)
    parser.add_argument("--min-height", type=int, default=2600)
    parser.add_argument("--force", action="store_true", help="Capture even when the market is outside regular trading hours.")
    parser.add_argument("--trigger", default="scheduled", choices=["scheduled", "session-close", "manual"])
    parser.add_argument("--scheduled-at", default="")
    parser.add_argument("--target-date", default="", help="Override the output timeline date for manual backfills.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capture", help="Capture one heatmap frame.")
    watch_parser = subparsers.add_parser("watch", help="Capture a heatmap frame repeatedly.")
    watch_parser.add_argument("--poll-seconds", type=int, default=10)
    watch_parser.add_argument("--grace-seconds", type=int, default=180)
    render_parser = subparsers.add_parser("render", help="Render captured frames into MP4.")
    render_parser.add_argument("--date", default="")
    render_parser.add_argument("--fps", type=float, default=2.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.market = args.market.upper()
    args.output_dir = args.output_dir.resolve()
    if args.command == "capture":
        print(json.dumps(capture_once(args), ensure_ascii=False, indent=2))
    elif args.command == "watch":
        watch(args)
    elif args.command == "render":
        print(render_video(args))


if __name__ == "__main__":
    main()
