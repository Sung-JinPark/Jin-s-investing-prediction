"""R5 G4 one-shot outer scoring using the frozen R4 Gate implementation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ai_fc.timeseries_v7_r4.core_qualification import compute_gate_evidence
from ai_fc.timeseries_v7_r4.cross_fit_calibration import (
    CalibrationCase,
    fit_cross_fit_calibrator,
)
from ai_fc.timeseries_v7_r4.e0_empirical_samples import empirical_crps
from ai_fc.timeseries_v7_r4.empirical_mixture import empirical_mixture_crps

from .conditional_scale_selection import _eligible, canonical_json
from .e0_rescale import rescale_e0_samples
from .fhs_har_first_light import HORIZONS, _label_inputs, _load_runtime, _scale, e1_fhs_samples
from .stacking_reassessment import mixture_quantiles


OUTER_BLOCK_COUNT = 6
WEIGHT_TOLERANCE = 1e-12


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def claim_outer_once(receipt_path: Path, *, approval_record: dict[str, Any],
                     generation_id: str, outer_role_hash: str) -> dict[str, Any]:
    """Atomically persist the irreversible exposure boundary."""
    if receipt_path.exists():
        raise RuntimeError("R5 outer has already been exposed; retry is forbidden")
    receipt = {
        "schema": "r5_outer_exposure_receipt_v1", "generation_id": generation_id,
        "claimed_at": datetime.now(timezone.utc).isoformat(), "outer_role_hash": outer_role_hash,
        "approval": approval_record, "exposure_count": 1, "retry_allowed": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_bytes(canonical_json(receipt) + b"\n")
    temporary.replace(receipt_path)
    return receipt


def six_outer_blocks(origins: Sequence[str]) -> list[dict[str, Any]]:
    values = list(origins)
    if len(values) < OUTER_BLOCK_COUNT or values != sorted(values) or len(set(values)) != len(values):
        raise ValueError("outer origins must be unique, sorted, and cover six blocks")
    chunks = np.array_split(np.asarray(values, dtype=object), OUTER_BLOCK_COUNT)
    result = []
    for index, chunk in enumerate(chunks, 1):
        block = [str(value) for value in chunk]
        result.append({"block": index, "origin_count": len(block), "first": block[0],
                       "last": block[-1],
                       "origin_hash": hashlib.sha256(canonical_json(block)).hexdigest()})
    if [value for chunk in chunks for value in chunk.tolist()] != values:
        raise RuntimeError("outer six-block partition changed the frozen origin order")
    return result


def probability_up(models: Sequence[np.ndarray], weights: Sequence[float]) -> float:
    if len(models) != len(weights) or not models:
        raise ValueError("models and weights must be aligned")
    value = sum(float(weight) * float(np.mean(np.asarray(samples) > 0.0))
                for samples, weight in zip(models, weights, strict=True))
    if not 0.0 <= value <= 1.0:
        raise ValueError("probability must be an explicit fraction in [0,1]")
    return value


def _active_models(*, origin: str, horizon: int, runtime: dict[str, Any],
                   grouped: dict[int, list[dict[str, Any]]], lambda_: float,
                   weights: dict[str, float]) -> tuple[list[np.ndarray], list[float], list[str]]:
    e0 = _eligible(grouped, origin, horizon)
    names = [name for name in ("E0", "E1_prime", "E2_prime")
             if float(weights.get(name, 0.0)) > WEIGHT_TOLERANCE]
    if "E0" not in names:
        raise ValueError("E0 anchor cannot be absent from outer distribution")
    candidates: dict[str, np.ndarray] = {"E0": e0}
    sigma_hat = _scale(runtime, origin, horizon)
    if "E1_prime" in names:
        pool = runtime["pools"][horizon]
        candidates["E1_prime"] = e1_fhs_samples(
            e0, center=pool["center"], sigma_hat=sigma_hat,
            standardized_residuals=pool["z"],
        )
    if "E2_prime" in names:
        candidates["E2_prime"] = rescale_e0_samples(
            e0, sigma_hat=sigma_hat, exponent=lambda_,
        )
    selected_weights = [float(weights[name]) for name in names]
    total = sum(selected_weights)
    if abs(total - 1.0) > 1e-12:
        raise ValueError("active frozen weights do not sum to one")
    return [candidates[name] for name in names], selected_weights, names


def _fit_calibrators(*, roles: dict[str, list[str]], lookup: dict[tuple[str, int], dict[str, Any]],
                     runtime: dict[str, Any], grouped: dict[int, list[dict[str, Any]]],
                     s1: dict[str, Any], m2: dict[str, Any]) -> dict[int, Any]:
    calibrators = {}
    for horizon in HORIZONS:
        weights = s1["horizons"][str(horizon)]["weights"]
        lambda_ = float(m2["horizons"][str(horizon)]["selected_lambda"])
        cases = []
        for origin in roles["calibration"]:
            models, active_weights, _ = _active_models(
                origin=origin, horizon=horizon, runtime=runtime, grouped=grouped,
                lambda_=lambda_, weights=weights,
            )
            cases.append(CalibrationCase(origin, "calibration",
                                         mixture_quantiles(models, active_weights),
                                         float(lookup[(origin, horizon)]["value"])))
        calibrators[horizon] = fit_cross_fit_calibrator(cases)
    return calibrators


def run_outer_gate(*, export_path: Path, m5_dir: Path, m2_summary: Path,
                   s1_summary: Path, g3_summary: Path, approval_log: Path,
                   output_dir: Path) -> dict[str, Any]:
    exposure_path = output_dir / "outer_exposure_receipt.json"
    gate_path = output_dir / "gate_decision.json"
    score_path = output_dir / "outer_score_matrix.parquet"
    if any(path.exists() for path in (exposure_path, gate_path, score_path)):
        raise RuntimeError("R5 G4 output already exists; outer retry is forbidden")

    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan, roles = export["five_role_plan"], export["five_role_plan"]["role_origins"]
    g3 = json.loads(g3_summary.read_text(encoding="utf-8"))
    s1 = json.loads(s1_summary.read_text(encoding="utf-8"))
    m2 = json.loads(m2_summary.read_text(encoding="utf-8"))
    decisions = [json.loads(line) for line in approval_log.read_text(encoding="utf-8").splitlines()
                 if line]
    approval = next((row for row in reversed(decisions)
                     if row.get("decision_id") == "G4-OUTER-ONCE" and row.get("approved") is True), None)
    if approval is None:
        raise ValueError("explicit append-only G4 approval is required")
    if not g3.get("g4_eligible") or g3.get("outer_opened") is not False:
        raise ValueError("G3 did not authorize the one-shot outer evaluation")
    if s1["role_hashes"] != plan["role_hashes"] or g3["role_hashes"] != plan["role_hashes"]:
        raise ValueError("frozen five-role hashes changed")
    if s1["row_use_counters"].get("outer_rows_used") != 0:
        raise ValueError("screening consumed outer rows")

    blocks = six_outer_blocks(roles["outer"])
    claim_outer_once(exposure_path, approval_record=approval,
                     generation_id=g3["generation_id"],
                     outer_role_hash=plan["role_hashes"]["outer"])

    runtime = _load_runtime(export, m5_dir)
    grouped, lookup = _label_inputs(export)
    calibrators = _fit_calibrators(roles=roles, lookup=lookup, runtime=runtime,
                                   grouped=grouped, s1=s1, m2=m2)
    rows: list[dict[str, Any]] = []
    outer_set = set(roles["outer"])
    # The actual is first dereferenced inside this one-shot loop, after the
    # exposure receipt and after each predictive distribution is constructed.
    for origin in roles["outer"]:
        for horizon in HORIZONS:
            label = lookup.get((origin, horizon))
            if label is None:
                raise ValueError(f"frozen outer label missing: {origin}:h{horizon}")
            weights = s1["horizons"][str(horizon)]["weights"]
            lambda_ = float(m2["horizons"][str(horizon)]["selected_lambda"])
            models, active_weights, names = _active_models(
                origin=origin, horizon=horizon, runtime=runtime, grouped=grouped,
                lambda_=lambda_, weights=weights,
            )
            raw_quantiles = mixture_quantiles(models, active_weights)
            quantiles = calibrators[horizon].calibrate_quantiles(raw_quantiles)
            actual = float(label["value"])
            model_crps = empirical_mixture_crps([[values] for values in models],
                                                [actual], active_weights)
            e0 = models[names.index("E0")]
            rows.append({
                "origin_session": origin, "horizon": horizon, "actual": actual,
                "model_crps": model_crps, "baseline_crps": empirical_crps(e0, actual),
                "p10": quantiles[1], "p25": quantiles[4], "p50": quantiles[9],
                "p75": quantiles[14], "p90": quantiles[17],
                "probability_up": probability_up(models, active_weights),
                "probability_unit": "fraction", "available_at_rule": "mature_at_on_or_before_origin",
                "sample_count": int(sum(len(values) for values in models)),
                "active_components": ",".join(names),
            })
    if len({row["origin_session"] for row in rows}) != len(outer_set):
        raise RuntimeError("outer origin coverage is incomplete")
    if len(rows) != len(roles["outer"]) * len(HORIZONS):
        raise RuntimeError("outer score coordinate count is incomplete")

    evidence = compute_gate_evidence(rows)
    deficits = evidence["gate_deficit_vector"]
    decision = "PASS" if not deficits else "HOLD_RESEARCH_GATE"
    gate = {
        "schema": "r5_g4_outer_gate_v1", "generation_id": g3["generation_id"],
        "decision": decision, "research_gate_pass": not deficits,
        "reason": None if not deficits else "RESEARCH_GATE_FAILED_REPLAN",
        "existing_gate_implementation": "ai_fc.timeseries_v7_r4.core_qualification.compute_gate_evidence",
        **evidence, "outer_blocks": blocks,
        "outer_exposure": {"count": 1, "retry_allowed": False,
                           "receipt_sha256": _sha(exposure_path)},
        "row_use_counters": {"outer_origins_used": len(roles["outer"]),
                             "outer_rows_used": len(rows), "outer_blocks_used": 6},
        "input_hashes": {"export": hashlib.sha256(raw).hexdigest(),
                         "m5": _sha(m5_dir / "selection_summary.json"),
                         "m2": _sha(m2_summary), "s1": _sha(s1_summary),
                         "g3": _sha(g3_summary)},
        "frozen_role_hashes": plan["role_hashes"],
        "grid_unchanged": True, "promotion_claimed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(score_path, index=False)
    gate["outer_score_matrix_sha256"] = _sha(score_path)
    temporary = gate_path.with_suffix(".tmp")
    temporary.write_bytes(canonical_json(gate) + b"\n")
    temporary.replace(gate_path)
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--m5-dir", type=Path, required=True)
    parser.add_argument("--m2-summary", type=Path, required=True)
    parser.add_argument("--s1-summary", type=Path, required=True)
    parser.add_argument("--g3-summary", type=Path, required=True)
    parser.add_argument("--approval-log", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_outer_gate(export_path=args.export, m5_dir=args.m5_dir,
                   m2_summary=args.m2_summary, s1_summary=args.s1_summary,
                   g3_summary=args.g3_summary, approval_log=args.approval_log,
                   output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
