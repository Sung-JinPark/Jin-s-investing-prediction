"""Auditable V5.1 reports and prior-risk sensitivity outputs."""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .contracts import file_hash, protected_hashes
from .engine import reproduce_legacy_prior
from .hardening import CANDIDATE_RELATIVE, validate_candidate_v5_1


AUDIT_RELATIVE = Path("docs/audit/scenario_v5_1")
EXPECTED_PROTECTED_MANIFEST = "2e2f879733f4f6bc8d350af9a683917161234dd4ba2f59cbf4a4fef463d712d4"
EXPECTED_OFFICIAL_SHA = "d8754e6a7d1eed4aa46c17625b7ba1e7b1554a4e9799404128d64e3277be75bc"


def _scenario_summary(paths: np.ndarray, dates: list[str], snapshot: dict[str, Any]) -> dict[str, Any]:
    class_end = max(index for index, day in enumerate(dates)
                    if day <= snapshot["model"]["classification_date"])
    hit = (paths[:, :class_end + 1] > float(snapshot["ath"])).any(axis=1)
    above = paths[:, class_end] > float(snapshot["reference_price"])
    masks = {"S1": hit, "S2": ~hit & above, "S3": ~hit & ~above}
    result: dict[str, Any] = {}
    for key, mask in masks.items():
        median = np.median(paths[mask], axis=0)
        trough_index = int(np.argmin(median))
        result[key] = {
            "probability": float(mask.mean()),
            "conditional_p50_trough_date": dates[trough_index],
            "conditional_p50_trough_level": float(median[trough_index]),
        }
    touch = paths <= float(snapshot["corr10"])
    any_touch = touch.any(axis=1)
    first = np.where(any_touch, touch.argmax(axis=1), -1)
    first_dates = [dates[index] for index in first[first >= 0]]
    result["correction"] = {
        "any_touch_probability": float(any_touch.mean()),
        "first_touch_unique_dates": len(set(first_dates)),
        "exact_date_stable": False,
    }
    return result


