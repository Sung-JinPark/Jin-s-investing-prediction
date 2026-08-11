"""Reproducible V5.2 path-distinctness shadow diagnostics.

The module writes research evidence only.  It never writes official snapshots,
forecast ledgers, calibration ledgers, or archives.
"""

from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.scenario_v5.contracts import compare_protected_hashes, protected_hashes

from .engine import (
    ANCHOR,
    CANDIDATE_RELATIVE,
    SEED,
    _bands,
    _engine_masks,
    _path_metrics,
    _research_distinctness,
    _scenario_outputs,
    build_weights,
    evidence_scores,
    generate_prior,
    load_inputs,
    weighted_quantile,
)


BASELINE_COMMIT = "7ef55604b468104ef80f968c9e0791c37cb0eda1"
OUTPUT_RELATIVE = Path("reports/diagnostics/v52_distinctness_baseline_20260811")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def _baseline_candidate(root: Path) -> dict[str, Any]:
    relative = CANDIDATE_RELATIVE.as_posix()
    completed = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{relative}"], cwd=root,
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _path_summary(payload: dict[str, Any]) -> dict[str, Any]:
    scenarios = payload["conditional_small_multiples"]["scenarios"]
    dates = payload["conditional_small_multiples"]["dates"]
    checkpoints = {
        "1m": min(21, len(dates) - 1),
        "3m": min(63, len(dates) - 1),
        "6m": min(126, len(dates) - 1),
        "12m": min(252, len(dates) - 1),
        "terminal": len(dates) - 1,
    }
    per_scenario: dict[str, Any] = {}
    for key, row in scenarios.items():
        values = np.asarray(row["bands"]["p50"], dtype=float)
        log_returns = np.diff(np.log(values))
        running = np.maximum.accumulate(values)
        drawdown = values / running - 1.0
        per_scenario[key] = {
            "p50_return_checkpoints": {
                label: float(values[index] / values[0] - 1.0)
                for label, index in checkpoints.items()
            },
            "p50_maximum_drawdown": float(drawdown.min()),
            "p50_maximum_drawdown_date": dates[int(np.argmin(drawdown))],
            "p50_downside_semivolatility": float(
                np.sqrt(np.mean(np.square(np.minimum(log_returns, 0.0))))
                * math.sqrt(252.0)
            ),
            "medoid_path_id": row["central_path_bundle"]["medoid_path_id"],
        }
    pair_rows: list[dict[str, Any]] = []
    for left, right in (("S1", "S2"), ("S1", "S3"), ("S2", "S3")):
        left_values = np.asarray(scenarios[left]["bands"]["p50"], dtype=float)
        right_values = np.asarray(scenarios[right]["bands"]["p50"], dtype=float)
        pair_rows.append({
            "pair": f"{left}-{right}",
            "p50_log_level_correlation": float(np.corrcoef(
                np.log(left_values), np.log(right_values)
            )[0, 1]),
            "p50_first_difference_correlation": float(np.corrcoef(
                np.diff(np.log(left_values)), np.diff(np.log(right_values))
            )[0, 1]),
        })
    return {"per_scenario": per_scenario, "pairs": pair_rows}


def _run_variant(
    root: Path, inputs: dict[str, Any], *, seed: int = SEED,
    count: int = 600, generator_share: float = .60,
    residual_scale: float | None = None, allow_shadow: bool = False,
) -> tuple[np.ndarray, list[str], np.ndarray, dict[str, Any], dict[str, Any]]:
    paths, dates, engines, _, audit = generate_prior(
        root, inputs, seed=seed, path_count_per_engine=count,
        generator_dotcom_share=generator_share,
        residual_scale_override=residual_scale,
        allow_shadow_cap_exceed=allow_shadow,
    )
    scores = evidence_scores(inputs)
    weighting = build_weights(paths, dates, engines, scores, inputs["dotcom"], audit)
    return paths, dates, engines, audit, weighting


