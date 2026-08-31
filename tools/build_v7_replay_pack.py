#!/usr/bin/env python3
"""Build a deterministic, self-contained V7 bootstrap gate replay pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


REPO = Path(__file__).resolve().parents[1]
FILES = (
    "data/contracts/multivariate_timeseries_v7.yaml",
    "data/timeseries_v7/manifests/protected_v6_baseline.json",
    "data/timeseries_v7/manifests/runtime_receipt.json",
    "locks/timeseries_v7/requirements.replay.lock",
    "containers/timeseries_v7/Dockerfile.replay",
    "migrations/timeseries_v7/0001_core.sql",
    "migrations/timeseries_v7/0001_core.down.sql",
    "src/ai_fc/timeseries_v7/__init__.py",
    "src/ai_fc/timeseries_v7/contract.py",
    "src/ai_fc/timeseries_v7/protection.py",
    "src/ai_fc/timeseries_v7/runtime.py",
    "src/ai_fc/timeseries_v7/gate_linter.py",
    "src/ai_fc/timeseries_v7/gates.py",
    "src/ai_fc/timeseries_v7/contract_runtime_audit.py",
    "src/ai_fc/timeseries_v7/models/__init__.py",
    "src/ai_fc/timeseries_v7/models/e0_anchor.py",
    "src/tests/timeseries_v7/test_v7_contract.py",
    "src/tests/timeseries_v7/test_v7_runtime.py",
    "src/tests/timeseries_v7/test_v7_gate_and_anchor.py",
    "tools/freeze_v7_runtime.py",
)
FIXED_ZIP_TIME = (2026, 8, 25, 0, 0, 0)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError(f"unsafe replay path: {name}")


def build_pack(output: Path) -> dict[str, object]:
    contents: dict[str, bytes] = {}
    for relative in FILES:
        _safe(relative)
        path = REPO / relative
        if not path.is_file():
            raise FileNotFoundError(relative)
        contents[relative] = path.read_bytes()
    readme = (
        "# NASDAQ V7 bootstrap replay\n\n"
        "This pack reproduces the frozen contract, runtime and bootstrap gate tests. "
        "It contains no private raw provider bodies and is not a model qualification PASS.\n\n"
        "Run: `PYTHONPATH=src python -m pytest src/tests/timeseries_v7 -q` using the exact lock.\n"
    ).encode()
    contents["REPLAY.md"] = readme
    manifest_rows = [
        {"path": name, "bytes": len(body), "sha256": sha(body)}
        for name, body in sorted(contents.items())
    ]
    manifest = {
        "schema_version": 1,
        "pack_type": "v7_bootstrap_offline_replay",
        "qualification_claim": False,
        "private_raw_bodies_included": False,
        "file_count": len(manifest_rows),
        "files": manifest_rows,
    }
    contents["MANIFEST.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(contents.items()):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body)
    temporary.replace(output)
    return {**manifest, "zip_sha256": sha(output.read_bytes()), "zip_bytes": output.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_pack(args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
