"""Append-only artifacts and dashboard projection for the time-series shadow model."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    LATEST_RELATIVE,
    LEDGER_RELATIVE,
    RUNS_RELATIVE,
    canonical_hash,
    load_contract,
)


FORECAST_LEDGER = "forecasts.jsonl"
RESOLUTION_LEDGER = "resolutions.jsonl"
CORRECTION_LEDGER = "corrections.jsonl"


class TimeSeriesArtifactError(RuntimeError):
    """A time-series artifact or append-only pointer failed validation."""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append_unique(path: Path, row: dict[str, Any], *, id_field: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    for prior in _read_jsonl(path):
        if prior.get(id_field) == row.get(id_field):
            if prior != row:
                raise TimeSeriesArtifactError(f"append-only conflict for {id_field}={row.get(id_field)}")
            return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return True


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def blocked_artifact(
    root: Path,
    *,
    as_of: str | None = None,
    knowledge_cutoff: str | None = None,
    reasons: list[str] | None = None,
    missing_features: list[str] | None = None,
) -> dict[str, Any]:
    contract = load_contract(root)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cutoff = knowledge_cutoff or now
    forecast_as_of = as_of or cutoff[:10]
    seed = {
        "model_id": contract["model_id"],
        "model_version": contract["model_version"],
        "contract_hash": canonical_hash(contract),
        "as_of": forecast_as_of,
        "knowledge_cutoff": cutoff,
        "display_state": "validation_pending",
    }
    return {
        "schema_version": 1,
        "forecast_id": f"ts-{canonical_hash(seed)[:20]}",
        "model_id": contract["model_id"],
        "model_version": contract["model_version"],
        "status": "shadow",
        "display_state": "validation_pending",
        "as_of": forecast_as_of,
        "knowledge_cutoff": cutoff,
        "generated_at": cutoff,
        "anchor": None,
        "target": contract["target"]["series_id"],
        "transform": contract["target"]["transform"],
        "probability_unit": "fraction",
        "probability_space": contract["probability_contract"]["space"],
        "combined_with_existing_models": False,
        "horizons": {},
        "path": {},
        "contributions_1d": {},
        "ensemble": {},
        "freshness": {
            "required_daily_sla_hours": contract["freshness"]["required_daily_sla_hours"],
            "missing_features": sorted(set(missing_features or [])),
        },
        "backtest": {
            "run_id": None,
            "gate_pass": False,
            "metrics": {},
            "reasons": reasons or ["PIT backfill and offline walk-forward validation are incomplete"],
        },
        "hashes": {
            "contract": canonical_hash(contract),
            "sources": None,
            "model": None,
            "content": None,
        },
        "publication": {
            "customer_numbers_visible": False,
            "automatic_champion_promotion": False,
            "minimum_shadow_sessions": contract["promotion"]["minimum_shadow_sessions"],
        },
    }


def validate_artifact(payload: dict[str, Any]) -> None:
    required = {
        "schema_version", "forecast_id", "model_id", "model_version", "status",
        "display_state", "as_of", "knowledge_cutoff", "anchor", "target", "transform",
        "probability_unit", "probability_space", "combined_with_existing_models",
        "horizons", "path", "contributions_1d", "ensemble", "freshness", "backtest",
        "hashes", "publication",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise TimeSeriesArtifactError(f"artifact missing fields: {missing}")
    if payload["schema_version"] != 1:
        raise TimeSeriesArtifactError("unsupported time-series artifact schema")
    if payload["model_id"] != "shadow.mf_dfm_ridge_varx_v1" or payload["status"] != "shadow":
        raise TimeSeriesArtifactError("time-series artifact must remain the registered shadow model")
    if payload["probability_unit"] != "fraction":
        raise TimeSeriesArtifactError("time-series probabilities must be stored as fractions")
    if payload["combined_with_existing_models"] is not False:
        raise TimeSeriesArtifactError("time-series probability space cannot be combined")
    if datetime.fromisoformat(payload["knowledge_cutoff"]).date() < datetime.fromisoformat(payload["as_of"]).date():
        raise TimeSeriesArtifactError("knowledge_cutoff cannot precede as_of")
    visible = bool((payload.get("publication") or {}).get("customer_numbers_visible"))
    gate_pass = bool((payload.get("backtest") or {}).get("gate_pass"))
    if visible is not gate_pass:
        raise TimeSeriesArtifactError("customer-number visibility must equal the offline publication gate")
    if not visible and (payload.get("horizons") or payload.get("path")):
        raise TimeSeriesArtifactError("failed publication gates must not expose customer numbers")
    quantile_order = ("p10", "p25", "p50", "p75", "p90")
    for horizon, row in (payload.get("horizons") or {}).items():
        quantiles = row.get("quantiles") or {}
        values = [quantiles.get(key) for key in quantile_order]
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise TimeSeriesArtifactError(f"horizon {horizon} quantiles are incomplete")
        if values != sorted(values):
            raise TimeSeriesArtifactError(f"horizon {horizon} quantiles are not monotone")
        for probability_key in ("probability_up", "first_touch_minus_10"):
            value = row.get(probability_key)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise TimeSeriesArtifactError(f"{probability_key} must be a fraction")
    path = payload.get("path") or {}
    if path:
        lengths = {len(path.get(key) or []) for key in quantile_order}
        if lengths != {63}:
            raise TimeSeriesArtifactError("published path must contain 63 values per quantile")
        for index in range(63):
            values = [float(path[key][index]) for key in quantile_order]
            if values != sorted(values):
                raise TimeSeriesArtifactError(f"path quantiles cross at session {index + 1}")
    contributions = payload.get("contributions_1d") or {}
    if contributions:
        predicted = float(contributions.get("predicted_log_return"))
        components = contributions.get("components") or {}
        if abs(sum(float(value) for value in components.values()) - predicted) > 1e-10:
            raise TimeSeriesArtifactError("one-day additive contributions do not reconcile")


def append_forecast(root: Path, payload: dict[str, Any]) -> Path:
    validate_artifact(payload)
    content = {**payload, "hashes": {**payload["hashes"], "content": None}}
    content_hash = canonical_hash(content)
    payload = {**payload, "hashes": {**payload["hashes"], "content": content_hash}}
    target = root / RUNS_RELATIVE / f"{payload['forecast_id']}.json"
    if target.exists():
        if _read_json(target) != payload:
            raise TimeSeriesArtifactError("forecast artifact id already has different content")
    else:
        _atomic_json(target, payload)
    ledger_row = {
        "forecast_id": payload["forecast_id"],
        "as_of": payload["as_of"],
        "knowledge_cutoff": payload["knowledge_cutoff"],
        "artifact_path": target.relative_to(root).as_posix(),
        "content_hash": content_hash,
        "status": "shadow",
    }
    _append_unique(
        root / LEDGER_RELATIVE / FORECAST_LEDGER,
        ledger_row,
        id_field="forecast_id",
    )
    pointer = {
        "schema_version": 1,
        "forecast_id": payload["forecast_id"],
        "artifact_path": ledger_row["artifact_path"],
        "content_hash": content_hash,
        "derived_pointer": True,
    }
    _atomic_json(root / LATEST_RELATIVE, pointer)
    return target


def append_resolution(root: Path, row: dict[str, Any]) -> bool:
    required = {"resolution_id", "forecast_id", "resolved_at", "horizon_sessions", "actual_index", "actual_return"}
    if not required.issubset(row):
        raise TimeSeriesArtifactError("resolution row is incomplete")
    return _append_unique(
        root / LEDGER_RELATIVE / RESOLUTION_LEDGER, row, id_field="resolution_id",
    )


def append_correction(root: Path, row: dict[str, Any]) -> bool:
    required = {"correction_id", "supersedes", "replacement", "reason", "corrected_at"}
    if not required.issubset(row) or row["supersedes"] == row["replacement"]:
        raise TimeSeriesArtifactError("correction requires distinct supersedes/replacement ids")
    return _append_unique(
        root / LEDGER_RELATIVE / CORRECTION_LEDGER, row, id_field="correction_id",
    )


def load_latest(root: Path) -> dict[str, Any]:
    pointer_path = root / LATEST_RELATIVE
    if not pointer_path.is_file():
        return blocked_artifact(root, reasons=["PIT 백필과 오프라인 검증을 준비하고 있습니다."])
    pointer = _read_json(pointer_path)
    artifact_path = root / str(pointer.get("artifact_path", ""))
    if not artifact_path.is_file():
        raise TimeSeriesArtifactError("latest pointer references a missing artifact")
    payload = _read_json(artifact_path)
    validate_artifact(payload)
    if payload["forecast_id"] != pointer.get("forecast_id"):
        raise TimeSeriesArtifactError("latest pointer forecast id mismatch")
    if payload["hashes"].get("content") != pointer.get("content_hash"):
        raise TimeSeriesArtifactError("latest pointer content hash mismatch")
    return payload


def load_projection(root: Path) -> dict[str, Any]:
    try:
        payload = load_latest(root)
    except (OSError, ValueError, TimeSeriesArtifactError) as exc:
        try:
            payload = blocked_artifact(root, reasons=[f"산출물 검증 실패: {exc}"])
        except (OSError, ValueError):
            # Synthetic dashboard fixtures and partially checked-out audit trees may
            # intentionally omit the preregistration contract.  The customer read
            # model must still fail closed instead of failing the whole dashboard.
            cutoff = "1970-01-01T00:00:00+00:00"
            payload = {
                "model_id": "shadow.mf_dfm_ridge_varx_v1",
                "model_version": 1,
                "as_of": cutoff,
                "knowledge_cutoff": cutoff,
                "probability_space": "isolated_multivariate_timeseries_shadow",
                "anchor": None,
                "horizons": {},
                "path": {},
                "contributions_1d": {},
                "ensemble": {},
                "freshness": {"status": "unavailable", "missing_features": []},
                "backtest": {
                    "gate_pass": False,
                    "reasons": ["시계열 연구모델 계약 또는 산출물을 준비하고 있습니다."],
                },
                "publication": {"customer_numbers_visible": False},
            }
    visible = bool(payload["publication"]["customer_numbers_visible"])
    projection = {
        "schema_version": 1,
        "status": "ready" if visible else "validation_pending",
        "model_id": payload["model_id"],
        "model_version": payload["model_version"],
        "model_label": "연구모델",
        "as_of": payload["as_of"],
        "knowledge_cutoff": payload["knowledge_cutoff"],
        "probability_space": payload["probability_space"],
        "combined_with_existing_models": False,
        "numbers_visible": visible,
        "anchor": payload["anchor"] if visible else None,
        "horizons": payload["horizons"] if visible else {},
        "path": payload["path"] if visible else {},
        "contributions_1d": payload["contributions_1d"] if visible else {},
        "ensemble": payload["ensemble"] if visible else {},
        "freshness": payload["freshness"],
        "backtest": payload["backtest"] if visible else {
            "gate_pass": False,
            "reasons": payload["backtest"].get("reasons") or ["오프라인 검증 중"],
        },
        "footnote": "*미국 시장·미국 공식 거시자료 기준",
    }
    return projection


def verify_latest(root: Path) -> dict[str, Any]:
    payload = load_latest(root)
    expected = payload["hashes"].get("content")
    replay = {**payload, "hashes": {**payload["hashes"], "content": None}}
    if canonical_hash(replay) != expected:
        raise TimeSeriesArtifactError("latest forecast content hash does not replay")
    ledger = _read_jsonl(root / LEDGER_RELATIVE / FORECAST_LEDGER)
    matching = [row for row in ledger if row.get("forecast_id") == payload["forecast_id"]]
    if len(matching) != 1:
        raise TimeSeriesArtifactError("latest forecast must have exactly one append-only ledger row")
    return {
        "ok": True,
        "forecast_id": payload["forecast_id"],
        "status": payload["display_state"],
        "content_hash": payload["hashes"]["content"],
        "customer_numbers_visible": payload["publication"]["customer_numbers_visible"],
    }
