#!/usr/bin/env python3
"""Independent, fail-closed reproducer for the frozen NASDAQ V6 Gate.

This module intentionally does not import ``ai_fc``.  It verifies the review
pack byte-for-byte, recomputes the published score aggregates from the sealed
score rows, and records why the frozen V6 result remains HOLD.  Detecting the
expected V6 failures is a successful V7-P0-001 audit outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from statistics import fmean, median
from typing import Any, Iterable

import numpy as np


EXPECTED_V6_PACK_SHA256 = "7b04d765106253a6a53927a8713ac2e34257db973910493f9c85b3070c158105"
EXPECTED_V6_PACK_BYTES = 14_778_803
EXPECTED_V6_MANIFEST_ENTRIES = 212
EXPECTED_V7_EVIDENCE_PACK_SHA256 = "a080b79500a991dcb98cba1f5e670e4755d118b9694e0b6bccf8d785252aba70"
EXPECTED_EVIDENCE_SHA256 = "f8e39197706dd2a7d9119bcd25da51556f6958d59c91aed604765885a8d4cb90"
EXPECTED_RUN_ID = "tsv6-sealed-46d58750db2abe8b40cec159"
EXPECTED_MODEL_ID = "shadow.nasdaq_pit_hierarchical_distribution_v6"
EXPECTED_LOGICAL_SCORE_SHA256 = "3338d152acd168f4b003530dc5f3bc5431dceb63ab1d2d4cd68dd55babd9bd8b"
EXPECTED_PHYSICAL_SCORE_SHA256 = "e287614f4d62b7cc9966eb4ba9961b65ff7f95bbfe1df8cc173207db6ceb6373"
EVIDENCE_MEMBER = "NASDAQ_V6_INDEPENDENT_GATE_EVIDENCE_20260825.json"
DELIVERY_MANIFEST_MEMBER = "NASDAQ_V7_DELIVERY_MANIFEST_20260825.json"
SCORES_PATH = (
    "outputs/timeseries_v6/research/sealed_runs/"
    f"{EXPECTED_RUN_ID}/scores.jsonl"
)
RUN_PATH = (
    "outputs/timeseries_v6/research/sealed_runs/"
    f"{EXPECTED_RUN_ID}/run.json"
)
GATE_PATH = "outputs/timeseries_v6/research/gate_result.json"
VERIFY_PATH = "outputs/timeseries_v6/research/verification_result.json"
CONTRACT_PATH = "data/contracts/multivariate_timeseries_v6.yaml"
BACKTEST_SOURCE_PATH = "src/ai_fc/timeseries_v6/research_backtest.py"
GATE_SOURCE_PATH = "src/ai_fc/timeseries_v6/research_gate.py"

PROTECTED_ROOTS = (
    "data/timeseries",
    "data/timeseries_v1",
    "data/timeseries_v2",
    "data/timeseries_v3",
    "data/timeseries_v4",
    "data/timeseries_v5",
    "data/timeseries_v6",
    "outputs/timeseries_v1",
    "outputs/timeseries_v2",
    "outputs/timeseries_v3",
    "outputs/timeseries_v4",
    "outputs/timeseries_v5",
    "outputs/timeseries_v6",
    "data/scenarios",
    "data/forecasts",
    "data/ledgers",
    "data/statistics/official_store/ledgers",
    "calibration",
)
PROTECTED_FILES = (
    "data/contracts/ledger_registry.yaml",
    "_site/data.json",
    "_site/future_paths.json",
    "_site/statistics.json",
)
SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"['\"]?\s*[:=]\s*['\"]?(?!REDACTED|null|none)[A-Za-z0-9_./+\-=]{12,}"
    ),
    re.compile(r"(?:gh[opsu]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})"),
)
SENSITIVE_ENV_FRAGMENT = re.compile(
    r"(?i)(api_?key|token|secret|password|database_url|access_?key|private_?key)"
)


class AuditError(RuntimeError):
    """The audit could not be completed reliably."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(value)
        temp = Path(handle.name)
    os.replace(temp, path)


def atomic_write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    atomic_write_bytes(path, (payload + "\n").encode("utf-8"))


def normalized_zip_name(name: str) -> tuple[str | None, str | None]:
    if not name or "\\" in name or "\x00" in name:
        return None, "empty, NUL, or backslash path"
    if re.match(r"^[A-Za-z]:", name) or name.startswith("/"):
        return None, "absolute or drive path"
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None, "relative traversal or ambiguous component"
    return path.as_posix(), None


