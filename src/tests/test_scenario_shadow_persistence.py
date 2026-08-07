from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ai_fc.scenario_shadow.legacy_actual_member import (
    build_and_write_legacy_diagnostic,
    build_legacy_diagnostic_payload,
)
from ai_fc.scenario_shadow.legacy_reproduction import reproduce_legacy_snapshot
from ai_fc.scenario_shadow.persistence import (
    LEGACY_DIAGNOSTIC_RELATIVE_PATH,
    canonical_payload_sha256,
    load_candidate,
    write_candidate,
)


ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_SHA = "7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c"


def _prepare_root(tmp_path: Path) -> Path:
    official_target = tmp_path / "data/scenarios/nasdaq_latest.json"
    official_target.parent.mkdir(parents=True)
    official_target.write_bytes((ROOT / "data/scenarios/nasdaq_latest.json").read_bytes())
    return tmp_path


def test_canonical_hash_excludes_receipt_time_and_code_revision() -> None:
    source_path = ROOT / "data/scenarios/nasdaq_latest.json"
    source_bytes = source_path.read_bytes()
    snapshot = json.loads(source_bytes.decode("utf-8"))
    reproduction = reproduce_legacy_snapshot(snapshot)
    payload = build_legacy_diagnostic_payload(
        root=ROOT,
        snapshot=snapshot,
        source_bytes=source_bytes,
        reproduction=reproduction,
    )
    changed = deepcopy(payload)
    payload["receipt"] = {"generated_at": "2026-01-01T00:00:00+00:00"}
    changed["receipt"] = {"generated_at": "2027-01-01T00:00:00+00:00"}
    payload["reproducibility"]["code_revision"] = "commit-a"
    payload["reproducibility"]["code_revision_dirty"] = True
    changed["reproducibility"]["code_revision"] = "commit-b"
    changed["reproducibility"]["code_revision_dirty"] = False
    assert canonical_payload_sha256(payload) == canonical_payload_sha256(changed)


def test_canonical_hash_is_same_for_same_input_config_and_seed() -> None:
    source_path = ROOT / "data/scenarios/nasdaq_latest.json"
    source_bytes = source_path.read_bytes()
    snapshot = json.loads(source_bytes.decode("utf-8"))
    first_reproduction = reproduce_legacy_snapshot(snapshot)
    second_reproduction = reproduce_legacy_snapshot(snapshot)
    first = build_legacy_diagnostic_payload(
        root=ROOT,
        snapshot=snapshot,
        source_bytes=source_bytes,
        reproduction=first_reproduction,
    )
    second = build_legacy_diagnostic_payload(
        root=ROOT,
        snapshot=snapshot,
        source_bytes=source_bytes,
        reproduction=second_reproduction,
    )
    assert canonical_payload_sha256(first) == canonical_payload_sha256(second)


def test_second_refresh_is_noop_and_latest_bytes_unchanged(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    path, first, first_changed = build_and_write_legacy_diagnostic(root)
    first_bytes = path.read_bytes()
    path2, second, second_changed = build_and_write_legacy_diagnostic(root)

    assert path2 == path
    assert first_changed is True
    assert second_changed is False
    assert path.read_bytes() == first_bytes
    assert first["reproducibility"]["canonical_payload_sha256"] == second["reproducibility"]["canonical_payload_sha256"]


def test_stale_source_is_blocked(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    build_and_write_legacy_diagnostic(root)
    official_path = root / "data/scenarios/nasdaq_latest.json"
    official = json.loads(official_path.read_text(encoding="utf-8"))
    official["snapshot_id"] = "different-source"
    official_path.write_text(json.dumps(official), encoding="utf-8")

    result = load_candidate(root)
    assert result.status == "stale_source"
    assert result.display_allowed is False
    assert result.reason == "source snapshot_id mismatch"


def test_source_sha_mismatch_marks_stale(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    build_and_write_legacy_diagnostic(root)
    official_path = root / "data/scenarios/nasdaq_latest.json"
    official = json.loads(official_path.read_text(encoding="utf-8"))
    official["audit_probe"] = "changes bytes without changing identity metadata"
    official_path.write_text(json.dumps(official), encoding="utf-8")

    result = load_candidate(root)
    assert result.status == "stale_source"
    assert result.display_allowed is False
    assert result.reason == "source snapshot_sha256 mismatch"


def test_corrupt_candidate_returns_structured_invalid_status(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    candidate = root / LEGACY_DIAGNOSTIC_RELATIVE_PATH
    candidate.parent.mkdir(parents=True)
    candidate.write_text("{not json", encoding="utf-8")

    result = load_candidate(root)
    assert result.status == "invalid"
    assert result.display_allowed is False
    assert result.reason and result.reason.startswith("invalid JSON")


def test_write_leaves_no_partial_temp_files(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    path, _, changed = build_and_write_legacy_diagnostic(root)
    assert changed is True
    assert path.exists()
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_changed_candidate_creates_immutable_archive_and_supersession_receipt(
    tmp_path: Path,
) -> None:
    root = _prepare_root(tmp_path)
    path, first, _ = build_and_write_legacy_diagnostic(root)
    first_bytes = path.read_bytes()
    first_sha = hashlib.sha256(first_bytes).hexdigest()
    changed = deepcopy(first)
    changed["config"]["audit_probe"] = "changed canonical content"

    _, second, was_changed = write_candidate(root, changed)

    archive = path.parent / "archive" / f"{path.stem}_{first_sha[:8]}.json"
    receipt_path = archive.with_suffix(".receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert was_changed is True
    assert archive.read_bytes() == first_bytes
    assert receipt == {
        "schema_version": 1,
        "record_type": "scenario_shadow_candidate_supersession",
        "append_only": True,
        "original_relative_path": LEGACY_DIAGNOSTIC_RELATIVE_PATH.as_posix(),
        "archived_relative_path": archive.relative_to(root).as_posix(),
        "archived_file_sha256": first_sha,
        "superseded_by_canonical_payload_sha256": second["reproducibility"]["canonical_payload_sha256"],
        "reason": "canonical_candidate_content_changed",
    }


def test_official_snapshot_hash_is_unchanged() -> None:
    assert hashlib.sha256(
        (ROOT / "data/scenarios/nasdaq_latest.json").read_bytes()
    ).hexdigest() == OFFICIAL_SHA
