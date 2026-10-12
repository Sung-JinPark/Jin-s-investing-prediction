"""Immutable, replayable display derivatives of an official scenario snapshot.

Only the latest reference is mutable. The source forecast, its archive and every
previous daily display revision remain unchanged; this module never fetches data.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import scenario
from .scenario_daily_flow import DailyFlowError, build_daily_flow, validate_daily_flow
from .scenario_v5.contracts import canonical_numerical_hash


LATEST_RELATIVE_PATH = Path("data/scenarios/daily_flow/latest.json")
ARCHIVE_RELATIVE_DIR = Path("data/scenarios/daily_flow/archive")
ARTIFACT_CONTRACT = "daily_flow_artifact_v1"
MODEL_HASH_ALGORITHM = "canonical_numerical_sha256_decimal_8"
PRICE_REPLAY_ABS_TOLERANCE = 1e-8
DIAGNOSTIC_REPLAY_ABS_TOLERANCE = 1e-12
_SEAL_FIELDS = {
    "generated_at", "artifact_contract", "artifact_id", "revision", "supersedes",
    "revision_reason", "source_snapshot_path", "model_content_sha256",
    "semantic_reference", "archive_path", "model_content_hash_algorithm",
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def model_content(payload: dict[str, Any]) -> dict[str, Any]:
    """The deterministic derivative, excluding only persistence metadata."""
    return {key: deepcopy(value) for key, value in payload.items() if key not in _SEAL_FIELDS}


def _model_hash(payload: dict[str, Any], *, numerical: bool = True) -> str:
    content = model_content(payload)
    return canonical_numerical_hash(content, decimal_places=8) if numerical else canonical_hash(content)


def _replay_matches(left: Any, right: Any, path: tuple[str, ...] = ()) -> bool:
    """Explicit machine precision allowances; never alter retained output values."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _replay_matches(value, right[key], (*path, key)) for key, value in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _replay_matches(value, other, path) for value, other in zip(left, right))
    if isinstance(left, float) and isinstance(right, float):
        tolerance = PRICE_REPLAY_ABS_TOLERANCE if (
            "values" in path or "conditional_bands" in path or "point_deltas" in path
            or path[-1:] in (("end",), ("terminal",), ("maximum_absolute_delta",))
        ) else DIAGNOSTIC_REPLAY_ABS_TOLERANCE
        return math.isclose(left, right, rel_tol=0, abs_tol=tolerance)
    return type(left) is type(right) and left == right


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DailyFlowError(f"cannot read daily-flow input {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DailyFlowError(f"daily-flow JSON must be an object: {path}")
    return payload


def _relative_path(root: Path, relative: str | Path) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise DailyFlowError("daily-flow reference escapes repository root")
    return target


def _archive_path(root: Path, relative: str | Path) -> Path:
    target = _relative_path(root, relative)
    if target.parent != (root / ARCHIVE_RELATIVE_DIR).resolve() or target.suffix != ".json":
        raise DailyFlowError("daily-flow archive reference is outside its archive directory")
    return target


def _atomic_latest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _semantic_reference(payload: dict[str, Any]) -> dict[str, Any]:
    reference = {
        "contract_id": ARTIFACT_CONTRACT,
        "artifact_id": payload["artifact_id"],
        "source_snapshot_id": payload["source_snapshot_id"],
        "source_snapshot_sha256": payload["source_snapshot_sha256"],
        "input_sha256": payload["input_sha256"],
        "version": payload["version"],
        "model_content_sha256": payload["model_content_sha256"],
    }
    if payload.get("model_content_hash_algorithm"):
        reference["model_content_hash_algorithm"] = payload["model_content_hash_algorithm"]
    return reference


def _validate_seal(payload: dict[str, Any], source: dict[str, Any] | None = None) -> None:
    validate_daily_flow(payload, source_snapshot=source)
    if payload.get("artifact_contract") != ARTIFACT_CONTRACT:
        raise DailyFlowError("daily-flow artifact contract mismatch")
    if type(payload.get("revision")) is not int or payload["revision"] < 1:
        raise DailyFlowError("daily-flow archive revision is invalid")
    if payload.get("artifact_id") != f"daily-flow:{payload.get('asof')}:r{payload['revision']}":
        raise DailyFlowError("daily-flow artifact ID disagrees with revision")
    algorithm = payload.get("model_content_hash_algorithm")
    if algorithm not in (None, MODEL_HASH_ALGORITHM):
        raise DailyFlowError("unsupported daily-flow model-content hash algorithm")
    if payload.get("model_content_sha256") != _model_hash(payload, numerical=algorithm is not None):
        raise DailyFlowError("daily-flow deterministic content hash mismatch")
    if payload.get("semantic_reference") != _semantic_reference(payload):
        raise DailyFlowError("daily-flow semantic reference mismatch")
    if source is not None and payload.get("source_snapshot_sha256") != canonical_hash(source):
        raise DailyFlowError("daily-flow source snapshot hash mismatch")
    if payload.get("status") != "ok" or (payload.get("shadow") or {}).get("passed") is not True:
        raise DailyFlowError("daily-flow selection or same-input shadow validation is blocked")


def _current_source(root: Path) -> tuple[dict[str, Any], Path]:
    """Read the retained snapshot, preferring its matching immutable archive."""
    latest = root / scenario.LATEST_RELATIVE_PATH
    source = scenario.validate_scenario(_read_json(latest))
    if not source.get("snapshot_id"):
        raise DailyFlowError("daily-flow requires a registered immutable source snapshot ID")
    source_hash = canonical_hash(source)
    for path in sorted((root / scenario.ARCHIVE_RELATIVE_DIR).glob(f"{source['asof']}*.json")):
        candidate = _read_json(path)
        if canonical_hash(candidate) == source_hash:
            return source, path
    # Fixtures and older retained vintages may lack an archive. The exact content
    # hash still prevents using a changed latest source during replay or display.
    return source, latest


def _load_pointer(root: Path, path: Path | None = None) -> tuple[dict[str, Any], Path]:
    selected = path or root / LATEST_RELATIVE_PATH
    payload = _read_json(selected)
    if payload.get("artifact_contract") == ARTIFACT_CONTRACT and "dates" in payload:
        return payload, selected
    if payload.get("contract_id") != ARTIFACT_CONTRACT or payload.get("kind") != "latest_reference":
        raise DailyFlowError("daily-flow latest must be an explicit archive reference")
    archive = _archive_path(root, payload.get("archive_path", ""))
    retained = _read_json(archive)
    if payload.get("artifact_sha256") != canonical_hash(retained):
        raise DailyFlowError("daily-flow immutable archive hash mismatch")
    if payload.get("semantic_reference") != retained.get("semantic_reference"):
        raise DailyFlowError("daily-flow latest/archive semantic reference mismatch")
    return retained, archive


def build_artifact(root: Path) -> tuple[Path, dict[str, Any], bool]:
    """Append a validated derivative revision and atomically advance its pointer."""
    source, source_path = _current_source(root)
    derived = build_daily_flow(source, calendar=scenario.load_calendar_contract(root))
    validate_daily_flow(derived, source_snapshot=source)
    if derived.get("status") != "ok" or (derived.get("shadow") or {}).get("passed") is not True:
        raise DailyFlowError("daily-flow selection or same-input shadow validation is blocked")
    if derived.get("source_snapshot_sha256") != canonical_hash(source):
        raise DailyFlowError("daily-flow builder source snapshot hash mismatch")
    content_hash = _model_hash(derived)
    archives = []
    for retained in sorted((root / ARCHIVE_RELATIVE_DIR).glob(f"{source['asof']}_r*.json")):
        old = _read_json(retained)
        _validate_seal(old)
        archives.append((old, retained))
    match = next(((old, retained) for old, retained in archives
                  if old.get("model_content_hash_algorithm") == MODEL_HASH_ALGORITHM
                  and _replay_matches(model_content(old), model_content(derived))), None)
    if match is not None:
        payload, archive = match
    else:
        previous = max(archives, key=lambda item: item[0]["revision"])[0] if archives else None
        revision = previous["revision"] + 1 if previous else 1
        payload = deepcopy(derived)
        archive = root / ARCHIVE_RELATIVE_DIR / f"{source['asof']}_r{revision:03d}_{content_hash[:12]}.json"
        payload.update({
            "artifact_contract": ARTIFACT_CONTRACT,
            "artifact_id": f"daily-flow:{source['asof']}:r{revision}",
            "revision": revision,
            "supersedes": previous["artifact_id"] if previous else None,
            "revision_reason": (
                "derived_display_contract_revision" if previous and
                previous["source_snapshot_sha256"] == derived["source_snapshot_sha256"]
                else "source_snapshot_revision" if previous else "initial_derived_display"
            ),
            "source_snapshot_path": source_path.relative_to(root).as_posix(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model_content_sha256": content_hash,
            "model_content_hash_algorithm": MODEL_HASH_ALGORITHM,
            "archive_path": archive.relative_to(root).as_posix(),
        })
        payload["semantic_reference"] = _semantic_reference(payload)
        _validate_seal(payload, source)
        archive.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation makes an existing revision impossible to overwrite.
        with archive.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    pointer = {
        "schema_version": 1, "contract_id": ARTIFACT_CONTRACT,
        "kind": "latest_reference", "archive_path": archive.relative_to(root).as_posix(),
        "artifact_sha256": canonical_hash(payload),
        "semantic_reference": payload["semantic_reference"],
    }
    latest = root / LATEST_RELATIVE_PATH
    changed = not latest.exists() or _read_json(latest) != pointer
    if changed:
        _atomic_latest(latest, pointer)
    return latest, payload, changed


def verify_artifact(root: Path, path: Path | None = None, *, replay: bool = True) -> dict[str, Any]:
    """Verify source binding, immutable reference, shadow gates and exact replay."""
    try:
        payload, archive = _load_pointer(root, path)
        source_path = _relative_path(root, payload["source_snapshot_path"])
        source = scenario.validate_scenario(_read_json(source_path))
        _validate_seal(payload, source)
        if _archive_path(root, payload["archive_path"]) != archive.resolve():
            raise DailyFlowError("daily-flow archive path does not match sealed metadata")
        if payload["revision"] > 1:
            predecessors = [_read_json(item) for item in (root / ARCHIVE_RELATIVE_DIR).glob(
                f"{payload['asof']}_r{payload['revision'] - 1:03d}_*.json")]
            if len(predecessors) != 1 or predecessors[0].get("artifact_id") != payload.get("supersedes"):
                raise DailyFlowError("daily-flow revision has no unique retained superseded predecessor")
            _validate_seal(predecessors[0])
        elif payload.get("supersedes") is not None:
            raise DailyFlowError("daily-flow initial revision cannot supersede another artifact")
        replay_hash = None
        if replay:
            rebuilt = build_daily_flow(source, calendar=scenario.load_calendar_contract(root))
            validate_daily_flow(rebuilt, source_snapshot=source)
            numerical = payload.get("model_content_hash_algorithm") == MODEL_HASH_ALGORITHM
            same_content = (_replay_matches(model_content(rebuilt), model_content(payload))
                            if numerical else model_content(rebuilt) == model_content(payload))
            replay_hash = _model_hash(rebuilt, numerical=numerical)
            # A quantized hash can cross a rounding boundary after one ULP. It
            # seals retained content; declared absolute tolerances gate replay.
            if not same_content:
                raise DailyFlowError("daily-flow exact deterministic replay mismatch")
        return {"ok": True, "artifact_id": payload["artifact_id"],
                "model_content_sha256": payload["model_content_sha256"],
                "source_snapshot_id": payload["source_snapshot_id"], "replay": replay,
                "shadow_passed": True,
                "replay_model_content_sha256": replay_hash,
                "replay_quantized_hash_matches": replay_hash == payload["model_content_sha256"] if replay else None,
                "model_content_hash_algorithm": payload.get("model_content_hash_algorithm", "canonical_sha256_exact"),
                "replay_tolerances": {"representative_and_band_price_absolute": PRICE_REPLAY_ABS_TOLERANCE,
                                      "derived_float_diagnostics_absolute": DIAGNOSTIC_REPLAY_ABS_TOLERANCE,
                                      "official_serialized_shadow": "exact",
                                      "source_hash_and_member_ids": "exact"}}
    except (DailyFlowError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)], "replay": replay}


