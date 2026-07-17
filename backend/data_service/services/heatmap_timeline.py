from __future__ import annotations

import json
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = ROOT / "tmp" / "heatmap-timeline"
DEFAULT_PREVIEW_WIDTH = 1600
VALID_MARKETS = {"CN", "HK", "US"}


class HeatmapTimelineError(RuntimeError):
    pass


def _frame_metadata(frame: Path) -> dict[str, Any]:
    metadata_path = frame.parent.parent / "metadata" / f"{frame.stem}.json"
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _timeline_frame_eligible(
    frame: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> bool:
    metadata = _frame_metadata(frame)
    if str(metadata.get("trigger") or "scheduled") == "manual":
        return False
    snapshot_id = str(metadata.get("snapshotId") or "")
    if not snapshot_id:
        return True
    try:
        relative = frame.relative_to(output_dir)
        market, target_date = relative.parts[:2]
    except (ValueError, IndexError):
        return True
    snapshot_path = output_dir.parent / "heatmap-snapshots" / market / target_date / f"{snapshot_id}.json"
    snapshot = _read_json(snapshot_path)
    industries = snapshot.get("industries") or []
    if not industries:
        return True
    return any(
        abs(float(item.get("changePercent") or 0)) > 1e-9
        for item in industries
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def render_heatmap_timeline_video(
    market: str,
    target_date: str = "",
    fps: float = 2.0,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    normalized_market = market.upper()
    if normalized_market not in VALID_MARKETS:
        raise HeatmapTimelineError(f"unsupported market: {market}")
    if fps <= 0:
        raise HeatmapTimelineError("fps must be greater than 0")
    if shutil.which("ffmpeg") is None:
        raise HeatmapTimelineError("ffmpeg is not available")

    date_key = target_date or datetime.now().strftime("%Y-%m-%d")
    frame_dir = output_dir / normalized_market / date_key / "frames"
    frames = [
        frame
        for frame in sorted(frame_dir.glob("*.png"))
        if _timeline_frame_eligible(frame, output_dir)
    ]
    if not frames:
        raise HeatmapTimelineError(f"no heatmap frames found for {normalized_market} on {date_key}")

    video_dir = output_dir / normalized_market / date_key / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    concat_path = video_dir / "frames.txt"
    frame_duration = 1 / fps
    with concat_path.open("w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(f"file '{frame}'\n")
            handle.write(f"duration {frame_duration:.6f}\n")
        handle.write(f"file '{frames[-1]}'\n")

    output_path = video_dir / f"{date_key}-{normalized_market}-heatmap-timeline.mp4"
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
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise HeatmapTimelineError(f"failed to render heatmap timeline video: {message}") from exc

    return {
        "market": normalized_market,
        "date": date_key,
        "fps": fps,
        "frameCount": len(frames),
        "firstFrame": str(frames[0]),
        "lastFrame": str(frames[-1]),
        "outputPath": str(output_path),
        "relativeOutputPath": str(output_path.relative_to(ROOT)),
    }


def resolve_frame_path(
    market: str,
    target_date: str,
    filename: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    normalized_market = market.upper()
    if normalized_market not in VALID_MARKETS:
        raise HeatmapTimelineError(f"unsupported market: {market}")
    if not target_date:
        raise HeatmapTimelineError("date is required")
    if not filename.endswith(".png") or "/" in filename or "\\" in filename:
        raise HeatmapTimelineError("invalid frame filename")
    frame_path = output_dir / normalized_market / target_date / "frames" / filename
    try:
        frame_path.relative_to(output_dir)
    except ValueError as exc:
        raise HeatmapTimelineError("invalid frame path") from exc
    if not frame_path.exists():
        raise HeatmapTimelineError("frame not found")
    return frame_path


def resolve_frame_preview_path(
    market: str,
    target_date: str,
    filename: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_width: int = DEFAULT_PREVIEW_WIDTH,
) -> Path:
    if max_width <= 0:
        raise HeatmapTimelineError("preview width must be greater than 0")
    frame_path = resolve_frame_path(
        market,
        target_date,
        filename,
        output_dir=output_dir,
    )
    preview_path = (
        frame_path.parent.parent
        / "previews"
        / str(max_width)
        / frame_path.name
    )
    if (
        preview_path.exists()
        and preview_path.stat().st_mtime_ns >= frame_path.stat().st_mtime_ns
    ):
        return preview_path

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with Image.open(frame_path) as source:
            source.load()
            preview = source.copy()
            preview.thumbnail(
                (max_width, max_width),
                Image.Resampling.LANCZOS,
            )
            with NamedTemporaryFile(
                dir=preview_path.parent,
                prefix=f".{preview_path.stem}-",
                suffix=".png",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            preview.save(temporary_path, format="PNG", optimize=True)
        temporary_path.replace(preview_path)
    except (OSError, ValueError) as exc:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise HeatmapTimelineError(
            f"failed to create frame preview: {filename}"
        ) from exc
    return preview_path


def list_heatmap_timeline_frames(
    market: str,
    target_date: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    normalized_market = market.upper()
    if normalized_market not in VALID_MARKETS:
        raise HeatmapTimelineError(f"unsupported market: {market}")
    date_key = target_date
    if not date_key or date_key == "latest":
        market_dir = output_dir / normalized_market
        dated_dirs = sorted(
            (
                item
                for item in market_dir.iterdir()
                if item.is_dir()
                and len(item.name) == 10
                and any(
                    _timeline_frame_eligible(frame, output_dir)
                    for frame in (item / "frames").glob("*.png")
                )
            ),
            key=lambda item: item.name,
            reverse=True,
        ) if market_dir.exists() else []
        date_key = dated_dirs[0].name if dated_dirs else datetime.now().strftime("%Y-%m-%d")
    frame_dir = output_dir / normalized_market / date_key / "frames"
    frames = []
    for frame in sorted(frame_dir.glob("*.png")):
        metadata = _frame_metadata(frame)
        trigger = str(metadata.get("trigger") or "scheduled")
        if not _timeline_frame_eligible(frame, output_dir):
            continue
        scheduled_at = str(metadata.get("scheduledAt") or "")
        captured_at = frame.name.split("-", 1)[0]
        label = captured_at
        if scheduled_at:
            label = scheduled_at[11:16]
        elif len(captured_at) == 6 and captured_at.isdigit():
            label = f"{captured_at[:2]}:{captured_at[2:4]}:{captured_at[4:6]}"
        frames.append({
            "filename": frame.name,
            "label": label,
            "capturedAt": captured_at,
            "scheduledAt": scheduled_at,
            "trigger": trigger,
            "snapshotId": str(metadata.get("snapshotId") or ""),
            "size": frame.stat().st_size,
            "url": (
                "/api/heatmap-timeline/frame"
                f"?market={normalized_market}&date={date_key}&filename={frame.name}"
            ),
            "previewUrl": (
                "/api/heatmap-timeline/preview"
                f"?market={normalized_market}&date={date_key}&filename={frame.name}"
            ),
        })
    frames.sort(key=lambda item: item.get("scheduledAt") or item.get("capturedAt") or "")
    return {
        "market": normalized_market,
        "date": date_key,
        "frameCount": len(frames),
        "frames": frames,
    }
