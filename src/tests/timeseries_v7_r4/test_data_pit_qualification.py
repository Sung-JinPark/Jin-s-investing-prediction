import io
import json
import zipfile
from hashlib import sha256

import pytest

from ai_fc.timeseries_v7_r4.data_pit_qualification import qualify_evidence_pack


def _write_pack(path, *, leakage=0, terminal_rate=1.0, latest="2026-08-24"):
    nested_buffer = io.BytesIO()
    with zipfile.ZipFile(nested_buffer, "w") as nested:
        nested.writestr("RECOMPUTED/snapshot_and_label_audit.json", json.dumps({
            "run_id": "frozen-run", "pit_leakage_count": leakage,
        }))
        nested.writestr("RECOMPUTED/receipt_audit.json", json.dumps({
            "run_id": "frozen-run", "receipt_count": 4,
            "success_count": int(4 * terminal_rate), "pass": terminal_rate == 1.0,
            "raw_hash_failures": [],
        }))
        nested.writestr("EVIDENCE/data/timeseries_v7/gates/frozen-run/data_quality_gate.json", json.dumps({
            "run_id": "frozen-run", "state": "READY", "train_allowed": True,
            "checks": {"pit_leakage_count": leakage,
                       "receipt_terminal_outcome_rate": terminal_rate,
                       "latest_target_session": latest},
        }))
        nested.writestr("EVIDENCE/data/timeseries_v7/snapshots/frozen-run/feature_manifest.json", json.dumps({
            "run_id": "frozen-run", "pit_leakage_count": leakage,
            "row_count": 10, "feature_count": 2,
            "feature_names": ["ret_1", "alfred_m2_growth_63"],
            "data_grade": ["native_pit"],
        }))
        nested.writestr("EVIDENCE/data/timeseries_v7/snapshots/frozen-run/pit_snapshot.parquet", b"source")
    with zipfile.ZipFile(path, "w") as outer:
        outer.writestr("INPUTS/evidence.zip", nested_buffer.getvalue())
    return sha256(path.read_bytes()).hexdigest()


def test_qualifies_complete_pit_evidence_without_changing_coordinates(tmp_path):
    pack = tmp_path / "pack.zip"
    digest = _write_pack(pack)

    result = qualify_evidence_pack(
        pack, nested_member="INPUTS/evidence.zip", expected_sha256=digest,
    )

    assert result["qualified"] is True
    assert result["run_id"] == "frozen-run"
    assert result["pit_violations"] == 0
    assert result["receipt_terminal_outcome_rate"] == 1.0
    assert result["freshness_pass"] is True
    assert result["lineage_pass"] is True


def test_acceptance_rematerializes_and_persists_an_r4_snapshot(monkeypatch, tmp_path):
    pack = tmp_path / "pack.zip"
    digest = _write_pack(pack)
    persisted = []

    monkeypatch.setattr(
        "ai_fc.timeseries_v7_r4.data_pit_qualification._rematerialize_r4_snapshot",
        lambda *_args, **_kwargs: ("1" * 64, "2" * 64, True, True, object()),
        raising=False,
    )
    monkeypatch.setattr(
        "ai_fc.timeseries_v7_r4.data_pit_qualification.persist_pit_snapshot",
        lambda url, snapshot: persisted.append((url, snapshot)) or True,
        raising=False,
    )

    result = qualify_evidence_pack(
        pack, nested_member="INPUTS/evidence.zip", expected_sha256=digest,
        database_url="postgresql://unit-test",
    )

    assert persisted and persisted[0][0] == "postgresql://unit-test"
    assert result["r4_snapshot_rematerialized"] is True
    assert result["source_snapshot_hash"] == "1" * 64
    assert result["r4_snapshot_hash"] == "2" * 64
    assert result["canonical_xnas_cutoff_proof"] is True
    assert result["feature_value_provenance_pass"] is True
    assert result["release_native_features_pass"] is True
    assert result["postgres_snapshot_persisted"] is True
    assert result["legacy_runtime_defects_acknowledged"] is True


@pytest.mark.parametrize("leakage,rate", [(1, 1.0), (0, 0.75)])
def test_qualification_fails_closed(leakage, rate, tmp_path):
    pack = tmp_path / "pack.zip"
    digest = _write_pack(pack, leakage=leakage, terminal_rate=rate)
    with pytest.raises(ValueError, match="qualification failed"):
        qualify_evidence_pack(pack, nested_member="INPUTS/evidence.zip", expected_sha256=digest)


def test_rejects_wrong_outer_digest_before_reading_evidence(tmp_path):
    pack = tmp_path / "pack.zip"
    _write_pack(pack)
    with pytest.raises(ValueError, match="sha256"):
        qualify_evidence_pack(pack, nested_member="INPUTS/evidence.zip", expected_sha256="0" * 64)
