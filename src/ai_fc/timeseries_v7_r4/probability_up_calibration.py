"""Leakage-safe zero-threshold calibration and evaluation for ``P(return > 0)``."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable, Sequence
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


def _report_from_predictions(probabilities: Sequence[float], outcomes: Sequence[bool],
                             base_probabilities: Sequence[float],
                             reliability_bins: int = 10) -> dict:
    losses = tuple((p - y) ** 2 for p, y in zip(probabilities, outcomes))
    positive = tuple(loss for loss, outcome in zip(losses, outcomes) if outcome)
    negative = tuple(loss for loss, outcome in zip(losses, outcomes) if not outcome)
    if not positive or not negative:
        raise ValueError("cross-fit holdout must contain both outcome directions")
    curve = []
    for index in range(reliability_bins):
        lower, upper = index / reliability_bins, (index + 1) / reliability_bins
        members = [(p, y) for p, y in zip(probabilities, outcomes)
                   if p >= lower and (p < upper or index == reliability_bins - 1)]
        if members:
            curve.append(asdict(ReliabilityBin(
                lower, upper, len(members), sum(p for p, _ in members) / len(members),
                sum(y for _, y in members) / len(members))))
    positive_brier = sum(positive) / len(positive)
    negative_brier = sum(negative) / len(negative)
    return {
        "brier": sum(losses) / len(losses),
        "base_rate_brier": sum((p - y) ** 2 for p, y in zip(base_probabilities, outcomes))
        / len(outcomes),
        "reliability_curve": curve,
        "direction": {
            "positive_count": len(positive), "negative_count": len(negative),
            "positive_brier": positive_brier, "negative_brier": negative_brier,
            "balanced_brier": (positive_brier + negative_brier) / 2,
        },
    }


def authoritative_temporal_cross_fit(export: dict, horizon: int,
                                     *, minimum_train_size: int = 106) -> dict:
    """Evaluate expanding cross-fit predictions inside the sealed calibration role."""
    if export.get("source_store") != "authoritative_postgresql":
        raise ValueError("authoritative PostgreSQL PIT export is required")
    plan = export.get("five_role_plan")
    if not isinstance(plan, dict):
        raise ValueError("sealed five-role plan is required")
    origins = tuple(str(value) for value in plan.get("role_origins", {}).get("calibration", ()))
    labels = export.get("labels")
    if not origins or not isinstance(labels, list):
        raise ValueError("fixed calibration origins and authoritative labels are required")
    by_origin = {(str(row.get("origin_session")), int(row.get("horizon_sessions", 0))): row
                 for row in labels}
    cases = []
    for origin in origins:
        outcome = by_origin.get((origin, horizon))
        if outcome is None:
            raise ValueError(f"missing calibration outcome for {origin}:h{horizon}")
        eligible = [float(row["value"]) for row in labels
                    if int(row.get("horizon_sessions", 0)) == horizon
                    and str(row.get("origin_session", "")) < origin
                    and str(row.get("mature_at") or row.get("available_at")
                            or row.get("label_end_session") or "")[:10] <= origin]
        if not eligible:
            raise ValueError(f"no PIT-eligible history for {origin}:h{horizon}")
        window = eligible[-max(63, horizon):]
        raw_probability = sum(value > 0 for value in window) / len(window)
        cases.append(ProbabilityCase(f"h{horizon}:{origin}", "calibration",
                                     raw_probability, float(outcome["value"])))
    if minimum_train_size < 2 or minimum_train_size >= len(cases):
        raise ValueError("minimum_train_size must leave a cross-fit holdout")
    predictions, outcomes, base_probabilities = [], [], []
    for index in range(minimum_train_size, len(cases)):
        training = cases[:index]
        calibrator = fit_probability_calibrator(training)
        predictions.append(calibrator.calibrate(cases[index].probability_up))
        outcomes.append(cases[index].actual > 0)
        base_probabilities.append(calibrator.base_rate)
    report = _report_from_predictions(predictions, outcomes, base_probabilities)
    return {
        "schema_version": 1, "family": f"h{horizon}", "horizon": horizon,
        "calibration_role_origin_count": len(origins),
        "fit_role": "calibration_temporal_cross_fit",
        "evaluation_role": "calibration_cross_fit_holdout",
        "temporal_scheme": "expanding", "minimum_train_size": minimum_train_size,
        "evaluation_rows": len(predictions), "future_training_rows_used": False,
        "probability_unit": "fraction", "probability_min": min(predictions),
        "probability_max": max(predictions), "probability_bounds": "PASS",
        "available_at_rule": "fit_labels_mature_at_or_before_holdout_origin",
        "role_hashes": dict(plan.get("role_hashes", {})),
        "row_use_counters": {
            "calibration_fit_rows": len(origins), "train_fit_rows": 0,
            "selection_fit_rows": 0, "stacking_fit_rows": 0,
            "legacy_review_pack_score_rows_used": 0,
            "qualification_score_rows_used": 0, "outer_rows_used": 0,
        },
        "brier": report["brier"],
        "base_rate_brier": report["base_rate_brier"],
        "balanced_brier": report["direction"]["balanced_brier"],
        "positive_brier": report["direction"]["positive_brier"],
        "negative_brier": report["direction"]["negative_brier"],
        "reliability_curve": report["reliability_curve"],
        "report": report,
    }


def _acceptance(review_pack: Path, nested_member: str, authoritative_export: Path,
                output_dir: Path) -> dict:

    source_sha = hashlib.sha256(review_pack.read_bytes()).hexdigest()
    with zipfile.ZipFile(review_pack) as outer:
        nested = outer.read(nested_member)
    with zipfile.ZipFile(io.BytesIO(nested)) as evidence:
        evidence_members_hash = hashlib.sha256(
            "\n".join(sorted(evidence.namelist())).encode()).hexdigest()
    export_bytes = authoritative_export.read_bytes()
    export = json.loads(export_bytes)
    export_sha = hashlib.sha256(export_bytes).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for horizon in (1, 5, 21, 63):
        key_payload = f"{source_sha}|{export_sha}|h{horizon}|probability-up-r4-v2"
        checkpoint_sha = hashlib.sha256(key_payload.encode()).hexdigest()
        checkpoint = output_dir / "checkpoints" / f"h{horizon}-{checkpoint_sha}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint.exists():
            reports.append(json.loads(checkpoint.read_text(encoding="utf-8")))
            continue
        payload = authoritative_temporal_cross_fit(export, horizon)
        payload.update({"source_sha256": source_sha,
                        "authoritative_export_sha256": export_sha})
        checkpoint.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reports.append(payload)
    role_hashes = export["five_role_plan"]["role_hashes"]
    source = {
        "r4_snapshot_hash": export["snapshot_hash"],
        "r4_snapshot_artifact_sha256": export_sha,
        "g2_artifact_sha256": "3e19f5dc4360b0a74de41a7d4c54967597853b12c81689c57fbc34c281972523",
        "calibration_role_hash": role_hashes["calibration"],
        "legacy_review_pack_score_rows_used": 0, "qualification_score_rows_used": 0,
        "outer_rows_used": 0, "outer_origin_intersection": 0,
    }
    summary = {
        "schema_version": 1, "schema": "r4_probability_up_calibration_v2",
        "supersedes_sha256": "532848611a9297eaf5c59bc27c13382f2e3fbd3f59c02d892073323076c9868c",
        "source": source, "source_sha256": source_sha,
        "evidence_members_hash": evidence_members_hash,
        "role_hashes": role_hashes, "families": reports,
        "row_use_counters": reports[0]["row_use_counters"],
    }
    (output_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def append_corrected_summary_revision(output_dir: Path) -> Path:
    """Preserve an incomplete receipt and append its schema-complete read model."""
    summary_path = output_dir / "acceptance_summary.json"
    original = summary_path.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    revisions = output_dir / "revisions"
    revisions.mkdir(parents=True, exist_ok=True)
    archived = revisions / f"{original_sha}.json"
    if not archived.exists():
        archived.write_bytes(original)
    payload = json.loads(original)
    for family in payload["families"]:
        report = family["report"]
        family.update({
            "brier": report["brier"],
            "base_rate_brier": report["base_rate_brier"],
            "balanced_brier": report["direction"]["balanced_brier"],
            "positive_brier": report["direction"]["positive_brier"],
            "negative_brier": report["direction"]["negative_brier"],
            "reliability_curve": report["reliability_curve"],
        })
    payload["receipt_revision_supersedes_sha256"] = original_sha
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return archived


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack", required=True, type=Path)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--authoritative-export", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    _acceptance(args.review_pack, args.nested_member, args.authoritative_export, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
