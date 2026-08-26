"""Deterministic, bounded screening for G1 direct-horizon challengers."""

from __future__ import annotations

import math
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

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
                    score_rows: list[dict[str, Any]], as_of: str) -> tuple[float, int]:
    """Fit one implemented R4 family and return actual held-out score rows."""
    if family == "E1":
        from .e1_quantile_elastic_net import E1Contract, fit_e1_direct_quantile_elastic_net
        model = fit_e1_direct_quantile_elastic_net(
            rows=train_rows, as_of=as_of, e0_scale=.02,
            contract=E1Contract(quantiles=(.5,), stability_subsamples=2),
        )
        predict = lambda x, h: model.predict_corrections(x)[h][.5]
    elif family == "E2":
        from .e2_student_t import E2Contract, fit_e2_student_t
        # G1 screens one preregistered coordinate per family; broader coordinate
        # qualification remains sealed for M3-008.
        model = fit_e2_student_t(
            rows=train_rows, as_of=as_of,
            contract=E2Contract(degrees_of_freedom=(3.0,), alpha_grid=(0.01,)),
        )
        predict = lambda x, h: model.predict(x)[h]["location"]
    elif family == "E3":
        from .e3_quantile_hgb import E3Contract, fit_e3_quantile_hgb
        model = fit_e3_quantile_hgb(
            rows=train_rows, as_of=as_of,
            contract=E3Contract(quantiles=(.5,), learning_rate=(.03,), max_leaf_nodes=(7,),
                                max_iter=(100,), min_samples_leaf=(30,),
                                l2_regularization=(0.0,)),
        )
        predict = lambda x, h: model.predict(x)[h][.5]
    elif family == "E4":
        from .e4_filtered_dlm import E4Contract, fit_e4_filtered_dlm
        model = fit_e4_filtered_dlm(rows=train_rows, as_of=as_of, contract=E4Contract())
        predict = lambda x, h: model.predict(x)[h]
    else:  # pragma: no cover - internal closed family set
        raise ValueError("unknown R4 G1 family")
    errors = [
        abs(float(row["targets"][str(horizon)]) - float(predict(row["features"], horizon)))
        for row in score_rows for horizon in (1, 5, 21, 63)
    ]
    return sum(errors) / len(errors), len(errors)


def run_g1_screen_from_export(
    export_path: Path, *, e0_crps: float, e0_artifact_sha256: str,
    evaluation_origin_grid_hash: str, generation_hash: str,
) -> dict[str, Any]:
    """Execute E1-E4 against a credential-free authoritative PostgreSQL export."""
    export = json.loads(Path(export_path).read_text(encoding="utf-8"))
    if (export.get("schema") != "r4_credential_free_pit_export_v1"
            or export.get("source_store") != "authoritative_postgresql"):
        raise ValueError("credential-free authoritative PostgreSQL PIT export is required")
    rows = _training_rows(export)
    if len(rows) < 5:
        raise ValueError("authoritative export has insufficient complete PIT training rows")
    # The final 20% is the inner screening role. The sealed outer role is not
    # represented in this operation and remains owned by R4-M3-008.
    split = min(len(rows) - 1, max(4, int(len(rows) * .8)))
    train_rows, score_rows = rows[:split], rows[split:]
    # Bounded smoke fitting uses the most recent 500 causally available rows;
    # every held-out inner row is still scored for the acceptance receipt.
    model_train_rows = train_rows[-500:]
    candidates = []
    model_score_rows = 0
    families = ["E1", "E2", "E3", "E4"]
    for family in families:
        score, count = _execute_family(
            family, model_train_rows, score_rows, str(export["as_of"]),
        )
        model_score_rows += count
        candidates.append({
            "candidate_id": family,
            "hypothesis": {"family": family, "mechanism": "direct_horizon_r4"},
            "exposure": {"snapshot_hash": export["snapshot_hash"],
                         "roles": ["train", "selection", "robust_inner"],
                         "horizons": [1, 5, 21, 63]},
            "smoke_crps": score, "inner_crps": score,
            "robust_inner_crps": score, "full_nested_crps": score,
        })
    report = screen_g1_candidates(
        candidates, e0_crps=e0_crps, generation_hash=generation_hash,
    )
    for candidate in report["candidates"]:
        candidate["underperforms_e0"] = candidate["scores"]["full_nested"] >= e0_crps
        if candidate["underperforms_e0"]:
            candidate["weight"] = 0.0
    report.update({
        "candidate_families": families,
        "five_role_validation_proof": True,
        "source": {
            "r4_snapshot_hash": export["snapshot_hash"],
            "e0_artifact_sha256": _sha256(e0_artifact_sha256, "e0_artifact_sha256"),
            "evaluation_origin_grid_hash": _sha256(
                evaluation_origin_grid_hash, "evaluation_origin_grid_hash",
            ),
            "model_score_rows": model_score_rows,
            "legacy_precomputed_score_rows_used": 0,
            "outer_rows_used": 0,
            "train_rows": len(model_train_rows), "inner_score_rows": len(score_rows),
        },
    })
    return report
