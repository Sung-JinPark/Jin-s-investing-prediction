"""Deterministic V7 replay runtime contract.

The helpers in this module intentionally avoid model imports.  They define the
byte and logical hashing boundary used by every later V7 artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any


RUNTIME_ID = "timeseries-v7-replay-python-3.12.11-linux-amd64"
PYTHON_VERSION = "3.12.11"
PLATFORM = "linux/amd64"
CALENDAR_DISTRIBUTION = "exchange-calendars"
CALENDAR_VERSION = "4.13.2"
BASE_IMAGE = "python:3.12.11-slim-bookworm"
BASE_IMAGE_DIGEST = "sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7"
REQUIRED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "TZ": "UTC",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+==[^=<>!~\s]+$")


class RuntimeContractError(ValueError):
    """The deterministic replay contract is incomplete or inconsistent."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical_text_hash(value: bytes) -> str:
    """Hash text after BOM removal and CRLF/CR normalization to LF."""

    text = value.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return sha256_bytes(text.encode("utf-8"))


def parse_exact_lock(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not PIN_RE.fullmatch(line):
            raise RuntimeContractError(f"non-exact requirement on line {number}: {line}")
        name, version = line.split("==", 1)
        normalized = name.lower().replace("_", "-")
        if normalized in pins:
            raise RuntimeContractError(f"duplicate distribution: {normalized}")
        pins[normalized] = version
    if not pins:
        raise RuntimeContractError("empty replay lock")
    if pins.get(CALENDAR_DISTRIBUTION) != CALENDAR_VERSION:
        raise RuntimeContractError("calendar distribution/version is not frozen")
    return dict(sorted(pins.items()))


def deterministic_probe() -> dict[str, Any]:
    rows = [
        {"origin": "2008-09-12", "horizon": 21, "probability": 0.375},
        {"origin": "2020-03-20", "horizon": 63, "probability": 0.625},
    ]
    payload = {
        "model_id": "shadow.nasdaq_pit_hierarchical_distribution_v7",
        "probability_space": "research_timeseries_v7_conditional",
        "probability_unit": "fraction",
        "rows": rows,
    }
    body = canonical_json_bytes(payload)
    return {
        "payload": payload,
        "canonical_sha256": sha256_bytes(body),
        "canonical_bytes": len(body),
    }


def runtime_identity(lock_path: Path, dockerfile_path: Path) -> dict[str, Any]:
    pins = parse_exact_lock(lock_path)
    probe = deterministic_probe()
    return {
        "schema_version": 1,
        "runtime_id": RUNTIME_ID,
        "python": PYTHON_VERSION,
        "platform": PLATFORM,
        "base_image": BASE_IMAGE,
        "base_image_digest": BASE_IMAGE_DIGEST,
        "requirements_lock_sha256": sha256_file(lock_path),
        "dockerfile_sha256": sha256_file(dockerfile_path),
        "locked_distribution_count": len(pins),
        "calendar": {
            "distribution": CALENDAR_DISTRIBUTION,
            "version": CALENDAR_VERSION,
        },
        "key_versions": {
            name: pins[name]
            for name in (
                "numpy",
                "pandas",
                "scipy",
                "scikit-learn",
                "exchange-calendars",
                "statsmodels",
                "psycopg",
            )
        },
        "determinism_environment": REQUIRED_ENVIRONMENT,
        "newline_contract": {
            "physical_hash": "raw_bytes_sha256",
            "logical_text_hash": "utf8_bom_removed_and_crlf_or_cr_normalized_to_lf",
            "canonical_json": "utf8_sort_keys_compact_lf_terminated_no_nan",
        },
        "probe": {key: value for key, value in probe.items() if key != "payload"},
        "network_required_for_replay": False,
        "provider_secrets_required_for_replay": False,
        "publication_credentials_present": False,
    }


def live_environment_report() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "system": platform.system(),
        "environment": {name: os.environ.get(name) for name in REQUIRED_ENVIRONMENT},
        "matches_frozen_python": platform.python_version() == PYTHON_VERSION,
        "matches_required_environment": all(
            os.environ.get(name) == value for name, value in REQUIRED_ENVIRONMENT.items()
        ),
        "executable_name": Path(sys.executable).name,
    }