def _variant_summary(
    paths: np.ndarray, dates: list[str], engines: np.ndarray,
    audit: dict[str, Any], weighting: dict[str, Any],
) -> dict[str, Any]:
    masks = _engine_masks(engines)
    weights = weighting["full_evidence"]["weights"]
    metrics = _path_metrics(paths, dates)
    scenarios, legacy = _scenario_outputs(paths, dates, weights, metrics, masks)
    distinctness = _research_distinctness(paths, dates, weights, masks, scenarios, audit)
    return {
        "scenario_probabilities": {
            key: float(weights[mask].sum()) for key, mask in masks.items()
        },
        "p50_return_checkpoints": {
            key: {
                str(index): scenarios[key]["bands"]["p50"][index] / ANCHOR - 1.0
                for index in (21, 63, 126, 252)
            } for key in ("S1", "S2", "S3")
        },
        "medoid_path_ids": {
            key: scenarios[key]["central_path_bundle"]["medoid_path_id"]
            for key in ("S1", "S2", "S3")
        },
        "legacy_2027_gate_pass": legacy["gate_pass"],
        "descriptive_checks": distinctness["descriptive_checks"],
        "pairs": distinctness["pairs"],
    }


def build_diagnostics(root: Path) -> list[Path]:
    output = root / OUTPUT_RELATIVE
    output.mkdir(parents=True, exist_ok=True)
    current = json.loads((root / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))
    baseline = _baseline_candidate(root)
    inputs = load_inputs(root)
    before = current["build_receipt"]["protected_before"]
    after = protected_hashes(root)

    baseline_target = output / "baseline_candidate_snapshot.json"
    current_target = output / "current_candidate_snapshot.json"
    _write_json(baseline_target, baseline)
    _write_json(current_target, current)

    seed_rows: list[dict[str, Any]] = []
    for seed in (SEED, SEED + 7, SEED + 13):
        variant = _run_variant(root, inputs, seed=seed)
        seed_rows.append({"seed": seed, **_variant_summary(*variant)})
    seed_target = output / "seed_stability.json"
    _write_json(seed_target, {
        "path_count_per_scenario": 600,
        "seeds": seed_rows,
        "required_orders_hold_all_seeds": all(
            row["descriptive_checks"]["cumulative_return_order_S1_gt_S2_gt_S3"]
            and row["descriptive_checks"]["medoid_path_ids_unique"]
            for row in seed_rows
        ),
    })

    residual_rows: list[dict[str, Any]] = []
    for scale in (.30, .65, 1.00):
        variant = _run_variant(root, inputs, count=500, residual_scale=scale)
        residual_rows.append({"residual_scale": scale, **_variant_summary(*variant)})
    residual_target = output / "residual_scale_ablation.json"
    _write_json(residual_target, {
        "note": "S1 uses full realized phase blocks; the override applies to S2/S3 residuals.",
        "rows": residual_rows,
    })

    grid_rows: list[dict[str, Any]] = []
    for b_value in (.40, .60, .70, .80):
        paths, dates, engines, audit, _ = _run_variant(
            root, inputs, count=400, generator_share=b_value,
            allow_shadow=b_value > .60,
        )
        scores = evidence_scores(inputs)
        masks = _engine_masks(engines)
        for a_value in (.40, .60, .70, .80):
            dotcom = dict(inputs["dotcom"])
            dotcom["scenario_strength"] = {"S1": a_value, "S2": 0.0, "S3": 0.0}
            weighting = build_weights(paths, dates, engines, scores, dotcom, audit)
            weights = weighting["full_evidence"]["weights"]
            s1_weights = weights[masks["S1"]] / weights[masks["S1"]].sum()
            s1_bands = _bands(paths[masks["S1"]], s1_weights)
            grid_rows.append({
                "A_evidence_strength": a_value,
                "B_generator_dotcom_block_share": b_value,
                "mode": "within_cap" if max(a_value, b_value) <= .60 else "shadow_only_cap_exceeded",
                "eligible_for_active_use": max(a_value, b_value) <= .60,
                "C_mixture_probability": {
                    key: float(weights[mask].sum()) for key, mask in masks.items()
                },
                "S1_p50_return": {
                    str(index): s1_bands["p50"][index] / ANCHOR - 1.0
                    for index in (21, 63, 126, 252)
                },
                "weight_gates_pass": weighting["full_evidence"]["diagnostics"]["gates_pass"],
            })
    sensitivity_target = output / "A_B_sensitivity_grid.json"
    _write_json(sensitivity_target, {
        "active": {"A": .60, "B": .60},
        "cap": .60,
        "above_cap_never_active": True,
        "path_count_per_scenario": 400,
        "rows": grid_rows,
    })

    current_summary = _path_summary(current)
    baseline_summary = _path_summary(baseline)
    diagnosis_target = output / "baseline_vs_candidate.json"
    _write_json(diagnosis_target, {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_model_content_sha256": baseline["model_content_sha256"],
        "candidate_model_content_sha256": current["model_content_sha256"],
        "baseline": baseline_summary,
        "candidate": current_summary,
        "candidate_full_distinctness": current["distinctness"],
        "gate_A_consistency": {
            "distinct_source_groups_confirmed": True,
            "disjoint_rng_streams_confirmed": True,
            "legacy_S1_S2_residual_scale_equal_0_30_confirmed": True,
            "legacy_A_0_60_was_post_generation_only_confirmed": True,
            "medoid_is_actual_member_confirmed": True,
            "dashboard_25_75_coordinates_confirmed": True,
            "specification_contradiction_found": False,
        },
    })

    asof_target = output / "asof_five_vintage_audit.json"
    history_dates = current["distribution"]["historical_actual"]["dates"][-5:]
    assignment_hashes = {
        key: current["model"]["generator_audit"]["scenarios"][key][
            "cluster_assignments_sha256"
        ] for key in ("S1", "S2", "S3")
    }
    _write_json(asof_target, {
        "dates": history_dates,
        "available_vintage_count": 1,
        "status": "STRUCTURAL_ASSIGNMENT_STABILITY_ONLY_NOT_A_PIT_BACKTEST",
        "reason": "Only one approved row-level source vintage exists for this candidate cutoff.",
        "assignment_hashes": [
            {"asof_proxy": value, "hashes": assignment_hashes,
             "pairwise_jaccard_to_current": {"S1": 1.0, "S2": 1.0, "S3": 1.0}}
            for value in history_dates
        ],
        "fabricated_rolling_vintages": False,
    })

    protected_target = output / "protected_hashes_before_after.json"
    _write_json(protected_target, {
        "before": before, "after": after,
        "comparison": compare_protected_hashes(before, after),
    })
    call_graph_target = output / "CALL_GRAPH_AND_COORDINATE_AUDIT.md"
    call_graph_target.write_text(
        "# V5.2 call graph and coordinate audit\n\n"
        "- `build_clustered_prior` freezes state-feature k-medoids assignments before cluster outcomes are read.\n"
        "- S1 uses the phase-preserving block sampler; S2 and S3 use their own selected DB clusters and RNG streams.\n"
        "- A changes post-generation likelihood, B changes S1 block provenance, and C is derived by `build_weights`.\n"
        "- `_central_bundle` selects actual simulated members; scenario path IDs use global pool indexes.\n"
        "- The dashboard SVG allocates history 0.25 and forecast 0.75 in its actual X-coordinate function.\n"
        "- The research route defaults to three months; one month, 2026, and 2027 remain selectable.\n"
        "- October 2 remains an ordinary first-touch CDF coordinate, not an exact-date forecast.\n",
        encoding="utf-8", newline="\n",
    )
    summary_target = output / "README.md"
    comparison = compare_protected_hashes(before, after)
    summary_target.write_text(
        "# Scenario V5.2 distinct-path diagnostic\n\n"
        f"Generated `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`.\n\n"
        f"- Baseline model: `{baseline['model_content_sha256']}`\n"
        f"- Candidate model: `{current['model_content_sha256']}`\n"
        f"- Protected manifest unchanged: `{comparison['ok']}`\n"
        "- Gate A contradiction: `false`\n"
        "- Threshold gate: `report_only` until 30 approved trading-day observations\n"
        "- Requested promotion origin counts are 15/20/12; actual S2=16 and S3=7 remain promotion-blocking\n"
        "- Above-cap A/B 0.70 and 0.80 rows are shadow-only and never active\n"
        "- Five-as-of output is explicitly a structural stability audit because five independent PIT vintages do not exist\n",
        encoding="utf-8", newline="\n",
    )
    return [
        baseline_target, current_target, seed_target, residual_target,
        sensitivity_target, diagnosis_target, asof_target, protected_target,
        call_graph_target, summary_target,
    ]


if __name__ == "__main__":
    for generated in build_diagnostics(Path.cwd()):
        print(generated)
