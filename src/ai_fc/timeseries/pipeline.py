"""End-to-end commands for the isolated NASDAQ multivariate shadow model."""

from __future__ import annotations

import json
import hashlib
import gzip
import math
import os
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.facts import as_of_rows, assert_no_leakage
from ai_fc.scenario import future_trading_days, load_calendar_contract

from .artifact import (
    FORECAST_LEDGER,
    append_forecast,
    append_resolution,
    blocked_artifact,
    load_latest,
    verify_latest,
)
from .backtest import OriginScore, summarize_backtest, walk_forward_backtest
from .contracts import (
    FACTS_RELATIVE,
    LEDGER_RELATIVE,
    MODEL_RELATIVE,
    RUNS_RELATIVE,
    canonical_hash,
    load_contract,
)
from .features import (
    FeatureBundle,
    assemble_feature_bundle,
    build_realtime_factor_history,
)
from .events import apply_event_overlay, read_events
from .ledger import (
    collect_alfred,
    incremental_realtime_window,
    read_facts,
    rebuild_facts_from_raw,
)
from .model import (
    RidgeVARXFit,
    RobustScaler,
    deterministic_seed,
    ensemble_weights,
    model_content_hash,
    select_distribution_parameters,
    select_ridge_varx,
    simulate_correlated_paths,
    summarize_paths,
)


class TimeSeriesPipelineError(RuntimeError):
    """A fail-closed pipeline gate prevented time-series publication."""


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def bootstrap_timeseries(root: Path, *, api_key: str) -> dict[str, Any]:
    if not api_key:
        raise TimeSeriesPipelineError("FRED_API_KEY is required and must be supplied at runtime")
    return collect_alfred(root, api_key=api_key)


def refresh_timeseries(root: Path, *, api_key: str) -> dict[str, Any]:
    if not api_key:
        raise TimeSeriesPipelineError("FRED_API_KEY is required and must be supplied at runtime")
    recovered = rebuild_facts_from_raw(root)
    retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
    realtime_start, realtime_end = incremental_realtime_window(root, retrieved_at=retrieved)
    result = collect_alfred(
        root, api_key=api_key, retrieved_at=retrieved,
        realtime_start=realtime_start, realtime_end=realtime_end,
    )
    return {"recovered_from_raw": recovered, **result}


def _source_hash(root: Path) -> str:
    facts = [fact.model_dump(mode="json") for fact in read_facts(root)]
    return canonical_hash(facts)


def _validate_bundle(bundle: FeatureBundle, contract: dict[str, Any]) -> None:
    if bundle.endogenous.shape[0] < 800:
        raise TimeSeriesPipelineError("PIT common sample has fewer than 800 completed sessions")
    registered_start_year = contract["model"]["windows"]["expanding_start"][:4]
    if bundle.dates[0][:4] > registered_start_year:
        raise TimeSeriesPipelineError("PIT common sample does not reach the preregistered expanding-start year")
    if bundle.endogenous.shape[1] != 6:
        raise TimeSeriesPipelineError("registered six-dimensional market vector is incomplete")
    required_factors = {"growth_factor", "inflation_factor"}
    if not required_factors.issubset(bundle.exogenous_names):
        raise TimeSeriesPipelineError("realtime DynamicFactorMQ growth/inflation states are incomplete")


def _write_model_arrays(
    path: Path, *, expanding: RidgeVARXFit, rolling: RidgeVARXFit,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            expanding_coefficients=expanding.coefficients,
            expanding_median=expanding.scaler.median,
            expanding_iqr=expanding.scaler.iqr,
            expanding_residuals=expanding.residuals,
            rolling_coefficients=rolling.coefficients,
            rolling_median=rolling.scaler.median,
            rolling_iqr=rolling.scaler.iqr,
            rolling_residuals=rolling.residuals,
        )
    os.replace(temporary, path)


