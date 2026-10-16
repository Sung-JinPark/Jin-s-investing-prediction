"""Preregistered identity and common validation for market-context research."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

MODEL_ID = "research.nasdaq_market_context_v1"
MODEL_VERSION = 1
AXES = ("growth", "inflation", "policy_rates", "energy", "ai_demand", "semiconductor", "risk_financial")
AXIS_LABELS = dict(zip(AXES, ("성장", "물가", "정책·금리", "에너지", "AI 수요·실적", "반도체 공급·경쟁", "위험·금융여건")))
HALF_LIVES = (5, 21, 63)
TRAIN_HORIZONS = (5, 21, 63)
TRAIN_WEIGHTS = (0.25, 0.5, 0.25)
HORIZON = 252
PATH_COUNT = 20000
SEED = 42
MIN_TRAIN_SESSIONS = 756
MIN_EVENTS = 30
CONTRACT_RELATIVE = Path("data/contracts/market_context_v1.yaml")
STORE_RELATIVE = Path("data/market_context")
FORECAST_LEDGER = STORE_RELATIVE / "ledgers/forecasts.jsonl"
RESOLUTION_LEDGER = STORE_RELATIVE / "ledgers/resolutions.jsonl"
MODEL_LEDGER = STORE_RELATIVE / "ledgers/models.jsonl"
LATEST_RELATIVE = STORE_RELATIVE / "latest.json"
QUANTILE_LEVELS = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
QUANTILE_NAMES = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")


class MarketContextError(ValueError):
    """The explicit research data or publication contract was not satisfied."""


def aware(value: str | datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise MarketContextError("invalid ISO timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise MarketContextError("timezone-aware timestamp required")
    return stamp.astimezone(timezone.utc)


def canonical_json(value: Any) -> str:
    def encode(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


json_hash = canonical_hash


def load_contract(root: Path) -> dict[str, Any]:
    try:
        contract = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MarketContextError(f"market-context contract unavailable: {exc}") from exc
    if not isinstance(contract, dict):
        raise MarketContextError("market-context contract must be a mapping")
    identities = {"contract_id": "market_context_v1", "model_id": MODEL_ID, "model_version": MODEL_VERSION}
    if any(contract.get(key) != value for key, value in identities.items()):
        raise MarketContextError("market-context contract identity mismatch")
    model = contract.get("model", {})
    expected = {"axes": list(AXES), "half_lives": list(HALF_LIVES), "horizon_sessions": HORIZON,
                "path_count": PATH_COUNT, "seed": SEED, "maximum_adjustment_sessions": 63,
                "minimum_training_sessions": MIN_TRAIN_SESSIONS, "minimum_events_per_family": MIN_EVENTS,
                "fit_intercept": False, "center_features": False, "bootstrap_count": 200,
                "bootstrap_block_sessions": 63, "train_horizons": list(TRAIN_HORIZONS),
                "horizon_weights": list(TRAIN_WEIGHTS), "lookback_sessions": 252,
                "primary_horizon": 21,
                "ridge_candidates": [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0, 100.0],
                "inner_purge_sessions": 63, "inner_embargo_sessions": 5,
                "coefficient_cadence": "monthly", "unsupported_family_numeric_effect": 0,
                "additional_daily_residual_noise": False}
    if any(model.get(key) != value for key, value in expected.items()):
        raise MarketContextError("numerical market-context contract differs from v1 implementation")
    representative = contract.get("representative", {})
    expected_representative = {
        "selection": "equal_weight_five_empirical_rank_distance_to_median",
        "statistics": ["terminal_log_return", "maximum_drawdown", "daily_volatility",
                       "negative_session_share", "sign_change_share"],
        "eligible_percentile_ranges": [[.4, .6], [.25, .75], [.25, .75], [.1, .9], [.1, .9]],
        "ties": "lowest_original_path_id", "relaxation": "prohibited",
        "daily_points_including_anchor": HORIZON + 1, "smoothing": "prohibited",
    }
    if any(representative.get(key) != value for key, value in expected_representative.items()):
        raise MarketContextError("representative market-context contract differs from v1 implementation")
    evaluation = contract.get("evaluation", {})
    expected_evaluation = {
        "primary": "crps_21", "minimum_matured_pit_origins": 252,
        "minimum_nonoverlapping_21_session_blocks": 12,
        "minimum_nonoverlapping_63_session_blocks": 8,
        "minimum_relative_crps_improvement": .02, "one_sided_confidence": .95,
        "secondary_maximum_relative_deterioration": .02,
        "inherited_sealed_performance": False, "choose_model_using_representative_error": False,
        "comparisons": ["baseline", "market_only", "event_only", "combined", "fhs"],
    }
    if any(evaluation.get(key) != value for key, value in expected_evaluation.items()):
        raise MarketContextError("evaluation market-context contract differs from v1 implementation")
    publication = contract.get("publication", {})
    if (publication.get("predictive_validation") != "not_established"
            or publication.get("official_ledger_write") is not False
            or publication.get("automatic_promotion") is not False
            or contract.get("probability_unit") != "fraction"):
        raise MarketContextError("research-only fraction publication contract required")
    return contract


def model_code_hash(root: Path) -> str:
    relative_paths = [Path("src/ai_fc/market_context") / name for name in
                      ("contracts.py", "model.py", "training.py", "evaluation.py", "features.py", "ledger.py", "pipeline.py")]
    relative_paths.append(Path("src/ai_fc/quant/mc.py"))
    return canonical_hash([{ "path": path.as_posix(), "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest() }
                           for path in relative_paths])


def runtime_identity() -> dict[str, Any]:
    return {"python": platform.python_version(),
            "packages": {name: version(name) for name in ("numpy", "scipy", "exchange-calendars")}}
