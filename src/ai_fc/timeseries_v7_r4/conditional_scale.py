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


def acceptance(review_pack: Path, nested_member: str, output_dir: Path) -> dict:
    import pyarrow.parquet as parquet

    source_sha = hashlib.sha256(review_pack.read_bytes()).hexdigest()
    with zipfile.ZipFile(review_pack) as outer:
        nested = outer.read(nested_member)
    with zipfile.ZipFile(io.BytesIO(nested)) as evidence:
        member = next(name for name in evidence.namelist() if name.endswith("/scores.parquet"))
        all_rows = parquet.read_table(io.BytesIO(evidence.read(member))).to_pylist()
    output_dir.mkdir(parents=True, exist_ok=True)
    families = []
    for horizon in sorted({int(row["horizon"]) for row in all_rows}):
        rows = sorted((row for row in all_rows if int(row["horizon"]) == horizon),
                      key=lambda row: row["origin_session"])
        split = max(20, int(len(rows) * .6))
        calibration = rows[:split]
        key = hashlib.sha256(
            f"{source_sha}|{nested_member}|{member}|h{horizon}|conditional-scale-v1|{split}".encode()
        ).hexdigest()
        checkpoint = output_dir / "checkpoints" / f"h{horizon}-{key}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint.exists():
            families.append(json.loads(checkpoint.read_text(encoding="utf-8")))
            continue
        states = _lagged_states(calibration)
        cases = tuple(ScaleCase(
            f"h{horizon}:{row['origin_session']}", "calibration", state,
            float(row["p50"]), float(row["actual"]),
            (float(row["p90"]) - float(row["p10"])) / 2,
        ) for row, state in zip(calibration, states))
        fitted = fit_conditional_scale(cases)
        diagnostics = {str(level): _coverage(cases, fitted, level) for level in (50, 80, 90)}
        normal_rows = tuple(row for row in cases if row.ex_ante_state == "normal")
        baseline_normal_width = sum(row.reference_width_80 for row in normal_rows) / len(normal_rows)
        normal_width = fitted.states["normal"].half_width_80
        payload = {
            "schema_version": 1, "family": f"h{horizon}", "source_sha256": source_sha,
            "scores_member": member, "available_at_rule": "state_uses_prior_outcomes_only",
            "calibration_rows": len(cases), "state_counts": {
                state: value.count for state, value in fitted.states.items()},
            "scales": {state: asdict(value) for state, value in fitted.states.items()},
            "coverage": diagnostics,
            "normal_sharpness": {"conditional_half_width_80": normal_width,
                                 "reference_half_width_80": baseline_normal_width,
                                 "ratio": normal_width / baseline_normal_width},
        }
        checkpoint.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        families.append(payload)
    summary = {"schema_version": 1, "source_sha256": source_sha, "families": families}
    (output_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack", required=True, type=Path)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    acceptance(args.review_pack, args.nested_member, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
