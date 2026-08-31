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
    append_unique,
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


SEALED_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/sealed_evaluations.jsonl")
SHADOW_FORECAST_LEDGER = Path("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")
SHADOW_RESOLUTION_LEDGER = Path("data/timeseries_v8/ledgers/shadow_resolutions.jsonl")
LATEST_RELATIVE = Path("data/timeseries_v8/multivariate_v8_latest.json")


def _read_chain(root: Path, relative: Path) -> list[dict[str, Any]]:
    path = root / relative
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _chain_append(root: Path, relative: Path, payload: dict[str, Any], *, key: str) -> dict[str, Any]:
    """Append one hash-chained row: prev_content_hash links to the last row."""
    rows = _read_chain(root, relative)
    previous = rows[-1]["content_hash"] if rows else "GENESIS"
    body = {k: v for k, v in payload.items() if k not in ("content_hash", "prev_content_hash")}
    body["prev_content_hash"] = previous
    body["content_hash"] = canonical_hash(body)
    from .artifact import append_unique as _append_unique

    _append_unique(root, relative, body, key=key)
    return body


def verify_chain(root: Path, relative: Path) -> list[str]:
    errors: list[str] = []
    previous = "GENESIS"
    for index, row in enumerate(_read_chain(root, relative)):
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if row.get("content_hash") != canonical_hash(body):
            errors.append(f"{relative.name}[{index}]: content hash mismatch")
        if row.get("prev_content_hash") != previous:
            errors.append(f"{relative.name}[{index}]: chain link broken")
        previous = row.get("content_hash", "")
    return errors


def _sealed_gate_passed(root: Path) -> dict[str, Any]:
    path = root / SEALED_LEDGER_RELATIVE
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ] if path.is_file() else []
    if not rows:
        raise TimeSeriesV8PipelineError("the sealed evaluation has not been disclosed")
    row = rows[-1]
    if (row.get("summary") or {}).get("gate_pass") is not True:
        raise TimeSeriesV8PipelineError(
            "the sealed evaluation did not pass the gate; the shadow surface stays closed"
        )
    return row


def _sealed_preconditions(
    root: Path, contract: dict[str, Any], *, user_signoff: str, path_count: int,
) -> dict[str, Any]:
    """Fail closed unless every gate before the single disclosure is satisfied."""
    if not str(user_signoff).strip():
        raise TimeSeriesV8PipelineError(
            "the sealed evaluation requires an explicit user sign-off string"
        )
    if not (contract.get("freeze_note") or {}).get("frozen_on"):
        raise TimeSeriesV8PipelineError("the V8 contract is not frozen")
    winner = contract.get("frozen_winner") or {}
    if not winner.get("config_overrides"):
        raise TimeSeriesV8PipelineError("no frozen winner configuration is registered")
    if (winner.get("user_signoff") or {}).get("decision_id") != "R8-D2":
        raise TimeSeriesV8PipelineError("the R8-D2 sign-off receipt is missing from the contract")
    required_paths = int(contract["model"]["distribution"]["sealed_path_count"])
    if int(path_count) != required_paths:
        raise TimeSeriesV8PipelineError(
            f"the sealed V8 evaluation requires exactly {required_paths} paths"
        )
    sealed = contract["model"]["sealed_evaluation"]
    if int(sealed.get("maximum_disclosures_per_model_version", 1)) != 1:
        raise TimeSeriesV8PipelineError("sealed disclosure budget drifted")
    if (root / SEALED_LEDGER_RELATIVE).is_file():
        raise TimeSeriesV8PipelineError("the single V8 sealed evaluation is already disclosed")
    frozen_config = build_config_from_grids(contract, winner["config_overrides"])
    holdouts = read_holdout_scorings(root)
    matching = [
        row for row in holdouts
        if row.get("config") == frozen_config.as_manifest()
        and (row.get("proxy") or {}).get("pass") is True
    ]
    if not matching:
        raise TimeSeriesV8PipelineError(
            "no passing holdout scoring exists for the frozen winner configuration"
        )
    return {"config": frozen_config, "holdout_row": matching[-1]}


