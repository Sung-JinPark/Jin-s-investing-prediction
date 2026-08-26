"""Deterministic, bounded screening for G1 direct-horizon challengers."""

from __future__ import annotations

import math
import json
from hashlib import sha256
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import ndtr

from .integrity import canonical_json, sha256_bytes


FUNNEL_BUDGETS = {
    "smoke": 160,
    "inner_screen": 48,
    "robust_inner": 12,
    "full_nested": 4,
    "qualification": 1,
}

_SCORE_COLUMNS = {
    "smoke": "smoke_crps",
    "inner_screen": "inner_crps",
    "robust_inner": "robust_inner_crps",
    "full_nested": "full_nested_crps",
}


def _sha256(value: Any, field: str) -> str:
    exact = str(value)
    if len(exact) != 64 or any(char not in "0123456789abcdef" for char in exact):
        raise ValueError(f"{field} must be a lowercase SHA-256 hash")
    return exact


def _budgets(overrides: Mapping[str, int] | None) -> dict[str, int]:
    result = dict(FUNNEL_BUDGETS)
    for stage, value in (overrides or {}).items():
        if stage not in result or isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("valid candidate funnel budget is required")
        if value < 0 or value > FUNNEL_BUDGETS[stage]:
            raise ValueError("candidate funnel budget exceeds the frozen contract")
        result[stage] = value
    ordered = list(result.values())
    if any(right > left for left, right in zip(ordered, ordered[1:])):
        raise ValueError("candidate funnel budgets must be non-increasing")
    return result


