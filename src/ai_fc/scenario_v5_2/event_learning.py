"""Append-only normalized macro-event learning for Scenario V5.2.

This is a research-candidate update boundary, not an online ML optimizer.  A
validated event is converted by a registered deterministic adapter, appended
without rewriting history, and then used on the next candidate rebuild.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_fc.scenario_v5.contracts import canonical_hash, canonical_json, file_hash


LEDGER_RELATIVE = Path("data/scenarios/candidates/event_learning/events.jsonl")
RECEIPTS_RELATIVE = Path("data/scenarios/candidates/event_learning/receipts")
ALLOWED_KINDS = {"cpi", "nfp", "fomc", "gdp", "earnings"}
NUMERICAL_STRENGTH = {"cpi": .15, "nfp": .15, "fomc": .15, "gdp": .12, "earnings": 0.0}


class EventLearningError(ValueError):
    """Raised when the append-only event-learning gate rejects a record."""


def _aware(value: Any, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise EventLearningError(f"{field} must be ISO timestamp") from exc
    if result.tzinfo is None:
        raise EventLearningError(f"{field} must be timezone-aware")
    return result


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventLearningError(f"{field} must be a non-boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise EventLearningError(f"{field} must be finite")
    return result


def _distribution(payload: Any, field: str) -> dict[str, float]:
    if not isinstance(payload, dict) or not payload:
        raise EventLearningError(f"{field} must be a non-empty target-range distribution")
    result = {str(key): _number(value, f"{field}.{key}") for key, value in payload.items()}
    if any(value < 0 or value > 1 for value in result.values()):
        raise EventLearningError(f"{field} probability outside [0,1]")
    if not math.isclose(sum(result.values()), 1.0, abs_tol=.0015):
        raise EventLearningError(f"{field} probabilities do not sum to one")
    return result


def _expected_target_midpoint(distribution: dict[str, float]) -> float:
    total = 0.0
    for target_range, probability in distribution.items():
        try:
            lower, upper = (float(value) for value in target_range.split("-"))
        except (TypeError, ValueError) as exc:
            raise EventLearningError(f"invalid target range: {target_range}") from exc
        total += ((lower + upper) / 2.0) * probability
    return total


def score_event(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind", ""))
    if kind not in ALLOWED_KINDS:
        raise EventLearningError(f"unsupported event kind: {kind}")
    actual = payload.get("actual")
    consensus = payload.get("consensus")
    units = payload.get("unit_metadata")
    if not isinstance(actual, dict) or not isinstance(consensus, dict) or not isinstance(units, dict):
        raise EventLearningError("actual, consensus, and unit_metadata must be objects")
    result = {
        "growth_risk": 0.0,
        "policy_relief": 0.0,
        "inflation_risk": 0.0,
        "used_numerically": kind != "earnings",
        "effective_strength": NUMERICAL_STRENGTH[kind],
        "adapter": "reference_only_without_approved_asset_mapping" if kind == "earnings" else "",
    }
    if kind in {"cpi", "nfp", "gdp"}:
        mapping = payload.get("mapping")
        if not isinstance(mapping, dict):
            raise EventLearningError("numeric surprise mapping is required")
        metric = str(mapping.get("metric", ""))
        if metric not in actual or metric not in consensus or metric not in units:
            raise EventLearningError(f"mapped metric missing from actual/consensus/unit: {metric}")
        scale = _number(mapping.get("standardization_scale"), "mapping.standardization_scale")
        if scale <= 0:
            raise EventLearningError("standardization scale must be positive")
        surprise = (_number(actual[metric], f"actual.{metric}")
                    - _number(consensus[metric], f"consensus.{metric}")) / scale
        result["surprise_z"] = surprise
        if kind == "cpi":
            result["inflation_risk"] = math.tanh(surprise)
            result["adapter"] = "inflation_surprise"
        else:
            result["growth_risk"] = math.tanh(-surprise)
            result["adapter"] = "labor_growth_surprise" if kind == "nfp" else "growth_surprise"
    elif kind == "fomc":
        if payload.get("probability_unit") != "fraction":
            raise EventLearningError("FOMC probability_unit must be explicit fraction")
        distributions = payload.get("rate_distributions")
        if not isinstance(distributions, dict):
            raise EventLearningError("FOMC rate_distributions required")
        pre = _distribution(distributions.get("pre"), "rate_distributions.pre")
        post = _distribution(distributions.get("post"), "rate_distributions.post")
        delta = _expected_target_midpoint(post) - _expected_target_midpoint(pre)
        result["expected_target_midpoint_delta"] = delta
        result["policy_relief"] = math.tanh(-delta / .25)
        result["adapter"] = "full_target_distribution_repricing"
    return result


def validate_event(payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    required = {
        "event_id", "revision_id", "kind", "reference_period", "published_at",
        "available_at", "as_of", "retrieved_at", "source_url", "source_sha256", "actual",
        "consensus", "unit_metadata",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise EventLearningError("missing event fields: " + ", ".join(missing))
    identifier_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    if not identifier_pattern.fullmatch(str(payload["event_id"])) \
            or not identifier_pattern.fullmatch(str(payload["revision_id"])):
        raise EventLearningError("event_id and revision_id must be path-safe identifiers")
    published = _aware(payload["published_at"], "published_at")
    available = _aware(payload["available_at"], "available_at")
    as_of = _aware(payload["as_of"], "as_of")
    retrieved = _aware(payload["retrieved_at"], "retrieved_at")
    if published > available or available > as_of or as_of > retrieved:
        raise EventLearningError(
            "event timestamps violate published <= available <= as_of <= retrieved"
        )
    if not str(payload["source_url"]).startswith("https://"):
        raise EventLearningError("source_url must use https")
    source_hash = str(payload["source_sha256"]).lower()
    if len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash):
        raise EventLearningError("source_sha256 must be a lowercase SHA-256")
    source_path = payload.get("source_path")
    if source_path and root is not None:
        resolved_root = root.resolve()
        path = (root / str(source_path)).resolve()
        if not path.is_relative_to(resolved_root):
            raise EventLearningError("event source_path escapes repository root")
        if not path.is_file() or file_hash(path) != source_hash:
            raise EventLearningError("event source_path hash mismatch")
    scores = score_event(payload)
    normalized = dict(payload)
    supplied_record_hash = str(normalized.pop("record_sha256", ""))
    normalized["scores"] = scores
    normalized["dependency_cluster_id"] = str(
        payload.get("dependency_cluster_id") or f"event:{payload['event_id']}"
    )
    normalized["record_sha256"] = canonical_hash({
        key: value for key, value in normalized.items() if key != "record_sha256"
    })
    if supplied_record_hash and supplied_record_hash != normalized["record_sha256"]:
        raise EventLearningError("event record_sha256 mismatch")
    return normalized


def _validate_revision_chain(rows: list[dict[str, Any]]) -> None:
    by_revision: dict[str, dict[str, Any]] = {}
    superseded: set[str] = set()
    for row in rows:
        revision = str(row["revision_id"])
        if revision in by_revision:
            raise EventLearningError(f"duplicate ledger revision: {revision}")
        supersedes = str(row.get("supersedes") or "")
        if supersedes:
            if supersedes not in by_revision or supersedes in superseded:
                raise EventLearningError(f"invalid supersedes relationship: {revision}")
            if by_revision[supersedes]["event_id"] != row["event_id"]:
                raise EventLearningError("a correction cannot supersede another event_id")
            superseded.add(supersedes)
        by_revision[revision] = row


def read_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / LEDGER_RELATIVE
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventLearningError(f"invalid event ledger JSON line {line_number}") from exc
        rows.append(validate_event(row, root))
    return rows


def active_events(root: Path) -> list[dict[str, Any]]:
    rows = read_ledger(root)
    _validate_revision_chain(rows)
    by_revision = {str(row["revision_id"]): row for row in rows}
    superseded = {str(row["supersedes"]) for row in rows if row.get("supersedes")}
    return [row for revision, row in by_revision.items() if revision not in superseded]


def append_event(root: Path, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = validate_event(payload, root)
    existing = read_ledger(root)
    same = [row for row in existing if row["revision_id"] == normalized["revision_id"]]
    if same:
        if canonical_json(same[0]) != canonical_json(normalized):
            raise EventLearningError(f"append-only revision conflict: {normalized['revision_id']}")
        return same[0], False
    same_event = [row for row in existing if row["event_id"] == normalized["event_id"]]
    if same_event and not normalized.get("supersedes"):
        raise EventLearningError("correction requires explicit supersedes")
    # Validate the complete prospective chain before the append boundary.
    _validate_revision_chain([*existing, normalized])
    path = root / LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(normalized) + "\n")
    return normalized, True


def event_score_summary(root: Path) -> dict[str, Any]:
    rows = active_events(root)
    raw = {"growth_risk": 0.0, "policy_relief": 0.0, "inflation_risk": 0.0}
    for row in rows:
        scores = row["scores"]
        strength = _number(scores["effective_strength"], "effective_strength")
        for key in raw:
            raw[key] += strength * _number(scores[key], f"scores.{key}")
    return {
        "active_event_count": len(rows),
        "numerical_event_count": sum(bool(row["scores"]["used_numerically"]) for row in rows),
        "raw_weighted_scores": raw,
        "bounded_scores": {key: math.tanh(value) for key, value in raw.items()},
        "events": rows,
    }


def learn_event(root: Path, input_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EventLearningError(f"event input unreadable: {exc}") from exc
    row, appended = append_event(root, payload)
    from .artifact import build_candidate, verify_candidate
    from .audit import render_dashboard

    candidate_path, candidate, _ = build_candidate(root, force=True)
    verification = verify_candidate(root, candidate_path, replay=True)
    if not verification["ok"]:
        raise EventLearningError("event appended but candidate verification failed")
    dashboard_path = render_dashboard(root, candidate)
    receipt = {
        "revision_id": row["revision_id"],
        "event_id": row["event_id"],
        "appended": appended,
        "record_sha256": row["record_sha256"],
        "candidate_path": candidate_path.relative_to(root).as_posix(),
        "candidate_model_sha256": candidate["model_content_sha256"],
        "dashboard_path": dashboard_path.relative_to(root).as_posix(),
        "verification": verification,
    }
    receipt["receipt_sha256"] = canonical_hash(receipt)
    receipt_path = root / RECEIPTS_RELATIVE / f"{row['revision_id']}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.is_file():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing.get("record_sha256") != row["record_sha256"]:
            raise EventLearningError("learning receipt conflict")
    else:
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return receipt
