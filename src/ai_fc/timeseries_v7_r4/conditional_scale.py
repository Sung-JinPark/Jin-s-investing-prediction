"""Ex-ante-state conditional central and volatility scale calibration."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import zipfile

import numpy as np


@dataclass(frozen=True, slots=True)
class ScaleCase:
    case_id: str
    role: str
    ex_ante_state: str
    central: float
    actual: float
    reference_width_80: float


@dataclass(frozen=True, slots=True)
class StateScale:
    count: int
    central_scale: float
    volatility_scale: float
    half_width_50: float
    half_width_80: float
    half_width_90: float


@dataclass(frozen=True, slots=True)
class ConditionalScale:
    states: Mapping[str, StateScale]
    fitted_case_ids: tuple[str, ...]


def _higher_quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    # Finite-sample conformal order statistic; no interpolation or clipping.
    rank = max(1, int(probability * (len(ordered) + 1) + .999999999))
    return ordered[min(rank, len(ordered)) - 1]


def fit_conditional_scale(cases: Iterable[ScaleCase]) -> ConditionalScale:
    rows = tuple(cases)
    if not rows or any(row.role != "calibration" for row in rows):
        raise ValueError("conditional scale accepts calibration role cases only")
    if any(not row.case_id for row in rows) or len({row.case_id for row in rows}) != len(rows):
        raise ValueError("case_id must be present and unique")
    if any(not row.ex_ante_state for row in rows):
        raise ValueError("explicit ex-ante state is required")
    for row in rows:
        numbers = (row.central, row.actual, row.reference_width_80)
        if not all(isfinite(float(value)) for value in numbers):
            raise ValueError("scale inputs must be finite")
        if row.reference_width_80 <= 0:
            raise ValueError("reference width must be positive")
    fitted: dict[str, StateScale] = {}
    for state in sorted({row.ex_ante_state for row in rows}):
        group = tuple(row for row in rows if row.ex_ante_state == state)
        # Unit-strength ridge toward identity prevents an unidentified zero-centre scale.
        numerator = 1.0 + sum(row.central * row.actual for row in group)
        denominator = 1.0 + sum(row.central * row.central for row in group)
        central_scale = numerator / denominator
        residuals = tuple(abs(row.actual - central_scale * row.central) for row in group)
        ratios = tuple(residual / row.reference_width_80
                       for residual, row in zip(residuals, group))
        fitted[state] = StateScale(
            len(group), central_scale, _higher_quantile(ratios, .5),
            _higher_quantile(residuals, .5), _higher_quantile(residuals, .8),
            _higher_quantile(residuals, .9),
        )
    return ConditionalScale(fitted, tuple(row.case_id for row in rows))


def _coverage(rows: Sequence[ScaleCase], fitted: ConditionalScale, level: int) -> float:
    covered = 0
    for row in rows:
        scale = fitted.states[row.ex_ante_state]
        width = getattr(scale, f"half_width_{level}")
        covered += abs(row.actual - scale.central_scale * row.central) <= width
    return covered / len(rows)


def _lagged_states(rows: Sequence[dict]) -> tuple[str, ...]:
    history: list[float] = []
    result = []
    for row in rows:
        if len(history) < 20:
            result.append("normal")
        else:
            recent = sum(abs(value) for value in history[-20:]) / 20
            expanding = sum(abs(value) for value in history) / len(history)
            result.append("stress" if recent > expanding else "normal")
        # Current outcome becomes available only after this origin's state is fixed.
        history.append(float(row["actual"]))
    return tuple(result)


def authoritative_calibration_cases(
    export: Mapping[str, object], horizon: int,
) -> tuple[tuple[ScaleCase, ...], dict]:
    """Build cases from the sealed R4 calibration role, never diagnostic scores."""
    if export.get("source_store") != "authoritative_postgresql":
        raise ValueError("authoritative PostgreSQL PIT export is required")
    plan = export.get("five_role_plan")
    if not isinstance(plan, dict):
        raise ValueError("sealed five-role plan is required")
    origins_by_role = plan.get("role_origins")
    role_hashes = plan.get("role_hashes")
    if not isinstance(origins_by_role, dict) or not isinstance(role_hashes, dict):
        raise ValueError("fixed role origins and hashes are required")
    calibration_origins = tuple(str(value) for value in origins_by_role.get("calibration", ()))
    labels = export.get("labels")
    if not isinstance(labels, list):
        raise ValueError("authoritative labels are required")

    cases: list[ScaleCase] = []
    for origin in calibration_origins:
        outcome_row = next((row for row in labels
                            if str(row.get("origin_session")) == origin
                            and int(row.get("horizon_sessions", 0)) == horizon), None)
        if outcome_row is None:
            raise ValueError(f"missing calibration outcome for {origin}:h{horizon}")
        eligible = sorted(
            (str(row["origin_session"]), float(row["value"]))
            for row in labels
            if int(row.get("horizon_sessions", 0)) == horizon
            and str(row.get("origin_session", "")) < origin
            and str(row.get("mature_at") or row.get("available_at")
                    or row.get("label_end_session") or "")[:10] <= origin
        )
        values = np.asarray([value for _, value in eligible], dtype=np.float64)
        if values.size == 0 or not np.isfinite(values).all():
            raise ValueError(f"no PIT-eligible history for {origin}:h{horizon}")
        p10, central, p90 = (float(value) for value in np.quantile(
            values, (.1, .5, .9), method="linear"))
        recent = float(np.mean(np.abs(values[-20:])))
        expanding = float(np.mean(np.abs(values)))
        state = "stress" if values.size >= 20 and recent > expanding else "normal"
        cases.append(ScaleCase(f"h{horizon}:{origin}", "calibration", state,
                               central, float(outcome_row["value"]), (p90 - p10) / 2))
    counters = {
        "calibration_fit_rows": len(cases), "train_fit_rows": 0,
        "selection_fit_rows": 0, "stacking_fit_rows": 0, "outer_rows_used": 0,
        "legacy_review_pack_score_rows_used": 0, "qualification_score_rows_used": 0,
    }
    return tuple(cases), {"role_hashes": dict(role_hashes), "row_use_counters": counters}


def acceptance(review_pack: Path, nested_member: str, authoritative_export: Path,
               output_dir: Path) -> dict:

    source_sha = hashlib.sha256(review_pack.read_bytes()).hexdigest()
    with zipfile.ZipFile(review_pack) as outer:
        # Verify the declared real evidence pack, but diagnostic scores are never loaded.
        with zipfile.ZipFile(io.BytesIO(outer.read(nested_member))) as evidence:
            evidence_members_hash = hashlib.sha256(
                "\n".join(sorted(evidence.namelist())).encode()).hexdigest()
    export_bytes = authoritative_export.read_bytes()
    export = json.loads(export_bytes)
    export_sha = hashlib.sha256(export_bytes).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    families = []
    for horizon in (1, 5, 21, 63):
        key = hashlib.sha256(
            f"{source_sha}|{export_sha}|h{horizon}|conditional-scale-v2".encode()
        ).hexdigest()
        checkpoint = output_dir / "checkpoints" / f"h{horizon}-{key}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint.exists():
            families.append(json.loads(checkpoint.read_text(encoding="utf-8")))
            continue
        cases, isolation = authoritative_calibration_cases(export, horizon)
        if len(cases) != 634:
            raise ValueError(f"fixed calibration role must contain 634 origins, got {len(cases)}")
        fitted = fit_conditional_scale(cases)
        diagnostics = {str(level): _coverage(cases, fitted, level) for level in (50, 80, 90)}
        normal_rows = tuple(row for row in cases if row.ex_ante_state == "normal")
        baseline_normal_width = sum(row.reference_width_80 for row in normal_rows) / len(normal_rows)
        normal_width = fitted.states["normal"].half_width_80
        payload = {
            "schema_version": 1, "family": f"h{horizon}", "source_sha256": source_sha,
            "authoritative_export_sha256": export_sha,
            "r4_snapshot_hash": export.get("snapshot_hash"),
            "available_at_rule": "state_and_distribution_use_only_outcomes_available_at_origin",
            "calibration_rows": len(cases), "state_counts": {
                state: value.count for state, value in fitted.states.items()},
            **isolation,
            "scales": {state: asdict(value) for state, value in fitted.states.items()},
            "coverage": diagnostics,
            "normal_sharpness": {"conditional_half_width_80": normal_width,
                                 "reference_half_width_80": baseline_normal_width,
                                 "ratio": normal_width / baseline_normal_width},
        }
        checkpoint.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        families.append(payload)
    state_variation = all(
        len(row["scales"]) > 1
        and len({value["central_scale"] for value in row["scales"].values()}) > 1
        and len({value["volatility_scale"] for value in row["scales"].values()}) > 1
        for row in families
    )
    maximum_sharpness_ratio = max(
        row["normal_sharpness"]["ratio"] for row in families)
    coverage_pass = all(
        abs(row["coverage"][str(level)] - level / 100) <= .01
        for row in families for level in (50, 80, 90)
    )
    acceptance_results = {
        "scale_varies_by_ex_ante_state": state_variation,
        "normal_state_sharpness_not_destroyed": maximum_sharpness_ratio <= 1.2,
        "calibration_50_80_90_coverage_pass": coverage_pass,
    }
    if not all(acceptance_results.values()):
        raise ValueError(f"conditional scale acceptance failed: {acceptance_results}")
    summary = {"schema_version": 1, "source_sha256": source_sha,
               "evidence_members_hash": evidence_members_hash,
               "authoritative_export_sha256": export_sha,
               "r4_snapshot_hash": export.get("snapshot_hash"), "families": families,
               "role_hashes": families[0]["role_hashes"],
               "row_use_counters": families[0]["row_use_counters"],
               "acceptance": acceptance_results,
               "maximum_normal_sharpness_ratio": maximum_sharpness_ratio}
    (output_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack", required=True, type=Path)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--authoritative-export", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    acceptance(args.review_pack, args.nested_member, args.authoritative_export, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
