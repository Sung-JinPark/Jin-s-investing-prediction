"""Algorithmic—not merely coordinate—runtime contract audit."""

from __future__ import annotations

from typing import Any, Mapping


REQUIRED_FOLD_ROLES = {"research_train", "candidate_selection", "stacking", "calibration", "outer_test"}


def audit_runtime_contract(contract: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    experts = runtime.get("experts", {})
    contract_experts = contract["candidates"]
    for candidate_id, specification in contract_experts.items():
        actual = experts.get(candidate_id)
        if actual is None:
            findings.append({"code": "missing_expert", "candidate": candidate_id})
            continue
        if actual.get("algorithm") != specification.get("algorithm"):
            findings.append({"code": "algorithm_mismatch", "candidate": candidate_id})
        if candidate_id == "E2" and actual.get("objective") != specification.get("objective"):
            findings.append({"code": "e2_objective_mismatch", "candidate": candidate_id})
        if candidate_id == "E7" and actual.get("full_trajectory_required") is not True:
            findings.append({"code": "e7_missing_full_trajectory", "candidate": candidate_id})
    roles = set(runtime.get("fold_roles", []))
    if roles != REQUIRED_FOLD_ROLES:
        findings.append({"code": "fold_role_mismatch", "candidate": "ALL"})
    if runtime.get("stacking", {}).get("weights") == "fixed":
        findings.append({"code": "fixed_stacking_prohibited", "candidate": "ENSEMBLE"})
    path = runtime.get("path_forecast", {})
    if not path.get("implemented") or int(path.get("sample_count", 0)) < int(contract["target"]["path_samples"]):
        findings.append({"code": "path_implementation_missing", "candidate": "PATH"})
    if path.get("endpoint_forced_to_actual") is True:
        findings.append({"code": "future_actual_endpoint_forcing", "candidate": "PATH"})
    return {"mismatch_count": len(findings), "findings": findings, "pass": not findings}
