from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from providers import longbridge


ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = ROOT / "tmp" / "heatmap-snapshots"
VALID_MARKETS = {"CN", "HK", "US"}
MARKET_TIMEZONES = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}
_LOCKS_GUARD = threading.Lock()
_LOCKS: Dict[str, threading.Lock] = {}
FRESHNESS_ATTEMPTS = 6
FRESHNESS_RETRY_SECONDS = 10
ZERO_EPSILON = 1e-9


class HeatmapSnapshotError(RuntimeError):
    pass


def _market(value: str) -> str:
    normalized = value.upper()
    if normalized not in VALID_MARKETS:
        raise HeatmapSnapshotError(f"unsupported market: {value}")
    return normalized


def _lock(market: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(market, threading.Lock())


def _atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _snapshot_files(market: str) -> list[Path]:
    market_dir = SNAPSHOT_DIR / market
    return sorted(market_dir.glob("????-??-??/*.json"), reverse=True) if market_dir.exists() else []


def _read(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _heatmap_fingerprint(payload: Dict[str, Any]) -> str:
    industries = payload.get("industries") or []
    rows = [
        {
            "code": str(item.get("code") or item.get("name") or ""),
            "changePercent": float(item.get("changePercent") or 0),
        }
        for item in industries
    ]
    return json.dumps(sorted(rows, key=lambda item: item["code"]), ensure_ascii=False, separators=(",", ":"))


def _all_zero(payload: Dict[str, Any]) -> bool:
    industries = payload.get("industries") or []
    return bool(industries) and all(
        abs(float(item.get("changePercent") or 0)) <= ZERO_EPSILON
        for item in industries
    )


def _previous_scheduled_snapshot(market: str, scheduled_at: str) -> Dict[str, Any]:
    current_time = datetime.fromisoformat(scheduled_at)
    candidates = []
    for path in _snapshot_files(market):
        payload = _read(path)
        if payload.get("trigger") not in {"scheduled", "session-close"}:
            continue
        timestamp = str(payload.get("scheduledAt") or payload.get("capturedAt") or "")
        try:
            if datetime.fromisoformat(timestamp) < current_time:
                candidates.append(payload)
        except ValueError:
            continue
    return max(
        candidates,
        key=lambda item: datetime.fromisoformat(str(item.get("scheduledAt") or item.get("capturedAt"))),
        default={},
    )


def _freshness_problem(
    payload: Dict[str, Any],
    previous: Dict[str, Any],
) -> str:
    if _all_zero(payload):
        return "all industry changes are zero"
    if previous and _heatmap_fingerprint(payload) == str(previous.get("dataFingerprint") or _heatmap_fingerprint(previous)):
        return f"industry changes match previous snapshot {previous.get('snapshotId')}"
    return ""


def create_heatmap_snapshot(
    market: str,
    *,
    trigger: str = "scheduled",
    scheduled_at: str = "",
) -> Dict[str, Any]:
    normalized = _market(market)
    with _lock(normalized):
        if scheduled_at:
            existing = latest_heatmap_snapshot(normalized, at_or_before=scheduled_at)
            if existing and existing.get("scheduledAt") == scheduled_at:
                return existing

        now = datetime.now().astimezone()
        effective_at = scheduled_at or now.isoformat(timespec="seconds")
        validate_freshness = trigger in {"scheduled", "session-close"}
        previous = (
            _previous_scheduled_snapshot(normalized, effective_at)
            if validate_freshness
            else {}
        )
        payload: Dict[str, Any] = {}
        freshness_problem = ""
        for attempt in range(1, FRESHNESS_ATTEMPTS + 1):
            payload = longbridge.fetch_industry_heatmap(
                normalized,
                include_stocks=False,
                force_refresh=attempt > 1,
            )
            groups = payload.get("groups") or []
            industries = payload.get("industries") or []
            if not groups or not industries:
                freshness_problem = "heatmap data is empty"
            elif validate_freshness:
                freshness_problem = _freshness_problem(payload, previous)
            else:
                freshness_problem = ""
            if not freshness_problem:
                break
            if attempt < FRESHNESS_ATTEMPTS:
                time.sleep(FRESHNESS_RETRY_SECONDS)
        if freshness_problem:
            raise HeatmapSnapshotError(
                f"{normalized} heatmap data did not refresh after "
                f"{FRESHNESS_ATTEMPTS} attempts: {freshness_problem}"
            )

        groups = payload.get("groups") or []
        industries = payload.get("industries") or []
        date_key = effective_at[:10]
        stamp = now.strftime("%Y%m%d%H%M%S")
        snapshot_id = f"heatmap-{normalized.lower()}-{stamp}-{uuid4().hex[:8]}"
        snapshot = {
            "schemaVersion": 2,
            "snapshotId": snapshot_id,
            "market": normalized,
            "marketTimezone": MARKET_TIMEZONES[normalized],
            "trigger": trigger,
            "scheduledAt": effective_at,
            "capturedAt": now.isoformat(timespec="seconds"),
            "updatedAt": payload.get("updatedAt") or now.isoformat(timespec="seconds"),
            "source": payload.get("source") or "Longbridge",
            "dataFingerprint": _heatmap_fingerprint(payload),
            "groups": groups,
            "industries": industries,
            "turnoverCoverage": payload.get("turnoverCoverage") or {},
            "image": None,
        }
        _atomic_json(SNAPSHOT_DIR / normalized / date_key / f"{snapshot_id}.json", snapshot)
        return snapshot


def get_heatmap_snapshot(snapshot_id: str) -> Dict[str, Any]:
    if not snapshot_id or "/" in snapshot_id or "\\" in snapshot_id:
        return {}
    for market in VALID_MARKETS:
        for path in _snapshot_files(market):
            if path.stem == snapshot_id:
                return _read(path)
    return {}


def latest_heatmap_snapshot(
    market: str,
    *,
    at_or_before: str = "",
    require_image: bool = False,
    scheduled_only: bool = False,
) -> Dict[str, Any]:
    normalized = _market(market)
    before_time = datetime.fromisoformat(at_or_before) if at_or_before else None
    candidates = []
    for path in _snapshot_files(normalized):
        payload = _read(path)
        if not payload:
            continue
        timestamp = str(payload.get("scheduledAt") or payload.get("capturedAt") or "")
        if before_time:
            try:
                if datetime.fromisoformat(timestamp) > before_time:
                    continue
            except ValueError:
                continue
        if require_image and not (payload.get("image") or {}).get("path"):
            continue
        if scheduled_only and payload.get("trigger") not in {"scheduled", "session-close"}:
            continue
        candidates.append(payload)
    return max(
        candidates,
        key=lambda item: datetime.fromisoformat(
            str(item.get("scheduledAt") or item.get("capturedAt"))
        ),
        default={},
    )


def attach_heatmap_image(
    snapshot_id: str,
    image_path: str,
    *,
    width: int,
    height: int,
    size: int,
) -> Dict[str, Any]:
    snapshot = get_heatmap_snapshot(snapshot_id)
    if not snapshot:
        raise HeatmapSnapshotError("heatmap snapshot not found")
    path = Path(image_path).resolve()
    try:
        relative_path = path.relative_to(ROOT)
    except ValueError as exc:
        raise HeatmapSnapshotError("image path is outside project") from exc
    if not path.exists():
        raise HeatmapSnapshotError("heatmap image not found")
    snapshot["image"] = {
        "path": str(path),
        "relativePath": str(relative_path),
        "width": width,
        "height": height,
        "size": size,
        "readyAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    date_key = str(snapshot.get("scheduledAt") or snapshot.get("capturedAt"))[:10]
    _atomic_json(
        SNAPSHOT_DIR / snapshot["market"] / date_key / f"{snapshot_id}.json",
        snapshot,
    )
    return snapshot
