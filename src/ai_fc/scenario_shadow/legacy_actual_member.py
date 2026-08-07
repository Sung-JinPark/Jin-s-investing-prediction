"""Build the honest Legacy GBM actual-member diagnostic candidate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .contracts import ScenarioShadowContractError, validate_candidate_payload
from .legacy_reproduction import (
    QUANTILES,
    SCENARIO_KEYS,
    LegacyGBMReproduction,
    reproduce_legacy_snapshot,
)
from .persistence import (
    OFFICIAL_RELATIVE_PATH,
    canonical_json_bytes,
    sha256_bytes,
    write_candidate,
)
from .representative import RepresentativeSelectionError, select_actual_representative_path


CANDIDATE_ID = "legacy_gbm_actual_member_v1"
GENERATOR_VERSION = "legacy-gbm-actual-member-v1"
SAMPLE_GATES = {
    "representative_and_p50": 200,
    "p25_p75": 500,
    "p10_p90": 1000,
    "p05_p95": 2000,
}
ALL_QUANTILES = tuple(key for _, key in QUANTILES)


def _git_revision(root: Path) -> tuple[str | None, bool | None]:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=root,
                text=True,
                encoding="utf-8",
                stderr=subprocess.DEVNULL,
            ).strip()
        )
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _rounded_quantiles(values: np.ndarray, keys: tuple[str, ...]) -> dict[str, list[int]]:
    percentile_by_key = {key: percentile for percentile, key in QUANTILES}
    return {
        key: [
            int(round(float(value)))
            for value in np.percentile(values, percentile_by_key[key], axis=0)
        ]
        for key in keys
    }


def _quantile_availability(sample_count: int) -> tuple[tuple[str, ...], dict[str, str]]:
    if sample_count < SAMPLE_GATES["representative_and_p50"]:
        return (), {
            "representative_and_p50": (
                f"insufficient_conditional_sample_n_{sample_count}_lt_200"
            )
        }
    available = ["p50"]
    blocked: dict[str, str] = {}
    for band, threshold, keys in (
        ("p25_p75", 500, ("p25", "p75")),
        ("p10_p90", 1000, ("p10", "p90")),
        ("p05_p95", 2000, ("p05", "p95")),
    ):
        if sample_count >= threshold:
            available.extend(keys)
        else:
            blocked[band] = (
                f"insufficient_conditional_sample_n_{sample_count}_lt_{threshold}"
            )
    return tuple(key for key in ALL_QUANTILES if key in available), blocked


def _validate_quantiles(quantiles: dict[str, list[int]], expected_length: int) -> None:
    arrays = []
    for key in ALL_QUANTILES:
        values = quantiles.get(key)
        if values is None:
            continue
        if len(values) != expected_length:
            raise ScenarioShadowContractError(f"{key} quantile length mismatch")
        arrays.append((key, np.asarray(values, dtype=float)))
    for (left_key, left), (right_key, right) in zip(arrays, arrays[1:]):
        if bool(np.any(left > right)):
            raise ScenarioShadowContractError(
                f"quantile order violation: {left_key}>{right_key}"
            )


def _year_slices(week_dates: tuple[str, ...]) -> dict[str, dict[str, int | str]]:
    result: dict[str, dict[str, int | str]] = {}
    years = sorted({date[:4] for date in week_dates})
    for year in years:
        indexes = [index for index, date in enumerate(week_dates) if date.startswith(year)]
        result[year] = {
            "start_index": indexes[0],
            "end_index": indexes[-1],
            "start_date": week_dates[indexes[0]],
            "end_date": week_dates[indexes[-1]],
        }
    return result


def build_legacy_diagnostic_payload(
    *,
    root: Path,
    snapshot: dict[str, Any],
    source_bytes: bytes,
    reproduction: LegacyGBMReproduction,
) -> dict[str, Any]:
    config = {
        "candidate_id": CANDIDATE_ID,
        "generator_version": GENERATOR_VERSION,
        "sample_gates": SAMPLE_GATES,
        "quantiles": list(ALL_QUANTILES),
        "representative_rule": "actual-central-multimetric-v1",
        "rounding": "nearest_integer_half_to_even",
    }
    source_sha = sha256_bytes(source_bytes)
    config_sha = sha256_bytes(canonical_json_bytes(config))
    n_paths = int(snapshot["model"]["n_paths"])
    code_revision, code_revision_dirty = _git_revision(root)

    unconditional_quantiles = _rounded_quantiles(
        reproduction.sampled_weekly, ALL_QUANTILES
    )
    _validate_quantiles(unconditional_quantiles, len(reproduction.week_dates))
    scenario_distributions: dict[str, Any] = {}
    representatives: dict[str, Any] = {}
    for key in SCENARIO_KEYS:
        mask = reproduction.masks[key]
        count = reproduction.counts[key]
        available, blocked = _quantile_availability(count)
        quantiles = _rounded_quantiles(reproduction.sampled_weekly[mask], available)
        _validate_quantiles(quantiles, len(reproduction.week_dates))
        try:
            representative = select_actual_representative_path(
                future_daily=reproduction.future_daily,
                sampled_weekly=reproduction.sampled_weekly,
                mask=mask,
                trading_days=reproduction.trading_days,
            )
        except RepresentativeSelectionError as exc:
            scenario_distributions[key] = {
                "status": "representative_hidden_no_candidate",
                "probability_space": "scenario_conditional",
                "sample_count": count,
                "available_quantiles": list(available),
                "blocked_quantiles": blocked,
                "quantiles": quantiles,
                "representative_path_id": None,
                "representative_blocked_reason": str(exc),
            }
            continue
        selected_index = representative["original_global_path_index"]
        if not bool(mask[selected_index]):
            raise ScenarioShadowContractError(f"{key} representative is outside cohort")
        expected_weekly = [
            int(round(float(value)))
            for value in reproduction.sampled_weekly[selected_index]
        ]
        if representative["weekly_values"] != expected_weekly:
            raise ScenarioShadowContractError(f"{key} representative is not an actual row")
        scenario_distributions[key] = {
            "status": "ok",
            "probability_space": "scenario_conditional",
            "sample_count": count,
            "available_quantiles": list(available),
            "blocked_quantiles": blocked,
            "quantiles": quantiles,
            "representative_path_id": representative["path_id"],
        }
        representatives[key] = representative

    payload: dict[str, Any] = {
        "schema_version": 2,
        "artifact_kind": "scenario_path_shadow",
        "candidate_id": CANDIDATE_ID,
        "status": "shadow_only",
        "promotion_state": "not_eligible_diagnostic_baseline",
        "dashboard_toggle_default": "off",
        "model_identity": {
            "family": "legacy_gbm",
            "engine_id": "gbm-daily-252d-v2-lookup",
            "display_variant": "actual_member_conditional_diagnostic",
            "is_rcfhs": False,
            "capabilities": {
                "approved_pit_history": False,
                "observable_regime": False,
                "state_conditioned_drift": False,
                "conditional_volatility": False,
                "standardized_empirical_residuals": False,
                "stationary_block_bootstrap": False,
                "source_block_lineage": False,
                "continuous_252_session_recursion": True,
                "adaptive_joint_simulation": False,
                "pointwise_conditional_quantiles": True,
                "actual_member_representative": True,
                "rolling_origin_validation": False,
            },
        },
        "source": {
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_sha256": source_sha,
            "asof": snapshot["asof"],
            "method": snapshot["method"],
            "revision": snapshot.get("revision"),
        },
        "config": config,
        "anchor": float(snapshot["anchor"]),
        "ath": float(snapshot["ath"]),
        "week_dates": list(reproduction.week_dates),
        "year_slices": _year_slices(reproduction.week_dates),
        "reproducibility": {
            "seed": int(snapshot["model"]["seed"]),
            "n_paths": n_paths,
            "horizon_sessions": int(snapshot["model"]["horizon_business_days"]),
            "config_sha256": config_sha,
            "canonical_payload_sha256": None,
            "generator_version": GENERATOR_VERSION,
            "code_revision": code_revision,
            "code_revision_dirty": code_revision_dirty,
            "matrix_summary_sha256": hashlib.sha256(
                reproduction.future_daily.tobytes(order="C")
            ).hexdigest(),
            "verification": reproduction.verification,
        },
        "official_weights": {
            "unit": "fraction",
            "source": "official_snapshot_partition",
            "values": {
                key: float(snapshot["paths"][key]["prob"]) / 100.0
                for key in SCENARIO_KEYS
            },
        },
        "candidate_implied_weights": {
            "unit": "fraction",
            "source": "reproduced_joint_partition_count",
            "values": {
                key: reproduction.counts[key] / n_paths for key in SCENARIO_KEYS
            },
        },
        "unconditional_distribution": {
            "status": "ok",
            "probability_space": "joint_unconditional_legacy_gbm",
            "sample_count": n_paths,
            "available_quantiles": list(ALL_QUANTILES),
            "quantiles": unconditional_quantiles,
            "basis": "direct percentile of the full joint sample matrix",
        },
        "scenario_distributions": scenario_distributions,
        "representatives": representatives,
        "diagnostics": {
            "sample_gates": SAMPLE_GATES,
            "partition_exhaustive_and_disjoint": True,
            "mixture_quantile_method": "direct_full_joint_samples",
            "weighted_average_of_conditional_quantiles": False,
            "all_stored_quantiles_monotone": True,
            "true_rcfhs_status": "not_implemented",
        },
        "receipt": {},
    }
    validate_candidate_payload(payload)
    return payload


def build_and_write_legacy_diagnostic(
    root: Path,
) -> tuple[Path, dict[str, Any], bool]:
    official_path = root / OFFICIAL_RELATIVE_PATH
    source_bytes = official_path.read_bytes()
    snapshot = json.loads(source_bytes.decode("utf-8"))
    reproduction = reproduce_legacy_snapshot(snapshot)
    payload = build_legacy_diagnostic_payload(
        root=root,
        snapshot=snapshot,
        source_bytes=source_bytes,
        reproduction=reproduction,
    )
    return write_candidate(root, payload)
