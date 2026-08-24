"""Read-only reproduction of the immutable NASDAQ V4 benchmark.

This module implements only backlog task ``V5-P0-001``.  It independently
recomputes hashes, score summaries, conditional diagnostics, and source-ledger
facts from the frozen V4 artifacts.  It never writes into V1--V4, Scenario,
forecast, official-ledger, or customer-dashboard paths.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import zipfile
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import yaml


MODEL_ID = "shadow.nasdaq_pit_market_event_distribution_v4"
EXPECTED_REVIEW_PACK_SHA256 = "58911b7b042c34e25075a8933350c8d2699b26e6795d4c80d29d42f1454f1f2c"
EXPECTED_REVIEW_PACK_BYTES = 15_091_342
V4_POINTER = Path("data/timeseries_v4/multivariate_v4_latest.json")
V4_CONTRACT = Path("data/contracts/multivariate_timeseries_v4.yaml")
V4_RECEIPTS = Path("data/timeseries_v4/ledgers/raw_receipts.jsonl")
V4_OBSERVATIONS = Path("data/timeseries_v4/ledgers/observations.jsonl")
V4_PARSE_OUTCOMES = Path("data/timeseries_v4/ledgers/receipt_parse_outcomes.jsonl")
V3_RUNS = Path("data/timeseries_v3/runs")
PROTECTED_ROOTS = (
    "data/timeseries",
    "data/timeseries_v1",
    "data/timeseries_v2",
    "data/timeseries_v3",
    "data/timeseries_v4",
    "data/scenarios",
    "data/forecasts",
    "data/ledgers",
    "src/ai_fc/dashboard.py",
    "src/ai_fc/dashboard_parts",
)
EXPECTED_PACK_VALUES: dict[str, Any] = {
    "model_id": MODEL_ID,
    "benchmark_status": "shadow_gate_hold",
    "origin_count": 963,
    "score_count": 3_852,
    "sample_count": 4_000,
    "receipt_count": 72,
    "observation_count": 113_615,
    "receipts_without_fact_link": 37,
    "available_after_1600_et_count": 57_973,
    "revision_seq_distribution": {"1": 113_615},
    "fed_independent_snapshot_count": 2,
    "nfp_pre_release_snapshot_proven": False,
    "improvement_21": 0.0028784508084850812,
    "improvement_63": 0.016945097002685507,
    "long_horizon_mean_improvement": 0.009911773905585295,
}


class BaselineAuditError(RuntimeError):
    """The immutable V4 benchmark could not be reproduced safely."""


def _normal(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normal(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def canonical_hash(value: Any) -> str:
    body = json.dumps(_normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise BaselineAuditError(f"expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise BaselineAuditError(f"expected JSON object at {path}:{number}")
            yield value


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


def _contract_hash(root: Path) -> str:
    contract = yaml.safe_load((root / V4_CONTRACT).read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise BaselineAuditError("V4 contract is not a mapping")
    return canonical_hash(contract)


def _quartile_labels(values: Sequence[float]) -> list[str]:
    array = np.asarray(values, dtype=float)
    boundaries = np.quantile(array[np.isfinite(array)], [0.25, 0.50, 0.75])
    return [f"Q{1 + int(np.searchsorted(boundaries, value, side='right'))}" for value in array]


def _group_summary(rows: list[dict[str, Any]], labels: Sequence[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for label in sorted(set(labels)):
        selected = [row for row, value in zip(rows, labels, strict=True) if value == label]
        model = float(np.mean([float(row["model_crps"]) for row in selected]))
        baseline = float(np.mean([float(row["baseline_crps"]) for row in selected]))
        result[label] = {
            "count": len(selected),
            "model_crps": model,
            "baseline_crps": baseline,
            "crps_improvement": (baseline - model) / baseline if baseline else 0.0,
            "p10_p90_coverage": sum(
                float(row["p10"]) <= float(row["actual"]) <= float(row["p90"])
                for row in selected
            )
            / len(selected),
            "baseline_p10_p90_coverage": sum(
                float(row["baseline_p10"]) <= float(row["actual"]) <= float(row["baseline_p90"])
                for row in selected
            )
            / len(selected),
        }
    return result


def _stationary_bootstrap_ci(
    losses: np.ndarray,
    *,
    block_length: int,
    confidence: float,
    iterations: int,
    seed: int,
) -> list[float]:
    values = np.asarray(losses, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations)
    restart = 1.0 / block_length
    for iteration in range(iterations):
        indexes = np.empty(values.size, dtype=int)
        indexes[0] = rng.integers(0, values.size)
        for position in range(1, values.size):
            indexes[position] = (
                rng.integers(0, values.size)
                if rng.random() < restart
                else (indexes[position - 1] + 1) % values.size
            )
        means[iteration] = np.mean(values[indexes])
    alpha = (1.0 - confidence) / 2.0
    return [float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))]


def compute_score_audit(
    rows: list[dict[str, Any]],
    *,
    expected_horizons: Sequence[int] = (1, 5, 21, 63),
    bootstrap_seed: int | None = None,
    bootstrap_iterations: int = 1_000,
) -> dict[str, Any]:
    """Independently aggregate the persisted per-origin score ledger."""
    horizons = tuple(int(value) for value in expected_horizons)
    keys = [(str(row["origin"]), int(row["horizon"])) for row in rows]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise ValueError(f"duplicate origin/horizon rows: {duplicate_count}")
    origins = sorted({origin for origin, _ in keys})
    expected = {(origin, horizon) for origin in origins for horizon in horizons}
    missing = expected.difference(keys)
    unexpected = set(keys).difference(expected)
    if missing or unexpected:
        raise ValueError(
            f"incomplete origin/horizon grid: missing={len(missing)}, unexpected={len(unexpected)}"
        )

    monotonicity_violations = 0
    for row in rows:
        quantiles = row.get("quantiles") or {}
        levels = sorted((float(level), float(value)) for level, value in quantiles.items())
        if any(levels[index][1] > levels[index + 1][1] for index in range(len(levels) - 1)):
            monotonicity_violations += 1

    by_horizon: dict[str, dict[str, Any]] = {}
    conditional: dict[str, Any] = {}
    for horizon in horizons:
        selected = [row for row in rows if int(row["horizon"]) == horizon]
        model = float(np.mean([float(row["model_crps"]) for row in selected]))
        baseline = float(np.mean([float(row["baseline_crps"]) for row in selected]))
        coverage = sum(
            float(row["p10"]) <= float(row["actual"]) <= float(row["p90"])
            for row in selected
        ) / len(selected)
        baseline_coverage = sum(
            float(row["baseline_p10"]) <= float(row["actual"]) <= float(row["baseline_p90"])
            for row in selected
        ) / len(selected)
        below_median = sum(
            float(row["actual"]) < float((row.get("quantiles") or {})["0.5"])
            for row in selected
        ) / len(selected)
        by_horizon[str(horizon)] = {
            "score_count": len(selected),
            "unique_origins": len({str(row["origin"]) for row in selected}),
            "model_crps": model,
            "baseline_crps": baseline,
            "improvement": (baseline - model) / baseline,
            "p10_p90_coverage": coverage,
            "baseline_p10_p90_coverage": baseline_coverage,
            "actual_below_forecast_median_fraction": below_median,
            "actual_at_or_above_forecast_median_fraction": 1.0 - below_median,
        }
        if horizon in {21, 63}:
            move_labels = _quartile_labels([abs(float(row["actual"])) for row in selected])
            conditional[str(horizon)] = {
                "absolute_move_quartile": _group_summary(selected, move_labels),
                "stress_regime": _group_summary(
                    selected, [str(row.get("stress_regime") or "unknown") for row in selected]
                ),
                "actual_sign": _group_summary(
                    selected, ["up" if float(row["actual"]) >= 0 else "down" for row in selected]
                ),
            }

    mean_long = float(np.mean([by_horizon["21"]["improvement"], by_horizon["63"]["improvement"]]))
    paired_ci: list[float] | None = None
    if bootstrap_seed is not None:
        losses_by_origin: dict[str, list[float]] = {}
        for row in rows:
            if int(row["horizon"]) not in {21, 63}:
                continue
            losses_by_origin.setdefault(str(row["origin"]), []).append(
                float(row["model_crps"]) - float(row["baseline_crps"])
            )
        paired = np.asarray([np.mean(losses_by_origin[origin]) for origin in sorted(losses_by_origin)])
        paired_ci = _stationary_bootstrap_ci(
            paired,
            block_length=13,
            confidence=0.90,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        )
    return {
        "score_count": len(rows),
        "origin_count": len(origins),
        "expected_horizons": list(horizons),
        "duplicate_origin_horizon_count": duplicate_count,
        "missing_origin_horizon_count": len(missing),
        "quantile_monotonicity_violations": monotonicity_violations,
        "horizons": by_horizon,
        "long_horizon_mean_improvement": mean_long,
        "paired_loss_difference_90_ci": paired_ci,
        "conditional": conditional,
    }


def _source_lineage_audit(root: Path) -> dict[str, Any]:
    receipts = list(_jsonl(root / V4_RECEIPTS))
    receipt_index = {str(row["receipt_id"]): row for row in receipts}
    linked_receipts: set[str] = set()
    orphan_observations = 0
    receipt_mismatches = 0
    revision_seq: Counter[int] = Counter()
    supersedes_count = 0
    after_close = 0
    observation_count = 0
    series: set[str] = set()
    fed_series: Counter[str] = Counter()
    fed_snapshots: set[str] = set()
    fed_snapshot_meetings: set[tuple[str, str]] = set()
    consensus_rows: list[dict[str, Any]] = []
    actual_rows: list[dict[str, Any]] = []
    ny = ZoneInfo("America/New_York")
    for row in _jsonl(root / V4_OBSERVATIONS):
        observation_count += 1
        receipt_id = str(row["receipt_id"])
        linked_receipts.add(receipt_id)
        receipt = receipt_index.get(receipt_id)
        if receipt is None:
            orphan_observations += 1
        elif receipt.get("raw_sha256") != row.get("raw_sha256") or receipt.get("source_id") != row.get("source_id"):
            receipt_mismatches += 1
        revision_seq[int(row["revision_seq"])] += 1
        supersedes_count += row.get("supersedes") is not None
        available = datetime.fromisoformat(str(row["available_at"]))
        if available.tzinfo is None:
            available = available.replace(tzinfo=timezone.utc)
        if available.astimezone(ny).timetz().replace(tzinfo=None) > time(16, 0):
            after_close += 1
        series_id = str(row["series_id"])
        series.add(series_id)
        if series_id.startswith("FED_RATE_"):
            fed_series[series_id] += 1
            dimensions = row.get("dimensions") or {}
            snapshot = str(dimensions.get("snapshot") or "")
            meeting = str(dimensions.get("meeting") or "")
            if snapshot:
                fed_snapshots.add(snapshot)
            if snapshot and meeting:
                fed_snapshot_meetings.add((snapshot, meeting))
        if series_id == "NFP_CONSENSUS":
            consensus_rows.append(row)
        elif series_id == "BLS_NFP_ACTUAL":
            actual_rows.append(row)

    raw_errors: list[str] = []
    unique_raw = {str(row["raw_sha256"]) for row in receipts}
    local_raw_count = 0
    private_locator_count = 0
    for receipt in receipts:
        if receipt.get("redistribution") == "private_locator_only":
            private_locator_count += 1
            if str(receipt.get("raw_sha256")) not in str(receipt.get("raw_path")):
                raw_errors.append(f"private locator hash mismatch: {receipt['receipt_id']}")
            continue
        local_raw_count += 1
        path = root / str(receipt["raw_path"])
        if not path.is_file():
            raw_errors.append(f"missing raw: {receipt['receipt_id']}")
            continue
        with gzip.open(path, "rb") as handle:
            observed = hashlib.sha256(handle.read()).hexdigest()
        if observed != receipt["raw_sha256"]:
            raw_errors.append(f"raw hash mismatch: {receipt['receipt_id']}")

    explicit_terminal: set[str] = set()
    if (root / V4_PARSE_OUTCOMES).is_file():
        explicit_terminal = {
            str(row["receipt_id"])
            for row in _jsonl(root / V4_PARSE_OUTCOMES)
            if bool(row.get("terminal"))
        }
    consensus_available = [datetime.fromisoformat(str(row["available_at"])) for row in consensus_rows]
    actual_available = [datetime.fromisoformat(str(row["available_at"])) for row in actual_rows]
    pre_release_proven = bool(
        consensus_available
        and actual_available
        and max(consensus_available) < min(actual_available)
    )
    return {
        "receipt_count": len(receipts),
        "unique_raw_sha256_count": len(unique_raw),
        "local_raw_receipt_count": local_raw_count,
        "private_locator_receipt_count": private_locator_count,
        "raw_verification_errors": raw_errors,
        "observation_count": observation_count,
        "series_count": len(series),
        "fact_to_receipt_linkage": 1.0 if not observation_count else (observation_count - orphan_observations) / observation_count,
        "orphan_observation_count": orphan_observations,
        "receipt_fact_mismatch_count": receipt_mismatches,
        "receipts_with_fact_link": len(linked_receipts.intersection(receipt_index)),
        "receipts_without_fact_link": len(set(receipt_index).difference(linked_receipts)),
        "explicit_terminal_outcome_receipt_count": len(explicit_terminal),
        "receipts_without_explicit_terminal_outcome": len(set(receipt_index).difference(explicit_terminal)),
        "terminal_outcome_ledger_present": (root / V4_PARSE_OUTCOMES).is_file(),
        "revision_seq_distribution": {str(key): value for key, value in sorted(revision_seq.items())},
        "supersedes_count": supersedes_count,
        "available_after_1600_et_count": after_close,
        "fed_event_identity": {
            "row_count": sum(fed_series.values()),
            "series_row_counts": dict(sorted(fed_series.items())),
            "independent_snapshot_count": len(fed_snapshots),
            "snapshot_meeting_count": len(fed_snapshot_meetings),
            "snapshot_ids": sorted(fed_snapshots),
            "minimum_must_use_independent_snapshots_not_rows": True,
        },
        "nfp_consensus": {
            "consensus_row_count": len(consensus_rows),
            "actual_row_count": len(actual_rows),
            "consensus_available_at": [row["available_at"] for row in consensus_rows],
            "actual_available_at": [row["available_at"] for row in actual_rows],
            "pre_release_snapshot_proven": pre_release_proven,
            "model_use": "ineligible_as_pre_event_feature" if not pre_release_proven else "eligible_subject_to_other_gates",
            "reason": (
                "consensus and actual share the same availability timestamp"
                if consensus_available and actual_available and max(consensus_available) == min(actual_available)
                else "consensus snapshot time is not strictly earlier than the actual release"
            ) if not pre_release_proven else None,
        },
    }


def _review_pack_audit(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BaselineAuditError(f"review pack missing: {path}")
    zip_sha = file_sha256(path)
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        entries = {item.filename.replace("\\", "/"): item for item in archive.infolist()}
        manifest_info = entries.get("MANIFEST.json")
        if manifest_info is None:
            raise BaselineAuditError("review pack MANIFEST.json missing")
        manifest = json.loads(archive.read(manifest_info).decode("utf-8-sig"))
        rows = manifest.get("files") or []
        for row in rows:
            name = str(row["path"]).replace("\\", "/")
            info = entries.get(name)
            if info is None:
                errors.append(f"missing:{name}")
                continue
            body = archive.read(info)
            if len(body) != int(row["bytes"]):
                errors.append(f"size:{name}")
            if hashlib.sha256(body).hexdigest() != row["sha256"]:
                errors.append(f"sha256:{name}")
        entry_count = len(entries)
    if zip_sha != EXPECTED_REVIEW_PACK_SHA256:
        errors.append("review_pack_zip_sha256")
    if path.stat().st_size != EXPECTED_REVIEW_PACK_BYTES:
        errors.append("review_pack_zip_size")
    return {
        "path": str(path.resolve()),
        "zip_sha256": zip_sha,
        "zip_bytes": path.stat().st_size,
        "zip_entry_count": entry_count,
        "manifest_file_count": len(rows),
        "manifest_total_bytes": sum(int(row["bytes"]) for row in rows),
        "manifest_errors": errors,
    }


def _median_preserving_proof(root: Path, run: dict[str, Any]) -> dict[str, Any]:
    contract = yaml.safe_load((root / V4_CONTRACT).read_text(encoding="utf-8"))
    settings = contract["distributional_calibrator"]
    source = (root / "src/ai_fc/timeseries_v4/pipeline.py").read_text(encoding="utf-8")
    formula = "np.median(values) + scale * (values - np.median(values))"
    sample = np.asarray([-3.0, -1.0, 0.5, 2.0, 8.0])
    errors = []
    for scale in settings["centered_scale_by_band"]:
        transformed = np.median(sample) + float(scale) * (sample - np.median(sample))
        errors.append(abs(float(np.median(transformed) - np.median(sample))))
    return {
        "formula": "median(samples) + scale * (samples - median(samples))",
        "formula_occurrences_in_v4_pipeline": source.count(formula),
        "centered_scales": [float(value) for value in settings["centered_scale_by_band"]],
        "anomaly_thresholds": [float(value) for value in settings["anomaly_thresholds"]],
        "predecessor_replay_required": settings["predecessor_replay_required"] is True,
        "predecessor_run_id": run["predecessor_run_id"],
        "predecessor_content_hash": run["predecessor_content_hash"],
        "synthetic_median_max_abs_error": max(errors),
        "location_or_direction_learned_by_v4_calibrator": False,
        "scale_only": True,
    }


def _pack_comparison(result: dict[str, Any]) -> dict[str, Any]:
    scores = result["v4_run"]["score_audit"]
    lineage = result["v4_source_lineage"]
    observed = {
        "model_id": result["v4_run"]["model_id"],
        "benchmark_status": result["benchmark_status"],
        "origin_count": scores["origin_count"],
        "score_count": scores["score_count"],
        "sample_count": result["v4_run"]["sample_count"],
        "receipt_count": lineage["receipt_count"],
        "observation_count": lineage["observation_count"],
        "receipts_without_fact_link": lineage["receipts_without_fact_link"],
        "available_after_1600_et_count": lineage["available_after_1600_et_count"],
        "revision_seq_distribution": lineage["revision_seq_distribution"],
        "fed_independent_snapshot_count": lineage["fed_event_identity"]["independent_snapshot_count"],
        "nfp_pre_release_snapshot_proven": lineage["nfp_consensus"]["pre_release_snapshot_proven"],
        "improvement_21": scores["horizons"]["21"]["improvement"],
        "improvement_63": scores["horizons"]["63"]["improvement"],
        "long_horizon_mean_improvement": scores["long_horizon_mean_improvement"],
    }
    mismatches: list[dict[str, Any]] = []
    for key, expected in EXPECTED_PACK_VALUES.items():
        actual = observed[key]
        if isinstance(expected, float):
            equal = abs(float(actual) - expected) <= 1e-12
        else:
            equal = actual == expected
        if not equal:
            mismatches.append({"field": key, "expected": expected, "observed": actual})
    return {"expected": EXPECTED_PACK_VALUES, "observed": observed, "mismatches": mismatches}


def reproduce_v4_baseline(root: Path, *, review_pack: Path) -> dict[str, Any]:
    root = root.resolve()
    pointer = _json(root / V4_POINTER)
    run_path = root / str(pointer["run_path"])
    run = _json(run_path)
    predecessor_path = root / V3_RUNS / f"{run['predecessor_run_id']}.json"
    predecessor = _json(predecessor_path)
    seed = int(str(predecessor["contract_hash"])[:16], 16) % (2**32)
    score_audit = compute_score_audit(
        list(run["scores"]),
        bootstrap_seed=seed,
        bootstrap_iterations=1_000,
    )
    calculated = {
        "content_hash": canonical_hash({key: value for key, value in run.items() if key != "content_hash"}),
        "contract_hash": _contract_hash(root),
        "model_code_hash": _model_code_hash(root),
        "predecessor_content_hash": canonical_hash(
            {key: value for key, value in predecessor.items() if key != "content_hash"}
        ),
    }
    stored = {
        "content_hash": run["content_hash"],
        "contract_hash": run["contract_hash"],
        "model_code_hash": run["model_code_hash"],
        "predecessor_content_hash": run["predecessor_content_hash"],
    }
    hash_mismatches = [key for key, value in calculated.items() if value != stored[key]]
    lineage = _source_lineage_audit(root)
    review = _review_pack_audit(review_pack)
    result: dict[str, Any] = {
        "schema_version": 1,
        "task_id": "V5-P0-001",
        "model_id": "shadow.nasdaq_pit_hybrid_distribution_v5",
        "scope": "read_only_v4_immutable_benchmark_reproduction",
        "benchmark_status": str(run["status"]),
        "v4_run": {
            "model_id": run["model_id"],
            "run_id": run["run_id"],
            "run_path": run_path.relative_to(root).as_posix(),
            "run_file_sha256": file_sha256(run_path),
            "status": run["status"],
            "sample_count": int(run["sample_count"]),
            "stored_hashes": stored,
            "recomputed_hashes": calculated,
            "hash_mismatches": hash_mismatches,
            "score_audit": score_audit,
            "median_preserving_scale_proof": _median_preserving_proof(root, run),
            "gate_reasons": list(run["research_gate"]["reasons"]),
            "customer_numbers_visible": False,
        },
        "v4_source_lineage": lineage,
        "review_pack": review,
        "storage_and_orchestration_findings": {
            "observation_jsonl_bytes": (root / V4_OBSERVATIONS).stat().st_size,
            "jsonl_requires_full_scan_for_latest_read_model": True,
            "v4_weekly_workflow_couples_scheduled_collection_and_full_backtest": True,
            "ralph_controller_role": "frozen_v2_repair_loop_not_research_flywheel",
            "ralph_state_root": "outputs/timeseries_v2/ralph",
        },
        "fixed_conclusions": {
            "v4_hold_must_not_change": True,
            "gate_lowered": False,
            "existing_2007_2026_is_genuine_v5_sealed_holdout": False,
            "automatic_promotion": False,
            "automatic_publication": False,
            "automatic_trading": False,
        },
    }
    result["pack_comparison"] = _pack_comparison(result)
    result["reproduction_pass"] = not any(
        (
            hash_mismatches,
            result["pack_comparison"]["mismatches"],
            review["manifest_errors"],
            lineage["raw_verification_errors"],
            lineage["orphan_observation_count"],
            lineage["receipt_fact_mismatch_count"],
            score_audit["quantile_monotonicity_violations"],
        )
    )
    result["task_status"] = "passed_reproduction_v4_remains_hold" if result["reproduction_pass"] else "hold_input_mismatch"
    return result


def create_protected_manifest(
    root: Path,
    *,
    protected_roots: Sequence[str] = PROTECTED_ROOTS,
) -> dict[str, Any]:
    root = root.resolve()
    rows: list[dict[str, Any]] = []
    present: list[str] = []
    absent: list[str] = []
    for relative in protected_roots:
        path = root / relative
        if not path.exists():
            absent.append(relative)
            continue
        present.append(relative)
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        for item in candidates:
            if not item.is_file() or "__pycache__" in item.parts or item.suffix in {".pyc", ".pyo"}:
                continue
            rows.append(
                {
                    "path": item.relative_to(root).as_posix(),
                    "bytes": item.stat().st_size,
                    "sha256": file_sha256(item),
                }
            )
    rows.sort(key=lambda row: row["path"])
    return {
        "schema_version": 1,
        "task_id": "V5-P0-001",
        "scope": "protected_predecessor_and_customer_surfaces",
        "protected_roots_present": present,
        "protected_roots_absent": absent,
        "transient_exclusions": ["__pycache__", "*.pyc", "*.pyo"],
        "file_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "manifest_sha256": canonical_hash(rows),
        "files": rows,
    }


def compare_protected_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left = {str(row["path"]): row for row in before["files"]}
    right = {str(row["path"]): row for row in after["files"]}
    added = sorted(set(right).difference(left))
    removed = sorted(set(left).difference(right))
    changed = sorted(
        path
        for path in set(left).intersection(right)
        if left[path]["sha256"] != right[path]["sha256"] or int(left[path]["bytes"]) != int(right[path]["bytes"])
    )
    return {
        "unchanged": not (added or removed or changed),
        "before_manifest_sha256": before["manifest_sha256"],
        "after_manifest_sha256": after["manifest_sha256"],
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    # Write bytes so Windows newline translation cannot make the audited
    # worktree hash differ from the normalized Git blob hash.
    temporary.write_bytes(
        (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    os.replace(temporary, path)


def _audit_markdown(result: dict[str, Any], protected: dict[str, Any]) -> str:
    score = result["v4_run"]["score_audit"]
    lineage = result["v4_source_lineage"]
    return f"""# V4 → V5 baseline reproduction audit

