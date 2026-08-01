"""Detection-only probability consistency checks; values are never auto-corrected."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ConstraintWarning:
    kind: str
    question_ids: tuple[str, ...]
    message: str


def detect_constraints(
    probabilities: dict[str, float], relationships: Iterable[dict], *,
    probability_spaces: dict[str, str] | None = None, tolerance: float = 1e-9,
) -> list[ConstraintWarning]:
    """Return violations for subset, monotonic, and exhaustive relationship records."""
    spaces = probability_spaces or {}
    warnings: list[ConstraintWarning] = []
    for relation in relationships:
        kind = relation.get("type")
        ids = tuple(relation.get("questions") or ())
        if not ids or any(question_id not in probabilities for question_id in ids):
            continue
        used_spaces = {spaces.get(question_id) for question_id in ids if spaces.get(question_id)}
        if len(used_spaces) > 1:
            warnings.append(ConstraintWarning(
                "probability_space_mismatch", ids,
                "서로 다른 probability_space는 동일 제약식에서 결합할 수 없습니다."))
            continue
        values = [probabilities[question_id] for question_id in ids]
        if kind == "subset_of" and len(ids) == 2 and values[0] > values[1] + tolerance:
            warnings.append(ConstraintWarning(
                kind, ids, f"P({ids[0]})={values[0]:.3f} > P({ids[1]})={values[1]:.3f}"))
        elif kind == "monotonic_threshold" and any(
            left < right - tolerance for left, right in zip(values, values[1:])
        ):
            warnings.append(ConstraintWarning(
                kind, ids, "높은 임계값의 확률이 낮은 임계값보다 큽니다."))
        elif kind == "mutually_exclusive_exhaustive" and abs(sum(values) - 1.0) > tolerance:
            warnings.append(ConstraintWarning(
                kind, ids, f"상호배타·완전 사건 확률 합이 {sum(values):.3f}입니다."))
    return warnings
