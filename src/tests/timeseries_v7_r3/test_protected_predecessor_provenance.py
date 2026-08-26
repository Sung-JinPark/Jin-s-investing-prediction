from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).parents[3] / "tools" / "audit_v7_r3_predecessor_provenance.py"
SPEC = importlib.util.spec_from_file_location("audit_v7_r3_predecessor_provenance", TOOL_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode().strip()


def _init_repo(repo: Path, path: str, content: bytes) -> str:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Fixture")
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", "fixture commit")
    return _git(repo, "rev-parse", "HEAD")


def _pack(path: Path, entry: str, content: bytes) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry, content)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_normal_provenance_maps_review_pack_git_and_worktree(tmp_path: Path) -> None:
    relative = "src/example.py"
    baseline = b"print('ok')\n\n"
    current = b"print('ok')\n"
    repo = tmp_path / "repo"
    commit = _init_repo(repo, relative, current)
    pack = tmp_path / "review.zip"
    _pack(pack, relative, baseline)
    spec = {
        "entry": relative,
        "expected_commits": [commit],
        "expected_change": "trailing_blank_line_only",
    }
    entry = {"sha256": _sha(baseline), "bytes": len(baseline), "category": "test"}
    result = AUDIT.audit_one_path(
        repo, relative, spec, entry, pack,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    assert result["pass"] is True
    assert result["current"]["worktree_status"] == ""
    assert result["history"][0]["commit"] == commit


def test_pack_hash_tampering_is_rejected(tmp_path: Path) -> None:
    pack = tmp_path / "review.zip"
    _pack(pack, "src/example.py", b"one\n")
    expected = AUDIT.sha256_file(pack)
    assert AUDIT.verify_pack(pack, expected)["sha256_pass"] is True
    pack.write_bytes(pack.read_bytes() + b"tamper")
    with pytest.raises(AUDIT.AuditError, match="SHA mismatch"):
        AUDIT.verify_pack(pack, expected)


def test_duplicate_casefolded_pack_path_is_rejected(tmp_path: Path) -> None:
    pack = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("A/file.py", "one")
        archive.writestr("a/file.py", "two")
    with pytest.raises(AUDIT.AuditError, match="duplicate normalized"):
        AUDIT.verify_pack(pack, AUDIT.sha256_file(pack))


def test_baseline_sha_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"snapshot":{"entries":[]}}\n', encoding="utf-8")
    monkeypatch.setattr(AUDIT, "EXPECTED_BASELINE_SHA256", "0" * 64)
    with pytest.raises(AUDIT.AuditError, match="baseline SHA-256 mismatch"):
        AUDIT.baseline_entries(baseline)


def test_current_git_blob_mismatch_and_dirty_path_fail(tmp_path: Path) -> None:
    relative = "src/example.py"
    baseline = b"print('before')\n"
    repo = tmp_path / "repo"
    commit = _init_repo(repo, relative, b"print('after')\n")
    (repo / relative).write_bytes(b"print('dirty')\n")
    pack = tmp_path / "review.zip"
    _pack(pack, relative, baseline)
    spec = {
        "entry": relative,
        "expected_commits": [commit],
        "expected_change": "unclassified_semantic_change",
    }
    entry = {"sha256": _sha(baseline), "bytes": len(baseline)}
    result = AUDIT.audit_one_path(
        repo, relative, spec, entry, pack,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    assert result["pass"] is False
    assert result["assertions"]["current_matches_head"] is False
    assert result["assertions"]["worktree_path_clean"] is False


def test_commit_before_frozen_baseline_fails_chronology(tmp_path: Path) -> None:
    relative = "src/example.py"
    baseline = b"print('ok')\n\n"
    current = b"print('ok')\n"
    repo = tmp_path / "repo"
    commit = _init_repo(repo, relative, current)
    pack = tmp_path / "review.zip"
    _pack(pack, relative, baseline)
    spec = {
        "entry": relative,
        "expected_commits": [commit],
        "expected_change": "trailing_blank_line_only",
    }
    entry = {"sha256": _sha(baseline), "bytes": len(baseline)}
    result = AUDIT.audit_one_path(
        repo, relative, spec, entry, pack,
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    assert result["pass"] is False
    assert result["assertions"]["commits_after_baseline"] is False


def test_missing_protected_path_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    pack = tmp_path / "review.zip"
    _pack(pack, "missing.py", b"x\n")
    with pytest.raises(AUDIT.AuditError, match="protected path missing"):
        AUDIT.audit_one_path(
            repo,
            "missing.py",
            {"entry": "missing.py", "expected_commits": [], "expected_change": "x"},
            {"sha256": _sha(b"x\n"), "bytes": 2},
            pack,
            datetime(2000, 1, 1, tzinfo=timezone.utc),
        )


def test_public_ci_skip_change_is_classified_semantically() -> None:
    before = b"def test_private():\n    load_private()\n"
    after = (
        b"def _require_private_partitions():\n    pytest.skip('private archive unavailable')\n\n"
        b"def test_private():\n    _require_private_partitions()\n"
    )
    result = AUDIT.classify_diff(
        before, after, "src/tests/timeseries_v6/test_v6_research_dataset.py",
    )
    assert result["classification"] == "public_ci_private_archive_skip"
    assert result["semantic_change"] is True


def test_unapproved_restoration_decision_is_rejected() -> None:
    decision = AUDIT.correction_decision("formal-correction")
    assert decision["formal_append_only_correction_approved"] is True
    assert decision["exact_restoration_required"] is False
    with pytest.raises(AUDIT.AuditError, match="formal-correction"):
        AUDIT.correction_decision("restore")


def test_protected_manifest_detects_change(tmp_path: Path) -> None:
    target = tmp_path / "data/timeseries"
    target.mkdir(parents=True)
    file_path = target / "fact.json"
    file_path.write_text("one", encoding="utf-8")
    before = AUDIT.protected_manifest(tmp_path)
    file_path.write_text("two", encoding="utf-8")
    after = AUDIT.protected_manifest(tmp_path)
    comparison = AUDIT.compare_manifests(before, after)
    assert comparison["pass"] is False
    assert comparison["changed"] == ["data/timeseries/fact.json"]


def test_secret_scan_reports_only_redacted_location(tmp_path: Path) -> None:
    safe = tmp_path / "safe.json"
    safe.write_text('{"field":"formal-correction"}', encoding="utf-8")
    assert AUDIT.secret_scan([safe])["secret_scan_pass"] is True
    unsafe = tmp_path / "unsafe.txt"
    unsafe.write_text("api_key=" + "z" * 32, encoding="utf-8")
    result = AUDIT.secret_scan([unsafe])
    assert result["secret_scan_pass"] is False
    assert result["findings"][0]["match"] == "redacted"


def test_result_schema_keeps_next_task_stopped() -> None:
    decision = AUDIT.correction_decision("formal-correction")
    fixture = {
        "task_id": AUDIT.TASK_ID,
        "decision": decision,
        "next_task_started": False,
    }
    encoded = json.dumps(fixture)
    decoded = json.loads(encoded)
    assert decoded["task_id"] == "V7R3-P0-002"
    assert decoded["next_task_started"] is False