def _sealed_bundle(root: Path, contract_v8: dict[str, Any]) -> CandidateFeatureBundle:
    """The full, untruncated C1 bundle — reachable only from the sealed verb."""
    contract_v2 = load_contract_v2(root)
    facts = read_facts(root)
    assembly_cutoff = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundle = assemble_candidate_bundle(
        root, contract=contract_v2, macro_facts=facts,
        candidate_id="C1", knowledge_cutoff=assembly_cutoff,
    )
    tolerated = {"dfm_origin_cache_incomplete"}
    blocking = [item for item in bundle.missing_features if item not in tolerated]
    if blocking or not bundle.dates:
        raise TimeSeriesV8PipelineError(
            f"V2 C1 bundle unavailable: {', '.join(blocking) or 'insufficient sessions'}"
        )
    from ai_fc.timeseries_v2.contracts import frozen_hash as frozen_hash_v2
    from ai_fc.timeseries_v2.dfm_cache import macro_release_cutoffs, read_dfm_manifest

    expected = set(macro_release_cutoffs(
        facts, start="2007-01-01", end=f"{bundle.dates[-1]}T23:59:59+00:00",
    ))
    ready = {
        str(row["cutoff"]) for row in read_dfm_manifest(root)
        if row.get("contract_hash") == frozen_hash_v2(contract_v2)
        and row.get("status") == "ready"
    }
    missing_cutoffs = sorted(expected - ready)
    if not expected or missing_cutoffs:
        raise TimeSeriesV8PipelineError(
            f"sealed-window DFM cache incomplete: {len(missing_cutoffs)} cutoff(s) missing"
        )
    if not np.isfinite(bundle.exogenous).all():
        raise TimeSeriesV8PipelineError("sealed-window factor states contain gaps")
    return bundle


def sealed_backtest_timeseries_v8(
    root: Path, *, user_signoff: str, knowledge_cutoff: str | None = None,
    path_count: int = 20000,
) -> dict[str, Any]:
    """The single, user-approved 2019+ disclosure of the frozen winner.

    This is never invoked by any loop or workflow: the contract prohibits
    `automatic_sealed_disclosure`, and the CLI requires the sign-off string
    to be passed explicitly on each invocation.
    """
    protected_before = protected_hashes(root)
    contract = load_contract_v8(root)
    verify_v2_benchmark(root, contract)
    require_dfm_runtime()
    pre = _sealed_preconditions(
        root, contract, user_signoff=user_signoff, path_count=path_count,
    )
    config = pre["config"]
    code_hash = model_code_hash(root)
    contract_digest = frozen_hash(contract)
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundle = _sealed_bundle(root, contract)
    from ai_fc.timeseries_v2.backtest import summarize_backtest_v2
    from ai_fc.timeseries_v2.contracts import runtime_manifest
    from ai_fc.timeseries_v2.market_archive import verify_market_lineage

    scores, _ = walk_forward_dev_backtest_v8(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        config=config,
        outer_start=str(contract["evaluation"]["outer_start"]),
        outer_end=bundle.dates[-1],
        path_count=path_count,
        pit_min_matured=int(
            contract["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]
        ),
    )
    minimum_origins = int(contract["evaluation"]["minimum_origins"])
    full_summary = summarize_backtest_v2(scores, minimum_origins=minimum_origins)
    sealed_start = str(contract["model"]["windows"]["sealed"][0])
    sealed_scores = [row for row in scores if row.date >= sealed_start]
    sealed_summary = summarize_backtest_v2(sealed_scores, minimum_origins=minimum_origins)
    reasons = list(full_summary["reasons"])
    # The 2008 regime necessarily precedes the sealed interval and stays
    # enforced through the full summary, exactly as in the V2 disclosure.
    reasons.extend(
        f"봉인평가: {reason}" for reason in sealed_summary["reasons"]
        if "great_financial_crisis_2008" not in reason
    )
    lineage = verify_market_lineage(root)
    if lineage["receipt_linkage"] < 1.0:
        reasons.append("market receipt linkage below 100%")
    common_start_limit = str(contract["publication_gate"]["market_common_start_not_after"])
    if not bundle.dates or bundle.dates[0] > common_start_limit:
        reasons.append("2007년 검증을 위한 공통 시장 표본 미확보")
    gate_pass = not reasons
    protected_after = protected_hashes(root)
    protected_comparison = compare_protected_hashes(protected_before, protected_after)
    if not protected_comparison["ok"]:
        raise TimeSeriesV8PipelineError(
            f"protected path changed during the V8 sealed evaluation: {protected_comparison}"
        )
    seed = {
        "model_id": contract["model_id"],
        "contract_hash": contract_digest,
        "model_code_hash": code_hash,
        "config": config.as_manifest(),
        "knowledge_cutoff": cutoff,
        "path_count": int(path_count),
    }
    run_id = f"tsv8-sealed-{canonical_hash(seed)[:24]}"
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "model_id": contract["model_id"],
        "model_version": int(contract["model_version"]),
        "contract_hash": contract_digest,
        "model_code_hash": code_hash,
        "knowledge_cutoff": cutoff,
        "config": config.as_manifest(),
        "frozen_winner": {
            "design_experiment_id": contract["frozen_winner"]["design_experiment_id"],
            "holdout_experiment_id": contract["frozen_winner"]["holdout_experiment_id"],
        },
        "user_signoff": {
            **(contract["frozen_winner"].get("user_signoff") or {}),
            "invocation": str(user_signoff),
        },
        "sealed_disclosure_number": 1,
        "development_window": contract["model"]["windows"]["development"],
        "sealed_window": [sealed_start, bundle.dates[-1]],
        "path_count": int(path_count),
        "summary": {**full_summary, "gate_pass": gate_pass,
                    "status": "pass" if gate_pass else "hold", "reasons": reasons},
        "sealed_summary": sealed_summary,
        "scores": _rows_to_json(scores),
        "market_lineage": {key: lineage[key] for key in ("ok", "receipt_linkage")},
        "evaluation_runtime": runtime_manifest(),
        "protected_manifest": protected_after,
        "protected_comparison": protected_comparison,
    }
    payload["content_hash"] = canonical_hash(payload)
    _atomic_json(root / RUNS_RELATIVE / f"{run_id}.json", payload)
    append_unique(root, SEALED_LEDGER_RELATIVE, payload, key="run_id")
    return payload