def inspect_zip(archive: zipfile.ZipFile) -> dict[str, Any]:
    unsafe: list[dict[str, str]] = []
    duplicate: list[str] = []
    case_collision: list[str] = []
    exact: set[str] = set()
    folded: dict[str, str] = {}
    files: list[str] = []
    for info in archive.infolist():
        normalized, reason = normalized_zip_name(info.filename)
        if reason:
            unsafe.append({"path": info.filename, "reason": reason})
            continue
        assert normalized is not None
        if normalized in exact:
            duplicate.append(normalized)
        exact.add(normalized)
        previous = folded.get(normalized.casefold())
        if previous is not None and previous != normalized:
            case_collision.append(f"{previous}|{normalized}")
        folded[normalized.casefold()] = normalized
        if not info.is_dir():
            files.append(normalized)
    return {
        "pass": not unsafe and not duplicate and not case_collision,
        "unsafe_paths": unsafe,
        "duplicate_paths": sorted(set(duplicate)),
        "case_collisions": sorted(set(case_collision)),
        "file_count": len(files),
        "files": files,
    }


def _parse_sha_manifest(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        if not match:
            raise AuditError(f"invalid MANIFEST.sha256 line: {line[:120]}")
        digest, name = match.groups()
        normalized, reason = normalized_zip_name(name)
        if reason or normalized is None:
            raise AuditError(f"unsafe MANIFEST.sha256 path: {name}")
        if normalized in rows:
            raise AuditError(f"duplicate MANIFEST.sha256 path: {normalized}")
        rows[normalized] = digest.lower()
    return rows


def verify_pack_integrity(
    pack: Path,
    *,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
    expected_entries: int | None = None,
) -> dict[str, Any]:
    physical_sha = sha256_file(pack)
    size = pack.stat().st_size
    failures: list[str] = []
    if expected_sha256 and physical_sha != expected_sha256:
        failures.append("zip_sha256_mismatch")
    if expected_bytes is not None and size != expected_bytes:
        failures.append("zip_size_mismatch")
    with zipfile.ZipFile(pack) as archive:
        inspection = inspect_zip(archive)
        if not inspection["pass"]:
            failures.append("unsafe_or_duplicate_zip_member")
        try:
            manifest = json.loads(archive.read("MANIFEST.json"))
            sha_manifest = _parse_sha_manifest(
                archive.read("MANIFEST.sha256").decode("utf-8-sig")
            )
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AuditError(f"manifest unavailable: {exc}") from exc
        if not isinstance(manifest, list):
            raise AuditError("MANIFEST.json must be a list")
        manifest_by_path: dict[str, dict[str, Any]] = {}
        for row in manifest:
            if not isinstance(row, dict):
                failures.append("non_object_manifest_row")
                continue
            name = str(row.get("path", ""))
            normalized, reason = normalized_zip_name(name)
            if reason or normalized is None:
                failures.append(f"unsafe_manifest_path:{name}")
                continue
            if normalized in manifest_by_path:
                failures.append(f"duplicate_manifest_path:{normalized}")
            manifest_by_path[normalized] = row
        if expected_entries is not None and len(manifest_by_path) != expected_entries:
            failures.append("manifest_entry_count_mismatch")
        actual_files = set(inspection["files"]) - {"MANIFEST.json", "MANIFEST.sha256"}
        if actual_files != set(manifest_by_path):
            failures.append("manifest_membership_mismatch")
        if set(sha_manifest) != set(manifest_by_path):
            failures.append("sha_manifest_membership_mismatch")
        for name, row in manifest_by_path.items():
            try:
                body = archive.read(name)
            except KeyError:
                failures.append(f"missing:{name}")
                continue
            digest = sha256_bytes(body)
            if int(row.get("bytes", -1)) != len(body):
                failures.append(f"size:{name}")
            if str(row.get("sha256", "")).lower() != digest:
                failures.append(f"sha256:{name}")
            if sha_manifest.get(name) != digest:
                failures.append(f"sha_manifest:{name}")
    return {
        "pass": not failures,
        "zip_sha256": physical_sha,
        "zip_bytes": size,
        "manifest_entries": len(manifest_by_path),
        "failures": sorted(set(failures)),
        "zip_inspection": {key: value for key, value in inspection.items() if key != "files"},
    }


def verify_evidence_pack(pack: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    outer_hash = sha256_file(pack)
    failures: list[str] = []
    if outer_hash != EXPECTED_V7_EVIDENCE_PACK_SHA256:
        failures.append("evidence_pack_sha256_mismatch")
    with zipfile.ZipFile(pack) as archive:
        inspection = inspect_zip(archive)
        if not inspection["pass"]:
            failures.append("unsafe_or_duplicate_evidence_member")
        delivery = json.loads(archive.read(DELIVERY_MANIFEST_MEMBER))
        listed = {row["name"]: row for row in delivery.get("artifacts", [])}
        for name, row in listed.items():
            body = archive.read(name)
            if len(body) != int(row["bytes"]) or sha256_bytes(body) != row["sha256"]:
                failures.append(f"delivery_artifact_mismatch:{name}")
        evidence_body = archive.read(EVIDENCE_MEMBER)
        evidence_hash = sha256_bytes(evidence_body)
        if evidence_hash != EXPECTED_EVIDENCE_SHA256:
            failures.append("independent_evidence_sha256_mismatch")
        evidence = json.loads(evidence_body)
    return evidence, {
        "pass": not failures,
        "zip_sha256": outer_hash,
        "zip_bytes": pack.stat().st_size,
        "delivery_artifacts": len(listed),
        "evidence_sha256": evidence_hash,
        "failures": failures,
    }


def _read_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    value = json.loads(archive.read(name))
    if not isinstance(value, dict):
        raise AuditError(f"{name} must contain a JSON object")
    return value


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    model = fmean(float(row["model_crps"]) for row in rows)
    baseline = fmean(float(row["baseline_crps"]) for row in rows)
    return {
        "count": len(rows),
        "model_crps": model,
        "baseline_crps": baseline,
        "improvement": (baseline - model) / baseline,
        "coverage_80": fmean(float(row["p10"]) <= float(row["actual"]) <= float(row["p90"]) for row in rows),
        "coverage_50": fmean(float(row["p25"]) <= float(row["actual"]) <= float(row["p75"]) for row in rows),
        "baseline_coverage_80": fmean(float(row["baseline_p10"]) <= float(row["actual"]) <= float(row["baseline_p90"]) for row in rows),
        "mean_actual": fmean(float(row["actual"]) for row in rows),
        "mean_p50": fmean(float(row["p50"]) for row in rows),
        "mean_up_probability": fmean(float(row["up_probability"]) for row in rows),
    }


def stationary_bootstrap_ci(
    values: np.ndarray, *, iterations: int = 5000, block_length: int = 13, seed: int = 62026
) -> list[float]:
    data = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations)
    for iteration in range(iterations):
        indexes = np.empty(len(data), dtype=int)
        indexes[0] = rng.integers(len(data))
        for position in range(1, len(data)):
            indexes[position] = (
                rng.integers(len(data))
                if rng.random() < 1 / block_length
                else (indexes[position - 1] + 1) % len(data)
            )
        means[iteration] = np.mean(data[indexes])
    return [float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))]


