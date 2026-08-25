from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("build_v6_review_pack", ROOT / "tools/build_v6_review_pack.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_two_clean_pack_builds_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    one = MODULE.build_pack(first, root=ROOT)
    two = MODULE.build_pack(second, root=ROOT)
    assert first.read_bytes() == second.read_bytes()
    assert one["zip_sha256"] == two["zip_sha256"]
    assert MODULE.verify_pack(first)["pass"] is True


def test_pack_has_fixed_metadata_manifest_and_no_cache(tmp_path: Path) -> None:
    pack = tmp_path / "pack.zip"
    MODULE.build_pack(pack, root=ROOT)
    with zipfile.ZipFile(pack) as archive:
        assert "MANIFEST.json" in archive.namelist()
        assert "MANIFEST.sha256" in archive.namelist()
        assert all(info.date_time == MODULE.FIXED_ZIP_TIME for info in archive.infolist())
        lowered = [name.lower() for name in archive.namelist()]
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in lowered)
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert len(manifest) == len(archive.namelist()) - 2
        assert any(row["path"] == "data/contracts/multivariate_timeseries_v6.yaml" for row in manifest)


def test_secret_scanner_blocks_private_key_and_real_assignment(tmp_path: Path) -> None:
    secret = tmp_path / "secret.py"
    secret.write_text("api_" + 'key="this-is-not-a-fake-key-value"\n', encoding="utf-8")
    findings = MODULE.scan_pack_secrets([("src/ai_fc/timeseries_v6/secret.py", secret)])
    assert findings == [{"path": "src/ai_fc/timeseries_v6/secret.py", "reason": "credential_assignment"}]
    fake = tmp_path / "fake.py"
    fake.write_text("api_" + 'key="fake-test-credential-123"\n', encoding="utf-8")
    assert MODULE.scan_pack_secrets([("src/tests/timeseries_v6/fake.py", fake)]) == []


def test_verify_detects_payload_tampering(tmp_path: Path) -> None:
    pack = tmp_path / "pack.zip"
    MODULE.build_pack(pack, root=ROOT)
    with zipfile.ZipFile(pack, "a", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("unexpected.txt", b"tamper")
    result = MODULE.verify_pack(pack)
    assert result["pass"] is False
    assert "manifest membership mismatch" in result["failures"]
