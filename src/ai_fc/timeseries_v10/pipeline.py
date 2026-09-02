"""V10 개발 파이프라인 — 사전등록 라벨 구동, 포크 평가 루프 전용.

정본: v10_gate_precision_design_260902.md §3(등록부)·§4(진단 의무).
이 모듈에는 봉인·홀드아웃 실행 경로가 존재하지 않는다 — 계약
holdout_execution_path: absent_by_construction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ai_fc.scenario_v5.contracts import compare_protected_hashes, protected_hashes
from ai_fc.timeseries_v8.artifact import append_unique, read_ledger
from ai_fc.timeseries_v8.backtest import (
    dev_gate_proxy_report,
    paired_differences_vs_best,
)
from ai_fc.timeseries_v8.contracts import load_contract_v8
from ai_fc.timeseries_v8.pipeline import (
    _development_bundle,
    _rows_to_json,
    require_dfm_runtime,
)
from .backtest_fork import walk_forward_dev_backtest_v8 as fork_walk_forward
from .identity_test import check_source_pins, run_identity_check
from .model_fork import DistributionConfigV8 as ForkConfig
from .state import build_state_series

MODEL_ID = "shadow.mf_dfm_varx_regime_width_v10"
MODEL_VERSION = 10
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v10.yaml")
STORE_RELATIVE = Path("data/timeseries_v10")
EXPERIMENT_LEDGER_RELATIVE = STORE_RELATIVE / "ledgers/development_experiments.jsonl"
RUNS_RELATIVE = STORE_RELATIVE / "runs"

CHAMPION_BASE = dict(
    fhs_horizons=(21, 63),
    blend_weight_by_horizon={1: 1.0, 5: 1.0, 21: 0.75, 63: 0.75},
    pit_recalibration_shrinkage=0.5,
)

# 사전등록 라벨 → 포크 config 오버라이드 (계약 preregistered_first_experiments 순서).
EXPERIMENT_CONFIGS: dict[str, dict[str, Any]] = {
    "V10_E0_identity": {},
    "V10_W1_kappa_05": {"w1_kappa": 0.5},
    "V10_W1_kappa_10": {"w1_kappa": 1.0},
    "V10_W3_gamma_m010": {"w3_blend_gamma": -0.10},
    "V10_W3_gamma_m020": {"w3_blend_gamma": -0.20},
    "V10_W1_sens_rv_kappa_10": {"w1_kappa": 1.0, "w1_state": "rv63_over_rv504"},
    "V10_W2_S1": {"w2_mix_weights": (0.60, 0.30, 0.10)},
    "V10_W2_S2": {"w2_mix_weights": (0.50, 0.30, 0.20)},
    "V10_W2_S3": {"w2_mix_weights": (0.70, 0.20, 0.10)},
    "V10_W4a_isotonic": {"w4_recal_map": "isotonic_pav"},
    "V10_W4b_two_layer": {"w4_recal_map": "isotonic_pav", "w4_recal_layers": 2},
    "V10_W5_h5": {"fhs_horizons": (5, 21, 63)},
    "V10_W5_h1_h5": {"fhs_horizons": (1, 5, 21, 63)},
}

GATE_MARGIN_AXES = ("h63_p10_p90_upper", "projected_ci90_upper", "p25_p75_lower",
                    "gfc_regime_minimum")


class TimeSeriesV10PipelineError(RuntimeError):
    """A V10 pipeline invariant failed closed."""


def canonical_hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_contract_v10(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if payload.get("contract_id") != "multivariate_timeseries_v10":
        raise TimeSeriesV10PipelineError("unexpected V10 contract id")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV10PipelineError("unexpected V10 identity")
    proxy = payload["dev_gate_proxy"]
    if proxy["design_long_horizon_mean_crps_min_improvement"] != 0.025:
        raise TimeSeriesV10PipelineError("V10 dev gate proxy drifted from V8")
    if payload["publication_gate"]["p10_p90_coverage"] != [0.76, 0.84]:
        raise TimeSeriesV10PipelineError("V10 publication gate drifted from V8")
    if payload["prohibitions"].get("automatic_holdout_consumption") is not True:
        raise TimeSeriesV10PipelineError("V10 stop-point prohibition removed")
    queue = payload["development_protocol"]["preregistered_first_experiments"]
    if list(queue) != list(EXPERIMENT_CONFIGS):
        raise TimeSeriesV10PipelineError("V10 preregistered queue drifted from the code map")
    return payload


def _gate_margins(summary: dict[str, Any], proxy_report: dict[str, Any]) -> dict[str, float]:
    horizons = summary.get("horizons") or {}
    cov63 = float(horizons.get("63", {}).get("coverage_p10_p90", float("nan")))
    mids = [float(horizons[h]["coverage_p25_p75"]) for h in ("1", "5", "21", "63")
            if h in horizons]
    gfc = ((summary.get("regime_coverage") or {}).get("great_financial_crisis_2008")
           or {}).get("coverage_p10_p90")
    projected = proxy_report["checks"].get("projected_full_window_ci90_upper", {}).get("observed")
    return {
        "h63_p10_p90_upper": 0.84 - cov63,
        "projected_ci90_upper": (
            float("nan") if projected is None else -0.0004 - float(projected)
        ),
        "p25_p75_lower": (min(mids) - 0.45) if mids else float("nan"),
        "gfc_regime_minimum": (
            float("nan") if gfc is None else float(gfc) - 0.72
        ),
    }


def _dual_vs_e0(root: Path, scores, e0_run: dict[str, Any] | None) -> dict[str, Any] | None:
    if e0_run is None:
        return None
    e0_map = {(s["date"], s["horizon"]): s["model_crps"] for s in e0_run["scores"]}
    diffs_by_origin: dict[str, list[float]] = {}
    for row in scores:
        key = (row.date, row.horizon)
        if row.horizon in (21, 63) and key in e0_map:
            diffs_by_origin.setdefault(row.date, []).append(
                float(e0_map[key]) - float(row.model_crps)  # 양수 = 개선
            )
    origins = sorted(diffs_by_origin)
    per_origin = np.array([float(np.mean(diffs_by_origin[o])) for o in origins])
    if len(per_origin) < 30:
        return None
    rng = np.random.default_rng(20260902)
    block = 13
    replicates = []
    for _ in range(2000):
        picks = []
        while len(picks) < len(per_origin):
            start = int(rng.integers(0, len(per_origin)))
            length = int(rng.geometric(1.0 / block))
            picks.extend(per_origin[(start + np.arange(length)) % len(per_origin)])
        replicates.append(float(np.mean(picks[: len(per_origin)])))
    lower, upper = np.percentile(replicates, [5, 95])
    se = float(np.std(replicates, ddof=1))
    return {
        "origin_count": len(per_origin),
        "mean": float(np.mean(per_origin)),
        "ci90": [float(lower), float(upper)],
        "bootstrap_se": se,
        "mde50": 1.645 * se,
    }


def _load_e0_run(root: Path) -> dict[str, Any] | None:
    rows = read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
    e0 = next((r for r in rows if r.get("experiment_label") == "V10_E0_identity"), None)
    if e0 is None:
        return None
    path = root / RUNS_RELATIVE / f"dev_{e0['experiment_id']}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def dev_backtest_timeseries_v10(
    root: Path, *, experiment_label: str, knowledge_cutoff: str | None = None,
    skip_identity_check: bool = False,
) -> dict[str, Any]:
    if experiment_label not in EXPERIMENT_CONFIGS:
        raise TimeSeriesV10PipelineError(
            f"experiment {experiment_label} is outside the preregistered queue"
        )
    contract = load_contract_v10(root)
    pin_errors = check_source_pins(root)
    if pin_errors:
        raise TimeSeriesV10PipelineError(f"source pins failed: {pin_errors}")
    protocol = contract["development_protocol"]
    experiments = read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
    if len(experiments) >= int(protocol["maximum_development_evaluations"]):
        raise TimeSeriesV10PipelineError("preregistered development budget is exhausted")
    if any(row.get("experiment_label") == experiment_label for row in experiments):
        return next(row for row in experiments
                    if row["experiment_label"] == experiment_label)
    if not skip_identity_check:
        identity = run_identity_check(root)
        if not identity["ok"]:
            raise TimeSeriesV10PipelineError(f"identity precheck failed: {identity['errors']}")
    protected_before = protected_hashes(root)
    contract8 = load_contract_v8(root)
    require_dfm_runtime()
    bundle = _development_bundle(root, contract8)
    state_primary, state_alt = build_state_series(bundle.endogenous[:, 0])
    config = ForkConfig(**{**CHAMPION_BASE, **EXPERIMENT_CONFIGS[experiment_label]})
    windows = contract["model"]["windows"]
    outer_start, outer_end = windows["design"]
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    scores, summary = fork_walk_forward(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        config=config,
        outer_start=str(outer_start),
        outer_end=str(outer_end),
        path_count=int(contract["model"]["distribution"]["development_path_count"]),
        pit_min_matured=104,
        state_series=state_primary,
        state_series_alt=state_alt,
    )
    paired = paired_differences_vs_best(scores)
    proxy = dev_gate_proxy_report(
        summary, paired, proxy=contract["dev_gate_proxy"], window_role="design",
    )
    comparison = compare_protected_hashes(protected_before, protected_hashes(root))
    if not comparison["ok"]:
        raise TimeSeriesV10PipelineError(
            f"protected path changed during a V10 run: {comparison}"
        )
    margins = _gate_margins(summary, proxy)
    dual = _dual_vs_e0(root, scores, _load_e0_run(root))
    identity_body = {
        "label": experiment_label, "config": config.as_manifest(),
        "model": MODEL_ID, "version": MODEL_VERSION,
    }
    experiment_id = f"tsv10-exp-{canonical_hash(identity_body)[:20]}"
    horizon_metrics = {
        key: {
            metric: value[metric]
            for metric in ("origins", "crps", "best_baseline", "best_baseline_crps",
                           "crps_improvement_vs_best", "coverage_p10_p90",
                           "coverage_p25_p75")
        }
        for key, value in (summary.get("horizons") or {}).items()
    }
    ledger_row = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "experiment_label": experiment_label,
        "window_role": "design",
        "window": {"outer_start": str(outer_start), "outer_end": str(outer_end)},
        "knowledge_cutoff": cutoff,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "config": config.as_manifest(),
        "degenerate": config.is_v10_degenerate(),
        "horizons": horizon_metrics,
        "paired_long_horizon": {
            key: paired[key] for key in ("origin_count", "mean", "ci90", "best_baselines")
        },
        "gfc_regime_coverage": (summary.get("regime_coverage") or {}).get(
            "great_financial_crisis_2008"
        ),
        "proxy": proxy,
        "gate_margin": margins,
        "dual_vs_e0": dual,
    }
    body = {key: value for key, value in ledger_row.items() if key != "content_hash"}
    ledger_row = {**body, "content_hash": canonical_hash(json.loads(json.dumps(body)))}
    append_unique(root, EXPERIMENT_LEDGER_RELATIVE, ledger_row, key="experiment_id")
    run_payload = {**ledger_row, "summary": summary, "scores": _rows_to_json(scores)}
    target = root / RUNS_RELATIVE / f"dev_{experiment_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(run_payload, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8", newline="\n",
    )
    return run_payload


def design_champion(root: Path) -> dict[str, Any] | None:
    """Champion = proxy pass AND non-degenerate AND significant dual gain."""
    rows = [
        row for row in read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
        if (row.get("proxy") or {}).get("pass") is True
        and row.get("degenerate") is False
        and (row.get("dual_vs_e0") or {}).get("mean", 0) > 0
        and (row.get("dual_vs_e0") or {}).get("ci90", [0, 0])[0] > 0
    ]
    if not rows:
        return None
    return max(rows, key=lambda row: row["dual_vs_e0"]["mean"])


def best_dual_improvement(root: Path) -> float:
    """최고 쌍대 개선 (stop-loss 판정용): E0 장기 CRPS 대비 상대."""
    e0_run = _load_e0_run(root)
    if e0_run is None:
        return 0.0
    e0_long = np.mean([
        float(e0_run["horizons"][h]["crps"]) for h in ("21", "63")
    ])
    best = 0.0
    for row in read_ledger(root, EXPERIMENT_LEDGER_RELATIVE):
        dual = row.get("dual_vs_e0") or {}
        if dual.get("mean"):
            best = max(best, float(dual["mean"]) / float(e0_long))
    return best


def verify_timeseries_v10(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    contract = None
    try:
        contract = load_contract_v10(root)
    except (OSError, TimeSeriesV10PipelineError, KeyError) as exc:
        errors.append(f"contract: {exc}")
    errors.extend(check_source_pins(root))
    experiments = read_ledger(root, EXPERIMENT_LEDGER_RELATIVE)
    for row in experiments:
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("content_hash") != canonical_hash(json.loads(json.dumps(body))):
            errors.append(f"ledger row hash mismatch: {row.get('experiment_id')}")
        if row.get("gate_margin") is None:
            errors.append(f"gate_margin diagnostics missing: {row.get('experiment_id')}")
    if contract is not None:
        budget = int(contract["development_protocol"]["maximum_development_evaluations"])
        if len(experiments) > budget:
            errors.append("development budget exceeded")
    champion = design_champion(root)
    return {
        "ok": not errors,
        "errors": errors,
        "model_id": MODEL_ID,
        "experiments": len(experiments),
        "best_dual_improvement": best_dual_improvement(root),
        "champion": None if champion is None else champion["experiment_label"],
    }
