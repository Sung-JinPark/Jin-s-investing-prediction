"""Frozen V3 coordinates and V2 immutability guards."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


MODEL_ID = "shadow.nasdaq_direct_regime_distribution_v3"
MODEL_VERSION = 3
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v3.yaml")
STORE_RELATIVE = Path("data/timeseries_v3")
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers"
RUNS_RELATIVE = STORE_RELATIVE / "runs"
MODELS_RELATIVE = STORE_RELATIVE / "models"
LATEST_RELATIVE = STORE_RELATIVE / "multivariate_v3_latest.json"
WORKBOOK_RELATIVE = STORE_RELATIVE / "workbooks/multivariate_timeseries_v3_latest.xlsx"
V2_RUN_RELATIVE = Path("data/timeseries_v2/runs/tsv2-backtest-f995c40e19ade197f3559b6e.json")


class TimeSeriesV3ContractError(RuntimeError):
    """A V3 preregistration or immutable V2 benchmark was violated."""


def _normal(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normal(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def canonical_hash(value: Any) -> str:
    body = json.dumps(_normal(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_contract_v3(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TimeSeriesV3ContractError("V3 contract must be a mapping")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV3ContractError("unexpected V3 identity")
    if payload["target"].get("horizons_sessions") != [1, 5, 21, 63]:
        raise TimeSeriesV3ContractError("V3 direct horizons drifted")
    if payload["target"].get("recursive_one_day_long_horizon") != "prohibited":
        raise TimeSeriesV3ContractError("recursive one-day long-horizon model is prohibited")
    probability = payload["probability_contract"]
    if probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]:
        raise TimeSeriesV3ContractError("V3 probability unit must be an explicit fraction")
    if probability.get("combine_with_official_forecasts") is not False:
        raise TimeSeriesV3ContractError("V3 cannot combine with official forecasts")
    if probability.get("combine_with_scenario_v5_2") is not False:
        raise TimeSeriesV3ContractError("V3 cannot combine with Scenario V5.2")
    weights = payload["baseline"]["components"]
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-12:
        raise TimeSeriesV3ContractError("fixed anchor weights must sum to one")
    if payload["baseline"].get("row_wise_oracle") != "prohibited":
        raise TimeSeriesV3ContractError("row-wise oracle comparator is prohibited")
    if not 0.0 <= float(payload["stacking"]["anchor_floor"]) <= 1.0:
        raise TimeSeriesV3ContractError("invalid anchor floor")
    required = {
        "mutate_v2", "retune_v2", "row_wise_oracle_baseline", "future_actual",
        "report_free_text_numeric_shift", "parallel_scenario_curve_shift",
        "automatic_official_merge", "automatic_investment_execution",
    }
    if not all(payload["prohibitions"].get(key) is True for key in required):
        raise TimeSeriesV3ContractError("V3 model-risk prohibition was removed")
    return payload


def frozen_coordinates(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: contract[key]
        for key in (
            "model_id", "model_version", "target", "probability_contract", "data_policy",
            "baseline", "direct_location", "volatility_tail", "regimes", "dfm_alignment",
            "events", "market_implied", "analyst_reports", "stacking", "path_reconciliation",
            "evaluation", "research_gate", "forward_shadow", "monitoring", "publication",
            "prohibitions",
        )
    }


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(frozen_coordinates(contract))


def model_code_hash(root: Path) -> str:
    folder = root / "src/ai_fc/timeseries_v3"
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def verify_v2_benchmark(root: Path, contract: dict[str, Any] | None = None) -> dict[str, str]:
    contract = contract or load_contract_v3(root)
    expected = contract["v2_benchmark"]
    payload = json.loads((root / V2_RUN_RELATIVE).read_text(encoding="utf-8"))
    observed = {
        "run_id": str(payload.get("run_id")),
        "content_hash": str(payload.get("content_hash")),
        "contract_hash": str(payload.get("contract_hash")),
        "model_code_hash": str(payload.get("hashes", {}).get("model_code")),
    }
    for key, value in observed.items():
        if value != str(expected[key]):
            raise TimeSeriesV3ContractError(f"sealed V2 benchmark drifted: {key}")
    return observed


def probability(value: float) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise TimeSeriesV3ContractError(f"probability outside [0,1]: {number}")
    return number
