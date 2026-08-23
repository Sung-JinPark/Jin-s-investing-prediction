"""Exact V3 replay with a preregistered PIT V4 distributional calibrator."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.timeseries_v3 import pipeline as v3_pipeline
from ai_fc.timeseries_v3.stacking import StackedDistribution

from .contracts import MODEL_ID, MODEL_VERSION, canonical_hash, contract_hash, load_v4_contract
from .features import build_v4_feature_frame
from .source_store import verify_v4_source_store


STORE_RELATIVE = Path("data/timeseries_v4")
RUNS_RELATIVE = STORE_RELATIVE / "runs"
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers/backtests.jsonl"
LATEST_RELATIVE = STORE_RELATIVE / "multivariate_v4_latest.json"
V3_RUN_RELATIVE = Path("data/timeseries_v3/runs/tsv3-research-1f80a06bf6e991d887a5be40.json")


class V4PipelineError(RuntimeError):
    """The exact replay or V4 model-risk boundary failed."""


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: dict[str, Any], *, identity: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and json.loads(line).get(identity) == payload.get(identity):
                return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _model_code_hash(root: Path) -> str:
    digest = hashlib.sha256()
    folder = root / "src/ai_fc/timeseries_v4"
    for path in sorted(folder.rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def _origin_risk_scores(frame, origins: list[str], *, settings: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    pd = __import__("pandas")
    dates = pd.DatetimeIndex(frame.index)
    locations = {day.date().isoformat(): index for index, day in enumerate(dates)}
    history_sessions = int(settings["anomaly_history_sessions"])
    minimum = int(settings["anomaly_minimum_observations"])
    aggregation = float(settings["anomaly_aggregation_quantile"])
    features = [str(value) for value in settings["input_features"]]
    missing_columns = [name for name in features if name not in frame.columns]
    if missing_columns:
        raise V4PipelineError(f"preregistered feature columns missing: {missing_columns}")
    scores: dict[str, float] = {}
    used_by_origin: dict[str, int] = {}
    for day in origins:
        position = locations.get(day)
        if position is None:
            raise V4PipelineError(f"V3 origin not present in V4 frame: {day}")
        historical = frame.iloc[max(0, position - history_sessions):position]
        current = frame.iloc[position]
        percentiles: list[float] = []
        for column in features:
            values = historical[column].dropna()
            value = float(current[column])
            if len(values) < minimum or not np.isfinite(value):
                continue
            median = float(values.median())
            historical_distance = np.abs(values.to_numpy(dtype=float) - median)
            current_distance = abs(value - median)
            percentiles.append(float(np.mean(historical_distance <= current_distance)))
        scores[day] = float(np.quantile(percentiles, aggregation)) if percentiles else 0.0
        used_by_origin[day] = len(percentiles)
    return scores, {
        "features_preregistered": features,
        "feature_use_min": min(used_by_origin.values()),
        "feature_use_max": max(used_by_origin.values()),
        "risk_quantiles": {
            str(level): float(np.quantile(list(scores.values()), level))
            for level in (0.0, 0.5, 0.8, 0.95, 1.0)
        },
    }


def run_v4_backtest(root: Path, *, bootstrap_iterations: int = 1000, persist: bool = True) -> dict[str, Any]:
    """Replay V3 exactly, then calibrate its final samples using only PIT V4 state."""
    contract = load_v4_contract(root)
    frozen_contract_hash = contract_hash(root)
    lineage = verify_v4_source_store(root)
    if not lineage["ok"] or abs(float(lineage["receipt_linkage"]) - 1.0) > 1e-12:
        raise V4PipelineError("V4 source lineage is incomplete")
    predecessor = json.loads((root / V3_RUN_RELATIVE).read_text(encoding="utf-8"))
    origins = sorted({str(row["origin"]) for row in predecessor["scores"]})
    _, features, _, _, feature_metadata = build_v4_feature_frame(root)
    settings = contract["distributional_calibrator"]
    risk, risk_audit = _origin_risk_scores(features, origins, settings=settings)
    lower, upper = (float(value) for value in settings["anomaly_thresholds"])
    scales = [float(value) for value in settings["centered_scale_by_band"]]
    incomplete_scale = float(settings["incomplete_core_centered_scale"])
    core_start = str(feature_metadata["core_market_start"]["VIX9D"])
    event_counts = feature_metadata["event_history_counts"]
    event_minimum = int(settings["captured_event_minimum"])

    original_combine = StackedDistribution.combine
    original_v3_atomic_json = v3_pipeline._atomic_json
    state = {"index": 0, "bands": {"incomplete_core": 0, "low": 0, "medium": 0, "high": 0}}

    def calibrated_combine(self, forecasts, *args, **kwargs):
        final = original_combine(self, forecasts, *args, **kwargs)
        if state["index"] >= len(origins):
            raise V4PipelineError("V3 emitted more origins than its sealed score ledger")
        day = origins[state["index"]]
        state["index"] += 1
        if day < core_start:
            state["bands"]["incomplete_core"] += 1
            base = {horizon: forecasts["anchor"].horizon_samples[horizon].copy() for horizon in final}
            return {
                horizon: np.median(values) + incomplete_scale * (values - np.median(values))
                for horizon, values in base.items()
            }
        score = risk[day]
        if score < lower:
            scale, band = scales[0], "low"
        elif score < upper:
            scale, band = scales[1], "medium"
        else:
            scale, band = scales[2], "high"
        state["bands"][band] += 1
        return {
            horizon: np.median(values) + scale * (values - np.median(values))
            for horizon, values in final.items()
        }

    StackedDistribution.combine = calibrated_combine
    # V3's public backtest helper normally persists its own run and latest
    # pointer.  V4 needs the exact calculation, not those side effects.
    v3_pipeline._atomic_json = lambda _path, _payload: None
    try:
        replay = v3_pipeline.run_research_backtest(
            root, sample_count=int(predecessor["sample_count"]), bootstrap_iterations=bootstrap_iterations,
        )
    finally:
        StackedDistribution.combine = original_combine
        v3_pipeline._atomic_json = original_v3_atomic_json
    if state["index"] != len(origins):
        raise V4PipelineError(f"V3 replay origin count drifted: {state['index']} != {len(origins)}")

    scores = replay["scores"]
    core = {
        "schema_version": 4,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "status": "shadow_gate_pass" if replay["research_gate"]["pass"] else "shadow_gate_hold",
        "contract_hash": frozen_contract_hash,
        "model_code_hash": _model_code_hash(root),
        "predecessor_run_id": predecessor["run_id"],
        "predecessor_content_hash": predecessor["content_hash"],
        "data_cutoff": replay["data_cutoff"],
        "origin_count": replay["origin_count"],
        "score_count": replay["score_count"],
        "sample_count": replay["sample_count"],
        "research_gate": replay["research_gate"],
        "source_lineage": lineage,
        "feature_metadata": feature_metadata,
        "risk_audit": risk_audit,
        "calibration_band_counts": state["bands"],
        "captured_event_policy": {
            "minimum_history": event_minimum,
            "observed_history": event_counts,
            "coefficient_weight": 0.0,
            "reason": "captured event histories remain below the preregistered 60-event minimum",
        },
        "probability_space": "research_timeseries_v4_conditional",
        "probability_unit": "fraction",
        "combined_with_official_forecasts": False,
        "combined_with_scenario_v5_2": False,
        "official_write": False,
    }
    run_id = f"tsv4-research-{canonical_hash(core)[:24]}"
    payload = {**core, "run_id": run_id, "scores": scores}
    payload["content_hash"] = canonical_hash(payload)
    if persist:
        run_path = root / RUNS_RELATIVE / f"{run_id}.json"
        _atomic_json(run_path, payload)
        _append_jsonl(root / LEDGER_RELATIVE, {key: value for key, value in payload.items() if key != "scores"}, identity="run_id")
        _atomic_json(root / LATEST_RELATIVE, {
            "run_id": run_id, "content_hash": payload["content_hash"],
            "status": payload["status"], "run_path": run_path.relative_to(root).as_posix(),
        })
    return payload


def verify_v4_run(root: Path) -> dict[str, Any]:
    """Verify the persisted V4 pointer, hashes, lineage and fail-closed state."""
    errors: list[str] = []
    pointer_path = root / LATEST_RELATIVE
    if not pointer_path.is_file():
        return {"ok": False, "errors": ["V4 latest pointer missing"]}
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    run_path = root / str(pointer.get("run_path", ""))
    if not run_path.is_file():
        return {"ok": False, "errors": ["V4 pointed run missing"]}
    run = json.loads(run_path.read_text(encoding="utf-8"))
    expected_content = canonical_hash({key: value for key, value in run.items() if key != "content_hash"})
    if run.get("content_hash") != expected_content or pointer.get("content_hash") != expected_content:
        errors.append("V4 content hash mismatch")
    if run.get("contract_hash") != contract_hash(root):
        errors.append("V4 contract hash mismatch")
    if run.get("model_code_hash") != _model_code_hash(root):
        errors.append("V4 model code hash mismatch")
    predecessor = json.loads((root / V3_RUN_RELATIVE).read_text(encoding="utf-8"))
    if run.get("predecessor_run_id") != predecessor.get("run_id") or run.get("predecessor_content_hash") != predecessor.get("content_hash"):
        errors.append("V3 predecessor identity mismatch")
    lineage = verify_v4_source_store(root)
    if not lineage["ok"] or abs(float(lineage["receipt_linkage"]) - 1.0) > 1e-12:
        errors.append("V4 source lineage failed")
    if run.get("probability_unit") != "fraction":
        errors.append("V4 probability unit drifted")
    if run.get("combined_with_official_forecasts") is not False or run.get("combined_with_scenario_v5_2") is not False:
        errors.append("V4 probability spaces were combined")
    gate_pass = bool(run.get("research_gate", {}).get("pass"))
    expected_status = "shadow_gate_pass" if gate_pass else "shadow_gate_hold"
    if run.get("status") != expected_status or pointer.get("status") != expected_status:
        errors.append("V4 status does not match its Gate")
    if run.get("official_write") is not False:
        errors.append("V4 official-write guard drifted")
    return {
        "ok": not errors,
        "errors": errors,
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "content_hash": run.get("content_hash"),
        "gate_pass": gate_pass,
        "source_lineage": lineage,
        "customer_numbers_visible": gate_pass,
    }
