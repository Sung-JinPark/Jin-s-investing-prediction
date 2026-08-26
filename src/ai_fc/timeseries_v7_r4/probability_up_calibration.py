"""Leakage-safe zero-threshold calibration and evaluation for ``P(return > 0)``."""

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


@dataclass(frozen=True, slots=True)
class ProbabilityCase:
    case_id: str
    role: str
    probability_up: float
    actual: float


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrator:
    thresholds: tuple[float, ...]
    values: tuple[float, ...]
    base_rate: float
    fitted_case_ids: tuple[str, ...]

    def calibrate(self, probability: float) -> float:
        value = _probability(probability)
        # A right-continuous step function is deterministic and preserves order.
        for threshold, calibrated in zip(self.thresholds, self.values):
            if value <= threshold:
                return calibrated
        return self.values[-1]


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_frequency: float


@dataclass(frozen=True, slots=True)
class DirectionDiagnostics:
    positive_count: int
    negative_count: int
    positive_brier: float
    negative_brier: float
    balanced_brier: float


@dataclass(frozen=True, slots=True)
class ProbabilityCalibrationReport:
    brier: float
    base_rate: float
    base_rate_brier: float
    reliability_curve: tuple[ReliabilityBin, ...]
    direction: DirectionDiagnostics
    calibration_case_ids: tuple[str, ...]
    evaluation_case_ids: tuple[str, ...]


def fit_probability_calibrator(cases: Iterable[ProbabilityCase]) -> ProbabilityCalibrator:
    rows = _validated_cases(cases, "calibration")
    ordered = sorted((_probability(row.probability_up), float(row.actual) > 0) for row in rows)
    blocks: list[list[float]] = []  # min x, max x, successes, count
    for probability, outcome in ordered:
        blocks.append([probability, probability, float(outcome), 1.0])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([left[0], right[1], left[2] + right[2], left[3] + right[3]])
    thresholds = tuple(block[1] for block in blocks)
    values = tuple(block[2] / block[3] for block in blocks)
    return ProbabilityCalibrator(thresholds, values,
                                 sum(actual > 0 for _, actual in ordered) / len(ordered),
                                 tuple(row.case_id for row in rows))


def evaluate_probability_calibration(
    calibrator: ProbabilityCalibrator,
    cases: Iterable[ProbabilityCase],
    *,
    reliability_bins: int = 10,
) -> ProbabilityCalibrationReport:
    rows = _validated_cases(cases, "evaluation")
    if set(calibrator.fitted_case_ids) & {row.case_id for row in rows}:
        raise ValueError("calibration and evaluation evidence must be disjoint")
    if reliability_bins < 1:
        raise ValueError("reliability_bins must be positive")
    probabilities = tuple(calibrator.calibrate(row.probability_up) for row in rows)
    outcomes = tuple(float(row.actual) > 0 for row in rows)
    losses = tuple((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes))
    positive = tuple(loss for loss, outcome in zip(losses, outcomes) if outcome)
    negative = tuple(loss for loss, outcome in zip(losses, outcomes) if not outcome)
    if not positive or not negative:
        raise ValueError("evaluation evidence must contain both outcome directions")
    pos_brier, neg_brier = sum(positive) / len(positive), sum(negative) / len(negative)
    curve = []
    for index in range(reliability_bins):
        lower, upper = index / reliability_bins, (index + 1) / reliability_bins
        members = [(p, y) for p, y in zip(probabilities, outcomes)
                   if p >= lower and (p < upper or index == reliability_bins - 1)]
        if members:
            curve.append(ReliabilityBin(lower, upper, len(members),
                                        sum(p for p, _ in members) / len(members),
                                        sum(y for _, y in members) / len(members)))
    base_losses = tuple((calibrator.base_rate - outcome) ** 2 for outcome in outcomes)
    return ProbabilityCalibrationReport(
        sum(losses) / len(losses), calibrator.base_rate, sum(base_losses) / len(base_losses),
        tuple(curve), DirectionDiagnostics(len(positive), len(negative), pos_brier, neg_brier,
                                           (pos_brier + neg_brier) / 2),
        calibrator.fitted_case_ids, tuple(row.case_id for row in rows),
    )


def _validated_cases(cases: Iterable[ProbabilityCase], role: str) -> tuple[ProbabilityCase, ...]:
    rows = tuple(cases)
    if not rows:
        raise ValueError(f"at least one {role} case is required")
    if any(row.role != role for row in rows):
        raise ValueError(f"{role} boundary accepts {role} role cases only")
    if any(not row.case_id for row in rows) or len({row.case_id for row in rows}) != len(rows):
        raise ValueError("case_id must be present and unique")
    for row in rows:
        _probability(row.probability_up)
        if not isfinite(float(row.actual)):
            raise ValueError("actual must be finite")
    return rows


def _probability(value: float) -> float:
    result = float(value)
    if not isfinite(result) or not 0 <= result <= 1:
        raise ValueError("probability_up must be a fraction in [0, 1]")
    return result


