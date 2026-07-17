from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from PIL import Image

from services.heatmap_timeline import (
    list_heatmap_timeline_frames,
    resolve_frame_preview_path,
)


class HeatmapTimelineTests(unittest.TestCase):
    def test_default_date_uses_latest_directory_with_frames(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            empty_frames = output_dir / "CN" / "2026-07-11" / "frames"
            latest_frames = output_dir / "CN" / "2026-07-10" / "frames"
            older_frames = output_dir / "CN" / "2026-07-09" / "frames"
            empty_frames.mkdir(parents=True)
            latest_frames.mkdir(parents=True)
            older_frames.mkdir(parents=True)
            (latest_frames / "101500-close-snapshot-heatmap-cn.png").write_bytes(b"png")
            (older_frames / "093000-close-snapshot-heatmap-cn.png").write_bytes(b"png")

            payload = list_heatmap_timeline_frames("CN", output_dir=output_dir)

        self.assertEqual(payload["date"], "2026-07-10")
        self.assertEqual(payload["frameCount"], 1)
        self.assertEqual(payload["frames"][0]["label"], "10:15:00")
        self.assertIn(
            "/api/heatmap-timeline/preview?",
            payload["frames"][0]["previewUrl"],
        )

    def test_all_zero_snapshot_frame_is_excluded_from_playback(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "heatmap-timeline"
            frame_dir = output_dir / "US" / "2026-07-13" / "frames"
            metadata_dir = output_dir / "US" / "2026-07-13" / "metadata"
            snapshot_dir = root / "heatmap-snapshots" / "US" / "2026-07-13"
            frame_dir.mkdir(parents=True)
            metadata_dir.mkdir(parents=True)
            snapshot_dir.mkdir(parents=True)
            zero_frame = frame_dir / "093000-scheduled-zero-heatmap-us.png"
            live_frame = frame_dir / "100000-scheduled-live-heatmap-us.png"
            zero_frame.write_bytes(b"png")
            live_frame.write_bytes(b"png")
            (metadata_dir / f"{zero_frame.stem}.json").write_text(
                json.dumps({"snapshotId": "zero", "trigger": "scheduled"}),
                encoding="utf-8",
            )
            (metadata_dir / f"{live_frame.stem}.json").write_text(
                json.dumps({"snapshotId": "live", "trigger": "scheduled"}),
                encoding="utf-8",
            )
            (snapshot_dir / "zero.json").write_text(
                json.dumps({"industries": [{"code": "a", "changePercent": 0}]}),
                encoding="utf-8",
            )
            (snapshot_dir / "live.json").write_text(
                json.dumps({"industries": [{"code": "a", "changePercent": 0.2}]}),
                encoding="utf-8",
            )

            payload = list_heatmap_timeline_frames(
                "US",
                target_date="2026-07-13",
                output_dir=output_dir,
            )

        self.assertEqual(payload["frameCount"], 1)
        self.assertEqual(payload["frames"][0]["filename"], live_frame.name)

    def test_preview_is_resized_and_cached(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            frame_dir = output_dir / "HK" / "2026-07-14" / "frames"
            frame_dir.mkdir(parents=True)
            frame = frame_dir / "160000-session-close-snapshot-heatmap-hk.png"
            Image.new("RGBA", (3200, 2692), (31, 111, 235, 255)).save(frame)

            preview = resolve_frame_preview_path(
                "HK",
                "2026-07-14",
                frame.name,
                output_dir=output_dir,
            )
            first_mtime = preview.stat().st_mtime_ns
            cached_preview = resolve_frame_preview_path(
                "HK",
                "2026-07-14",
                frame.name,
                output_dir=output_dir,
            )

            with Image.open(preview) as image:
                self.assertEqual(image.size, (1600, 1346))
            self.assertEqual(preview, cached_preview)
            self.assertEqual(first_mtime, cached_preview.stat().st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