def fit_timeseries(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    contract = load_contract(root)
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    facts = read_facts(root)
    if not facts:
        raise TimeSeriesPipelineError("no ALFRED PIT facts; run timeseries-bootstrap first")
    assert_no_leakage((fact for fact in facts if fact.available_at <= cutoff), as_of=cutoff)
    factor_history = build_realtime_factor_history(facts, knowledge_cutoff=cutoff)
    bundle = assemble_feature_bundle(
        facts, knowledge_cutoff=cutoff, factor_history=factor_history,
    )
    _validate_bundle(bundle, contract)
    lag_candidates = contract["model"]["varx"]["lag_candidates"]
    alpha_candidates = contract["model"]["varx"]["ridge_alpha_candidates"]
    expanding = select_ridge_varx(
        bundle.endogenous,
        bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        lag_candidates=lag_candidates,
        alpha_candidates=alpha_candidates,
    )
    rolling_start = max(0, len(bundle.dates) - int(contract["model"]["windows"]["rolling_sessions"]))
    rolling = select_ridge_varx(
        bundle.endogenous,
        bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        lag_candidates=lag_candidates,
        alpha_candidates=alpha_candidates,
        train_start=rolling_start,
    )
    combined_residuals = np.vstack((expanding.residuals, rolling.residuals))
    seed = deterministic_seed(contract["model_id"], contract["model_version"], bundle.dates[-1])
    block_length, ewma_lambda, distribution_scores = select_distribution_parameters(
        combined_residuals,
        block_candidates=contract["model"]["distribution"]["block_length_candidates"],
        ewma_candidates=contract["model"]["distribution"]["ewma_lambda_candidates"],
        seed=seed,
    )
    run_seed = {
        "model_id": contract["model_id"],
        "version": contract["model_version"],
        "knowledge_cutoff": cutoff,
        "source_hash": _source_hash(root),
        "dates": [bundle.dates[0], bundle.dates[-1], len(bundle.dates)],
        "expanding": expanding.manifest(),
        "rolling": rolling.manifest(),
        "distribution": {"block_length": block_length, "ewma_lambda": ewma_lambda},
    }
    run_id = f"ts-fit-{canonical_hash(run_seed)[:24]}"
    arrays_path = root / MODEL_RELATIVE / f"{run_id}.npz"
    _write_model_arrays(arrays_path, expanding=expanding, rolling=rolling)
    factor_path = root / FACTS_RELATIVE / f"factor_states_{bundle.dates[-1]}.json"
    _atomic_json(factor_path, factor_history)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "model_id": contract["model_id"],
        "model_version": contract["model_version"],
        "status": "shadow",
        "as_of": bundle.dates[-1],
        "knowledge_cutoff": cutoff,
        "training": {
            "start": bundle.dates[0],
            "end": bundle.dates[-1],
            "sessions": len(bundle.dates),
            "endogenous_names": list(bundle.endogenous_names),
            "exogenous_names": list(bundle.exogenous_names),
            "dates": list(bundle.dates),
            "missing_features": list(bundle.missing_required),
            "transform_manifest": bundle.transform_manifest,
        },
        "expanding": expanding.manifest(),
        "rolling_10y": rolling.manifest(),
        "distribution": {
            "block_length": block_length,
            "ewma_lambda": ewma_lambda,
            "selection_scores": distribution_scores,
            "path_count": contract["model"]["distribution"]["path_count"],
        },
        "source_hash": run_seed["source_hash"],
        "contract_hash": canonical_hash(contract),
        "arrays_path": arrays_path.relative_to(root).as_posix(),
        "arrays_sha256": _file_sha256(arrays_path),
        "factor_history_path": factor_path.relative_to(root).as_posix(),
        "factor_history_hash": canonical_hash(factor_history),
    }
    payload["model_hash"] = model_content_hash(payload)
    run_path = root / MODEL_RELATIVE / f"{run_id}.json"
    _atomic_json(run_path, payload)
    _atomic_json(root / MODEL_RELATIVE / "latest.json", {
        "schema_version": 1,
        "run_id": run_id,
        "model_path": run_path.relative_to(root).as_posix(),
        "model_hash": payload["model_hash"],
        "derived_pointer": True,
    })
    return payload


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_fit(root: Path) -> tuple[dict[str, Any], RidgeVARXFit, RidgeVARXFit]:
    pointer = _read_json(root / MODEL_RELATIVE / "latest.json")
    payload = _read_json(root / pointer["model_path"])
    if payload.get("model_hash") != pointer.get("model_hash"):
        raise TimeSeriesPipelineError("model pointer hash mismatch")
    replay = {key: value for key, value in payload.items() if key != "model_hash"}
    if model_content_hash(replay) != payload.get("model_hash"):
        raise TimeSeriesPipelineError("model manifest does not replay")
    arrays_path = root / payload["arrays_path"]
    if _file_sha256(arrays_path) != payload["arrays_sha256"]:
        raise TimeSeriesPipelineError("model array hash mismatch")
    factor_history = _read_json(root / payload["factor_history_path"])
    if canonical_hash(factor_history) != payload.get("factor_history_hash"):
        raise TimeSeriesPipelineError("factor-state history hash mismatch")
    with np.load(arrays_path, allow_pickle=False) as arrays:
        def rebuild(prefix: str, manifest_key: str) -> RidgeVARXFit:
            manifest = payload[manifest_key]
            return RidgeVARXFit(
                lag=int(manifest["lag"]),
                alpha=float(manifest["alpha"]),
                endog_names=tuple(manifest["endogenous"]),
                exog_names=tuple(manifest["exogenous"]),
                predictor_names=tuple(manifest["predictors"]),
                coefficients=arrays[f"{prefix}_coefficients"].copy(),
                scaler=RobustScaler(
                    median=arrays[f"{prefix}_median"].copy(),
                    iqr=arrays[f"{prefix}_iqr"].copy(),
                ),
                residuals=arrays[f"{prefix}_residuals"].copy(),
                train_start=int(manifest["train_start"]),
                train_end=int(manifest["train_end"]),
                selection_score=float(manifest["selection_score"]),
            )
        return payload, rebuild("expanding", "expanding"), rebuild("rolling", "rolling_10y")


