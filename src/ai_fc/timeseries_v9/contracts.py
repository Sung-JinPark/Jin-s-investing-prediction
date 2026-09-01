"""Frozen V9 coordinates, immutable V8 predecessor guards, and role hashes.

V9 never edits the sealed V8 boundary: every V8/V2 artifact is imported or
read, byte-identical.  The gate arithmetic here is a verbatim copy of the V8
contract — the loop is prohibited from changing a single threshold.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

MODEL_ID = "shadow.mf_dfm_varx_liquidity_v9"
MODEL_VERSION = 9
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v9.yaml")
STORE_RELATIVE = Path("data/timeseries_v9")
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers"
RUNS_RELATIVE = STORE_RELATIVE / "runs"
EXPERIMENT_LEDGER_RELATIVE = LEDGER_RELATIVE / "development_experiments.jsonl"
HOLDOUT_LEDGER_RELATIVE = LEDGER_RELATIVE / "holdout_scorings.jsonl"
V8_SEALED_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/sealed_evaluations.jsonl")
V1_CANONICAL_FACTS_RELATIVE = Path("data/timeseries/facts/observations.parquet")

DEVELOPMENT_TRUNCATION_AFTER = "2019-04-30"
DESIGN_WINDOW = ("2007-01-01", "2014-12-31")
HOLDOUT_WINDOW = ("2015-01-01", "2018-12-31")


class TimeSeriesV9ContractError(RuntimeError):
    """A V9 preregistration or immutable V8 predecessor guard was violated."""


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


def load_contract_v9(root: Path) -> dict[str, Any]:
    payload = _normalize(yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise TimeSeriesV9ContractError("V9 contract is not a mapping")
    if payload.get("contract_id") != "multivariate_timeseries_v9":
        raise TimeSeriesV9ContractError("unexpected V9 contract id")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV9ContractError("unexpected V9 identity")
    if payload["target"]["horizons_sessions"] != [1, 5, 21, 63]:
        raise TimeSeriesV9ContractError("V9 horizons drifted")
    probability = payload["probability_contract"]
    if probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]:
        raise TimeSeriesV9ContractError("V9 probabilities must be explicit fractions")
    for flag in ("combine_with_official_forecasts", "combine_with_scenario_v5_2",
                 "combine_with_v8_surface"):
        if probability.get(flag) is not False:
            raise TimeSeriesV9ContractError("V9 must remain isolated from other surfaces")
    benchmark = payload["v8_benchmark"]
    if benchmark.get("immutable") is not True or benchmark.get("retune_prohibited") is not True:
        raise TimeSeriesV9ContractError("V8 predecessor immutability was weakened")
    windows = payload["model"]["windows"]
    if windows["design"] != list(DESIGN_WINDOW):
        raise TimeSeriesV9ContractError("V9 design window drifted")
    if windows["holdout"] != list(HOLDOUT_WINDOW):
        raise TimeSeriesV9ContractError("V9 holdout window drifted")
    if windows["development_truncation_after"] != DEVELOPMENT_TRUNCATION_AFTER:
        raise TimeSeriesV9ContractError("V9 development truncation drifted")
    if windows["sealed"] != ["2019-01-01", "latest"]:
        raise TimeSeriesV9ContractError("V9 sealed window drifted")
    varx = payload["model"]["varx"]
    if varx["lag_candidates"] != [1, 2, 5]:
        raise TimeSeriesV9ContractError("V9 must keep the frozen V2 lag grid")
    if varx["ridge_alpha_candidates"] != [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0]:
        raise TimeSeriesV9ContractError("V9 must keep the frozen V2 ridge grid")
    sealed = payload["model"]["sealed_evaluation"]
    if sealed.get("maximum_disclosures_per_model_version") != 1:
        raise TimeSeriesV9ContractError("V9 sealed disclosure budget drifted")
    if sealed.get("retune_after_failure") != "prohibited":
        raise TimeSeriesV9ContractError("V9 retune-after-failure prohibition was removed")
    if sealed.get("requires_explicit_user_signoff") is not True:
        raise TimeSeriesV9ContractError("V9 sealed disclosure lost its user sign-off gate")
    protocol = payload["development_protocol"]
    if int(protocol["maximum_development_evaluations"]) != 24:
        raise TimeSeriesV9ContractError("V9 development evaluation budget drifted")
    if int(protocol["holdout_maximum_finalists"]) != 3:
        raise TimeSeriesV9ContractError("V9 holdout finalist budget drifted")
    if protocol.get("holdout_requires_explicit_user_approval") is not True:
        raise TimeSeriesV9ContractError("V9 holdout user-approval gate was removed")
    # Gate arithmetic is a verbatim V8 copy — reject any relaxation.
    proxy = payload["dev_gate_proxy"]
    expected_proxy = {
        "design_long_horizon_mean_crps_min_improvement": 0.025,
        "design_paired_se_max": 0.001,
        "projected_full_window_ci90_upper_max": -0.0004,
        "projection_reference_origins": 1011,
        "design_short_horizon_crps_max_underperformance": 0.01,
        "design_p10_p90_coverage": [0.76, 0.84],
        "design_p25_p75_coverage": [0.45, 0.55],
        "design_gfc_regime_p10_p90_minimum": 0.72,
        "holdout_long_horizon_mean_crps_min_improvement": 0.02,
        "holdout_paired_bootstrap_ci90_upper_max": 0.0,
        "pit_leakage_count": 0,
        "receipt_linkage": 1.0,
    }
    for key, value in expected_proxy.items():
        if proxy.get(key) != value:
            raise TimeSeriesV9ContractError(f"V9 dev gate proxy drifted from V8: {key}")
    gate = payload["publication_gate"]
    if gate["long_horizon_mean_crps_min_improvement"] != 0.02:
        raise TimeSeriesV9ContractError("V9 publication gate was relaxed")
    if gate["p10_p90_coverage"] != [0.76, 0.84] or gate["p25_p75_coverage"] != [0.45, 0.55]:
        raise TimeSeriesV9ContractError("V9 coverage bands drifted")
    if gate["regime_p10_p90_minimum"] != 0.70:
        raise TimeSeriesV9ContractError("V9 regime coverage minimum drifted")
    features = payload["features"]
    registered = features.get("registered") or {}
    if set(registered) != {"F1_m2sl_liquidity"}:
        raise TimeSeriesV9ContractError("V9 registered feature set drifted from preregistration")
    rules = features["rejection_rules"]
    if float(rules["max_abs_correlation_vs_existing_exog"]) != 0.85:
        raise TimeSeriesV9ContractError("V9 correlation rejection threshold drifted")
    required_prohibitions = {
        "mutate_v2", "retune_v2", "v2_store_write",
        "mutate_v8", "retune_v8", "v8_store_write",
        "sealed_2019_access_during_development", "dev_gate_threshold_relaxation",
        "direct_index_level_training", "forced_endpoint", "future_actual_exogenous",
        "silent_feature_drop", "silent_normalization", "official_ledger_write",
        "scenario_v5_2_mutation", "automatic_sealed_disclosure",
        "automatic_holdout_consumption",
        "automatic_main_self_modification_in_production", "secret_loading_in_loops",
    }
    if not all(payload["prohibitions"].get(key) is True for key in required_prohibitions):
        raise TimeSeriesV9ContractError("V9 model-risk prohibition was removed")
    return payload


def frozen_coordinates(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        key: contract[key]
        for key in (
            "model_id", "model_version", "target", "probability_contract",
            "data_policy", "v8_benchmark", "model", "features", "research_grids",
            "development_protocol", "dev_gate_proxy", "evaluation",
            "publication_gate", "operational_gate", "promotion", "prohibitions",
        )
    }


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(frozen_coordinates(contract))


def verify_v8_benchmark(root: Path, contract: dict[str, Any] | None = None) -> dict[str, str]:
    """Fail closed if the immutable V8 sealed disclosure drifted in any pinned hash."""
    contract = contract or load_contract_v9(root)
    expected = contract["v8_benchmark"]
    path = root / V8_SEALED_LEDGER_RELATIVE
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if path.is_file() else []
    match = next((row for row in rows if row.get("run_id") == expected["run_id"]), None)
    if match is None:
        raise TimeSeriesV9ContractError("pinned V8 sealed run is missing from its ledger")
    observed = {
        "run_id": str(match.get("run_id")),
        "content_hash": str(match.get("content_hash")),
        "contract_hash": str(match.get("contract_hash")),
        "model_code_hash": str(match.get("model_code_hash")),
    }
    for key, value in observed.items():
        if value != str(expected[key]):
            raise TimeSeriesV9ContractError(f"immutable V8 benchmark drifted: {key}")
    if (match.get("summary") or {}).get("gate_pass") is not True:
        raise TimeSeriesV9ContractError("pinned V8 sealed run is not a PASS disclosure")
    return observed


def v8_sealed_source_hash(root: Path) -> str:
    """Byte-level fingerprint of the sealed V8 package — must never move under V9."""
    digest = hashlib.sha256()
    for path in sorted((root / "src/ai_fc/timeseries_v8").rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        body = path.read_bytes()
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def model_code_hash(root: Path) -> str:
    """Hash the V9 implementation plus the frozen V8/V2/V1 kernels it reuses."""
    dependency_paths = [
        *sorted((root / "src/ai_fc/timeseries_v9").rglob("*.py")),
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
            raise TimeSeriesV9ContractError(f"V9 model dependency missing: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        body = path.read_bytes()
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def role_hashes(root: Path) -> dict[str, str]:
    """Role-separated code fingerprints (train / selection / holdout).

    The supervisor loop records these at BOOT and refuses to continue when a
    role's code moved mid-run — iteration may not silently rewrite the code
    that selects or scores itself.
    """
    contract = load_contract_v9(root)
    package = root / "src/ai_fc/timeseries_v9"
    out: dict[str, str] = {}
    for role, files in contract["role_separation"].items():
        if role == "note":
            continue
        digest = hashlib.sha256()
        for name in files:
            path = package / name
            if not path.is_file():
                raise TimeSeriesV9ContractError(f"role file missing for {role}: {name}")
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
        out[str(role)] = digest.hexdigest()
    return out


def assert_development_cutoff(day: str) -> str:
    """Reject any development data cutoff past the structural truncation date."""
    if str(day) > DEVELOPMENT_TRUNCATION_AFTER:
        raise TimeSeriesV9ContractError(
            "V9 development may not see data after "
            f"{DEVELOPMENT_TRUNCATION_AFTER}; requested {day}"
        )
    return str(day)
