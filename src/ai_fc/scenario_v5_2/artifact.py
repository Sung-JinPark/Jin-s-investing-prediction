"""Build and strict verification boundary for Scenario V5.2."""

from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai_fc.scenario_v5.contracts import (
    canonical_hash,
    compare_protected_hashes,
    file_hash,
    protected_hashes,
)

from .engine import (
    CANDIDATE_ID,
    CANDIDATE_RELATIVE,
    SHADOW_V52_RELATIVE,
    LEGACY_V52_RELATIVE,
    KNOWLEDGE_CUTOFF,
    QUANTILE_NAMES,
    SOURCE_PATHS,
    ScenarioV52Error,
    assemble_candidate,
    source_file_hash,
)


def _git_context(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
    status = run("status", "--porcelain")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status),
        "status_entry_count": len(status.splitlines()) if status else 0,
        "python": platform.python_version(),
    }


def _model_content(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    for key in (
        "model_content_sha256", "generated_at", "build_receipt",
        "build_receipt_sha256", "validation",
    ):
        result.pop(key, None)
    return result


def _receipt_content(receipt: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(receipt)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_candidate(root: Path, *, force: bool = False) -> tuple[Path, dict[str, Any], bool]:
    before = protected_hashes(root)
    payload = assemble_candidate(root)
    payload["model_content_sha256"] = canonical_hash(_model_content(payload))
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["build_receipt"] = {
        "artifact_type": "scenario_v5_2_research_candidate",
        "candidate_id": CANDIDATE_ID,
        "model_content_sha256": payload["model_content_sha256"],
        "generated_at": payload["generated_at"],
        "source_hashes": payload["source_hashes"],
        "protected_before": before,
        "build_context": _git_context(root),
    }
    payload["build_receipt_sha256"] = canonical_hash(
        _receipt_content(payload["build_receipt"])
    )
    path = root / CANDIDATE_RELATIVE
    existing: dict[str, Any] | None = None
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
    changed = force or existing is None or (
        existing.get("model_content_sha256") != payload["model_content_sha256"]
    )
    if changed:
        _write_json_atomic(path, payload)
    elif existing is not None:
        payload = existing
    after = protected_hashes(root)
    comparison = compare_protected_hashes(before, after)
    if not comparison["ok"]:
        raise ScenarioV52Error(f"protected paths changed during build: {comparison}")
    result = validate_candidate(payload, root, replay=False)
    if not result["ok"]:
        raise ScenarioV52Error("candidate failed validation: " + "; ".join(result["errors"]))
    return path, payload, changed


def _check_probability(value: Any, label: str, errors: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{label}: probability must be non-boolean number")
        return
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        errors.append(f"{label}: probability outside [0,1]")


def validate_candidate(
    payload: dict[str, Any], root: Path | None = None, *, replay: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("candidate_id") != CANDIDATE_ID:
        errors.append("candidate id mismatch")
    if payload.get("artifact_type") != "scenario_v5_2_research_candidate":
        errors.append("artifact type mismatch")
    if payload.get("promotion_state") != "NOT_OFFICIAL_NOT_CHAMPION":
        errors.append("promotion state is not research-only")
    try:
        cutoff = datetime.fromisoformat(str(payload.get("knowledge_cutoff")))
        base_cutoff = datetime.fromisoformat(KNOWLEDGE_CUTOFF)
        if cutoff.tzinfo is None or cutoff < base_cutoff:
            errors.append("knowledge cutoff precedes registered V5.2 base cutoff")
        if payload.get("as_of") != payload.get("knowledge_cutoff"):
            errors.append("as_of and knowledge cutoff mismatch")
    except (TypeError, ValueError):
        cutoff = datetime.max.replace(tzinfo=timezone.utc)
        errors.append("invalid knowledge cutoff")
    expected_hash = canonical_hash(_model_content(payload))
    if payload.get("model_content_sha256") != expected_hash:
        errors.append("model content hash mismatch")
    receipt = payload.get("build_receipt", {})
    if receipt:
        if payload.get("build_receipt_sha256") != canonical_hash(_receipt_content(receipt)):
            errors.append("build receipt hash mismatch")
        if receipt.get("model_content_sha256") != payload.get("model_content_sha256"):
            errors.append("receipt model hash mismatch")

    for row in payload.get("evidence_registry", []):
        if row.get("used_numerically"):
            try:
                available = datetime.fromisoformat(str(row["available_at"]))
                if available.tzinfo is None or available > cutoff:
                    errors.append(f"future/naive evidence: {row.get('evidence_id')}")
            except (KeyError, TypeError, ValueError):
                errors.append(f"invalid evidence time: {row.get('evidence_id')}")
        strength = row.get("effective_strength")
        if isinstance(strength, bool) or not isinstance(strength, (int, float)):
            errors.append(f"invalid evidence strength: {row.get('evidence_id')}")
        else:
            approved_cap = row.get("approved_cap", .35)
            if isinstance(approved_cap, bool) or not isinstance(approved_cap, (int, float)) \
                    or not 0 <= float(approved_cap) <= 1:
                errors.append(f"invalid approved evidence cap: {row.get('evidence_id')}")
            elif "approved_cap" in row and (
                row.get("dependency_cluster_id") != "dotcom_single_cycle_analog"
                or not math.isclose(float(approved_cap), .60)
            ):
                errors.append(f"unauthorized evidence-cap override: {row.get('evidence_id')}")
            elif float(strength) < 0 or float(strength) > float(approved_cap):
                errors.append(f"dependency cap exceeded: {row.get('evidence_id')}")

    if root is not None:
        for relative in SOURCE_PATHS:
            path = root / relative
            if not path.is_file():
                errors.append(f"source missing: {relative}")
            elif payload.get("source_hashes", {}).get(relative) \
                    != source_file_hash(root, relative):
                errors.append(f"source hash mismatch: {relative}")
        for baseline in (SHADOW_V52_RELATIVE, LEGACY_V52_RELATIVE):
            baseline_path = root / baseline
            if not baseline_path.is_file():
                errors.append(f"shadow baseline missing: {baseline}")
            elif payload.get("source_hashes", {}).get(baseline.as_posix()) \
                    != file_hash(baseline_path):
                errors.append(f"shadow baseline source hash mismatch: {baseline}")
        if receipt.get("protected_before"):
            comparison = compare_protected_hashes(
                receipt["protected_before"], protected_hashes(root)
            )
            if not comparison["ok"]:
                errors.append("protected hash mismatch since candidate build")

    ablations = payload.get("ablations", {})
    if set(ablations) != {"prior_only", "labor_only", "labor_rate", "full_evidence"}:
        errors.append("four required ablations are missing")
    for name, row in ablations.items():
        probabilities = row.get("probabilities", {})
        for key, value in probabilities.items():
            if key == "scenario_probabilities":
                for scenario, probability in value.items():
                    _check_probability(probability, f"{name}.{scenario}", errors)
                if not math.isclose(sum(value.values()), 1.0, abs_tol=1e-10):
                    errors.append(f"{name}: scenario probabilities do not sum to one")
            elif key == "year_end_p50":
                if isinstance(value, bool) or not isinstance(value, (int, float)) \
                        or not math.isfinite(float(value)) or float(value) <= 0:
                    errors.append(f"{name}.{key}: invalid index level")
            else:
                _check_probability(value, f"{name}.{key}", errors)
        diagnostics = row.get("weight_diagnostics", {})
        if not math.isclose(float(diagnostics.get("weight_sum", -1)), 1.0, abs_tol=1e-12):
            errors.append(f"{name}: weight sum invalid")
        if not diagnostics.get("gates_pass"):
            errors.append(f"{name}: weight concentration gate failed")

    distribution = payload.get("distribution", {})
    dates = distribution.get("dates", [])
    bands = distribution.get("bands", {})
    if not dates or dates != sorted(set(dates)):
        errors.append("distribution dates must be unique and sorted")
    if distribution.get("probability_space") != "total_path_mixture":
        errors.append("main chart is not total mixture")
    for name in QUANTILE_NAMES:
        values = bands.get(name, [])
        if len(values) != len(dates):
            errors.append(f"{name} length mismatch")
        elif any(isinstance(v, bool) or not isinstance(v, (int, float))
                 or not math.isfinite(float(v)) for v in values):
            errors.append(f"{name} contains invalid value")
    if bands and all(len(bands.get(name, [])) == len(dates) for name in QUANTILE_NAMES):
        for index in range(len(dates)):
            values = [bands[name][index] for name in QUANTILE_NAMES]
            if values != sorted(values):
                errors.append(f"quantiles not monotone at {dates[index]}")
                break

    display = payload.get("display_contract", {})
    if display.get("main_chart") != "total_mixture_p50_and_bands":
        errors.append("main chart contract mismatch")
    if display.get("main_chart_scenario_lines") is not False:
        errors.append("scenario lines leaked into main chart")
    if display.get("scenario_surface") != "S1_S2_S3_conditional_small_multiples":
        errors.append("scenario small-multiple contract mismatch")
    if display.get("fake_wiggle") is not False:
        errors.append("fake p50 wiggle is forbidden")
    if display.get("october_2_exact_date_forecast") is not False:
        errors.append("October 2 exact-date forecast is forbidden")
    bundle = distribution.get("central_path_bundle", {})
    if bundle.get("member_count") not in range(5, 10) or len(bundle.get("members", [])) not in range(5, 10):
        errors.append("central actual member bundle must contain 5-9 paths")
    if bundle.get("fake_wiggle_applied") is not False:
        errors.append("central bundle reports fake wiggle")
    if not bundle.get("realism_gate_pass"):
        errors.append("central bundle realism gate failed")

    first_touch = payload.get("first_touch_distribution", {})
    if first_touch.get("exact_date_forecast") is not False:
        errors.append("first touch is incorrectly exact-date")
    if "2026-10-02" not in first_touch.get("dates", []):
        errors.append("October 2 audit coordinate missing")
    cdf = first_touch.get("cdf", [])
    density = first_touch.get("density", [])
    if len(cdf) != len(density) or any(b + 1e-12 < a for a, b in zip(cdf, cdf[1:])):
        errors.append("first-touch CDF invalid")
    if cdf:
        total = float(cdf[-1]) + float(first_touch.get("never_touched_by_october_end", -1))
        if not math.isclose(total, 1.0, abs_tol=2e-8):
            errors.append("first-touch probability mass invalid")

    scenarios = payload.get("conditional_small_multiples", {}).get("scenarios", {})
    if set(scenarios) != {"S1", "S2", "S3"}:
        errors.append("conditional scenarios missing")
    else:
        probabilities = []
        for name, row in scenarios.items():
            _check_probability(row.get("probability"), f"scenario.{name}", errors)
            probabilities.append(row.get("probability", 0))
            if row.get("probability_space") != "conditional_cohort_from_total_mixture":
                errors.append(f"scenario {name} probability space mismatch")
            for quantile in QUANTILE_NAMES:
                if len(row.get("bands", {}).get(quantile, [])) != len(dates):
                    errors.append(f"scenario {name} {quantile} length mismatch")
            scenario_bundle = row.get("central_path_bundle", {})
            if scenario_bundle.get("member_count") not in range(5, 10):
                errors.append(f"scenario {name} central bundle missing")
            if not scenario_bundle.get("realism_gate_pass"):
                errors.append(f"scenario {name} central bundle realism gate failed")
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-10):
            errors.append("full scenario probabilities do not sum to one")

    if not payload.get("distinctness_2027", {}).get("gate_pass"):
        errors.append("2027 distinctness gate failed")
    circularity = payload.get("circularity_control", {})
    if not circularity.get("gate_pass"):
        errors.append("circularity gate failed")
    if circularity.get("realized_event_return_coefficient") != 0.0:
        errors.append("event-day return was double counted")
    if payload.get("anchor", {}).get("future_event_jump") != 0.0:
        errors.append("future event jump must be zero")
    if not payload.get("dependency_control", {}).get("gate_pass"):
        errors.append("dependency control gate failed")
    if payload.get("model", {}).get("hard_event_mapping", {}).get("status") \
            != "REFERENCE_ONLY_INSUFFICIENT_N":
        errors.append("insufficient event map was not fail-closed")
    generator = payload.get("model", {}).get("generator_audit", {})
    expected_mixture = {
        "S1_dotcom_expansion_cluster": 1.0 / 3.0,
        "S2_modern_baseline_cluster": 1.0 / 3.0,
        "S3_macro_tightening_stress_cluster": 1.0 / 3.0,
    }
    if generator.get("engine_mixture_probability") != expected_mixture:
        errors.append("three-scenario equal simulation-pool contract mismatch")
    counts = generator.get("path_count_by_engine", {})
    if set(counts) != set(expected_mixture) \
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                   for value in counts.values()) \
            or (all(isinstance(value, int) and not isinstance(value, bool)
                    for value in counts.values())
                and sum(counts.values()) != payload.get("model", {}).get("path_count")) \
            or counts != payload.get("model", {}).get("path_count_by_engine"):
        errors.append("three-scenario database path counts are invalid")
    cluster_scenarios = generator.get("scenarios", {})
    expected_groups = {
        "S1": "dotcom_price_state_db",
        "S2": "modern_general_market_state_db",
        "S3": "macro_tightening_financial_conditions_db",
    }
    if generator.get("method") != "deterministic_k_medoids_then_cluster_level_outcome_labeling" \
            or generator.get("cluster_assignment_information_set") != "origin_state_features_only" \
            or generator.get("individual_origin_outcome_selection") is not False \
            or generator.get("gate_pass") is not True \
            or set(cluster_scenarios) != set(expected_groups):
        errors.append("scenario cluster construction contract failed")
    else:
        for scenario, expected_group in expected_groups.items():
            row = cluster_scenarios[scenario]
            if row.get("source_group") != expected_group \
                    or row.get("clustering_uses_forward_outcomes") is not False \
                    or row.get("outcomes_used_after_assignment_for_cluster_label_only") is not True \
                    or len(str(row.get("cluster_assignments_sha256", ""))) != 64 \
                    or row.get("sampling", {}).get("forced_endpoint") is not False \
                    or row.get("sampling", {}).get("forced_turning_date") is not False:
                errors.append(f"scenario {scenario} cluster audit failed")
        selected_returns = [
            cluster_scenarios[name]["selected_cluster"]["outcome_medians"]["forward_return_252d"]
            for name in ("S1", "S2", "S3")
        ]
        if not (selected_returns[0] > selected_returns[1] > selected_returns[2] \
                and selected_returns[0] - selected_returns[2] > .50):
            errors.append("scenario cluster outcomes are not dramatically ordered")
    sensitivity = payload.get("sensitivity_analysis", {})
    sensitivity_rows = sensitivity.get("rows", [])
    if [row.get("S1_strength") for row in sensitivity_rows] != [.28, .45, .60] \
            or not sensitivity.get("gate_pass"):
        errors.append("S1 0.28/0.45/0.60 sensitivity gate failed")

    for key, row in payload.get("evidence_attribution", {}).items():
        residual = row.get("additivity_residual")
        if not isinstance(residual, (int, float)) or abs(float(residual)) > 1e-12:
            errors.append(f"attribution does not add up: {key}")

    dotcom = payload.get("dotcom_scenario_weighting", {})
    strengths = dotcom.get("scenario_strength", {})
    if strengths != {"S1": .60, "S2": 0.0, "S3": 0.0}:
        errors.append("dotcom S1/S2/S3 weighting gate failed")
    if strengths and max(strengths.values()) > float(dotcom.get("dependency_cap", 0)):
        errors.append("dotcom dependency cap exceeded")
    if strengths != {"S1": .60, "S2": 0.0, "S3": 0.0} \
            or not math.isclose(float(dotcom.get("dependency_cap", 0)), .60):
        errors.append("dotcom 0.60/0.00/0.00 override contract mismatch")
    shares = dotcom.get("path_engine_share_by_scenario", {})
    try:
        own_engines = {
            "S1": "S1_dotcom_expansion_cluster",
            "S2": "S2_modern_baseline_cluster",
            "S3": "S3_macro_tightening_stress_cluster",
        }
        if not all(
            math.isclose(shares[scenario][engine], 1.0, abs_tol=1e-10)
            and math.isclose(sum(shares[scenario].values()), 1.0, abs_tol=1e-10)
            for scenario, engine in own_engines.items()
        ):
            errors.append("scenario paths are not isolated to their database generators")
    except (KeyError, TypeError, ValueError):
        errors.append("dotcom scenario generator-share audit is invalid")
    if not dotcom.get("one_month_negative_target_preserved"):
        errors.append("dotcom one-month correction evidence was cherry-picked")
    if dotcom.get("forced_endpoint") is not False \
            or dotcom.get("forced_october_direction") is not False:
        errors.append("dotcom view forced path geometry")
    if float(dotcom.get("S1_no_repeat_probability_after_dotcom", 0)) \
            <= float(dotcom.get("S1_no_repeat_probability_before_dotcom", 0)):
        errors.append("dotcom S1 no-repeat likelihood did not increase")
    event_learning = payload.get("event_learning", {})
    if event_learning.get("mode") != "append_only_event_then_deterministic_candidate_rebuild":
        errors.append("event learning mode is not append-only deterministic rebuild")
    if event_learning.get("background_scraping_or_unbounded_self_training") is not False:
        errors.append("unbounded event self-training is forbidden")

    if replay and root is not None and not errors:
        replayed = assemble_candidate(root)
        replay_hash = canonical_hash(_model_content(replayed))
        if replay_hash != payload.get("model_content_sha256"):
            errors.append("deterministic replay hash mismatch")
    return {
        "ok": not errors,
        "errors": errors,
        "candidate_id": payload.get("candidate_id"),
        "model_content_sha256": payload.get("model_content_sha256"),
        "replay_checked": replay,
    }


def verify_candidate(root: Path, path: Path | None = None, *, replay: bool = True) -> dict[str, Any]:
    target = path or (root / CANDIDATE_RELATIVE)
    if not target.is_file():
        return {"ok": False, "errors": [f"candidate missing: {target}"], "replay_checked": False}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"candidate unreadable: {exc}"], "replay_checked": False}
    result = validate_candidate(payload, root, replay=replay)
    result["path"] = target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target)
    return result


