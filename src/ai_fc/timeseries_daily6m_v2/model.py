"""Generate one paired v2 shadow forecast (three arms) without writing files.

The VARX fits are called through the v1 module attribute
(``ai_fc.timeseries_daily6m.model.select_ridge_varx_v2``) so the two tracks
always share one fitting call path.  The v1 seed, recorded block/lambda and
recorded issuance exogenous values reproduce the v1 joint paths; only when that
reduction identity holds is the run in the primary (identical_inputs) sample.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.timeseries.model import deterministic_seed
from ai_fc.timeseries_daily6m import contracts as v1C
from ai_fc.timeseries_daily6m import model as v1M
from ai_fc.timeseries_v2.contracts import runtime_manifest

from . import kernel as K
from .contracts import (
    ARMS, CONTRACT_ID, Daily6mV2ContractError, FOOTNOTE, MODEL_ID, MODEL_VERSION, PROBABILITY_SPACE, canonical_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
COLUMNS = v1C.ENDOGENOUS_NAMES


def _get(bundle: Any, key: str, default: Any = None) -> Any:
    return bundle.get(key, default) if isinstance(bundle, dict) else getattr(bundle, key, default)


def _path_hash(paths: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(paths, dtype=np.float64).tobytes()).hexdigest()


def _coefficient_gap(fit: Any, recorded: Any) -> float | None:
    """Max |coefficient difference| against the v1 run's recorded fit manifest (diagnostic only)."""
    if not isinstance(recorded, dict) or recorded.get("coefficients") is None:
        return None
    try:
        theirs = np.asarray(recorded["coefficients"], dtype=float)
    except (TypeError, ValueError):
        return None
    mine = np.asarray(fit.coefficients, dtype=float)
    if mine.shape != theirs.shape:
        return None
    gap = float(np.max(np.abs(mine - theirs)))
    return gap if np.isfinite(gap) else None


def _platform_manifest() -> dict[str, Any]:
    """Machine and BLAS build identity (diagnostic only: ulp-level reduction differences across runners)."""
    import platform
    manifest: dict[str, Any] = {"machine": platform.machine(), "system": platform.system(), "processor": platform.processor() or None}
    try:
        blas = (np.show_config(mode="dicts") or {}).get("Build Dependencies", {}).get("blas", {})
        manifest["blas"] = {key: blas.get(key) for key in ("name", "version", "openblas configuration")}
    except Exception:  # noqa: BLE001 - diagnostics must never fail an issuance
        manifest["blas"] = None
    return manifest


def session_close(day: str):
    """Actual XNAS close of ``day`` (early closes included), timezone aware."""
    from datetime import date, timedelta
    import exchange_calendars as xcals
    import pandas as pd
    current = date.fromisoformat(day)
    exchange = xcals.get_calendar("XNAS", start=(current - timedelta(days=7)).isoformat(),
                                  end=(current + timedelta(days=7)).isoformat())
    return exchange.session_close(pd.Timestamp(day)).to_pydatetime()


