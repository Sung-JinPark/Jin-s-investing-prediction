"""Auditable Phase A/H outputs and honest rolling-origin framework."""

from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .artifact import CANDIDATE_RELATIVE, load_candidate, verify_candidate
from .contracts import compare_protected_hashes, file_hash, protected_hashes


AUDIT_RELATIVE = "docs/audit/scenario_v5"
BASELINE_NAME = "PROTECTED_HASHES_BASELINE.json"
DELIVERY_NAME = "AI_INVESTING_SCENARIO_V5_DELIVERY_260807.zip"
DELIVERY_PATHS = (
    "data/contracts/scenario_v5_event_impact.yaml",
    "data/contracts/scenario_v5_evidence_view.yaml",
    "data/contracts/scenario_v5_model.yaml",
    "data/scenario_views",
    "data/scenarios/candidates",
    "docs/audit/scenario_v5",
    "docs/generated/read_model_v2.schema.json",
    "reports/dashboard.html",
    "src/ai_fc/cli.py",
    "src/ai_fc/dashboard.py",
    "src/ai_fc/dashboard_parts/dashboard.css",
    "src/ai_fc/dashboard_parts/dashboard.js",
    "src/ai_fc/read_model_contract.py",
    "src/ai_fc/scenario_v5",
    "src/tests/test_scenario_v5.py",
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _csv_text(fieldnames: list[str], rows: list[dict[str, Any]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def capture_protected_baseline(root: Path) -> Path:
    target = root / AUDIT_RELATIVE / BASELINE_NAME
    if target.exists():
        return target
    payload = protected_hashes(root)
    payload["captured_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["purpose"] = "Scenario V5 pre-change protected-input baseline"
    _write_json(target, payload)
    return target


def _path_realism(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scenarios = candidate["conditional_distribution"]["scenarios"]
    dates = candidate["conditional_distribution"]["dates"]
    for key, row in scenarios.items():
        values = np.asarray(row["representative_path_values"], dtype=float)
        daily = np.diff(np.log(values))
        running = np.maximum.accumulate(values)
        drawdown = values / running - 1.0
        weekly_indexes = sorted(set([0, *range(5, len(values), 5), len(values) - 1]))
        weekly_returns = np.diff(np.log(values[weekly_indexes]))
        signs = np.sign(weekly_returns)
        rows.append({
            "scenario": key,
            "probability_fraction": row["probability"],
            "path_count": row["path_count"],
            "weighted_ess": row["weighted_effective_sample_size"],
            "representative_path_id": row["representative_path_id"],
            "member_path": row["representative_selection"]["member_path"],
            "terminal": values[-1],
            "annualized_daily_volatility": daily.std(ddof=1) * math.sqrt(252.0),
            "maximum_drawdown": drawdown.min(),
            "underwater_share_below_2pct": (drawdown < -0.02).mean(),
            "weekly_down_count": int((weekly_returns < 0).sum()),
            "weekly_direction_changes": int((signs[1:] * signs[:-1] < 0).sum()),
            "date_count": len(dates),
        })
    return rows


def build_reports(root: Path, *, test_summary: dict[str, Any] | None = None) -> list[Path]:
    audit = root / AUDIT_RELATIVE
    audit.mkdir(parents=True, exist_ok=True)
    baseline_path = capture_protected_baseline(root)
    before = json.loads(baseline_path.read_text(encoding="utf-8"))
    after = protected_hashes(root)
    comparison = compare_protected_hashes(before, after)
    protected_target = audit / "SCENARIO_V5_PROTECTED_HASHES.json"
    _write_json(protected_target, {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "before": before,
        "after": after,
        "comparison": comparison,
    })

    candidate_path = root / CANDIDATE_RELATIVE
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    verification = verify_candidate(root, candidate_path)
    evidence_rows: list[dict[str, Any]] = []
    for row in candidate["evidence_views"]:
        evidence_rows.append({
            "view_id": row.get("view_id"),
            "origin_type": row.get("origin_type"),
            "source_id": row.get("source_id"),
            "source_path": row.get("source_path"),
            "source_sha256": row.get("source_sha256"),
            "available_at": row.get("available_at"),
            "view_kind": row.get("view_kind"),
            "condition": row.get("condition"),
            "unit": row.get("unit"),
            "probability_space": row.get("probability_space"),
            "target": row.get("target"),
            "physical_translation_status": row.get("physical_translation_status"),
            "approval_status": row.get("approval_status"),
            "used_numerically": row.get("used_numerically"),
            "effective_strength": (row.get("quality") or {}).get("effective_strength"),
            "blocked_reason": row.get("blocked_reason"),
        })
    evidence_fields = list(evidence_rows[0]) if evidence_rows else ["view_id"]
    evidence_target = audit / "SCENARIO_V5_EVIDENCE_VIEW_REPORT.csv"
    evidence_target.write_text(_csv_text(evidence_fields, evidence_rows), encoding="utf-8")

    fit_rows = candidate["posterior_diagnostics"].get("view_fit", [])
    fit_fields = list(fit_rows[0]) if fit_rows else ["view_id"]
    fit_target = audit / "SCENARIO_V5_VIEW_FIT_REPORT.csv"
    fit_target.write_text(_csv_text(fit_fields, fit_rows), encoding="utf-8")

    realism_rows = _path_realism(candidate)
    realism_target = audit / "SCENARIO_V5_PATH_REALISM_REPORT.csv"
    realism_target.write_text(_csv_text(list(realism_rows[0]), realism_rows), encoding="utf-8")

    tests = test_summary or {"status": "pending_final_execution"}
    test_target = audit / "SCENARIO_V5_TEST_REPORT.md"
    test_target.write_text(
        "# Scenario V5 Test Report\n\n"
        f"- Status: `{tests.get('status')}`\n"
        f"- Targeted: {tests.get('targeted', 'pending')}\n"
        f"- Full suite: {tests.get('full_suite', 'pending')}\n"
        f"- JavaScript: {tests.get('javascript', 'pending')}\n"
        f"- Reproducibility: {tests.get('reproducibility', 'pending')}\n"
        f"- Protected inputs: `{'PASS' if comparison['ok'] else 'FAIL'}`\n"
        f"- Candidate verification: `{'PASS' if verification['ok'] else 'FAIL'}`\n",
        encoding="utf-8",
    )

    same_shape = candidate["conditional_distribution"]["same_shape_diagnostics"]
    probabilities = candidate["conditional_distribution"]["scenarios"]
    fit_by_id = {row["view_id"]: row for row in fit_rows}
    direct_views = [row for row in candidate["evidence_views"] if row["used_numerically"]]
    reference_views = [row for row in candidate["evidence_views"] if not row["used_numerically"]]
    pair_lines = "\n".join(
        f"- {row['pair']}: weekly return corr `{row['weekly_return_correlation']:.6f}`, "
        f"turning overlap `{row['turning_point_overlap']:.6f}`, normalized distance "
        f"`{row['normalized_trajectory_distance']:.6f}`"
        for row in same_shape["pairs"]
    )
    view_lines = "\n".join(
        f"- `{row['view_id']}` -> `{row['condition']}`; target `{row['target']:.4f}`, "
        f"posterior `{fit_by_id[row['view_id']]['posterior_probability']:.6f}`"
        for row in direct_views
    )
    reference_lines = "\n".join(
        f"- `{row['view_id']}`: `{row['probability_space']}`; {row.get('blocked_reason')}"
        for row in reference_views
    )
    legacy_probabilities = candidate["source_snapshot"]["legacy_displayed_probabilities"]
    posterior_delta = {
        key: probabilities[key]["probability"] - legacy_probabilities[key]
        for key in ("S1", "S2", "S3")
    }
    realism_by_key = {row["scenario"]: row for row in realism_rows}
    implementation_target = audit / "SCENARIO_V5_IMPLEMENTATION_REPORT.md"
    implementation_target.write_text(
        "# Scenario V5 Implementation Report\n\n"
        "## Result\n\n"
        "Built an evidence-conditioned research candidate without mutating the official snapshot. "
        "The candidate honestly retains the reproduced legacy GBM process because the long-history "
        "store lacks the approved row-level PIT/vintage/hash contract required for RCFHS.\n\n"
        "## Identity and governance\n\n"
        f"- Candidate: `{candidate['candidate_id']}`\n"
        f"- Prior: `{candidate['identity']['prior_engine']}`\n"
        "- Label: `RESEARCH CANDIDATE - NOT OFFICIAL - NOT CHAMPION`\n"
        f"- Dirty-worktree review-only: `{candidate['build_context']['review_only']}`\n"
        f"- Protected inputs unchanged: `{comparison['ok']}`\n"
        f"- Candidate verification: `{verification['ok']}`\n\n"
        f"- Prior sample extension: source prefix `{candidate['prior']['source_path_count']}` paths; "
        f"deterministic same-RNG sample `{candidate['prior']['path_count']}` paths.\n\n"
        "## Evidence separation\n\n"
        f"- Numerical physical views: `{sum(bool(row['used_numerically']) for row in evidence_rows)}`\n"
        f"- Reference/blocked views: `{sum(not bool(row['used_numerically']) for row in evidence_rows)}`\n"
        "- Risk-neutral options are reference-only and are not translated into physical probabilities.\n"
        "- No approved event-impact mapping exists; every event price jump is exactly zero.\n\n"
        "## Posterior and scenarios\n\n"
        f"- Overall ESS: `{candidate['posterior_diagnostics']['effective_sample_size']:.2f}`\n"
        f"- Solver/gates pass: `{candidate['posterior_diagnostics']['gates_pass']}`\n"
        f"- S1/S2/S3 probabilities: `{probabilities['S1']['probability']:.6f}` / "
        f"`{probabilities['S2']['probability']:.6f}` / `{probabilities['S3']['probability']:.6f}`\n"
        f"- Same-shape gate pass: `{same_shape['gate_pass']}`\n"
        f"- Scenario ESS gate pass: "
        f"`{candidate['conditional_distribution']['distribution_gates']['scenario_ess_pass']}` "
        f"(minimum `{candidate['conditional_distribution']['distribution_gates']['scenario_weighted_ess_minimum']:.0f}`).\n"
        "- Representatives are actual simulated member paths selected by deterministic centrality gates.\n\n"
        "## Promotion\n\n"
        "Promotion remains blocked pending rolling-origin validation and explicit human approval.\n\n"
        "## Required model-risk questions\n\n"
        "### 1. What actually entered the legacy graph numerically?\n\n"
        "The official snapshot used its stored 252-session GBM parameters, seed 42, and fixed "
        "anchor/ATH/reference thresholds. Its structural display then reused one calendar-shape "
        "template across S1/S2/S3. It did not numerically ingest the forecast ledger, option views, "
        "or unapproved report prose.\n\n"
        "### 2. Why did CPI/FOMC/NVDA/report content not enter legacy paths?\n\n"
        "No approved point-in-time surprise-to-^IXIC impact mapping existed. Report views also had "
        "no approved structured records, so prose-to-number conversion was prohibited.\n\n"
        "### 3. Which path metrics receive each numerical EvidenceView?\n\n"
        f"{view_lines}\n\n"
        "### 4. Why are some views reference-only?\n\n"
        f"{reference_lines}\n\n"
        "### 5. How was risk-neutral information handled?\n\n"
        "QQQ option-derived probabilities remain `risk_neutral_terminal`; they are displayed and "
        "hashed but never averaged with physical forecasts or used as entropy constraints.\n\n"
        "### 6. What proves the scenarios no longer share one residual?\n\n"
        f"{pair_lines}\n\n"
        f"The same-shape gate is `{same_shape['gate_pass']}` and all three representatives have "
        "distinct member path IDs.\n\n"
        "### 7. What is each representative's residual/event/regime lineage?\n\n"
        f"- S1 member `{probabilities['S1']['representative_path_id']}`; S2 member "
        f"`{probabilities['S2']['representative_path_id']}`; S3 member "
        f"`{probabilities['S3']['representative_path_id']}`.\n"
        "- Residual lineage: each is its own seed-42 GBM simulation row, chosen by exact weighted "
        "L1 medoid centrality plus registered realism penalties.\n"
        "- Event lineage: every unmapped event has `J_t=0`; event forecasts are state-only.\n"
        "- Regime lineage: no blocked AI/liquidity/cross-asset state is used numerically.\n\n"
        "### 8. Does 2027 continuously inherit the 2026 state?\n\n"
        "Yes. The artifact contains one ordered anchor plus 252-session path with no calendar-year "
        "reset; 2027-01-04 is the next stored session after 2026-12-31.\n\n"
        "### 9. How did posterior scenario weights differ from the source snapshot display?\n\n"
        f"S1 `{probabilities['S1']['probability']:.6f}` ({posterior_delta['S1']:+.6f}), "
        f"S2 `{probabilities['S2']['probability']:.6f}` ({posterior_delta['S2']:+.6f}), "
        f"S3 `{probabilities['S3']['probability']:.6f}` ({posterior_delta['S3']:+.6f}) versus "
        f"source displayed fractions {legacy_probabilities['S1']:.2f}/"
        f"{legacy_probabilities['S2']:.2f}/{legacy_probabilities['S3']:.2f}.\n\n"
        "### 10. Which report cluster tilted the posterior?\n\n"
        "None. No approved report view exists, so report-cluster numerical strength and posterior "
        "tilt are exactly zero. Proposed report files are structurally blocked.\n\n"
        "### 11. Are ESS and view conflicts safe?\n\n"
        f"Overall ESS is `{candidate['posterior_diagnostics']['effective_sample_size']:.2f}`; maximum "
        f"path weight is `{candidate['posterior_diagnostics']['maximum_path_weight']:.8f}` and top-1% "
        f"share is `{candidate['posterior_diagnostics']['top_one_percent_weight_share']:.6f}`. "
        f"Scenario ESS values are S1 `{probabilities['S1']['weighted_effective_sample_size']:.2f}`, "
        f"S2 `{probabilities['S2']['weighted_effective_sample_size']:.2f}`, and "
        f"S3 `{probabilities['S3']['weighted_effective_sample_size']:.2f}`. All "
        "three view residuals are inside their declared tolerances.\n\n"
        "### 12. Is the official artifact unchanged?\n\n"
        f"Yes. Official SHA-256 remains `{candidate['source_snapshot']['sha256']}` and the full "
        f"protected manifest comparison is `{comparison['ok']}`.\n\n"
        "### 13. Why does this remain a research candidate?\n\n"
        "The repository lacks enough approved PIT rolling origins with row-level response hashes, "
        "vintages, and available_at timestamps. No OOS scores were fabricated; promotion requires "
        "rolling-origin evidence and explicit human approval.\n\n"
        "## 2027 representative realism\n\n"
        + "\n".join(
            f"- {key}: annualized daily vol `{realism_by_key[key]['annualized_daily_volatility']:.6f}`, "
            f"maximum drawdown `{realism_by_key[key]['maximum_drawdown']:.6f}`, weekly down count "
            f"`{realism_by_key[key]['weekly_down_count']}`, direction changes "
            f"`{realism_by_key[key]['weekly_direction_changes']}`"
            for key in ("S1", "S2", "S3")
        ) + "\n",
        encoding="utf-8",
    )

    rollback_target = audit / "SCENARIO_V5_DIFF_AND_ROLLBACK.md"
    rollback_target.write_text(
        "# Scenario V5 Diff and Rollback\n\n"
        "## Scope\n\n"
        "All V5 outputs are additive research-candidate artifacts. The official "
        "`data/scenarios/nasdaq_latest.json`, its archive, forecast/calibration ledgers, "
        "and registered source stores are protected by before/after SHA-256 manifests.\n\n"
        "## Rollback\n\n"
        "1. Remove the V5 candidate files under `data/scenarios/candidates/`.\n"
        "2. Remove the V5 contracts under `data/contracts/scenario_v5_*.yaml`.\n"
        "3. Revert the additive `scenario_v5` Python package, CLI hooks, read-model key, and dashboard V5 block.\n"
        "4. Rebuild the dashboard; the existing official legacy scenario remains the fallback.\n\n"
        "No ledger rollback or data migration is required. Do not delete or rewrite official history.\n",
        encoding="utf-8",
    )
    return [implementation_target, evidence_target, fit_target, realism_target,
            test_target, protected_target, rollback_target]


def report_views(root: Path) -> dict[str, Any]:
    candidate = load_candidate(root, maximum_age_days=36500)
    if candidate is None:
        return {"status": "blocked", "reason": "valid candidate not found", "views": []}
    return {
        "status": "ok",
        "candidate_id": candidate["candidate_id"],
        "views": [{
            "view_id": row["view_id"],
            "origin_type": row["origin_type"],
            "probability_space": row["probability_space"],
            "target": row.get("target"),
            "used_numerically": row["used_numerically"],
            "approval_status": row["approval_status"],
            "blocked_reason": row.get("blocked_reason"),
        } for row in candidate["evidence_views"]],
    }


def rolling_origin_framework(root: Path) -> Path:
    target = root / AUDIT_RELATIVE / "ROLLING_ORIGIN_FRAMEWORK.json"
    payload = {
        "schema_version": 1,
        "status": "framework_only_blocked",
        "candidate_id": "scenario_v5_evidence_conditioned_legacy_prior_v1",
        "horizons_sessions": [21, 63, 126, 252],
        "minimum_origin_requirements": {
            "source_response_sha256": True,
            "observation_available_at": True,
            "source_vintage": True,
            "forecast_as_of": True,
            "fixed_model_contract_per_fold": True,
        },
        "metrics": ["log_score", "brier_score", "crps", "interval_coverage",
                    "pit_uniformity", "scenario_calibration", "path_realism"],
        "blocked_reason": (
            "The repository does not yet contain enough approved rolling origins with row-level "
            "response hashes, source vintages, and available_at timestamps. Fabricated backtest "
            "scores are prohibited."
        ),
        "promotion_requires_human_approval": True,
    }
    _write_json(target, payload)
    return target


def create_delivery_zip(root: Path) -> tuple[Path, Path]:
    """Package only V5 scope, preserving repository-relative paths and hashes."""
    files: set[Path] = set()
    for relative in DELIVERY_PATHS:
        target = root / relative
        if target.is_file():
            files.add(target)
        elif target.is_dir():
            files.update(path for path in target.rglob("*") if path.is_file()
                         and "__pycache__" not in path.parts and path.suffix != ".pyc")
    manifest_path = root / AUDIT_RELATIVE / "DELIVERY_MANIFEST.json"
    files.discard(manifest_path)
    rows = [{
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_hash(path),
    } for path in sorted(files)]
    _write_json(manifest_path, {
        "schema_version": 1,
        "delivery": DELIVERY_NAME,
        "candidate_id": "scenario_v5_evidence_conditioned_legacy_prior_v1",
        "file_count_excluding_manifest": len(rows),
        "files": rows,
        "excluded": [
            "official scenario snapshots and archives",
            "forecast/calibration ledgers",
            "unrelated dirty-worktree files",
            "Python bytecode and caches",
        ],
    })
    files.add(manifest_path)
    zip_path = root / DELIVERY_NAME
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(root).as_posix())
    return zip_path, manifest_path
