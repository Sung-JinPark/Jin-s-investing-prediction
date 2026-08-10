"""Build the deterministic Scenario V5.3 UI remediation review ZIP."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = ROOT / "docs/audit/scenario_v5_3"
OUTPUT_ROOT = ROOT / "reports/reviews/current/scenario_v5_3"
PACKAGE_NAME = "AI_INVESTING_SCENARIO_V5_3_UI_REMEDIATION_REVIEW_PACK_260810.zip"
SOURCE_AUDIT_NAME = "AI_INVESTING_SCENARIO_V5_3_AUDIT_AND_REMEDIATION_PACK_260810.zip"
SOURCE_AUDIT_SHA256 = "2f5f3ac44ddc1cf4af1ecf7a98cd68ff95f246e3e71f01cd106820c2b65098c7"
FIXED_ZIP_TIME = (2026, 8, 10, 12, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info, data


def main() -> int:
    payload = {
        "PACKAGE_README_260810.md": (AUDIT_ROOT / "PACKAGE_README_260810.md").read_bytes(),
        "IMPLEMENTATION_REVIEW_260810.md": (AUDIT_ROOT / "IMPLEMENTATION_REVIEW_260810.md").read_bytes(),
        "TEST_RESULTS_260810.txt": (AUDIT_ROOT / "TEST_RESULTS_260810.txt").read_bytes(),
        "PROTECTED_HASH_COMPARISON_260810.json": (
            AUDIT_ROOT / "PROTECTED_HASH_COMPARISON_260810.json"
        ).read_bytes(),
        "README_CUSTOMER_VIEW.md": (ROOT / "README.md").read_bytes(),
        "SOURCE_AUDIT_PACK_RECEIPT.txt": (
            f"file={SOURCE_AUDIT_NAME}\nsha256={SOURCE_AUDIT_SHA256}\n"
        ).encode("utf-8"),
    }
    manifest = {
        "schema_version": 1,
        "package": PACKAGE_NAME,
        "generated_for_date": "2026-08-10",
        "files": [
            {"path": name, "bytes": len(data), "sha256": _sha256(data)}
            for name, data in sorted(payload.items())
        ],
    }
    payload["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    package = OUTPUT_ROOT / PACKAGE_NAME
    with zipfile.ZipFile(package, "w") as archive:
        for name, data in sorted(payload.items()):
            info, content = _entry(name, data)
            archive.writestr(info, content)

    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_suffix(package.suffix + ".sha256").write_text(
        f"{digest}  {package.name}\n", encoding="utf-8", newline="\n"
    )
    print(f"generated: {package.relative_to(ROOT).as_posix()}")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
