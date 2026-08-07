"""Scenario V5 artifact assembly, validation, persistence, and no-op semantics."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .contracts import canonical_hash, file_hash, load_contracts
from .engine import (
    build_conditional_outputs,
    condition_matrix,
    entropy_pool,
    reproduce_legacy_prior,
)
from .evidence import build_evidence_registry, event_states


CANDIDATE_ID = "scenario_v5_evidence_conditioned_legacy_prior_v1"
CANDIDATE_RELATIVE = (
    "data/scenarios/candidates/"
    "scenario_v5_evidence_conditioned_legacy_prior_v1_latest.json"
)


class ScenarioV5Error(RuntimeError):
    pass


def _git_state(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, text=True,
            capture_output=True, encoding="utf-8", errors="replace",
        ).stdout.strip()
    status = run("status", "--porcelain")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status),
        "review_only": bool(status),
        "status_entries": len(status.splitlines()) if status else 0,
    }


def _comparable(payload: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(payload)
    for field in ("generated_at", "canonical_sha256", "receipt"):
        value.pop(field, None)
    # The number of untracked/modified entries grows as this additive build
    # writes its own candidate and reports. It is audit context, not a model
    # input, so excluding it is required for genuine same-input no-op behavior.
    if isinstance(value.get("build_context"), dict):
        value["build_context"].pop("status_entries", None)
    return value


def validate_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("candidate_id") != CANDIDATE_ID:
        errors.append("candidate_id mismatch")
    identity = payload.get("identity") or {}
    if identity.get("prior_engine") != "legacy_gbm_reproduced_v1" or identity.get("is_rcfhs") is not False:
        errors.append("honest legacy-prior identity required")
    if payload.get("status") not in {"ok", "degraded"}:
        errors.append("candidate status invalid")
    scenarios = payload.get("conditional_distribution", {}).get("scenarios", {})
    probabilities = [scenarios.get(key, {}).get("probability") for key in ("S1", "S2", "S3")]
    if not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in probabilities):
        errors.append("scenario probabilities must be fractions in [0,1]")
    elif not np.isclose(sum(probabilities), 1.0, atol=1e-10):
        errors.append("scenario probabilities do not sum to one")
    dates = payload.get("conditional_distribution", {}).get("dates", [])
    if len(dates) != 253 or len(set(dates)) != len(dates) or dates != sorted(dates):
        errors.append("candidate must contain 253 strictly increasing anchor+session dates")
    for key in ("S1", "S2", "S3"):
        row = scenarios.get(key, {})
        values = row.get("representative_path_values", [])
        if len(values) != len(dates):
            errors.append(f"{key} representative length mismatch")
        if row.get("representative_selection", {}).get("member_path") is not True:
            errors.append(f"{key} representative is not an actual member")
    for view in payload.get("evidence_views", []):
        target = view.get("target")
        if view.get("unit") == "fraction" and target is not None and not 0 <= target <= 1:
            errors.append(f"invalid probability unit in {view.get('view_id')}")
        if view.get("probability_space") in {"risk_neutral_terminal", "reference_only"} and view.get("used_numerically"):
            errors.append(f"reference/risk-neutral view used numerically: {view.get('view_id')}")
    if any(float(item.get("price_jump", 0)) != 0.0 for item in payload.get("event_states", [])):
        errors.append("unmapped event price jump must be zero")
    posterior = payload.get("posterior_diagnostics", {})
    if not posterior.get("converged") or not posterior.get("gates_pass"):
        errors.append("entropy-pooling solver/gates failed")
    same_shape = payload.get("conditional_distribution", {}).get("same_shape_diagnostics", {})
    visible = payload.get("conditional_distribution", {}).get("representative_lines_visible")
    if visible is not bool(same_shape.get("gate_pass")):
        errors.append("same-shape visibility gate mismatch")
    expected_hash = canonical_hash(_comparable(payload))
    if payload.get("canonical_sha256") and payload["canonical_sha256"] != expected_hash:
        errors.append("canonical_sha256 mismatch")
    return {"ok": not errors, "errors": errors, "canonical_sha256": expected_hash}


def assemble_candidate(root: Path) -> dict[str, Any]:
    snapshot_path = root / "data/scenarios/nasdaq_latest.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    contracts = load_contracts(root)
    model_contract = contracts["scenario_v5_model"]
    identity = deepcopy(model_contract["identity"])
    paths, dates = reproduce_legacy_prior(snapshot)
    evidence = build_evidence_registry(root, snapshot, contracts)
    matrix, numerical_views = condition_matrix(paths, dates, snapshot, evidence)
    weights, posterior = entropy_pool(
        matrix, numerical_views, model_contract["entropy_pooling"])
    conditional = build_conditional_outputs(
        paths, dates, weights, snapshot, model_contract)
    git = _git_state(root)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "ok",
        "candidate_id": CANDIDATE_ID,
        "display_name": "Evidence-Conditioned Market Outlook - Research Candidate",
        "banner": "RESEARCH CANDIDATE - NOT OFFICIAL - NOT CHAMPION",
        "asof": snapshot["asof"],
        "knowledge_cutoff": snapshot["generated_at"],
        "generated_at": generated,
        "identity": identity,
        "source_snapshot": {
            "path": snapshot_path.relative_to(root).as_posix(),
            "sha256": file_hash(snapshot_path),
            "snapshot_id": snapshot.get("snapshot_id"),
            "revision": snapshot.get("revision"),
            "anchor": snapshot["anchor"],
            "ath": snapshot["ath"],
            "corr10": snapshot["corr10"],
            "reference_price": snapshot["reference_price"],
            "classification_date": snapshot["model"]["classification_date"],
        },
        "pit_integrity": {
            "market_data_asof": snapshot["asof"],
            "knowledge_cutoff": snapshot["generated_at"],
            "strict_available_at": True,
            "future_data_used": False,
            "vintage_limitation": (
                "Long-history rows lack a fully approved response_sha/vintage/available_at contract; "
                "therefore the prior is the reproduced legacy GBM, not RCFHS."
            ),
        },
        "prior": {
            "engine": identity["prior_engine"],
            "path_count": int(paths.shape[0]),
            "horizon_sessions": int(paths.shape[1]),
            "seed": snapshot["model"]["seed"],
            "continuous_across_calendar_years": True,
            "event_jump_policy": "J_t = 0 until an approved mapping exists",
            "parameters": snapshot["model"]["gbm_parameters"],
        },
        "evidence_views": evidence,
        "event_states": event_states(
            snapshot, evidence, contracts["scenario_v5_event_impact"]),
        "posterior_diagnostics": posterior,
        "conditional_distribution": conditional,
        "promotion": {
            "state": identity["promotion_state"],
            "rolling_origin_status": model_contract["rolling_origin"]["status"],
            "human_approval_required": True,
            "official_snapshot_mutated": False,
        },
        "build_context": git,
        "receipt": {
            "artifact_type": "scenario_v5_research_candidate",
            "same_input_noop_supported": True,
            "git_head": git["head"],
        },
    }
    payload["canonical_sha256"] = canonical_hash(_comparable(payload))
    validation = validate_candidate(payload)
    if not validation["ok"]:
        raise ScenarioV5Error("; ".join(validation["errors"]))
    payload["validation"] = {"ok": True, "errors": []}
    # Validation is intentionally excluded from the earlier hash only if absent;
    # recompute now so the persisted contract is self-consistent.
    payload["canonical_sha256"] = canonical_hash(_comparable(payload))
    return payload


def build_candidate(root: Path, *, force: bool = False) -> tuple[Path, dict[str, Any], bool]:
    target = root / CANDIDATE_RELATIVE
    payload = assemble_candidate(root)
    if target.is_file() and not force:
        current = json.loads(target.read_text(encoding="utf-8"))
        if (validate_candidate(current)["ok"]
                and canonical_hash(_comparable(current)) == canonical_hash(_comparable(payload))):
            return target, current, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = root / "data/scenarios/candidates/archive"
    receipts = root / "data/scenarios/candidates/receipts"
    archive.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    short_hash = payload["canonical_sha256"][:12]
    archive_path = archive / f"{CANDIDATE_ID}_{snapshot_stamp(payload)}_{short_hash}.json"
    if not archive_path.exists():
        archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt_path = receipts / f"{CANDIDATE_ID}_{short_hash}.json"
    if not receipt_path.exists():
        receipt_path.write_text(json.dumps({
            "candidate_id": CANDIDATE_ID,
            "canonical_sha256": payload["canonical_sha256"],
            "source_snapshot_sha256": payload["source_snapshot"]["sha256"],
            "artifact": target.relative_to(root).as_posix(),
            "archive": archive_path.relative_to(root).as_posix(),
            "review_only": payload["build_context"]["review_only"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload, True


def snapshot_stamp(payload: dict[str, Any]) -> str:
    return str(payload["asof"]).replace("-", "")


def load_candidate(root: Path, *, maximum_age_days: int = 7) -> dict[str, Any] | None:
    path = root / CANDIDATE_RELATIVE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validation = validate_candidate(payload)
        if not validation["ok"]:
            return None
        generated = datetime.fromisoformat(payload["generated_at"])
        if generated.tzinfo is None:
            return None
        age = datetime.now(timezone.utc) - generated.astimezone(timezone.utc)
        if age.total_seconds() > maximum_age_days * 86400:
            return None
        return payload
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def verify_candidate(root: Path, path: Path | None = None) -> dict[str, Any]:
    candidate_path = path or root / CANDIDATE_RELATIVE
    if not candidate_path.is_file():
        return {"ok": False, "errors": [f"candidate not found: {candidate_path}"]}
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    result = validate_candidate(payload)
    result["path"] = candidate_path.as_posix()
    result["source_snapshot_current_sha256"] = file_hash(root / "data/scenarios/nasdaq_latest.json")
    result["source_snapshot_unchanged"] = (
        result["source_snapshot_current_sha256"] == payload["source_snapshot"]["sha256"])
    result["ok"] = bool(result["ok"] and result["source_snapshot_unchanged"])
    if not result["source_snapshot_unchanged"]:
        result["errors"].append("source snapshot hash changed")
    return result
