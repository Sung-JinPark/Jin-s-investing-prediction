"""Fail-closed guard preventing any R6 worker from reading R5 outer evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OuterAccessBlocked(RuntimeError):
    """Raised before a denied R5 outer path or role can be opened."""

    state = "BLOCKED_PROTECTED_SCOPE"


def _normalized_role(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


@dataclass(frozen=True)
class R5OuterDenylist:
    repo_root: Path
    contract: dict[str, Any]

    @classmethod
    def load(cls, repo_root: Path) -> "R5OuterDenylist":
        root = repo_root.resolve()
        contract_path = (
            root
            / "data"
            / "timeseries_v7_r6"
            / "contracts"
            / "r5_outer_worker_denylist.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if contract.get("policy") != "deny_before_open":
            raise ValueError("R6 outer denylist must use deny_before_open")
        if contract.get("retry_allowed") is not False:
            raise ValueError("R5 outer retry must remain forbidden")
        if contract.get("outer_exposure_count_frozen") != 1:
            raise ValueError("R5 outer exposure count must remain frozen at one")
        return cls(repo_root=root, contract=contract)

    def assert_role_allowed(self, role: str) -> None:
        normalized = _normalized_role(role)
        denied = {_normalized_role(item) for item in self.contract["deny_roles"]}
        prefixes = tuple(
            _normalized_role(item) for item in self.contract["deny_role_prefixes"]
        )
        if normalized in denied or normalized.startswith(prefixes):
            raise OuterAccessBlocked(
                f"BLOCKED_PROTECTED_SCOPE: denied R5 outer role {role!r}"
            )

    def assert_path_allowed(self, candidate: Path) -> None:
        path = candidate if candidate.is_absolute() else self.repo_root / candidate
        resolved = path.resolve(strict=False)
        denied_paths = {
            (self.repo_root / item).resolve(strict=False)
            for item in self.contract["deny_paths"]
        }
        denied_basenames = {
            item.lower() for item in self.contract["deny_basenames"]
        }
        if resolved in denied_paths or resolved.name.lower() in denied_basenames:
            raise OuterAccessBlocked(
                f"BLOCKED_PROTECTED_SCOPE: denied R5 outer path {resolved}"
            )

    def guarded_read_bytes(self, candidate: Path, *, role: str) -> bytes:
        self.assert_role_allowed(role)
        self.assert_path_allowed(candidate)
        path = candidate if candidate.is_absolute() else self.repo_root / candidate
        return path.read_bytes()
