from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.timeseries_v7.runtime import (
    BASE_IMAGE_DIGEST,
    REQUIRED_ENVIRONMENT,
    RuntimeContractError,
    deterministic_probe,
    logical_text_hash,
    parse_exact_lock,
    runtime_identity,
    sha256_bytes,
)


REPO = Path(__file__).resolve().parents[3]
LOCK = REPO / "locks/timeseries_v7/requirements.replay.lock"
DOCKERFILE = REPO / "containers/timeseries_v7/Dockerfile.replay"


def test_replay_lock_is_exact_and_calendar_is_pinned() -> None:
    pins = parse_exact_lock(LOCK)
    assert pins["exchange-calendars"] == "4.13.2"
    assert len(pins) == 40


def test_non_exact_requirement_fails_closed(tmp_path: Path) -> None:
    lock = tmp_path / "bad.lock"
    lock.write_text("numpy>=2\n", encoding="utf-8")
    with pytest.raises(RuntimeContractError, match="non-exact"):
        parse_exact_lock(lock)


def test_runtime_identity_pins_image_python_blas_and_hashes() -> None:
    report = runtime_identity(LOCK, DOCKERFILE)
    assert report["base_image_digest"] == BASE_IMAGE_DIGEST
    assert report["python"] == "3.12.11"
    assert report["platform"] == "linux/amd64"
    assert report["determinism_environment"] == REQUIRED_ENVIRONMENT
    assert len(report["requirements_lock_sha256"]) == 64
    assert len(report["dockerfile_sha256"]) == 64


def test_logical_newline_hash_is_os_independent_but_physical_is_not() -> None:
    lf = b"alpha\nbeta\n"
    crlf = b"alpha\r\nbeta\r\n"
    assert logical_text_hash(lf) == logical_text_hash(crlf)
    assert sha256_bytes(lf) != sha256_bytes(crlf)


def test_probe_is_deterministic_and_probability_is_fraction() -> None:
    first = deterministic_probe()
    second = deterministic_probe()
    assert first == second
    assert first["canonical_sha256"] == "29186949d7ba07d2c69259cabdcf0342dfdf7f670eaeb1ee4b63b9c85cace306"
    assert all(0 <= row["probability"] <= 1 for row in first["payload"]["rows"])
