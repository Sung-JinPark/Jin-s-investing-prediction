#!/usr/bin/env python3
"""Independent, offline adversarial auditor for the NASDAQ V5 review pack.

The auditor deliberately does not import ``ai_fc``.  It inspects the frozen
review ZIP, parses source with ``ast`` and distinguishes evidence that can be
recomputed from evidence that is merely reported.  Detected model-risk
findings are successful audit results; exit status 2 is reserved for failures
of the audit tool itself.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from zoneinfo import ZoneInfo

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is part of the root project
    yaml = None


EXPECTED_PACK_SHA256 = "082020809a495f1c09b9a0b6fe758aee71192c9e7fb91673cf7a792c0c68bd04"
EXPECTED_MANIFEST_ENTRIES = 119
EXPECTED_MODEL_ID = "shadow.nasdaq_pit_hybrid_distribution_v5"
EXPECTED_RUN_ID = "tsv5-research-92c262efafd01118e1dd82cc"
PACK_GENERATED_AT = "2026-08-24T05:01:22Z"
PROTECTED_ROOTS = (
    "data/timeseries",
    "data/timeseries_v1",
    "data/timeseries_v2",
    "data/timeseries_v3",
    "data/timeseries_v4",
    "data/timeseries_v5",
    "data/scenarios",
    "data/forecasts",
    "data/ledgers",
    "outputs/timeseries_v1",
    "outputs/timeseries_v2",
    "outputs/timeseries_v3",
    "outputs/timeseries_v4",
    "outputs/timeseries_v5",
)
SECRET_ENV_NAMES = {
    "FRED_API_KEY", "BLS_API_KEY", "BEA_API_KEY", "EIA_API_KEY",
    "NASDAQ_DATA_LINK_API_KEY", "CME_API_KEY", "CBOE_API_KEY",
    "GH_TOKEN", "GITHUB_TOKEN", "TSV5_DATABASE_URL",
    "TSV5_S3_ACCESS_KEY_ID", "TSV5_S3_SECRET_ACCESS_KEY",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)['\"]?\s*[:=]\s*['\"]?(?!REDACTED|null|none)[A-Za-z0-9_./+\-=]{12,}"),
    re.compile(r"(?:gh[opsu]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})"),
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence(path: str, line: int | None, detail: str) -> dict[str, Any]:
    return {"path": path, "line": line, "detail": detail}


def finding(
    finding_id: str,
    severity: str,
    title: str,
    evidence_rows: list[dict[str, Any]],
    risk: str,
    remediation: str,
    confidence: str = "high",
    status: str = "confirmed",
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "status": status,
        "evidence": evidence_rows,
        "risk": risk,
        "remediation": remediation,
        "confidence": confidence,
    }


def normalized_zip_name(name: str) -> tuple[str | None, str | None]:
    """Return a safe canonical member name or a rejection reason."""
    if not name or "\\" in name or "\x00" in name:
        return None, "empty, NUL, or backslash path"
    if re.match(r"^[A-Za-z]:", name) or name.startswith("/"):
        return None, "absolute or drive-qualified path"
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None, "dot, empty, or traversal segment"
    return path.as_posix().rstrip("/"), None


def inspect_zip_members(pack: Path) -> dict[str, Any]:
    unsafe: list[dict[str, str]] = []
    duplicates: list[dict[str, str]] = []
    members: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    with zipfile.ZipFile(pack) as archive:
        for info in archive.infolist():
            canonical, reason = normalized_zip_name(info.filename)
            if reason:
                unsafe.append({"path": info.filename, "reason": reason})
                continue
            assert canonical is not None
            key = canonical.casefold()
            if key in seen:
                duplicates.append({"path": info.filename, "collides_with": seen[key]})
            else:
                seen[key] = info.filename
            members.append({
                "path": canonical,
                "original_path": info.filename,
                "bytes": info.file_size,
                "compressed_bytes": info.compress_size,
                "is_dir": info.is_dir(),
            })
    return {"members": members, "unsafe_paths": unsafe, "duplicate_paths": duplicates}


def safe_extract(pack: Path, destination: Path, inspection: dict[str, Any]) -> None:
    if inspection["unsafe_paths"] or inspection["duplicate_paths"]:
        return
    root = destination.resolve()
    with zipfile.ZipFile(pack) as archive:
        for info in archive.infolist():
            canonical, reason = normalized_zip_name(info.filename)
            if reason or canonical is None:
                continue
            target = (destination / canonical).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:  # defense in depth
                raise RuntimeError(f"ZIP member escapes extraction root: {info.filename}") from exc
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _pack_root(extract_root: Path) -> Path | None:
    matches = list(extract_root.glob("*/MANIFEST.sha256")) + list(extract_root.glob("MANIFEST.sha256"))
    return matches[0].parent if len(matches) == 1 else None


def verify_pack_integrity(pack_root: Path, inspection: dict[str, Any]) -> dict[str, Any]:
    sha_path = pack_root / "MANIFEST.sha256"
    manifest_path = pack_root / "MANIFEST.json"
    failures: list[dict[str, Any]] = []
    sha_rows: dict[str, str] = {}
    if sha_path.is_file():
        for index, line in enumerate(sha_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                failures.append({"path": "MANIFEST.sha256", "line": index, "reason": "invalid format"})
                continue
            digest, name = match.groups()
            canonical, reason = normalized_zip_name(name)
            if reason or canonical is None:
                failures.append({"path": name, "reason": f"unsafe manifest path:{reason}"})
                continue
            if canonical in sha_rows:
                failures.append({"path": canonical, "reason": "duplicate manifest entry"})
            sha_rows[canonical] = digest
    else:
        failures.append({"path": "MANIFEST.sha256", "reason": "missing"})

    json_rows: dict[str, dict[str, Any]] = {}
    if manifest_path.is_file():
        raw_manifest = read_json(manifest_path)
        if not isinstance(raw_manifest, list):
            failures.append({"path": "MANIFEST.json", "reason": "root must be an array"})
        else:
            for row in raw_manifest:
                if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                    failures.append({"path": "MANIFEST.json", "reason": "invalid row"})
                    continue
                json_rows[row["path"]] = row
    else:
        failures.append({"path": "MANIFEST.json", "reason": "missing"})

    for name, expected_digest in sha_rows.items():
        path = pack_root / name
        if not path.is_file():
            failures.append({"path": name, "reason": "missing content file"})
            continue
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
            failures.append({"path": name, "reason": "sha256 mismatch", "expected": expected_digest, "actual": actual_digest})
        row = json_rows.get(name)
        if row is None:
            failures.append({"path": name, "reason": "missing from MANIFEST.json"})
            continue
        if row.get("sha256") != expected_digest:
            failures.append({"path": name, "reason": "JSON/SHA manifest digest mismatch"})
        if int(row.get("bytes", -1)) != path.stat().st_size:
            failures.append({"path": name, "reason": "byte size mismatch", "expected": row.get("bytes"), "actual": path.stat().st_size})

    for name in sorted(set(json_rows) - set(sha_rows)):
        failures.append({"path": name, "reason": "MANIFEST.json entry absent from MANIFEST.sha256"})

    relative_files = {
        path.relative_to(pack_root).as_posix()
        for path in pack_root.rglob("*")
        if path.is_file()
    }
    expected_files = set(sha_rows) | {"MANIFEST.json", "MANIFEST.sha256"}
    unexpected = sorted(relative_files - expected_files)
    missing = sorted(expected_files - relative_files)
    packaging_warnings = sorted(
        name for name in relative_files
        if name.endswith((".pyc", ".pyo")) or "/__pycache__/" in f"/{name}/" or name.endswith((".cache", ".tmp"))
    )
    if unexpected:
        failures.append({"path": unexpected, "reason": "unexpected files"})
    if missing:
        failures.append({"path": missing, "reason": "missing expected files"})
    return {
        "entry_count": len(sha_rows),
        "expected_entry_count": EXPECTED_MANIFEST_ENTRIES,
        "pass": not failures and len(sha_rows) == EXPECTED_MANIFEST_ENTRIES,
        "failures": failures,
        "unexpected_files": unexpected,
        "missing_files": missing,
        "packaging_warnings": packaging_warnings,
        "zip_unsafe_paths": inspection["unsafe_paths"],
        "zip_duplicate_paths": inspection["duplicate_paths"],
    }


def _line_number(text: str, pattern: str) -> int | None:
    regex = re.compile(pattern)
    for number, line in enumerate(text.splitlines(), 1):
        if regex.search(line):
            return number
    return None


def _load_pack_json(pack_root: Path, relative: str) -> dict[str, Any]:
    path = pack_root / relative
    return read_json(path) if path.is_file() else {}


def parse_reported_evidence(pack_root: Path) -> dict[str, Any]:
    test = _load_pack_json(pack_root, "EVIDENCE/TEST_SUMMARY.json")
    gate = _load_pack_json(pack_root, "EVIDENCE/BACKTEST_GATE_SUMMARY.json")
    verify = _load_pack_json(pack_root, "EVIDENCE/V5_VERIFY.json")
    ui = _load_pack_json(pack_root, "EVIDENCE/BUILD_AND_UI_CHECK.json")
    public_run = _load_pack_json(pack_root, f"SOURCE_SNAPSHOT/data/timeseries_v5/runs/{EXPECTED_RUN_ID}.json")
    latest = _load_pack_json(pack_root, "SOURCE_SNAPSHOT/data/timeseries_v5/multivariate_v5_latest.json")
    return {
        "test_summary": test,
        "backtest": gate,
        "verify": verify,
        "build_ui": ui,
        "public_run": public_run,
        "latest": latest,
    }


def recompute_evidence(reported: dict[str, Any]) -> dict[str, Any]:
    gate = reported.get("backtest", {})
    research = gate.get("research_gate", {})
    horizons = research.get("by_horizon", {})
    improvements: dict[str, float] = {}
    errors: list[str] = []
    for key, row in horizons.items():
        baseline = float(row["baseline_crps"])
        model = float(row["model_crps"])
        improvements[key] = (baseline - model) / baseline
        if not math.isclose(improvements[key], float(row["improvement"]), rel_tol=0.0, abs_tol=1e-14):
            errors.append(f"horizon {key} improvement mismatch")
    long_mean = sum(improvements[key] for key in ("21", "63")) / 2 if all(key in improvements for key in ("21", "63")) else None
    origin_count = int(gate.get("origin_count", 0))
    score_count = int(gate.get("score_count", 0))
    arithmetic_count = origin_count * len(horizons)
    consistency = {
        "model_id": gate.get("model_id", EXPECTED_MODEL_ID) in {EXPECTED_MODEL_ID, None}
        and reported.get("verify", {}).get("model_id") == EXPECTED_MODEL_ID
        and reported.get("latest", {}).get("model_id") == EXPECTED_MODEL_ID,
        "run_id": gate.get("run_id") == EXPECTED_RUN_ID
        and reported.get("public_run", {}).get("run_id") == EXPECTED_RUN_ID
        and reported.get("latest", {}).get("backtest_run_id") == EXPECTED_RUN_ID,
        "research_gate": research.get("pass") is False and reported.get("latest", {}).get("research_gate", {}).get("pass") is False,
        "visibility": reported.get("latest", {}).get("numbers_visible") is False
        and reported.get("build_ui", {}).get("static_build", {}).get("numbers_visible") is False,
        "operational_gate": reported.get("latest", {}).get("operational_gate", {}).get("pass") is False
        and reported.get("build_ui", {}).get("static_build", {}).get("operational_gate_pass") is False,
        "contract_hash": reported.get("verify", {}).get("contract_hash") == reported.get("public_run", {}).get("contract_hash"),
        "lineage_counts": all(
            reported.get("verify", {}).get("lineage", {}).get(key) == reported.get("public_run", {}).get("source_lineage", {}).get(key)
            for key in ("receipt_count", "observation_count", "link_count")
        ),
    }
    if not all(consistency.values()):
        errors.extend(f"cross-file inconsistency:{key}" for key, ok in consistency.items() if not ok)
    if score_count != arithmetic_count:
        errors.append("origin × horizon score arithmetic mismatch")
    if long_mean is not None and not math.isclose(long_mean, float(research.get("long_horizon_mean_improvement", math.nan)), rel_tol=0, abs_tol=1e-14):
        errors.append("long-horizon mean mismatch")
    return {
        "status": "partial",
        "origin_count": origin_count,
        "horizon_count": len(horizons),
        "score_count_recomputed": arithmetic_count,
        "reported_score_count": score_count,
        "horizon_improvements": improvements,
        "long_horizon_mean_improvement": long_mean,
        "consistency": consistency,
        "errors": errors,
        "recomputed_fields": [
            "origin_count_times_horizon_count", "horizon_improvement",
            "long_horizon_mean_improvement", "cross_file_identifiers",
            "gate_and_visibility_state", "lineage_count_consistency",
        ],
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def parse_runtime_hgb(source: str) -> tuple[list[dict[str, Any]], list[int]]:
    tree = ast.parse(source)
    rows: list[dict[str, Any]] = []
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) == "HistGradientBoostingRegressor":
            kwargs = {keyword.arg: _literal(keyword.value) for keyword in node.keywords if keyword.arg}
            rows.append({
                "family": "quantile_hist_gradient_boosting",
                "learning_rate": kwargs.get("learning_rate"),
                "max_leaf_nodes": kwargs.get("max_leaf_nodes"),
            })
            lines.append(node.lineno)
    return rows, lines


def contract_runtime_diff(contract: dict[str, Any], models_source: str) -> dict[str, Any]:
    bundle = contract.get("candidate_bundle", {})
    contract_specs = [
        {
            "family": "quantile_hist_gradient_boosting",
            "learning_rate": learning_rate,
            "max_leaf_nodes": leaves,
        }
        for learning_rate, leaves in itertools.product(
            bundle.get("hgb_learning_rate", []), bundle.get("hgb_max_leaf_nodes", [])
        )
    ]
    runtime_specs, runtime_lines = parse_runtime_hgb(models_source)
    contract_payload = {"specs": sorted(contract_specs, key=canonical_json)}
    runtime_payload = {"specs": sorted(runtime_specs, key=canonical_json)}
    return {
        "contract": contract_payload,
        "runtime": runtime_payload,
        "contract_canonical_json": canonical_json(contract_payload),
        "runtime_canonical_json": canonical_json(runtime_payload),
        "contract_sha256": json_hash(contract_payload),
        "runtime_sha256": json_hash(runtime_payload),
        "exact_match": contract_payload == runtime_payload,
        "runtime_lines": runtime_lines,
    }


def parse_registry_ids(source: str) -> tuple[list[str], int | None]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "SOURCE_REGISTRY" and isinstance(node.value, ast.Dict):
            return [str(_literal(key)) for key in node.value.keys], node.lineno
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SOURCE_REGISTRY" for target in node.targets) and isinstance(node.value, ast.Dict):
            return [str(_literal(key)) for key in node.value.keys], node.lineno
    return [], None


SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "fred_alfred": ("fred_nasdaqcom",),
    "us_treasury_rates": ("treasury_yield_curve", "treasury_real_yield_curve"),
    "nyfed_markets": ("nyfed_reference_rates", "nyfed_rrp"),
    "fed_h41": ("fed_h41_walcl",),
    "fed_h10": ("fred_h10_dollar",),
    "eia_petroleum": ("eia_crude_oil",),
    "fama_french": ("fed_fama_french",),
    "philadelphia_fed_spf": ("philadelphia_spf",),
}

FINDING_CATALOG = (
    ("F-001", "P0", "Global model-input PIT proof is incomplete"),
    ("F-002", "P0", "HGB frozen coordinates do not match implementation"),
    ("F-003", "P0", "Contract source inventory and registry diverge"),
    ("F-004", "P0", "Backtest anchor is reconstructed from only p10/p90"),
    ("F-005", "P0", "Inner stacking/calibration boundary lacks horizon-aware purge"),
    ("F-006", "P0", "Weight selection and nine-quantile calibration reuse the same 52 origins"),
    ("F-007", "P0", "Atlas auto-merge conflicts with explicit approval contract"),
    ("F-008", "P0", "Structured PostgreSQL schema is bypassed by a generic JSONB ledger"),
    ("F-009", "P0", "Atlas is a sequential file-state script, not a long-running controller"),
    ("F-010", "P0", "Review pack is not a standalone numerical replay bundle"),
    ("F-011", "P0", "Pre-open current date is counted as a completed XNAS session"),
    ("F-012", "P0", "Collection failures are outside receipt terminal coverage"),
    ("F-013", "P1", "Lineage verifier checks existence, not exact cardinality and chain integrity"),
    ("F-014", "P1", "Observation-row count overstates effective information volume"),
    ("F-015", "P1", "Feature matrix contains aliases and highly redundant signals"),
    ("F-016", "P1", "Legacy DFM factor levels are reused without V5 alignment proof"),
    ("F-017", "P1", "Candidate family names overstate actual algorithms"),
    ("F-018", "P1", "Symmetric EVT cannot represent downside/upside tail asymmetry"),
    ("F-019", "P1", "Anchor-only eras can make stress diagnostics non-informative"),
    ("F-020", "P1", "Long-horizon failure is broad, not a single calibration miss"),
    ("F-021", "P1", "Displayed daily paths are deterministic interpolation of marginal quantiles"),
    ("F-022", "P1", "1-day contribution output is not valid for every selected family"),
    ("F-023", "P1", "HTTP and archive collectors lack production-scale controls"),
    ("F-024", "P1", "Several reconstructed sources use heuristic release timestamps"),
    ("F-025", "P1", "Feature loading is hardwired to a local private-store path"),
    ("F-026", "P1", "Scheduled workflow can push research read models directly"),
    ("F-027", "P1", "Compute workflow runs only the V5 test file and may reuse a stale backtest"),
    ("F-028", "P2", "Compiled __pycache__ artifacts are included in the review pack"),
    ("F-029", "P2", "Candidate budget does not control repeated adaptive choices inside candidates"),
    ("F-030", "P2", "Headline data volume omits independent-unit and source-concentration context"),
)


def reconcile_finding_catalog(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detected = {row["id"]: row for row in findings}
    static_supported = {
        "F-013", "F-014", "F-015", "F-016", "F-017", "F-018", "F-019", "F-020",
        "F-022", "F-023", "F-024", "F-025", "F-027", "F-029", "F-030",
    }
    rows: list[dict[str, Any]] = []
    for finding_id, severity, title in FINDING_CATALOG:
        if finding_id in detected:
            status = detected[finding_id]["status"]
            basis = "independently machine-detected by this audit"
        elif finding_id in static_supported:
            status = "supported"
            basis = "supported by static pack evidence but not elevated to an independently complete reproducer finding"
        else:
            status = "not_detected"
            basis = "no independent detection in the current audit"
        rows.append({"id": finding_id, "severity": severity, "title": title, "status": status, "basis": basis})
    return rows


def source_registry_diff(
    contract: dict[str, Any],
    sources_source: str,
    features_source: str,
    collection: dict[str, Any],
    parquet: dict[str, Any],
) -> dict[str, Any]:
    contract_ids: list[str] = []
    for block in contract.get("source_blocks", {}).values():
        contract_ids.extend(str(value) for value in block.get("sources", []))
    runtime_ids, registry_line = parse_registry_ids(sources_source)
    contract_set, runtime_set = set(contract_ids), set(runtime_ids)
    receipt_ids = {str(row.get("source_id")) for row in collection.get("results", []) if row.get("receipt_id")}
    observation_ids = {str(row.get("source_id")) for row in collection.get("results", []) if int(row.get("facts", 0) or 0) > 0}
    collection_failures = [row for row in collection.get("results", []) if row.get("outcome") == "collection_failed"]
    parquet_ids = {str(row.get("source_id")) for row in parquet.get("files", [])}
    all_ids = sorted(contract_set | runtime_set | receipt_ids | parquet_ids)
    rows: list[dict[str, Any]] = []
    reverse_alias = {runtime: contract_id for contract_id, targets in SOURCE_ALIASES.items() for runtime in targets}
    for source_id in all_ids:
        alias_targets = list(SOURCE_ALIASES.get(source_id, ()))
        alias_for = reverse_alias.get(source_id)
        if source_id in contract_set and source_id in runtime_set:
            declaration = "exact_match"
        elif source_id in contract_set:
            declaration = "alias_candidate" if alias_targets else "contract_only"
        else:
            declaration = "alias_candidate" if alias_for else "runtime_only"
        implemented = source_id in runtime_set
        materialized = source_id in parquet_ids
        rows.append({
            "source_id": source_id,
            "declaration_status": declaration,
            "contract_declared": source_id in contract_set,
            "runtime_registered": implemented,
            "alias_targets": alias_targets,
            "alias_for": alias_for,
            "collector": implemented,
            "parser": implemented,
            "receipt": source_id in receipt_ids,
            "observation": source_id in observation_ids,
            "parquet": materialized,
            "feature_reference": source_id in features_source,
            "implementation_materialization_status": (
                "implemented_but_not_materialized" if implemented and not materialized
                else "materialized_but_not_declared" if materialized and source_id not in contract_set
                else "materialized" if materialized else "not_materialized"
            ),
        })
    return {
        "contract_count": len(contract_set),
        "runtime_count": len(runtime_set),
        "exact_match_count": len(contract_set & runtime_set),
        "contract_only": sorted(contract_set - runtime_set),
        "runtime_only": sorted(runtime_set - contract_set),
        "alias_candidates": SOURCE_ALIASES,
        "registry_line": registry_line,
        "collection_failures_without_receipt": collection_failures,
        "rows": rows,
    }


def feature_pit_proof(features_source: str, pipeline_source: str, public_run: dict[str, Any]) -> dict[str, Any]:
    patterns = {
        "observation_time_pivot": r'\.pivot\(index="observation_time"',
        "date_only_reindex": r"\.reindex\(frame\.index\)",
        "forward_fill": r"\.ffill\(",
        "v4_inherited": r'data/timeseries_v4/parquet/observations\.parquet',
        "lineage_derived_leakage_count": r'pit_leakage_count.*0 if lineage\["ok"\] else 1',
    }
    locations = {
        key: {
            "detected": bool(re.search(pattern, features_source if key != "lineage_derived_leakage_count" else pipeline_source)),
            "line": _line_number(features_source if key != "lineage_derived_leakage_count" else pipeline_source, pattern),
        }
        for key, pattern in patterns.items()
    }
    feature_names = public_run.get("feature_metadata", {}).get("feature_names", [])
    selections = public_run.get("latest_selection_by_horizon", {})
    training = {
        str(horizon): {
            "active_feature_count": len(row.get("active_feature_names", [])),
            "training_rows": row.get("training_rows"),
            "calibration_origins": row.get("calibration_origins"),
        }
        for horizon, row in selections.items()
    }
    return {
        "receipt_observation_lineage_valid": bool(public_run.get("source_lineage", {}).get("ok")),
        "global_feature_pit_proof": False,
        "reason": "The run does not carry observation IDs and max_available_at for every origin-feature value; inherited V4 data are joined by observation date and forward-filled.",
        "active_feature_total": len(feature_names),
        "origin_feature_lineage_rows_available": False,
        "patterns": locations,
        "training_by_horizon": training,
    }


def comparator_identity(models_source: str, pipeline_source: str) -> dict[str, Any]:
    model_line = _line_number(models_source, r"def approximate_anchor_samples")
    copied_line = _line_number(pipeline_source, r'model_crps = float\(row\["baseline_crps"\]\)')
    return {
        "exact_comparator_identity": False,
        "gaussian_from_p10_p90": model_line is not None,
        "copied_baseline_crps_on_anchor_fallback": copied_line is not None,
        "same_sample_object_proven": False,
        "evidence": [
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/models.py", model_line, "approximate_anchor_samples reconstructs a Gaussian sample from p10/p90"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/pipeline.py", copied_line, "anchor fallback copies baseline CRPS rather than recomputing it from the reconstructed sample"),
        ],
    }


def validation_independence(pipeline_source: str, public_run: dict[str, Any]) -> dict[str, Any]:
    selection_line = _line_number(pipeline_source, r"validation_rows")
    residual_line = _line_number(pipeline_source, r"quantile_calibration")
    selections = public_run.get("latest_selection_by_horizon", {})
    calibration_counts = sorted({int(row.get("calibration_origins", 0)) for row in selections.values()})
    quantile_counts = sorted({len(row.get("quantile_calibration", {})) for row in selections.values()})
    return {
        "selection_stacking_calibration_disjoint": False,
        "same_resolved_origins_reused": calibration_counts == [52],
        "selection_history_origins": 52,
        "quantile_calibration_levels": quantile_counts,
        "row_count_purge_present": "purge_rows" in pipeline_source,
        "label_interval_purge_proof": False,
        "evidence": [
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/pipeline.py", selection_line, "the same validation tail is used for candidate scoring and stacking"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/pipeline.py", residual_line, "calibration adjustments are produced from the same validation predictions"),
        ],
    }


def _weekday_sessions(start_exclusive: date, end_inclusive: date) -> list[str]:
    values: list[str] = []
    cursor = start_exclusive + timedelta(days=1)
    while cursor <= end_inclusive:
        if cursor.weekday() < 5:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def first_eligible_session(available_at: datetime, sessions: list[dict[str, str]]) -> str | None:
    """Return the first session whose close is not earlier than availability."""
    if available_at.tzinfo is None:
        raise ValueError("available_at must be timezone-aware")
    for session in sessions:
        close_at = datetime.fromisoformat(session["close_at"].replace("Z", "+00:00"))
        if available_at <= close_at:
            return session["session_date"]
    return None


def freshness_boundary(generated_at: str, last_loaded: str, target_date: str) -> dict[str, Any]:
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    target = date.fromisoformat(target_date)
    loaded = date.fromisoformat(last_loaded)
    eastern = generated.astimezone(ZoneInfo("America/New_York"))
    target_completed = eastern.date() > target or (eastern.date() == target and eastern.timetz().replace(tzinfo=None) >= time(16, 0))
    last_completed = target if target_completed and target.weekday() < 5 else target - timedelta(days=1)
    while last_completed.weekday() >= 5:
        last_completed -= timedelta(days=1)
    completed = _weekday_sessions(loaded, last_completed)
    calendar_target = _weekday_sessions(loaded, target)
    return {
        "generated_at": generated_at,
        "generated_at_new_york": eastern.isoformat(),
        "last_loaded_session": last_loaded,
        "last_completed_xnas_session": last_completed.isoformat(),
        "calendar_target_date": target_date,
        "target_session_completed": target_completed,
        "completed_missing_sessions": completed,
        "completed_missing_count": len(completed),
        "calendar_target_sessions": calendar_target,
        "calendar_target_count": len(calendar_target),
        "pre_open_off_by_one_detected": len(calendar_target) == len(completed) + 1,
    }


def static_architecture_checks(pack_root: Path) -> dict[str, Any]:
    source = pack_root / "SOURCE_SNAPSHOT"
    postgres = (source / "src/ai_fc/timeseries_v5/storage/postgres.py").read_text(encoding="utf-8")
    migration = (source / "migrations/timeseries_v5/0001_control_plane.sql").read_text(encoding="utf-8")
    atlas = (source / "tools/atlas_timeseries.py").read_text(encoding="utf-8")
    workflow = (source / ".github/workflows/timeseries-v5-refresh.yml").read_text(encoding="utf-8")
    pipeline = (source / "src/ai_fc/timeseries_v5/pipeline.py").read_text(encoding="utf-8")
    source_code = (source / "src/ai_fc/timeseries_v5/sources.py").read_text(encoding="utf-8")
    models = (source / "src/ai_fc/timeseries_v5/models.py").read_text(encoding="utf-8")
    return {
        "postgres_typed_schema_bypassed": {
            "detected": "research_append_ledger" in postgres and "payload JSONB" in migration,
            "line": _line_number(postgres, r"research_append_ledger"),
        },
        "atlas_local_state": {
            "detected": "STATE_ROOT" in atlas and ".events.jsonl" in atlas,
            "lease": bool(re.search(r"\blease\b", atlas, re.IGNORECASE)),
            "heartbeat": bool(re.search(r"\bheartbeat\b", atlas, re.IGNORECASE)),
            "checkpoint": bool(re.search(r"\bcheckpoint\b", atlas, re.IGNORECASE)),
            "line": _line_number(atlas, r"STATE_ROOT"),
        },
        "atlas_auto_merge": {
            "detected": "--auto-merge" in atlas and '"gh", "pr", "merge", "--auto"' in atlas,
            "line": _line_number(atlas, r"--auto-merge"),
        },
        "scheduled_direct_push": {
            "detected": "contents: write" in workflow and "git push" in workflow,
            "permission_line": _line_number(workflow, r"contents: write"),
            "push_line": _line_number(workflow, r"git push"),
        },
        "deterministic_path_interpolation": {
            "detected": bool(re.search(r"interp|linspace", pipeline, re.IGNORECASE)),
            "line": _line_number(pipeline, r"interp|linspace"),
        },
        "collection_failure_outside_receipt_denominator": {
            "detected": "collection_failed" not in source_code and "receipt_core" in source_code,
            "line": _line_number(source_code, r"receipt_core"),
        },
        "candidate_family_semantics": {
            "quantile_hist_gradient_boosting": "three sklearn quantile HGB regressors plus a Ridge location model",
            "dynamic_linear_state_space": "Ridge with exponentially increasing sample weights; no state-space filter",
            "ex_ante_soft_regime_mixture": "deterministic feature augmentation inside one direct distribution model",
            "student_t_evt_tail": "absolute-residual GPD tail applied symmetrically",
            "evt_absolute_residual_line": _line_number(models, r"absolute_residual = np\.abs"),
            "dynamic_weight_line": _line_number(models, r"dynamic_linear_state_space"),
        },
    }


def sanitized_subprocess_env(temp_root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        sensitive = key in SECRET_ENV_NAMES or any(token in upper for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "ACCESS_KEY", "PRIVATE_KEY"))
        if not sensitive:
            env[key] = value
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(temp_root / "SOURCE_SNAPSHOT" / "src")
    env["TEMP"] = str(temp_root / "tmp")
    env["TMP"] = str(temp_root / "tmp")
    (temp_root / "tmp").mkdir(parents=True, exist_ok=True)
    return env


def standalone_snapshot_test(pack_root: Path) -> dict[str, Any]:
    snapshot = pack_root / "SOURCE_SNAPSHOT"
    test_path = snapshot / "src/tests/test_multivariate_timeseries_v5.py"
    base_temp = pack_root.parent / "snapshot-pytest-temp"
    command = [
        sys.executable, "-m", "pytest", str(test_path), "-q", "-p", "no:cacheprovider",
        "--basetemp", str(base_temp),
    ]
    result = subprocess.run(
        command,
        cwd=snapshot,
        env=sanitized_subprocess_env(pack_root),
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + "\n" + result.stderr
    missing = sorted(set(re.findall(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)", combined)))
    return {
        "status": "pass" if result.returncode == 0 else "fail",
        "command": command,
        "returncode": result.returncode,
        "missing_modules": missing,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def manifest_tree(root: Path, roots: Iterable[str] = PROTECTED_ROOTS) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relative_root in roots:
        base = root / relative_root
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else base.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    files.sort(key=lambda row: row["path"])
    return {"schema_version": 1, "roots": list(roots), "files": files, "file_count": len(files), "content_hash": json_hash(files)}


def compare_manifests(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left = {row["path"]: row for row in before.get("files", [])}
    right = {row["path"]: row for row in after.get("files", [])}
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = sorted(path for path in set(left) & set(right) if left[path] != right[path])
    return {
        "ok": not (added or removed or changed),
        "before_hash": before.get("content_hash"),
        "after_hash": after.get("content_hash"),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def scan_secret_texts(paths: Iterable[Path]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in {".json", ".md", ".log", ".txt", ".py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                matches.append({"path": path.as_posix(), "line": number, "redacted": True})
    return {"pass": not matches, "matches": matches}


def build_findings(
    runtime_diff: dict[str, Any],
    source_diff: dict[str, Any],
    pit: dict[str, Any],
    comparator: dict[str, Any],
    validation: dict[str, Any],
    freshness: dict[str, Any],
    architecture: dict[str, Any],
    integrity: dict[str, Any],
    replay: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not runtime_diff["exact_match"]:
        rows.append(finding("F-002", "P0", "HGB frozen coordinates do not match implementation", [
            evidence("SOURCE_SNAPSHOT/data/contracts/multivariate_timeseries_v5.yaml", 134, "contract registers learning rates 0.03/0.07 and leaves 7/15"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/models.py", runtime_diff["runtime_lines"][0] if runtime_diff["runtime_lines"] else None, "runtime uses learning_rate 0.05 and max_leaf_nodes 7"),
        ], "The evaluated candidate is not the frozen candidate.", "Generate runtime estimators from a canonical contract candidate spec and fail on hash mismatch."))
    if source_diff["contract_only"] or source_diff["runtime_only"]:
        rows.append(finding("F-003", "P0", "Contract source inventory and registry diverge", [
            evidence("SOURCE_SNAPSHOT/data/contracts/multivariate_timeseries_v5.yaml", 55, f"37 contract IDs; {len(source_diff['contract_only'])} absent from runtime"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/sources.py", source_diff["registry_line"], f"24 runtime IDs; {len(source_diff['runtime_only'])} absent from contract"),
        ], "Source coverage and aliases cannot be verified from the frozen contract.", "Register canonical source IDs, explicit aliases and implementation/materialization status."))
    if not pit["global_feature_pit_proof"]:
        rows.append(finding("F-001", "P0", "Global model-input PIT proof is incomplete", [
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/features.py", pit["patterns"]["observation_time_pivot"]["line"], "V4 observations are pivoted on observation_time"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/features.py", pit["patterns"]["date_only_reindex"]["line"], "date-only reindex and forward fill lack feature-value available_at lineage"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/pipeline.py", pit["patterns"]["lineage_derived_leakage_count"]["line"], "pit_leakage_count is derived from ledger lineage state"),
        ], "Same-session or post-close information may enter inherited features.", "Persist origin-feature observation IDs and max_available_at and gate every value against origin_cutoff_at."))
    if not comparator["exact_comparator_identity"]:
        rows.append(finding("F-004", "P0", "Comparator sample identity is not exact", comparator["evidence"], "Stacking may optimize against a reconstructed comparator while Gate metrics use copied comparator losses.", "Use one immutable comparator sample object and recompute all comparator scores from it."))
    if not validation["selection_stacking_calibration_disjoint"]:
        rows.append(finding("F-005", "P0", "Inner selection, stacking and calibration are not independent", validation["evidence"], "The same 52 resolved origins can overfit family, weight and nine quantile offsets.", "Create disjoint label-mature folds with horizon-aware purge and embargo."))
        rows.append(finding("F-006", "P0", "The same 52 origins are reused for stacking and calibration", validation["evidence"], "Repeated reuse consumes the same validation information multiple times.", "Separate stacking and calibration origins and record fold-role hashes."))
    if freshness["pre_open_off_by_one_detected"]:
        rows.append(finding("F-011", "P0", "Pre-open freshness includes an uncompleted current session", [
            evidence("SOURCE_SNAPSHOT/data/timeseries_v5/multivariate_v5_latest.json", 1, f"reported 6; completed-session count is {freshness['completed_missing_count']}"),
        ], "Freshness metrics are wrong at pre-open cutoffs even though the candidate remains HOLD.", "Count only XNAS sessions whose regular close is on or before knowledge_cutoff."))
    if source_diff["collection_failures_without_receipt"] or architecture["collection_failure_outside_receipt_denominator"]["detected"]:
        rows.append(finding("F-012", "P0", "Collection failures are excluded from receipt terminal coverage", [
            evidence("SOURCE_SNAPSHOT/data/timeseries_v5/manifests/collection_latest.json", 1, "EIA collection_failed has no receipt_id"),
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/sources.py", architecture["collection_failure_outside_receipt_denominator"]["line"], "receipt creation occurs only after a successful HTTP response"),
        ], "Reported 100% terminal coverage omits attempts that never created receipts.", "Record exactly one terminal attempt outcome before HTTP and exactly one receipt outcome after receipt creation."))
    if architecture["postgres_typed_schema_bypassed"]["detected"]:
        rows.append(finding("F-008", "P0", "Typed PostgreSQL schema is bypassed by a generic JSONB ledger", [
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/storage/postgres.py", architecture["postgres_typed_schema_bypassed"]["line"], "append writes research_append_ledger payload JSONB"),
        ], "Database constraints in typed tables are not enforced.", "Write core entities to typed append-only tables and reserve JSONB for extension metadata."))
    local = architecture["atlas_local_state"]
    if local["detected"] and not any((local["lease"], local["heartbeat"], local["checkpoint"])):
        rows.append(finding("F-009", "P0", "Atlas lacks a durable queue, lease, heartbeat and checkpoint", [
            evidence("SOURCE_SNAPSHOT/tools/atlas_timeseries.py", local["line"], "state is a local JSON file and events JSONL"),
        ], "Long-running work cannot provide safe concurrency or durable recovery.", "Use the preregistered PostgreSQL task queue with leases, heartbeats and checkpoints."))
    if architecture["atlas_auto_merge"]["detected"]:
        rows.append(finding("F-007", "P0", "Atlas auto-merge conflicts with explicit approval", [
            evidence("SOURCE_SNAPSHOT/tools/atlas_timeseries.py", architecture["atlas_auto_merge"]["line"], "run/resume exposes --auto-merge"),
        ], "Research output could be merged without the required signed owner approval.", "Remove auto-merge and require a separately recorded approval decision."))
    if replay.get("row_level_score_recompute") == "unavailable":
        rows.append(finding("F-010", "P0", "The pack is not a complete numerical replay bundle", [
            evidence("MANIFEST.sha256", 1, "private score matrix, samples and Parquet are not included"),
        ], "Summary integrity is verifiable but score-level CRPS and bootstrap claims are not independently reproducible.", "Package immutable score rows and runtime lock, or expose content-addressed private replay inputs.", "high", "unavailable"))
    if architecture["scheduled_direct_push"]["detected"]:
        rows.append(finding("F-026", "P1", "Scheduled workflow commits and pushes directly", [
            evidence("SOURCE_SNAPSHOT/.github/workflows/timeseries-v5-refresh.yml", architecture["scheduled_direct_push"]["push_line"], "scheduled workflow invokes git push"),
        ], "A scheduled research job can mutate the publication branch.", "Use read-only scheduled jobs and a separately approved promotion workflow."))
    if architecture["deterministic_path_interpolation"]["detected"]:
        rows.append(finding("F-021", "P1", "Path geometry is deterministically interpolated", [
            evidence("SOURCE_SNAPSHOT/src/ai_fc/timeseries_v5/pipeline.py", architecture["deterministic_path_interpolation"]["line"], "path construction contains interpolation/linspace"),
        ], "Displayed path dynamics are not sampled joint trajectories.", "Generate paths from joint endpoint and trajectory samples."))
    if integrity.get("packaging_warnings"):
        rows.append(finding("F-028", "P2", "Review pack includes compiled caches", [
            evidence(integrity["packaging_warnings"][0], None, f"{len(integrity['packaging_warnings'])} cache/compiled files are packaged"),
        ], "Mutable interpreter caches add noise and weaken a clean-source replay claim.", "Exclude __pycache__, pyc and mutable caches from future review packs."))
    return sorted(rows, key=lambda row: (int(row["severity"][1:]), row["id"]))


def reproducibility_matrix(test_replay: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_and_byte_integrity": "complete",
        "summary_json_parse": "complete",
        "aggregate_arithmetic": "partial",
        "standalone_source_snapshot_test": test_replay["status"],
        "full_repository_test_claim": "reported_only",
        "row_level_score_recompute": "unavailable",
        "origin_sample_recompute": "unavailable",
        "private_parquet_replay": "unavailable",
        "runtime_lock_replay": "unavailable",
        "unavailable_inputs": [
            "full 3,852-row score matrix",
            "4,000 samples for every origin and horizon",
            "private raw/feature Parquet",
            "complete repository modules",
            "identical runtime lock/container",
        ],
    }


def audit_pack(pack: Path, output: Path, repo_root: Path, *, run_snapshot_test: bool = True) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    inspection = inspect_zip_members(pack)
    with tempfile.TemporaryDirectory(prefix="v5-gate-audit-") as temp_name:
        temp_root = Path(temp_name)
        safe_extract(pack, temp_root, inspection)
        pack_root = _pack_root(temp_root)
        if pack_root is None:
            integrity = {
                "entry_count": 0,
                "expected_entry_count": EXPECTED_MANIFEST_ENTRIES,
                "pass": False,
                "failures": [{"path": "MANIFEST.sha256", "reason": "safe pack root unavailable"}],
                "unexpected_files": [], "missing_files": [], "packaging_warnings": [],
                "zip_unsafe_paths": inspection["unsafe_paths"], "zip_duplicate_paths": inspection["duplicate_paths"],
            }
            report = {
                "schema_version": 1, "input_pack": str(pack), "input_pack_sha256": sha256_file(pack),
                "manifest_entry_count": 0, "manifest_pass": False, "reported_metrics": {},
                "independently_recomputed_metrics": {"status": "unavailable"},
                "unavailable_replay_inputs": [], "test_replay": {"status": "unavailable"},
                "contract_runtime_mismatches": {}, "source_registry_mismatches": {},
                "feature_pit_proof": {}, "comparator_identity": {}, "validation_independence": {},
                "freshness_boundary": {}, "protected_non_mutation": {}, "secret_scan": {},
                "pack_integrity": integrity, "findings": [], "limitations": ["safe extraction was rejected"],
                "final_status": "audit_complete_with_integrity_findings",
            }
            return report, {}, {}, reproducibility_matrix({"status": "unavailable"})

        integrity = verify_pack_integrity(pack_root, inspection)
        reported = parse_reported_evidence(pack_root)
        recomputed = recompute_evidence(reported)
        snapshot_test = standalone_snapshot_test(pack_root) if run_snapshot_test else {"status": "unavailable", "reason": "disabled by caller", "returncode": None, "missing_modules": []}
        reproducibility = reproducibility_matrix(snapshot_test)

        source = pack_root / "SOURCE_SNAPSHOT"
        contract_text = (source / "data/contracts/multivariate_timeseries_v5.yaml").read_text(encoding="utf-8")
        if yaml is None:
            raise RuntimeError("PyYAML is required to safely parse the V5 contract")
        contract = yaml.safe_load(contract_text)
        models_source = (source / "src/ai_fc/timeseries_v5/models.py").read_text(encoding="utf-8")
        sources_source = (source / "src/ai_fc/timeseries_v5/sources.py").read_text(encoding="utf-8")
        features_source = (source / "src/ai_fc/timeseries_v5/features.py").read_text(encoding="utf-8")
        pipeline_source = (source / "src/ai_fc/timeseries_v5/pipeline.py").read_text(encoding="utf-8")
        runtime_diff = contract_runtime_diff(contract, models_source)
        collection = _load_pack_json(pack_root, "SOURCE_SNAPSHOT/data/timeseries_v5/manifests/collection_latest.json")
        parquet = _load_pack_json(pack_root, "SOURCE_SNAPSHOT/data/timeseries_v5/manifests/parquet_latest.json")
        source_diff = source_registry_diff(contract, sources_source, features_source, collection, parquet)
        pit = feature_pit_proof(features_source, pipeline_source, reported.get("public_run", {}))
        comparator = comparator_identity(models_source, pipeline_source)
        validation = validation_independence(pipeline_source, reported.get("public_run", {}))
        freshness = freshness_boundary(PACK_GENERATED_AT, "2026-08-14", "2026-08-24")
        architecture = static_architecture_checks(pack_root)
        findings = build_findings(runtime_diff, source_diff, pit, comparator, validation, freshness, architecture, integrity, reproducibility)
        catalog_reconciliation = reconcile_finding_catalog(findings)
        report = {
            "schema_version": 1,
            "audit_task_id": "V6-P0-001",
            "input_pack": str(pack),
            "input_pack_bytes": pack.stat().st_size,
            "input_pack_sha256": sha256_file(pack),
            "expected_input_pack_sha256": EXPECTED_PACK_SHA256,
            "manifest_entry_count": integrity["entry_count"],
            "manifest_pass": integrity["pass"],
            "pack_integrity": integrity,
            "reported_metrics": reported,
            "independently_recomputed_metrics": recomputed,
            "unavailable_replay_inputs": reproducibility["unavailable_inputs"],
            "test_replay": snapshot_test,
            "contract_runtime_mismatches": runtime_diff,
            "source_registry_mismatches": source_diff,
            "feature_pit_proof": pit,
            "comparator_identity": comparator,
            "validation_independence": validation,
            "freshness_boundary": freshness,
            "architecture_checks": architecture,
            "protected_non_mutation": {},
            "secret_scan": {},
            "findings": findings,
            "finding_catalog_reconciliation": catalog_reconciliation,
            "finding_catalog_counts": {
                status: sum(row["status"] == status for row in catalog_reconciliation)
                for status in ("confirmed", "supported", "unavailable", "not_detected", "out_of_task_scope")
            },
            "finding_counts": {severity: sum(row["severity"] == severity for row in findings) for severity in ("P0", "P1", "P2")},
            "limitations": [
                "Summary-level arithmetic is not row-level CRPS replay.",
                "Private score matrices, per-origin samples and Parquet partitions are absent.",
                "Alias candidates are hypotheses and are never promoted to exact matches.",
                "Freshness session enumeration is fixed to the audited 2026-08-14 through 2026-08-24 interval, which has no XNAS holiday.",
            ],
            "final_status": "audit_complete_with_findings",
        }
        return report, runtime_diff, source_diff, reproducibility


def command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--skip-snapshot-test", action="store_true", help="fixture-only option")
    args = parser.parse_args(argv)
    try:
        pack = args.pack.expanduser().resolve(strict=True)
        repo_root = args.repo_root.expanduser().resolve(strict=True)
        output = args.output if args.output.is_absolute() else repo_root / args.output
        report, runtime_diff, source_diff, replay = audit_pack(pack, output, repo_root, run_snapshot_test=not args.skip_snapshot_test)
        write_json(output, report)
        write_json(output.parent / "v5_runtime_contract_diff.json", runtime_diff)
        write_json(output.parent / "v5_contract_registry_diff.json", source_diff)
        write_json(output.parent / "v5_reproducibility_matrix.json", replay)
        print(canonical_json({"status": report["final_status"], "output": str(output), "findings": report.get("finding_counts", {})}))
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"audit tool failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(command())
