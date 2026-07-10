from __future__ import annotations

import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = ROOT / "tmp" / "heatmap-timeline"
VALID_MARKETS = {"CN", "HK", "US"}


class HeatmapTimelineError(RuntimeError):
    pass


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
    frames = sorted(frame_dir.glob("*.png"))
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


def resolve_frame_path(market: str, target_date: str, filename: str) -> Path:
    normalized_market = market.upper()
    if normalized_market not in VALID_MARKETS:
        raise HeatmapTimelineError(f"unsupported market: {market}")
    if not target_date:
        raise HeatmapTimelineError("date is required")
    if not filename.endswith(".png") or "/" in filename or "\\" in filename:
        raise HeatmapTimelineError("invalid frame filename")
    frame_path = DEFAULT_OUTPUT_DIR / normalized_market / target_date / "frames" / filename
    try:
        frame_path.relative_to(DEFAULT_OUTPUT_DIR)
    except ValueError as exc:
        raise HeatmapTimelineError("invalid frame path") from exc
    if not frame_path.exists():
        raise HeatmapTimelineError("frame not found")
    return frame_path


def list_heatmap_timeline_frames(
    market: str,
    target_date: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    normalized_market = market.upper()
    if normalized_market not in VALID_MARKETS:
        raise HeatmapTimelineError(f"unsupported market: {market}")
    date_key = target_date or datetime.now().strftime("%Y-%m-%d")
    frame_dir = output_dir / normalized_market / date_key / "frames"
    frames = []
    for frame in sorted(frame_dir.glob("*.png")):
        captured_at = frame.name.split("-", 1)[0]
        label = captured_at
        if len(captured_at) == 6 and captured_at.isdigit():
            label = f"{captured_at[:2]}:{captured_at[2:4]}:{captured_at[4:6]}"
        frames.append({
            "filename": frame.name,
            "label": label,
            "capturedAt": captured_at,
            "size": frame.stat().st_size,
            "url": (
                "/api/heatmap-timeline/frame"
                f"?market={normalized_market}&date={date_key}&filename={frame.name}"
            ),
        })
    return {
        "market": normalized_market,
        "date": date_key,
        "frameCount": len(frames),
        "frames": frames,
    }