def load_dev_run(root: Path, identity: str) -> dict[str, Any]:
    path = root / RUNS_RELATIVE / f"dev_{identity}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = canonical_hash({key: value for key, value in payload.items() if key != "content_hash"})
    if payload.get("content_hash") != expected:
        raise TimeSeriesV8PipelineError("V8 development run content hash mismatch")
    payload["score_rows"] = _rows_from_json(payload["scores"])
    return payload


def _iso_week(day: str) -> str:
    iso = datetime.fromisoformat(day).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def shadow_forecast_timeseries_v8(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    """Append this ISO week's prospective forecast to the hash-chained ledger.

    The full frozen-methodology walk-forward is replayed from 2007 so the
    ensemble and PIT-recalibration state at the forecast origin are exactly
    the sealed methodology's state — deterministic, so a same-day rerun
    produces the identical forecast and the append deduplicates. One
    forecast per ISO week; labels mature only sessions later, so every row
    is recorded strictly before its outcome is knowable.
    """
    contract = load_contract_v8(root)
    verify_v2_benchmark(root, contract)
    require_dfm_runtime()
    sealed_row = _sealed_gate_passed(root)
    config = build_config_from_grids(
        contract, json.loads(json.dumps(contract["frozen_winner"]["config_overrides"])),
    )
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundle = _sealed_bundle(root, contract)
    origin = bundle.dates[-1]
    existing = _read_chain(root, SHADOW_FORECAST_LEDGER)
    same_week = [row for row in existing if row.get("iso_week") == _iso_week(origin)]
    if same_week:
        return {**same_week[-1], "skipped": "a forecast already exists for this ISO week"}
    scores, summary = walk_forward_dev_backtest_v8(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        config=config,
        outer_start=str(contract["evaluation"]["outer_start"]),
        outer_end=bundle.dates[-1],
        path_count=int(contract["model"]["distribution"]["sealed_path_count"]),
        pit_min_matured=int(
            contract["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]
        ),
        collect_cramer_audit=False,
        emit_forecast=True,
    )
    forecast = summary["shadow_forecast"]
    payload = {
        "schema_version": 1,
        "forecast_id": f"tsv8-shadow-{canonical_hash({'model': contract['model_id'], 'config': config.as_manifest(), 'origin': forecast['origin']})[:24]}",
        "model_id": contract["model_id"],
        "model_version": int(contract["model_version"]),
        "origin": forecast["origin"],
        "iso_week": _iso_week(forecast["origin"]),
        "knowledge_cutoff": cutoff,
        "contract_hash": frozen_hash(contract),
        "model_code_hash": model_code_hash(root),
        "sealed_run_id": sealed_row["run_id"],
        "config": config.as_manifest(),
        "grid_levels_count": forecast["grid_levels_count"],
        "ensemble_weights": forecast["ensemble_weights"],
        "block_length": forecast["block_length"],
        "ewma_lambda": forecast["ewma_lambda"],
        "horizons": forecast["horizons"],
        "matured_origins_at_emit": len({row.date for row in scores}),
        "probability_unit": "fraction",
    }
    return _chain_append(root, SHADOW_FORECAST_LEDGER, payload, key="forecast_id")


def shadow_resolve_timeseries_v8(
    root: Path, *, bundle: CandidateFeatureBundle | None = None,
) -> dict[str, Any]:
    """Score every matured, unresolved shadow forecast horizon (append-only)."""
    from ai_fc.timeseries.backtest import sample_crps

    forecasts = _read_chain(root, SHADOW_FORECAST_LEDGER)
    if not forecasts:
        return {"resolved": 0, "note": "no shadow forecasts yet"}
    resolutions = _read_chain(root, SHADOW_RESOLUTION_LEDGER)
    resolved_keys = {(row["forecast_id"], int(row["horizon"])) for row in resolutions}
    if bundle is None:
        bundle = _sealed_bundle(root, load_contract_v8(root))
    index_by_date = {day: index for index, day in enumerate(bundle.dates)}
    appended = []
    for forecast in forecasts:
        origin_index = index_by_date.get(forecast["origin"])
        if origin_index is None:
            continue
        for horizon in (1, 5, 21, 63):
            key = (forecast["forecast_id"], horizon)
            if key in resolved_keys:
                continue
            end = origin_index + horizon
            if end >= len(bundle.dates):
                continue
            actual = float(np.sum(bundle.endogenous[origin_index + 1: end + 1, 0]))
            grid = np.asarray(forecast["horizons"][str(horizon)]["quantile_grid"], dtype=float)
            baseline_grid = np.asarray(
                forecast["horizons"][str(horizon)]["baseline_quantile_grid"], dtype=float,
            )
            levels_count = int(forecast["grid_levels_count"])
            p10, p25, p50, p75, p90 = (
                float(grid[int(q * levels_count)]) for q in (0.10, 0.25, 0.50, 0.75, 0.90)
            )
            payload = {
                "schema_version": 1,
                "resolution_id": f"{forecast['forecast_id']}-h{horizon}",
                "forecast_id": forecast["forecast_id"],
                "model_id": forecast["model_id"],
                "origin": forecast["origin"],
                "horizon": horizon,
                "resolved_session": bundle.dates[end],
                "actual_log_return": actual,
                "model_crps": float(sample_crps(grid, actual)),
                "baseline_crps": float(sample_crps(baseline_grid, actual)),
                "covered_p10_p90": bool(p10 <= actual <= p90),
                "covered_p25_p75": bool(p25 <= actual <= p75),
                "direction_correct": bool((p50 >= 0) == (actual >= 0)),
                "p_up": forecast["horizons"][str(horizon)]["p_up"],
            }
            appended.append(_chain_append(
                root, SHADOW_RESOLUTION_LEDGER, payload, key="resolution_id",
            ))
            resolved_keys.add(key)
    return {"resolved": len(appended), "total_resolutions": len(resolutions) + len(appended)}


def publish_latest_timeseries_v8(root: Path) -> dict[str, Any]:
    """Write the fail-closed V8 latest pointer (data layer only).

    Numbers become visible only when the disclosed sealed gate passed AND
    the operational freshness gate holds; the customer display surface is a
    separately governed display-promotion step, and every output keeps its
    참고 의견 (research reference) status per the project constitution.
    """
    from ai_fc.timeseries_v2.market_archive import read_market_observations

    contract = load_contract_v8(root)
    now = datetime.now(timezone.utc)
    cutoff = now.isoformat(timespec="seconds")
    sealed_row = None
    reasons: list[str] = []
    try:
        sealed_row = _sealed_gate_passed(root)
    except TimeSeriesV8PipelineError as exc:
        reasons.append(str(exc))
    market = read_market_observations(root, knowledge_cutoff=cutoff)
    operational = contract["operational_gate"]
    default_limit = float(operational["required_market_max_age_hours"])
    overrides = {
        str(key): float(value)
        for key, value in (operational.get("per_group_max_age_hours_override") or {}).items()
    }
    freshness_groups = []
    for alternatives in operational["required_market_groups"]:
        label = "_or_".join(alternatives)
        rows = [row for row in market if row.series_id in set(alternatives)]
        if not rows:
            freshness_groups.append({"group": label, "status": "missing"})
            reasons.append(f"필수 시장 입력 누락: {label}")
            continue
        latest = max(rows, key=lambda row: (row.observation_time, row.available_at))
        observation_end = datetime.fromisoformat(latest.observation_time).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc,
        )
        age_hours = max(0.0, (now - observation_end).total_seconds() / 3600.0)
        limit = overrides.get(label, default_limit)
        status = "fresh" if age_hours <= limit else "stale"
        freshness_groups.append({
            "group": label, "observation_time": latest.observation_time,
            "age_hours": age_hours, "limit_hours": limit, "status": status,
        })
        if status != "fresh":
            reasons.append(f"필수 시장 입력 신선도 초과: {label}")
    resolutions = _read_chain(root, SHADOW_RESOLUTION_LEDGER)
    recent_required = int(operational["recent_origins"])
    matured_origins = sorted({row["origin"] for row in resolutions if row["horizon"] == 63})
    monitoring: dict[str, Any] = {"matured_shadow_origins": len(matured_origins)}
    if len(matured_origins) >= recent_required:
        recent = matured_origins[-recent_required:]
        rows = [row for row in resolutions if row["origin"] in set(recent)]
        model_crps = float(np.mean([row["model_crps"] for row in rows if row["horizon"] in (21, 63)]))
        baseline_crps = float(np.mean([row["baseline_crps"] for row in rows if row["horizon"] in (21, 63)]))
        underperformance = (model_crps - baseline_crps) / baseline_crps if baseline_crps > 0 else 0.0
        monitoring.update({
            "source": "shadow_resolutions",
            "recent_long_horizon_crps_underperformance": underperformance,
        })
        if underperformance > float(operational["crps_max_underperformance"]):
            reasons.append("최근 shadow 원점 CRPS가 기준선 대비 허용치 초과")
    else:
        monitoring["source"] = "sealed_backtest_until_shadow_origins_mature"
    forecasts = _read_chain(root, SHADOW_FORECAST_LEDGER)
    latest_forecast = forecasts[-1] if forecasts else None
    if latest_forecast is None:
        reasons.append("shadow forecast가 아직 없음")
    visible = not reasons
    payload: dict[str, Any] = {
        "schema_version": 1,
        "model_id": contract["model_id"],
        "model_version": int(contract["model_version"]),
        "status": "shadow_live" if visible else "shadow_operational_hold",
        "display_state": "research_reference" if visible else "validation_pending",
        "as_of": None if latest_forecast is None else latest_forecast["origin"],
        "knowledge_cutoff": cutoff,
        "probability_unit": "fraction",
        "probability_space": str(contract["probability_contract"]["space"]),
        "publication": {
            "customer_numbers_visible": visible,
            "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
            "reference_opinion_only": True,
        },
        "gate": {
            "sealed_gate_pass": bool(sealed_row is not None),
            "sealed_run_id": None if sealed_row is None else sealed_row["run_id"],
            "operational_pass": visible,
            "reasons": reasons,
        },
        "operational": {"freshness": freshness_groups, "monitoring": monitoring},
        "footnote": "*미국 시장·미국 공식 거시자료 기준 · 참고 의견",
    }
    if visible and latest_forecast is not None:
        levels_count = int(latest_forecast["grid_levels_count"])
        payload["horizons"] = {
            horizon: {
                "p10": float(values["quantile_grid"][int(0.10 * levels_count)]),
                "p25": float(values["quantile_grid"][int(0.25 * levels_count)]),
                "p50": float(values["quantile_grid"][int(0.50 * levels_count)]),
                "p75": float(values["quantile_grid"][int(0.75 * levels_count)]),
                "p90": float(values["quantile_grid"][int(0.90 * levels_count)]),
                "probability_up": float(values["p_up"]),
            }
            for horizon, values in latest_forecast["horizons"].items()
        }
        for horizon in payload["horizons"].values():
            if not 0.0 <= horizon["probability_up"] <= 1.0:
                raise TimeSeriesV8PipelineError("shadow probability escaped the fraction contract")
    payload["content_hash"] = canonical_hash(payload)
    _atomic_json(root / LATEST_RELATIVE, payload)
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
    for relative in (SHADOW_FORECAST_LEDGER, SHADOW_RESOLUTION_LEDGER):
        errors.extend(verify_chain(root, relative))
    sealed_marker = root / SEALED_LEDGER_RELATIVE
    if sealed_marker.is_file():
        frozen = bool(((contract or {}).get("freeze_note") or {}).get("frozen_on"))
        signoff = ((contract or {}).get("frozen_winner") or {}).get("user_signoff") or {}
        if not (frozen and signoff.get("decision_id") == "R8-D2"):
            errors.append("a V8 sealed ledger exists before contract freeze and user sign-off")
    return {
        "ok": not errors,
        "errors": errors,
        "model_id": None if contract is None else contract["model_id"],
        "contract_hash": None if contract is None else frozen_hash(contract),
        "v2_benchmark": benchmark,
        "experiments": len(experiments),
        "holdout_scorings": len(holdouts),
        "shadow_forecasts": len(_read_chain(root, SHADOW_FORECAST_LEDGER)),
        "shadow_resolutions": len(_read_chain(root, SHADOW_RESOLUTION_LEDGER)),
        "development_budget": budget,
    }