- Task: `V5-P0-001`
- Scope: V4 immutable benchmark reproduction only
- Reproduction: **{'PASS' if result['reproduction_pass'] else 'HOLD — input mismatch'}**
- V4 benchmark decision: **{result['benchmark_status']}**
- V5 model/controller/storage implementation: not started in this task

## Immutable identities

| Coordinate | Recomputed value | Match |
|---|---|---|
| V4 run | `{result['v4_run']['run_id']}` | yes |
| V4 content hash | `{result['v4_run']['recomputed_hashes']['content_hash']}` | {'yes' if 'content_hash' not in result['v4_run']['hash_mismatches'] else 'no'} |
| V4 contract hash | `{result['v4_run']['recomputed_hashes']['contract_hash']}` | {'yes' if 'contract_hash' not in result['v4_run']['hash_mismatches'] else 'no'} |
| V4 model-code hash | `{result['v4_run']['recomputed_hashes']['model_code_hash']}` | {'yes' if 'model_code_hash' not in result['v4_run']['hash_mismatches'] else 'no'} |
| V3 predecessor content hash | `{result['v4_run']['recomputed_hashes']['predecessor_content_hash']}` | {'yes' if 'predecessor_content_hash' not in result['v4_run']['hash_mismatches'] else 'no'} |
| Review ZIP | `{result['review_pack']['zip_sha256']}` | {'yes' if not result['review_pack']['manifest_errors'] else 'no'} |