def generate_v2_forecast(bundle: Any, *, anchor: float, as_of: str, future_dates: list[str], v1_run: dict[str, Any],
                         previous_selection: tuple[int, float] | list | None, constants: dict[str, Any],
                         path_count: int | None = None, root: Path | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    root = REPO_ROOT if root is None else root
    issued = v1M._timestamp(as_of)
    dates = list(_get(bundle, "dates", ()))
    y = np.asarray(_get(bundle, "endogenous"), dtype=float)
    x = np.asarray(_get(bundle, "exogenous"), dtype=float)
    v1_config = v1_run.get("model_config") or {}
    path_count = int(v1_run.get("path_count")) if path_count is None else int(path_count)
    if (len(dates) < v1C.MINIMUM_TRAINING_SESSIONS or dates != sorted(set(dates))
            or y.shape != (len(dates), len(COLUMNS)) or x.shape != (len(dates), len(v1C.EXOGENOUS_NAMES))
            or tuple(_get(bundle, "endogenous_names", ())) != COLUMNS
            or tuple(_get(bundle, "exogenous_names", ())) != v1C.EXOGENOUS_NAMES
            or not np.isfinite(y).all() or not np.isfinite(x).all() or not np.isfinite(anchor) or anchor <= 0
            or path_count < 5 or path_count != int(v1_run.get("path_count", -1))):
        raise Daily6mV2ContractError("v2 needs the complete named v1 feature bundle and the v1 path count")
    if _get(bundle, "issues", ()):
        raise Daily6mV2ContractError("input bundle has unresolved issues")
    origin = str(dates[-1])
    if origin != v1_run.get("anchor_date"):
        raise Daily6mV2ContractError("v2 bundle anchor differs from the paired v1 origin")
    expected_dates, calendar_end, calendar_hash = v1M.future_session_dates(origin)
    if list(future_dates) != expected_dates or list(future_dates) != list(v1_run.get("dates") or []):
        raise Daily6mV2ContractError("future dates must equal the exact v1 six-month XNAS range")
    if issued.timestamp() < session_close(origin).timestamp() + 900:
        raise Daily6mV2ContractError("forecast origin session must be completed before issuance")
    if issued.timestamp() >= session_close(future_dates[0]).timestamp():
        raise Daily6mV2ContractError("first target session has closed — no retroactive v2 issuance")
    lineage = _get(bundle, "lineage", {}) or {}
    v1M._validate_lineage_availability(lineage, issued)
    v1M._validate_registered_captured_tail(lineage, origin)
    recorded = v1_config.get("issuance_exogenous") or {}
    try:
        exog_last = np.array([float(recorded[name]) for name in v1C.EXOGENOUS_NAMES], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise Daily6mV2ContractError("v1 run lacks the recorded issuance exogenous state") from exc
    if not np.isfinite(exog_last).all():
        raise Daily6mV2ContractError("v1 recorded issuance exogenous state is not finite")
    bundle_exog = _get(bundle, "issuance_exogenous")
    bundle_exog = None if bundle_exog is None else [float(value) for value in np.asarray(bundle_exog, dtype=float)]

    expanding = v1M.select_ridge_varx_v2(y, x, endog_names=COLUMNS, exog_names=v1C.EXOGENOUS_NAMES)
    rolling = v1M.select_ridge_varx_v2(y, x, endog_names=COLUMNS, exog_names=v1C.EXOGENOUS_NAMES,
                                       train_start=max(0, len(dates) - 2520))
    seed = deterministic_seed(v1C.MODEL_ID, v1C.MODEL_VERSION, origin)
    runtime = {**runtime_manifest(), "exchange_calendars": importlib.metadata.version("exchange-calendars")}
    v1_block, v1_lambda = int(v1_config.get("block_length")), float(v1_config.get("ewma_lambda"))
    common = dict(weights=(0.5, 0.5), endog_history=y, exog_last=exog_last, anchor=float(anchor),
                  path_count=path_count, horizon=len(future_dates), seed=seed)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        reduced = K.simulate_paths_v2_arms((expanding, rolling), block_length=v1_block, ewma_lambda=v1_lambda,
                                           persistence=np.ones(len(COLUMNS)), anchor_rule="slow_ewma_0.996",
                                           arms=("main",), fresh=False, **common)
    reduced_paths = reduced["main"]["index_paths"]
    resimulated_hash = _path_hash(reduced_paths)
    v1_code_hash_at_issue = v1C.model_code_hash(root)
    path_equal = resimulated_hash == v1_run.get("path_hash")
    code_equal = v1_code_hash_at_issue == v1_run.get("model_code_hash")
    pair_status = "identical_inputs" if path_equal and code_equal else "inputs_differ"
    reason = None if pair_status == "identical_inputs" else ("path_hash" if not path_equal else "v1_code_hash")
    v1_grid = None
    unrounded = K.quantile_grid_unrounded(reduced_paths, anchor=anchor)
    expected = np.array([[np.log(float(record["band_index"][name]) / float(anchor)) for record in v1_run["records"]]
                         for name in K.BAND_NAMES])
    shape_equal = expected.shape == unrounded[list(K.BAND_ROWS)].shape
    # diagnostics only (review N1): how far an inputs_differ reconstruction is from v1 — never part of the pass rule
    magnitude = {
        "max_abs_log_band_diff": float(np.max(np.abs(unrounded[list(K.BAND_ROWS)] - expected))) if shape_equal else None,
        "max_abs_coefficient_diff": {name: _coefficient_gap(fit, v1_config.get(key))
                                     for name, key, fit in (("expanding", "expanding_fit", expanding), ("rolling", "rolling_fit", rolling))},
        "platform": _platform_manifest(),
    }
    if pair_status == "identical_inputs":
        if not shape_equal or np.max(np.abs(unrounded[list(K.BAND_ROWS)] - expected)) > 1e-12:
            raise Daily6mV2ContractError("reconstructed v1 grid does not reproduce the v1 band_index — contract violation")
        v1_grid = np.round(unrounded, 10).tolist()
    del reduced, reduced_paths, unrounded

    residuals = np.vstack((expanding.residuals, rolling.residuals))
    selection = K.select_distribution_crn(residuals, previous=previous_selection, constants=constants)
    block, decay = int(selection["chosen"][0]), float(selection["chosen"][1])
    persistence = np.array([float(constants["persistence_by_column"][name]) for name in COLUMNS])
    long_run_rule = constants["long_run_rule"]["registered"]
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        simulated = K.simulate_paths_v2_arms((expanding, rolling), block_length=block, ewma_lambda=decay,
                                             persistence=persistence, anchor_rule=long_run_rule, arms=ARMS, fresh=True, **common)
    arms: dict[str, Any] = {}
    paths: dict[str, np.ndarray] = {}
    for arm in ARMS:
        index = np.asarray(simulated[arm]["index_paths"], dtype=float)
        if not np.isfinite(simulated[arm]["log_returns"]).all():
            raise Daily6mV2ContractError("v2 simulation produced non-finite returns (no clipping)")
        records = K.summarize_compact(index, anchor=anchor, future_dates=list(future_dates))
        grid = K.quantile_grid(index, anchor=anchor)
        arms[arm] = {"path_hash": _path_hash(index), "records": records, "quantile_grid": grid.tolist()}
        paths[arm] = index
    diagnostics = simulated["diagnostics"]
    v1_records = [{"date": record["date"], "band_index": dict(record["band_index"]),
                   "probability_up_from_previous": float(record["probability_up_from_previous"])}
                  for record in v1_run["records"]]
    payload = {
        "schema_version": 1, "model_id": MODEL_ID, "model_version": MODEL_VERSION, "contract_id": CONTRACT_ID,
        "issued_at": issued.isoformat(), "origin_session": origin, "anchor_date": origin,
        "anchor": {"series_id": "NASDAQCOM", "date": origin, "value": float(anchor),
                   "available_at": (v1_run.get("anchor") or {}).get("available_at")},
        "dates": list(future_dates), "calendar_end_date": calendar_end, "calendar_hash": calendar_hash,
        "horizon_sessions": len(future_dates), "path_count": path_count, "probability_unit": "fraction",
        "probability_space": PROBABILITY_SPACE, "status": "shadow_research", "numbers_visible": False,
        "parent": {"v1_run_id": v1_run["run_id"], "v1_run_content_hash": v1_run["content_hash"],
                   "v1_model_code_hash": v1_run.get("model_code_hash"), "v1_model_code_hash_at_issue": v1_code_hash_at_issue,
                   "v1_contract_hash": v1_run.get("contract_hash")},
        "pair_status": pair_status, "inputs_differ_reason": reason,
        "reduction_identity": {"v1_path_hash": v1_run.get("path_hash"), "resimulated_path_hash": resimulated_hash,
                               "equal": path_equal, "v1_code_hash_equal": code_equal, "seed": seed,
                               "block_length": v1_block, "ewma_lambda": v1_lambda,
                               # diagnostics only (not part of the pass rule): which input differed
                               "fit_residual_hash_equal": {
                                   name: (None if not isinstance(v1_config.get(key), dict) else
                                          fit.manifest()["residual_hash"] == v1_config[key].get("residual_hash"))
                                   for name, key, fit in (("expanding", "expanding_fit", expanding), ("rolling", "rolling_fit", rolling))},
                               "v1_runtime": v1_config.get("runtime"), "runtime": runtime,
                               "magnitude": magnitude},
        "projection_exogenous": {"source": "v1_run_model_config", "values": exog_last.tolist()},
        "v2_bundle_issuance_exogenous": bundle_exog,
        "selection": selection,
        "variance": {"fresh_over_lagged_sd": {"expanding": None if diagnostics[0] is None else diagnostics[0]["fresh_over_lagged_sd"],
                                              "rolling": None if diagnostics[1] is None else diagnostics[1]["fresh_over_lagged_sd"]},
                     "long_run_over_fresh": {"expanding": None if diagnostics[0] is None else diagnostics[0]["long_run_over_fresh"],
                                             "rolling": None if diagnostics[1] is None else diagnostics[1]["long_run_over_fresh"]},
                     "persistence": persistence.tolist(), "long_run_rule": long_run_rule},
        "quantile_levels": list(K.GRID_LEVELS),
        "arms": arms,
        "v1_reference": {"run_id": v1_run["run_id"], "run_content_hash": v1_run["content_hash"],
                         "path_hash": v1_run.get("path_hash"), "model_code_hash": v1_run.get("model_code_hash"),
                         "contract_hash": v1_run.get("contract_hash"), "block_length": v1_block, "ewma_lambda": v1_lambda,
                         "issuance_exogenous": exog_last.tolist(), "quantile_grid": v1_grid, "records": v1_records},
        "evidence": {"predictive_validation": "not_established", "research_only": True},
        "footnote": FOOTNOTE,
    }
    payload["content_hash"] = canonical_hash(payload)
    return payload, paths
