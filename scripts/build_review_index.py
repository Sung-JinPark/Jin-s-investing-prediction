"""Build a deterministic integrity index for public review ZIP artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "reports/reviews"
INDEX_PATH = REVIEW_ROOT / "INDEX.json"
LOCAL_ONLY = REVIEW_ROOT / "archive/local_only"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _sidecar_status(path: Path, digest: str) -> str:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.is_file():
        return "missing"
    fields = sidecar.read_text(encoding="utf-8").strip().split()
    if len(fields) < 2 or fields[1] != path.name:
        return "invalid"
    return "verified" if fields[0].lower() == digest else "mismatch"


def _zip_record(path: Path) -> dict[str, Any]:
    digest = _sha256(path)
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        member_count = len(archive.infolist())
    if bad_member is not None:
        raise ValueError(f"ZIP CRC failure: {_relative(path)}::{bad_member}")
    return {
        "path": _relative(path),
        "bytes": path.stat().st_size,
        "sha256": digest,
        "zip_member_count": member_count,
        "zip_crc": "pass",
        "sidecar": _sidecar_status(path, digest),
    }


def build_index() -> dict[str, Any]:
    packages = [
        _zip_record(path)
        for path in sorted(REVIEW_ROOT.rglob("*.zip"))
        if LOCAL_ONLY not in path.parents
    ]
    extracted = []
    extracted_root = REVIEW_ROOT / "archive/extracted"
    if extracted_root.is_dir():
        for path in sorted(item for item in extracted_root.iterdir() if item.is_dir()):
            extracted.append({
                "path": _relative(path),
                "file_count": sum(1 for item in path.rglob("*") if item.is_file()),
            })
    return {
        "schema_version": 1,
        "review_root": _relative(REVIEW_ROOT),
        "public_zip_count": len(packages),
        "packages": packages,
        "extracted_snapshots": extracted,
        "excluded": [
            "reports/reviews/archive/local_only",
            "dualdb/data/raw",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_index(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not INDEX_PATH.is_file() or INDEX_PATH.read_text(encoding="utf-8") != expected:
            print(f"review index drift: {_relative(INDEX_PATH)}", file=sys.stderr)
            return 1
        print(f"review index current: {_relative(INDEX_PATH)}")
        return 0
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"generated: {_relative(INDEX_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
