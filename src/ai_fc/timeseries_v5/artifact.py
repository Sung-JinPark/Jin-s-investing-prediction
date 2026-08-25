"""Fail-closed V5 projection and forecast artifact validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import MODEL_ID, PROBABILITY_SPACE
from .identifiers import content_hash


LATEST_RELATIVE = Path("data/timeseries_v5/multivariate_v5_latest.json")


def validate_latest(value: dict[str, Any]) -> None:
    if value.get("model_id") != MODEL_ID: raise ValueError("V5 model id mismatch")
    if value.get("probability_space") != PROBABILITY_SPACE: raise ValueError("V5 probability space mismatch")
    if value.get("probability_unit") != "fraction": raise ValueError("V5 probability unit mismatch")
    visible = value.get("numbers_visible") is True; research = value.get("research_gate", {}).get("pass") is True; operational = value.get("operational_gate", {}).get("pass") is True
    if visible is not (research and operational): raise ValueError("V5 visibility must equal both Gate decisions")
    if visible:
        horizons = value.get("horizons") or {}
        if set(horizons) != {"1", "5", "21", "63"}: raise ValueError("V5 visible horizon set incomplete")
        for row in horizons.values():
            probability = float(row["up_probability"])
            if not 0 <= probability <= 1: raise ValueError("V5 probability outside fraction bounds")
            quantiles = row["quantiles"]; ordered = [float(quantiles[key]) for key in ("p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99")]
            if ordered != sorted(ordered): raise ValueError("V5 quantile crossing")
    elif value.get("horizons") or value.get("path"): raise ValueError("V5 HOLD surface must hide numerical forecasts")
    body = dict(value); expected = body.pop("content_hash", None)
    if expected != content_hash(body): raise ValueError("V5 latest content hash mismatch")


def load_projection(root: Path) -> dict[str, Any] | None:
    path = root / LATEST_RELATIVE
    if not path.is_file(): return None
    value = json.loads(path.read_text(encoding="utf-8")); validate_latest(value); return value