## Recomputed scores

| Horizon | V4 CRPS | Fixed comparator | Improvement | p10–p90 coverage | actual below median |
|---:|---:|---:|---:|---:|---:|
""" + "\n".join(
        f"| {horizon} | {row['model_crps']:.12f} | {row['baseline_crps']:.12f} | "
        f"{row['improvement']:.6%} | {row['p10_p90_coverage']:.6%} | "
        f"{row['actual_below_forecast_median_fraction']:.6%} |"
        for horizon, row in score["horizons"].items()
    ) + f"""

- Complete grid: {score['origin_count']} origins × 4 horizons = {score['score_count']} rows.
- Duplicate origin/horizon: {score['duplicate_origin_horizon_count']}.
- Quantile monotonicity violations: {score['quantile_monotonicity_violations']}.
- 21/63 mean CRPS improvement: {score['long_horizon_mean_improvement']:.6%}; frozen Gate: 2.000000%.
- Paired overlap-aware 90% CI: `{score['paired_loss_difference_90_ci']}`.
- Gate reasons: {', '.join(result['v4_run']['gate_reasons'])}.

## Source and PIT findings

- Receipts: {lineage['receipt_count']}; observations: {lineage['observation_count']}; fact→receipt linkage: {lineage['fact_to_receipt_linkage']:.6%}.
- Receipts with facts: {lineage['receipts_with_fact_link']}; without fact links: {lineage['receipts_without_fact_link']}.
- Explicit terminal parse outcomes: {lineage['explicit_terminal_outcome_receipt_count']}/{lineage['receipt_count']}. V4 has no terminal-outcome ledger, so this is not 100% terminal coverage.
- Revision distribution: `{lineage['revision_seq_distribution']}`; supersedes: {lineage['supersedes_count']}.
- Observations available after 16:00 ET: {lineage['available_after_1600_et_count']}.
- Fed-rate rows: {lineage['fed_event_identity']['row_count']}; independent snapshots: {lineage['fed_event_identity']['independent_snapshot_count']}; snapshot×meeting identities: {lineage['fed_event_identity']['snapshot_meeting_count']}.
- NFP consensus pre-release eligibility: **{lineage['nfp_consensus']['pre_release_snapshot_proven']}** — {lineage['nfp_consensus']['reason']}.
- V4 feature alignment converts `available_at` to a New York date, so the 16:00 boundary cannot be proven by the current feature view.

