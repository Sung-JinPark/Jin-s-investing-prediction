"""Build and independently verify the Scenario V4 PR3A review package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_RELATIVE = Path("reports/md/scenario_v4_pr3a_review_package_260807")
ZIP_RELATIVE = Path("reports/md/scenario_v4_pr3a_review_package_260807.zip")
ZIP_SHA_RELATIVE = Path("reports/md/scenario_v4_pr3a_review_package_260807.zip.sha256")
MANIFEST_NAME = "MANIFEST.jsonl"
OFFICIAL_RELATIVE = Path("data/scenarios/nasdaq_latest.json")
RETIRED_RELATIVE = Path(
    "data/scenarios/shadow/archive/rcfhs_sb_v1_misidentified_20260807_cd2bb86b.json"
)
RETIREMENT_RECEIPT_RELATIVE = Path(
    "data/scenarios/shadow/archive/rcfhs_sb_v1_retirement_receipt.json"
)
CANDIDATE_RELATIVE = Path(
    "data/scenarios/shadow/legacy_gbm_actual_member_v1_latest.json"
)
OFFICIAL_SHA256 = "7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c"
RETIRED_SHA256 = "cd2bb86b37b2e9cbe6c5c370e3bbd3cc6f21a8953727732c8b4fc27590ee70ca"
CANDIDATE_FILE_SHA256 = "922a3c7c2200f2a55f360becdc29c0d190104bc70e1bf80a4de28cb08c843411"
CANDIDATE_CANONICAL_SHA256 = (
    "2b0895ccc58ec44b585305f0afa6b974aa15546d05676af0250e75044c68ed57"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "command": subprocess.list2cmdline(args),
        "exit_code": completed.returncode,
        "stdout": completed.stdout if completed.stdout else "NO_STDOUT\n",
        "stderr": completed.stderr if completed.stderr else "NO_STDERR\n",
    }


def changed_paths() -> list[dict[str, str]]:
    result = run_command(["git", "diff", "--name-status", "HEAD"])
    if result["exit_code"] != 0:
        raise RuntimeError(result["stderr"])
    rows: list[dict[str, str]] = []
    for line in result["stdout"].splitlines():
        parts = line.split("\t")
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) == 3:
            rows.append({"status": status, "path": parts[2], "source_path": parts[1]})
        elif len(parts) == 2:
            rows.append({"status": status, "path": parts[1], "source_path": ""})
    return rows


def is_allowed_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    exact = {
        "AGENTS.md",
        "src/ai_fc/scenario_v4_shadow.py",
        "src/ai_fc/cli.py",
        "src/ai_fc/dashboard.py",
        "src/ai_fc/read_model_contract.py",
        "src/ai_fc/dashboard_parts/dashboard.js",
        "src/ai_fc/dashboard_parts/dashboard.css",
        "src/tests/test_scenario_representative.py",
        "src/tests/test_dashboard.py",
        "src/tests/test_read_model_contract.py",
        "tools/reproduce_scenario_snapshot.py",
        "tools/verify_scenario_shadow_package.py",
        # Necessary paired contract-test update omitted by the supplied allowlist.
        "src/tests/test_scenario_v4_shadow.py",
    }
    prefixes = (
        "prompts/scenario_v4/",
        "docs/audit/phase3_260807/",
        "reports/md/",
        "data/scenarios/shadow/",
        "src/ai_fc/scenario_shadow/",
    )
    if normalized in exact or normalized.startswith(prefixes):
        return True
    name = Path(normalized).name
    parent = Path(normalized).parent.as_posix()
    return parent == "src/tests" and (
        name.startswith("test_scenario_shadow_")
        or name.startswith("test_scenario_legacy_")
    ) and name.endswith(".py")


def assert_scope(rows: list[dict[str, str]]) -> dict[str, Any]:
    excluded_generated = (
        PACKAGE_RELATIVE.as_posix(),
        ZIP_RELATIVE.as_posix(),
        ZIP_SHA_RELATIVE.as_posix(),
    )
    checked = [row for row in rows if row["path"] not in excluded_generated]
    violations = [row for row in checked if not is_allowed_path(row["path"])]
    if violations:
        raise RuntimeError(f"changed paths outside PR3A scope: {violations}")
    return {
        "status": "pass_with_documented_exception",
        "checked_count": len(checked),
        "violations": [],
        "documented_allowlist_omission": "src/tests/test_scenario_v4_shadow.py",
        "reason": "paired behavior tests for the explicitly allowed compatibility module",
    }


def source_diff() -> bytes:
    pathspecs = [
        ".",
        f":(exclude){PACKAGE_RELATIVE.as_posix()}/**",
        f":(exclude){ZIP_RELATIVE.as_posix()}",
        f":(exclude){ZIP_SHA_RELATIVE.as_posix()}",
    ]
    completed = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", *pathspecs],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
    if not completed.stdout:
        raise RuntimeError("source diff unexpectedly empty")
    return completed.stdout


def test_commands() -> list[tuple[str, list[str]]]:
    targeted = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/tests").glob("test_*.py")
        if path.name.startswith(("test_scenario", "test_dashboard"))
        or path.name in {"test_read_model_contract.py", "test_inventory.py"}
    )
    return [
        (
            "merge_base",
            [
                "git",
                "merge-base",
                "--is-ancestor",
                "0c14900fec2f1276e799df09f68c8270fd5d9646",
                "HEAD",
            ],
        ),
        ("legacy_reproduction", [sys.executable, "tools/reproduce_scenario_snapshot.py"]),
        ("javascript_syntax", ["node", "--check", "src/ai_fc/dashboard_parts/dashboard.js"]),
        ("targeted_pytest", [sys.executable, "-m", "pytest", *targeted, "-q"]),
        ("full_pytest", [sys.executable, "-m", "pytest", "-q"]),
        (
            "diff_check",
            [
                "git",
                "diff",
                "--check",
                "HEAD",
                "--",
                "AGENTS.md",
                "data/scenarios/shadow",
                "src/ai_fc",
                "src/tests",
                "tools/reproduce_scenario_snapshot.py",
                "tools/verify_scenario_shadow_package.py",
                "docs/audit/phase3_260807/PR3A_R1_SEMANTIC_HOTFIX_REPORT.md",
                "docs/audit/phase3_260807/PR3A_R2_LEGACY_DIAGNOSTIC_IMPLEMENTATION.md",
                "docs/audit/phase3_260807/PR3A_R2_REPRESENTATIVE_METRICS.csv",
                "docs/audit/phase3_260807/PR3A_R2_REPRODUCTION_RECEIPT.json",
                "docs/audit/phase3_260807/PR3A_R3_DASHBOARD_REPORT.md",
                "docs/audit/phase3_260807/PR3A_R4_REVIEW_PACKAGE_REPORT.md",
                "docs/audit/phase3_260807/SCENARIO_V4_PR3_R0_BASELINE_CHARACTERIZATION.md",
                "docs/audit/phase3_260807/SCENARIO_V4_PR3_R0_IMPLEMENTATION_MAP.csv",
                "docs/audit/phase3_260807/SCENARIO_V4_PR3_R0_METRICS.json",
            ],
        ),
    ]


def dynamic_receipts() -> tuple[dict[str, Any], dict[str, Any]]:
    sys.path.insert(0, str(ROOT / "src"))
    from ai_fc.scenario_shadow.legacy_actual_member import (  # noqa: PLC0415
        build_and_write_legacy_diagnostic,
    )
    from ai_fc.scenario_shadow.persistence import load_candidate  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="scenario-pr3a-review-") as temp_name:
        temp_root = Path(temp_name)
        official = temp_root / OFFICIAL_RELATIVE
        official.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / OFFICIAL_RELATIVE, official)
        candidate_path, first, first_changed = build_and_write_legacy_diagnostic(temp_root)
        first_bytes = candidate_path.read_bytes()
        _, second, second_changed = build_and_write_legacy_diagnostic(temp_root)
        second_bytes = candidate_path.read_bytes()
        noop = {
            "status": "pass" if first_changed and not second_changed and first_bytes == second_bytes else "fail",
            "first_refresh_changed": first_changed,
            "second_refresh_changed": second_changed,
            "bytes_unchanged": first_bytes == second_bytes,
            "first_file_sha256": sha256_bytes(first_bytes),
            "second_file_sha256": sha256_bytes(second_bytes),
            "first_canonical_sha256": first["reproducibility"]["canonical_payload_sha256"],
            "second_canonical_sha256": second["reproducibility"]["canonical_payload_sha256"],
        }
        payload = json.loads(official.read_text(encoding="utf-8"))
        payload["snapshot_id"] = "independent-stale-source-probe"
        official.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        stale_result = load_candidate(temp_root)
        stale = {
            "status": "pass" if stale_result.status == "stale_source" and not stale_result.display_allowed else "fail",
            "loader_status": stale_result.status,
            "display_allowed": stale_result.display_allowed,
            "reason": stale_result.reason,
        }
    if noop["status"] != "pass" or stale["status"] != "pass":
        raise RuntimeError(f"dynamic persistence checks failed: noop={noop}, stale={stale}")
    return noop, stale


def ui_receipt() -> dict[str, Any]:
    source = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    checks = {
        "explicit_shadow_banner": "LEGACY GBM ACTUAL-MEMBER · SHADOW DIAGNOSTIC" in source,
        "explicit_not_rcfhs_official_champion": "NOT RCFHS · NOT OFFICIAL · NOT CHAMPION" in source,
        "joint_unconditional_panel": "Legacy joint unconditional distribution" in source,
        "state_driven_view_model": "buildScenarioChartViewModel" in source,
        "legacy_invalid_active_label_absent": "RCFHS-SB v1 official" not in source,
        "legacy_invalid_toggle_label_absent": "RCFHS-SB v1 shadow" not in source,
        "diagnostic_wrapper_default_hidden": "data-flow-diagnostic-view hidden" in source,
    }
    return {"status": "pass" if all(checks.values()) else "fail", "checks": checks}


def artifact_receipts(official_before: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = json.loads((ROOT / CANDIDATE_RELATIVE).read_text(encoding="utf-8"))
    official_after = sha256_file(ROOT / OFFICIAL_RELATIVE)
    artifacts = {
        "status": "pass",
        "retired_artifact": {
            "relative_path": RETIRED_RELATIVE.as_posix(),
            "sha256": sha256_file(ROOT / RETIRED_RELATIVE),
            "expected_sha256": RETIRED_SHA256,
        },
        "new_candidate": {
            "relative_path": CANDIDATE_RELATIVE.as_posix(),
            "file_sha256": sha256_file(ROOT / CANDIDATE_RELATIVE),
            "expected_file_sha256": CANDIDATE_FILE_SHA256,
            "canonical_payload_sha256": candidate["reproducibility"]["canonical_payload_sha256"],
            "expected_canonical_payload_sha256": CANDIDATE_CANONICAL_SHA256,
        },
    }
    official = {
        "status": "pass" if official_before == official_after == OFFICIAL_SHA256 else "fail",
        "relative_path": OFFICIAL_RELATIVE.as_posix(),
        "before_sha256": official_before,
        "after_sha256": official_after,
        "expected_sha256": OFFICIAL_SHA256,
    }
    values = (
        artifacts["retired_artifact"]["sha256"] == RETIRED_SHA256,
        artifacts["new_candidate"]["file_sha256"] == CANDIDATE_FILE_SHA256,
        artifacts["new_candidate"]["canonical_payload_sha256"] == CANDIDATE_CANONICAL_SHA256,
        official["status"] == "pass",
    )
    if not all(values):
        artifacts["status"] = "fail"
        raise RuntimeError(f"fixed artifact/hash gate failed: {artifacts}, {official}")
    return artifacts, official


def copy_reports(package: Path) -> None:
    report_dir = package / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    names = [
        "SCENARIO_V4_PR3_R0_BASELINE_CHARACTERIZATION.md",
        "SCENARIO_V4_PR3_R0_METRICS.json",
        "SCENARIO_V4_PR3_R0_IMPLEMENTATION_MAP.csv",
        "PR3A_R1_SEMANTIC_HOTFIX_REPORT.md",
        "PR3A_R2_REPRODUCTION_RECEIPT.json",
        "PR3A_R2_REPRESENTATIVE_METRICS.csv",
        "PR3A_R2_LEGACY_DIAGNOSTIC_IMPLEMENTATION.md",
        "PR3A_R3_DASHBOARD_REPORT.md",
        "PR3A_R4_REVIEW_PACKAGE_REPORT.md",
    ]
    for name in names:
        shutil.copyfile(ROOT / "docs/audit/phase3_260807" / name, report_dir / name)


def build_manifest(package: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in package.rglob("*") if item.is_file()):
        relative = path.relative_to(package).as_posix()
        if relative == MANIFEST_NAME:
            continue
        size = path.stat().st_size
        if size <= 0:
            raise RuntimeError(f"zero-byte evidence file forbidden: {relative}")
        entries.append(
            {"relative_path": relative, "size_bytes": size, "sha256": sha256_file(path)}
        )
    manifest = "".join(json.dumps(row, sort_keys=True) + "\n" for row in entries)
    write_text(package / MANIFEST_NAME, manifest)
    return entries


def create_zip(package: Path, zip_path: Path) -> str:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in package.rglob("*") if item.is_file()):
            relative = path.relative_to(package).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temp_path, zip_path)
    return sha256_file(zip_path)


def build() -> None:
    package = ROOT / PACKAGE_RELATIVE
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    # Evidence hashes are byte contracts; disable checkout newline conversion.
    write_text(package / ".gitattributes", "* -text\n")
    official_before = sha256_file(ROOT / OFFICIAL_RELATIVE)
    rows = changed_paths()
    scope = assert_scope(rows)

    diff_path = package / "evidence/01_source.diff"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_bytes(source_diff())
    changed_path = package / "evidence/02_changed_paths.csv"
    changed_path.parent.mkdir(parents=True, exist_ok=True)
    with changed_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["status", "path", "source_path"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    write_json(package / "evidence/03_scope_gate.json", scope)

    receipts: list[dict[str, Any]] = []
    for name, command in test_commands():
        receipt = run_command(command)
        receipt["name"] = name
        receipts.append(receipt)
        write_text(
            package / f"test_logs/{name}.log",
            f"command: {receipt['command']}\nexit_code: {receipt['exit_code']}\n"
            f"--- stdout ---\n{receipt['stdout']}--- stderr ---\n{receipt['stderr']}",
        )
        if receipt["exit_code"] != 0:
            raise RuntimeError(f"command failed: {receipt['command']}")
    write_text(
        package / "evidence/04_command_receipts.jsonl",
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in receipts),
    )

    noop, stale = dynamic_receipts()
    artifacts, official = artifact_receipts(official_before)
    ui = ui_receipt()
    if ui["status"] != "pass":
        raise RuntimeError(f"UI semantic checks failed: {ui}")
    write_json(package / "evidence/05_official_hash.json", official)
    write_json(package / "evidence/06_artifact_hashes.json", artifacts)
    write_json(package / "evidence/07_noop_refresh.json", noop)
    write_json(package / "evidence/08_stale_source.json", stale)
    write_json(package / "evidence/09_ui_semantics.json", ui)
    write_json(
        package / "evidence/10_review_context.json",
        {
            "branch": run_command(["git", "branch", "--show-current"])["stdout"].strip(),
            "head": run_command(["git", "rev-parse", "HEAD"])["stdout"].strip(),
            "pr2_merge_base": "0c14900fec2f1276e799df09f68c8270fd5d9646",
            "candidate_identity": "legacy_gbm_actual_member_v1",
            "candidate_classification": ["shadow_only", "not_rcfhs", "not_official", "not_champion"],
        },
    )
    artifacts_dir = package / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for relative in (RETIRED_RELATIVE, RETIREMENT_RECEIPT_RELATIVE, CANDIDATE_RELATIVE):
        shutil.copyfile(ROOT / relative, artifacts_dir / relative.name)
    copy_reports(package)
    build_manifest(package)
    zip_hash = create_zip(package, ROOT / ZIP_RELATIVE)
    write_text(ROOT / ZIP_SHA_RELATIVE, f"{zip_hash}  {ZIP_RELATIVE.name}\n")
    verify()
    print(f"PASS package={PACKAGE_RELATIVE.as_posix()}")
    print(f"PASS zip={ZIP_RELATIVE.as_posix()} sha256={zip_hash}")


def manifest_rows(package: Path) -> list[dict[str, Any]]:
    manifest = package / MANIFEST_NAME
    if not manifest.is_file() or manifest.stat().st_size == 0:
        raise RuntimeError("manifest is missing or empty")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    paths = [row["relative_path"] for row in rows]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise RuntimeError("manifest paths must be sorted and unique")
    return rows


def verify_entries(rows: Iterable[dict[str, Any]], read: Any, names: set[str]) -> None:
    expected = {row["relative_path"] for row in rows}
    actual = names - {MANIFEST_NAME}
    if actual != expected:
        raise RuntimeError(f"package entry mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    for row in rows:
        data = read(row["relative_path"])
        if not data:
            raise RuntimeError(f"zero-byte evidence: {row['relative_path']}")
        if len(data) != row["size_bytes"]:
            raise RuntimeError(f"size mismatch: {row['relative_path']}")
        if sha256_bytes(data) != row["sha256"]:
            raise RuntimeError(f"hash mismatch: {row['relative_path']}")


def verify() -> None:
    package = ROOT / PACKAGE_RELATIVE
    rows = manifest_rows(package)
    disk_names = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    }
    verify_entries(rows, lambda name: (package / name).read_bytes(), disk_names)

    zip_path = ROOT / ZIP_RELATIVE
    with zipfile.ZipFile(zip_path) as archive:
        zip_names = {info.filename for info in archive.infolist() if not info.is_dir()}
        if MANIFEST_NAME not in zip_names:
            raise RuntimeError("ZIP manifest missing")
        zipped_rows = [
            json.loads(line)
            for line in archive.read(MANIFEST_NAME).decode("utf-8").splitlines()
            if line
        ]
        if zipped_rows != rows:
            raise RuntimeError("ZIP manifest differs from directory manifest")
        verify_entries(zipped_rows, archive.read, zip_names)

    sidecar = (ROOT / ZIP_SHA_RELATIVE).read_text(encoding="utf-8").strip().split()
    if len(sidecar) != 2 or sidecar[0] != sha256_file(zip_path) or sidecar[1] != zip_path.name:
        raise RuntimeError("ZIP SHA-256 sidecar mismatch")
    print(f"PASS entries={len(rows)}")
    print(f"PASS zip_sha256={sidecar[0]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.build:
        build()
    else:
        verify()


if __name__ == "__main__":
    main()
