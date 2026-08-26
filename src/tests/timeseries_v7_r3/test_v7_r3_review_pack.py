from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).parents[3] / "tools" / "build_v7_r3_full_review_pack.py"
SPEC = importlib.util.spec_from_file_location("build_v7_r3_full_review_pack", TOOL_PATH)
assert SPEC and SPEC.loader
PACK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACK
SPEC.loader.exec_module(PACK)


def test_review_pack_roundtrip_and_manifest(tmp_path: Path) -> None:
    output = tmp_path / "review.zip"
    result = PACK.write_pack(output, {
        "README.md": b"review\n",
        "EVIDENCE/result.json": b'{"status":"SUCCEEDED"}\n',
    })
    assert result["manifest_pass"] is True
    assert result["secret_scan_pass"] is True
    with zipfile.ZipFile(output) as archive:
        assert "MANIFEST.json" in archive.namelist()
        assert "MANIFEST.sha256" in archive.namelist()
        assert "REVIEW/SECRET_SCAN.json" in archive.namelist()


def test_two_builds_are_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    contents = {"README.md": b"same\n", "SOURCE/tool.py": b"print('ok')\n"}
    PACK.write_pack(first, contents)
    PACK.write_pack(second, contents)
    assert first.read_bytes() == second.read_bytes()


def test_payload_tamper_is_rejected(tmp_path: Path) -> None:
    clean = tmp_path / "clean.zip"
    PACK.write_pack(clean, {"README.md": b"clean\n"})
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(clean) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "README.md":
                payload = b"changed\n"
            target.writestr(info, payload)
    with pytest.raises(PACK.PackError, match="payload hash mismatch"):
        PACK.verify_pack(tampered)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "a\\b"])
def test_unsafe_paths_are_rejected(name: str) -> None:
    with pytest.raises(PACK.PackError):
        PACK.safe_name(name)


def test_nested_zip_secret_is_detected_without_echoing_value() -> None:
    nested_buffer = io.BytesIO()
    with zipfile.ZipFile(nested_buffer, "w") as archive:
        archive.writestr("receipt.txt", "api_key=" + "z" * 32)
    result = PACK.scan_contents({"INPUTS/nested.zip": nested_buffer.getvalue()})
    assert result["secret_scan_pass"] is False
    assert result["findings"][0]["match"] == "redacted"
    assert "z" * 32 not in str(result)


def test_explicit_synthetic_security_fixture_is_recorded_as_exclusion() -> None:
    source = (
        b"def test_output_redaction_and_secret_scan_never_record_values():\n"
        b"    synthetic_fetch = True\n"
        b"    text = 'api_key=" + b"z" * 32 + b"'\n"
    )
    result = PACK.scan_contents({"SOURCE/src/tests/test_security.py": source})
    assert result["secret_scan_pass"] is True
    assert result["finding_count"] == 0
    assert result["synthetic_fixture_exclusion_count"] == 1


def test_duplicate_casefolded_nested_paths_are_rejected() -> None:
    nested_buffer = io.BytesIO()
    with zipfile.ZipFile(nested_buffer, "w") as archive:
        archive.writestr("A/file.txt", "one")
        archive.writestr("a/file.txt", "two")
    with pytest.raises(PACK.PackError, match="duplicate normalized"):
        PACK.scan_contents({"INPUTS/nested.zip": nested_buffer.getvalue()})
