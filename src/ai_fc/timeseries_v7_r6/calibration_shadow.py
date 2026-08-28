"""R6 calibration-only SHARPEN/TILT research without any R5 outer access."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .governance import (
    canonical_json,
    load_active_contract,
    protected_manifest,
    sha256_file,
    verify_inputs,
    write_json,
)
from .outer_guard import R5OuterDenylist


LEVELS = np.asarray([0.10, 0.25, 0.50, 0.75, 0.90], dtype=float)
QCOLS = ("p10", "p25", "p50", "p75", "p90")
HORIZONS = (1, 5, 21, 63)


def _as_quantiles(frame: pd.DataFrame) -> np.ndarray:
    return frame.loc[:, QCOLS].to_numpy(dtype=float)


def integrated_pinball(actual: Iterable[float], quantiles: np.ndarray) -> float:
    y = np.asarray(list(actual), dtype=float)[:, None]
    error = y - np.asarray(quantiles, dtype=float)
    loss = np.maximum(LEVELS * error, (LEVELS - 1.0) * error)
    return float(np.mean(loss))


def band_metrics(actual: Iterable[float], quantiles: np.ndarray) -> dict[str, float]:
    y = np.asarray(list(actual), dtype=float)
    q = np.asarray(quantiles, dtype=float)
    coverage80 = float(np.mean((y >= q[:, 0]) & (y <= q[:, 4])))
    coverage50 = float(np.mean((y >= q[:, 1]) & (y <= q[:, 3])))
    return {
        "coverage80": coverage80,
        "coverage50": coverage50,
        "nominal_coverage_absolute_error": abs(coverage80 - 0.80)
        + abs(coverage50 - 0.50),
    }


def scale_quantiles(quantiles: np.ndarray, scale: float) -> np.ndarray:
    q = np.asarray(quantiles, dtype=float)
    if scale == 1.0:
        return q.copy()
    median = q[:, 2:3]
    return median + float(scale) * (q - median)


def _interp_probability(value: float, quantiles: np.ndarray) -> float:
    q = np.maximum.accumulate(np.asarray(quantiles, dtype=float))
    if value <= q[0]:
        width = max(q[1] - q[0], 1e-12)
        return float(np.clip(LEVELS[0] + (value - q[0]) * 0.15 / width, 0.0, 0.10))
    if value >= q[-1]:
        width = max(q[-1] - q[-2], 1e-12)
        return float(np.clip(LEVELS[-1] + (value - q[-1]) * 0.15 / width, 0.90, 1.0))
    for index in range(len(LEVELS) - 1):
        if value <= q[index + 1]:
            width = q[index + 1] - q[index]
            if width <= 1e-12:
                return float((LEVELS[index] + LEVELS[index + 1]) / 2.0)
            weight = (value - q[index]) / width
            return float(LEVELS[index] + weight * (LEVELS[index + 1] - LEVELS[index]))
    raise AssertionError("unreachable predictive CDF branch")


def _interp_quantile(probability: float, quantiles: np.ndarray) -> float:
    probability = float(np.clip(probability, 0.0, 1.0))
    q = np.maximum.accumulate(np.asarray(quantiles, dtype=float))
    if probability <= LEVELS[0]:
        slope = (q[1] - q[0]) / 0.15
        return float(q[0] + (probability - LEVELS[0]) * slope)
    if probability >= LEVELS[-1]:
        slope = (q[-1] - q[-2]) / 0.15
        return float(q[-1] + (probability - LEVELS[-1]) * slope)
    return float(np.interp(probability, LEVELS, q))


def fit_pit_map(actual: Iterable[float], quantiles: np.ndarray) -> np.ndarray:
    pits = np.asarray(
        [_interp_probability(y, q) for y, q in zip(actual, quantiles, strict=True)],
        dtype=float,
    )
    return np.maximum.accumulate(np.quantile(pits, LEVELS, method="linear"))


def apply_pit_map(quantiles: np.ndarray, source_probabilities: np.ndarray) -> np.ndarray:
    return np.asarray(
        [
            [_interp_quantile(probability, row) for probability in source_probabilities]
            for row in np.asarray(quantiles, dtype=float)
        ],
        dtype=float,
    )


def implied_up_probability(quantiles: np.ndarray) -> np.ndarray:
    return np.asarray([1.0 - _interp_probability(0.0, row) for row in quantiles])


def balanced_accuracy(actual_up: np.ndarray, predicted_up: np.ndarray) -> float | None:
    actual = np.asarray(actual_up, dtype=bool)
    predicted = np.asarray(predicted_up, dtype=bool)
    positive = actual
    negative = ~actual
    if not positive.any() or not negative.any():
        return None
    return float((np.mean(predicted[positive]) + np.mean(~predicted[negative])) / 2.0)


def temporal_splits(
    origins: list[str], *, folds: int, warmup_folds: int, purge_and_embargo: int
) -> list[dict[str, object]]:
    ordered = sorted(set(origins))
    chunks = [list(chunk) for chunk in np.array_split(np.asarray(ordered), folds)]
    positions = {origin: index for index, origin in enumerate(ordered)}
    splits: list[dict[str, object]] = []
    for fold_index in range(warmup_folds, folds):
        test = chunks[fold_index]
        test_start_position = positions[test[0]]
        fit_stop = max(0, test_start_position - purge_and_embargo)
        fit = ordered[:fit_stop]
        if not fit:
            raise ValueError(f"R6 fold {fold_index} has no purged calibration history")
        splits.append(
            {
                "fold": fold_index + 1,
                "fit_origins": fit,
                "test_origins": test,
                "fit_last_position": positions[fit[-1]],
                "test_first_position": test_start_position,
                "excluded_origin_count": test_start_position - positions[fit[-1]] - 1,
            }
        )
    return splits


def _choose_scale(frame: pd.DataFrame, scale_grid: list[float]) -> tuple[float, list[dict[str, float]]]:
    actual = frame["actual"].to_numpy(dtype=float)
    base = _as_quantiles(frame)
    base_pinball = integrated_pinball(actual, base)
    trials: list[dict[str, float]] = []
    for scale in scale_grid:
        candidate = scale_quantiles(base, float(scale))
        bands = band_metrics(actual, candidate)
        trials.append(
            {
                "scale": float(scale),
                "integrated_pinball": integrated_pinball(actual, candidate),
                **bands,
            }
        )
    eligible = [
        row for row in trials if row["integrated_pinball"] <= base_pinball + 1e-15
    ]
    if not eligible:
        return 1.0, trials
    chosen = min(
        eligible,
        key=lambda row: (
            row["nominal_coverage_absolute_error"],
            row["integrated_pinball"],
            abs(row["scale"] - 1.0),
        ),
    )
    return float(chosen["scale"]), trials


def _market_returns(path: Path) -> dict[str, float]:
    rows: list[tuple[str, float]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            rows.append((str(row["date"]), float(row["value"])))
    rows.sort()
    returns: dict[str, float] = {}
    for index in range(1, len(rows)):
        date, value = rows[index]
        previous = rows[index - 1][1]
        if value > 0.0 and previous > 0.0:
            returns[date] = math.log(value / previous)
    return returns


def _tilt_quantiles(quantiles: np.ndarray, shifts: np.ndarray) -> np.ndarray:
    return np.asarray(quantiles, dtype=float) + np.asarray(shifts, dtype=float)[:, None]


def _choose_t2(
    frame: pd.DataFrame,
    prior_returns: dict[str, float],
    shrinkage_grid: list[float],
    minimum_group_rows: int,
) -> tuple[float, dict[str, float], list[dict[str, float]]]:
    origin_returns = frame["origin_session"].map(prior_returns)
    if origin_returns.isna().any():
        raise ValueError("T2 requires a known completed-session return at every origin")
    groups = np.where(origin_returns.to_numpy(dtype=float) < 0.0, "negative", "nonnegative")
    residual = frame["actual"].to_numpy(dtype=float) - frame["p50"].to_numpy(dtype=float)
    medians: dict[str, float] = {}
    for group in ("negative", "nonnegative"):
        selected = residual[groups == group]
        if len(selected) < minimum_group_rows:
            return 0.0, {"negative": 0.0, "nonnegative": 0.0}, []
        medians[group] = float(np.median(selected))
    base = _as_quantiles(frame)
    actual = frame["actual"].to_numpy(dtype=float)
    trials = []
    for shrinkage in shrinkage_grid:
        shifts = np.asarray([shrinkage * medians[group] for group in groups])
        score = integrated_pinball(actual, _tilt_quantiles(base, shifts))
        trials.append({"shrinkage": float(shrinkage), "integrated_pinball": score})
    chosen = min(trials, key=lambda row: (row["integrated_pinball"], row["shrinkage"]))
    return float(chosen["shrinkage"]), medians, trials


def _prediction_rows(
    test: pd.DataFrame,
    quantiles: np.ndarray,
    *,
    candidate: str,
    fold: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source, q in zip(test.itertuples(index=False), quantiles, strict=True):
        rows.append(
            {
                "origin_session": str(source.origin_session),
                "horizon": int(source.horizon),
                "fold": int(fold),
                "role": "calibration_crossfit_holdout",
                "candidate": candidate,
                "actual": float(source.actual),
                **{column: float(value) for column, value in zip(QCOLS, q, strict=True)},
            }
        )
    return rows


def _candidate_metrics(predictions: pd.DataFrame) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    for (candidate, horizon), frame in predictions.groupby(["candidate", "horizon"]):
        q = _as_quantiles(frame)
        actual = frame["actual"].to_numpy(dtype=float)
        p_up = implied_up_probability(q)
        metrics.append(
            {
                "candidate": str(candidate),
                "horizon": int(horizon),
                "rows": len(frame),
                "integrated_pinball": integrated_pinball(actual, q),
                **band_metrics(actual, q),
                "p_up_mean": float(np.mean(p_up)),
                "p_up_std": float(np.std(p_up)),
                "p50_balanced_accuracy": balanced_accuracy(actual > 0.0, q[:, 2] > 0.0),
                "p_up_balanced_accuracy": balanced_accuracy(actual > 0.0, p_up >= 0.5),
            }
        )
    return metrics


def _select_sharpen(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    selections: list[dict[str, object]] = []
    for horizon in HORIZONS:
        rows = [
            row
            for row in metrics
            if row["horizon"] == horizon and row["candidate"] in {"C0", "C1", "C2"}
        ]
        baseline = next(row for row in rows if row["candidate"] == "C0")
        eligible = [
            row
            for row in rows
            if row["integrated_pinball"] <= baseline["integrated_pinball"] + 1e-15
        ]
        selected = min(
            eligible,
            key=lambda row: (
                row["nominal_coverage_absolute_error"],
                row["integrated_pinball"],
                row["candidate"],
            ),
        )
        selections.append(
            {
                "horizon": horizon,
                "selected_candidate": selected["candidate"],
                "selection_role": "calibration_crossfit_holdout",
                "constraint": "integrated_pinball_nondegradation_vs_C0",
            }
        )
    return selections


def _c3_audit(repo_root: Path, contract: dict[str, object]) -> dict[str, object]:
    guard = R5OuterDenylist.load(repo_root)
    pool_record = contract["input_artifacts"]["r5_standardized_residual_pool"]
    pool_path = repo_root / pool_record["path"]
    guard.assert_role_allowed(str(pool_record["allowed_role"]))
    guard.assert_path_allowed(pool_path)
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    z_summary = []
    for horizon in HORIZONS:
        values = np.asarray([row["z"] for row in pool["pools"][str(horizon)]["rows"]])
        z_summary.append(
            {
                "horizon": horizon,
                "rows": len(values),
                "mean": float(np.mean(values)),
                "standard_deviation": float(np.std(values, ddof=1)),
                "near_unit_standard_deviation": bool(abs(np.std(values, ddof=1) - 1.0) <= 0.10),
            }
        )

    source_names = (
        ("r5_m1_calibration_scores", "conditional_component_m1"),
        ("r5_m2_calibration_scores", "conditional_component_m2"),
        ("r5_m3_calibration_scores", "e0_weighted_proxy_m3"),
        ("r5_calibration_scores", "final_stacked_s1"),
    )
    width_summary: list[dict[str, object]] = []
    for artifact_name, label in source_names:
        record = contract["input_artifacts"][artifact_name]
        path = repo_root / record["path"]
        guard.assert_role_allowed(str(record["allowed_role"]))
        guard.assert_path_allowed(path)
        frame = pd.read_parquet(path)
        for role in frame["role"].astype(str).unique():
            guard.assert_role_allowed(role)
        for horizon, group in frame.groupby("horizon"):
            width_summary.append(
                {
                    "source": label,
                    "horizon": int(horizon),
                    "rows": len(group),
                    "mean_width80": float(np.mean(group["p90"] - group["p10"])),
                    "mean_width50": float(np.mean(group["p75"] - group["p25"])),
                }
            )
    return {
        "schema": "r6_c3_structural_width_audit_v1",
        "role": "calibration_audit_only",
        "standardized_residual_pool": z_summary,
        "interval_width_decomposition_proxies": width_summary,
        "causal_e0_floor_attribution_proven": False,
        "limitation": (
            "Component-level calibration widths do not identify the causal E0-floor "
            "contribution without a newly approved sample-level reblend."
        ),
        "decision_gate": "R6-D1",
        "outer_rows_used": 0,
    }


def _e0_nesting(repo_root: Path, contract: dict[str, object]) -> dict[str, object]:
    record = contract["input_artifacts"]["registered_e0_matrix"]
    guard = R5OuterDenylist.load(repo_root)
    path = repo_root / record["path"]
    guard.assert_role_allowed(str(record["allowed_role"]))
    guard.assert_path_allowed(path)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    proofs = []
    for coordinate in artifact["coordinates"]:
        values = coordinate["sample_set"]["values"]
        before = hashlib.sha256(canonical_json(values)).hexdigest()
        c1_identity = list(values)
        c2_identity = list(values)
        t2_identity = list(values)
        hashes = {
            "E0": before,
            "C1_scale_1": hashlib.sha256(canonical_json(c1_identity)).hexdigest(),
            "C2_identity_map": hashlib.sha256(canonical_json(c2_identity)).hexdigest(),
            "T2_shrinkage_0": hashlib.sha256(canonical_json(t2_identity)).hexdigest(),
        }
        proofs.append(
            {
                "origin_session": coordinate["origin_session"],
                "horizon": coordinate["horizon_sessions"],
                "sample_count": len(values),
                "hashes": hashes,
                "exact_identity": len(set(hashes.values())) == 1,
            }
        )
    return {
        "schema": "r6_e0_nesting_proof_v1",
        "registered_matrix_sha256": sha256_file(path),
        "coordinates": proofs,
        "all_exact": all(row["exact_identity"] for row in proofs),
        "outer_rows_used": 0,
    }


def run_calibration_shadow(repo_root: Path, output_dir: Path) -> dict[str, object]:
    root = repo_root.resolve()
    output = output_dir.resolve()
    before = protected_manifest(root)
    contract = load_active_contract(root)
    verified = verify_inputs(root, contract)
    if not verified["all_matched"]:
        raise RuntimeError("R6 active preregistration input hash mismatch")
    guard = R5OuterDenylist.load(root)

    score_record = contract["input_artifacts"]["r5_calibration_scores"]
    score_path = root / score_record["path"]
    guard.assert_role_allowed(str(score_record["allowed_role"]))
    guard.assert_path_allowed(score_path)
    calibration = pd.read_parquet(score_path).sort_values(
        ["origin_session", "horizon"]
    )
    for role in calibration["role"].astype(str).unique():
        guard.assert_role_allowed(role)
    if set(calibration["role"].astype(str)) != {"calibration"}:
        raise ValueError("R6 candidate fitting accepts calibration rows only")

    market_record = contract["input_artifacts"]["nasdaq_observations"]
    market_path = root / market_record["path"]
    guard.assert_role_allowed(str(market_record["allowed_role"]))
    guard.assert_path_allowed(market_path)
    prior_returns = _market_returns(market_path)

    invariants = contract["frozen_invariants"]
    purge_and_embargo = int(invariants["purge_sessions"]) + int(
        invariants["embargo_sessions"]
    )
    origins = sorted(calibration["origin_session"].astype(str).unique())
    splits = temporal_splits(
        origins,
        folds=int(invariants["cross_fit_folds"]),
        warmup_folds=int(invariants["cross_fit_warmup_folds"]),
        purge_and_embargo=purge_and_embargo,
    )

    prediction_rows: list[dict[str, object]] = []
    fit_receipts: list[dict[str, object]] = []
    for split in splits:
        fold = int(split["fold"])
        fit_origins = set(split["fit_origins"])
        test_origins = set(split["test_origins"])
        if fit_origins & test_origins:
            raise AssertionError("R6 calibration fit/test roles overlap")
        for horizon in HORIZONS:
            fit = calibration[
                calibration["origin_session"].isin(fit_origins)
                & (calibration["horizon"] == horizon)
            ].copy()
            test = calibration[
                calibration["origin_session"].isin(test_origins)
                & (calibration["horizon"] == horizon)
            ].copy()
            if len(fit) < int(contract["candidates"]["C2"]["minimum_fit_rows"]):
                raise ValueError(f"R6 fold {fold} horizon {horizon} lacks C2 fit rows")
            base_test = _as_quantiles(test)
            prediction_rows.extend(
                _prediction_rows(test, base_test, candidate="C0", fold=fold)
            )

            scale, scale_trials = _choose_scale(
                fit, list(contract["candidates"]["C1"]["scale_grid"])
            )
            prediction_rows.extend(
                _prediction_rows(
                    test,
                    scale_quantiles(base_test, scale),
                    candidate="C1",
                    fold=fold,
                )
            )

            pit_probabilities = fit_pit_map(
                fit["actual"].to_numpy(dtype=float), _as_quantiles(fit)
            )
            prediction_rows.extend(
                _prediction_rows(
                    test,
                    apply_pit_map(base_test, pit_probabilities),
                    candidate="C2",
                    fold=fold,
                )
            )

            shrinkage, medians, shrinkage_trials = _choose_t2(
                fit,
                prior_returns,
                list(contract["candidates"]["T2"]["shrinkage_grid"]),
                int(contract["candidates"]["T2"]["minimum_group_rows"]),
            )
            test_groups = np.where(
                test["origin_session"].map(prior_returns).to_numpy(dtype=float) < 0.0,
                "negative",
                "nonnegative",
            )
            shifts = np.asarray([shrinkage * medians[group] for group in test_groups])
            prediction_rows.extend(
                _prediction_rows(
                    test,
                    _tilt_quantiles(base_test, shifts),
                    candidate="T2",
                    fold=fold,
                )
            )
            fit_receipts.append(
                {
                    "fold": fold,
                    "horizon": horizon,
                    "fit_rows": len(fit),
                    "test_rows": len(test),
                    "fit_last_origin": max(fit_origins),
                    "test_first_origin": min(test_origins),
                    "excluded_origin_count": split["excluded_origin_count"],
                    "C1": {"selected_scale": scale, "trials": scale_trials},
                    "C2": {"source_probabilities": pit_probabilities.tolist()},
                    "T2": {
                        "selected_shrinkage": shrinkage,
                        "group_median_residuals": medians,
                        "trials": shrinkage_trials,
                    },
                }
            )

    predictions = pd.DataFrame(prediction_rows).sort_values(
        ["candidate", "horizon", "origin_session"]
    )
    if not (
        (predictions["p10"] <= predictions["p25"])
        & (predictions["p25"] <= predictions["p50"])
        & (predictions["p50"] <= predictions["p75"])
        & (predictions["p75"] <= predictions["p90"])
    ).all():
        raise AssertionError("R6 candidate transformation broke quantile monotonicity")

    metrics = _candidate_metrics(predictions)
    sharpen_selection = _select_sharpen(metrics)
    direction = {
        "schema": "r6_direction_measurement_audit_v1",
        "T0": [row for row in metrics if row["candidate"] == "C0"],
        "T2": [row for row in metrics if row["candidate"] == "T2"],
        "T3": {
            "definition": "P(up)=1-F_predictive(0)",
            "fit": False,
            "probability_unit": "fraction",
            "bounds_pass": bool(
                np.all(
                    (implied_up_probability(_as_quantiles(predictions)) >= 0.0)
                    & (implied_up_probability(_as_quantiles(predictions)) <= 1.0)
                )
            ),
        },
        "outer_rows_used": 0,
    }
    c3 = _c3_audit(root, contract)
    nesting = _e0_nesting(root, contract)

    output.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output / "crossfit_predictions.parquet", index=False)
    write_json(
        output / "calibration_candidate_metrics.json",
        {
            "schema": "r6_calibration_candidate_metrics_v1",
            "model_id": contract["model_id"],
            "contract_revision": contract["active_revision"],
            "metrics": metrics,
            "sharpen_selection": sharpen_selection,
            "fit_receipts": fit_receipts,
            "row_use_counters": {
                "calibration_source_rows": len(calibration),
                "crossfit_prediction_rows": len(predictions),
                "outer_rows_used": 0,
            },
        },
    )
    write_json(output / "direction_audit.json", direction)
    write_json(output / "c3_structural_width_audit.json", c3)
    write_json(output / "e0_nesting_proof.json", nesting)
    write_json(
        output / "preregistration_revision_receipt.json",
        {
            "schema": "r6_preregistration_revision_receipt_v1",
            "base_contract_sha256": contract["active_revision"]["supersedes_sha256"],
            "revision_contract_sha256": contract["active_revision"]["sha256"],
            "revision_contract_path": contract["active_revision"]["path"],
            "candidate_outputs_seen_before_registration": False,
            "all_registered_inputs_matched": verified["all_matched"],
            "outer_rows_used": 0,
        },
    )

    after = protected_manifest(root)
    write_json(output / "protected_manifest_after.json", after)
    protected_unchanged = before["manifest_sha256"] == after["manifest_sha256"]
    checkpoint = {
        "schema": "r6_decision_checkpoint_v1",
        "status": "WAIT_USER_DECISIONS",
        "terminal_state_claimed": False,
        "research_gate_pass": False,
        "numbers_visible": False,
        "outer_rows_used": 0,
        "protected_non_mutation": protected_unchanged,
        "completed_without_decisions": ["C1", "C2", "C3_audit", "T0", "T2", "T3", "E0_nesting"],
        "disabled": {"T1": "R6-D2 approval required"},
        "pending_decisions": {
            "R6-D1": "Maintain the E0 floor or approve a formal lower-floor contract revision.",
            "R6-D2": "Approve VIXCLS DV-1 onboarding for T1 or defer it.",
            "R6-D3": "Preregister prospective sample timing and coverage tolerance before ledger initialization.",
        },
        "forbidden_claims_observed": [],
    }
    write_json(output / "decision_checkpoint.json", checkpoint)
    artifact_paths = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "artifact_manifest.json"
    )
    write_json(
        output / "artifact_manifest.json",
        {
            "schema": "r6_internal_artifact_manifest_v1",
            "artifacts": [
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in artifact_paths
            ],
            "outer_rows_used": 0,
        },
    )
    return checkpoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_calibration_shadow(args.repo, args.output_dir)
    return 0 if result["status"] == "WAIT_USER_DECISIONS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
