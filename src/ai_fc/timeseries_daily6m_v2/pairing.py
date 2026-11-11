"""r3 pair eligibility rule for the daily6m v2 shadow (pre-outcome amendment, 2026-11-12).

The first main run (daily6m-v2-9cc54ec9…) reproduced v1 only to ulp level (coefficients 4.2e-16 / 7.5e-16,
log bands 8.0e-16) because OpenBLAS picks a CPU-specific kernel on each runner, so bit-identical paths are
structurally rare.  ``pair_status`` stays as recorded (identical_inputs | inputs_differ); the primary-sample
admission is a separate, rule-derived ``pair_eligibility`` computed from recorded run fields only.

This file is part of the gating ``model_code_hash`` (contracts.NUMERICAL_CODE_PATHS): it decides whether a
run stores the reconstructed v1 grid (the input of the primary metric v1_crps39) and which runs enter the
primary sample, so any edit here — stricter or more lenient — changes the run identity and needs a new
contract revision.  Thresholds and the criteria list are additionally pinned by the contract YAML.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

PAIR_RULE_REVISION = "r3"
PAIR_TOLERANCE = 1e-12
PRIMARY_ELIGIBILITY = ("identical_inputs", "tolerance_equivalent")
EQUIVALENCE_CRITERIA = (
    "path_hash_only", "v1_code_hash_equal", "runtime_equal", "selection_reused", "projection_exogenous_from_v1",
    "coefficients_within_tolerance", "bands_within_tolerance", "fit_structure_equal", "anchor_equal",
    "factor_rows_equal_excluding_materialization", "market_rows_same_observations",
)
GRID_CRITERION = "v1_reference_grid_recorded"
FIT_STRUCTURE_KEYS = ("lag", "alpha", "endogenous", "exogenous", "predictors", "residual_count", "train_start", "train_end")
MARKET_OBSERVATION_KEYS = ("session", "series_id", "role", "observation_time", "carried")
FACTOR_VOLATILE_KEYS = ("cache_materialized_at",)   # checkout mtime of the DFM cache file — differs per CI job


def _finite_le(value: Any, bound: float) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            and abs(float(value)) <= bound)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def fit_structure_comparison(mine: dict[str, Any], recorded: Any) -> dict[str, Any]:
    """Discrete fit identity (lag, alpha, names, window) + robust-scaler gap against a v1 recorded fit manifest.

    The scaler (median/IQR per predictor) is an order-statistic function of the training inputs that does
    not go through BLAS, so together with the coefficient gap it fingerprints the input matrices.
    """
    if not isinstance(recorded, dict):
        return {"equal": False, "differing_keys": ["not_recorded"], "max_abs_scaler_diff": None}
    mine, recorded = _jsonable(mine), _jsonable(recorded)
    differing = [key for key in FIT_STRUCTURE_KEYS if mine.get(key) != recorded.get(key)]
    gap = None
    try:
        pairs = [(np.asarray(mine["scaler"][name], dtype=float), np.asarray(recorded["scaler"][name], dtype=float))
                 for name in ("median", "iqr")]
        if all(a.shape == b.shape for a, b in pairs):
            gap = float(max(np.max(np.abs(a - b)) if a.size else 0.0 for a, b in pairs))
    except (KeyError, TypeError, ValueError):
        gap = None
    if gap is None or not math.isfinite(gap):
        differing.append("scaler")
        gap = None
    elif gap > PAIR_TOLERANCE:
        differing.append("scaler")
    return {"equal": not differing, "differing_keys": differing, "max_abs_scaler_diff": gap}


def lineage_comparison(mine: Any, recorded: Any) -> dict[str, Any]:
    """v2 bundle lineage vs the v1 run's recorded source_lineage.

    Criteria: the same observation chosen per (session, series, role) and the same factor content (only the
    checkout-mtime field dropped).  Capture metadata (source swap captured->native, retrieved_at, receipts)
    is counted as a diagnostic only — it changes provenance, not values.
    """
    empty = {"recorded": False, "market_rows_same_observations": False, "factor_rows_equal_excluding_materialization": False,
             "market_rows": None, "factor_rows": None, "market_rows_metadata_differ": None, "metadata_examples": []}
    if not isinstance(mine, dict) or not isinstance(recorded, dict):
        return empty
    mine_market, their_market = _jsonable(mine.get("market_rows") or []), _jsonable(recorded.get("market_rows") or [])
    mine_factor, their_factor = _jsonable(mine.get("factor_rows") or []), _jsonable(recorded.get("factor_rows") or [])
    if not mine_market or not their_market or not mine_factor or not their_factor:
        return empty

    def observations(rows):
        return [{key: row.get(key) for key in MARKET_OBSERVATION_KEYS} for row in rows]

    def stripped(rows):
        return [{key: value for key, value in row.items() if key not in FACTOR_VOLATILE_KEYS} for row in rows]

    examples, differ = [], 0
    if len(mine_market) == len(their_market):
        for a, b in zip(their_market, mine_market):
            if a != b:
                differ += 1
                if len(examples) < 10:
                    examples.append({"session": a.get("session"), "series_id": a.get("series_id"),
                                     "v1": {"source_id": a.get("source_id"), "data_grade": a.get("data_grade")},
                                     "v2": {"source_id": b.get("source_id"), "data_grade": b.get("data_grade")}})
    return {"recorded": True, "market_rows_same_observations": observations(mine_market) == observations(their_market),
            "factor_rows_equal_excluding_materialization": stripped(mine_factor) == stripped(their_factor),
            "market_rows": [len(their_market), len(mine_market)], "factor_rows": [len(their_factor), len(mine_factor)],
            "market_rows_metadata_differ": differ if len(mine_market) == len(their_market) else None,
            "metadata_examples": examples}


def equivalence_criteria(run: dict[str, Any]) -> dict[str, bool]:
    """r3 evidence criteria from recorded run fields only (missing evidence = False, never recomputed)."""
    identity = run.get("reduction_identity") or {}
    magnitude = identity.get("magnitude") or {}
    coefficients = magnitude.get("max_abs_coefficient_diff") or {}
    evidence = identity.get("input_evidence") or {}
    structure = evidence.get("fit_structure") or {}
    lineage = evidence.get("lineage") or {}
    reference = run.get("v1_reference") or {}
    projection = run.get("projection_exogenous") or {}
    runtime, v1_runtime = identity.get("runtime"), identity.get("v1_runtime")
    return {
        "path_hash_only": run.get("pair_status") == "inputs_differ" and run.get("inputs_differ_reason") == "path_hash",
        "v1_code_hash_equal": identity.get("v1_code_hash_equal") is True,
        "runtime_equal": isinstance(runtime, dict) and bool(runtime) and runtime == v1_runtime,
        "selection_reused": (identity.get("block_length") is not None and identity.get("block_length") == reference.get("block_length")
                             and identity.get("ewma_lambda") is not None and identity.get("ewma_lambda") == reference.get("ewma_lambda")),
        "projection_exogenous_from_v1": (projection.get("source") == "v1_run_model_config" and projection.get("values") is not None
                                         and projection.get("values") == reference.get("issuance_exogenous")),
        "coefficients_within_tolerance": all(_finite_le(coefficients.get(name), PAIR_TOLERANCE) for name in ("expanding", "rolling")),
        "bands_within_tolerance": _finite_le(magnitude.get("max_abs_log_band_diff"), PAIR_TOLERANCE),
        "fit_structure_equal": all((structure.get(name) or {}).get("equal") is True for name in ("expanding", "rolling")),
        "anchor_equal": evidence.get("anchor_equal") is True,
        "factor_rows_equal_excluding_materialization": lineage.get("factor_rows_equal_excluding_materialization") is True,
        "market_rows_same_observations": lineage.get("market_rows_same_observations") is True,
    }


def classify_pair(run: dict[str, Any]) -> dict[str, Any]:
    """The r3 pair_eligibility block for one run (deterministic in its recorded fields)."""
    if run.get("pair_status") == "identical_inputs":
        return {"rule": PAIR_RULE_REVISION, "status": "identical_inputs", "tolerance_abs": PAIR_TOLERANCE, "criteria": None, "failed": []}
    criteria = equivalence_criteria(run)
    criteria[GRID_CRITERION] = (run.get("v1_reference") or {}).get("quantile_grid") is not None
    failed = [name for name, passed in criteria.items() if not passed]
    return {"rule": PAIR_RULE_REVISION, "status": "excluded" if failed else "tolerance_equivalent",
            "tolerance_abs": PAIR_TOLERANCE, "criteria": criteria, "failed": failed}


def ledger_pair_eligibility(row: dict[str, Any]) -> str:
    """Eligibility of a forecast or resolution ledger row; rows from r2 runs (no field) keep their r2 meaning."""
    value = row.get("pair_eligibility")
    if value is not None:
        return value
    return "identical_inputs" if row.get("pair_status") == "identical_inputs" else "excluded"
