from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services import heatmap_snapshots


class HeatmapSnapshotTests(unittest.TestCase):
    @staticmethod
    def payload(change: float, updated_at: str = "2026-07-13T10:00:01+08:00"):
        return {
            "source": "Longbridge",
            "updatedAt": updated_at,
            "groups": [{"name": "科技", "code": "group", "changePercent": change}],
            "industries": [{"name": "半导体", "code": "industry", "changePercent": change}],
        }

    def test_snapshot_is_deduplicated_by_market_and_scheduled_slot(self):
        payload = {
            "source": "Longbridge",
            "updatedAt": "2026-07-13T10:00:01+08:00",
            "groups": [{"name": "科技", "code": "group", "changePercent": 0.2}],
            "industries": [{"name": "半导体", "code": "industry", "changePercent": 0.2}],
        }
        with (
            TemporaryDirectory() as tmp,
            patch.object(heatmap_snapshots, "ROOT", Path(tmp).resolve()),
            patch.object(heatmap_snapshots, "SNAPSHOT_DIR", Path(tmp).resolve() / "snapshots"),
            patch.object(
                heatmap_snapshots.longbridge,
                "fetch_industry_heatmap",
                return_value=payload,
            ) as fetcher,
        ):
            first = heatmap_snapshots.create_heatmap_snapshot(
                "CN",
                scheduled_at="2026-07-13T10:00:00+08:00",
            )
            second = heatmap_snapshots.create_heatmap_snapshot(
                "CN",
                scheduled_at="2026-07-13T10:00:00+08:00",
            )

        self.assertEqual(first["snapshotId"], second["snapshotId"])
        self.assertEqual(fetcher.call_count, 1)

    def test_scheduled_snapshot_retries_all_zero_until_market_moves(self):
        with (
            TemporaryDirectory() as tmp,
            patch.object(heatmap_snapshots, "ROOT", Path(tmp).resolve()),
            patch.object(heatmap_snapshots, "SNAPSHOT_DIR", Path(tmp).resolve() / "snapshots"),
            patch.object(heatmap_snapshots.time, "sleep") as sleeper,
            patch.object(
                heatmap_snapshots.longbridge,
                "fetch_industry_heatmap",
                side_effect=[self.payload(0), self.payload(0.42)],
            ) as fetcher,
        ):
            snapshot = heatmap_snapshots.create_heatmap_snapshot(
                "US",
                scheduled_at="2026-07-13T10:00:00-04:00",
            )

        self.assertEqual(snapshot["industries"][0]["changePercent"], 0.42)
        self.assertEqual(fetcher.call_count, 2)
        self.assertEqual(fetcher.call_args_list[1].kwargs["force_refresh"], True)
        sleeper.assert_called_once_with(heatmap_snapshots.FRESHNESS_RETRY_SECONDS)

    def test_scheduled_snapshot_retries_data_identical_to_previous_frame(self):
        with (
            TemporaryDirectory() as tmp,
            patch.object(heatmap_snapshots, "ROOT", Path(tmp).resolve()),
            patch.object(heatmap_snapshots, "SNAPSHOT_DIR", Path(tmp).resolve() / "snapshots"),
            patch.object(heatmap_snapshots.time, "sleep"),
            patch.object(
                heatmap_snapshots.longbridge,
                "fetch_industry_heatmap",
                side_effect=[self.payload(0.2), self.payload(0.2), self.payload(0.35)],
            ) as fetcher,
        ):
            first = heatmap_snapshots.create_heatmap_snapshot(
                "US",
                scheduled_at="2026-07-13T10:00:00-04:00",
            )
            second = heatmap_snapshots.create_heatmap_snapshot(
                "US",
                scheduled_at="2026-07-13T10:30:00-04:00",
            )

        self.assertNotEqual(first["dataFingerprint"], second["dataFingerprint"])
        self.assertEqual(fetcher.call_count, 3)

    def test_persistent_duplicate_is_rejected_without_writing_a_frame(self):
        repeated = self.payload(0.2)
        with (
            TemporaryDirectory() as tmp,
            patch.object(heatmap_snapshots, "ROOT", Path(tmp).resolve()),
            patch.object(heatmap_snapshots, "SNAPSHOT_DIR", Path(tmp).resolve() / "snapshots"),
            patch.object(heatmap_snapshots, "FRESHNESS_ATTEMPTS", 2),
            patch.object(heatmap_snapshots.time, "sleep"),
            patch.object(
                heatmap_snapshots.longbridge,
                "fetch_industry_heatmap",
                side_effect=[repeated, repeated, repeated],
            ),
        ):
            heatmap_snapshots.create_heatmap_snapshot(
                "US",
                scheduled_at="2026-07-13T10:00:00-04:00",
            )
            with self.assertRaisesRegex(heatmap_snapshots.HeatmapSnapshotError, "match previous"):
                heatmap_snapshots.create_heatmap_snapshot(
                    "US",
                    scheduled_at="2026-07-13T10:30:00-04:00",
                )
            files = list((Path(tmp).resolve() / "snapshots").glob("**/*.json"))

        self.assertEqual(len(files), 1)

    def test_completed_image_is_available_to_consumers(self):
        payload = {
            "source": "Longbridge",
            "groups": [{"name": "科技", "code": "group"}],
            "industries": [{"name": "半导体", "code": "industry"}],
        }
        with (
            TemporaryDirectory() as tmp,
            patch.object(heatmap_snapshots, "ROOT", Path(tmp).resolve()),
            patch.object(heatmap_snapshots, "SNAPSHOT_DIR", Path(tmp).resolve() / "snapshots"),
            patch.object(
                heatmap_snapshots.longbridge,
                "fetch_industry_heatmap",
                return_value=payload,
            ),
        ):
            snapshot = heatmap_snapshots.create_heatmap_snapshot(
                "US",
                trigger="manual",
                scheduled_at="2026-07-13T10:00:00-04:00",
            )
            image = Path(tmp).resolve() / "frame.png"
            image.write_bytes(b"png")
            heatmap_snapshots.attach_heatmap_image(
                snapshot["snapshotId"],
                str(image),
                width=3200,
                height=2692,
                size=3,
            )
            latest = heatmap_snapshots.latest_heatmap_snapshot("US", require_image=True)

        self.assertEqual(latest["snapshotId"], snapshot["snapshotId"])
        self.assertEqual(latest["image"]["width"], 3200)


if __name__ == "__main__":
    unittest.main()