def _validate_score_rows(rows: list[dict[str, Any]]) -> None:
    required = {
        "origin", "horizon", "actual", "model_crps", "baseline_crps",
        "p10", "p25", "p50", "p75", "p90", "baseline_p10", "baseline_p90",
        "up_probability", "stress_regime",
    }
    for index, row in enumerate(rows):
        missing = required - set(row)
        if missing:
            raise AuditError(f"score row {index} missing {sorted(missing)}")
        if int(row["horizon"]) not in {1, 5, 21, 63}:
            raise AuditError(f"score row {index} has unexpected horizon")
        quantiles = [float(row[key]) for key in ("p10", "p25", "p50", "p75", "p90")]
        if not all(math.isfinite(value) for value in quantiles) or quantiles != sorted(quantiles):
            raise AuditError(f"score row {index} has invalid quantiles")
        probability = float(row["up_probability"])
        if not 0.0 <= probability <= 1.0:
            raise AuditError(f"score row {index} has invalid probability unit")


def recompute_scores(archive: zipfile.ZipFile) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run = _read_json(archive, RUN_PATH)
    gate = _read_json(archive, GATE_PATH)
    verification = _read_json(archive, VERIFY_PATH)
    if run.get("run_id") != EXPECTED_RUN_ID:
        raise AuditError("sealed run id mismatch")
    raw = archive.read(SCORES_PATH)
    physical_hash = sha256_bytes(raw)
    canonical = raw.replace(b"\r\n", b"\n")
    logical_score_hash = sha256_bytes(canonical)
    rows = [json.loads(line) for line in canonical.decode("utf-8").splitlines() if line]
    _validate_score_rows(rows)
    by_horizon: dict[str, dict[str, Any]] = {}
    direction: dict[str, dict[str, Any]] = {}
    for horizon in (1, 5, 21, 63):
        selected = [row for row in rows if int(row["horizon"]) == horizon]
        by_horizon[str(horizon)] = _summary(selected)
        down = [row for row in selected if float(row["actual"]) < 0]
        up = [row for row in selected if float(row["actual"]) >= 0]
        direction[str(horizon)] = {
            "actual_up_rate": len(up) / len(selected),
            "p50_positive_rate": fmean(float(row["p50"]) > 0 for row in selected),
            "down_count": len(down),
            "downside_true_negative_rate": fmean(float(row["p50"]) < 0 for row in down),
        }
    paired: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if int(row["horizon"]) in {21, 63}:
            paired[str(row["origin"])].append(float(row["model_crps"]) - float(row["baseline_crps"]))
    paired_values = np.asarray([fmean(paired[key]) for key in sorted(paired)])
    ci = stationary_bootstrap_ci(paired_values)
    long_mean = fmean(by_horizon[str(h)]["improvement"] for h in (21, 63))

    research_reasons: list[str] = []
    if long_mean < 0.02:
        research_reasons.append("long_horizon_mean_crps_improvement_below_2pct")
    if any(by_horizon[str(h)]["improvement"] <= 0 for h in (21, 63)):
        research_reasons.append("long_horizon_not_individually_positive")
    if ci[1] > 0:
        research_reasons.append("paired_stationary_bootstrap_ci_upper_above_zero")
    stress: dict[str, Any] = {}
    extreme_q4: dict[str, Any] = {}
    sign_under = 0.0
    for horizon in (21, 63):
        selected = [row for row in rows if int(row["horizon"]) == horizon]
        for positive in (False, True):
            subset = [row for row in selected if (float(row["actual"]) >= 0) == positive]
            if subset:
                sign_under = max(sign_under, max(0.0, -_summary(subset)["improvement"]))
        threshold = float(np.quantile([abs(float(row["actual"])) for row in selected], 0.75))
        q4 = _summary([row for row in selected if abs(float(row["actual"])) >= threshold])
        q4["absolute_return_threshold"] = threshold
        extreme_q4[str(horizon)] = q4
        if q4["coverage_80"] < 0.65 or q4["coverage_80"] < q4["baseline_coverage_80"]:
            research_reasons.append(f"h{horizon}_extreme_q4_coverage")
        stress[str(horizon)] = {}
        for regime in ("gfc", "pandemic", "tightening", "rebound"):
            subset = [row for row in selected if row["stress_regime"] == regime]
            summary = _summary(subset)
            stress[str(horizon)][regime] = summary
            if len(subset) < 20 or summary["coverage_80"] < 0.70:
                research_reasons.append(f"h{horizon}_{regime}_coverage_or_sample")
    if sign_under > 0.05:
        research_reasons.append("return_sign_side_underperformance_above_5pct")
    for horizon in (1, 5, 21, 63):
        summary = by_horizon[str(horizon)]
        if not 0.76 <= summary["coverage_80"] <= 0.84:
            research_reasons.append(f"h{horizon}_p10_p90_coverage")
        if not 0.45 <= summary["coverage_50"] <= 0.55:
            research_reasons.append(f"h{horizon}_p25_p75_coverage")

    operational = verification["operational"]
    operational_recomputed = bool(operational.get("fit_snapshot_compatibility")) and all(
        bool(value.get("pass")) for value in operational["source_specific_freshness"].values()
    )
    integrity = verification
    integrity_recomputed = (
        int(integrity["pit"]["pit_leakage_count"]) == 0
        and float(integrity["pit"]["active_feature_provenance_rate"]) == 1.0
        and float(integrity["archive"]["receipt_observation_link_rate"]) == 1.0
        and int(integrity["runtime"]["contract_runtime_mismatch_count"]) == 0
    )
    result = {
        "row_count": len(rows),
        "origin_count": len({str(row["origin"]) for row in rows}),
        "horizon_count": len(by_horizon),
        "physical_scores_artifact_sha256": physical_hash,
        "logical_canonical_scores_sha256": logical_score_hash,
        "run_declared_scores_sha256": run.get("scores_sha256"),
        "hashes_match_expected": (
            physical_hash == EXPECTED_PHYSICAL_SCORE_SHA256
            and logical_score_hash == EXPECTED_LOGICAL_SCORE_SHA256
            and run.get("scores_sha256") == logical_score_hash
        ),
        "by_horizon": by_horizon,
        "long_horizon_mean_improvement": long_mean,
        "paired_stationary_bootstrap_90_ci": ci,
        "extreme_q4": extreme_q4,
        "stress_regimes": stress,
        "direction": direction,
        "integrity_gate_pass": integrity_recomputed,
        "research_gate_pass": not research_reasons,
        "research_gate_reasons": sorted(set(research_reasons)),
        "operational_gate_pass": operational_recomputed,
        "operational_gate_reasons": sorted(operational.get("reasons", [])),
        "numbers_visible": bool(integrity_recomputed and not research_reasons and operational_recomputed),
        "reported_gate_status": gate.get("status"),
        "reported_gate_matches": (
            gate["integrity_gate"]["pass"] == integrity_recomputed
            and gate["research_gate"]["pass"] == (not research_reasons)
            and gate["operational_gate"]["pass"] == operational_recomputed
            and gate["numbers_visible"] == bool(integrity_recomputed and not research_reasons and operational_recomputed)
        ),
        "reproducibility_boundary": {
            "stored_score_row_aggregation": "complete",
            "stationary_bootstrap_from_stored_loss_rows": "complete",
            "crps_recompute_from_per_origin_samples": "unavailable_samples_not_packaged",
            "full_model_refit": "not_performed_immutable_v6",
        },
    }
    return rows, result