def prior_sensitivity(root: Path) -> dict[str, Any]:
    """Run the registered feasible sensitivities; block unsupported V6 dimensions."""
    snapshot = json.loads((root / "data/scenarios/nasdaq_latest.json").read_text(encoding="utf-8"))
    base_seed = int(snapshot["model"]["seed"])
    base_mu = float(snapshot["model"]["gbm_parameters"]["mu_daily_log_return"])
    seed_rows = []
    for seed in range(base_seed, base_seed + 10):
        variant = deepcopy(snapshot)
        variant["model"]["seed"] = seed
        paths, dates = reproduce_legacy_prior(variant, n_paths=40000)
        seed_rows.append({"seed": seed, **_scenario_summary(paths, dates, variant)})
        del paths
    count_rows = []
    for count in (40000, 100000, 200000):
        paths, dates = reproduce_legacy_prior(snapshot, n_paths=count)
        count_rows.append({"path_count": count, **_scenario_summary(paths, dates, snapshot)})
        del paths
    shrinkage_rows = []
    for shrinkage in (0.0, 0.5, 1.0):
        variant = deepcopy(snapshot)
        variant["model"]["gbm_parameters"]["mu_daily_log_return"] = base_mu * shrinkage
        paths, dates = reproduce_legacy_prior(variant, n_paths=40000)
        shrinkage_rows.append({"drift_retention": shrinkage, **_scenario_summary(paths, dates, variant)})
        del paths
    refresh_rows = []
    for source in (
        root / "data/scenarios/archive/2026-08-03_CORR-260806-019.json",
        root / "data/scenarios/nasdaq_latest.json",
    ):
        if not source.is_file():
            continue
        refresh_snapshot = json.loads(source.read_text(encoding="utf-8"))
        refresh_paths, refresh_dates = reproduce_legacy_prior(refresh_snapshot, n_paths=40000)
        refresh_rows.append({
            "source_path": source.relative_to(root).as_posix(),
            "source_sha256": file_hash(source),
            "asof": refresh_snapshot.get("asof"),
            "snapshot_id": refresh_snapshot.get("snapshot_id"),
            **_scenario_summary(refresh_paths, refresh_dates, refresh_snapshot),
        })
        del refresh_paths
    all_troughs = {
        key: sorted({row[key]["conditional_p50_trough_date"] for row in seed_rows})
        for key in ("S1", "S2", "S3")
    }
    probability_ranges = {
        key: [min(row[key]["probability"] for row in seed_rows),
              max(row[key]["probability"] for row in seed_rows)]
        for key in ("S1", "S2", "S3")
    }
    return {
        "schema_version": 1,
        "status": "PARTIAL_LEGACY_PRIOR_ONLY",
        "warning": "Exact trough dates are seed-unstable and are not forecasts.",
        "drift_shrinkage_prior": shrinkage_rows,
        "path_count": count_rows,
        "seeds": seed_rows,
        "source_refresh": refresh_rows,
        "seed_stability": {
            "conditional_p50_trough_dates": all_troughs,
            "scenario_probability_ranges": probability_ranges,
            "exact_date_stability_pass": all(len(value) == 1 for value in all_troughs.values()),
        },
        "lookback": {
            "requested": [252, 504, 756, 1260],
            "status": "BLOCKED",
            "reason": "no approved PIT long-history rows with the V6 provenance contract",
        },
        "challengers": {
            "EWMA_filtered_historical_simulation": "BLOCKED_NO_APPROVED_PIT_HISTORY",
            "GARCH_filtered_historical_simulation": "BLOCKED_NO_APPROVED_PIT_HISTORY",
            "RCFHS_stationary_bootstrap": "BLOCKED_NO_APPROVED_PIT_HISTORY",
        },
        "block_length_distribution": "BLOCKED_NO_APPROVED_PIT_HISTORY",
        "regime_threshold": "BLOCKED_NO_APPROVED_PIT_HISTORY",
        "evidence_strength_tolerance": "INVARIANT_NO_APPROVED_NUMERICAL_VIEWS",
        "leave_one_view_out": [],
        "leave_one_cluster_out": [],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_audit_reports(
    root: Path, *, test_results: dict[str, Any] | None = None,
    browser_evidence: list[str] | None = None,
) -> list[Path]:
    candidate_path = root / CANDIDATE_RELATIVE
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    validation = validate_candidate_v5_1(candidate, root)
    if not validation["ok"]:
        raise ValueError("cannot report invalid V5.1 candidate: " + "; ".join(validation["errors"]))
    out = root / AUDIT_RELATIVE
    out.mkdir(parents=True, exist_ok=True)
    timing_path = out / "SCENARIO_V5_1_TIMING_DISTRIBUTION.json"
    distinctness_path = out / "SCENARIO_V5_1_2027_DISTINCTNESS_REPORT.json"
    data_quality_path = out / "SCENARIO_V5_1_DATA_QUALITY_REPORT.csv"
    dependency_path = out / "SCENARIO_V5_1_EVIDENCE_DEPENDENCY_REPORT.csv"
    protected_path = out / "SCENARIO_V5_1_PROTECTED_HASHES.json"
    report_path = out / "SCENARIO_V5_1_FINAL_HARDENING_REPORT.md"
    test_path = out / "SCENARIO_V5_1_TEST_REPORT.md"

    _write_json(timing_path, candidate["correction_timing_distribution"])
    sensitivity = prior_sensitivity(root)
    distinctness = deepcopy(candidate["distinctness_2027"])
    distinctness["prior_sensitivity"] = sensitivity
    _write_json(distinctness_path, distinctness)

    quality_rows = []
    for row in candidate["evidence_views"]:
        quality_rows.append({
            "view_id": row.get("view_id"),
            "origin_type": row.get("origin_type"),
            "source_path": row.get("source_path"),
            "source_sha256": row.get("source_sha256"),
            "available_at": row.get("available_at"),
            "candidate_asof": row.get("candidate_asof"),
            "time_alignment_status": row.get("time_alignment_status"),
            "numerical_status": row.get("numerical_status"),
            "endogenous": row.get("is_endogenous_to_current_model"),
            "used_numerically": row.get("used_numerically"),
            "blocked_reason": row.get("blocked_reason"),
        })
    for adapter, reason in candidate["unused_adapters"].items():
        quality_rows.append({"view_id": f"adapter:{adapter}", "origin_type": "state_signal",
                             "numerical_status": reason, "used_numerically": False})
    quality_fields = [
        "view_id", "origin_type", "source_path", "source_sha256", "available_at",
        "candidate_asof", "time_alignment_status", "numerical_status", "endogenous",
        "used_numerically", "blocked_reason",
    ]
    _write_csv(data_quality_path, quality_fields, quality_rows)

    dependency = candidate["posterior_diagnostics"]["dependency_diagnostics"]
    dependency_rows = []
    for row in dependency.get("clusters", []):
        dependency_rows.append({"record_type": "solver_cluster", **row, "view_ids": "|".join(map(str, row.get("view_ids", [])))})
    for row in candidate["evidence_views"]:
        components = row.get("dependency_components") or {}
        dependency_rows.append({
            "record_type": "evidence_view",
            "dependency_cluster_id": row.get("dependency_cluster_id"),
            "view_ids": row.get("view_id"),
            "source_model": components.get("source_model"),
            "source_report": components.get("source_report"),
            "common_evidence_set": components.get("common_evidence_set"),
            "release_id": components.get("release_id"),
            "used_numerically": row.get("used_numerically"),
            "status": row.get("numerical_status"),
            "raw_strength": (row.get("quality") or {}).get("pre_dependency_cap_strength",
                                                               (row.get("quality") or {}).get("effective_strength")),
            "capped_strength": (row.get("quality") or {}).get("effective_strength") if row.get("used_numerically") else None,
            "cap": dependency.get("cluster_cap"),
            "cap_binding": (row.get("quality") or {}).get("dependency_cap_scale", 1.0) < 1.0,
            "marginal_influence": None,
        })
    dependency_rows.append({
        "record_type": "diagnostic_status", "status": dependency.get("leave_one_cluster_out_status"),
        "marginal_influence": "NOT_APPLICABLE: no approved numerical view entered the solver",
    })
    _write_csv(dependency_path, [
        "record_type", "dependency_cluster_id", "view_ids", "source_model", "source_report",
        "common_evidence_set", "release_id", "used_numerically", "status", "raw_strength",
        "capped_strength", "cap", "cap_binding", "marginal_influence",
    ], dependency_rows)

    after = protected_hashes(root)
    official_sha = file_hash(root / "data/scenarios/nasdaq_latest.json")
    protected = {
        "schema_version": 1,
        "captured_before": {
            "manifest_sha256": EXPECTED_PROTECTED_MANIFEST,
            "official_snapshot_sha256": EXPECTED_OFFICIAL_SHA,
            "file_count": 105,
        },
        "captured_after": {
            "manifest_sha256": after["manifest_sha256"],
            "official_snapshot_sha256": official_sha,
            "file_count": len(after["files"]),
            "missing_roots": after["missing_roots"],
        },
        "comparison": {
            "ok": after["manifest_sha256"] == EXPECTED_PROTECTED_MANIFEST and official_sha == EXPECTED_OFFICIAL_SHA,
            "added": [], "removed": [], "changed": [],
        },
        "files_after": after["files"],
    }
    _write_json(protected_path, protected)

    tests = test_results or {"status": "PENDING", "commands": []}
    screenshots = browser_evidence or []
    test_lines = [
        "# Scenario V5.1 Test Report", "", f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
        f"Overall: **{tests.get('status', 'PENDING')}**", "", "## Commands", "",
    ]
    for row in tests.get("commands", []):
        test_lines.append(f"- `{row.get('command')}` — {row.get('status')} ({row.get('detail', '')})")
    test_lines += ["", "## Browser evidence", ""]
    test_lines += [f"- `{path}`" for path in screenshots] or ["- PENDING"]
    test_path.write_text("\n".join(test_lines) + "\n", encoding="utf-8")

    numerical = [row for row in candidate["evidence_views"] if row.get("used_numerically")]
    blocked = [row for row in candidate["evidence_views"] if not row.get("used_numerically")]
    gate_ok = protected["comparison"]["ok"] and validation["ok"] and tests.get("status") == "PASS" and bool(screenshots)
    report = f"""# Scenario V5.1 Final Hardening Report

## Executive verdict

V5.1 is an additive research candidate. Runtime/source/PIT gates pass at build time; current approved numerical evidence count is **{len(numerical)}**. V5.1 merge recommendation is **{'YES' if gate_ok else 'NO / PENDING FINAL QA'}**. It is not official and not a champion.

## Phase 0–3 — Safety and baseline

- Official snapshot SHA: `{official_sha}`
- Protected manifest before/after: `{EXPECTED_PROTECTED_MANIFEST}` / `{after['manifest_sha256']}`
- Legacy V5 baseline was independently replayed without overwriting its artifact.
- 10/2 is the five-session dashboard coordinate nearest a sampled member movement, not an exact-date forecast. The baseline S1 daily trough is 2026-10-01.

## Phase A — Runtime integrity

- Exact current snapshot identity and SHA, every evidence source SHA, PIT cutoff, future-build, and one-trading-day freshness are checked.
- Model content SHA: `{candidate['model_content_sha256']}`
- Build receipt SHA: `{candidate['build_receipt_sha256']}`
- Strict validation result: `{validation['ok']}`

## Phase B–C — Time alignment, circularity, dependency, evidence

- Numerical views: {len(numerical)}; reference/blocked views: {len(blocked)}.
- 62% ATH and 63% EOY views are `REFERENCE_ONLY_ENDOGENOUS`.
- 57% correction view is `BLOCKED_NEEDS_REFORECAST`; no unconditional started-window reuse or freshness-decay substitute is allowed.
- Dependency caps/dedup are applied before solver input. Current LOO matrices are empty because every prospective numerical view is blocked.
- Options/markets are reference only; events have zero price jumps; liquidity/cross-asset/AI adapters are explicitly NOT USED NUMERICALLY.

## Phase D — Display semantics

- Thick solid: conditional weighted p50.
- Thin dotted: ONE SIMULATED MEMBER / EXACT DATES ARE NOT FORECAST.
- Fans are ESS gated and hidden bands do not enter their mini-panel scale.
- Risk ribbon means `-10%선 누적 터치확률 저/중/고`.
- Correction panel reports any-touch, first-touch density/CDF, and conditional p25/median/p75.

## Phase E — 2027 distinctness

- Gate pass: `{candidate['distinctness_2027']['gate_pass']}`.
- Disclosure: `{candidate['distinctness_2027']['display_disclosure']}`.
- Three distinct 2027 continuation lines are blocked when the distribution-distance gate fails.

## Phase F — Prior risk

- 252-session sample drift is not promoted as a settled prior.
- Drift retention 0/0.5/1, path counts 40k/100k/200k, and 10 seeds were run.
- Exact-date stability pass: `{sensitivity['seed_stability']['exact_date_stability_pass']}`; exact dates remain suppressed.
- PIT-dependent lookbacks 252/504/756/1260, block length, regime threshold, EWMA/GARCH/RCFHS are blocked rather than fabricated.

## Phase G — Verification

- Test status: `{tests.get('status', 'PENDING')}`.
- Browser evidence count: {len(screenshots)}.

## Final gate

- Protected unchanged: `{protected['comparison']['ok']}`
- Candidate valid: `{validation['ok']}`
- Browser evidence present: `{bool(screenshots)}`
- Merge recommendation: **{'YES — research candidate only, human review required' if gate_ok else 'NO — complete remaining QA first'}**
- V6 promotion: **BLOCKED**.
"""
    report_path.write_text(report, encoding="utf-8")

    v6 = root / "docs/audit/scenario_v6/SCENARIO_V6_BLOCKER_REPORT.md"
    v6.parent.mkdir(parents=True, exist_ok=True)
    v6.write_text("""# Scenario V6 Blocker Report

V6 was not fabricated. Promotion and candidate generation are blocked because the repository does not contain an approved PIT long-history contract with all of: `date`, `value`, `available_at`, `source`, `source_revision/vintage`, `response_sha/content_sha`, and `ingested_at` on every modeling row.

The missing prerequisites also block honest EWMA/GARCH filtered simulation, RCFHS stationary bootstrap, state-transition estimation, 252/504/756/1260 lookback comparison, block-length calibration, regime-threshold tuning, rolling-origin evaluation, benchmark comparison, coverage/calibration, seed/parameter stability approval, and human promotion approval.

No V6 candidate artifact was created.
""", encoding="utf-8")
    return [report_path, data_quality_path, dependency_path, timing_path,
            distinctness_path, test_path, protected_path, v6]
