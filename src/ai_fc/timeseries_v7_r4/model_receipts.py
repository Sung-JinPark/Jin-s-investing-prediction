"""Fail-closed lineage receipts for model selection, stacking and calibration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from .integrity import canonical_json, sha256_bytes


_BINDING_HASHES = ("contract_hash", "code_hash", "runtime_hash", "data_hash")
_STAGE_HASHES = (
    "selection_hash", "stacking_hash", "calibration_hash", "sample_set_hash",
)


def _hash(value: Any, name: str) -> str:
    exact = str(value)
    if len(exact) != 64 or any(char not in "0123456789abcdef" for char in exact):
        raise ValueError(f"{name} must be a lowercase SHA-256 hash")
    return exact


def _bound_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in receipt.items()
            if key != "binding_hash"}


def emit_model_receipts(
    rows: Iterable[Mapping[str, Any]], *, contract_hash: str, code_hash: str,
    runtime_hash: str, data_hash: str,
) -> dict[str, Any]:
    """Emit one fully bound receipt per frozen origin/horizon coordinate."""
    bindings = {
        name: _hash(value, name) for name, value in (
            ("contract_hash", contract_hash), ("code_hash", code_hash),
            ("runtime_hash", runtime_hash), ("data_hash", data_hash),
        )
    }
    normalized = []
    coordinates: set[tuple[str, int]] = set()
    for source in rows:
        origin = str(source.get("origin_session", ""))
        horizon = source.get("horizon_sessions")
        if not origin or not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
            raise ValueError("valid origin_session and horizon_sessions are required")
        coordinate = (origin, horizon)
        if coordinate in coordinates:
            raise ValueError("duplicate origin-horizon receipt")
        coordinates.add(coordinate)
        row = {"origin_session": origin, "horizon_sessions": horizon}
        row.update({name: _hash(source.get(name), name) for name in _STAGE_HASHES})
        normalized.append(row)
    if not normalized:
        raise ValueError("at least one origin-horizon receipt is required")
    normalized.sort(key=lambda row: (row["origin_session"], row["horizon_sessions"]))
    receipt = {
        "schema": "model_selection_stacking_calibration_receipt_v1",
        **bindings,
        "origin_horizon_receipts": normalized,
    }
    receipt["binding_hash"] = sha256_bytes(canonical_json(receipt))
    return receipt


def verify_model_receipts(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild and authenticate a receipt; absence or mutation fails closed."""
    if receipt.get("schema") != "model_selection_stacking_calibration_receipt_v1":
        raise ValueError("model receipt is required")
    try:
        rebuilt = emit_model_receipts(
            receipt["origin_horizon_receipts"],
            **{name: receipt[name] for name in _BINDING_HASHES},
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("complete model receipt is required") from exc
    if rebuilt["binding_hash"] != receipt.get("binding_hash"):
        raise ValueError("model receipt binding hash mismatch")
    if rebuilt != dict(receipt):
        raise ValueError("model receipt contains unbound fields")
    return rebuilt