def structural_failures(archive: zipfile.ZipFile, rows: list[dict[str, Any]]) -> dict[str, Any]:
    backtest = archive.read(BACKTEST_SOURCE_PATH).decode("utf-8-sig")
    gate_source = archive.read(GATE_SOURCE_PATH).decode("utf-8-sig")
    contract = archive.read(CONTRACT_PATH).decode("utf-8-sig")
    sealed_match = re.search(r'dates\s*>=\s*"(\d{4}-\d{2}-\d{2})"', backtest)
    gfc_match = re.search(
        r'if\s+"(\d{4}-\d{2}-\d{2})"\s*<=\s*origin\s*<=\s*"(\d{4}-\d{2}-\d{2})"\s*:\s*return\s*"gfc"',
        backtest,
    )
    minimum_match = re.search(r"len\(subset\)\s*<\s*(\d+)", gate_source)
    purge_match = re.search(r"np\.arange\(0,\s*index\s*-\s*(\d+)\)", backtest)
    purge_sessions = re.search(r"purge_sessions:\s*(\d+)", contract)
    embargo_sessions = re.search(r"embargo_sessions:\s*(\d+)", contract)
    weekly = "canonical_origin_frequency: weekly_last_completed_xnas_session" in contract
    if not all((sealed_match, gfc_match, minimum_match, purge_match, purge_sessions, embargo_sessions)):
        raise AuditError("required V6 structural coordinates are not parseable")
    sealed_start = date.fromisoformat(sealed_match.group(1))
    gfc_start, gfc_end = (date.fromisoformat(value) for value in gfc_match.groups())
    minimum = int(minimum_match.group(1))
    gfc_rows = [row for row in rows if row["stress_regime"] == "gfc"]
    unique_origins = sorted({date.fromisoformat(str(row["origin"])) for row in rows})
    row_offset = int(purge_match.group(1))
    gaps = [
        (unique_origins[index] - unique_origins[index - row_offset]).days
        for index in range(row_offset, len(unique_origins))
    ]
    contract_total = int(purge_sessions.group(1)) + int(embargo_sessions.group(1))
    return {
        "gfc_gate": {
            "sealed_start": sealed_start.isoformat(),
            "gfc_start": gfc_start.isoformat(),
            "gfc_end": gfc_end.isoformat(),
            "minimum_required": minimum,
            "sealed_gfc_rows": len(gfc_rows),
            "window_intersection_possible": not (sealed_start > gfc_end),
            "feasible": len(gfc_rows) >= minimum and sealed_start <= gfc_end,
            "assessment": "STRUCTURALLY_IMPOSSIBLE_UNDER_FROZEN_V6_WINDOW",
        },
        "purge_embargo": {
            "origin_frequency": "weekly_last_completed_xnas_session" if weekly else "unknown",
            "contract_purge_sessions": int(purge_sessions.group(1)),
            "contract_embargo_sessions": int(embargo_sessions.group(1)),
            "contract_total_sessions": contract_total,
            "implementation_expression": purge_match.group(0),
            "implementation_weekly_rows_excluded": row_offset,
            "sealed_grid_calendar_gap_days": {
                "min": min(gaps), "median": median(gaps), "max": max(gaps)
            },
            # ``index`` is a weekly-row coordinate.  Equality of the two
            # integers (68) does not make weekly rows equivalent to sessions.
            "unit_match": not weekly,
            "assessment": "P0_UNIT_MISMATCH_WEEKLY_ROWS_USED_AS_TRADING_SESSIONS",
        },
    }