def _sample_indexes(length: int, step: int = 20) -> list[int]:
    indexes = list(range(0, length, step))
    if indexes[-1] != length - 1:
        indexes.append(length - 1)
    return indexes


def _sample_bundle(bundle: dict[str, Any], indexes: list[int]) -> dict[str, Any]:
    members = bundle["members"][:5]
    return {
        "member_count": len(members),
        "medoid_path_id": bundle["medoid_path_id"],
        "medoid_values": [bundle["medoid_values"][index] for index in indexes],
        "members": [
            {"path_id": row["path_id"], "values": [row["values"][index] for index in indexes]}
            for row in members
        ],
        "realism_gate_pass": bundle["realism_gate_pass"],
    }


def dashboard_projection(
    root: Path, now: datetime, *, maximum_age_trading_days: int = 1,
) -> dict[str, Any]:
    """Return a bounded read-only projection with an explicit stale fallback."""
    target = root / CANDIDATE_RELATIVE
    if not target.is_file():
        return {
            "schema_version": 1, "status": "unavailable", "candidate_id": CANDIDATE_ID,
            "runtime_gate": {"display_eligible": False, "reasons": ["candidate missing"]},
        }
    payload = json.loads(target.read_text(encoding="utf-8"))
    validation = validate_candidate(payload, root, replay=False)
    cutoff = datetime.fromisoformat(payload["knowledge_cutoff"])
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    cursor = cutoff.date() + timedelta(days=1)
    age = 0
    while cursor <= now_utc.date():
        if cursor.weekday() < 5:
            age += 1
        cursor += timedelta(days=1)
    reasons: list[str] = []
    if not validation["ok"]:
        reasons.extend(validation["errors"])
    if age > maximum_age_trading_days:
        reasons.append(f"candidate age {age} trading days exceeds {maximum_age_trading_days}")
    if reasons:
        return {
            "schema_version": 1, "status": "stale_or_invalid",
            "candidate_id": CANDIDATE_ID, "banner": "STALE/INVALID V5.2 RESEARCH CANDIDATE",
            "runtime_gate": {"display_eligible": False, "age_trading_days": age, "reasons": reasons},
        }
    dates = payload["distribution"]["dates"]
    indexes = _sample_indexes(len(dates))
    scenarios: dict[str, Any] = {}
    for key, row in payload["conditional_small_multiples"]["scenarios"].items():
        scenarios[key] = {
            "label": row["label"], "probability": row["probability"],
            "path_count": row["path_count"],
            "bands": {
                name: [row["bands"][name][index] for index in indexes]
                for name in ("p10", "p25", "p50", "p75", "p90")
            },
            "central_path_bundle": _sample_bundle(row["central_path_bundle"], indexes),
        }
    return {
        "schema_version": 1,
        "status": "degraded" if "LIMITED" in payload["status"] else "ok",
        "candidate_id": CANDIDATE_ID,
        "banner": "RESEARCH CANDIDATE · NOT OFFICIAL · LIMITED EVENT MAP",
        "as_of": payload["as_of"],
        "runtime_gate": {"display_eligible": True, "age_trading_days": age, "reasons": []},
        "anchor": payload["anchor"],
        "model": {
            "path_count": payload["model"]["path_count"],
            "seed": payload["model"]["seed"],
            "hard_event_mapping": payload["model"]["hard_event_mapping"],
        },
        "evidence_scores": payload["evidence_scores"],
        "evidence_attribution": payload["evidence_attribution"],
        "dotcom_scenario_weighting": {
            # The complete cluster inventory and path-generator audit remain in
            # the candidate/audit pack.  The dashboard receives only fields it
            # renders, preserving the existing standalone size budget.
            "scenario_strength": payload["dotcom_scenario_weighting"]["scenario_strength"],
            "forward_return_targets": payload["dotcom_scenario_weighting"]["forward_return_targets"],
            "S1_probability_increment": payload["dotcom_scenario_weighting"]["S1_probability_increment"],
            "forced_endpoint": payload["dotcom_scenario_weighting"]["forced_endpoint"],
            "forced_october_direction": payload["dotcom_scenario_weighting"]["forced_october_direction"],
        },
        "event_learning": payload["event_learning"],
        "shadow_comparison": payload["shadow_comparison"],
        "ablations": {
            name: {"probabilities": row["probabilities"]}
            for name, row in payload["ablations"].items()
        },
        "first_touch_distribution": payload["first_touch_distribution"],
        "distinctness_2027": {
            "gate_pass": payload["distinctness_2027"]["gate_pass"],
            "partition_information_cutoff": payload["distinctness_2027"]["partition_information_cutoff"],
        },
        "distribution": {
            "dates": [dates[index] for index in indexes],
            "bands": {
                name: [payload["distribution"]["bands"][name][index] for index in indexes]
                for name in ("p10", "p25", "p50", "p75", "p90")
            },
            "historical_actual": {
                "dates": payload["distribution"]["historical_actual"]["dates"][-40:],
                "values": payload["distribution"]["historical_actual"]["values"][-40:],
                "role": "historical_actual_through_anchor",
            },
            "forecast_boundary": payload["distribution"]["forecast_boundary"],
            "central_path_bundle": _sample_bundle(
                payload["distribution"]["central_path_bundle"], indexes
            ),
        },
        "conditional_small_multiples": {
            "dates": [dates[index] for index in indexes], "scenarios": scenarios,
        },
        "display_contract": payload["display_contract"],
        "model_content_sha256": payload["model_content_sha256"],
    }
