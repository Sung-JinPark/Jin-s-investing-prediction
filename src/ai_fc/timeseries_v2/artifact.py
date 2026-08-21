"""Append-only V2 forecast/sealed ledgers and dashboard projection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .contracts import LATEST_RELATIVE, LEDGER_RELATIVE, canonical_hash


FORECAST_LEDGER = LEDGER_RELATIVE / "forecasts.jsonl"
SEALED_LEDGER = LEDGER_RELATIVE / "sealed_evaluations.jsonl"
SEALED_CORRECTION_LEDGER = LEDGER_RELATIVE / "sealed_evaluation_corrections.jsonl"
RESOLUTION_LEDGER = LEDGER_RELATIVE / "resolutions.jsonl"


class TimeSeriesV2ArtifactError(RuntimeError):
    """A V2 append-only or publication artifact failed closed."""


def append_unique(root: Path, relative: Path, payload: dict[str, Any], *, key: str) -> bool:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                existing[str(row[key])] = row
    identity = str(payload[key])
    if identity in existing:
        if existing[identity] != payload:
            raise TimeSeriesV2ArtifactError(f"append-only collision for {identity}")
        return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def write_latest(root: Path, payload: dict[str, Any]) -> Path:
    if payload.get("model_id") != "shadow.mf_dfm_ridge_varx_v2":
        raise TimeSeriesV2ArtifactError("V2 latest pointer received another model")
    publication = payload.get("publication") or {}
    visible = publication.get("customer_numbers_visible") is True
    if visible and payload.get("gate", {}).get("pass") is not True:
        raise TimeSeriesV2ArtifactError("V2 numbers cannot be visible before all gates pass")
    if visible and payload.get("probability_space") != "research_timeseries_v2_conditional":
        raise TimeSeriesV2ArtifactError("V2 probability space is not isolated")
    if visible:
        for horizon in payload.get("horizons", {}).values():
            probability = horizon.get("probability_up")
            if probability is None or not 0.0 <= float(probability) <= 1.0:
                raise TimeSeriesV2ArtifactError("V2 probability must be a fraction")
    payload = dict(payload)
    payload["content_hash"] = canonical_hash(payload)
    target = root / LATEST_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target


def read_latest(root: Path) -> dict[str, Any] | None:
    path = root / LATEST_RELATIVE
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = canonical_hash({key: value for key, value in payload.items() if key != "content_hash"})
    if payload.get("content_hash") != expected:
        raise TimeSeriesV2ArtifactError("V2 latest content hash mismatch")
    return payload


def blocked_latest(
    *, as_of: str, knowledge_cutoff: str, contract_hash: str, reasons: list[str],
    data_summary: dict[str, Any], ralph_run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "model_id": "shadow.mf_dfm_ridge_varx_v2",
        "model_version": 2,
        "status": "shadow_validation_hold",
        "display_state": "validation_pending",
        "as_of": as_of,
        "knowledge_cutoff": knowledge_cutoff,
        "probability_unit": "fraction",
        "probability_space": "research_timeseries_v2_conditional",
        "publication": {
            "customer_numbers_visible": False,
            "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
        },
        "gate": {"pass": False, "reasons": reasons},
        "data_summary": data_summary,
        "ralph_run_id": ralph_run_id,
        "footnote": "*미국 시장·미국 공식 거시자료 기준",
    }


def load_projection(root: Path) -> dict[str, Any] | None:
    payload = read_latest(root)
    if payload is None:
        return None
    visible = payload["publication"]["customer_numbers_visible"] is True
    base = {
        "schema_version": 2,
        "model_id": payload["model_id"],
        "status": payload["status"],
        "display_state": payload["display_state"],
        "as_of": payload["as_of"],
        "knowledge_cutoff": payload["knowledge_cutoff"],
        "numbers_visible": visible,
        "probability_space": payload["probability_space"],
        "combined_with_existing_models": False,
        "gate": payload["gate"],
        "data_summary": payload.get("data_summary", {}),
        "footnote": payload.get("footnote", "*미국 시장·미국 공식 거시자료 기준"),
    }
    if not visible:
        return base
    base.update({
        "anchor": payload["anchor"],
        "horizons": payload["horizons"],
        "path": {
            "history_dates": [row["date"] for row in payload["history"]],
            "history_index": [row["value"] for row in payload["history"]],
            "dates": payload["future_dates"],
            **payload["path_quantiles"],
        },
        "contributions_1d": {
            "exact_prediction": payload["contributions"]["exact_prediction"],
            "sum": payload["contributions"]["sum"],
            "components": {
                row["name"]: row["value"] for row in payload["contributions"]["rows"]
            },
        },
        "ensemble": payload["ensemble"],
        "backtest": {"metrics": payload["backtest"]},
    })
    return base