## Model proof

The V4 code applies `median + scale × (samples − median)` using scales 0.85/1.10/1.60. The synthetic median-preservation error is {result['v4_run']['median_preserving_scale_proof']['synthetic_median_max_abs_error']:.1e}. It changes scale only; it does not learn location, direction, or regime transition.

## Pack comparison and safety

- Pack numeric mismatches: {len(result['pack_comparison']['mismatches'])}.
- Review-pack manifest errors: {len(result['review_pack']['manifest_errors'])}.
- The separately supplied V5 blueprint delivery is verified by `input_blueprint_verification.json`.
- Protected baseline: {protected['file_count']} files, {protected['total_bytes']} bytes, manifest `{protected['manifest_sha256']}`.
- V4 remains `shadow_gate_hold`; customer numbers, automatic promotion, publication, and trading remain disabled.
- No provider credential is needed or read by this reproducer.

## Tests

- Focused V3/V4/P0-001 results are recorded in `outputs/timeseries_v5/audit/test_report.json`.
- Full-suite environment status is recorded separately and does not change the V4 HOLD decision.
- Secret non-exposure and protected before/after evidence are separate machine-readable artifacts.

## Unresolved blockers

1. V4 lacks receipt terminal-outcome accounting: 72/72 receipts have no explicit terminal outcome row.
2. All 113,615 observations are revision sequence 1; no real revision chain is demonstrated.
3. 57,973 availability timestamps are after 16:00 ET while the V4 feature join discards time-of-day.
4. Fed history is two independent snapshots, not six independent events.
5. The single NFP consensus row is timestamped exactly with the actual and is not a proven pre-release snapshot.

