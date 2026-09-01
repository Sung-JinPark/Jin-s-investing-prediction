"""V9 development pipeline — a read-only wrapper over the sealed V8 engine.

The wrapper's entire modeling delta is the exogenous matrix: preregistered V9
features are appended as extra columns and everything else — VARX kernels,
FHS distribution, PIT recalibration, scoring, baselines — is the byte-sealed
V8 implementation called as a library.  The E0-nesting invariant follows
structurally: with an empty feature set the inputs are the V8 inputs,
bit-identical, and a regression test asserts exactly that.

Stops that are NOT automated here: holdout consumption requires an explicit
user-approval string, and no sealed-evaluation entry point exists in this
package at all.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.scenario_v5.contracts import compare_protected_hashes, protected_hashes
from ai_fc.timeseries_v8.artifact import append_unique, read_ledger
from ai_fc.timeseries_v8.backtest import (
    dev_gate_proxy_report,
    paired_differences_vs_best,
    walk_forward_dev_backtest_v8,
)
from ai_fc.timeseries_v8.contracts import load_contract_v8
from ai_fc.timeseries_v8.model import experiment_id
from ai_fc.timeseries_v8.pipeline import (
    _development_bundle,
    _rows_to_json,
    build_config_from_grids,
    require_dfm_runtime,
)
from .contracts import (
    EXPERIMENT_LEDGER_RELATIVE,
    HOLDOUT_LEDGER_RELATIVE,
    MODEL_ID,
    MODEL_VERSION,
    RUNS_RELATIVE,
    TimeSeriesV9ContractError,
    canonical_hash,
    frozen_hash,
    load_contract_v9,
    model_code_hash,
    v8_sealed_source_hash,
    verify_v8_benchmark,
)
from .features import build_m2sl_feature, correlation_rejection

FEATURE_BUILDERS = {"F1_m2sl_liquidity": build_m2sl_feature}


class TimeSeriesV9PipelineError(RuntimeError):
    """A V9 pipeline invariant failed closed."""


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8", newline="\n",
    )
    temporary.replace(path)


def _validate_feature_set(contract: dict[str, Any], feature_set: list[str]) -> list[str]:
    grid = contract["research_grids"]["V9_F1_liquidity_exog"]["feature_sets"]
    ordered = sorted(feature_set)
    if ordered not in [sorted(candidate) for candidate in grid]:
        raise TimeSeriesV9PipelineError(
            f"feature set {ordered} is outside the preregistered grid {grid}"
        )
    unknown = [name for name in ordered if name not in FEATURE_BUILDERS]
    if unknown:
        raise TimeSeriesV9PipelineError(f"no builder for preregistered feature(s): {unknown}")
    return ordered


def dev_backtest_timeseries_v9(
    root: Path,
    *,
    feature_set: list[str],
    experiment_label: str = "",
    window_role: str = "design",
    holdout_user_approval: str = "",
    knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    if window_role not in ("design", "holdout"):
        raise TimeSeriesV9PipelineError("window role must be design or holdout")
    protected_before = protected_hashes(root)
    v8_source_before = v8_sealed_source_hash(root)
    contract9 = load_contract_v9(root)
    verify_v8_benchmark(root, contract9)
    contract8 = load_contract_v8(root)
    require_dfm_runtime()
    features = _validate_feature_set(contract9, list(feature_set))
    protocol = contract9["development_protocol"]
    experiments = read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
    holdouts = read_ledger(root, HOLDOUT_LEDGER_RELATIVE)

    config = build_config_from_grids(
        contract8,
        json.loads(json.dumps(contract9["model"]["base_configuration_overrides"])),
    )
    code_hash = model_code_hash(root)
    bundle = _development_bundle(root, contract8)
    exog = np.ascontiguousarray(bundle.exogenous)
    exog_names = tuple(bundle.exogenous_names)
    feature_manifests: list[dict[str, Any]] = []
    for name in features:
        column, manifest = FEATURE_BUILDERS[name](root, bundle.dates)
        manifest["correlation"] = correlation_rejection(
            column, exog, exog_names,
            limit=float(contract9["features"]["rejection_rules"][
                "max_abs_correlation_vs_existing_exog"]),
        )
        exog = np.ascontiguousarray(np.column_stack([exog, column]))
        exog_names = exog_names + (f"v9_{name}",)
        feature_manifests.append(manifest)

    bundle_hash = canonical_hash({
        "dates": bundle.dates,
        "endogenous": np.ascontiguousarray(bundle.endogenous).tobytes().hex(),
        "exogenous": exog.tobytes().hex(),
        "feature_set": features,
    })
    identity = experiment_id(config, bundle_hash=bundle_hash, code_hash=code_hash)
    identity = identity.replace("tsv8-exp-", "tsv9-exp-")
    windows = contract9["model"]["windows"]
    if window_role == "design":
        if len(experiments) >= int(protocol["maximum_development_evaluations"]):
            raise TimeSeriesV9PipelineError(
                "preregistered development evaluation budget is exhausted"
            )
        prior = next((row for row in experiments if row["experiment_id"] == identity), None)
        if prior is not None:
            return prior
        outer_start, outer_end = windows["design"]
        path_count = int(contract9["model"]["distribution"]["development_path_count"])
    else:
        # ★ 정지점: 홀드아웃은 무인 자동화 밖 — 명시 승인 문자열 없이는 실행 불가.
        if not str(holdout_user_approval).strip():
            raise TimeSeriesV9PipelineError(
                "holdout consumption requires an explicit user-approval string "
                "(automatic_holdout_consumption is prohibited by contract)"
            )
        if any(row["experiment_id"] == identity for row in holdouts):
            raise TimeSeriesV9PipelineError("this finalist already consumed its holdout scoring")
        if len({row["experiment_id"] for row in holdouts}) >= int(
                protocol["holdout_maximum_finalists"]):
            raise TimeSeriesV9PipelineError("holdout finalist budget is exhausted")
        outer_start = windows["development"][0]
        outer_end = windows["holdout"][1]
        path_count = int(contract9["model"]["distribution"]["sealed_path_count"])

    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    scores, summary = walk_forward_dev_backtest_v8(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=exog,
        endog_names=bundle.endogenous_names,
        exog_names=exog_names,
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        config=config,
        outer_start=outer_start,
        outer_end=outer_end,
        path_count=path_count,
        pit_min_matured=int(
            contract8["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]
        ),
    )
    if window_role == "holdout":
        holdout_start, holdout_end = windows["holdout"]
        reported = [row for row in scores if holdout_start <= row.date <= holdout_end]
    else:
        reported = scores
    paired = paired_differences_vs_best(reported)
    from ai_fc.timeseries_v8.pipeline import _resummarize
    proxy = dev_gate_proxy_report(
        summary if window_role == "design" else _resummarize(reported),
        paired, proxy=contract9["dev_gate_proxy"], window_role=window_role,
    )

    if v8_sealed_source_hash(root) != v8_source_before:
        raise TimeSeriesV9PipelineError("V8 sealed sources changed during a V9 run — abort")
    comparison = compare_protected_hashes(protected_before, protected_hashes(root))
    if not comparison["ok"]:
        raise TimeSeriesV9PipelineError(
            f"protected path changed during V9 development run: {comparison}"
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
        "window_role": window_role,
        "window": {"outer_start": outer_start, "outer_end": outer_end},
        "knowledge_cutoff": cutoff,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "contract_hash": frozen_hash(contract9),
        "model_code_hash": code_hash,
        "bundle_hash": bundle_hash,
        "feature_set": features,
        "feature_manifests": feature_manifests,
        "config": config.as_manifest(),
        "path_count": path_count,
        "horizons": horizon_metrics,
        "paired_long_horizon": {
            key: paired[key] for key in ("origin_count", "mean", "ci90", "best_baselines")
        },
        "gfc_regime_coverage": (summary.get("regime_coverage") or {}).get(
            "great_financial_crisis_2008"
        ),
        "proxy": proxy,
    }
    if window_role == "holdout":
        ledger_row["holdout_user_approval"] = str(holdout_user_approval)
    body = {key: value for key, value in ledger_row.items() if key != "content_hash"}
    ledger_row = {**body, "content_hash": canonical_hash(body)}
    relative = EXPERIMENT_LEDGER_RELATIVE if window_role == "design" else HOLDOUT_LEDGER_RELATIVE
    append_unique(root, relative, ledger_row, key="experiment_id")
    run_payload = {
        **ledger_row,
        "summary": summary,
        "paired_differences": paired["differences"],
        "scores": _rows_to_json(reported),
    }
    run_payload["content_hash"] = canonical_hash(
        {key: value for key, value in run_payload.items() if key != "content_hash"}
    )
    _atomic_json(root / RUNS_RELATIVE / f"dev_{identity}.json", run_payload)
    return run_payload


def design_champion(root: Path) -> dict[str, Any] | None:
    """The design champion, if any ledger row satisfies the preregistered proxy."""
    rows = [
        row for row in read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
        if row.get("window_role") == "design" and (row.get("proxy") or {}).get("pass") is True
    ]
    if not rows:
        return None
    def long_mean(row: dict[str, Any]) -> float:
        horizons = row.get("horizons") or {}
        values = [
            float(horizons[key]["crps_improvement_vs_best"])
            for key in ("21", "63") if key in horizons
        ]
        return float(np.mean(values)) if values else float("-inf")
    return max(rows, key=long_mean)


def verify_timeseries_v9(root: Path) -> dict[str, Any]:
    """Verify V9 preregistration, predecessor pins, budgets, and ledgers."""
    errors: list[str] = []
    contract: dict[str, Any] | None = None
    try:
        contract = load_contract_v9(root)
    except (OSError, TimeSeriesV9ContractError, KeyError) as exc:
        errors.append(f"contract: {exc}")
    benchmark = None
    if contract is not None:
        try:
            benchmark = verify_v8_benchmark(root, contract)
        except (OSError, TimeSeriesV9ContractError) as exc:
            errors.append(f"v8_benchmark: {exc}")
    experiments = read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
    holdouts = read_ledger(root, HOLDOUT_LEDGER_RELATIVE)
    for row in experiments + holdouts:
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("content_hash") != canonical_hash(body):
            errors.append(f"ledger row hash mismatch: {row.get('experiment_id')}")
    budget = None
    if contract is not None:
        budget = int(contract["development_protocol"]["maximum_development_evaluations"])
        if len(experiments) > budget:
            errors.append("development evaluation budget exceeded")
        if len({row["experiment_id"] for row in holdouts}) > int(
                contract["development_protocol"]["holdout_maximum_finalists"]):
            errors.append("holdout finalist budget exceeded")
        for row in holdouts:
            if not str(row.get("holdout_user_approval") or "").strip():
                errors.append(
                    f"holdout row without a user approval string: {row.get('experiment_id')}"
                )
    return {
        "ok": not errors,
        "errors": errors,
        "model_id": None if contract is None else contract["model_id"],
        "contract_hash": None if contract is None else frozen_hash(contract),
        "v8_benchmark": benchmark,
        "v8_sealed_source_hash": v8_sealed_source_hash(root),
        "experiments": len(experiments),
        "holdout_scorings": len(holdouts),
        "development_budget": budget,
        "champion": (design_champion(root) or {}).get("experiment_label"),
    }
