#!/usr/bin/env python3
"""Benchmark the AI assistant with provider and local-query stage timings.

This script calls the same service functions as /api/assistant/chat while wrapping
the provider and local query boundaries. It never prints API keys or full prompts.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "data_service"
for entry in (str(BACKEND), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from services import ai_assistant  # noqa: E402
from services import reports  # noqa: E402


DEFAULT_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "stock": {"message": "腾讯控股属于哪个一级和二级行业？"},
    "sector": {"message": "给我 7 月 15 日酿酒业的变化"},
    "weekly": {"message": "给我最新一份周报"},
    "quick-midday": {
        "message": "请生成午报",
        "quickAction": True,
        "session": "midday",
    },
}


def _provider_stage(messages: List[Dict[str, str]]) -> str:
    contents = [str(item.get("content") or "") for item in messages]
    joined = "\n".join(contents)
    if "ResultEnvelope：" in joined:
        return "provider_answer"
    if "校验失败" in joined:
        return "provider_planner_repair"
    if "市场报告助手" in joined:
        return "provider_report"
    return "provider_planner"


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _summary(values: List[float]) -> Dict[str, float]:
    return {
        "minMs": round(min(values), 1),
        "meanMs": round(statistics.fmean(values), 1),
        "p50Ms": round(_percentile(values, 0.50), 1),
        "p95Ms": round(_percentile(values, 0.95), 1),
        "maxMs": round(max(values), 1),
    }


def _latest_cached_report_date(session: str) -> str:
    try:
        cache = json.loads(reports.CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return next(
        (
            date_key
            for date_key in sorted(cache, reverse=True)
            if isinstance(cache.get(date_key), dict)
            and isinstance(cache[date_key].get(session), dict)
        ),
        "",
    )


def profile_once(payload: Dict[str, Any], model: str = "") -> Dict[str, Any]:
    provider_calls: List[Dict[str, Any]] = []
    local_calls: List[Dict[str, Any]] = []
    original_provider_chat = ai_assistant._provider_chat
    original_execute_query = ai_assistant.execute_market_query

    def timed_provider_chat(
        config: Dict[str, str],
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.1,
    ) -> str:
        started = time.perf_counter()
        stage = _provider_stage(messages)
        try:
            content = original_provider_chat(
                config,
                messages,
                temperature=temperature,
            )
            return content
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            provider_calls.append({
                "stage": stage,
                "elapsedMs": round(elapsed, 1),
                "inputChars": sum(len(str(item.get("content") or "")) for item in messages),
                "outputChars": len(content) if "content" in locals() else 0,
            })

    def timed_execute_query(query: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        try:
            return original_execute_query(query)
        finally:
            local_calls.append({
                "stage": "local_query",
                "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
                "domain": str((query.get("intent") or {}).get("domain") or ""),
            })

    payload = dict(payload)
    if model:
        payload["model"] = model
    started = time.perf_counter()
    with (
        patch.object(ai_assistant, "_provider_chat", side_effect=timed_provider_chat),
        patch.object(ai_assistant, "execute_market_query", side_effect=timed_execute_query),
    ):
        response = ai_assistant.generate_assistant_response(
            payload,
            "http://localhost:3005",
        )
    total_ms = (time.perf_counter() - started) * 1000
    measured_ms = sum(item["elapsedMs"] for item in [*provider_calls, *local_calls])
    return {
        "totalMs": round(total_ms, 1),
        "overheadMs": round(max(0.0, total_ms - measured_ms), 1),
        "providerCalls": provider_calls,
        "localCalls": local_calls,
        "resultType": str(
            (response.get("result") or {}).get("resultType")
            or response.get("reportType")
            or ""
        ),
        "model": str(response.get("model") or ""),
    }


def aggregate_runs(payload: Dict[str, Any], runs: int, model: str = "") -> Dict[str, Any]:
    samples = []
    for index in range(runs):
        sample = profile_once(payload, model)
        sample["run"] = index + 1
        samples.append(sample)

    stages: Dict[str, List[float]] = {}
    for sample in samples:
        stages.setdefault("total", []).append(float(sample["totalMs"]))
        stages.setdefault("overhead", []).append(float(sample["overheadMs"]))
        for item in [*sample["providerCalls"], *sample["localCalls"]]:
            stages.setdefault(str(item["stage"]), []).append(float(item["elapsedMs"]))
    return {
        "message": str(payload.get("message") or ""),
        "quickAction": bool(payload.get("quickAction")),
        "runs": runs,
        "model": samples[-1]["model"],
        "resultType": samples[-1]["resultType"],
        "summary": {stage: _summary(values) for stage, values in stages.items()},
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile AI assistant latency by stage")
    parser.add_argument(
        "--scenario",
        choices=sorted(DEFAULT_SCENARIOS),
        default="stock",
        help="built-in benchmark query",
    )
    parser.add_argument("--message", help="override the built-in query")
    parser.add_argument("--model", default="", help="override the configured model")
    parser.add_argument("--runs", type=int, default=1, help="number of real provider runs")
    parser.add_argument("--output", type=Path, help="optional JSON result path")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    payload = dict(DEFAULT_SCENARIOS[args.scenario])
    if payload.get("quickAction") and not args.message:
        target_date = _latest_cached_report_date(str(payload.get("session") or ""))
        if target_date:
            payload["message"] = f"请生成 {target_date} 午报"
    if args.message:
        payload["message"] = args.message
    result = aggregate_runs(payload, args.runs, args.model)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
