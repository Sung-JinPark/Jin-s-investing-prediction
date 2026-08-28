"""Frozen V8 coordinates, V2 predecessor immutability guards, and paths."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


MODEL_ID = "shadow.mf_dfm_varx_calibrated_v8"
MODEL_VERSION = 8
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v8.yaml")
STORE_RELATIVE = Path("data/timeseries_v8")
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers"
RUNS_RELATIVE = STORE_RELATIVE / "runs"
EXPERIMENT_LEDGER_RELATIVE = LEDGER_RELATIVE / "development_experiments.jsonl"
HOLDOUT_LEDGER_RELATIVE = LEDGER_RELATIVE / "holdout_scorings.jsonl"
V2_RUN_RELATIVE = Path("data/timeseries_v2/runs/tsv2-backtest-f995c40e19ade197f3559b6e.json")

# Structural 2019-blindness: no V8 development code path may accept a later
# truncation date.  The sealed 2019+ interval stays untouched until the
# single, user-approved disclosure.
DEVELOPMENT_TRUNCATION_AFTER = "2019-04-30"
DESIGN_WINDOW = ("2007-01-01", "2014-12-31")
HOLDOUT_WINDOW = ("2015-01-01", "2018-12-31")


class TimeSeriesV8ContractError(RuntimeError):
    """A V8 preregistration or immutable V2 predecessor guard was violated."""


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


def load_contract_v8(root: Path) -> dict[str, Any]:
    payload = _normalize(yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TimeSeriesV8ContractError("V8 contract is not a mapping")
    if payload.get("contract_id") != "multivariate_timeseries_v8":
        raise TimeSeriesV8ContractError("unexpected V8 contract id")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV8ContractError("unexpected V8 identity")
    if payload["target"]["horizons_sessions"] != [1, 5, 21, 63]:
        raise TimeSeriesV8ContractError("V8 horizons drifted")
    probability = payload["probability_contract"]
    if probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]:
        raise TimeSeriesV8ContractError("V8 probabilities must be explicit fractions")
    if probability.get("combine_with_official_forecasts") is not False:
        raise TimeSeriesV8ContractError("V8 must remain isolated from official forecasts")
    if probability.get("combine_with_scenario_v5_2") is not False:
        raise TimeSeriesV8ContractError("V8 must remain isolated from Scenario V5.2")
    benchmark = payload["v2_benchmark"]
    if benchmark.get("immutable") is not True or benchmark.get("retune_prohibited") is not True:
        raise TimeSeriesV8ContractError("V2 predecessor immutability was weakened")
    caveat = payload["disclosure_caveat"]
    if caveat.get("v2_2019_scores_published_before_design") is not True:
        raise TimeSeriesV8ContractError("the semi-clean 2019+ caveat was removed")
    if caveat.get("candidate_selection_must_be_2019_blind") is not True:
        raise TimeSeriesV8ContractError("2019-blind candidate selection was weakened")
    windows = payload["model"]["windows"]
    if windows["design"] != ["2007-01-01", "2014-12-31"]:
        raise TimeSeriesV8ContractError("V8 design window drifted")
    if windows["holdout"] != ["2015-01-01", "2018-12-31"]:
        raise TimeSeriesV8ContractError("V8 holdout window drifted")
    if windows["development_truncation_after"] != DEVELOPMENT_TRUNCATION_AFTER:
        raise TimeSeriesV8ContractError("V8 development truncation drifted")
    if windows["sealed"] != ["2019-01-01", "latest"]:
        raise TimeSeriesV8ContractError("V8 sealed window drifted")
    varx = payload["model"]["varx"]
    if varx["lag_candidates"] != [1, 2, 5]:
        raise TimeSeriesV8ContractError("V8 must keep the frozen V2 lag grid")
    if varx["ridge_alpha_candidates"] != [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0]:
        raise TimeSeriesV8ContractError("V8 must keep the frozen V2 ridge grid")
    sealed = payload["model"]["sealed_evaluation"]
    if sealed.get("maximum_disclosures_per_model_version") != 1:
        raise TimeSeriesV8ContractError("V8 sealed disclosure budget drifted")
    if sealed.get("retune_after_failure") != "prohibited":
        raise TimeSeriesV8ContractError("V8 retune-after-failure prohibition was removed")
    if sealed.get("requires_explicit_user_signoff") is not True:
        raise TimeSeriesV8ContractError("V8 sealed disclosure lost its user sign-off gate")
    protocol = payload["development_protocol"]
    if int(protocol["maximum_development_evaluations"]) != 24:
        raise TimeSeriesV8ContractError("V8 development evaluation budget drifted")
    if int(protocol["holdout_maximum_finalists"]) != 3:
        raise TimeSeriesV8ContractError("V8 holdout finalist budget drifted")
    gate = payload["publication_gate"]
    if gate["long_horizon_mean_crps_min_improvement"] != 0.02:
        raise TimeSeriesV8ContractError("V8 publication gate was relaxed")
    if gate["p10_p90_coverage"] != [0.76, 0.84] or gate["p25_p75_coverage"] != [0.45, 0.55]:
        raise TimeSeriesV8ContractError("V8 coverage bands drifted")
    if gate["regime_p10_p90_minimum"] != 0.70:
        raise TimeSeriesV8ContractError("V8 regime coverage minimum drifted")
    required_prohibitions = {
        "mutate_v2", "retune_v2", "v2_store_write",
        "sealed_2019_access_during_development", "dev_gate_threshold_relaxation",
        "direct_index_level_training", "forced_endpoint", "future_actual_exogenous",
        "silent_feature_drop", "silent_normalization", "official_ledger_write",
        "scenario_v5_2_mutation", "automatic_sealed_disclosure",
        "automatic_main_self_modification_in_production",
    }
    if not all(payload["prohibitions"].get(key) is True for key in required_prohibitions):
        raise TimeSeriesV8ContractError("V8 model-risk prohibition was removed")
    return payload


def frozen_coordinates(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: contract[key]
        for key in (
            "model_id", "model_version", "target", "probability_contract",
            "data_policy", "v2_benchmark", "disclosure_caveat", "model",
            "research_grids", "development_protocol", "dev_gate_proxy",
            "evaluation", "publication_gate", "operational_gate", "promotion",
            "prohibitions",
        )
    }


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(frozen_coordinates(contract))


def model_code_hash(root: Path) -> str:
    """Hash the V8 implementation plus the frozen V2/V1 kernels it reuses."""
    dependency_paths = [
        *sorted((root / "src/ai_fc/timeseries_v8").rglob("*.py")),
        root / "src/ai_fc/timeseries_v2/model.py",
        root / "src/ai_fc/timeseries_v2/backtest.py",
        root / "src/ai_fc/timeseries_v2/features.py",
        root / "src/ai_fc/timeseries_v2/dfm_cache.py",
        root / "src/ai_fc/timeseries/model.py",
        root / "src/ai_fc/timeseries/backtest.py",
    ]
    digest = hashlib.sha256()
    for path in dependency_paths:
        if not path.is_file():
            raise TimeSeriesV8ContractError(f"V8 model dependency missing: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        body = path.read_bytes()
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def verify_v2_benchmark(root: Path, contract: dict[str, Any] | None = None) -> dict[str, str]:
    """Fail closed if the immutable V2 sealed run drifted in any pinned hash."""
    contract = contract or load_contract_v8(root)
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
            raise TimeSeriesV8ContractError(f"immutable V2 benchmark drifted: {key}")
    return observed


def assert_development_cutoff(day: str) -> str:
    """Reject any development data cutoff past the structural truncation date."""
    if str(day) > DEVELOPMENT_TRUNCATION_AFTER:
        raise TimeSeriesV8ContractError(
            "V8 development may not see data after "
            f"{DEVELOPMENT_TRUNCATION_AFTER}; requested {day}"
        )
    return str(day)
