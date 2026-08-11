"""Build the independently recomputable Scenario V5.3 acceptance evidence ZIP."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "cea5b9f47e41305fc73ce79c39269a6b2b946744"
OUTPUT = (
    ROOT / "reports/reviews/current/scenario_v5_3/"
    "AI_INVESTING_SCENARIO_V5_3_ACCEPTANCE_EVIDENCE_PACK_260811.zip"
)
FIXED_ZIP_TIME = (2026, 8, 11, 0, 0, 0)

SOURCE_FILES = (
    "README.md",
    "data/method_changes.jsonl",
    "docs/generated/read_model_v2.schema.json",
    "src/ai_fc/dashboard.py",
    "src/ai_fc/dashboard_parts/dashboard.css",
    "src/ai_fc/dashboard_parts/dashboard.js",
    "src/ai_fc/read_model_contract.py",
    "src/ai_fc/scenario_v5_2/artifact.py",
    "src/tests/test_dashboard.py",
    "src/tests/test_scenario_v5.py",
    "src/tests/test_scenario_v5_2.py",
    "scripts/build_scenario_v5_3_acceptance_evidence_pack.py",
)

REPORT_FILES = (
    "docs/audit/scenario_v5_3/ACCEPTANCE_REMEDIATION_REPORT_260811.md",
    "docs/audit/scenario_v5_3/P0_P2_GATE_MATRIX_260811.csv",
    "docs/audit/scenario_v5_3/HONESTY_SURFACE_SURVIVAL_260811.csv",
    "docs/audit/scenario_v5_3/ENVIRONMENT_NOTES_260811.txt",
    "docs/audit/scenario_v5_3/USER_REVIEW_RECEIPT_260811.md",
    "docs/audit/scenario_v5_3/LIVE_SITE_COMPARISON_260811.md",
)

DATA_FILES = (
    "data/scenarios/nasdaq_latest.json",
    "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json",
    "data/scenarios/band_calibration.csv",
    "data/method_changes.jsonl",
    "data/scenario_views/approved/scenario_v5_2_dotcom_upside_260810.json",
    "data/cross_asset/cross_asset_latest.json",
    "data/signals/scenario_tracker_latest.json",
    "data/liquidity/liquidity_latest.json",
    "data/calendar/events.csv",
)

TARGETED_TESTS = (
    "src/tests/test_dashboard.py",
    "src/tests/test_scenario_v5.py",
    "src/tests/test_scenario_v5_2.py",
    "src/tests/test_read_model_contract.py",
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    command = subprocess.list2cmdline(args)
    raw = (
        f"$ {command}\n"
        f"exit_code={completed.returncode}\n\n"
        f"[stdout]\n{completed.stdout}\n"
        f"[stderr]\n{completed.stderr}\n"
    )
    return {"command": command, "exit_code": completed.returncode, "raw": raw}


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True,
    ).stdout


def _repo_manifest() -> dict[str, Any]:
    tracked = {
        raw.decode("utf-8", errors="surrogateescape")
        for raw in _git_bytes("ls-files", "-z").split(b"\0") if raw
    }
    names = _git_bytes("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    rows = []
    for raw in names.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", errors="surrogateescape")
        if (
            relative.startswith("_site/")
            or relative == "reports/reviews/INDEX.json"
            or relative.startswith(
                "reports/reviews/current/scenario_v5_3/"
                "AI_INVESTING_SCENARIO_V5_3_ACCEPTANCE_EVIDENCE_PACK_260811.zip"
            )
        ):
            continue
        path = ROOT / relative
        if path.is_file():
            rows.append({
                "path": relative.replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "tracked": relative in tracked,
            })
    return {
        "schema_version": 1,
        "file_count": len(rows),
        "excluded_generated_outputs": [
            "_site/",
            "reports/reviews/INDEX.json",
            OUTPUT.relative_to(ROOT).as_posix(),
            OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").relative_to(ROOT).as_posix(),
        ],
        "files": rows,
    }


def _add_file(members: dict[str, bytes], relative: str, prefix: str = "") -> None:
    path = ROOT / relative
    if not path.is_file():
        raise FileNotFoundError(relative)
    name = f"{prefix}/{relative}" if prefix else relative
    members[name.replace("\\", "/")] = path.read_bytes()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _zip_write(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, payload)


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from ai_fc.scenario_v5.contracts import (  # noqa: PLC0415
        compare_protected_hashes,
        protected_hashes,
    )

    protected_before = protected_hashes(ROOT)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    node = shutil.which("node") or "node"
    python = sys.executable

    commands = {
        "static_build": _run([
            python, "-m", "ai_fc", "dashboard", "--pages-out", "_site",
        ], env=env),
        "node_check": _run([node, "--check", "src/ai_fc/dashboard_parts/dashboard.js"]),
        "targeted_pytest": _run([python, "-m", "pytest", "-q", *TARGETED_TESTS], env=env),
        "full_pytest": _run([python, "-m", "pytest", "-q"], env=env),
        "git_diff_check": _run(["git", "diff", "HEAD", "--check"]),
    }
    protected_after = protected_hashes(ROOT)
    protected_comparison = compare_protected_hashes(protected_before, protected_after)

    failures = [name for name, row in commands.items() if row["exit_code"] != 0]
    if not protected_comparison["ok"]:
        failures.append("protected_hash_comparison")

    members: dict[str, bytes] = {}
    for relative in SOURCE_FILES:
        _add_file(members, relative, "source")
    for relative in REPORT_FILES:
        _add_file(members, relative, "reports")
    for relative in DATA_FILES:
        _add_file(members, relative, "data_snapshots")
    for path in sorted((ROOT / "reports/screenshots/v53_acceptance_260811").glob("*")):
        if path.is_file():
            members[f"screenshots/{path.name}"] = path.read_bytes()
    for relative in ("_site/index.html", "_site/data.json"):
        _add_file(members, relative, "static_build")

    members["git/cea5b9f_to_worktree.patch"] = _git_bytes(
        "diff", "--binary", BASELINE, "--", ".",
        ":(exclude)reports/reviews/INDEX.json",
        ":(exclude)reports/reviews/current/scenario_v5_3/"
        "AI_INVESTING_SCENARIO_V5_3_ACCEPTANCE_EVIDENCE_PACK_260811.zip",
        ":(exclude)reports/reviews/current/scenario_v5_3/"
        "AI_INVESTING_SCENARIO_V5_3_ACCEPTANCE_EVIDENCE_PACK_260811.zip.sha256",
    )
    members["git/cea5b9f_to_head.log"] = _git_bytes(
        "log", "--reverse", "--date=iso-strict",
        "--format=%H%x09%cI%x09%s", f"{BASELINE}..HEAD",
    )
    members["git/head.txt"] = _git_bytes("rev-parse", "HEAD")
    members["git/status_porcelain.txt"] = _git_bytes("status", "--porcelain=v1")
    members["manifests/protected_before.json"] = _json_bytes(protected_before)
    members["manifests/protected_after.json"] = _json_bytes(protected_after)
    members["manifests/protected_comparison.json"] = _json_bytes(protected_comparison)
    members["manifests/repository_files.json"] = _json_bytes(_repo_manifest())
    members["logs/environment_notes.txt"] = (
        ROOT / "docs/audit/scenario_v5_3/ENVIRONMENT_NOTES_260811.txt"
    ).read_bytes()
    for name, result in commands.items():
        members[f"logs/{name}.log"] = result["raw"].encode("utf-8")
    members["logs/command_results.json"] = _json_bytes({
        "schema_version": 1,
        "all_passed": not failures,
        "failures": failures,
        "commands": {
            name: {"command": row["command"], "exit_code": row["exit_code"]}
            for name, row in commands.items()
        },
        "protected": protected_comparison,
    })

    manifest_rows = [
        {"path": name, "bytes": len(payload), "sha256": _sha256_bytes(payload)}
        for name, payload in sorted(members.items())
    ]
    manifest = {
        "schema_version": 1,
        "package": OUTPUT.name,
        "baseline": BASELINE,
        "head": _git_bytes("rev-parse", "HEAD").decode().strip(),
        "all_validation_passed": not failures,
        "member_count_excluding_manifest": len(manifest_rows),
        "members": manifest_rows,
    }
    members["MANIFEST.json"] = _json_bytes(manifest)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".zip", dir=OUTPUT.parent, delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w") as archive:
            for name, payload in sorted(members.items()):
                _zip_write(archive, name, payload)
        with zipfile.ZipFile(temporary_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError(f"ZIP CRC failure: {bad_member}")
        os.replace(temporary_path, OUTPUT)
    finally:
        temporary_path.unlink(missing_ok=True)

    digest = _sha256_file(OUTPUT)
    sidecar = OUTPUT.with_suffix(OUTPUT.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {OUTPUT.name}\n", encoding="utf-8", newline="\n")
    summary = {
        "ok": not failures,
        "output": OUTPUT.relative_to(ROOT).as_posix(),
        "bytes": OUTPUT.stat().st_size,
        "sha256": digest,
        "zip_member_count": len(members),
        "failures": failures,
        "protected_manifest": protected_after["manifest_sha256"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
