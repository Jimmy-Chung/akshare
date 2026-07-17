from pathlib import Path
from tempfile import TemporaryDirectory
import json
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

    def test_history_and_dates_are_read_directly_from_snapshot_json(self):
        with TemporaryDirectory() as tmp:
            snapshot_dir = Path(tmp).resolve() / "snapshots"
            date_dir = snapshot_dir / "US" / "2026-07-13"
            date_dir.mkdir(parents=True)
            for snapshot_id, scheduled_at, trigger, change in (
                ("first", "2026-07-13T09:30:00-04:00", "scheduled", 0.2),
                ("second", "2026-07-13T10:00:00-04:00", "scheduled", 0.4),
                ("manual", "2026-07-13T10:15:00-04:00", "manual", 0.5),
                ("zero", "2026-07-13T10:30:00-04:00", "scheduled", 0),
            ):
                (date_dir / f"{snapshot_id}.json").write_text(
                    json.dumps({
                        "snapshotId": snapshot_id,
                        "market": "US",
                        "trigger": trigger,
                        "scheduledAt": scheduled_at,
                        "capturedAt": scheduled_at,
                        "industries": [{"code": "industry", "changePercent": change}],
                    }),
                    encoding="utf-8",
                )

            with patch.object(heatmap_snapshots, "SNAPSHOT_DIR", snapshot_dir):
                dates = heatmap_snapshots.list_heatmap_snapshot_dates("US")
                history = heatmap_snapshots.list_heatmap_snapshot_history("US", "2026-07-13")

        self.assertEqual(dates["latestDate"], "2026-07-13")
        self.assertEqual(dates["dates"], [{"date": "2026-07-13", "snapshotCount": 2}])
        self.assertEqual(history["snapshotCount"], 2)
        self.assertEqual([item["snapshotId"] for item in history["snapshots"]], ["first", "second"])
        self.assertEqual([item["label"] for item in history["snapshots"]], ["09:30", "10:00"])

    def test_invalid_history_date_is_rejected(self):
        with self.assertRaises(heatmap_snapshots.HeatmapSnapshotError):
            heatmap_snapshots.list_heatmap_snapshot_history("CN", "../../etc")


if __name__ == "__main__":
    unittest.main()
