"""Fail-closed read projection for the independent six-month daily forecast."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from . import contracts as C
from . import features as F
from .pipeline import Daily6mPipelineError, hold_payload, load_run, validate_run

# 전진 성적(표시 전용) 기준값 — 무정보 Brier 0.25 = p=0.5 고정 예측의 점수, 공칭 구간 80%.
NO_INFORMATION_BRIER = 0.25
NOMINAL_INTERVAL_COVERAGE = 0.8


def forward_record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """해소 원장 행을 전진 성적으로 요약한다 — 표시 전용 순수 함수, 채점·판정이 아니다.

    누적 Brier(무정보 0.25 병기)·80% 구간 적중 n/N·발행 수·해소일 수만 센다. 같은 발행의
    일별 행은 독립 표본이 아니므로 발행 수와 해소일 수를 함께 싣는다. 정정(supersedes)된
    해소 행은 최신 개정만 센다 — 원장 자체는 그대로다. 행이 없으면 숫자 대신 None(화면은
    '—')이고, predictive_validation 은 어떤 경우에도 not_established 로 유지한다.
    """
    superseded = {str(row.get("supersedes")) for row in rows if row.get("supersedes")}
    active = []
    for row in rows:
        if str(row.get("resolution_id")) in superseded:
            continue
        brier = row.get("brier")
        if isinstance(brier, bool) or not isinstance(brier, (int, float)) or not math.isfinite(float(brier)):
            continue
        active.append(row)
    count = len(active)
    dates = sorted({str(row.get("date")) for row in active if row.get("date")})
    forecasts = {str(row.get("forecast_id")) for row in active if row.get("forecast_id")}
    return {
        "schema_version": 1,
        "model_id": C.MODEL_ID,
        "ledger": C.RESOLUTION_LEDGER.as_posix(),
        "display_only": True,
        "probability_unit": "fraction",
        "resolved_rows": count,
        "forecasts": len(forecasts),
        "resolved_dates": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "mean_brier": round(sum(float(row["brier"]) for row in active) / count, 4) if count else None,
        "no_information_brier": NO_INFORMATION_BRIER,
        "covered_p10_p90_rows": sum(1 for row in active if row.get("inside_p10_p90") is True) if count else None,
        "nominal_interval_coverage": NOMINAL_INTERVAL_COVERAGE,
        "independent_rows": False,
        "predictive_validation": "not_established",
    }


def load_forward_record(root: Path) -> dict[str, Any]:
    """원장이 없거나 깨졌으면 행 0 으로 닫는다 — 빌드를 세우지 않고 숫자를 지어내지 않는다."""
    path = root / C.RESOLUTION_LEDGER
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ] if path.is_file() else []
    except (OSError, ValueError) as exc:
        record = forward_record([])
        record["ledger_error"] = str(exc)
        return record
    return forward_record(rows)


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
        held = hold_payload(reasons, as_of=run["as_of"], evidence={"source_freshness": stable_freshness, "origin_age_sessions": age})
        # Preserve issuance identity on HOLD so the UI does not describe this
        # original issue time as a new preflight check or an unpublished run.
        body = {key: value for key, value in held.items() if key != "content_hash"}
        body.update({"run_id": run["run_id"], "anchor_date": run["anchor_date"]})
        return {**body, "content_hash": C.canonical_hash(body)}
    actual = frame[(frame["series_id"] == "NASDAQCOM") & (frame["day"] > run["anchor_date"]) & frame["day"].isin(run["dates"])].sort_values("day")
    lineage = run.get("source_lineage") or {}
    body = {key: value for key, value in run.items() if key not in {"source_lineage", "joint_path_artifact", "content_hash"}}
    body["operational_source_freshness"] = [
        {key: value for key, value in row.items() if key != "age_hours"} for row in freshness]
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
            # A stored operational source HOLD must be reevaluated at read time:
            # it is not a new forecast and cannot select a superseded issue.
            reasons = pointer.get("gate", {}).get("reasons") or []
            if (pointer.get("run_id") and reasons
                    and all(str(reason).startswith("required source ") for reason in reasons)):
                from .pipeline import _active, read_chain
                active = _active(read_chain(root, C.FORECAST_LEDGER))
                if active and active[-1]["forecast_id"] == pointer["run_id"]:
                    return project_run(root, load_run(root, active[-1]), now=now)
            return pointer
        row = {"forecast_id": pointer["run_id"], "run_path": pointer["run_path"], "run_content_hash": pointer["run_content_hash"]}
        return project_run(root, load_run(root, row), now=now)
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, ImportError, Daily6mPipelineError, C.Daily6mContractError) as exc:
        return hold_payload(["daily6m artifact unavailable: " + str(exc)])
