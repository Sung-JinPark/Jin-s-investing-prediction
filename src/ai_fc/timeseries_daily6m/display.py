"""Fail-closed read projection for the independent six-month daily forecast."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import contracts as C
from . import features as F
from .pipeline import Daily6mPipelineError, hold_payload, load_run, validate_run


def project_run(root: Path, run: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    validate_run(run)
    current = F.aware_time(now)
    frame = F.read_native_frame(root, as_of=current)
    freshness = F.source_freshness(frame, current)
    reasons = ["required source " + row["group"] + " " + row["status"] for row in freshness if row["status"] != "fresh"]
    age = F.origin_age(run["anchor_date"], current)
    if age >= 10:
        reasons.append("forecast origin age reaches 10 completed sessions")
    if reasons:
        stable_freshness = [{key: value for key, value in row.items() if key != "age_hours"} for row in freshness]
        return hold_payload(reasons, as_of=run["as_of"], evidence={"source_freshness": stable_freshness, "origin_age_sessions": age})
    actual = frame[(frame["series_id"] == "NASDAQCOM") & (frame["day"] > run["anchor_date"]) & frame["day"].isin(run["dates"])].sort_values("day")
    lineage = run.get("source_lineage") or {}
    body = {key: value for key, value in run.items() if key not in {"source_lineage", "joint_path_artifact", "content_hash"}}
    body.update({"content_hash": run["content_hash"], "source_lineage": {**{key: value for key, value in lineage.items() if key not in {"market_rows", "factor_rows", "initial_missing_daily_inputs"}}, "initial_missing_daily_inputs_count": len(lineage.get("initial_missing_daily_inputs") or [])}, "gate": {"pass": True, "reasons": [], "origin_age_sessions": age}, "realized": {"dates": actual["day"].tolist(), "index": [float(value) for value in actual["value"]]}})
    # Freshness ages are used for the gate but not reserialized: identical
    # source data and gate state produce the same sidecar identity.
    body["projection_hash"] = C.canonical_hash(body)
    return body


def load_projection(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    path = root / C.LATEST_RELATIVE
    if not path.is_file():
        return hold_payload(["independent daily6m forecast is not published"], status="absent")
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        if pointer.get("content_hash") != C.canonical_hash({key: value for key, value in pointer.items() if key != "content_hash"}):
            raise Daily6mPipelineError("latest pointer content hash mismatch")
        if pointer.get("numbers_visible") is not True:
            if pointer.get("records") or pointer.get("dates") or pointer.get("sample_paths"):
                raise Daily6mPipelineError("HOLD pointer contains numerical forecast arrays")
            return pointer
        row = {"forecast_id": pointer["run_id"], "run_path": pointer["run_path"], "run_content_hash": pointer["run_content_hash"]}
        return project_run(root, load_run(root, row), now=now)
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, ImportError, Daily6mPipelineError, C.Daily6mContractError) as exc:
        return hold_payload(["daily6m artifact unavailable: " + str(exc)])
