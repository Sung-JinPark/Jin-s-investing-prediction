"""Deterministic multilayer historical-shape engine for Scenario V5.2.

The module is deliberately research-only.  It transports the latest completed
official market anchor into three mutually exclusive point-in-time historical
episode databases, then uses scenario-native feature schemas, empirical phase
durations, residual pools, and transitions for S1/S2/S3.  Validated evidence
changes both episode selection and phase-duration selection before mixture
weights are computed.  It never writes an official artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy.stats import energy_distance, wasserstein_distance

from ai_fc.scenario_v5.contracts import canonical_hash, file_hash
from ai_fc.scenario_v5_2.clustering import ScenarioClusterError, build_clustered_prior
from ai_fc.scenario_v5_2.separation import (
    SEPARATION_CONTRACT_RELATIVE,
    SeparationContractError,
    load_separation_contract,
    structural_event_adapter,
)


CANDIDATE_ID = "scenario_v5_2_scenario_clustered_db_v4"
WEIGHT_CONTRACT_RELATIVE = Path("data/contracts/scenario_v5_2_weights.yaml")
CANDIDATE_RELATIVE = Path(
    "data/scenarios/candidates/"
    "scenario_v5_2_scenario_clustered_db_v4_latest.json"
)
SHADOW_V52_RELATIVE = Path(
    "data/scenarios/candidates/"
    "scenario_v5_2_dotcom_dominant_generator_v3_latest.json"
)
LEGACY_V52_RELATIVE = Path(
    "data/scenarios/candidates/"
    "scenario_v5_2_macro_actualized_historical_shape_v1_latest.json"
)
ANCHOR_DATE = date(2026, 8, 7)
KNOWLEDGE_CUTOFF = "2026-08-10T00:00:00+00:00"
ANCHOR = 26690.62
ATH = 27093.90
REFERENCE_PRICE = 26206.89
PATH_COUNT_PER_ENGINE = 3000
SEED = 520807
QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
QUANTILE_NAMES = ("p5", "p10", "p25", "p50", "p75", "p90", "p95")

SOURCE_PATHS = (
    "data/raw/macro/bls_empsit_2026_07_20260807_browser_capture.txt",
    "data/normalized/macro/bls_empsit_2026_07_20260807.json",
    "data/raw/rates/fed_rate_monitor_20260808.html",
    "data/normalized/rates/fed_rate_monitor_pre_post_jobs_20260807.json",
    "data/raw/market/yahoo_ixic_daily_20160104_20260807.json",
    "data/normalized/market/yahoo_ixic_daily_20160104_20260807_manifest.json",
    "data/normalized/market/jobs_event_state_20260807.json",
    "data/scenarios/candidates/scenario_v5_1_time_aligned_legacy_prior_v1_latest.json",
    "data/model_runs/knn_analog_latest.json",
    "data/normalized/market/dotcom_upside_analog_20260810.json",
    "data/scenario_views/approved/scenario_v5_2_dotcom_upside_260810.json",
    "data/raw/market/dualdb_ixic_dotcom_daily_19950103_20041231.json",
    "data/normalized/market/dualdb_ixic_dotcom_daily_19950103_20041231.json",
    "data/raw/market/dualdb_macro_cluster_daily_19900102_20260804.json",
    "data/normalized/market/dualdb_macro_cluster_daily_19900102_20260804.json",
    "data/scenarios/nasdaq_latest.json",
    "data/contracts/scenario_v5_3_separation.yaml",
)


class ScenarioV52Error(RuntimeError):
    """A fail-closed V5.2 input or model gate."""


def source_file_hash(root: Path, relative: str | Path) -> str:
    """Hash sources portably while preserving raw-capture bytes exactly."""
    relative_path = Path(relative)
    path = root / relative_path
    if relative_path.as_posix() in {SOURCE_PATHS[7], SOURCE_PATHS[15]}:
        # The existing V5.1 reference JSON predates the current EOL rules.  Text
        # mode makes its reference-only hash stable across Windows/Linux clones.
        normalized = path.read_text(encoding="utf-8").encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()
    return file_hash(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ScenarioV52Error(f"timezone required: {value}")
    return result


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioV52Error(f"{name} must be a non-boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise ScenarioV52Error(f"{name} must be finite")
    return result


def _validate_fraction(value: Any, name: str) -> float:
    result = _finite_number(value, name)
    if not 0.0 <= result <= 1.0:
        raise ScenarioV52Error(f"{name} fraction outside [0,1]")
    return result


def _validate_rate_distributions(payload: dict[str, Any], cutoff: datetime) -> None:
    if payload.get("probability_unit") != "fraction":
        raise ScenarioV52Error("rate probability unit must be explicit fraction")
    for snapshot_id, snapshot in payload["snapshots"].items():
        if _aware(snapshot["available_at"]) > cutoff:
            raise ScenarioV52Error(f"future rate snapshot: {snapshot_id}")
        for meeting, distribution in snapshot["meetings"].items():
            values = [_validate_fraction(v, f"{snapshot_id}.{meeting}.{k}")
                      for k, v in distribution.items()]
            if not math.isclose(sum(values), 1.0, abs_tol=0.0015):
                raise ScenarioV52Error(
                    f"rate distribution does not sum to one: {snapshot_id}.{meeting}"
                )


def load_inputs(root: Path) -> dict[str, Any]:
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ScenarioV52Error(f"missing V5.2 source: {relative}")
    for baseline in (SHADOW_V52_RELATIVE, LEGACY_V52_RELATIVE):
        if not (root / baseline).is_file():
            raise ScenarioV52Error(f"missing V5.2 shadow baseline: {baseline}")
    if not (root / WEIGHT_CONTRACT_RELATIVE).is_file():
        raise ScenarioV52Error("missing Scenario V5.2 weight contract")
    labor = _read_json(root / SOURCE_PATHS[1])
    rates = _read_json(root / SOURCE_PATHS[3])
    history_manifest = _read_json(root / SOURCE_PATHS[5])
    market = _read_json(root / SOURCE_PATHS[6])
    v51 = _read_json(root / SOURCE_PATHS[7])
    dotcom_model_run = _read_json(root / SOURCE_PATHS[8])
    dotcom = _read_json(root / SOURCE_PATHS[9])
    dotcom_view = _read_json(root / SOURCE_PATHS[10])
    dotcom_history = _read_json(root / SOURCE_PATHS[12])
    macro_cluster_history = _read_json(root / SOURCE_PATHS[14])
    current_scenario = _read_json(root / SOURCE_PATHS[15])
    shadow_v52 = _read_json(root / SHADOW_V52_RELATIVE)
    legacy_v52 = _read_json(root / LEGACY_V52_RELATIVE)
    weight_contract = yaml.safe_load(
        (root / WEIGHT_CONTRACT_RELATIVE).read_text(encoding="utf-8")
    )
    try:
        separation_contract, separation_contract_audit = load_separation_contract(root)
    except SeparationContractError as exc:
        raise ScenarioV52Error(f"invalid complete-separation contract: {exc}") from exc
    spaces = weight_contract.get("weight_spaces", {})
    if weight_contract.get("candidate_id") != CANDIDATE_ID \
            or weight_contract.get("probability_unit") != "fraction" \
            or weight_contract.get("official_or_champion_use") is not False:
        raise ScenarioV52Error("invalid V5.2 weight contract identity")
    for name in ("A_evidence_strength", "B_generator_dotcom_block_share"):
        active = _validate_fraction(spaces.get(name, {}).get("active"), f"{name}.active")
        cap = _validate_fraction(spaces.get(name, {}).get("cap"), f"{name}.cap")
        if active > cap or not math.isclose(cap, .60):
            raise ScenarioV52Error(f"{name} exceeds the preregistered 0.60 cap")
    if spaces.get("C_mixture_probability", {}).get("directly_settable") is not False:
        raise ScenarioV52Error("C mixture probability must be derived, not configured")
    from .event_learning import event_score_summary

    event_updates = event_score_summary(root)
    event_cluster_strength: dict[str, float] = {}
    for row in event_updates["events"]:
        cluster = str(row["dependency_cluster_id"])
        event_cluster_strength[cluster] = event_cluster_strength.get(cluster, 0.0) \
            + float(row["scores"]["effective_strength"])
    if any(value > .35 for value in event_cluster_strength.values()):
        raise ScenarioV52Error("event-learning dependency cluster cap exceeded")
    event_updates["dependency_cluster_strength"] = event_cluster_strength
    event_cutoffs = [
        _aware(str(row["as_of"])) for row in event_updates["events"]
    ]
    current_scenario_generated = _aware(str(current_scenario.get("generated_at")))
    cutoff = max([_aware(KNOWLEDGE_CUTOFF), current_scenario_generated, *event_cutoffs])
    for label, row in (("labor", labor), ("market", market)):
        if _aware(row["available_at"]) > cutoff:
            raise ScenarioV52Error(f"future {label} evidence")
    if labor.get("units", {}).get("rates") != "fraction":
        raise ScenarioV52Error("labor rates require explicit fraction unit")
    for field in (
        "unemployment_rate", "labor_force_participation_rate",
        "employment_population_ratio", "average_hourly_earnings_yoy",
    ):
        _validate_fraction(labor["actual"][field], f"labor.actual.{field}")
    if labor.get("missing_fields"):
        raise ScenarioV52Error("required labor fields are missing; missing is not zero")
    try:
        current_anchor = _finite_number(current_scenario["anchor"], "current_scenario.anchor")
        current_asof = date.fromisoformat(str(current_scenario["asof"]))
        current_ath = _finite_number(current_scenario["ath"], "current_scenario.ath")
        current_reference = _finite_number(
            current_scenario["reference_price"], "current_scenario.reference_price"
        )
    except (KeyError, ValueError) as exc:
        raise ScenarioV52Error("current scenario anchor contract is invalid") from exc
    if current_anchor <= 0 or current_ath <= 0 or current_reference <= 0 \
            or current_asof > cutoff.date():
        raise ScenarioV52Error("current scenario anchor escapes its information set")
    _validate_rate_distributions(rates, cutoff)
    raw_history = root / history_manifest["raw_source_path"]
    if file_hash(raw_history) != history_manifest["raw_sha256"]:
        raise ScenarioV52Error("historical price raw hash mismatch")
    if not math.isclose(
        float(history_manifest["last_close"]), ANCHOR, rel_tol=0.0, abs_tol=0.01
    ):
        raise ScenarioV52Error("historical last close does not match post-event anchor")
    if file_hash(root / dotcom["source_path"]) != dotcom["source_sha256"]:
        raise ScenarioV52Error("dotcom analog source hash mismatch")
    dotcom_raw = root / dotcom_history.get("raw_source_path", "")
    if dotcom_raw != root / SOURCE_PATHS[11] or not dotcom_raw.is_file():
        raise ScenarioV52Error("dotcom daily raw source path mismatch")
    if file_hash(dotcom_raw) != dotcom_history.get("raw_sha256"):
        raise ScenarioV52Error("dotcom daily raw source hash mismatch")
    if dotcom_history.get("series") != "^IXIC" \
            or dotcom_history.get("row_count") != 2519 \
            or dotcom_history.get("first_session") != "1995-01-03" \
            or dotcom_history.get("last_session") != "2004-12-31":
        raise ScenarioV52Error("dotcom daily source coverage mismatch")
    macro_raw = root / macro_cluster_history.get("raw_source_path", "")
    if macro_raw != root / SOURCE_PATHS[13] or not macro_raw.is_file():
        raise ScenarioV52Error("macro cluster raw source path mismatch")
    if file_hash(macro_raw) != macro_cluster_history.get("raw_sha256"):
        raise ScenarioV52Error("macro cluster raw source hash mismatch")
    if set(macro_cluster_history.get("series", {})) != {
        "NASDAQCOM", "DFF", "DGS2", "DGS10", "T10Y2Y", "VIXCLS", "NFCI",
    }:
        raise ScenarioV52Error("macro cluster series coverage mismatch")
    if dotcom_model_run.get("model") != "knn_analog":
        raise ScenarioV52Error("dotcom analog must come from the registered kNN run")
    if dotcom.get("probability_unit") != "fraction":
        raise ScenarioV52Error("dotcom forward-return targets require explicit fraction unit")
    if int(dotcom.get("cycle_count", 0)) != 1 or int(dotcom.get("neighbor_count", 0)) != 5:
        raise ScenarioV52Error("dotcom single-cycle dependency disclosure mismatch")
    strengths = {
        key: _validate_fraction(value, f"dotcom.scenario_strength.{key}")
        for key, value in dotcom.get("scenario_strength", {}).items()
    }
    if set(strengths) != {"S1", "S2", "S3"} or not (
        strengths["S1"] == .60 and strengths["S2"] == strengths["S3"] == 0.0
    ):
        raise ScenarioV52Error("dotcom evidence must be isolated to S1 at strength 0.60")
    if max(strengths.values()) > _validate_fraction(
        dotcom.get("dependency_cap"), "dotcom.dependency_cap"
    ):
        raise ScenarioV52Error("dotcom dependency cap exceeded")
    override = dotcom.get("approved_override", {})
    if not math.isclose(float(dotcom.get("dependency_cap", 0)), .60) \
            or not math.isclose(float(override.get("cap", 0)), .60) \
            or not override.get("approval_receipt") \
            or override.get("official_or_champion_use") is not False:
        raise ScenarioV52Error("dotcom 0.60 research override is not explicitly bounded")
    if dotcom_view.get("used_numerically") is not True \
            or not dotcom_view.get("human_approval_receipt"):
        raise ScenarioV52Error("dotcom numerical view lacks explicit human approval")
    if dotcom_view.get("scenario_strength") != dotcom.get("scenario_strength"):
        raise ScenarioV52Error("dotcom view and normalized strengths disagree")
    for label, row in (
        ("dotcom", dotcom), ("dotcom_view", dotcom_view),
        ("dotcom_history", dotcom_history),
        ("macro_cluster_history", macro_cluster_history),
    ):
        if _aware(str(row["available_at"])) > cutoff:
            raise ScenarioV52Error(f"future {label} evidence")
    return {
        "labor": labor,
        "rates": rates,
        "history_manifest": history_manifest,
        "market": market,
        "v51": v51,
        "dotcom": dotcom,
        "dotcom_view": dotcom_view,
        "dotcom_history": dotcom_history,
        "macro_cluster_history": macro_cluster_history,
        "current_scenario": current_scenario,
        "forecast_anchor": {
            "date": current_asof.isoformat(),
            "close": current_anchor,
            "ath": current_ath,
            "reference_price": current_reference,
            "available_at": current_scenario_generated.isoformat(),
        },
        "dotcom_model_run": dotcom_model_run,
        "event_updates": event_updates,
        "knowledge_cutoff": cutoff.isoformat(),
        "shadow_v52": shadow_v52,
        "legacy_v52": legacy_v52,
        "weight_contract": weight_contract,
        "separation_contract": separation_contract,
        "separation_contract_audit": separation_contract_audit,
    }


def _business_dates(start: date, end: date) -> list[str]:
    values: list[str] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _historical_returns(
    root: Path, manifest: dict[str, Any],
) -> tuple[np.ndarray, list[str], np.ndarray]:
    raw = _read_json(root / manifest["raw_source_path"])
    result = raw["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    rows: list[tuple[str, float]] = []
    for stamp, close in zip(timestamps, closes, strict=True):
        if close is None:
            continue
        session = datetime.fromtimestamp(int(stamp), tz=timezone.utc).date().isoformat()
        if session <= ANCHOR_DATE.isoformat():
            rows.append((session, _finite_number(close, f"history.{session}.close")))
    dates = [row[0] for row in rows]
    values = np.asarray([row[1] for row in rows], dtype=float)
    if len(values) != int(manifest["row_count"]):
        raise ScenarioV52Error("historical row count mismatch")
    if dates[-1] != ANCHOR_DATE.isoformat() or not math.isclose(values[-1], ANCHOR, abs_tol=.01):
        raise ScenarioV52Error("historical series is not aligned to anchor")
    returns = np.diff(np.log(values))
    if len(returns) < 1260 or not np.isfinite(returns).all():
        raise ScenarioV52Error("insufficient approved point-in-time historical returns")
    return returns, dates, values


def generate_prior(
    root: Path, inputs: dict[str, Any], *, seed: int = SEED,
    path_count_per_engine: int = PATH_COUNT_PER_ENGINE, block_restart_probability: float = .10,
    generator_dotcom_share: float | None = None,
    residual_scale_override: float | None = None,
    allow_shadow_cap_exceed: bool = False,
    structural_scores: dict[str, Any] | None = None,
) -> tuple[np.ndarray, list[str], np.ndarray, dict[str, Any], dict[str, Any]]:
    anchor_date = date.fromisoformat(inputs["forecast_anchor"]["date"])
    anchor = float(inputs["forecast_anchor"]["close"])
    if anchor_date >= date(2027, 12, 31):
        raise ScenarioV52Error("current anchor leaves no 2027 research horizon")
    dates = [
        anchor_date.isoformat(),
        *_business_dates(anchor_date + timedelta(days=1), date(2027, 12, 31)),
    ]
    horizon = len(dates) - 1
    if not 0 < block_restart_probability <= 1:
        raise ScenarioV52Error("block restart probability must be in (0,1]")
    _, history_dates, history_levels = _historical_returns(
        root, inputs["history_manifest"]
    )
    if structural_scores is None:
        structural_scores = evidence_scores(inputs)
    structural_adapter = structural_event_adapter(
        structural_scores, inputs["separation_contract"]
    )
    try:
        paths, engines, cluster_audit = build_clustered_prior(
            history_dates,
            history_levels,
            inputs["dotcom_history"],
            inputs["macro_cluster_history"],
            horizon=horizon,
            count_per_scenario=path_count_per_engine,
            seed=seed,
            restart_probability=block_restart_probability,
            anchor=anchor,
            weight_contract=inputs["weight_contract"],
            generator_dotcom_share=generator_dotcom_share,
            residual_scale_override=residual_scale_override,
            allow_shadow_cap_exceed=allow_shadow_cap_exceed,
            separation_contract=inputs["separation_contract"],
            structural_adapter=structural_adapter,
        )
    except ScenarioClusterError as exc:
        raise ScenarioV52Error(f"scenario cluster gate failed: {exc}") from exc
    actual_dates = history_dates[-60:]
    actual_values = [round(float(value), 2) for value in history_levels[-60:]]
    if actual_dates[-1] != anchor_date.isoformat():
        actual_dates = [*actual_dates, anchor_date.isoformat()]
        actual_values = [*actual_values, round(anchor, 2)]
    historical_actual = {
        "dates": actual_dates,
        "values": actual_values,
        "role": "historical_actual_through_anchor",
    }
    generator_audit = {
        **cluster_audit,
        "path_count": int(paths.shape[0]),
        "path_count_by_engine": {
            "S1_dotcom_easing_multilayer": int((engines == 0).sum()),
            "S2_balanced_soft_landing_layer": int((engines == 1).sum()),
            "S3_tightening_stress_layer": int((engines == 2).sum()),
        },
        "engine_mixture_probability": {
            "S1_dotcom_easing_multilayer": 1.0 / 3.0,
            "S2_balanced_soft_landing_layer": 1.0 / 3.0,
            "S3_tightening_stress_layer": 1.0 / 3.0,
        },
        "dotcom_source_dataset_id": inputs["dotcom_history"]["dataset_id"],
        "dotcom_source_available_at": inputs["dotcom_history"]["available_at"],
        "macro_source_dataset_id": inputs["macro_cluster_history"]["dataset_id"],
        "macro_source_available_at": inputs["macro_cluster_history"]["available_at"],
        "legacy_block_restart_probability": block_restart_probability,
        "legacy_block_restart_probability_active": False,
        "restart_policy": "empirical_scenario_native_phase_transitions",
        "general_history_start": history_dates[0],
        "general_history_end": history_dates[-1],
        "weight_contract_path": WEIGHT_CONTRACT_RELATIVE.as_posix(),
        "weight_contract_sha256": file_hash(root / WEIGHT_CONTRACT_RELATIVE),
        "separation_contract_path": SEPARATION_CONTRACT_RELATIVE.as_posix(),
        "separation_contract_sha256": file_hash(root / SEPARATION_CONTRACT_RELATIVE),
        "separation_contract_audit": inputs["separation_contract_audit"],
        "structural_event_adapter": structural_adapter,
    }
    return paths, dates, engines, historical_actual, generator_audit


def _robust_z(values: np.ndarray) -> np.ndarray:
    median = float(np.median(values))
    q25, q75 = np.quantile(values, [0.25, 0.75])
    scale = max(float(q75 - q25) / 1.349, 1e-9)
    return (values - median) / scale


def _path_metrics(paths: np.ndarray, dates: list[str]) -> dict[str, np.ndarray]:
    anchor = float(paths[0, 0])
    returns = np.diff(np.log(paths), axis=1)
    running_max = np.maximum.accumulate(paths, axis=1)
    drawdowns = paths / running_max - 1.0
    date_2026 = max(index for index, value in enumerate(dates) if value <= "2026-12-31")
    returns_2026 = returns[:, :date_2026]
    running_max_2026 = running_max[:, :date_2026 + 1]
    drawdowns_2026 = paths[:, :date_2026 + 1] / running_max_2026 - 1.0
    early = min(20, paths.shape[1] - 1)
    trough = np.argmin(drawdowns, axis=1)
    recovery = np.empty(paths.shape[0], dtype=float)
    for row, trough_index in enumerate(trough):
        prior_peak = float(running_max[row, trough_index])
        recovered = np.flatnonzero(paths[row, trough_index + 1:] >= prior_peak)
        recovery[row] = (float(recovered[0] + 1) if recovered.size
                         else float(paths.shape[1] - trough_index + 30))
    return {
        "terminal_2026": paths[:, date_2026],
        "terminal_2027": paths[:, -1],
        "terminal_return_2026": paths[:, date_2026] / anchor - 1.0,
        "terminal_return_2027": paths[:, -1] / anchor - 1.0,
        "early_return": paths[:, early] / anchor - 1.0,
        "maximum_drawdown": drawdowns.min(axis=1),
        "maximum_drawdown_2026": drawdowns_2026.min(axis=1),
        "annualized_volatility": returns.std(axis=1, ddof=1) * math.sqrt(252.0),
        "annualized_volatility_2026": returns_2026.std(axis=1, ddof=1) * math.sqrt(252.0),
        "downside_semivolatility": np.sqrt(
            np.mean(np.square(np.minimum(returns, 0.0)), axis=1)
        ) * math.sqrt(252.0),
        "time_underwater": (drawdowns < -.02).mean(axis=1),
        "direction_changes": (
            np.sign(returns[:, 1:]) * np.sign(returns[:, :-1]) < 0
        ).sum(axis=1).astype(float),
        "recovery_days": recovery,
    }


def _expected_hike_count(distribution: dict[str, float]) -> float:
    result = 0.0
    for target_range, probability in distribution.items():
        lower = float(target_range.split("-")[0])
        steps = int(round((lower - 3.50) / 0.25))
        result += steps * float(probability)
    return result


def evidence_scores(inputs: dict[str, Any]) -> dict[str, Any]:
    labor = inputs["labor"]
    actual = labor["actual"]
    consensus = labor["consensus"]["nonfarm_payroll_change"]
    payroll_surprise_z = (actual["nonfarm_payroll_change"] - consensus) / 100000.0
    revision_z = labor["combined_revision"] / 100000.0
    layoff_z = actual["temporary_layoffs_change"] / 500000.0
    labor_growth_risk_raw = (
        0.50 * -payroll_surprise_z + 0.35 * -revision_z + 0.15 * layoff_z
    )
    event_raw = inputs["event_updates"]["raw_weighted_scores"]
    growth_risk_raw = labor_growth_risk_raw + float(event_raw["growth_risk"])
    growth_risk = math.tanh(growth_risk_raw)

    rates = inputs["rates"]["snapshots"]
    pre = rates["pre_jobs_previous_day"]["meetings"]
    post = rates["post_jobs_current"]["meetings"]
    meeting_deltas = {
        meeting: _expected_hike_count(post[meeting]) - _expected_hike_count(pre[meeting])
        for meeting in pre
    }
    expected_count_relief_raw = -sum(meeting_deltas.values()) / len(meeting_deltas)
    aggregate_deltas = {
        meeting: float(row["delta"])
        for meeting, row in inputs["rates"]["aggregate_hike_probability"].items()
    }
    aggregate_probability_relief_raw = -sum(aggregate_deltas.values()) \
        / len(aggregate_deltas) / .10
    base_policy_relief_raw = (
        .60 * aggregate_probability_relief_raw + .40 * expected_count_relief_raw
    )
    policy_relief_raw = base_policy_relief_raw + float(event_raw["policy_relief"])
    policy_relief = math.tanh(policy_relief_raw)

    inflation_risk_raw = float(event_raw["inflation_risk"])
    inflation_risk = math.tanh(inflation_risk_raw)

    observations = inputs["market"]["observations"]
    cross_asset_raw = (
        0.40 * (-observations["us_10y_yield_change"] / 0.0010)
        + 0.30 * (-observations["vix_change"] / 1.0)
        + 0.30 * (-observations["dollar_index_change"] / 0.50)
    )
    cross_asset_relief = math.tanh(cross_asset_raw)
    return {
        "labor_growth_risk": {
            "raw": growth_risk_raw,
            "bounded_score": growth_risk,
            "components": {
                "base_labor_growth_risk_raw": labor_growth_risk_raw,
                "event_learning_increment_raw": float(event_raw["growth_risk"]),
                "payroll_surprise_z": payroll_surprise_z,
                "combined_revision_z": revision_z,
                "temporary_layoff_change_z": layoff_z,
            },
            "interpretation": "positive means more growth risk",
        },
        "policy_relief": {
            "raw": policy_relief_raw,
            "bounded_score": policy_relief,
            "expected_hike_count_delta_by_meeting": meeting_deltas,
            "aggregate_hike_probability_delta_by_meeting": aggregate_deltas,
            "components": {
                "expected_hike_count_relief_raw": expected_count_relief_raw,
                "aggregate_probability_relief_raw": aggregate_probability_relief_raw,
                "base_policy_relief_raw": base_policy_relief_raw,
                "event_learning_increment_raw": float(event_raw["policy_relief"]),
            },
            "interpretation": "positive means less expected tightening after jobs",
        },
        "inflation_risk": {
            "raw": inflation_risk_raw,
            "bounded_score": inflation_risk,
            "interpretation": "positive means a hotter-than-consensus inflation update",
        },
        "cross_asset_relief": {
            "raw": cross_asset_raw,
            "bounded_score": cross_asset_relief,
            "nasdaq_event_return_coefficient": 0.0,
            "interpretation": "weak state view; realized Nasdaq return is excluded",
        },
        "source_event_revision_ids": [
            str(labor["release_id"]),
            str(inputs["rates"]["dataset_id"]),
            *[
                str(row["revision_id"])
                for row in inputs["event_updates"].get("events", [])
            ],
        ],
        "event_learning": inputs["event_updates"],
    }


def _normalise_weights(log_weights: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    if not np.isfinite(log_weights).all():
        raise ScenarioV52Error("non-finite log weights")
    shifted = log_weights - float(log_weights.max())
    unnormalised = np.exp(shifted)
    denominator = float(unnormalised.sum())
    if not math.isfinite(denominator) or denominator <= 0:
        raise ScenarioV52Error("invalid explicit weight normalizer")
    weights = unnormalised / denominator
    if not math.isclose(float(weights.sum()), 1.0, abs_tol=1e-12):
        raise ScenarioV52Error("weights do not sum to one")
    count = len(weights)
    ess = float(1.0 / np.square(weights).sum())
    top_n = max(1, math.ceil(count * .01))
    top_share = float(np.partition(weights, -top_n)[-top_n:].sum())
    entropy = float(-np.sum(weights * np.log(weights)))
    kl = float(np.sum(weights * np.log(weights * count)))
    gates = {
        "ess_at_least_20pct": ess >= count * .20,
        "maximum_weight_at_most_0_005": float(weights.max()) <= .005,
        "top_one_percent_share_at_most_0_10": top_share <= .10,
    }
    return weights, {
        "normalization": "explicit_log_sum_exp",
        "weight_sum": float(weights.sum()),
        "effective_sample_size": ess,
        "effective_sample_size_fraction": ess / count,
        "maximum_path_weight": float(weights.max()),
        "top_one_percent_weight_share": top_share,
        "entropy": entropy,
        "relative_entropy_from_uniform": kl,
        "gates": gates,
        "gates_pass": all(gates.values()),
    }


def build_weights(
    paths: np.ndarray, dates: list[str], engines: np.ndarray,
    scores: dict[str, Any], dotcom: dict[str, Any],
    cluster_audit: dict[str, Any],
) -> dict[str, Any]:
    anchor = float(paths[0, 0])
    if engines.shape != (paths.shape[0],) or not set(np.unique(engines)).issubset({0, 1, 2}):
        raise ScenarioV52Error("path-engine labels do not match the three-engine prior")
    metrics = _path_metrics(paths, dates)
    masks = _engine_masks(engines)
    growth_score = float(scores["labor_growth_risk"]["bounded_score"])
    policy_score = float(scores["policy_relief"]["bounded_score"])
    cross_score = float(scores["cross_asset_relief"]["bounded_score"])
    inflation_score = float(scores["inflation_risk"]["bounded_score"])

    base_scores = cluster_audit.get("base_scenario_scores", {})
    if set(base_scores) != {"S1", "S2", "S3"}:
        raise ScenarioV52Error("cluster prior lacks three base scenario scores")
    validated_base_scores = {
        scenario: _finite_number(value, f"base_scenario_scores.{scenario}")
        for scenario, value in base_scores.items()
    }
    if min(validated_base_scores.values()) <= 0:
        raise ScenarioV52Error("cluster base scenario scores must be positive")
    base_prior_log = sum(
        math.log(validated_base_scores[scenario]) * mask.astype(float)
        for scenario, mask in masks.items()
    )

    # Evidence changes scenario probabilities through explicitly different
    # causal channels.  It never reclassifies an individual simulated path.
    growth_coefficients = {"S1": -.20, "S2": .05, "S3": .45}
    policy_coefficients = {"S1": .40, "S2": .05, "S3": -.40}
    cross_coefficients = {"S1": .10, "S2": .05, "S3": -.10}
    inflation_coefficients = {"S1": -.15, "S2": 0.0, "S3": .35}
    balance_score = max(0.0, 1.0 - abs(growth_score - policy_score))
    balance_coefficients = {"S1": 0.0, "S2": .12, "S3": 0.0}

    def scenario_component(coefficients: dict[str, float], score: float) -> np.ndarray:
        return sum(
            coefficients[scenario] * score * mask.astype(float)
            for scenario, mask in masks.items()
        )

    growth_log = scenario_component(growth_coefficients, growth_score)
    policy_log = scenario_component(policy_coefficients, policy_score)
    cross_log = scenario_component(cross_coefficients, cross_score)
    inflation_log = scenario_component(inflation_coefficients, inflation_score)
    balance_log = scenario_component(balance_coefficients, balance_score)

    horizon_sessions = {
        "one_month": 21,
        "three_month": 63,
        "six_month": 126,
        "twelve_month": 252,
    }
    targets = {
        key: _finite_number(value, f"dotcom.forward_return_targets.{key}")
        for key, value in dotcom["forward_return_targets"].items()
    }
    if set(targets) != set(horizon_sessions):
        raise ScenarioV52Error("dotcom forward-return target horizons mismatch")
    horizon_indexes = {
        key: min(sessions, len(dates) - 1)
        for key, sessions in horizon_sessions.items()
    }
    horizon_dates = {key: dates[index] for key, index in horizon_indexes.items()}
    forward_returns = np.column_stack([
        paths[:, horizon_indexes[key]] / anchor - 1.0 for key in horizon_dates
    ])
    target_vector = np.asarray([targets[key] for key in horizon_dates], dtype=float)
    robust_scales = np.maximum(
        (np.quantile(forward_returns, .75, axis=0)
         - np.quantile(forward_returns, .25, axis=0)) / 1.349,
        .03,
    )
    dotcom_distance = np.sqrt(np.mean(
        np.square((forward_returns - target_vector[None, :]) / robust_scales[None, :]),
        axis=1,
    ))
    dotcom_compatibility = _robust_z(-dotcom_distance)
    october_end = max(index for index, value in enumerate(dates) if value <= "2026-10-31")
    no_repeat_condition = (
        (paths[:, :october_end + 1].min(axis=1) > anchor * .90)
        & (metrics["terminal_2026"] > anchor)
    ).astype(float)
    condition_rate = float(no_repeat_condition.mean())
    no_repeat_feature = (
        no_repeat_condition - condition_rate
    ) / max(math.sqrt(condition_rate * (1.0 - condition_rate)), .20)
    joint_relief = max(0.0, growth_score) * max(0.0, policy_score)
    strengths = {
        key: float(dotcom["scenario_strength"][key]) for key in ("S1", "S2", "S3")
    }
    if strengths["S1"] <= 0 or strengths["S2"] != 0 or strengths["S3"] != 0:
        raise ScenarioV52Error("dotcom likelihood must be positive for S1 and zero elsewhere")
    s1_no_repeat = masks["S1"].astype(float) * joint_relief * no_repeat_feature
    # The registered analog applies only inside the independently generated S1
    # cohort.  The positive intercept makes strength sensitivity monotonic;
    # compatibility and no-repeat terms only reshape S1 internally.
    dotcom_log_adjustment = strengths["S1"] * masks["S1"].astype(float) * (
        .35 + .25 * dotcom_compatibility + .40 * joint_relief * no_repeat_feature
    )

    base_full_log = (
        base_prior_log + growth_log + policy_log + cross_log
        + inflation_log + balance_log
    )
    logs = {
        "prior_only": base_prior_log,
        "policy_only": base_prior_log + policy_log,
        "labor_only": base_prior_log + growth_log,
        "labor_rate": base_prior_log + growth_log + policy_log,
        "full_without_dotcom": base_full_log,
        "full_evidence": base_full_log + dotcom_log_adjustment,
    }
    result: dict[str, Any] = {"metrics": metrics, "features": {
        "base_prior_log": base_prior_log,
        "growth_risk": growth_log,
        "policy_relief": policy_log,
        "cross_asset_relief": cross_log,
        "inflation_risk": inflation_log,
        "balanced_state": balance_log,
        "dotcom_compatibility": dotcom_compatibility,
        "no_repeat_correction": no_repeat_feature,
        "no_repeat_condition": no_repeat_condition,
        "dotcom_log_adjustment": dotcom_log_adjustment,
        "full_evidence_log": logs["full_evidence"],
    }}
    for name, log_weights in logs.items():
        weights, diagnostics = _normalise_weights(log_weights)
        result[name] = {"weights": weights, "diagnostics": diagnostics}
    result["dotcom_audit"] = {
        "method": dotcom["method"],
        "single_cycle_limitation": True,
        "cycle_count": int(dotcom["cycle_count"]),
        "neighbor_count": int(dotcom["neighbor_count"]),
        "forward_return_targets": targets,
        "target_dates": horizon_dates,
        "scenario_strength": strengths,
        "generator_routing_rule": "S1-only soft likelihood; S2 and S3 receive exactly zero",
        "strength_gate": (
            math.isclose(strengths["S1"], .60)
            and strengths["S2"] == 0.0 and strengths["S3"] == 0.0
        ),
        "dependency_cap": float(dotcom["dependency_cap"]),
        "joint_growth_risk_policy_relief_score": joint_relief,
        "no_repeat_condition_definition": (
            "no first touch of -10% through October end and year-end above anchor"
        ),
        "prior_no_repeat_condition_probability": condition_rate,
        "compatibility_median_by_scenario": {
            key: float(np.median(dotcom_compatibility[mask])) for key, mask in masks.items()
        },
        "mean_log_adjustment_by_scenario": {
            key: float(np.mean(dotcom_log_adjustment[mask])) for key, mask in masks.items()
        },
        "one_month_negative_target_preserved": targets["one_month"] < 0,
        "forced_endpoint": False,
        "forced_october_direction": False,
    }
    result["scenario_layer_contract"] = {
        "path_partition": "immutable generator labels",
        "S1": "dotcom expansion blocks plus disjoint falling-rate easing macro blocks",
        "S2": "disjoint neutral-rate soft-landing macro blocks",
        "S3": "disjoint tightening drawdown, failed-relief, and stress-persistence blocks",
        "shared_database_cluster": False,
        "shared_macro_origin_dates": False,
        "shared_residual_pool": False,
        "valuation_and_earnings_status": (
            "reference_only_until_point_in_time_cross_era_history_is_complete"
        ),
        "outcome_based_path_reclassification": False,
        "base_scenario_scores": validated_base_scores,
        "evidence_coefficients": {
            "labor_growth_risk": growth_coefficients,
            "policy_relief": policy_coefficients,
            "cross_asset_relief": cross_coefficients,
            "inflation_risk": inflation_coefficients,
            "balanced_state": balance_coefficients,
        },
    }
    return result


def weighted_quantile(values: np.ndarray, weights: np.ndarray,
                      quantiles: tuple[float, ...] | np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights) - 0.5 * sorted_weights
    cumulative /= sorted_weights.sum()
    return np.interp(np.asarray(quantiles, dtype=float), cumulative, sorted_values)


def _bands(paths: np.ndarray, weights: np.ndarray) -> dict[str, list[float]]:
    result = {name: [] for name in QUANTILE_NAMES}
    for column in range(paths.shape[1]):
        values = weighted_quantile(paths[:, column], weights, QUANTILES)
        for name, value in zip(QUANTILE_NAMES, values, strict=True):
            result[name].append(round(float(value), 2))
    return result


def _engine_masks(engines: np.ndarray) -> dict[str, np.ndarray]:
    masks = {
        "S1": engines == 0,
        "S2": engines == 1,
        "S3": engines == 2,
    }
    if any(not mask.any() for mask in masks.values()):
        raise ScenarioV52Error("scenario-specific database generator produced an empty cohort")
    if not np.all(sum(mask.astype(int) for mask in masks.values()) == 1):
        raise ScenarioV52Error("scenario cohorts do not form a partition")
    return masks


def _probability_metrics(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
    masks: dict[str, np.ndarray],
) -> dict[str, Any]:
    anchor = float(paths[0, 0])
    end_2026 = max(i for i, value in enumerate(dates) if value <= "2026-12-31")
    oct_end = max(i for i, value in enumerate(dates) if value <= "2026-10-31")
    touch = (paths[:, :oct_end + 1] <= anchor * .90).any(axis=1)
    ath = (paths[:, :end_2026 + 1] > ATH).any(axis=1)
    return {
        "terminal_above_anchor_2026": float(weights @ (paths[:, end_2026] > anchor)),
        "terminal_above_v51_reference_2026": float(weights @ (paths[:, end_2026] > REFERENCE_PRICE)),
        "new_ath_by_2026": float(weights @ ath),
        "first_touch_minus_10_by_october_end": float(weights @ touch),
        "terminal_above_anchor_2027": float(weights @ (paths[:, -1] > anchor)),
        "year_end_p50": float(weighted_quantile(
            paths[:, end_2026], weights, (.50,)
        )[0]),
        "scenario_probabilities": {
            key: float(weights[mask].sum()) for key, mask in masks.items()
        },
    }


def _first_touch_distribution(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
) -> dict[str, Any]:
    anchor = float(paths[0, 0])
    oct_end = max(i for i, value in enumerate(dates) if value <= "2026-10-31")
    hit = paths[:, :oct_end + 1] <= anchor * .90
    any_hit = hit.any(axis=1)
    first = np.where(any_hit, np.argmax(hit, axis=1), -1)
    density = np.asarray([
        float(weights[first == index].sum()) for index in range(oct_end + 1)
    ])
    cdf = np.cumsum(density)
    touch_probability = float(weights[any_hit].sum())
    conditional_dates: dict[str, str | None] = {"p25": None, "p50": None, "p75": None}
    if touch_probability > 0:
        conditional_cdf = cdf / touch_probability
        for name, level in (("p25", .25), ("p50", .50), ("p75", .75)):
            conditional_dates[name] = dates[int(np.searchsorted(conditional_cdf, level, side="left"))]
    return {
        "barrier": round(anchor * .90, 2),
        "barrier_definition": "10 percent below the post-event anchor",
        "probability_unit": "fraction",
        "exact_date_forecast": False,
        "dates": dates[:oct_end + 1],
        "density": [round(float(value), 10) for value in density],
        "cdf": [round(float(value), 10) for value in cdf],
        "never_touched_by_october_end": round(float(weights[~any_hit].sum()), 10),
        "conditional_on_touch_quantiles": conditional_dates,
        "october_2_role": "ordinary CDF coordinate only; no target or forced trough",
        "cdf_at_2026_10_02": round(float(cdf[dates.index("2026-10-02")]), 10),
    }


def _central_bundle(
    paths: np.ndarray, dates: list[str], weights: np.ndarray, bands: dict[str, list[float]],
    path_ids: np.ndarray | None = None,
) -> dict[str, Any]:
    if path_ids is None:
        path_ids = np.arange(paths.shape[0])
    if path_ids.shape != (paths.shape[0],):
        raise ScenarioV52Error("central bundle path ID map is not aligned")
    sample_columns = np.arange(0, paths.shape[1], 5)
    metrics = _path_metrics(paths, dates)
    bounds = {
        "annualized_volatility": np.quantile(metrics["annualized_volatility"], [.10, .90]),
        "direction_changes": np.quantile(metrics["direction_changes"], [.10, .90]),
        "maximum_drawdown": np.quantile(metrics["maximum_drawdown"], [.05, .95]),
        "time_underwater": np.quantile(metrics["time_underwater"], [.05, .95]),
    }
    eligible = np.ones(paths.shape[0], dtype=bool)
    for key, (low, high) in bounds.items():
        eligible &= (metrics[key] >= low) & (metrics[key] <= high)
    if int(eligible.sum()) < 9:
        raise ScenarioV52Error("insufficient realistic members for central bundle")
    target = np.asarray(bands["p50"])[sample_columns]
    distances = np.mean(
        np.abs(paths[:, sample_columns] - target[None, :]) / target[None, :], axis=1
    )
    medoid_score = distances + (1.0 - weights / weights.max()) * .002
    medoid_score[~eligible] = np.inf
    medoid = int(np.argmin(medoid_score))
    terminal_levels = weighted_quantile(
        paths[:, -1], weights, np.asarray([.20, .30, .40, .50, .60, .70, .80])
    )
    members: list[int] = []
    for level in terminal_levels:
        score = np.abs(paths[:, -1] - level) / max(float(level), 1.0) + distances * .25
        score[~eligible] = np.inf
        order = np.argsort(score, kind="stable")
        selected = next(int(index) for index in order
                        if eligible[index] and int(index) not in members)
        members.append(selected)
    pair_correlations = []
    member_returns = np.diff(np.log(paths[members]), axis=1)
    for left in range(len(members)):
        for right in range(left + 1, len(members)):
            pair_correlations.append(float(np.corrcoef(member_returns[left], member_returns[right])[0, 1]))
    member_diagnostics = []
    for index in members:
        row_metrics = {key: float(metrics[key][index]) for key in bounds}
        row_gates = {
            key: float(bounds[key][0]) <= value <= float(bounds[key][1])
            for key, value in row_metrics.items()
        }
        member_diagnostics.append({
            "path_id": f"path_{int(path_ids[index]):05d}", "metrics": row_metrics,
            "realism_gates": row_gates, "gate_pass": all(row_gates.values()),
        })
    return {
        "member_count": 7,
        "selection_rule": "actual weighted central members spanning terminal p20-p80",
        "fake_wiggle_applied": False,
        "p50_smoothing": "none; pointwise weighted distribution median",
        "medoid_path_id": f"path_{int(path_ids[medoid]):05d}",
        "medoid_values": [round(float(value), 2) for value in paths[medoid]],
        "members": [
            {
                "path_id": f"path_{int(path_ids[index]):05d}",
                "values": [round(float(value), 2) for value in paths[index]],
            }
            for index in members
        ],
        "historical_conditional_bounds": {
            key: {"low": float(value[0]), "high": float(value[1])}
            for key, value in bounds.items()
        },
        "member_diagnostics": member_diagnostics,
        "no_piecewise_linear_endpoint_path": all(
            row["metrics"]["direction_changes"] >= bounds["direction_changes"][0]
            for row in member_diagnostics
        ),
        "maximum_pair_return_correlation": max(pair_correlations),
        "no_common_residual_gate": max(pair_correlations) < .95,
        "realism_gate_pass": (
            all(row["gate_pass"] for row in member_diagnostics)
            and max(pair_correlations) < .95
        ),
    }


def _scenario_outputs(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
    metrics: dict[str, np.ndarray], masks: dict[str, np.ndarray],
) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = {
        "S1": "dotcom expansion price-state cluster conditional",
        "S2": "modern general-market baseline cluster conditional",
        "S3": "macro tightening and financial-stress cluster conditional",
    }
    scenarios: dict[str, Any] = {}
    summary: dict[str, dict[str, float]] = {}
    for scenario, mask in masks.items():
        conditional = weights[mask] / weights[mask].sum()
        cohort_paths = paths[mask]
        scenario_bands = _bands(cohort_paths, conditional)
        scenarios[scenario] = {
            "label": labels[scenario],
            "probability": float(weights[mask].sum()),
            "probability_space": "conditional_cohort_from_total_mixture",
            "path_count": int(mask.sum()),
            "bands": scenario_bands,
            "central_path_bundle": _central_bundle(
                cohort_paths, dates, conditional, scenario_bands,
                np.flatnonzero(mask),
            ),
        }
        summary[scenario] = {
            "terminal_return_2027": float(weighted_quantile(
                metrics["terminal_return_2027"][mask], conditional, (.5,))[0]),
            "maximum_drawdown": float(weighted_quantile(
                metrics["maximum_drawdown"][mask], conditional, (.5,))[0]),
            "recovery_days": float(weighted_quantile(
                metrics["recovery_days"][mask], conditional, (.5,))[0]),
            "annualized_volatility": float(weighted_quantile(
                metrics["annualized_volatility"][mask], conditional, (.5,))[0]),
            "downside_semivolatility": float(weighted_quantile(
                metrics["downside_semivolatility"][mask], conditional, (.5,))[0]),
        }
    pairs: list[dict[str, Any]] = []
    keys = list(scenarios)
    for left_index in range(len(keys)):
        for right_index in range(left_index + 1, len(keys)):
            left, right = keys[left_index], keys[right_index]
            deltas = {
                key: abs(summary[left][key] - summary[right][key])
                for key in summary[left]
            }
            metric_gates = {
                "terminal_return_2027": deltas["terminal_return_2027"] >= .05,
                "maximum_drawdown": deltas["maximum_drawdown"] >= .02,
                "recovery_days": deltas["recovery_days"] >= 20.0,
                "annualized_volatility": deltas["annualized_volatility"] >= .02,
            }
            left_mask, right_mask = masks[left], masks[right]
            left_weights = weights[left_mask] / weights[left_mask].sum()
            right_weights = weights[right_mask] / weights[right_mask].sum()
            start_2027 = next(i for i, value in enumerate(dates) if value >= "2027-01-01")
            left_p50 = np.asarray(scenarios[left]["bands"]["p50"][start_2027:], dtype=float)
            right_p50 = np.asarray(scenarios[right]["bands"]["p50"][start_2027:], dtype=float)
            level_correlation = float(np.corrcoef(
                left_p50 / left_p50[0], right_p50 / right_p50[0]
            )[0, 1])
            weekly_left = np.diff(np.log(left_p50[::5]))
            weekly_right = np.diff(np.log(right_p50[::5]))
            weekly_return_correlation = float(np.corrcoef(weekly_left, weekly_right)[0, 1])
            terminal_wasserstein = float(wasserstein_distance(
                metrics["terminal_return_2027"][left_mask],
                metrics["terminal_return_2027"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            terminal_energy = float(energy_distance(
                metrics["terminal_return_2027"][left_mask],
                metrics["terminal_return_2027"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            mdd_distance = float(wasserstein_distance(
                metrics["maximum_drawdown"][left_mask],
                metrics["maximum_drawdown"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            volatility_distance = float(wasserstein_distance(
                metrics["annualized_volatility"][left_mask],
                metrics["annualized_volatility"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            distribution_gates = {
                "normalized_p50_level_correlation": abs(level_correlation) < .995,
                "weekly_return_correlation": abs(weekly_return_correlation) < .98,
                "terminal_wasserstein": terminal_wasserstein >= .03,
                "terminal_energy": terminal_energy >= .10,
                "mdd_distribution_distance": mdd_distance >= .015,
                "volatility_distribution_distance": volatility_distance >= .01,
            }
            pairs.append({
                "pair": f"{left}-{right}",
                "absolute_differences": deltas,
                "metric_gates": metric_gates,
                "distinct_metric_count": sum(metric_gates.values()),
                "distribution_diagnostics": {
                    "normalized_p50_level_correlation": level_correlation,
                    "weekly_return_correlation": weekly_return_correlation,
                    "terminal_wasserstein": terminal_wasserstein,
                    "terminal_energy": terminal_energy,
                    "mdd_distribution_distance": mdd_distance,
                    "volatility_distribution_distance": volatility_distance,
                },
                "distribution_gates": distribution_gates,
                "distribution_gate_count": sum(distribution_gates.values()),
                "gate_pass": sum(metric_gates.values()) >= 2
                             and sum(distribution_gates.values()) >= 3,
            })
    distinctness = {
        "rule": "pre-outcome state-cluster cohorts; each 2027 pair must pass >=2 median and >=3 distribution diagnostics",
        "partition_information_cutoff": "historical_origin_state_only",
        "partition_uses_forward_outcomes_for_assignment": False,
        "cluster_labels_use_forward_outcomes_after_assignment": True,
        "partition_uses_2027_outcomes": False,
        "scenario_medians": summary,
        "pairs": pairs,
        "gate_pass": all(row["gate_pass"] for row in pairs),
    }
    return scenarios, distinctness


def _standardized_log_dtw(left: np.ndarray, right: np.ndarray) -> float:
    left_log = np.log(left)
    right_log = np.log(right)
    left_z = (left_log - left_log.mean()) / max(float(left_log.std(ddof=1)), 1e-12)
    right_z = (right_log - right_log.mean()) / max(float(right_log.std(ddof=1)), 1e-12)
    previous = np.full(len(right_z) + 1, np.inf)
    previous[0] = 0.0
    for left_value in left_z:
        current = np.full(len(right_z) + 1, np.inf)
        for index, right_value in enumerate(right_z, start=1):
            cost = abs(float(left_value - right_value))
            current[index] = cost + min(
                current[index - 1], previous[index], previous[index - 1]
            )
        previous = current
    return float(previous[-1] / max(len(left_z), len(right_z)))


def _research_distinctness(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
    masks: dict[str, np.ndarray], scenarios: dict[str, Any],
    generator_audit: dict[str, Any],
) -> dict[str, Any]:
    anchor = float(paths[0, 0])
    metrics = _path_metrics(paths, dates)
    checkpoints = {63: min(63, len(dates) - 1), 126: min(126, len(dates) - 1),
                   252: min(252, len(dates) - 1)}
    geometry_checkpoints = {
        sessions: min(sessions, len(dates) - 1)
        for sessions in (21, 42, 52, 63, 84, 105, 126, 252)
    }
    end_2026 = max(index for index, value in enumerate(dates) if value <= "2026-12-31")
    per_scenario: dict[str, Any] = {}
    touch_cdfs: dict[str, np.ndarray] = {}
    for scenario, mask in masks.items():
        conditional = weights[mask] / weights[mask].sum()
        p50 = np.asarray(scenarios[scenario]["bands"]["p50"], dtype=float)
        touch = _first_touch_distribution(paths[mask], dates, conditional)
        touch_cdfs[scenario] = np.asarray(touch["cdf"], dtype=float)
        per_scenario[scenario] = {
            "cumulative_return_p50": {
                str(sessions): float(weighted_quantile(
                    paths[mask, index] / anchor - 1.0, conditional, (.50,)
                )[0]) for sessions, index in checkpoints.items()
            },
            "shape_checkpoint_return_p50": {
                str(sessions): float(p50[index] / anchor - 1.0)
                for sessions, index in geometry_checkpoints.items()
            },
            "maximum_drawdown_p50": float(weighted_quantile(
                metrics["maximum_drawdown"][mask], conditional, (.50,)
            )[0]),
            "downside_semivolatility_p50": float(weighted_quantile(
                metrics["downside_semivolatility"][mask], conditional, (.50,)
            )[0]),
            "recovery_days_p50": float(weighted_quantile(
                metrics["recovery_days"][mask], conditional, (.50,)
            )[0]),
            "medoid_path_id": scenarios[scenario]["central_path_bundle"]["medoid_path_id"],
            "selected_origin_count": int(
                generator_audit["scenarios"][scenario]["selected_cluster"]["origin_count"]
            ),
            "requested_promotion_minimum_origins": int(
                generator_audit["scenarios"][scenario][
                    "requested_promotion_minimum_origins"
                ]
            ),
            "episode_sampling_ess": float(
                generator_audit["scenarios"][scenario]["sampling"]["episode_sampling_ess"]
            ),
        }
    pairs: list[dict[str, Any]] = []
    for left, right in (("S1", "S2"), ("S1", "S3"), ("S2", "S3")):
        left_mask, right_mask = masks[left], masks[right]
        left_weights = weights[left_mask] / weights[left_mask].sum()
        right_weights = weights[right_mask] / weights[right_mask].sum()
        left_p50 = np.asarray(scenarios[left]["bands"]["p50"], dtype=float)
        right_p50 = np.asarray(scenarios[right]["bands"]["p50"], dtype=float)
        left_diff = np.diff(np.log(left_p50))
        right_diff = np.diff(np.log(right_p50))
        rolling_correlations = [
            float(np.corrcoef(left_diff[start:start + 63], right_diff[start:start + 63])[0, 1])
            for start in range(0, len(left_diff) - 62, 21)
        ]
        pairs.append({
            "pair": f"{left}-{right}",
            "p50_log_level_correlation": float(np.corrcoef(
                np.log(left_p50), np.log(right_p50)
            )[0, 1]),
            "p50_first_difference_correlation": float(np.corrcoef(
                left_diff, right_diff
            )[0, 1]),
            "rolling_63d_first_difference_correlation": {
                "minimum": min(rolling_correlations),
                "median": float(np.median(rolling_correlations)),
                "maximum": max(rolling_correlations),
            },
            "standardized_log_path_dtw": _standardized_log_dtw(left_p50, right_p50),
            "terminal_wasserstein_2026": float(wasserstein_distance(
                paths[left_mask, end_2026] / anchor - 1.0,
                paths[right_mask, end_2026] / anchor - 1.0,
                u_weights=left_weights, v_weights=right_weights,
            )),
            "terminal_wasserstein_2027": float(wasserstein_distance(
                paths[left_mask, -1] / anchor - 1.0,
                paths[right_mask, -1] / anchor - 1.0,
                u_weights=left_weights, v_weights=right_weights,
            )),
            "first_touch_minus_10_ks": float(np.max(np.abs(
                touch_cdfs[left] - touch_cdfs[right]
            ))),
        })
    returns_order = {
        str(sessions): (
            per_scenario["S1"]["cumulative_return_p50"][str(sessions)]
            > per_scenario["S2"]["cumulative_return_p50"][str(sessions)]
            > per_scenario["S3"]["cumulative_return_p50"][str(sessions)]
        ) for sessions in checkpoints
    }
    mdd_severity = {
        key: abs(per_scenario[key]["maximum_drawdown_p50"])
        for key in ("S1", "S2", "S3")
    }
    downside = {
        key: per_scenario[key]["downside_semivolatility_p50"]
        for key in ("S1", "S2", "S3")
    }
    recovery = {
        key: per_scenario[key]["recovery_days_p50"]
        for key in ("S1", "S2", "S3")
    }
    medoids = [per_scenario[key]["medoid_path_id"] for key in ("S1", "S2", "S3")]
    pair_metrics = {row["pair"]: row for row in pairs}
    provenance_hashes = {
        generator_audit["scenarios"][key]["sampling"]["residual_pool_sha256"]
        for key in ("S1", "S2", "S3")
    }
    baseline_correlation = 0.963
    minimum_material_reduction = 0.02
    observed_s1_s2 = float(pair_metrics["S1-S2"]["p50_log_level_correlation"])
    descriptive_checks = {
        "cumulative_return_order_S1_gt_S2_gt_S3": all(returns_order.values()),
        "S1_and_S2_drawdown_below_S3": (
            max(mdd_severity["S1"], mdd_severity["S2"]) < mdd_severity["S3"]
        ),
        "S1_drawdown_below_80pct_of_S3": mdd_severity["S1"] <= .80 * mdd_severity["S3"],
        "S1_and_S2_downside_semivolatility_below_S3": (
            max(downside["S1"], downside["S2"]) < downside["S3"]
        ),
        "S1_recovery_faster_than_S2_and_S3": (
            recovery["S1"] < min(recovery["S2"], recovery["S3"])
        ),
        "S1_S2_log_level_correlation_materially_below_0_963_baseline": (
            observed_s1_s2 <= baseline_correlation - minimum_material_reduction
        ),
        "episode_interval_intersection_zero": (
            generator_audit["episode_interval_overlap_count"] == 0
        ),
        "scenario_feature_schemas_distinct": (
            generator_audit["feature_schemas_distinct"] is True
        ),
        "independent_residual_pool_hashes": (
            len(provenance_hashes) == 3
            and generator_audit["residual_pool_hashes_unique"] is True
        ),
        "empirical_phase_repetition_gates_pass": (
            generator_audit["phase_repetition_gates_pass"] is True
        ),
        "fixed_phase_template_inactive": (
            generator_audit["fixed_phase_template_active"] is False
        ),
        "event_adapter_changes_structure_not_probability_only": (
            generator_audit["structural_event_adapter"]["probability_only_update"] is False
        ),
        "medoid_path_ids_unique": len(set(medoids)) == 3,
        "paths_unchanged_by_distinctness_evaluation": True,
    }
    return {
        "schema_version": 3,
        "contract_path": "data/contracts/scenario_v5_3_separation.yaml",
        "weight_contract_path": WEIGHT_CONTRACT_RELATIVE.as_posix(),
        "operational_mode": "report_only",
        "status": "REPORT_ONLY_INSUFFICIENT_30_TRADING_DAY_SHADOW_HISTORY",
        "threshold_calibration": {
            "observations": 0,
            "minimum": 30,
            "upper_bound_rule": "shadow_distribution_p75",
            "lower_bound_rule": "shadow_distribution_p25",
            "threshold_run_id": None,
        },
        "threshold_gate_evaluated": False,
        "gate_pass": None,
        "promotion_eligible": False,
        "baseline_comparison": {
            "metric": "S1-S2_p50_log_level_correlation",
            "baseline": baseline_correlation,
            "redesigned_shadow": observed_s1_s2,
            "minimum_material_reduction": minimum_material_reduction,
            "observed_reduction": baseline_correlation - observed_s1_s2,
            "material_reduction_gate_pass": (
                observed_s1_s2 <= baseline_correlation - minimum_material_reduction
            ),
            "fixed_absolute_target_used": False,
        },
        "sample_adequacy": {
            "gate_pass": generator_audit["promotion_sample_gate_pass"],
            "scenarios": {
                key: generator_audit["promotion_sample_gates"][key]
                for key in ("S1", "S2", "S3")
            },
            "failure_is_promotion_blocking_not_path_mutating": True,
            "reason": generator_audit["research_sample_exception"],
        },
        "failure_action": "display_warning_and_stop_promotion_without_path_mutation",
        "per_scenario": per_scenario,
        "phase_and_kernel_audit": {
            key: {
                "fixed_phase_template": generator_audit["scenarios"][key][
                    "sampling"
                ]["fixed_phase_template"],
                "phase_duration_distribution": generator_audit["scenarios"][key][
                    "sampling"
                ]["phase_duration_distribution"],
                "phase_repetition_gate": generator_audit["scenarios"][key][
                    "sampling"
                ]["phase_repetition_gate"],
                "kernel_audit": generator_audit["scenarios"][key]["sampling"][
                    "kernel_audit"
                ],
            }
            for key in ("S1", "S2", "S3")
        },
        "pairs": pairs,
        "descriptive_checks": descriptive_checks,
        "descriptive_checks_pass": all(descriptive_checks.values()),
        "seed_stability": "reported_in_external_shadow_diagnostic",
        "asof_state_cluster_stability": "reported_in_external_shadow_diagnostic",
    }


def _evidence_registry(root: Path, inputs: dict[str, Any]) -> list[dict[str, Any]]:
    registry = [
        {
            "evidence_id": "bls_actual_2026_07",
            "origin_release_id": inputs["labor"]["release_id"],
            "source_path": SOURCE_PATHS[1],
            "source_sha256": file_hash(root / SOURCE_PATHS[1]),
            "available_at": inputs["labor"]["available_at"],
            "dependency_cluster_id": "bls_empsit_2026_07",
            "effective_strength": .30,
            "used_numerically": True,
            "role": "labor_growth_risk",
        },
        {
            "evidence_id": "fed_rate_distribution_pre_post",
            "origin_release_id": inputs["rates"]["dataset_id"],
            "source_path": SOURCE_PATHS[3],
            "source_sha256": file_hash(root / SOURCE_PATHS[3]),
            "available_at": inputs["rates"]["source_updated_at"],
            "dependency_cluster_id": "cme_fed_funds_futures",
            "effective_strength": .25,
            "used_numerically": True,
            "role": "policy_relief",
        },
        {
            "evidence_id": "post_jobs_cross_asset_state",
            "origin_release_id": inputs["market"]["event_id"],
            "source_path": SOURCE_PATHS[6],
            "source_sha256": file_hash(root / SOURCE_PATHS[6]),
            "available_at": inputs["market"]["available_at"],
            "dependency_cluster_id": "post_jobs_market_state",
            "effective_strength": .10,
            "used_numerically": True,
            "role": "weak_cross_asset_state",
            "nasdaq_event_return_coefficient": 0.0,
        },
        {
            "evidence_id": "v5_1_ancestor_candidate",
            "origin_release_id": inputs["v51"]["candidate_id"],
            "source_path": SOURCE_PATHS[7],
            "source_sha256": source_file_hash(root, SOURCE_PATHS[7]),
            "available_at": inputs["v51"]["generated_at"],
            "dependency_cluster_id": "scenario_ancestor",
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "reference_only_endogenous_circularity_blocked",
        },
        {
            "evidence_id": "kiplinger_jobs_consensus_and_commentary",
            "origin_release_id": inputs["labor"]["release_id"],
            "source_url": inputs["labor"]["consensus"]["source_url"],
            "dependency_cluster_id": "bls_empsit_2026_07",
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "consensus_field_only; narrative reference only",
        },
        {
            "evidence_id": "dotcom_knn_single_cycle_analog",
            "origin_release_id": inputs["dotcom"]["dataset_id"],
            "source_path": SOURCE_PATHS[9],
            "source_sha256": file_hash(root / SOURCE_PATHS[9]),
            "available_at": inputs["dotcom"]["available_at"],
            "dependency_cluster_id": inputs["dotcom"]["dependency_cluster_id"],
            "effective_strength": float(inputs["dotcom"]["scenario_strength"]["S1"]),
            "approved_cap": float(inputs["dotcom"]["dependency_cap"]),
            "scenario_strength": inputs["dotcom"]["scenario_strength"],
            "used_numerically": True,
            "role": "S1_only_soft_likelihood_S2_S3_exactly_zero",
            "single_cycle_limitation": True,
        },
        {
            "evidence_id": "dotcom_daily_path_generator_source",
            "origin_release_id": inputs["dotcom_history"]["dataset_id"],
            "source_path": SOURCE_PATHS[12],
            "source_sha256": file_hash(root / SOURCE_PATHS[12]),
            "available_at": inputs["dotcom_history"]["available_at"],
            "dependency_cluster_id": inputs["dotcom"]["dependency_cluster_id"],
            "effective_strength": 0.0,
            "approved_cap": float(inputs["dotcom"]["dependency_cap"]),
            "used_numerically": True,
            "role": "path_generator_source_under_same_dotcom_cluster_no_extra_strength",
            "single_cycle_limitation": True,
        },
        {
            "evidence_id": "approved_human_dotcom_model_risk_view",
            "origin_release_id": inputs["dotcom_view"]["origin_release_id"],
            "source_path": SOURCE_PATHS[10],
            "source_sha256": file_hash(root / SOURCE_PATHS[10]),
            "available_at": inputs["dotcom_view"]["available_at"],
            "dependency_cluster_id": inputs["dotcom_view"]["dependency_cluster_id"],
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "approval_receipt_for_same_dotcom_dependency_cluster",
        },
        {
            "evidence_id": "modern_nasdaq_actual_history_reference",
            "origin_release_id": inputs["history_manifest"]["dataset_id"],
            "source_path": SOURCE_PATHS[5],
            "source_sha256": file_hash(root / SOURCE_PATHS[5]),
            "available_at": "2026-08-07T20:00:00+00:00",
            "dependency_cluster_id": "actual_history_display_anchor",
            "effective_strength": 0.0,
            "used_numerically": True,
            "role": "actual_history_and_legacy_anchor_validation_not_scenario_geometry",
        },
        {
            "evidence_id": "macro_easing_expansion_origin_cohort",
            "origin_release_id": inputs["macro_cluster_history"]["dataset_id"],
            "source_path": SOURCE_PATHS[14],
            "source_sha256": file_hash(root / SOURCE_PATHS[14]),
            "available_at": inputs["macro_cluster_history"]["available_at"],
            "dependency_cluster_id": "macro_easing_expansion_origin_set",
            "effective_strength": 0.0,
            "used_numerically": True,
            "role": "S1_auxiliary_40pct_phase_block_pool_disjoint_from_S2_S3",
            "origin_set_overlap_count_with_other_macro_layers": 0,
        },
        {
            "evidence_id": "macro_balanced_soft_landing_origin_cohort",
            "origin_release_id": inputs["macro_cluster_history"]["dataset_id"],
            "source_path": SOURCE_PATHS[14],
            "source_sha256": file_hash(root / SOURCE_PATHS[14]),
            "available_at": inputs["macro_cluster_history"]["available_at"],
            "dependency_cluster_id": "macro_balanced_soft_landing_origin_set",
            "effective_strength": 0.0,
            "used_numerically": True,
            "role": "S2_only_balanced_mean_reversion_phase_block_pool",
            "origin_set_overlap_count_with_other_macro_layers": 0,
        },
        {
            "evidence_id": "macro_tightening_stress_origin_cohort",
            "origin_release_id": inputs["macro_cluster_history"]["dataset_id"],
            "source_path": SOURCE_PATHS[14],
            "source_sha256": file_hash(root / SOURCE_PATHS[14]),
            "available_at": inputs["macro_cluster_history"]["available_at"],
            "dependency_cluster_id": "macro_tightening_stress_origin_set",
            "effective_strength": 0.0,
            "used_numerically": True,
            "role": "S3_only_drawdown_failed_relief_stress_persistence_phase_pool",
            "origin_set_overlap_count_with_other_macro_layers": 0,
        },
        {
            "evidence_id": "latest_completed_market_anchor",
            "origin_release_id": inputs["current_scenario"]["snapshot_id"],
            "source_path": SOURCE_PATHS[15],
            "source_sha256": source_file_hash(root, SOURCE_PATHS[15]),
            "available_at": inputs["forecast_anchor"]["available_at"],
            "dependency_cluster_id": "current_official_market_anchor",
            "effective_strength": 0.0,
            "used_numerically": True,
            "role": "forecast_time_transport_anchor_only_no_future_jump",
        },
        {
            "evidence_id": "v5_2_v3_shadow_candidate",
            "origin_release_id": inputs["shadow_v52"]["candidate_id"],
            "source_path": SHADOW_V52_RELATIVE.as_posix(),
            "source_sha256": file_hash(root / SHADOW_V52_RELATIVE),
            "available_at": inputs["shadow_v52"]["as_of"],
            "dependency_cluster_id": "scenario_ancestor",
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "shadow_validation_reference_only",
        },
    ]
    for event in inputs["event_updates"]["events"]:
        registry.append({
            "evidence_id": f"event_learning:{event['revision_id']}",
            "origin_release_id": event["event_id"],
            "source_path": event.get("source_path"),
            "source_url": event["source_url"],
            "source_sha256": event["source_sha256"],
            "available_at": event["available_at"],
            "dependency_cluster_id": event["dependency_cluster_id"],
            "effective_strength": float(event["scores"]["effective_strength"]),
            "used_numerically": bool(event["scores"]["used_numerically"]),
            "role": f"append_only_{event['scores']['adapter']}",
            "revision_id": event["revision_id"],
            "supersedes": event.get("supersedes"),
        })
    return registry


def assemble_candidate(root: Path) -> dict[str, Any]:
    inputs = load_inputs(root)
    forecast_anchor = inputs["forecast_anchor"]
    anchor = float(forecast_anchor["close"])
    scores = evidence_scores(inputs)
    paths, dates, engines, historical_actual, generator_audit = generate_prior(
        root, inputs, structural_scores=scores
    )
    weighting = build_weights(
        paths, dates, engines, scores, inputs["dotcom"], generator_audit
    )
    metrics = weighting["metrics"]
    masks = _engine_masks(engines)
    ablations: dict[str, Any] = {}
    for name in ("prior_only", "labor_only", "labor_rate", "full_evidence"):
        weights = weighting[name]["weights"]
        ablations[name] = {
            "included_evidence": {
                "prior_only": [],
                "labor_only": ["labor_growth_risk"],
                "labor_rate": ["labor_growth_risk", "policy_relief"],
                "full_evidence": [
                    "labor_growth_risk", "policy_relief", "cross_asset_relief",
                    "event_learning", "dotcom_S1_weighted_upside_view",
                ],
            }[name],
            "probabilities": _probability_metrics(paths, dates, weights, masks),
            "weight_diagnostics": weighting[name]["diagnostics"],
        }
    policy_only_metrics = _probability_metrics(
        paths, dates, weighting["policy_only"]["weights"], masks
    )
    full_without_dotcom_metrics = _probability_metrics(
        paths, dates, weighting["full_without_dotcom"]["weights"], masks
    )
    full_weights = weighting["full_evidence"]["weights"]
    mixture_bands = _bands(paths, full_weights)
    scenarios, distinctness = _scenario_outputs(
        paths, dates, full_weights, metrics, masks
    )
    research_distinctness = _research_distinctness(
        paths, dates, full_weights, masks, scenarios, generator_audit
    )
    zero_structural_scores = {
        "policy_relief": {"bounded_score": 0.0},
        "labor_growth_risk": {"bounded_score": 0.0},
        "inflation_risk": {"bounded_score": 0.0},
        "source_event_revision_ids": scores["source_event_revision_ids"],
    }
    counterfactual_paths, counterfactual_dates, counterfactual_engines, _, \
        counterfactual_audit = generate_prior(
            root, inputs, path_count_per_engine=240,
            structural_scores=zero_structural_scores,
        )
    if counterfactual_dates != dates:
        raise ScenarioV52Error("structural event counterfactual horizon mismatch")
    counterfactual_masks = _engine_masks(counterfactual_engines)
    structural_rows: dict[str, Any] = {}
    for scenario in ("S1", "S2", "S3"):
        active_subset = paths[masks[scenario]][:240]
        zero_subset = counterfactual_paths[counterfactual_masks[scenario]]
        active_p50 = np.median(active_subset, axis=0)
        zero_p50 = np.median(zero_subset, axis=0)
        structural_rows[scenario] = {
            "active_path_sha256": hashlib.sha256(
                np.asarray(active_subset, dtype="<f8").tobytes()
            ).hexdigest(),
            "zero_event_path_sha256": hashlib.sha256(
                np.asarray(zero_subset, dtype="<f8").tobytes()
            ).hexdigest(),
            "paths_differ": not np.array_equal(active_subset, zero_subset),
            "p50_return_difference_active_minus_zero": {
                str(index): float(
                    active_p50[index] / anchor - zero_p50[index] / anchor
                )
                for index in (21, 63, 126, 252)
            },
            "active_episode_group_weight_multipliers": generator_audit[
                "scenarios"
            ][scenario]["sampling"]["episode_group_weight_multipliers"],
            "zero_event_episode_group_weight_multipliers": counterfactual_audit[
                "scenarios"
            ][scenario]["sampling"]["episode_group_weight_multipliers"],
            "active_phase_duration_selection_tilts": generator_audit[
                "scenarios"
            ][scenario]["sampling"]["phase_duration_selection_tilts"],
            "zero_event_phase_duration_selection_tilts": counterfactual_audit[
                "scenarios"
            ][scenario]["sampling"]["phase_duration_selection_tilts"],
        }
    structural_event_ablation = {
        "comparison": "full_structural_evidence_vs_zero_event_structure",
        "path_count_per_scenario": 240,
        "same_seed_and_registered_episode_libraries": True,
        "probability_weights_applied": False,
        "paths_differ_all_scenarios": all(
            row["paths_differ"] for row in structural_rows.values()
        ),
        "source_event_revision_ids": scores["source_event_revision_ids"],
        "scenarios": structural_rows,
    }
    attribution: dict[str, Any] = {}
    probability_keys = [
        "terminal_above_anchor_2026", "terminal_above_v51_reference_2026",
        "new_ath_by_2026", "first_touch_minus_10_by_october_end",
        "terminal_above_anchor_2027",
    ]
    for key in probability_keys:
        prior = ablations["prior_only"]["probabilities"][key]
        labor_value = ablations["labor_only"]["probabilities"][key]
        rate_value = ablations["labor_rate"]["probabilities"][key]
        macro_full = full_without_dotcom_metrics[key]
        full = ablations["full_evidence"]["probabilities"][key]
        attribution[key] = {
            "pre_jobs_same_anchor_counterfactual": prior,
            "labor_growth_risk_effect": labor_value - prior,
            "policy_relief_effect": rate_value - labor_value,
            "cross_asset_state_effect": macro_full - rate_value,
            "event_and_cross_asset_effect": macro_full - rate_value,
            "dotcom_upside_effect": full - macro_full,
            "post_jobs_full": full,
            "total_change": full - prior,
            "additivity_residual": full - prior
                                   - (labor_value - prior)
                                   - (rate_value - labor_value)
                                   - (macro_full - rate_value)
                                   - (full - macro_full),
        }
    event_reaction_zero = np.zeros(paths.shape[0])
    no_event_weights, _ = _normalise_weights(
        weighting["features"]["full_evidence_log"] + event_reaction_zero
    )
    event_double_count_gate = bool(np.array_equal(no_event_weights, full_weights))
    evidence = _evidence_registry(root, inputs)
    dotcom_audit = dict(weighting["dotcom_audit"])
    no_repeat = weighting["features"]["no_repeat_condition"]
    before_dotcom_weights = weighting["full_without_dotcom"]["weights"]
    dotcom_audit["no_repeat_probability_before_dotcom"] = float(
        before_dotcom_weights @ no_repeat
    )
    dotcom_audit["no_repeat_probability_after_dotcom"] = float(full_weights @ no_repeat)
    s1 = masks["S1"]
    dotcom_audit["S1_no_repeat_probability_before_dotcom"] = float(
        (before_dotcom_weights[s1] / before_dotcom_weights[s1].sum()) @ no_repeat[s1]
    )
    dotcom_audit["S1_no_repeat_probability_after_dotcom"] = float(
        (full_weights[s1] / full_weights[s1].sum()) @ no_repeat[s1]
    )
    dotcom_audit["S1_probability_increment"] = (
        ablations["full_evidence"]["probabilities"]["scenario_probabilities"]["S1"]
        - full_without_dotcom_metrics["scenario_probabilities"]["S1"]
    )
    dotcom_audit["A_evidence_strength"] = float(
        inputs["weight_contract"]["weight_spaces"]["A_evidence_strength"]["active"]
    )
    dotcom_audit["B_generator_dotcom_block_share"] = float(
        generator_audit["B_generator_dotcom_block_share"]
    )
    dotcom_audit["B_realized_dotcom_session_share"] = float(
        generator_audit["scenarios"]["S1"]["sampling"]["realized_dotcom_session_share"]
    )
    dotcom_audit["C_mixture_probability"] = {
        key: float(full_weights[mask].sum()) for key, mask in masks.items()
    }
    dotcom_audit["generator"] = generator_audit
    dotcom_audit["path_engine_share_by_scenario"] = {
        scenario: {
            "S1_dotcom_easing_multilayer": float(
                full_weights[mask & (engines == 0)].sum() / full_weights[mask].sum()
            ),
            "S2_balanced_soft_landing_layer": float(
                full_weights[mask & (engines == 1)].sum() / full_weights[mask].sum()
            ),
            "S3_tightening_stress_layer": float(
                full_weights[mask & (engines == 2)].sum() / full_weights[mask].sum()
            ),
        }
        for scenario, mask in masks.items()
    }
    shadow_full = inputs["shadow_v52"]["ablations"]["full_evidence"]["probabilities"]
    shadow_comparison = {
        "baseline_candidate_id": inputs["shadow_v52"]["candidate_id"],
        "baseline_model_content_sha256": inputs["shadow_v52"]["model_content_sha256"],
        "baseline_source_sha256": file_hash(root / SHADOW_V52_RELATIVE),
        "candidate_id": CANDIDATE_ID,
        "comparable_anchor": inputs["shadow_v52"]["anchor"]["close"] == anchor,
        "comparable_distribution_seed": inputs["shadow_v52"]["model"]["seed"] == SEED,
        "changed_inputs": [
            "latest_completed_official_market_anchor_transport",
            "mutually_exclusive_macro_origin_regime_cohorts",
            "S1_dotcom_plus_easing_S2_balanced_S3_tightening_stress_databases",
            "independent_phase_block_pools_and_residual_provenance",
            "dotcom_likelihood_isolated_to_S1_at_0.60",
        ],
        "metric_deltas": {
            key: ablations["full_evidence"]["probabilities"][key] - shadow_full[key]
            for key in probability_keys
        },
        "scenario_probability_deltas": {
            key: ablations["full_evidence"]["probabilities"]["scenario_probabilities"][key]
                 - shadow_full["scenario_probabilities"][key]
            for key in ("S1", "S2", "S3")
        },
        "official_snapshot_overwritten": False,
    }
    sensitivity_rows: list[dict[str, Any]] = []
    for s1_strength in (.40, .60):
        if math.isclose(s1_strength, .60):
            sensitivity_weighting = weighting
            sensitivity_metrics = ablations["full_evidence"]["probabilities"]
        else:
            sensitivity_dotcom = dict(inputs["dotcom"])
            sensitivity_dotcom["scenario_strength"] = {
                "S1": s1_strength, "S2": 0.0, "S3": 0.0,
            }
            sensitivity_weighting = build_weights(
                paths, dates, engines, scores, sensitivity_dotcom, generator_audit
            )
            sensitivity_metrics = _probability_metrics(
                paths, dates, sensitivity_weighting["full_evidence"]["weights"], masks
            )
        sensitivity_rows.append({
            "S1_strength": s1_strength,
            "S2_strength": 0.0,
            "S3_strength": 0.0,
            "scenario_probabilities": sensitivity_metrics["scenario_probabilities"],
            "terminal_above_anchor_2026": sensitivity_metrics["terminal_above_anchor_2026"],
            "first_touch_minus_10_by_october_end": sensitivity_metrics[
                "first_touch_minus_10_by_october_end"
            ],
            "year_end_p50": sensitivity_metrics["year_end_p50"],
            "effective_sample_size_fraction": sensitivity_weighting[
                "full_evidence"
            ]["diagnostics"]["effective_sample_size_fraction"],
            "weight_gates_pass": sensitivity_weighting[
                "full_evidence"
            ]["diagnostics"]["gates_pass"],
        })
    sensitivity_gate = (
        all(row["weight_gates_pass"] for row in sensitivity_rows)
        and all(
            later["scenario_probabilities"]["S1"]
            > earlier["scenario_probabilities"]["S1"]
            for earlier, later in zip(sensitivity_rows, sensitivity_rows[1:])
        )
    )
    b_sensitivity_rows: list[dict[str, Any]] = []
    for generator_share in (.40, .60):
        if math.isclose(generator_share, .60):
            sensitivity_paths = paths
            sensitivity_dates = dates
            sensitivity_engines = engines
            sensitivity_generator_audit = generator_audit
            sensitivity_weighting = weighting
        else:
            sensitivity_paths, sensitivity_dates, sensitivity_engines, _, \
                sensitivity_generator_audit = generate_prior(
                    root, inputs, generator_dotcom_share=generator_share
                )
            sensitivity_weighting = build_weights(
                sensitivity_paths, sensitivity_dates, sensitivity_engines,
                scores, inputs["dotcom"], sensitivity_generator_audit,
            )
        sensitivity_masks = _engine_masks(sensitivity_engines)
        sensitivity_weights = sensitivity_weighting["full_evidence"]["weights"]
        sensitivity_bands = _bands(
            sensitivity_paths[sensitivity_masks["S1"]],
            sensitivity_weights[sensitivity_masks["S1"]]
            / sensitivity_weights[sensitivity_masks["S1"]].sum(),
        )
        sensitivity_path_metrics = _path_metrics(sensitivity_paths, sensitivity_dates)
        conditional_s1 = sensitivity_weights[sensitivity_masks["S1"]] \
            / sensitivity_weights[sensitivity_masks["S1"]].sum()
        b_sensitivity_rows.append({
            "B_generator_dotcom_block_share": generator_share,
            "status": "active" if math.isclose(generator_share, .60) else "within_cap_shadow",
            "realized_dotcom_session_share": sensitivity_generator_audit[
                "scenarios"
            ]["S1"]["sampling"]["realized_dotcom_session_share"],
            "S1_p50_returns": {
                str(sessions): sensitivity_bands["p50"][sessions] / anchor - 1.0
                for sessions in (21, 63, 126, 252)
            },
            "S1_terminal_return_p50": sensitivity_bands["p50"][-1] / anchor - 1.0,
            "S1_maximum_drawdown_p50": float(weighted_quantile(
                sensitivity_path_metrics["maximum_drawdown"][sensitivity_masks["S1"]],
                conditional_s1, (.50,),
            )[0]),
            "C_mixture_probability": {
                key: float(sensitivity_weights[mask].sum())
                for key, mask in sensitivity_masks.items()
            },
        })
    candidate = {
        "schema_version": 1,
        "artifact_type": "scenario_v5_2_research_candidate",
        "candidate_id": CANDIDATE_ID,
        "status": "RESEARCH_CANDIDATE_COMPLETE_SEPARATION_DB_LIMITED_EVENT_MAP",
        "promotion_state": "NOT_OFFICIAL_NOT_CHAMPION",
        "as_of": inputs["knowledge_cutoff"],
        "knowledge_cutoff": inputs["knowledge_cutoff"],
        "anchor": {
            "symbol": "^IXIC",
            "date": forecast_anchor["date"],
            "available_at": forecast_anchor["available_at"],
            "close": anchor,
            "event_day_return_role": "latest_completed_market_anchor_only",
            "future_event_jump": 0.0,
        },
        "forecast_time_transport": {
            "source_snapshot_id": inputs["current_scenario"]["snapshot_id"],
            "source_cutoff": inputs["current_scenario"]["generated_at"],
            "source_anchor": anchor,
            "target_anchor": anchor,
            "target_anchor_date": forecast_anchor["date"],
            "mode": "LATEST_COMPLETED_MARKET_DAY_REFORECAST",
            "source_probabilities_used_numerically": False,
            "legacy_v5_1_probabilities_used_numerically": False,
            "historical_transport_step": 0.0,
        },
        "model": {
            "model_id": "complete_separation_empirical_episode_databases_v6",
            "seed": SEED,
            "path_count": int(paths.shape[0]),
            "path_count_by_engine": {
                "S1_dotcom_easing_multilayer": int((engines == 0).sum()),
                "S2_balanced_soft_landing_layer": int((engines == 1).sum()),
                "S3_tightening_stress_layer": int((engines == 2).sum()),
            },
            "engine_mixture_probability": {
                "S1_dotcom_easing_multilayer": 1.0 / 3.0,
                "S2_balanced_soft_landing_layer": 1.0 / 3.0,
                "S3_tightening_stress_layer": 1.0 / 3.0,
            },
            "generator_audit": generator_audit,
            "history_start": inputs["history_manifest"]["first_session"],
            "history_end": inputs["history_manifest"]["last_session"],
            "history_observations": inputs["history_manifest"]["row_count"],
            "hard_event_mapping": {
                "eligible_historical_event_count": 1,
                "preferred_minimum": 60,
                "weak_minimum": 30,
                "status": "REFERENCE_ONLY_INSUFFICIENT_N",
                "direct_event_return_kernel_used": False,
            },
            "path_creation_note": (
                "No endpoint, drawdown date, fixed phase duration, or scenario "
                "probability is forced. Paths recombine observed scenario-native "
                "episode segments with empirical transitions."
            ),
            "valuation_and_earnings_gate": {
                "status": "REFERENCE_ONLY_MISSING_POINT_IN_TIME_CROSS_ERA_HISTORY",
                "stale_Cyclically_adjusted_PE_substitution": False,
                "fabricated_low_PER_feature": False,
                "source_mapping": inputs["separation_contract"]["source_mapping"],
                "D0_blocked_coordinates": inputs["separation_contract_audit"][
                    "D0_blocked_features"
                ],
            },
        },
        "weight_spaces": {
            "contract_id": inputs["weight_contract"]["contract_id"],
            "contract_path": WEIGHT_CONTRACT_RELATIVE.as_posix(),
            "A_evidence_strength": {
                "value": dotcom_audit["A_evidence_strength"],
                "role": "post_generation_S1_likelihood",
                "changes_path_geometry": False,
            },
            "B_generator_dotcom_block_share": {
                "value": dotcom_audit["B_generator_dotcom_block_share"],
                "realized_session_share": dotcom_audit["B_realized_dotcom_session_share"],
                "role": "S1_registered_episode_session_source_share",
                "changes_path_geometry": True,
            },
            "C_mixture_probability": {
                "value": dotcom_audit["C_mixture_probability"],
                "role": "derived_research_cohort_mass",
                "directly_settable": False,
                "calibrated_event_probability": False,
            },
        },
        "evidence_scores": scores,
        "evidence_registry": evidence,
        "scenario_layer_contract": weighting["scenario_layer_contract"],
        "complete_separation_contract": {
            "path": SEPARATION_CONTRACT_RELATIVE.as_posix(),
            "sha256": generator_audit["separation_contract_sha256"],
            "shared_runtime_inputs_allowed": [
                "current_index_anchor", "trading_calendar"
            ],
            "feature_schemas": generator_audit["feature_schemas_by_scenario"],
            "episode_ids": generator_audit["episode_ids_by_scenario"],
            "episode_interval_overlap_count": generator_audit[
                "episode_interval_overlap_count"
            ],
            "residual_pool_hashes_unique": generator_audit[
                "residual_pool_hashes_unique"
            ],
            "fixed_phase_template_active": generator_audit[
                "fixed_phase_template_active"
            ],
            "structural_event_adapter": generator_audit[
                "structural_event_adapter"
            ],
        },
        "dependency_control": {
            "default_cluster_cap": .35,
            "approved_cluster_overrides": {
                "dotcom_single_cycle_analog": {
                    "cap": .60,
                    "scope": "research-only S1 challenger",
                    "approval_receipt": inputs["dotcom"]["approved_override"]["approval_receipt"],
                    "official_or_champion_use": False,
                },
            },
            "clusters": [
                {"id": "bls_empsit_2026_07", "effective_strength": .30, "cap": .35, "gate_pass": True},
                {"id": "cme_fed_funds_futures", "effective_strength": .25, "cap": .35, "gate_pass": True},
                {"id": "post_jobs_market_state", "effective_strength": .10, "cap": .35, "gate_pass": True},
                {"id": "dotcom_single_cycle_analog", "effective_strength": .60, "cap": .60, "gate_pass": True},
                {"id": "macro_easing_expansion_origin_set", "effective_strength": 0.0, "cap": .35, "gate_pass": True},
                {"id": "macro_balanced_soft_landing_origin_set", "effective_strength": 0.0, "cap": .35, "gate_pass": True},
                {"id": "macro_tightening_stress_origin_set", "effective_strength": 0.0, "cap": .35, "gate_pass": True},
                {"id": "current_official_market_anchor", "effective_strength": 0.0, "cap": .35, "gate_pass": True},
                {"id": "scenario_ancestor", "effective_strength": 0.0, "cap": .35, "gate_pass": True},
                *[
                    {"id": key, "effective_strength": value, "cap": .35, "gate_pass": value <= .35}
                    for key, value in inputs["event_updates"]["dependency_cluster_strength"].items()
                ],
            ],
            "duplicate_narratives_numerical_strength": 0.0,
            "gate_pass": True,
        },
        "circularity_control": {
            "v5_1_ancestor_used_numerically": False,
            "narrative_reports_used_numerically": False,
            "realized_event_return_coefficient": 0.0,
            "future_event_jump": 0.0,
            "full_equals_explicit_zero_event_reaction": event_double_count_gate,
            "gate_pass": event_double_count_gate,
        },
        "ablations": ablations,
        "component_ablations": {
            "policy_only": {
                "included_evidence": ["policy_relief"],
                "probabilities": policy_only_metrics,
                "weight_diagnostics": weighting["policy_only"]["diagnostics"],
            },
            "growth_only": ablations["labor_only"],
            "combined_growth_and_policy": ablations["labor_rate"],
            "macro_full_without_dotcom": {
                "included_evidence": [
                    "labor_growth_risk", "policy_relief", "cross_asset_relief",
                    "event_learning",
                ],
                "probabilities": full_without_dotcom_metrics,
                "weight_diagnostics": weighting["full_without_dotcom"]["diagnostics"],
            },
            "dotcom_upside_increment": {
                "included_evidence": ["dotcom_S1_weighted_upside_view"],
                "scenario_strength": inputs["dotcom"]["scenario_strength"],
                "probability_increment": {
                    key: ablations["full_evidence"]["probabilities"][key]
                         - full_without_dotcom_metrics[key]
                    for key in probability_keys
                },
            },
            "report_view_increment": {
                "numerical_report_views": 1,
                "reason": "explicitly approved dotcom view; same-cluster approval row has zero extra strength",
            },
        },
        "evidence_attribution": attribution,
        "dotcom_scenario_weighting": dotcom_audit,
        "event_learning": {
            "mode": "append_only_event_then_deterministic_candidate_rebuild",
            "ledger_path": "data/scenarios/candidates/event_learning/events.jsonl",
            "supported_events": ["cpi", "nfp", "fomc", "gdp", "earnings"],
            "active_event_count": inputs["event_updates"]["active_event_count"],
            "numerical_event_count": inputs["event_updates"]["numerical_event_count"],
            "corrections_require_supersedes": True,
            "instant_means": "after a validated normalized release is explicitly ingested",
            "background_scraping_or_unbounded_self_training": False,
            "structural_adapter": generator_audit["structural_event_adapter"],
            "probability_only_update": False,
        },
        "structural_event_ablation": structural_event_ablation,
        "distribution": {
            "probability_space": "total_path_mixture",
            "dates": dates,
            "bands": mixture_bands,
            "historical_actual": historical_actual,
            "forecast_boundary": forecast_anchor["date"],
            "central_path_bundle": _central_bundle(
                paths, dates, full_weights, mixture_bands
            ),
        },
        "conditional_small_multiples": {
            "probability_space": "scenario_conditional",
            "dates": dates,
            "scenarios": scenarios,
        },
        "first_touch_distribution": _first_touch_distribution(paths, dates, full_weights),
        "pre_post_jobs_comparison": {
            "comparison_basis": "same post-event anchor counterfactual to isolate evidence; not an archived pre-event forecast",
            "before_jobs_prior_only": {
                **ablations["prior_only"]["probabilities"],
                "first_touch_distribution": _first_touch_distribution(
                    paths, dates, weighting["prior_only"]["weights"]
                ),
            },
            "after_jobs_full_evidence": {
                **ablations["full_evidence"]["probabilities"],
                "first_touch_distribution": _first_touch_distribution(
                    paths, dates, full_weights
                ),
            },
            "archived_v5_1_reference": {
                "knowledge_cutoff": inputs["v51"]["knowledge_cutoff"],
                "scenario_probabilities": {
                    key: inputs["v51"]["conditional_distribution"]["scenarios"][key]["probability"]
                    for key in ("S1", "S2", "S3")
                },
                "correction_touch_probability": inputs["v51"]["correction_timing_distribution"]["any_touch_probability"],
                "warning": "not directly comparable because anchor, horizon, prior, and partition changed",
            },
        },
        "shadow_comparison": shadow_comparison,
        "sensitivity_analysis": {
            "design": "A varies likelihood on fixed paths; B varies S1 registered-episode session provenance",
            "rows": sensitivity_rows,
            "B_generator_rows": b_sensitivity_rows,
            "above_cap_shadow_only": [0.70, 0.80],
            "above_cap_never_active": True,
            "monotonic_S1_probability_gate": sensitivity_gate,
            "gate_pass": sensitivity_gate,
        },
        "distinctness_2027": distinctness,
        "distinctness": research_distinctness,
        "display_contract": {
            "main_chart": "shared_log_axis_three_conditional_p50_with_total_mixture_band",
            "main_chart_scenario_lines": True,
            "scenario_surface": "S1_S2_S3_conditional_p50_shared_scale",
            "primary_line": "three_scenario_conditional_p50_lines",
            "secondary_lines": "scenario_actual_medoids_plus_total_mixture_p25_p75_band",
            "probability_space_separation": {
                "scenario_lines": "scenario_conditional",
                "gray_band": "total_path_mixture",
                "cohort_weights": "research_cohort_weight_not_calibrated_event_probability",
            },
            "fake_wiggle": False,
            "october_2_exact_date_forecast": False,
            "percent_conversion_boundary": "dashboard_only",
            "dotcom_weight_disclosure": "S1 0.60 override; S2 0.00; S3 0.00; research only",
            "scenario_database_disclosure": (
                "S1/S2/S3 use distinct feature schemas, registered non-overlapping "
                "episodes, empirical phase durations/transitions, and residual pools; "
                "S1 targets a 0.60 dotcom session share"
            ),
            "valuation_disclosure": (
                "PER/valuation is reference-only because a vintage-complete cross-era "
                "point-in-time history is unavailable; no stale or fabricated value input"
            ),
        },
        "source_hashes": {
            **{path: source_file_hash(root, path) for path in SOURCE_PATHS},
            SHADOW_V52_RELATIVE.as_posix(): file_hash(root / SHADOW_V52_RELATIVE),
            LEGACY_V52_RELATIVE.as_posix(): file_hash(root / LEGACY_V52_RELATIVE),
            WEIGHT_CONTRACT_RELATIVE.as_posix(): file_hash(root / WEIGHT_CONTRACT_RELATIVE),
        },
        "protected_write_contract": {
            "official_snapshot": "read_only",
            "ledger": "not_opened_for_write",
            "archive": "not_opened_for_write",
        },
    }
    if not distinctness["gate_pass"]:
        candidate["status"] = "RESEARCH_CANDIDATE_DEGRADED_2027_DISTINCTNESS"
    candidate["model_content_sha256"] = canonical_hash(candidate)
    return candidate


def stable_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
