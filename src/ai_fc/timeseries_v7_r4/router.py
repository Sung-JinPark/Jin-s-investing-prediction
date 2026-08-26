"""Deterministic Gate-deficit router from the frozen R4 contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .integrity import canonical_json, sha256_bytes


@dataclass(frozen=True)
class RoutedTask:
    rule_id: str
    action: str
    priority: int
    deduplication_key: str


class HypothesisRegistry:
    """Append-only PostgreSQL registry for frozen research combinations."""

    def __init__(self, connection: Any):
        self.connection = connection

    def register(self, *, deficit_family: str, action: str, hypothesis_hash: str,
                 dataset_snapshot_hash: str, code_hash: str, runtime_hash: str) -> bool:
        coordinates = {
            "hypothesis_hash": hypothesis_hash,
            "dataset_snapshot_hash": dataset_snapshot_hash,
            "code_hash": code_hash,
            "runtime_hash": runtime_hash,
        }
        for name, value in coordinates.items():
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"{name} must be an explicit SHA-256")
        registry_key = sha256_bytes(canonical_json(coordinates))
        row = self.connection.execute(
            "INSERT INTO timeseries_v7_r4.hypothesis_registry"
            " (registry_key,deficit_family,action,hypothesis_hash,dataset_snapshot_hash,"
            "code_hash,runtime_hash) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING RETURNING 1",
            (registry_key, deficit_family, action, hypothesis_hash, dataset_snapshot_hash,
             code_hash, runtime_hash),
        ).fetchone()
        return row is not None


class GateDeficitRouter:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self._validate_contract()

    def _validate_contract(self) -> None:
        rules = self.payload.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ValueError("router contract requires rules")
        for rule in rules:
            if (not isinstance(rule, Mapping) or not rule.get("id")
                    or not rule.get("when") or not rule.get("enqueue")):
                raise ValueError("each router rule requires id, when, and enqueue")

    def validate_gate_coverage(self, gate_checks: Iterable[str]) -> dict[str, tuple[str, ...]]:
        """Return admissible actions for every Gate, rejecting uncovered checks."""
        mapping: dict[str, list[str]] = {str(check): [] for check in gate_checks}
        for rule in self.payload["rules"]:
            for check in rule["when"]:
                if check in mapping:
                    mapping[check].extend(str(action) for action in rule["enqueue"])
        uncovered = sorted(check for check, actions in mapping.items() if not actions)
        if uncovered:
            raise ValueError(f"Gate checks lack admissible task families: {uncovered}")
        return {check: tuple(actions) for check, actions in mapping.items()}

    @classmethod
    def from_yaml(cls, path: Path) -> "GateDeficitRouter":
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("router contract must be a mapping")
        return cls(value)

    def route(self, deficits: list[str], *, dataset_snapshot_hash: str,
              code_hash: str, runtime_hash: str, blocker_signature: str | None = None,
              blocker_history: Iterable[Mapping[str, Any]] = ()) -> list[RoutedTask]:
        active = set(deficits)
        history = list(blocker_history)
        policy = self.payload.get("same_blocker_policy", {})
        alternate_at = int(policy.get("route_to_alternate_family_at", 3))
        blocked_actions: set[str] = set()
        if blocker_signature:
            matching = [item for item in history
                        if item.get("blocker_signature") == blocker_signature]
            if len(matching) >= alternate_at:
                blocked_actions = {str(item["action"]) for item in matching if item.get("action")}
        routed: list[RoutedTask] = []
        seen: set[str] = set()
        for rule in sorted(self.payload["rules"], key=lambda item: int(item["priority"])):
            matched = sorted(active.intersection(rule["when"]))
            if not matched:
                continue
            family = rule["id"]
            for action in rule["enqueue"]:
                if action in blocked_actions:
                    continue
                key_payload = {
                    "deficit_family": family,
                    "hypothesis_hash": sha256_bytes(canonical_json({"action": action, "matched": matched})),
                    "dataset_snapshot_hash": dataset_snapshot_hash,
                    "code_hash": code_hash,
                    "runtime_hash": runtime_hash,
                }
                key = sha256_bytes(canonical_json(key_payload))
                if key in seen:
                    continue
                seen.add(key)
                routed.append(RoutedTask(family, action, int(rule["priority"]), key))
        return routed