def authoritative_calibration_cases(
    export: Mapping[str, object], horizon: int,
) -> tuple[tuple[ProbabilityCase, ...], dict]:
    """Construct raw P(up) cases using only PIT history and the sealed calibration role."""
    if export.get("source_store") != "authoritative_postgresql":
        raise ValueError("authoritative PostgreSQL PIT export is required")
    plan = export.get("five_role_plan")
    if not isinstance(plan, dict):
        raise ValueError("sealed five-role plan is required")
    origins_by_role, role_hashes = plan.get("role_origins"), plan.get("role_hashes")
    if not isinstance(origins_by_role, dict) or not isinstance(role_hashes, dict):
        raise ValueError("fixed role origins and hashes are required")
    labels = export.get("labels")
    if not isinstance(labels, list):
        raise ValueError("authoritative labels are required")
    cases = []
    for origin_value in origins_by_role.get("calibration", ()):
        origin = str(origin_value)
        outcome = next((row for row in labels if str(row.get("origin_session")) == origin
                        and int(row.get("horizon_sessions", 0)) == horizon), None)
        if outcome is None:
            raise ValueError(f"missing calibration outcome for {origin}:h{horizon}")
        history = [float(row["value"]) for row in labels
                   if int(row.get("horizon_sessions", 0)) == horizon
                   and str(row.get("origin_session", "")) < origin
                   and str(row.get("mature_at") or row.get("available_at")
                           or row.get("label_end_session") or "")[:10] <= origin]
        if not history or not all(isfinite(value) for value in history):
            raise ValueError(f"no PIT-eligible history for {origin}:h{horizon}")
        probability = sum(value > 0 for value in history) / len(history)
        cases.append(ProbabilityCase(f"h{horizon}:{origin}", "calibration",
                                     probability, float(outcome["value"])))
    counters = {"calibration_fit_rows": len(cases), "train_fit_rows": 0,
                "selection_fit_rows": 0, "stacking_fit_rows": 0, "outer_rows_used": 0,
                "legacy_review_pack_score_rows_used": 0, "qualification_score_rows_used": 0}
    return tuple(cases), {"role_hashes": dict(role_hashes), "row_use_counters": counters}


def _acceptance(review_pack: Path, nested_member: str, authoritative_export: Path,
                g2_artifact: Path, output_dir: Path) -> dict:

    source_sha = hashlib.sha256(review_pack.read_bytes()).hexdigest()
    with zipfile.ZipFile(review_pack) as outer:
        nested = outer.read(nested_member)
    with zipfile.ZipFile(io.BytesIO(nested)) as evidence:
        evidence_members_hash = hashlib.sha256(
            "\n".join(sorted(evidence.namelist())).encode()).hexdigest()
    export_bytes, g2_bytes = authoritative_export.read_bytes(), g2_artifact.read_bytes()
    export = json.loads(export_bytes)
    export_sha = hashlib.sha256(export_bytes).hexdigest()
    g2_sha = hashlib.sha256(g2_bytes).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for horizon in (1, 5, 21, 63):
        family, isolation = authoritative_calibration_cases(export, horizon)
        if len(family) != 634:
            raise ValueError(f"fixed calibration role must contain 634 origins, got {len(family)}")
        key_payload = f"{source_sha}|{export_sha}|{g2_sha}|h{horizon}|temporal-cross-fit-v2"
        checkpoint_sha = hashlib.sha256(key_payload.encode()).hexdigest()
        checkpoint = output_dir / f"{checkpoint_sha}.json"
        if checkpoint.exists():
            reports.append(json.loads(checkpoint.read_text(encoding="utf-8")))
            continue
        split = 106
        calibration = family[:split]
        evaluation = tuple(ProbabilityCase(row.case_id, "evaluation", row.probability_up, row.actual)
                           for row in family[split:])
        report = evaluate_probability_calibration(fit_probability_calibrator(calibration), evaluation)
        payload = {
            "schema_version": 2, "family": f"h{horizon}", "source_sha256": source_sha,
            "authoritative_export_sha256": export_sha, "g2_artifact_sha256": g2_sha,
            "r4_snapshot_hash": export.get("snapshot_hash"), **isolation,
            "split": {"rule": "temporal-cross-fit-within-fixed-calibration-role", "calibration_rows": split,
                      "evaluation_rows": len(family) - split},
            "report": asdict(report),
        }
        checkpoint.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reports.append(payload)
    summary = {"schema_version": 2, "source_sha256": source_sha,
               "evidence_members_hash": evidence_members_hash,
               "authoritative_export_sha256": export_sha, "g2_artifact_sha256": g2_sha,
               "r4_snapshot_hash": export.get("snapshot_hash"), "families": reports,
               "role_hashes": reports[0]["role_hashes"],
               "row_use_counters": reports[0]["row_use_counters"]}
    (output_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack", required=True, type=Path)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--authoritative-export", required=True, type=Path)
    parser.add_argument("--g2-artifact", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    _acceptance(args.review_pack, args.nested_member, args.authoritative_export,
                args.g2_artifact, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
