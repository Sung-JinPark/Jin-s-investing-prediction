"""Identity, preregistration, and provenance for daily six-month research."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

MODEL_ID = "research.nasdaq_daily6m_varx_v1"
MODEL_VERSION = 1
CONTRACT_RELATIVE = Path("data/contracts/timeseries_daily6m_v1.yaml")
STORE_RELATIVE = Path("data/timeseries_daily6m")
FORECAST_LEDGER = STORE_RELATIVE / "ledgers/forecasts.jsonl"
RESOLUTION_LEDGER = STORE_RELATIVE / "ledgers/resolutions.jsonl"
LATEST_RELATIVE = STORE_RELATIVE / "latest.json"
PATH_COUNT = 20000
MINIMUM_TRAINING_SESSIONS = 800
ENDOGENOUS_NAMES = (
    "nasdaq_return", "vix_change", "dgs2_change_bps", "curve_change_bps", "dollar_change",
)
EXOGENOUS_NAMES = ("growth_factor", "inflation_factor", "dfm_age_since_release")
QUANTILE_LEVELS = (0.10, 0.25, 0.50, 0.75, 0.90)
QUANTILE_NAMES = ("p10", "p25", "p50", "p75", "p90")


class Daily6mContractError(RuntimeError):
    """A research forecast cannot satisfy its explicit contract."""


def canonical_hash(value: Any) -> str:
    def encode(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"unsupported hash value: {type(item).__name__}")

    body = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False, default=encode)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(contract)


def load_contract(root: Path) -> dict[str, Any]:
    with (root / CONTRACT_RELATIVE).open(encoding="utf-8") as handle:
        contract = yaml.safe_load(handle)
    if not isinstance(contract, dict):
        raise Daily6mContractError("daily6m contract must be a mapping")
    required = {
        "contract_id": "timeseries_daily6m_v1", "model_id": MODEL_ID, "model_version": MODEL_VERSION,
    }
    if any(contract.get(key) != value for key, value in required.items()):
        raise Daily6mContractError("daily6m contract identity mismatch")
    target = contract.get("target", {})
    probability = contract.get("probability_contract", {})
    model = contract.get("model", {})
    publication = contract.get("publication", {})
    if (target.get("calendar_months") != 6 or target.get("exchange") != "XNAS"
            or target.get("calendar_end_rule") != "preserve_month_end_else_same_day_clamped"):
        raise Daily6mContractError("daily6m requires six calendar months of XNAS sessions")
    if probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]:
        raise Daily6mContractError("daily6m requires explicit fraction probabilities")
    if (model.get("path_count") != PATH_COUNT
            or model.get("endogenous") != list(ENDOGENOUS_NAMES)
            or model.get("exogenous") != list(EXOGENOUS_NAMES)
            or model.get("ensemble_weights") != {"expanding": 0.5, "rolling_10y": 0.5}
            or model.get("minimum_training_sessions") != MINIMUM_TRAINING_SESSIONS
            or model.get("exogenous_projection") != "latest_known_values_held_constant"
            or model.get("per_horizon_calibration") != "none"):
        raise Daily6mContractError("daily6m model coordinates differ from v1 implementation")
    numerical_defaults = {
        "lag_candidates": [1, 2, 5],
        "ridge_alpha_candidates": [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0],
        "inner_purge_sessions": 63, "inner_embargo_sessions": 5, "rolling_sessions": 2520,
        "block_length_candidates": [5, 10, 21], "ewma_lambda_candidates": [0.94, 0.97],
        "distribution_validation_horizon": 21,
        "seed_rule": "sha256_model_id_model_version_origin_session",
        "quantiles": list(QUANTILE_LEVELS),
    }
    if any(model.get(key) != value for key, value in numerical_defaults.items()):
        raise Daily6mContractError("daily6m numerical settings disagree with immutable kernel defaults")
    fhs = contract.get("comparison", {}).get("fhs", {})
    if fhs.get("ewma_lambda") != 0.97 or fhs.get("burn_in_sessions") != 60:
        raise Daily6mContractError("daily6m FHS benchmark settings disagree with v1 implementation")
    tail = contract.get("data_policy", {}).get("captured_forward_tail", {})
    tail_policy = {
        "series_id": "VIXCLS", "raw_series_id": "VIX", "source_id": "cboe_vix_archive",
        "allowed_session": "latest_completed_origin_only", "maximum_sessions": 1,
        "require_receipt": True, "require_raw_sha256": True,
        "availability": "actual_capture_before_issuance", "prohibit_native_relabelling": True,
        "historical_backfill": False,
    }
    if tail != tail_policy:
        raise Daily6mContractError("daily6m permits only the registered current-session captured VIX tail")
    resolution_policy = {
        "ledger": "resolutions", "revision_policy": "append_with_supersedes_for_changed_published_close",
        "revision_key": ["source_id", "series_id", "observation_time", "value", "available_at", "vintage_start", "source_hash"],
        "capture_only_changes_create_revision": False, "preserves_all_revisions": True,
        "verify_replays_immutable_forecast_and_pinned_outcomes": True,
    }
    if contract.get("evaluation", {}).get("resolution") != resolution_policy:
        raise Daily6mContractError("daily6m requires append-only native-outcome revisions and scoring replay")
    if (publication.get("predictive_validation") != "not_established"
            or publication.get("official_ledger_write") is not False
            or publication.get("automatic_promotion") is not False):
        raise Daily6mContractError("research preview must not imply validated or official promotion")
    return contract


def model_code_hash(root: Path) -> str:
    # This version's complete numerical dependency set, without mutating or
    # changing the separate V8 model-code hash definition.
    paths = [
        root / "src/ai_fc/timeseries_daily6m/contracts.py",
        root / "src/ai_fc/timeseries_daily6m/model.py",
        root / "src/ai_fc/timeseries_daily6m/features.py",
        root / "src/ai_fc/timeseries_daily6m/pipeline.py",
        root / "src/ai_fc/timeseries/model.py",
        root / "src/ai_fc/timeseries/backtest.py",
        root / "src/ai_fc/timeseries_v2/model.py",
        root / "src/ai_fc/timeseries_v2/contracts.py",
        root / "src/ai_fc/timeseries_v2/dfm_cache.py",
        root / "src/ai_fc/timeseries_v2/market_archive.py",
        root / "data/contracts/multivariate_timeseries_v2.yaml",
        root / "src/ai_fc/timeseries_v8/model.py",
    ]
    digest = hashlib.sha256()
    for path in paths:
        name = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()