def backtest_timeseries(
    root: Path, *, knowledge_cutoff: str | None = None, path_count: int = 1000,
) -> dict[str, Any]:
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    contract = load_contract(root)
    facts = read_facts(root)
    factor_history = build_realtime_factor_history(facts, knowledge_cutoff=cutoff)
    bundle = assemble_feature_bundle(facts, knowledge_cutoff=cutoff, factor_history=factor_history)
    _validate_bundle(bundle, contract)
    scores, summary = walk_forward_backtest(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        outer_start=contract["evaluation"]["outer_start"],
        path_count=path_count,
    )
    rows = [{
        **row.__dict__,
        "baseline_crps": dict(row.baseline_crps),
    } for row in scores]
    run_seed = {
        "model_id": contract["model_id"],
        "knowledge_cutoff": cutoff,
        "source_hash": _source_hash(root),
        "summary": summary,
    }
    run_id = f"ts-backtest-{canonical_hash(run_seed)[:24]}"
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "model_id": contract["model_id"],
        "model_version": contract["model_version"],
        "knowledge_cutoff": cutoff,
        "source_hash": run_seed["source_hash"],
        "pit_leakage_count": 0,
        "purge_sessions": contract["evaluation"]["purge_sessions"],
        "embargo_sessions": contract["evaluation"]["embargo_sessions"],
        "summary": summary,
        "scores": rows,
    }
    payload["content_hash"] = canonical_hash(payload)
    run_path = root / RUNS_RELATIVE / f"{run_id}.json"
    _atomic_json(run_path, payload)
    _atomic_json(root / RUNS_RELATIVE / "backtest_latest.json", {
        "schema_version": 1,
        "run_id": run_id,
        "run_path": run_path.relative_to(root).as_posix(),
        "content_hash": payload["content_hash"],
        "derived_pointer": True,
    })
    return payload


def _load_backtest(root: Path) -> dict[str, Any] | None:
    pointer_path = root / RUNS_RELATIVE / "backtest_latest.json"
    if not pointer_path.is_file():
        return None
    pointer = _read_json(pointer_path)
    payload = _read_json(root / pointer["run_path"])
    if payload.get("content_hash") != pointer.get("content_hash"):
        raise TimeSeriesPipelineError("backtest pointer hash mismatch")
    replay = {key: value for key, value in payload.items() if key != "content_hash"}
    if canonical_hash(replay) != payload.get("content_hash"):
        raise TimeSeriesPipelineError("backtest run does not replay")
    return payload


