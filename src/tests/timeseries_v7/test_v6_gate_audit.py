from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from tools import audit_v6_gate as audit


def _write_manifest_pack(path: Path, files: dict[str, bytes], *, mutate_manifest: bool = False) -> None:
    manifest = [
        {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        for name, body in sorted(files.items())
    ]
    if mutate_manifest:
        manifest[0]["sha256"] = "0" * 64
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    sha_bytes = "".join(f"{row['sha256']}  {row['path']}\n" for row in manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
        archive.writestr("MANIFEST.json", manifest_bytes)
        archive.writestr("MANIFEST.sha256", sha_bytes)


def _score_row(origin: str, horizon: int, actual: float) -> dict[str, object]:
    return {
        "origin": origin,
        "horizon": horizon,
        "actual": actual,
        "model_crps": abs(actual) + 0.01,
        "baseline_crps": abs(actual) + 0.011,
        "p10": -0.20,
        "p25": -0.05,
        "p50": 0.01,
        "p75": 0.05,
        "p90": 0.20,
        "baseline_p10": -0.19,
        "baseline_p90": 0.19,
        "up_probability": 0.55,
        "stress_regime": "tightening",
    }


def _write_score_archive(path: Path) -> None:
    start = date(2022, 1, 7)
    rows = []
    for index in range(30):
        origin = (start + timedelta(days=index * 7)).isoformat()
        actual = -0.02 if index % 2 else 0.02
        for horizon in (1, 5, 21, 63):
            rows.append(_score_row(origin, horizon, actual))
    scores = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows).encode()
    run = {"run_id": audit.EXPECTED_RUN_ID, "scores_sha256": hashlib.sha256(scores).hexdigest()}
    gate = {
        "integrity_gate": {"pass": True},
        "research_gate": {"pass": False},
        "operational_gate": {"pass": False},
        "numbers_visible": False,
        "status": "shadow_gate_hold",
    }
    verification = {
        "pit": {"pit_leakage_count": 0, "active_feature_provenance_rate": 1.0},
        "archive": {"receipt_observation_link_rate": 1.0},
        "runtime": {"contract_runtime_mismatch_count": 0},
        "operational": {
            "pass": False,
            "reasons": ["stale:fixture"],
            "fit_snapshot_compatibility": True,
            "source_specific_freshness": {"fixture": {"pass": False}},
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(audit.SCORES_PATH, scores)
        archive.writestr(audit.RUN_PATH, json.dumps(run))
        archive.writestr(audit.GATE_PATH, json.dumps(gate))
        archive.writestr(audit.VERIFY_PATH, json.dumps(verification))


def test_clean_manifest_pack_passes(tmp_path: Path) -> None:
    pack = tmp_path / "clean.zip"
    _write_manifest_pack(pack, {"one.txt": b"one", "nested/two.txt": b"two"})
    result = audit.verify_pack_integrity(pack, expected_entries=2)
    assert result["pass"] is True
    assert result["manifest_entries"] == 2


def test_manifest_tamper_fails(tmp_path: Path) -> None:
    pack = tmp_path / "tampered.zip"
    _write_manifest_pack(pack, {"one.txt": b"one"}, mutate_manifest=True)
    result = audit.verify_pack_integrity(pack, expected_entries=1)
    assert result["pass"] is False
    assert any(item.startswith("sha256:") for item in result["failures"])


def test_zip_path_traversal_and_case_collision_are_rejected(tmp_path: Path) -> None:
    pack = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("../escape.txt", b"x")
        archive.writestr("Data/A.txt", b"a")
        archive.writestr("data/a.txt", b"b")
    with zipfile.ZipFile(pack) as archive:
        result = audit.inspect_zip(archive)
    assert result["pass"] is False
    assert result["unsafe_paths"]
    assert result["case_collisions"]


def test_duplicate_zip_member_is_rejected(tmp_path: Path) -> None:
    pack = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("same.txt", b"one")
        archive.writestr("same.txt", b"two")
    with zipfile.ZipFile(pack) as archive:
        result = audit.inspect_zip(archive)
    assert result["pass"] is False
    assert result["duplicate_paths"] == ["same.txt"]


def test_invalid_score_quantile_is_rejected() -> None:
    row = _score_row("2022-01-07", 21, -0.1)
    row["p10"], row["p90"] = 0.2, -0.2
    with pytest.raises(audit.AuditError, match="invalid quantiles"):
        audit._validate_score_rows([row])


def test_score_recomputation_detects_always_up_downside(tmp_path: Path) -> None:
    pack = tmp_path / "scores.zip"
    _write_score_archive(pack)
    with zipfile.ZipFile(pack) as archive:
        rows, result = audit.recompute_scores(archive)
    assert len(rows) == 120
    assert result["direction"]["21"]["downside_true_negative_rate"] == 0
    assert result["direction"]["63"]["downside_true_negative_rate"] == 0
    assert result["research_gate_pass"] is False
    assert result["operational_gate_pass"] is False


def test_structural_audit_detects_gfc_and_purge_mismatches(tmp_path: Path) -> None:
    pack = tmp_path / "source.zip"
    backtest = b'''\nif "2008-01-01" <= origin <= "2009-06-30": return "gfc"\nsealed = np.where(dates >= "2019-01-01")[0]\ntrain = np.arange(0, index - 68)\n'''
    gate = b'''\nif len(subset) < 20 or coverage < 0.70: reasons.append("bad")\n'''
    contract = b'''\ncanonical_origin_frequency: weekly_last_completed_xnas_session\npurge_sessions: 63\nembargo_sessions: 5\n'''
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr(audit.BACKTEST_SOURCE_PATH, backtest)
        archive.writestr(audit.GATE_SOURCE_PATH, gate)
        archive.writestr(audit.CONTRACT_PATH, contract)
    origins = [(date(2019, 1, 4) + timedelta(days=index * 7)).isoformat() for index in range(80)]
    rows = [{"origin": origin, "stress_regime": "normal"} for origin in origins]
    with zipfile.ZipFile(pack) as archive:
        result = audit.structural_failures(archive, rows)
    assert result["gfc_gate"]["feasible"] is False
    assert result["purge_embargo"]["unit_match"] is False
    assert result["purge_embargo"]["sealed_grid_calendar_gap_days"]["median"] == 476


def test_protected_manifest_detects_change(tmp_path: Path) -> None:
    protected = tmp_path / "data/timeseries_v6"
    protected.mkdir(parents=True)
    target = protected / "sealed.json"
    target.write_text("before", encoding="utf-8")
    before = audit.protected_manifest(tmp_path)
    target.write_text("after", encoding="utf-8")
    after = audit.protected_manifest(tmp_path)
    comparison = audit.compare_protected(before, after)
    assert comparison["pass"] is False
    assert comparison["changed"] == ["data/timeseries_v6/sealed.json"]


def test_secret_scan_redacts_match(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text("api_key=" + "A" * 32, encoding="utf-8")
    result = audit.scan_secrets([output])
    assert result["pass"] is False
    assert result["matches"][0]["value"] == "REDACTED"


def test_stationary_bootstrap_is_deterministic() -> None:
    values = audit.np.asarray([0.1, -0.2, 0.3, -0.1])
    assert audit.stationary_bootstrap_ci(values) == audit.stationary_bootstrap_ci(values)
