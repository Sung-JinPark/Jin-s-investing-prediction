"""Frozen V2 contract, paths, and model-risk guards."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v2.yaml")
STORE_RELATIVE = Path("data/timeseries_v2")
RAW_RELATIVE = STORE_RELATIVE / "raw"
PRIVATE_RAW_RELATIVE = STORE_RELATIVE / "private_raw_locators"
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers"
FACTS_RELATIVE = STORE_RELATIVE / "facts"
PARQUET_RELATIVE = STORE_RELATIVE / "parquet"
DFM_CACHE_RELATIVE = STORE_RELATIVE / "dfm_cache"
MODEL_RELATIVE = STORE_RELATIVE / "models"
RUNS_RELATIVE = STORE_RELATIVE / "runs"
LATEST_RELATIVE = STORE_RELATIVE / "multivariate_v2_latest.json"
WORKBOOK_RELATIVE = STORE_RELATIVE / "workbooks/multivariate_timeseries_v2_latest.xlsx"


class TimeSeriesV2ContractError(RuntimeError):
    """A frozen V2 coordinate drifted or a contract gate failed."""


def runtime_manifest() -> dict[str, str]:
    """Return the numerical runtime needed to replay a V2 fit or evaluation."""
    packages = ("numpy", "pandas", "scipy", "statsmodels")
    return {
        "python": platform.python_version(),
        **{name: importlib.metadata.version(name) for name in packages},
    }


def require_dfm_runtime(manifest: dict[str, str] | None = None) -> dict[str, str]:
    """Fail closed unless the preregistered DynamicFactorMQ runtime is active."""
    observed = dict(manifest or runtime_manifest())
    if observed.get("statsmodels") != "0.14.6":
        raise TimeSeriesV2ContractError(
            "V2 DFM requires statsmodels==0.14.6; "
            f"observed {observed.get('statsmodels') or 'missing'}"
        )
    pandas_parts = str(observed.get("pandas", "0")).split(".")
    try:
        pandas_pair = tuple(int(part) for part in pandas_parts[:2])
    except ValueError as exc:
        raise TimeSeriesV2ContractError("V2 pandas runtime is not parseable") from exc
    if not ((2, 2) <= pandas_pair < (3, 0)):
        raise TimeSeriesV2ContractError(
            "V2 requires pandas>=2.2,<3; "
            f"observed {observed.get('pandas') or 'missing'}"
        )
    return observed


def _normalize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def canonical_hash(value: Any) -> str:
    body = json.dumps(_normalize(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def model_code_hash(root: Path) -> str:
    """Hash the V2 implementation and the frozen V1 numerical primitives it imports."""
    dependency_paths = [
        *[
            root / f"src/ai_fc/timeseries_v2/{name}"
            for name in (
                "contracts.py", "market_archive.py", "dfm_cache.py", "features.py",
                "model.py", "backtest.py", "pipeline.py", "artifact.py",
            )
        ],
        root / "src/ai_fc/timeseries/model.py",
        root / "src/ai_fc/timeseries/backtest.py",
        root / "src/ai_fc/timeseries/events.py",
        root / "src/ai_fc/timeseries/ledger.py",
    ]
    digest = hashlib.sha256()
    for path in dependency_paths:
        if not path.is_file():
            raise TimeSeriesV2ContractError(f"V2 model dependency missing: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        body = path.read_bytes()
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def load_contract_v2(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    payload = _normalize(yaml.safe_load(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TimeSeriesV2ContractError("V2 contract is not a mapping")
    if payload.get("contract_id") != "multivariate_timeseries_v2":
        raise TimeSeriesV2ContractError("unexpected V2 contract id")
    if payload.get("model_id") != "shadow.mf_dfm_ridge_varx_v2":
        raise TimeSeriesV2ContractError("unexpected V2 model id")
    if payload.get("model_version") != 2:
        raise TimeSeriesV2ContractError("unexpected V2 model version")
    if payload["target"]["horizons_sessions"] != [1, 5, 21, 63]:
        raise TimeSeriesV2ContractError("V2 horizons drifted")
    probability = payload["probability_contract"]
    if probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]:
        raise TimeSeriesV2ContractError("V2 probabilities must be explicit fractions")
    if probability.get("combine_with_official_forecasts") is not False:
        raise TimeSeriesV2ContractError("V2 must remain isolated from official forecasts")
    if probability.get("combine_with_scenario_v5_2") is not False:
        raise TimeSeriesV2ContractError("V2 must remain isolated from Scenario V5.2")
    grades = payload["data_policy"]["grades"]
    if grades != ["native_pit", "reconstructed_market_archive", "captured_forward"]:
        raise TimeSeriesV2ContractError("V2 data grades drifted")
    if payload["data_policy"].get("reconstructed_archive_is_native_pit") is not False:
        raise TimeSeriesV2ContractError("reconstructed market history cannot be called native PIT")
    varx = payload["model"]["varx"]
    if varx["endogenous"] != [
        "nasdaq_return", "vix_change", "dgs2_change_bps", "curve_change_bps", "dollar_change",
    ]:
        raise TimeSeriesV2ContractError("V2 core market vector drifted")
    if "BAMLH0A0HYM2" in varx["endogenous"]:
        raise TimeSeriesV2ContractError("restricted HY OAS cannot be required in V2")
    if varx["lag_candidates"] != [1, 2, 5]:
        raise TimeSeriesV2ContractError("V2 lag grid drifted")
    if varx["ridge_alpha_candidates"] != [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0]:
        raise TimeSeriesV2ContractError("V2 ridge grid drifted")
    dynamic_factor = payload["model"]["dynamic_factor"]
    if dynamic_factor.get("em_tolerance") != 0.00001:
        raise TimeSeriesV2ContractError("V2 DFM EM tolerance drifted")
    if dynamic_factor.get("em_cold_max_iterations") != 300:
        raise TimeSeriesV2ContractError("V2 DFM cold-fit budget drifted")
    if dynamic_factor.get("em_warm_max_iterations") != 300:
        raise TimeSeriesV2ContractError("V2 DFM warm-fit budget drifted")
    if dynamic_factor.get("log_likelihood_decrease_allowed") is not False:
        raise TimeSeriesV2ContractError("V2 DFM cannot accept a decreasing likelihood fit")
    overlay = payload["event_overlay"]
    if overlay.get("minimum_pit_observations_for_overlay") != 10:
        raise TimeSeriesV2ContractError("V2 event overlay minimum drifted")
    if overlay.get("minimum_pit_observations_for_varx") != 60:
        raise TimeSeriesV2ContractError("V2 event coefficient minimum drifted")
    if overlay.get("future_actual_surprise_allowed") is not False:
        raise TimeSeriesV2ContractError("V2 cannot use a future event actual")
    candidates = payload["model"]["candidates"]
    if list(candidates) != ["C1", "C2", "C3", "C4", "C5"]:
        raise TimeSeriesV2ContractError("V2 candidate inventory drifted")
    windows = payload["model"]["windows"]
    if windows["warmup"] != ["1996-01-01", "2006-12-31"]:
        raise TimeSeriesV2ContractError("V2 warmup window drifted")
    if windows["development"] != ["2007-01-01", "2018-12-31"]:
        raise TimeSeriesV2ContractError("V2 development window drifted")
    if windows["sealed"] != ["2019-01-01", "latest"]:
        raise TimeSeriesV2ContractError("V2 sealed window drifted")
    if payload["ralph"]["maximum_iterations"] != 50 or payload["ralph"]["maximum_hours"] != 24:
        raise TimeSeriesV2ContractError("V2 Ralph runtime budget drifted")
    operational = payload["operational_gate"]
    if operational.get("required_market_max_age_hours") != 48:
        raise TimeSeriesV2ContractError("V2 required-market freshness SLA drifted")
    if operational.get("required_market_groups") != [
        ["NASDAQCOM"], ["VIX"], ["DGS2"], ["DGS10"], ["DTWEXBGS", "DTWEXB"],
    ]:
        raise TimeSeriesV2ContractError("V2 required-market freshness inventory drifted")
    required_prohibitions = {
        "direct_index_level_training", "forced_endpoint", "future_actual_exogenous",
        "silent_feature_drop", "silent_normalization", "official_ledger_write",
        "scenario_v5_2_mutation", "automatic_main_self_modification_in_production",
    }
    if not all(payload["prohibitions"].get(key) is True for key in required_prohibitions):
        raise TimeSeriesV2ContractError("V2 model-risk prohibition was removed")
    return payload


def frozen_coordinates(contract: dict[str, Any]) -> dict[str, Any]:
    """Coordinates that a Ralph repair run may never tune after start."""
    return {
        "model_id": contract["model_id"],
        "sources": contract["sources"],
        "transforms": contract["transforms"],
        "alignment": contract["alignment"],
        "candidates": contract["model"]["candidates"],
        "dynamic_factor": contract["model"]["dynamic_factor"],
        "varx": contract["model"]["varx"],
        "ensemble": contract["model"]["ensemble"],
        "distribution": contract["model"]["distribution"],
        "event_overlay": contract["event_overlay"],
        "windows": contract["model"]["windows"],
        "evaluation": contract["evaluation"],
        "publication_gate": contract["publication_gate"],
        "operational_gate": contract["operational_gate"],
        "probability_contract": contract["probability_contract"],
    }


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(frozen_coordinates(contract))