def load_daily_flow(root: Path, source_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Fail closed with an explicit reason; never substitute a weekly legacy path."""
    try:
        payload, _ = _load_pointer(root)
        source, _ = _current_source(root)
        _validate_seal(payload, source)
        if (source_snapshot.get("snapshot_id") != payload["source_snapshot_id"]
                or source_snapshot.get("asof") != payload["asof"]):
            raise DailyFlowError("daily-flow derivative does not match the displayed source vintage")
        return payload
    except (DailyFlowError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"schema_version": 1, "status": "unavailable", "probability_unit": "fraction",
                "reason": str(exc), "source_snapshot_id": source_snapshot.get("snapshot_id"),
                "asof": source_snapshot.get("asof"),
                "runtime_gate": {"display_eligible": False, "reasons": [str(exc)]}}


def dashboard_projection(root: Path, source_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bounded chart projection; full selection evidence remains in its archive.

    All three scenario arrays retain the exact daily source values. Persistence
    and selection audit details are read from the referenced immutable archive.
    """
    payload = load_daily_flow(root, source_snapshot)
    if payload.get("status") != "ok":
        return payload
    projection = {
        key: deepcopy(payload[key]) for key in (
            "schema_version", "version", "status", "source_snapshot_id",
            "source_snapshot_sha256", "input_sha256", "asof", "anchor", "calendar_end",
            "default_end_index", "dates", "probability_unit", "risk", "semantic_reference",
            "artifact_id", "generated_at", "model_content_sha256",
        )
    }
    projection.update({
        "display_projection": True,
        "display_projection_version": "daily_flow_chart_projection_v1",
        "audit_artifact_path": payload["archive_path"],
        "shadow": {"passed": payload["shadow"]["passed"], "tolerance": payload["shadow"]["tolerance"]},
        "scenarios": {},
    })
    for key, row in payload["scenarios"].items():
        fields = ("status", "reason", "probability", "probability_unit", "model_probability", "sample_count")
        projected = {name: deepcopy(row[name]) for name in fields if name in row}
        projected.update({name: deepcopy(row[name]) for name in (
            "member_path_index", "values", "conditional_bands", "end") if name in row})
        projection["scenarios"][key] = projected
    return projection
