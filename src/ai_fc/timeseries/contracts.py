"""Contract loader and stable paths for the multivariate forecast subsystem."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v1.yaml")
STORE_RELATIVE = Path("data/timeseries")
RAW_RELATIVE = STORE_RELATIVE / "raw"
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers"
FACTS_RELATIVE = STORE_RELATIVE / "facts"
MODEL_RELATIVE = STORE_RELATIVE / "models"
RUNS_RELATIVE = STORE_RELATIVE / "runs"
LATEST_RELATIVE = STORE_RELATIVE / "multivariate_latest.json"
WORKBOOK_RELATIVE = STORE_RELATIVE / "workbooks/multivariate_timeseries_latest.xlsx"


class TimeSeriesContractError(RuntimeError):
    """A preregistered model or data contract failed closed."""


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    payload = _normalize_yaml_scalars(yaml.safe_load(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TimeSeriesContractError("multivariate time-series contract is not a mapping")
    if payload.get("contract_id") != "multivariate_timeseries_v1":
        raise TimeSeriesContractError("unexpected multivariate time-series contract id")
    if payload.get("model_id") != "shadow.mf_dfm_ridge_varx_v1":
        raise TimeSeriesContractError("unexpected multivariate time-series model id")
    horizons = ((payload.get("target") or {}).get("horizons_sessions") or [])
    if horizons != [1, 5, 21, 63]:
        raise TimeSeriesContractError("time-series horizons must be preregistered 1/5/21/63")
    if ((payload.get("probability_contract") or {}).get("stored_unit") != "fraction"):
        raise TimeSeriesContractError("canonical probability unit must be fraction")
    probability = payload["probability_contract"]
    if probability.get("bounds") != [0.0, 1.0] or probability.get("combine_with_official_forecasts") is not False:
        raise TimeSeriesContractError("probability bounds or isolation contract drifted")
    varx = ((payload.get("model") or {}).get("varx") or {})
    if varx.get("lag_candidates") != [1, 2, 5]:
        raise TimeSeriesContractError("VARX lag candidates must remain preregistered 1/2/5")
    if varx.get("ridge_alpha_candidates") != [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0]:
        raise TimeSeriesContractError("Ridge alpha grid drifted")
    distribution = ((payload.get("model") or {}).get("distribution") or {})
    if distribution.get("path_count") != 20_000:
        raise TimeSeriesContractError("published distribution must use 20,000 paths")
    if distribution.get("block_length_candidates") != [5, 10, 21]:
        raise TimeSeriesContractError("stationary-bootstrap candidates drifted")
    if distribution.get("ewma_lambda_candidates") != [0.94, 0.97]:
        raise TimeSeriesContractError("EWMA candidates drifted")
    bridge = ((payload.get("sources") or {}).get("registered_historical_bridges") or {}).get("DTWEXBGS")
    if not bridge or bridge.get("predecessor") != "DTWEXB" or bridge.get("level_splice") != "prohibited":
        raise TimeSeriesContractError("registered official dollar-history bridge drifted")
    prohibitions = payload.get("prohibitions") or {}
    if not all(prohibitions.get(key) is True for key in (
        "direct_index_level_training", "forced_endpoint", "future_actual_exogenous",
        "silent_feature_drop", "silent_normalization", "official_ledger_write",
        "scenario_v5_2_mutation",
    )):
        raise TimeSeriesContractError("one or more model-risk prohibitions were removed")
    return payload


def _normalize_yaml_scalars(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_yaml_scalars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_yaml_scalars(item) for item in value]
    return value


def canonical_hash(payload: Any) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
