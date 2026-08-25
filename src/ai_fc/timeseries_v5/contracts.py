"""Frozen V5 contract validation and protected-scope guards."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .identifiers import content_hash


MODEL_ID = "shadow.nasdaq_pit_hybrid_distribution_v5"
MODEL_VERSION = 5
PROBABILITY_SPACE = "research_timeseries_v5_conditional"
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v5.yaml")


class V5ContractError(RuntimeError):
    """The frozen research contract or protected boundary is invalid."""


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V5ContractError("V5 contract must be a mapping")
    checks = {"schema_version": MODEL_VERSION, "model_id": MODEL_ID, "probability_space": PROBABILITY_SPACE, "probability_unit": "fraction"}
    for key, expected in checks.items():
        if value.get(key) != expected:
            raise V5ContractError(f"V5 contract {key} drifted")
    if value.get("target", {}).get("horizons_sessions") != [1, 5, 21, 63]:
        raise V5ContractError("V5 horizon contract drifted")
    gate = value.get("research_gate") or {}
    if float(gate.get("long_horizon_mean_crps_improvement_min", -1)) != 0.02:
        raise V5ContractError("V5 CRPS gate was lowered")
    if float(gate.get("stress_regime_coverage_min", -1)) != 0.70:
        raise V5ContractError("V5 stress coverage gate was lowered")
    if value.get("candidate_bundle", {}).get("maximum_experiments") != 12:
        raise V5ContractError("V5 experiment budget drifted")
    return value


def contract_hash(root: Path) -> str:
    return content_hash(load_contract(root))


def model_code_hash(root: Path) -> str:
    digest = hashlib.sha256()
    folder = root / "src/ai_fc/timeseries_v5"
    for path in sorted(folder.rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big")); digest.update(relative)
        digest.update(len(body).to_bytes(8, "big")); digest.update(body)
    return digest.hexdigest()


def protected_manifest(root: Path) -> dict[str, str]:
    contract = load_contract(root)
    entries: dict[str, str] = {}
    for relative_root in contract["isolation"]["protected_roots"]:
        target = root / relative_root
        paths = [target] if target.is_file() else sorted(item for item in target.rglob("*") if item.is_file()) if target.is_dir() else []
        for path in paths:
            entries[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def compare_protected(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    added = sorted(set(after) - set(before)); removed = sorted(set(before) - set(after))
    changed = sorted(path for path in set(before) & set(after) if before[path] != after[path])
    return {"ok": not (added or removed or changed), "added": added, "removed": removed, "changed": changed}


def path_allowed(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) or normalized.startswith(pattern.removesuffix("/**")) for pattern in patterns)