def screen_g1_candidates(
    candidates: Iterable[Mapping[str, Any]], *, e0_crps: float,
    generation_hash: str, budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Run each candidate through the frozen funnel without changing its evidence.

    Every stage selects only from its predecessor and sorts on that stage's
    precomputed out-of-sample CRPS.  The function does not fit, re-score, or
    re-select observations, so frozen research coordinates remain untouched.
    """
    generation_hash = _sha256(generation_hash, "generation_hash")
    limits = _budgets(budgets)
    baseline = float(e0_crps)
    if not math.isfinite(baseline) or baseline <= 0.0:
        raise ValueError("finite positive E0 CRPS is required")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in candidates:
        candidate_id = str(source.get("candidate_id", ""))
        hypothesis = source.get("hypothesis")
        exposure = source.get("exposure")
        if not candidate_id or candidate_id in seen:
            raise ValueError("unique candidate_id is required")
        if not isinstance(hypothesis, Mapping) or not hypothesis:
            raise ValueError("explicit candidate hypothesis is required")
        if not isinstance(exposure, Mapping) or not exposure:
            raise ValueError("explicit candidate exposure is required")
        scores = {}
        for stage, column in _SCORE_COLUMNS.items():
            score = float(source.get(column, float("nan")))
            if not math.isfinite(score) or score < 0.0:
                raise ValueError(f"finite non-negative {column} is required")
            scores[stage] = score
        seen.add(candidate_id)
        normalized.append({
            "candidate_id": candidate_id,
            "hypothesis_hash": sha256_bytes(canonical_json(dict(hypothesis))),
            "exposure_hash": sha256_bytes(canonical_json(dict(exposure))),
            "scores": scores,
            "deepest_stage": None,
            "weight": 0.0,
            **({"score_kind": source["score_kind"]} if "score_kind" in source else {}),
            **({"model_receipt": source["model_receipt"]} if "model_receipt" in source else {}),
            **({"checkpoint_key": source["checkpoint_key"]} if "checkpoint_key" in source else {}),
        })

    selected = sorted(normalized, key=lambda row: row["candidate_id"])
    counts: dict[str, int] = {}
    for stage in _SCORE_COLUMNS:
        selected = sorted(selected, key=lambda row: (row["scores"][stage], row["candidate_id"]))[
            : limits[stage]
        ]
        counts[stage] = len(selected)
        for row in selected:
            row["deepest_stage"] = stage
    qualified = selected[:limits["qualification"]]
    counts["qualification"] = len(qualified)
    qualified_ids = {row["candidate_id"] for row in qualified}
    for row in normalized:
        final_score = row["scores"]["full_nested"]
        if row["candidate_id"] in qualified_ids and final_score < baseline:
            row["weight"] = min(1.0, 1.0 - final_score / baseline)
            row["deepest_stage"] = "qualification"

    return {
        "schema": "g1_bounded_candidate_funnel_v1",
        "generation_hash": generation_hash,
        "funnel_budgets": limits,
        "candidate_counts": counts,
        "candidates": sorted(normalized, key=lambda row: row["candidate_id"]),
    }


_IDENTITY_COLUMNS = frozenset({
    "origin_session", "origin_cutoff_at", "max_available_at", "pit_pass", "price",
})
_G1_CORE_FEATURES = (
    "ret_1", "momentum_5", "momentum_21", "momentum_63",
    "rv_5", "rv_21", "rv_63", "vix_level", "term_level", "dff_level",
)


def _quantile_crps(actual: float, quantiles: Mapping[float, float]) -> float:
    """Approximate distribution CRPS by integrating quantile (pinball) loss."""
    coordinates = sorted((float(q), float(value)) for q, value in quantiles.items())
    if len(coordinates) < 2 or coordinates[0][0] <= 0.0 or coordinates[-1][0] >= 1.0:
        raise ValueError("at least two interior predictive quantiles are required")
    losses = []
    for quantile, prediction in coordinates:
        error = float(actual) - prediction
        losses.append(max(quantile * error, (quantile - 1.0) * error))
    # Constant tails plus trapezoidal integration over the stored quantile function.
    integral = coordinates[0][0] * losses[0] + (1.0 - coordinates[-1][0]) * losses[-1]
    integral += sum(
        (right[0] - left[0]) * (left_loss + right_loss) / 2.0
        for left, right, left_loss, right_loss in zip(
            coordinates, coordinates[1:], losses, losses[1:],
        )
    )
    return 2.0 * integral


def _normal_crps(actual: float, location: float, scale: float) -> float:
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("positive predictive scale is required")
    z = (actual - location) / scale
    density = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return scale * (z * (2.0 * float(ndtr(z)) - 1.0) + 2.0 * density
                    - 1.0 / math.sqrt(math.pi))


def _training_rows(export: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Join the authoritative export without weakening its PIT timestamps."""
    as_of = str(export.get("as_of", ""))
    features = export.get("feature_rows")
    labels = export.get("labels")
    if not as_of or not isinstance(features, list) or not isinstance(labels, list):
        raise ValueError("authoritative PIT export requires as_of, feature_rows, and labels")
    targets: dict[str, dict[str, float]] = {}
    maturity: dict[str, list[str]] = {}
    for label in labels:
        origin = str(label.get("origin_session", ""))
        horizon = int(label.get("horizon_sessions", 0))
        mature_at = str(label.get("mature_at", ""))
        value = float(label.get("value", float("nan")))
        if horizon in (1, 5, 21, 63) and mature_at <= as_of and math.isfinite(value):
            targets.setdefault(origin, {})[str(horizon)] = value
            maturity.setdefault(origin, []).append(mature_at)
    available_names = {key for row in features for key in row}
    feature_names = [name for name in _G1_CORE_FEATURES if name in available_names]
    if feature_names != list(_G1_CORE_FEATURES):
        raise ValueError("authoritative PIT export lacks the frozen G1 core feature coordinates")
    rows = []
    for feature in features:
        origin = str(feature.get("origin_session", ""))
        if set(targets.get(origin, {})) != {"1", "5", "21", "63"}:
            continue
        cutoff = str(feature.get("origin_cutoff_at", ""))
        feature_available = str(feature.get("max_available_at", ""))
        if feature.get("pit_pass") is not True or not cutoff or feature_available > cutoff:
            raise ValueError("feature row violates point-in-time available_at semantics")
        available_at = max([feature_available, *maturity[origin]])
        if available_at > as_of:
            continue
        values = []
        for name in feature_names:
            value = feature.get(name)
            values.append(0.0 if value is None else float(value))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("PIT export contains a non-finite feature")
        rows.append({"origin_session": origin, "available_at": available_at,
                     "features": values, "targets": targets[origin]})
    rows.sort(key=lambda row: (row["origin_session"], row["available_at"]))
    return rows


def _execute_family(family: str, train_rows: list[dict[str, Any]],
                    score_rows_by_role: Mapping[str, list[dict[str, Any]]],
                    as_of: str) -> tuple[dict[str, float], dict[str, int], dict[str, Any]]:
    """Fit a frozen family and score its stored predictive distribution."""
    if family == "E1":
        from .e1_quantile_elastic_net import E1Contract, fit_e1_direct_quantile_elastic_net
        contract = E1Contract()
        model = fit_e1_direct_quantile_elastic_net(
            rows=train_rows, as_of=as_of, e0_scale=.02,
            contract=contract,
        )
        def distribution_one(row, horizon):
            predictive = model.predict_corrections(row["features"])[horizon]
            return (
                _quantile_crps(row["targets"][str(horizon)], predictive),
                {"kind": "quantile_grid", "values": predictive},
            )
        coordinates = model.diagnostics["hyperparameters"]
        convergence = {"enforced": True, "method": "L-BFGS-B_success_or_raise"}
    elif family == "E2":
        from .e2_student_t import E2Contract, fit_e2_student_t, _student_t_crps
        contract = E2Contract()
        model = fit_e2_student_t(
            rows=train_rows, as_of=as_of, contract=contract,
        )
        def distribution_one(row, horizon):
            predictive = model.predict(row["features"])[horizon]
            scale = predictive["scale"]
            standardized = np.asarray([
                (row["targets"][str(horizon)] - predictive["location"]) / scale,
            ])
            score = float(_student_t_crps(
                standardized, np.asarray([scale]), predictive["degrees_of_freedom"],
            )[0])
            return score, {"kind": "student_t", **predictive}
        coordinates = {"degrees_of_freedom": list(contract.degrees_of_freedom),
                       "alpha_grid": list(contract.alpha_grid)}
        convergence = {"enforced": True, "method": "L-BFGS-B_success_or_raise"}
    elif family == "E3":
        from .e3_quantile_hgb import E3Contract, fit_e3_quantile_hgb
        contract = E3Contract()
        model = fit_e3_quantile_hgb(
            rows=train_rows, as_of=as_of, contract=contract,
        )
        def distribution_one(row, horizon):
            predictive = model.predict(row["features"])[horizon]
            return (
                _quantile_crps(row["targets"][str(horizon)], predictive),
                {"kind": "quantile_grid", "values": predictive},
            )
        coordinates = model.diagnostics["contract_candidate_coordinates"]
        convergence = {"enforced": True, "method": "deterministic_fixed_iterations"}
    elif family == "E4":
        from .e4_filtered_dlm import E4Contract, fit_e4_filtered_dlm
        contract = E4Contract()
        model = fit_e4_filtered_dlm(rows=train_rows, as_of=as_of, contract=contract)
        residual_scale = {
            horizon: max(float(np.std([
                receipt["actual"] - receipt["forecast"]
                for receipt in model.direct_horizon_receipts
                if receipt["horizon_sessions"] == horizon
            ], ddof=1)), 1e-10) for horizon in contract.horizons
        }
        def distribution_one(row, horizon):
            location = model.predict(row["features"])[horizon]
            scale = residual_scale[horizon]
            return (
                _normal_crps(row["targets"][str(horizon)], location, scale),
                {"kind": "normal", "location": location, "scale": scale},
            )
        coordinates = model.diagnostics["contract_candidate_coordinates"]
        convergence = {"enforced": True, "method": "closed_form_kalman_filter"}
    else:  # pragma: no cover - internal closed family set
        raise ValueError("unknown R4 G1 family")
    scores, counts = {}, {}
    distribution_hasher = sha256()
    for role, rows in score_rows_by_role.items():
        values = []
        for row in rows:
            for horizon in (1, 5, 21, 63):
                score, predictive = distribution_one(row, horizon)
                values.append(score)
                distribution_hasher.update(canonical_json({
                    "family": family,
                    "role": role,
                    "origin_session": row["origin_session"],
                    "horizon": horizon,
                    "predictive_distribution": predictive,
                }))
        if not values or not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise ValueError(f"{family} produced invalid distribution CRPS for {role}")
        scores[role], counts[role] = sum(values) / len(values), len(values)
    return scores, counts, {
        "score": "distribution_crps",
        "frozen_coordinates": True,
        "coordinates": coordinates,
        "optimizer_convergence": convergence,
        "predictive_distribution_hash": distribution_hasher.hexdigest(),
        "score_rows": sum(counts.values()),
    }


def run_g1_screen_from_export(
    export_path: Path, *, e0_crps: float, e0_artifact_sha256: str,
    evaluation_origin_grid_hash: str, generation_hash: str,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute E1-E4 against a credential-free authoritative PostgreSQL export."""
    export = json.loads(Path(export_path).read_text(encoding="utf-8"))
    if (export.get("schema") != "r4_credential_free_pit_export_v1"
            or export.get("source_store") != "authoritative_postgresql"):
        raise ValueError("credential-free authoritative PostgreSQL PIT export is required")
    rows = _training_rows(export)
    plan = export.get("five_role_plan")
    expected_roles = ["train", "selection", "stacking", "calibration", "outer"]
    if (not isinstance(plan, Mapping) or plan.get("schema") != "r4_five_role_origin_plan_v1"
            or plan.get("role_order") != expected_roles
            or plan.get("outer_exposed_during_screen") is not False):
        raise ValueError("authoritative export requires a sealed five-role plan")
    role_origins = plan.get("role_origins", {})
    rows_by_origin = {row["origin_session"]: row for row in rows}
    rows_by_role = {
        role: [rows_by_origin[origin] for origin in role_origins.get(role, [])
               if origin in rows_by_origin]
        for role in expected_roles
    }
    actual_counts = {role: len(role_rows) for role, role_rows in rows_by_role.items()}
    if actual_counts != plan.get("role_counts"):
        raise ValueError("five-role plan counts do not bind complete PIT rows")
    if len(rows_by_role["train"]) < 4:
        raise ValueError("authoritative export has insufficient complete PIT training rows")
    train_rows = rows_by_role["train"]
    score_rows_by_role = {role: rows_by_role[role]
                          for role in ("selection", "stacking", "calibration")}
    candidates = []
    model_score_rows = 0
    families = ["E1", "E2", "E3", "E4"]
    checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir is not None else None
    if checkpoint_dir is not None:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for family in families:
        checkpoint_key = sha256(canonical_json({
            "family": family, "snapshot_hash": export["snapshot_hash"],
            "plan_hash": plan["plan_hash"], "as_of": export["as_of"],
            "implementation": "frozen_coordinates_distribution_crps_v2_receipted",
        })).hexdigest()
        checkpoint = checkpoint_dir / f"{family}-{checkpoint_key}.json" if checkpoint_dir else None
        if checkpoint is not None and checkpoint.exists():
            family_result = json.loads(checkpoint.read_text(encoding="utf-8"))
        else:
            scores, counts, receipt = _execute_family(
                family, train_rows, score_rows_by_role, str(export["as_of"]),
            )
            family_result = {"checkpoint_key": checkpoint_key, "scores": scores,
                             "counts": counts, "receipt": receipt}
            if checkpoint is not None:
                checkpoint.write_bytes(canonical_json(family_result) + b"\n")
        scores, counts, receipt = (family_result["scores"], family_result["counts"],
                                    family_result["receipt"])
        model_score_rows += sum(counts.values())
        candidates.append({
            "candidate_id": family,
            "hypothesis": {"family": family, "mechanism": "direct_horizon_r4"},
            "exposure": {"snapshot_hash": export["snapshot_hash"],
                         "roles": ["train", "selection", "stacking", "calibration"],
                         "horizons": [1, 5, 21, 63]},
            "smoke_crps": scores["selection"], "inner_crps": scores["selection"],
            "robust_inner_crps": scores["stacking"],
            "full_nested_crps": scores["calibration"],
            "score_kind": "distribution_crps", "model_receipt": receipt,
            "checkpoint_key": family_result["checkpoint_key"],
        })
    report = screen_g1_candidates(
        candidates, e0_crps=e0_crps, generation_hash=generation_hash,
    )
    for candidate in report["candidates"]:
        candidate["underperforms_e0"] = candidate["scores"]["full_nested"] >= e0_crps
        if candidate["underperforms_e0"]:
            candidate["weight"] = 0.0
    five_role_receipt = {
        "schema": plan["schema"], "plan_hash": _sha256(plan["plan_hash"], "plan_hash"),
        "role_order": expected_roles, "role_counts": actual_counts,
        "role_hashes": plan["role_hashes"], "outer_exposed_during_screen": False,
        "excluded_count": int(plan["excluded_count"]),
        "interval_overlap_count": int(plan["interval_overlap_count"]),
        "purge_unit": plan["purge_unit"],
        "purge_sessions": int(plan["purge_sessions"]),
        "embargo_sessions": int(plan["embargo_sessions"]),
    }
    score_receipts = [
        {
            "family": candidate["candidate_id"],
            "metric": "crps",
            "predictive_distribution_hash": candidate["model_receipt"][
                "predictive_distribution_hash"
            ],
            "score_rows": int(candidate["model_receipt"]["score_rows"]),
            "checkpoint_key": candidate["checkpoint_key"],
        }
        for candidate in report["candidates"]
    ]
    report.update({
        "candidate_families": families,
        "five_role_validation_proof": True,
        "five_role_receipt": five_role_receipt,
        "score_receipts": score_receipts,
        "source": {
            "r4_snapshot_hash": export["snapshot_hash"],
            "e0_artifact_sha256": _sha256(e0_artifact_sha256, "e0_artifact_sha256"),
            "e0_mean_crps": float(e0_crps),
            "evaluation_origin_grid_hash": _sha256(
                evaluation_origin_grid_hash, "evaluation_origin_grid_hash",
            ),
            "score_metric": "distribution_crps",
            "frozen_candidate_coordinates_preserved": all(
                candidate["model_receipt"].get("frozen_coordinates") is True
                for candidate in report["candidates"]
            ),
            "optimizer_convergence_required": all(
                candidate["model_receipt"].get("optimizer_convergence", {}).get("enforced")
                is True for candidate in report["candidates"]
            ),
            "five_role_receipt": five_role_receipt,
            "model_score_rows": model_score_rows,
            "legacy_precomputed_score_rows_used": 0,
            "outer_rows_used": 0,
            "train_rows": len(train_rows),
            "inner_score_rows": sum(len(value) for value in score_rows_by_role.values()),
        },
    })
    return report