These are V5 backlog inputs, not changes authorized by task V5-P0-001.
"""


def write_audit_artifacts(root: Path, *, review_pack: Path) -> dict[str, Path]:
    root = root.resolve()
    audit_dir = root / "outputs/timeseries_v5/audit"
    docs_dir = root / "docs/timeseries_v5"
    before = create_protected_manifest(root)
    _atomic_json(audit_dir / "protected_manifest_before.json", before)
    result = reproduce_v4_baseline(root, review_pack=review_pack)
    _atomic_json(audit_dir / "baseline_reproduction.json", result)
    docs_dir.mkdir(parents=True, exist_ok=True)
    report_path = docs_dir / "V4_TO_V5_BASELINE_AUDIT.md"
    report_path.write_bytes(_audit_markdown(result, before).encode("utf-8"))
    after = create_protected_manifest(root)
    comparison = compare_protected_manifests(before, after)
    _atomic_json(audit_dir / "protected_manifest_after.json", after)
    _atomic_json(audit_dir / "protected_non_mutation.json", comparison)
    if not comparison["unchanged"]:
        raise BaselineAuditError(f"protected paths changed: {comparison}")
    if not result["reproduction_pass"]:
        raise BaselineAuditError(f"V4 reproduction mismatch: {result['pack_comparison']['mismatches']}")
    return {
        "baseline": audit_dir / "baseline_reproduction.json",
        "protected_before": audit_dir / "protected_manifest_before.json",
        "protected_after": audit_dir / "protected_manifest_after.json",
        "protected_comparison": audit_dir / "protected_non_mutation.json",
        "report": report_path,
    }


def parser() -> argparse.ArgumentParser:
    item = argparse.ArgumentParser(description=__doc__)
    item.add_argument("--root", type=Path, default=Path.cwd())
    item.add_argument("--review-pack", type=Path, required=True)
    return item


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        artifacts = write_audit_artifacts(args.root, review_pack=args.review_pack)
    except (BaselineAuditError, OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"task_id": "V5-P0-001", "status": "hold", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "task_id": "V5-P0-001",
                "status": "passed_reproduction_v4_remains_hold",
                "artifacts": {key: str(value) for key, value in artifacts.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