def _close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def compare_independent_evidence(evidence: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    expected = evidence["independent_score_recomputation"]
    mismatches: list[str] = []
    for key in ("row_count", "origin_count", "horizon_count"):
        if int(expected[key]) != int(scores[key]):
            mismatches.append(key)
    for horizon in (1, 5, 21, 63):
        ours = scores["by_horizon"][str(horizon)]
        theirs = expected["by_horizon"][str(horizon)]
        mapping = {
            "model_crps": "model_crps",
            "baseline_crps": "baseline_crps",
            "improvement": "improvement",
            "coverage_80": "coverage_80",
            "coverage_50": "coverage_50",
        }
        for ours_key, their_key in mapping.items():
            if not _close(ours[ours_key], theirs[their_key]):
                mismatches.append(f"h{horizon}.{ours_key}")
    if not _close(scores["long_horizon_mean_improvement"], expected["long_horizon_mean_improvement"]):
        mismatches.append("long_horizon_mean_improvement")
    for index, value in enumerate(expected["paired_stationary_bootstrap_90_ci"]):
        if not _close(scores["paired_stationary_bootstrap_90_ci"][index], value):
            mismatches.append(f"paired_ci[{index}]")
    return {"pass": not mismatches, "mismatches": mismatches, "evidence_sha256": EXPECTED_EVIDENCE_SHA256}


def protected_manifest(repo_root: Path) -> dict[str, Any]:
    selected: dict[str, Path] = {}
    roots_present: dict[str, bool] = {}
    for relative in PROTECTED_ROOTS:
        root = repo_root / relative
        roots_present[relative] = root.exists()
        if root.is_file():
            selected[root.relative_to(repo_root).as_posix()] = root
        elif root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and ".secrets" not in path.parts:
                    selected[path.relative_to(repo_root).as_posix()] = path
    for relative in PROTECTED_FILES:
        path = repo_root / relative
        roots_present[relative] = path.exists()
        if path.is_file():
            selected[relative] = path
    entries = [
        {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for relative, path in sorted(selected.items())
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(entries),
        "roots_present": roots_present,
        "entries": entries,
        "content_hash": logical_hash(entries),
    }


def compare_protected(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    left = {row["path"]: (row["bytes"], row["sha256"]) for row in before["entries"]}
    right = {row["path"]: (row["bytes"], row["sha256"]) for row in after["entries"]}
    return {
        "pass": left == right,
        "before_hash": before["content_hash"],
        "after_hash": after["content_hash"],
        "added": sorted(set(right) - set(left)),
        "removed": sorted(set(left) - set(right)),
        "changed": sorted(path for path in set(left) & set(right) if left[path] != right[path]),
    }


def scan_secrets(paths: Iterable[Path]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    scanned = 0
    for root in paths:
        candidates = [root] if root.is_file() else list(root.rglob("*")) if root.is_dir() else []
        for path in candidates:
            if not path.is_file() or ".secrets" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                    matches.append({"path": str(path), "line": line_number, "value": "REDACTED"})
    return {"pass": not matches, "scanned_files": scanned, "matches": matches}


def sanitized_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not SENSITIVE_ENV_FRAGMENT.search(key)}


def run_command(command: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=sanitized_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    payload = (completed.stdout or "") + ("\n" if completed.stdout and completed.stderr else "") + (completed.stderr or "")
    atomic_write_bytes(log_path, payload.encode("utf-8", errors="replace"))
    return {
        "command": subprocess.list2cmdline(command),
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
        "log_path": str(log_path),
    }


def _pytest_counts(result: dict[str, Any]) -> tuple[int, int, int]:
    text = result["stdout_tail"] + "\n" + result["stderr_tail"]
    def count(label: str) -> int:
        match = re.search(rf"(\d+) {label}", text)
        return int(match.group(1)) if match else 0
    return count("passed"), count("failed"), count("skipped")


def build_report(
    pack_integrity: dict[str, Any],
    evidence_integrity: dict[str, Any],
    scores: dict[str, Any],
    structures: dict[str, Any],
    evidence_compare: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": "V7-P0-001",
        "audit_status": "succeeded" if all((pack_integrity["pass"], evidence_integrity["pass"], evidence_compare["pass"])) else "failed",
        "audit_success_does_not_mean_v6_gate_pass": True,
        "model_id": EXPECTED_MODEL_ID,
        "sealed_run_id": EXPECTED_RUN_ID,
        "manifest_pass": pack_integrity["pass"],
        "score_rows": scores["row_count"],
        "research_gate_pass": scores["research_gate_pass"],
        "operational_gate_pass": scores["operational_gate_pass"],
        "numbers_visible": scores["numbers_visible"],
        "gfc_gate_feasible": structures["gfc_gate"]["feasible"],
        "purge_unit_match": structures["purge_embargo"]["unit_match"],
        "h21_downside_tnr": scores["direction"]["21"]["downside_true_negative_rate"],
        "h63_downside_tnr": scores["direction"]["63"]["downside_true_negative_rate"],
        "protected_non_mutation": None,
        "secret_scan_pass": None,
        "next_task_started": False,
        "input_integrity": {"v6_review_pack": pack_integrity, "v7_evidence_pack": evidence_integrity},
        "independent_score_recomputation": scores,
        "structural_failures": structures,
        "independent_evidence_comparison": evidence_compare,
        "final_assessment": "V6_HOLD_REPRODUCED_IMMUTABLY",
    }


def artifact_rows(paths: Iterable[Path], repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        if path.is_file():
            rows.append({
                "path": path.relative_to(repo_root).as_posix(),
                "logical_sha256": sha256_file(path),
                "physical_sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            })
    return rows


def command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--evidence-pack", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path.cwd(), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--skip-tests", action="store_true", help="Used only by isolated fixtures")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    audit_dir = output.parent
    result_dir = repo_root / "outputs/timeseries_v7/task_results/V7-P0-001"
    before_path = audit_dir / "protected_manifest_before.json"
    after_path = audit_dir / "protected_manifest_after.json"
    secret_path = audit_dir / "secret_scan.json"
    artifact_manifest_path = audit_dir / "ARTIFACTS.sha256"
    result_path = result_dir / "result.json"
    doc_path = repo_root / "docs/timeseries_v7/V6_FAILURE_BASELINE.md"
    started_at = datetime.now(timezone.utc).isoformat()
    commands: list[dict[str, Any]] = []
    try:
        before = protected_manifest(repo_root)
        atomic_write_json(before_path, before)
        pack_integrity = verify_pack_integrity(
            args.pack,
            expected_sha256=EXPECTED_V6_PACK_SHA256,
            expected_bytes=EXPECTED_V6_PACK_BYTES,
            expected_entries=EXPECTED_V6_MANIFEST_ENTRIES,
        )
        evidence, evidence_integrity = verify_evidence_pack(args.evidence_pack)
        with zipfile.ZipFile(args.pack) as archive:
            rows, scores = recompute_scores(archive)
            structures = structural_failures(archive, rows)
        evidence_compare = compare_independent_evidence(evidence, scores)
        report = build_report(pack_integrity, evidence_integrity, scores, structures, evidence_compare)
        atomic_write_json(output, report)

        if not args.skip_tests:
            commands.append(run_command(
                [sys.executable, "-m", "pytest", "src/tests/timeseries_v7/test_v6_gate_audit.py", "-q", "-p", "no:cacheprovider"],
                repo_root,
                result_dir / "targeted_tests.log",
            ))
            commands.append(run_command(
                [sys.executable, "-m", "pytest", "src/tests/timeseries_v6/test_v6_research_gate.py", "-q", "-p", "no:cacheprovider"],
                repo_root,
                result_dir / "v6_gate_regression.log",
            ))
            commands.append(run_command(
                [sys.executable, "-m", "pytest", "src/tests/timeseries_v6", "--collect-only", "-q", "-p", "no:cacheprovider"],
                repo_root,
                result_dir / "broad_suite_collection.log",
            ))

        after = protected_manifest(repo_root)
        atomic_write_json(after_path, after)
        protected = compare_protected(before, after)
        report["protected_non_mutation"] = protected["pass"]
        report["protected_manifest"] = protected
        atomic_write_json(output, report)

        targeted_ok = args.skip_tests or (len(commands) >= 2 and commands[0]["returncode"] == 0 and commands[1]["returncode"] == 0)
        broad_environment_problem = bool(
            len(commands) >= 3
            and commands[2]["returncode"] != 0
            and "ModuleNotFoundError" in (commands[2]["stdout_tail"] + commands[2]["stderr_tail"])
        )
        acceptance = {
            "manifest_pass": report["manifest_pass"] is True,
            "score_rows": report["score_rows"] == 1540,
            "research_gate_is_false": report["research_gate_pass"] is False,
            "operational_gate_is_false": report["operational_gate_pass"] is False,
            "gfc_gate_is_infeasible": report["gfc_gate_feasible"] is False,
            "purge_unit_mismatch_detected": report["purge_unit_match"] is False,
            "h21_downside_tnr_is_zero": report["h21_downside_tnr"] == 0,
            "h63_downside_tnr_is_zero": report["h63_downside_tnr"] == 0,
            "protected_non_mutation": protected["pass"],
            "independent_evidence_match": evidence_compare["pass"],
            "score_hashes_match": scores["hashes_match_expected"],
            "targeted_and_v6_regression_tests": targeted_ok,
            "next_task_not_started": report["next_task_started"] is False,
        }
        passed = failed = skipped = 0
        for test_result in commands[:2]:
            counts = _pytest_counts(test_result)
            passed += counts[0]; failed += counts[1]; skipped += counts[2]
        preliminary_status = "succeeded" if all(acceptance.values()) else "blocked"
        result = {
            "schema_version": 1,
            "run_id": f"v7-p0-001-{EXPECTED_V6_PACK_SHA256[:16]}",
            "cycle_id": "v7-bootstrap-audit-20260825",
            "generation_id": "v7-pre-generation-v6-baseline",
            "task_key": "V7-P0-001",
            "status": preliminary_status,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "input_hashes_verified": pack_integrity["pass"] and evidence_integrity["pass"],
            "changed_files": [],
            "commands": commands,
            "tests": {"passed": passed, "failed": failed, "skipped": skipped},
            "broad_suite": {
                "status": "unavailable_environment" if broad_environment_problem else ("pass" if len(commands) >= 3 and commands[2]["returncode"] == 0 else "not_run"),
                "dependency_changes_made": False,
            },
            "artifacts": [],
            "protected_manifest": {
                "before_hash": protected["before_hash"],
                "after_hash": protected["after_hash"],
                "unchanged": protected["pass"],
            },
            "secret_scan": {"pass": False, "matches": []},
            "acceptance": acceptance,
            "blocker": None if preliminary_status == "succeeded" else "V7_P0_001_ACCEPTANCE_FAILED",
            "next_recommended_task": None,
            "next_task_started": False,
        }
        atomic_write_json(result_path, result)
        secret = scan_secrets((audit_dir, result_dir, doc_path))
        atomic_write_json(secret_path, secret)
        report["secret_scan_pass"] = secret["pass"]
        report["content_sha256"] = logical_hash({key: value for key, value in report.items() if key != "content_sha256"})
        atomic_write_json(output, report)
        acceptance["secret_scan_pass"] = secret["pass"]
        result["secret_scan"] = secret
        result["acceptance"] = acceptance
        result["status"] = "succeeded" if all(acceptance.values()) else "blocked"
        result["blocker"] = None if result["status"] == "succeeded" else "V7_P0_001_ACCEPTANCE_FAILED"
        code_path = repo_root / "tools/audit_v6_gate.py"
        test_path = repo_root / "src/tests/timeseries_v7/test_v6_gate_audit.py"
        primary_artifacts = [
            code_path, test_path, doc_path, output, before_path, after_path,
            secret_path, *[Path(row["log_path"]) for row in commands],
        ]
        result["artifacts"] = artifact_rows(primary_artifacts, repo_root)
        result["changed_files"] = sorted({row["path"] for row in result["artifacts"]} | {result_path.relative_to(repo_root).as_posix(), artifact_manifest_path.relative_to(repo_root).as_posix()})
        result["content_sha256"] = logical_hash({key: value for key, value in result.items() if key != "content_sha256"})
        atomic_write_json(result_path, result)
        manifest_targets = [*primary_artifacts, result_path]
        lines = "".join(
            f"{sha256_file(path)}  {path.relative_to(repo_root).as_posix()}\n"
            for path in sorted(set(manifest_targets))
            if path.is_file()
        )
        atomic_write_bytes(artifact_manifest_path, lines.encode("utf-8"))
        if not protected["pass"] or not secret["pass"]:
            return 3
        return 0 if result["status"] == "succeeded" else 2
    except (AuditError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        error = {
            "schema_version": 1,
            "task_key": "V7-P0-001",
            "status": "blocked",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "blocker": f"{type(exc).__name__}:{exc}",
            "next_task_started": False,
        }
        atomic_write_json(result_path, error)
        print(error["blocker"], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(command())