def _blocked_forecast(
    root: Path, *, cutoff: str, reasons: list[str], missing: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    payload = blocked_artifact(
        root,
        as_of=cutoff[:10],
        knowledge_cutoff=cutoff,
        reasons=reasons,
        missing_features=missing or [],
    )
    target = append_forecast(root, payload)
    return target, payload


def forecast_timeseries(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    contract = load_contract(root)
    facts = read_facts(root)
    if not facts:
        return _blocked_forecast(
            root, cutoff=cutoff,
            reasons=["ALFRED PIT 백필 전이므로 검증 숫자를 표시하지 않습니다."],
        )
    try:
        model_run, expanding, rolling = _load_fit(root)
        backtest = _load_backtest(root)
        factor_history = _read_json(root / model_run["factor_history_path"])
        bundle = assemble_feature_bundle(facts, knowledge_cutoff=cutoff, factor_history=factor_history)
        _validate_bundle(bundle, contract)
    except (OSError, ValueError, TimeSeriesPipelineError) as exc:
        return _blocked_forecast(root, cutoff=cutoff, reasons=[str(exc)])
    if not backtest or not bool(backtest["summary"].get("gate_pass")):
        reasons = ((backtest or {}).get("summary") or {}).get("reasons") or [
            "2007년 이후 워크포워드 공개 Gate 검증 전입니다."
        ]
        return _blocked_forecast(
            root, cutoff=cutoff, reasons=list(reasons), missing=list(bundle.missing_required),
        )
    current_source_hash = _source_hash(root)
    required_daily = set(contract["sources"]["daily_required"])
    availability = [
        datetime.fromisoformat(value)
        for series_id, value in bundle.source_available_at.items()
        if series_id in required_daily
    ]
    oldest_required_available = min(availability)
    age_hours = (datetime.fromisoformat(cutoff) - oldest_required_available).total_seconds() / 3600
    if age_hours > float(contract["freshness"]["required_daily_sla_hours"]):
        # Do not silently reuse prior inputs as a new forecast.
        try:
            prior = load_latest(root)
            return root / RUNS_RELATIVE / f"{prior['forecast_id']}.json", prior
        except (OSError, ValueError):
            return _blocked_forecast(root, cutoff=cutoff, reasons=["필수 일별 입력이 48시간 SLA를 초과했습니다."])
    history = backtest["summary"].get("ensemble_crps_history_21d") or {}
    expanding_weight, rolling_weight, weight_reason = ensemble_weights(
        history.get("expanding") or [], history.get("rolling_10y") or [],
    )
    nasdaq_rows = as_of_rows(facts, series_id="NASDAQCOM", as_of=cutoff)
    anchor_row = max(
        (row for row in nasdaq_rows if row.observation_time[:10] <= bundle.dates[-1]),
        key=lambda item: item.observation_time,
    )
    anchor = float(anchor_row.value)
    seed = deterministic_seed(contract["model_id"], contract["model_version"], bundle.dates[-1])
    distribution = model_run["distribution"]
    simulated = simulate_correlated_paths(
        (expanding, rolling),
        weights=(expanding_weight, rolling_weight),
        endog_history=bundle.endogenous,
        exog_last=bundle.exogenous[-1],
        anchor=anchor,
        path_count=int(contract["model"]["distribution"]["path_count"]),
        horizon=63,
        block_length=int(distribution["block_length"]),
        ewma_lambda=float(distribution["ewma_lambda"]),
        seed=seed,
    )
    event_facts = read_events(root, knowledge_cutoff=cutoff)
    cutoff_dt = datetime.fromisoformat(cutoff)
    upcoming_events = [
        event for event in event_facts
        if event.actual is None and datetime.fromisoformat(event.scheduled_at) > cutoff_dt
    ]
    current_event = min(upcoming_events, key=lambda item: item.scheduled_at) if upcoming_events else None
    event_paths, event_overlay = apply_event_overlay(
        simulated["index_paths"],
        anchor=anchor,
        events=event_facts,
        current_event=current_event,
        contract=contract,
        seed=seed,
    )
    simulated["index_paths"] = event_paths
    simulated["path_hash"] = hashlib.sha256(
        np.ascontiguousarray(event_paths).view(np.uint8)
    ).hexdigest()
    summary = summarize_paths(simulated["index_paths"], anchor=anchor)
    left = expanding.target_contributions(bundle.endogenous, bundle.exogenous[-1])
    right = rolling.target_contributions(bundle.endogenous, bundle.exogenous[-1])
    contribution_names = sorted(set(left) | set(right))
    components = {
        name: expanding_weight * left.get(name, 0.0) + rolling_weight * right.get(name, 0.0)
        for name in contribution_names
    }
    predicted_log_return = float(sum(components.values()))
    sessions = future_trading_days(
        date.fromisoformat(bundle.dates[-1]), 63, load_calendar_contract(root),
    )
    payload_seed = {
        "model_id": contract["model_id"],
        "version": contract["model_version"],
        "contract_hash": canonical_hash(contract),
        "as_of": bundle.dates[-1],
        "knowledge_cutoff": cutoff,
        "model_hash": model_run["model_hash"],
        "backtest_id": backtest["run_id"],
        "path_hash": simulated["path_hash"],
    }
    payload = {
        "schema_version": 1,
        "forecast_id": f"ts-{canonical_hash(payload_seed)[:20]}",
        "model_id": contract["model_id"],
        "model_version": contract["model_version"],
        "status": "shadow",
        "display_state": "ready",
        "as_of": bundle.dates[-1],
        "knowledge_cutoff": cutoff,
        "generated_at": cutoff,
        "anchor": {"series_id": "NASDAQCOM", "date": anchor_row.observation_time[:10], "value": anchor},
        "target": contract["target"]["series_id"],
        "transform": contract["target"]["transform"],
        "probability_unit": "fraction",
        "probability_space": contract["probability_contract"]["space"],
        "combined_with_existing_models": False,
        "horizons": summary["horizons"],
        "path": {
            "history_dates": [row.observation_time[:10] for row in nasdaq_rows if row.observation_time[:10] <= bundle.dates[-1]][-63:],
            "history_index": [float(row.value) for row in nasdaq_rows if row.observation_time[:10] <= bundle.dates[-1]][-63:],
            "dates": [item.isoformat() for item in sessions],
            **summary["path_quantiles"],
        },
        "contributions_1d": {
            "predicted_log_return": predicted_log_return,
            "components": components,
        },
        "ensemble": {
            "expanding_weight": expanding_weight,
            "rolling_10y_weight": rolling_weight,
            "weight_rule": weight_reason,
            "distribution_block_length": distribution["block_length"],
            "ewma_lambda": distribution["ewma_lambda"],
            "path_count": contract["model"]["distribution"]["path_count"],
            "seed": seed,
        },
        "event_overlay": event_overlay,
        "freshness": {
            "required_daily_sla_hours": contract["freshness"]["required_daily_sla_hours"],
            "oldest_required_available_at": oldest_required_available.isoformat(),
            "age_hours": age_hours,
            "missing_features": list(bundle.missing_required),
            "model_training_end": model_run["training"]["end"],
        },
        "backtest": {
            "run_id": backtest["run_id"],
            "gate_pass": True,
            "metrics": backtest["summary"],
            "reasons": [],
        },
        "hashes": {
            "contract": canonical_hash(contract),
            "sources": current_source_hash,
            "model_training_sources": model_run["source_hash"],
            "model": model_run["model_hash"],
            "path": simulated["path_hash"],
            "content": None,
        },
        "publication": {
            "customer_numbers_visible": True,
            "automatic_champion_promotion": False,
            "minimum_shadow_sessions": contract["promotion"]["minimum_shadow_sessions"],
        },
    }
    target = append_forecast(root, payload)
    return target, _read_json(target)


def resolve_timeseries(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> dict[str, int]:
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    facts = read_facts(root)
    nasdaq_rows = as_of_rows(facts, series_id="NASDAQCOM", as_of=cutoff)
    prices = {row.observation_time[:10]: float(row.value) for row in nasdaq_rows}
    completed_dates = sorted(prices)
    appended = 0
    existing = _jsonl(root / LEDGER_RELATIVE / "resolutions.jsonl")
    existing_keys = {(row["forecast_id"], row["horizon_sessions"]) for row in existing}
    for ledger_row in _jsonl(root / LEDGER_RELATIVE / FORECAST_LEDGER):
        artifact = _read_json(root / ledger_row["artifact_path"])
        if not artifact["publication"]["customer_numbers_visible"]:
            continue
        dates = artifact["path"]["dates"]
        for horizon in (1, 5, 21, 63):
            key = (artifact["forecast_id"], horizon)
            target_date = dates[horizon - 1]
            if key in existing_keys or target_date not in prices:
                continue
            anchor = float(artifact["anchor"]["value"])
            actual_index = prices[target_date]
            row_seed = {
                "forecast_id": artifact["forecast_id"],
                "horizon_sessions": horizon,
                "target_date": target_date,
                "actual_index": actual_index,
                "knowledge_cutoff": cutoff,
            }
            row = {
                "resolution_id": f"tsr-{canonical_hash(row_seed)[:24]}",
                "forecast_id": artifact["forecast_id"],
                "resolved_at": cutoff,
                "horizon_sessions": horizon,
                "target_date": target_date,
                "actual_index": actual_index,
                "actual_return": actual_index / anchor - 1.0,
                "probability_space": artifact["probability_space"],
            }
            appended += int(append_resolution(root, row))
            existing_keys.add(key)
    return {"existing": len(existing), "appended": appended, "total": len(existing) + appended}


def verify_timeseries(root: Path) -> dict[str, Any]:
    """Replay the complete shadow chain without mutating any durable artifact."""
    contract = load_contract(root)
    forecast = verify_latest(root)
    latest = load_latest(root)
    receipts = _jsonl(root / LEDGER_RELATIVE / "raw_receipts.jsonl")
    event_receipts = _jsonl(root / LEDGER_RELATIVE / "event_raw_receipts.jsonl")
    receipt_keys: set[tuple[str, str, str]] = set()
    raw_errors: list[str] = []
    for row in [*receipts, *event_receipts]:
        raw_path = root / row["raw_path"]
        if not raw_path.is_file():
            raw_errors.append(f"missing:{row['receipt_id']}")
            continue
        try:
            body = gzip.decompress(raw_path.read_bytes())
        except (OSError, EOFError):
            raw_errors.append(f"gzip:{row['receipt_id']}")
            continue
        if hashlib.sha256(body).hexdigest() != row["raw_sha256"]:
            raw_errors.append(f"hash:{row['receipt_id']}")
        receipt_keys.add((str(row["series_id"]), str(row["raw_sha256"]), str(row["retrieved_at"])))
    facts = read_facts(root)
    orphan_facts = [
        fact.key for fact in facts
        if (fact.series_id, fact.source_hash, fact.retrieved_at) not in receipt_keys
    ]
    cutoff = str(latest["knowledge_cutoff"])
    cutoff_dt = datetime.fromisoformat(cutoff)
    leakage = [
        fact.key for fact in facts
        if datetime.fromisoformat(fact.available_at) > cutoff_dt
    ]
    model_status: dict[str, Any] = {"present": False}
    if (root / MODEL_RELATIVE / "latest.json").is_file():
        model, _, _ = _load_fit(root)
        model_status = {"present": True, "run_id": model["run_id"], "model_hash": model["model_hash"]}
    backtest_status: dict[str, Any] = {"present": False}
    backtest = _load_backtest(root)
    if backtest is not None:
        backtest_status = {
            "present": True,
            "run_id": backtest["run_id"],
            "content_hash": backtest["content_hash"],
            "gate_pass": bool(backtest["summary"]["gate_pass"]),
        }
    events = read_events(root, knowledge_cutoff=cutoff)
    event_receipt_ids = {str(row["receipt_id"]) for row in event_receipts}
    orphan_events = [
        event.event_id for event in events
        if event.receipt_id not in event_receipt_ids
        or any(identifier not in event_receipt_ids for identifier in event.supporting_receipt_ids)
    ]
    failures: list[str] = []
    if raw_errors:
        failures.append(f"raw receipt errors={len(raw_errors)}")
    if orphan_facts:
        failures.append(f"orphan facts={len(orphan_facts)}")
    if leakage:
        failures.append(f"available_at leakage={len(leakage)}")
    if orphan_events:
        failures.append(f"orphan events={len(orphan_events)}")
    if latest["model_id"] != contract["model_id"] or latest["combined_with_existing_models"] is not False:
        failures.append("probability-space isolation failed")
    if latest["hashes"].get("contract") != canonical_hash(contract):
        failures.append("forecast contract hash is stale")
    return {
        "ok": not failures,
        "model_id": contract["model_id"],
        "forecast": forecast,
        "receipts": len(receipts),
        "event_receipts": len(event_receipts),
        "facts": len(facts),
        "events": len(events),
        "raw_errors": raw_errors,
        "orphan_facts": orphan_facts[:10],
        "leakage": leakage[:10],
        "orphan_events": orphan_events[:10],
        "model": model_status,
        "backtest": backtest_status,
        "failures": failures,
    }
