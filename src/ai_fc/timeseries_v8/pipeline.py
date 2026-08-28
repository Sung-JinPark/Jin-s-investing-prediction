"""V8 development pipeline: 2019-blind candidate evaluation and verification.

Only development verbs exist here.  There is deliberately no sealed
evaluation entry point in the V8 scaffold — the single 2019+ disclosure is a
separate, user-approved step that will be added only after the dev-gate
proxy is green and the contract is frozen (`automatic_sealed_disclosure`
is a contract prohibition).
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.scenario_v5.contracts import compare_protected_hashes, protected_hashes
from ai_fc.timeseries.ledger import read_facts
from ai_fc.timeseries_v2.contracts import load_contract_v2, require_dfm_runtime
from ai_fc.timeseries_v2.features import CandidateFeatureBundle, assemble_candidate_bundle
from ai_fc.timeseries_v2.pipeline import _rows_from_json, _rows_to_json

from .artifact import (
    append_experiment,
    append_holdout_scoring,
    read_experiments,
    read_holdout_scorings,
)
from .backtest import (
    dev_gate_proxy_report,
    paired_differences_vs_best,
    walk_forward_dev_backtest_v8,
)
from .contracts import (
    DEVELOPMENT_TRUNCATION_AFTER,
    RUNS_RELATIVE,
    TimeSeriesV8ContractError,
    assert_development_cutoff,
    canonical_hash,
    frozen_hash,
    load_contract_v8,
    model_code_hash,
    verify_v2_benchmark,
)
from .model import DistributionConfigV8, experiment_id


class TimeSeriesV8PipelineError(RuntimeError):
    """A V8 development gate failed closed."""


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_config_from_grids(
    contract: dict[str, Any], overrides: dict[str, Any] | None = None,
) -> DistributionConfigV8:
    """Build a config point, rejecting anything outside the preregistered grids."""
    grids = contract["research_grids"]
    overrides = dict(overrides or {})

    phi = overrides.pop("phi", "identity")
    phi_candidates = grids["B1_volatility_term_structure"]["phi_candidates"]
    if phi in ("identity", None):
        phi_value: float | str | None = None
    elif phi in phi_candidates or (isinstance(phi, (int, float)) and float(phi) in [
        float(item) for item in phi_candidates if isinstance(item, (int, float))
    ]):
        phi_value = phi if phi == "fitted_ar1" else float(phi)
    else:
        raise TimeSeriesV8ContractError(f"phi {phi!r} is not preregistered")

    window = int(overrides.pop("unconditional_window_sessions", 2520))
    if window not in [int(item) for item in grids["B1_volatility_term_structure"]["unconditional_window_sessions"]]:
        raise TimeSeriesV8ContractError(f"unconditional window {window} is not preregistered")

    omega_grid = grids["B2_bounded_location_anchor"]["omega_by_horizon"]
    omega_overrides = {int(key): float(value) for key, value in dict(overrides.pop("omega_by_horizon", {})).items()}
    omega: dict[int, float] = {}
    for horizon in (1, 5, 21, 63):
        allowed = [float(item) for item in omega_grid[f"h{horizon}"]]
        value = float(omega_overrides.get(horizon, 0.0))
        if value not in allowed:
            raise TimeSeriesV8ContractError(f"omega[h{horizon}]={value} is not preregistered")
        omega[horizon] = value

    sigma_cap = float(overrides.pop("sigma_cap", 0.25))
    if sigma_cap not in [float(item) for item in grids["B2_bounded_location_anchor"]["sigma_cap_candidates"]]:
        raise TimeSeriesV8ContractError(f"sigma_cap {sigma_cap} is not preregistered")

    mu_window = overrides.pop("mu_hat_window_sessions", "expanding")
    if mu_window in ("expanding", None):
        mu_window_value: int | None = None
    elif int(mu_window) in [
        int(item) for item in grids["B2_bounded_location_anchor"]["mu_hat_window"]
        if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
    ]:
        mu_window_value = int(mu_window)
    else:
        raise TimeSeriesV8ContractError(f"mu_hat window {mu_window!r} is not preregistered")

    blend_candidates = [float(item) for item in grids["B3_baseline_convex_blend"]["weight_by_horizon_candidates"]]
    blend_overrides = {int(key): float(value) for key, value in dict(overrides.pop("blend_weight_by_horizon", {})).items()}
    blend: dict[int, float] = {}
    for horizon in (1, 5, 21, 63):
        value = float(blend_overrides.get(horizon, 1.0))
        if value not in blend_candidates:
            raise TimeSeriesV8ContractError(f"blend weight[h{horizon}]={value} is not preregistered")
        blend[horizon] = value

    recal = overrides.pop("pit_recalibration_shrinkage", None)
    if recal is not None:
        allowed_shrinkage = [
            float(item) for item in grids["B4_pit_recalibration"]["shrinkage_to_identity"]
        ]
        if float(recal) not in allowed_shrinkage:
            raise TimeSeriesV8ContractError(
                f"pit recalibration shrinkage {recal} is not preregistered"
            )
        recal = float(recal)

    fhs_grid = grids["B5_fhs_long_horizon"]
    fhs_horizons = tuple(int(h) for h in overrides.pop("fhs_horizons", ()))
    if fhs_horizons:
        if str(fhs_grid.get("status", "")).startswith("reserved"):
            raise TimeSeriesV8ContractError("B5 is reserved and has not been activated")
        allowed_horizons = {int(h) for h in fhs_grid["horizons"]}
        if not set(fhs_horizons).issubset(allowed_horizons):
            raise TimeSeriesV8ContractError(f"FHS horizons {fhs_horizons} are not preregistered")
    fhs_vol = str(overrides.pop("fhs_vol_projection", "current_ewma"))
    if fhs_vol not in [str(item) for item in fhs_grid["vol_projection"]]:
        raise TimeSeriesV8ContractError(f"FHS vol projection {fhs_vol!r} is not preregistered")
    fhs_tilt = float(overrides.pop("fhs_tilt_omega", 0.0))
    if fhs_tilt not in [float(item) for item in fhs_grid["tilt_omega"]]:
        raise TimeSeriesV8ContractError(f"FHS tilt omega {fhs_tilt} is not preregistered")
    fhs_cap = float(overrides.pop("fhs_tilt_cap_sigma", 0.25))
    if fhs_cap not in [float(item) for item in fhs_grid["tilt_cap_sigma"]]:
        raise TimeSeriesV8ContractError(f"FHS tilt cap {fhs_cap} is not preregistered")

    if overrides:
        raise TimeSeriesV8ContractError(f"unknown config keys: {sorted(overrides)}")
    return DistributionConfigV8(
        phi=phi_value,
        unconditional_window_sessions=window,
        omega_by_horizon=omega,
        sigma_cap=sigma_cap,
        mu_hat_window_sessions=mu_window_value,
        blend_weight_by_horizon=blend,
        pit_recalibration_shrinkage=recal,
        fhs_horizons=fhs_horizons,
        fhs_vol_projection=fhs_vol,
        fhs_tilt_omega=fhs_tilt,
        fhs_tilt_cap_sigma=fhs_cap,
    )


def _development_bundle(root: Path, contract_v8: dict[str, Any]) -> CandidateFeatureBundle:
    """Assemble the read-only V2 C1 bundle, structurally truncated for development.

    The market archive stores capture-time availability (`captured_forward`),
    so 2019-blindness is enforced the same way V2's own sealed development
    selection enforced it: by truncating the assembled session axis at the
    registered truncation date.  Factor states stay PIT because each session
    links only to DFM caches with cutoffs at or before that session.
    """
    if contract_v8["data_policy"].get("feature_bundle") != "v2_candidate_C1_readonly":
        raise TimeSeriesV8ContractError("V8 feature bundle registration drifted")
    contract_v2 = load_contract_v2(root)
    facts = read_facts(root)
    cutoff_day = assert_development_cutoff(DEVELOPMENT_TRUNCATION_AFTER)
    assembly_cutoff = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundle = assemble_candidate_bundle(
        root, contract=contract_v2, macro_facts=facts,
        candidate_id="C1", knowledge_cutoff=assembly_cutoff,
    )
    # The V2 completeness flag spans the full range up to the assembly cutoff;
    # V8 only needs the development span, so tolerate exactly that flag and
    # enforce a development-window completeness check of its own below.
    tolerated = {"dfm_origin_cache_incomplete"}
    blocking = [item for item in bundle.missing_features if item not in tolerated]
    if blocking or not bundle.dates:
        raise TimeSeriesV8PipelineError(
            f"V2 C1 bundle unavailable: {', '.join(blocking) or 'insufficient sessions'}"
        )
    from ai_fc.timeseries_v2.contracts import frozen_hash as frozen_hash_v2
    from ai_fc.timeseries_v2.dfm_cache import macro_release_cutoffs, read_dfm_manifest

    expected = set(macro_release_cutoffs(
        facts, start="2007-01-01", end=f"{cutoff_day}T23:59:59+00:00",
    ))
    ready = {
        str(row["cutoff"]) for row in read_dfm_manifest(root)
        if row.get("contract_hash") == frozen_hash_v2(contract_v2)
        and row.get("status") == "ready"
    }
    missing_cutoffs = sorted(expected - ready)
    if not expected or missing_cutoffs:
        raise TimeSeriesV8PipelineError(
            "development-window DFM cache incomplete: "
            f"{len(missing_cutoffs)} cutoff(s) missing"
        )
    stop = next(
        (index for index, day in enumerate(bundle.dates) if day > cutoff_day),
        len(bundle.dates),
    )
    if not np.isfinite(bundle.exogenous[:stop]).all():
        raise TimeSeriesV8PipelineError("development-window factor states contain gaps")
    return CandidateFeatureBundle(
        candidate_id=bundle.candidate_id, status=bundle.status,
        dates=bundle.dates[:stop], endogenous=bundle.endogenous[:stop],
        endogenous_names=bundle.endogenous_names, exogenous=bundle.exogenous[:stop],
        exogenous_names=bundle.exogenous_names, data_grades=bundle.data_grades,
        missing_features=bundle.missing_features, dfm_cache_ids=bundle.dfm_cache_ids,
        transform_manifest=bundle.transform_manifest,
        dfm_cache_complete=bundle.dfm_cache_complete,
    )


def dev_backtest_timeseries_v8(
    root: Path,
    *,
    config_overrides: dict[str, Any] | None = None,
    experiment_label: str = "",
    window_role: str = "design",
    parent_experiment_id: str | None = None,
    knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    if window_role not in ("design", "holdout"):
        raise TimeSeriesV8PipelineError("window role must be design or holdout")
    protected_before = protected_hashes(root)
    contract = load_contract_v8(root)
    verify_v2_benchmark(root, contract)
    require_dfm_runtime()
    protocol = contract["development_protocol"]
    experiments = read_experiments(root)
    config = build_config_from_grids(contract, config_overrides)
    code_hash = model_code_hash(root)
    bundle = _development_bundle(root, contract)
    bundle_hash = canonical_hash({
        "dates": bundle.dates,
        "endogenous": np.ascontiguousarray(bundle.endogenous).tobytes().hex(),
        "exogenous": np.ascontiguousarray(bundle.exogenous).tobytes().hex(),
    })
    identity = experiment_id(config, bundle_hash=bundle_hash, code_hash=code_hash)
    windows = contract["model"]["windows"]
    if window_role == "design":
        if len(experiments) >= int(protocol["maximum_development_evaluations"]):
            raise TimeSeriesV8PipelineError(
                "preregistered development evaluation budget is exhausted"
            )
        if any(row["experiment_id"] == identity for row in experiments):
            prior = next(row for row in experiments if row["experiment_id"] == identity)
            return prior
        outer_start, outer_end = windows["design"]
        path_count = int(contract["model"]["distribution"]["development_path_count"])
    else:
        holdouts = read_holdout_scorings(root)
        if any(row["experiment_id"] == identity for row in holdouts):
            raise TimeSeriesV8PipelineError("this finalist already consumed its holdout scoring")
        distinct = {row["experiment_id"] for row in holdouts}
        if len(distinct) >= int(protocol["holdout_maximum_finalists"]):
            raise TimeSeriesV8PipelineError("holdout finalist budget is exhausted")
        # The holdout run evaluates the full development span so the ensemble
        # history is warm, but only holdout-window origins are reported.
        outer_start = windows["development"][0]
        outer_end = windows["holdout"][1]
        path_count = int(contract["model"]["distribution"]["sealed_path_count"])
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    scores, summary = walk_forward_dev_backtest_v8(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        config=config,
        outer_start=outer_start,
        outer_end=outer_end,
        path_count=path_count,
        pit_min_matured=int(
            contract["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]
        ),
    )
    if window_role == "holdout":
        holdout_start, holdout_end = windows["holdout"]
        reported_scores = [row for row in scores if holdout_start <= row.date <= holdout_end]
    else:
        reported_scores = scores
    paired = paired_differences_vs_best(reported_scores)
    proxy = dev_gate_proxy_report(
        summary if window_role == "design" else _resummarize(reported_scores),
        paired, proxy=contract["dev_gate_proxy"], window_role=window_role,
    )
    protected_after = protected_hashes(root)
    protected_comparison = compare_protected_hashes(protected_before, protected_after)
    if not protected_comparison["ok"]:
        raise TimeSeriesV8PipelineError(
            f"protected path changed during V8 development run: {protected_comparison}"
        )
    horizon_metrics = {
        key: {
            metric: value[metric]
            for metric in ("origins", "crps", "best_baseline", "best_baseline_crps",
                           "crps_improvement_vs_best", "coverage_p10_p90", "coverage_p25_p75")
        }
        for key, value in (summary.get("horizons") or {}).items()
    }
    ledger_row = {
        "schema_version": 1,
        "experiment_id": identity,
        "experiment_label": experiment_label,
        "parent_experiment_id": parent_experiment_id,
        "window_role": window_role,
        "window": {"outer_start": outer_start, "outer_end": outer_end},
        "knowledge_cutoff": cutoff,
        "model_id": contract["model_id"],
        "model_version": int(contract["model_version"]),
        "contract_hash": frozen_hash(contract),
        "model_code_hash": code_hash,
        "bundle_hash": bundle_hash,
        "config": config.as_manifest(),
        "path_count": path_count,
        "horizons": horizon_metrics,
        "paired_long_horizon": {
            key: paired[key] for key in ("origin_count", "mean", "ci90", "best_baselines")
        },
        "cramer_distance_mean": summary.get("cramer_distance_mean"),
        "gfc_regime_coverage": (summary.get("regime_coverage") or {}).get(
            "great_financial_crisis_2008"
        ),
        "proxy": proxy,
    }
    if window_role == "design":
        append_experiment(root, ledger_row)
    else:
        append_holdout_scoring(root, ledger_row)
    run_payload = {
        **ledger_row,
        "summary": summary,
        "paired_differences": paired["differences"],
        "scores": _rows_to_json(reported_scores),
    }
    run_payload["content_hash"] = canonical_hash(run_payload)
    _atomic_json(root / RUNS_RELATIVE / f"dev_{identity}.json", run_payload)
    return run_payload


def _resummarize(rows: list[Any]) -> dict[str, Any]:
    from ai_fc.timeseries_v2.backtest import summarize_backtest_v2

    return summarize_backtest_v2(list(rows), minimum_origins=1)


def load_dev_run(root: Path, identity: str) -> dict[str, Any]:
    path = root / RUNS_RELATIVE / f"dev_{identity}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = canonical_hash({key: value for key, value in payload.items() if key != "content_hash"})
    if payload.get("content_hash") != expected:
        raise TimeSeriesV8PipelineError("V8 development run content hash mismatch")
    payload["score_rows"] = _rows_from_json(payload["scores"])
    return payload


def verify_timeseries_v8(root: Path) -> dict[str, Any]:
    """Verify V8 preregistration, predecessor pins, and ledger discipline."""
    errors: list[str] = []
    contract: dict[str, Any] | None = None
    try:
        contract = load_contract_v8(root)
    except (OSError, TimeSeriesV8ContractError, KeyError) as exc:
        errors.append(f"contract: {exc}")
    benchmark: dict[str, str] | None = None
    if contract is not None:
        try:
            benchmark = verify_v2_benchmark(root, contract)
        except (OSError, TimeSeriesV8ContractError) as exc:
            errors.append(f"v2_benchmark: {exc}")
    experiments = read_experiments(root)
    holdouts = read_holdout_scorings(root)
    for row in experiments + holdouts:
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("content_hash") != canonical_hash(body):
            errors.append(f"ledger row hash mismatch: {row.get('experiment_id')}")
    budget = None
    if contract is not None:
        budget = int(contract["development_protocol"]["maximum_development_evaluations"])
        if len(experiments) > budget:
            errors.append("development evaluation budget exceeded")
        finalists = {row["experiment_id"] for row in holdouts}
        if len(finalists) > int(contract["development_protocol"]["holdout_maximum_finalists"]):
            errors.append("holdout finalist budget exceeded")
        if any(
            not math.isfinite(float(row.get("paired_long_horizon", {}).get("mean") or math.nan))
            for row in experiments
        ):
            errors.append("non-finite paired mean in experiment ledger")
    sealed_marker = root / "data/timeseries_v8/ledgers/sealed_evaluations.jsonl"
    if sealed_marker.is_file():
        errors.append("a V8 sealed ledger exists before contract freeze and user sign-off")
    return {
        "ok": not errors,
        "errors": errors,
        "model_id": None if contract is None else contract["model_id"],
        "contract_hash": None if contract is None else frozen_hash(contract),
        "v2_benchmark": benchmark,
        "experiments": len(experiments),
        "holdout_scorings": len(holdouts),
        "development_budget": budget,
    }
