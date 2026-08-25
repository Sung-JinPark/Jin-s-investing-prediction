from __future__ import annotations

import copy
import hashlib

import pytest

from ai_fc.timeseries_v6.lineage_v2 import verify_lineage


def _fixture() -> dict[str, object]:
    raw = b"123"
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "raw_bytes": {"local://object": raw},
        "raw_objects": [{
            "object_sha256": sha, "stored_sha256": sha, "decompressed_bytes": 3,
            "object_uri": "local://object", "compression": "none",
        }],
        "receipts": [{"receipt_id": "r1", "object_sha256": sha}],
        "outcomes": [{"receipt_id": "r1", "outcome_status": "parsed", "observation_count": 2}],
        "observation_versions": [
            {"observation_version_id": "v0", "observation_key_id": "k", "revision_seq": 0,
             "supersedes_observation_version_id": None, "raw_object_sha256": sha},
            {"observation_version_id": "v1", "observation_key_id": "k", "revision_seq": 1,
             "supersedes_observation_version_id": "v0", "raw_object_sha256": sha},
        ],
        "links": [
            {"receipt_id": "r1", "observation_version_id": "v0", "relation": "parsed_from"},
            {"receipt_id": "r1", "observation_version_id": "v1", "relation": "parsed_from"},
        ],
    }


def _verify(fixture: dict[str, object]):
    return verify_lineage(
        raw_objects=fixture["raw_objects"], receipts=fixture["receipts"],
        outcomes=fixture["outcomes"], observation_versions=fixture["observation_versions"],
        links=fixture["links"], object_loader=lambda uri: fixture["raw_bytes"][uri],
    )


def _codes(result) -> set[str]:
    return {item.code for item in result.findings}


def test_clean_lineage_passes() -> None:
    result = _verify(_fixture())
    assert result.passed is True
    assert result.as_dict()["finding_count"] == 0


def test_duplicate_outcome_and_fact_count_mismatch_fail() -> None:
    duplicate = _fixture()
    duplicate["outcomes"].append(copy.deepcopy(duplicate["outcomes"][0]))
    assert "terminal_outcome_cardinality" in _codes(_verify(duplicate))
    mismatch = _fixture()
    mismatch["outcomes"][0]["observation_count"] = 1
    assert "fact_count_mismatch" in _codes(_verify(mismatch))


def test_invalid_relation_and_orphan_fail() -> None:
    invalid = _fixture()
    invalid["links"][0]["relation"] = "invented"
    assert "invalid_relation" in _codes(_verify(invalid))
    orphan = _fixture()
    orphan["links"] = orphan["links"][:1]
    orphan["outcomes"][0]["observation_count"] = 1
    assert "orphan_observation_version" in _codes(_verify(orphan))


def test_revision_branch_cycle_and_sequence_gap_each_fail() -> None:
    branch = _fixture()
    branch["observation_versions"].append({
        "observation_version_id": "v1b", "observation_key_id": "k", "revision_seq": 1,
        "supersedes_observation_version_id": "v0",
        "raw_object_sha256": branch["raw_objects"][0]["object_sha256"],
    })
    branch["links"].append({"receipt_id": "r1", "observation_version_id": "v1b", "relation": "revision_evidence"})
    assert "revision_branch" in _codes(_verify(branch))

    cycle = _fixture()
    cycle["observation_versions"][0]["supersedes_observation_version_id"] = "v1"
    assert "revision_cycle" in _codes(_verify(cycle))

    gap = _fixture()
    gap["observation_versions"][1]["revision_seq"] = 2
    assert "revision_seq_gap" in _codes(_verify(gap))


def test_corrupt_raw_object_and_missing_object_fail() -> None:
    corrupt = _fixture()
    corrupt["raw_bytes"]["local://object"] = b"corrupt"
    codes = _codes(_verify(corrupt))
    assert "stored_object_hash_mismatch" in codes
    assert "raw_object_hash_mismatch" in codes

    missing = _fixture()
    missing["raw_objects"] = []
    assert "missing_raw_object" in _codes(_verify(missing))
