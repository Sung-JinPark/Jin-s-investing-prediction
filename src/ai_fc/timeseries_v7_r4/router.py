"""Deterministic Gate-deficit router from the frozen R4 contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .integrity import canonical_json, sha256_bytes


@dataclass(frozen=True)
class RoutedTask:
    rule_id: str
    action: str
    priority: int
    deduplication_key: str


class GateDeficitRouter:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    @classmethod
    def from_yaml(cls, path: Path) -> "GateDeficitRouter":
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("router contract must be a mapping")
        return cls(value)

    def route(self, deficits: list[str], *, dataset_snapshot_hash: str,
              code_hash: str, runtime_hash: str) -> list[RoutedTask]:
        active = set(deficits)
        routed: list[RoutedTask] = []
        seen: set[str] = set()
        for rule in sorted(self.payload["rules"], key=lambda item: int(item["priority"])):
            matched = sorted(active.intersection(rule["when"]))
            if not matched:
                continue
            family = rule["id"]
            for action in rule["enqueue"]:
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

