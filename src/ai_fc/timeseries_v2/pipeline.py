"""V2 data, candidate, sealed evaluation, fit, forecast, and verification pipeline."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.scenario import future_trading_days, load_calendar_contract
from ai_fc.scenario_v5.contracts import compare_protected_hashes, protected_hashes
from ai_fc.timeseries.backtest import (
    OriginScore,
    _baseline_samples,
    sample_crps,
)
from ai_fc.timeseries.events import apply_event_overlay, read_events
from ai_fc.timeseries.ledger import read_facts
from ai_fc.timeseries.model import (
    RidgeVARXFit,
    RobustScaler,
    deterministic_seed,
    ensemble_weights,
    summarize_paths,
)

from .backtest import (
    ensemble_history_21d,
    summarize_backtest_v2,
    walk_forward_backtest_v2,
)
from .artifact import (
    FORECAST_LEDGER,
    RESOLUTION_LEDGER,
    SEALED_CORRECTION_LEDGER,
    SEALED_LEDGER,
    append_unique,
    blocked_latest,
    read_latest,
    write_latest,
)
from .contracts import (
    MODEL_RELATIVE,
    RUNS_RELATIVE,
    canonical_hash,
    frozen_hash,
    load_contract_v2,
    model_code_hash,
    runtime_manifest,
)
from .dfm_cache import (
    build_origin_dfm_cache,
    macro_release_cutoffs,
    read_dfm_manifest,
    verify_dfm_runtime_provenance,
)
from .features import CandidateFeatureBundle, assemble_candidate_bundle, export_candidate_parquet
from .market_archive import (
    collect_official_market_archives,
    export_market_parquet,
    read_market_observations,
    verify_market_lineage,
)
from .model import (
    select_distribution_parameters_v2,
    select_ridge_varx_v2,
    simulate_correlated_paths_v2,
)


class TimeSeriesV2PipelineError(RuntimeError):
    """A V2 data, model, sealed, or publication gate failed closed."""


def _source_ledger_hashes(root: Path) -> dict[str, str | None]:
    paths = {
        "macro_observation_manifest": Path("data/timeseries/ledgers/observation_chunks.jsonl"),
        "macro_receipts": Path("data/timeseries/ledgers/raw_receipts.jsonl"),
        "market_observations": Path("data/timeseries_v2/ledgers/market_observations.jsonl"),
        "market_receipts": Path("data/timeseries_v2/ledgers/market_raw_receipts.jsonl"),
        "dfm_cache_manifest": Path("data/timeseries_v2/ledgers/dfm_cache_manifest.jsonl"),
    }
    return {
        key: hashlib.sha256((root / path).read_bytes()).hexdigest()
        if (root / path).is_file() else None
        for key, path in paths.items()
    }


def _required_market_freshness(
    market: list[Any], *, contract: dict[str, Any], knowledge_cutoff: str,
) -> dict[str, Any]:
    cutoff = datetime.fromisoformat(knowledge_cutoff)
    limit = float(contract["operational_gate"]["required_market_max_age_hours"])
    groups: list[dict[str, Any]] = []
    stale: list[str] = []
    for alternatives in contract["operational_gate"]["required_market_groups"]:
        rows = [row for row in market if row.series_id in set(alternatives)]
        label = "_or_".join(alternatives)
        if not rows:
            groups.append({"group": label, "status": "missing", "age_hours": None})
            stale.append(label)
            continue
        latest_day = max(row.observation_time for row in rows)
        latest = max(
            (row for row in rows if row.observation_time == latest_day),
            key=lambda row: row.available_at,
        )
        availability_age = (
            cutoff - datetime.fromisoformat(latest.available_at)
        ).total_seconds() / 3600.0
        observation_end = datetime.fromisoformat(latest.observation_time).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc,
        )
        observation_age = (cutoff - observation_end).total_seconds() / 3600.0
        age_hours = max(0.0, availability_age, observation_age)
        status = "fresh" if age_hours <= limit else "stale"
        groups.append({
            "group": label,
            "selected_series": latest.series_id,
            "observation_time": latest.observation_time,
            "available_at": latest.available_at,
            "age_hours": age_hours,
            "status": status,
        })
        if status != "fresh":
            stale.append(label)
    return {"ok": not stale, "maximum_age_hours": limit, "groups": groups, "stale_groups": stale}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _rows_to_json(scores: list[OriginScore]) -> list[dict[str, Any]]:
    return [
        {
            "date": row.date, "horizon": row.horizon,
            "actual_log_return": row.actual_log_return, "model_crps": row.model_crps,
            "baseline_crps": row.baseline_crps, "median": row.median,
            "p10": row.p10, "p25": row.p25, "p75": row.p75, "p90": row.p90,
            "direction_correct": row.direction_correct,
            "first_touch_actual": row.first_touch_actual,
            "first_touch_probability": row.first_touch_probability,
            "expanding_crps": row.expanding_crps, "rolling_crps": row.rolling_crps,
            "block_length": row.block_length, "ewma_lambda": row.ewma_lambda,
        }
        for row in scores
    ]


def _rows_from_json(rows: list[dict[str, Any]]) -> list[OriginScore]:
    return [OriginScore(**row) for row in rows]


def _score_candidate(scores: list[OriginScore], *, start: str, end: str) -> float:
    rows = [row for row in scores if start <= row.date <= end and row.horizon in {21, 63}]
    if not rows:
        return math.inf
    return float(np.mean([row.model_crps for row in rows]))


def _candidate_development_eligibility(
    bundle: CandidateFeatureBundle, *, contract: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Require candidates to be scored over the same preregistered development era."""
    reasons: list[str] = []
    common_start = str(contract["publication_gate"]["market_common_start_not_after"])
    if not bundle.dates or bundle.dates[0] > common_start:
        reasons.append("development_window_pit_coverage_incomplete")
    development_end = str(contract["model"]["windows"]["development"][1])
    if not bundle.dates or bundle.dates[-1] <= development_end:
        reasons.append("development_target_horizon_incomplete")
    return not reasons, reasons


def _monitoring_sample(values: np.ndarray, *, count: int = 201) -> list[float]:
    """Compact deterministic empirical distribution for future CRPS resolution."""
    probabilities = (np.arange(count, dtype=float) + 0.5) / count
    return [float(value) for value in np.quantile(np.asarray(values, dtype=float), probabilities)]


def _operational_gate_reasons(
    root: Path, *, contract: dict[str, Any], fallback_scores: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    path = root / RESOLUTION_LEDGER
    resolutions = [] if not path.is_file() else [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]
    scored = [
        row for row in resolutions
        if int(row.get("horizon_sessions", 0)) in {21, 63}
        and row.get("model_crps") is not None and row.get("baseline_crps")
    ]
    origins = sorted({str(row["as_of"]) for row in scored})[-int(contract["operational_gate"]["recent_origins"]):]
    if len(origins) >= int(contract["operational_gate"]["recent_origins"]):
        rows = [row for row in scored if row["as_of"] in origins]
        source = "matured_shadow_forecasts"
    else:
        rows = [
            row for row in fallback_scores
            if int(row.get("horizon", 0)) in {21, 63}
        ][-2 * int(contract["operational_gate"]["recent_origins"]):]
        source = "sealed_backtest_until_26_shadow_origins_mature"
    relative: list[float] = []
    coverage: dict[str, float] = {}
    for horizon in (21, 63):
        subset = [row for row in rows if int(row.get("horizon", row.get("horizon_sessions", 0))) == horizon]
        if not subset:
            continue
        for row in subset:
            best = min(float(value) for value in row["baseline_crps"].values())
            relative.append((float(row["model_crps"]) - best) / max(best, 1e-12))
        if "covered_p10_p90" in subset[0]:
            coverage[str(horizon)] = float(np.mean([bool(row["covered_p10_p90"]) for row in subset]))
        else:
            coverage[str(horizon)] = float(np.mean([
                float(row["p10"]) <= float(row["actual_log_return"]) <= float(row["p90"])
                for row in subset
            ]))
    reasons: list[str] = []
    underperformance = None if not relative else float(np.mean(relative))
    if (
        underperformance is not None
        and underperformance > float(contract["operational_gate"]["crps_max_underperformance"])
    ):
        reasons.append("최근 26개 원점 CRPS가 기준선보다 5% 이상 악화")
    lower, upper = contract["publication_gate"]["p10_p90_coverage"]
    for horizon, value in coverage.items():
        if not float(lower) <= value <= float(upper):
            reasons.append(f"최근 {horizon}일 p10-p90 적중률이 계약 범위를 이탈")
    return reasons, {
        "source": source, "matured_origin_count": len(origins),
        "mean_crps_underperformance": underperformance, "coverage_p10_p90": coverage,
    }


def bootstrap_timeseries_v2(root: Path) -> dict[str, Any]:
    """Fetch only official market archives; ALFRED macro PIT remains in V1's canonical store."""
    before = protected_hashes(root)
    market = collect_official_market_archives(root, collection_mode="bootstrap_reconstruction")
    after = protected_hashes(root)
    comparison = compare_protected_hashes(before, after)
    if not comparison["ok"]:
        raise TimeSeriesV2PipelineError(f"protected path changed during V2 bootstrap: {comparison}")
    return {"market": market, "protected": comparison, "lineage": verify_market_lineage(root),
            "parquet": export_market_parquet(root)}


def refresh_timeseries_v2(root: Path) -> dict[str, Any]:
    before = protected_hashes(root)
    market = collect_official_market_archives(root, collection_mode="forward_refresh")
    lineage = verify_market_lineage(root)
    if not lineage["ok"]:
        raise TimeSeriesV2PipelineError(f"V2 market lineage failed: {lineage['errors'][:3]}")
    comparison = compare_protected_hashes(before, protected_hashes(root))
    if not comparison["ok"]:
        raise TimeSeriesV2PipelineError(f"protected path changed during V2 refresh: {comparison}")
    return {"market": market, "lineage": lineage, "protected": comparison,
            "parquet": export_market_parquet(root)}


def prepare_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None, max_dfm_cutoffs: int | None = None,
) -> dict[str, Any]:
    contract = load_contract_v2(root)
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    facts = read_facts(root)
    if not facts:
        raise TimeSeriesV2PipelineError("ALFRED macro PIT store is empty; run timeseries-bootstrap")
    if any(row.available_at > cutoff for row in facts if row.series_id in contract["sources"]["macro_native_pit"]["growth"]):
        # Post-cutoff rows may exist in the ledger and are expected; they must be excluded by the fitter.
        pass
    dfm = build_origin_dfm_cache(
        root, contract=contract, facts=facts, end_cutoff=cutoff,
        start=contract["model"]["windows"]["warmup"][0], max_cutoffs=max_dfm_cutoffs,
    )
    dfm_runtime_audit = verify_dfm_runtime_provenance(root)
    lineage = verify_market_lineage(root)
    market = read_market_observations(root, knowledge_cutoff=cutoff)
    series_counts = {
        series_id: sum(row.series_id == series_id for row in market)
        for series_id in ("NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXB", "DTWEXBGS")
    }
    required = ("NASDAQCOM", "VIX", "DGS2", "DGS10")
    missing = [series_id for series_id in required if series_counts[series_id] == 0]
    if series_counts["DTWEXB"] + series_counts["DTWEXBGS"] == 0:
        missing.append("DTWEXB_or_DTWEXBGS")
    result = {
        "schema_version": 2, "model_id": contract["model_id"], "knowledge_cutoff": cutoff,
        "contract_hash": frozen_hash(contract), "market_lineage": lineage,
        "dfm_runtime_provenance": dfm_runtime_audit,
        "market_counts": series_counts, "missing_market": missing, "dfm": dfm,
        "status": "ready" if (
            not missing and lineage["ok"] and dfm["blocking_failed"] == 0
            and dfm["ready_before_evaluation"] and dfm_runtime_audit["ok"]
        ) else "hold",
    }
    nasdaq_days = [row.observation_time for row in market if row.series_id == "NASDAQCOM"]
    prior_latest = read_latest(root)
    if prior_latest is None or prior_latest["publication"]["customer_numbers_visible"] is not True:
        reasons = ["2019년 이후 봉인 평가가 아직 완료되지 않음"]
        reasons.extend(f"필수 시장 자료 누락: {item}" for item in missing)
        if dfm["blocking_failed"]:
            reasons.append(f"2007년 이후 원점별 DFM 캐시 실패 {dfm['blocking_failed']}건")
        if not dfm["ready_before_evaluation"]:
            reasons.append("2007년 평가 시작 전 사용 가능한 DFM 캐시 없음")
        if not lineage["ok"]:
            reasons.append("시장 원문-영수증-관측 연결 검증 실패")
        if not dfm_runtime_audit["ok"]:
            reasons.append("DFM 실행 버전 증거 누락 또는 statsmodels 0.14.6 불일치")
        write_latest(root, blocked_latest(
            as_of=max(nasdaq_days) if nasdaq_days else cutoff[:10],
            knowledge_cutoff=cutoff, contract_hash=frozen_hash(contract), reasons=reasons,
            data_summary={
                "market_counts": series_counts,
                "market_start": min(nasdaq_days) if nasdaq_days else None,
                "data_grades": ["native_pit", "reconstructed_market_archive"],
                "dfm_cache_entries": len(read_dfm_manifest(root)),
            },
        ))
    return result


def _bundle_manifest(bundle: CandidateFeatureBundle) -> dict[str, Any]:
    return {
        "candidate_id": bundle.candidate_id, "status": bundle.status,
        "start": bundle.dates[0] if bundle.dates else None,
        "end": bundle.dates[-1] if bundle.dates else None,
        "sessions": len(bundle.dates), "endogenous": list(bundle.endogenous_names),
        "exogenous": list(bundle.exogenous_names), "data_grades": list(bundle.data_grades),
        "missing_features": list(bundle.missing_features),
        "dfm_cache_count": len(bundle.dfm_cache_ids),
        "dfm_cache_complete": bundle.dfm_cache_complete,
        "content_hash": canonical_hash({
            "dates": bundle.dates,
            "endogenous": np.ascontiguousarray(bundle.endogenous).tobytes().hex(),
            "exogenous": np.ascontiguousarray(bundle.exogenous).tobytes().hex(),
        }),
    }


def _run_backtest(
    bundle: CandidateFeatureBundle, *, contract: dict[str, Any], path_count: int,
) -> tuple[list[OriginScore], dict[str, Any]]:
    if bundle.status != "ready":
        raise TimeSeriesV2PipelineError(
            f"{bundle.candidate_id} unavailable: {', '.join(bundle.missing_features) or 'insufficient sessions'}"
        )
    return walk_forward_backtest_v2(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        outer_start="2007-01-01",
        path_count=path_count,
    )


def _sealed_already_disclosed(
    root: Path, *, model_id: str, contract_hash: str,
    replacement_model_code_hash: str | None = None,
) -> dict[str, Any] | None:
    path = root / SEALED_LEDGER
    if not path.is_file():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    matches = [row for row in rows if row["model_id"] == model_id and row["contract_hash"] == contract_hash]
    correction_path = root / SEALED_CORRECTION_LEDGER
    corrections = [] if not correction_path.is_file() else [
        json.loads(line)
        for line in correction_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    correction_by_id = {
        str(row.get("correction_id")): row for row in corrections
        if row.get("correction_id")
    }
    superseded_corrections: set[str] = set()
    for correction in corrections:
        supersedes = correction.get("supersedes")
        if not supersedes:
            continue
        prior_correction = correction_by_id.get(str(supersedes))
        if prior_correction is None:
            raise TimeSeriesV2PipelineError("sealed correction supersedes an unknown correction")
        if prior_correction.get("invalidates_run_id") != correction.get("invalidates_run_id"):
            raise TimeSeriesV2PipelineError("sealed correction supersedes another run's correction")
        superseded_corrections.add(str(supersedes))
    by_run = {str(row["run_id"]): row for row in matches}
    invalidated: set[str] = set()
    replacement_hashes: set[str] = set()
    invalidated_model_hashes: set[str] = set()
    for correction in corrections:
        run_id = str(correction.get("invalidates_run_id", ""))
        if run_id not in by_run:
            continue
        prior = by_run[run_id]
        if correction.get("invalidated_content_hash") != prior.get("content_hash"):
            raise TimeSeriesV2PipelineError("sealed correction content hash mismatch")
        if correction.get("invalidated_model_code_hash") != (prior.get("hashes") or {}).get("model_code"):
            raise TimeSeriesV2PipelineError("sealed correction model-code hash mismatch")
        if correction.get("frozen_contract_hash") != contract_hash:
            raise TimeSeriesV2PipelineError("sealed correction changed a frozen contract")
        replacement_hash = str(correction.get("replacement_model_code_hash") or "")
        invalidated_model_hash = str(correction.get("invalidated_model_code_hash") or "")
        if not replacement_hash:
            raise TimeSeriesV2PipelineError("sealed correction replacement hash is missing")
        if str(correction.get("correction_id")) not in superseded_corrections:
            replacement_hashes.add(replacement_hash)
            invalidated_model_hashes.add(invalidated_model_hash)
        invalidated.add(run_id)
    active = [row for row in matches if str(row["run_id"]) not in invalidated]
    if len(active) > 1:
        raise TimeSeriesV2PipelineError("sealed evaluation disclosed more than once")
    active_replacement_hashes = replacement_hashes - invalidated_model_hashes
    if (
        replacement_model_code_hash is not None
        and matches and not active
        and replacement_model_code_hash not in active_replacement_hashes
    ):
        raise TimeSeriesV2PipelineError("sealed correction does not authorize this calculation build")
    return active[0] if active else None


def invalidate_sealed_evaluation_for_calculation_error(
    root: Path, *, run_id: str, reason_code: str,
) -> dict[str, Any]:
    """Append an auditable invalidation without deleting the disclosed run.

    Only independently verifiable implementation errors are accepted. Frozen
    candidates, windows, gates, and probability semantics are not reopened.
    """
    allowed = {
        "weekly_origin_target_alignment_and_seed_contract",
        "sealed_ensemble_history_and_combined_ci_contract",
    }
    if reason_code not in allowed:
        raise TimeSeriesV2PipelineError("sealed correction reason is not allowlisted")
    contract = load_contract_v2(root)
    contract_digest = frozen_hash(contract)
    path = root / SEALED_LEDGER
    if not path.is_file():
        raise TimeSeriesV2PipelineError("sealed evaluation ledger is missing")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    matches = [row for row in rows if str(row.get("run_id")) == run_id]
    if len(matches) != 1:
        raise TimeSeriesV2PipelineError("sealed run identity is missing or ambiguous")
    prior = matches[0]
    if prior.get("contract_hash") != contract_digest:
        raise TimeSeriesV2PipelineError("sealed correction cannot change frozen coordinates")
    old_code = (prior.get("hashes") or {}).get("model_code")
    new_code = model_code_hash(root)
    if not old_code or old_code == new_code:
        raise TimeSeriesV2PipelineError("sealed correction requires a distinct calculation build")
    correction_path = root / SEALED_CORRECTION_LEDGER
    existing_corrections = [] if not correction_path.is_file() else [
        json.loads(line) for line in correction_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    relevant = [row for row in existing_corrections if row.get("invalidates_run_id") == run_id]
    superseded_ids = {str(row["supersedes"]) for row in relevant if row.get("supersedes")}
    active_relevant = [
        row for row in relevant if str(row.get("correction_id")) not in superseded_ids
    ]
    if len(active_relevant) > 1:
        raise TimeSeriesV2PipelineError("sealed run has ambiguous active corrections")
    prior_correction = active_relevant[0] if active_relevant else None
    if (
        prior_correction
        and prior_correction.get("replacement_model_code_hash") == new_code
        and prior_correction.get("reason_code") == reason_code
    ):
        return prior_correction
    seed = {
        "invalidates_run_id": run_id,
        "invalidated_content_hash": prior.get("content_hash"),
        "invalidated_model_code_hash": old_code,
        "replacement_model_code_hash": new_code,
        "frozen_contract_hash": contract_digest,
        "reason_code": reason_code,
        "supersedes": None if prior_correction is None else prior_correction["correction_id"],
    }
    payload = {
        "schema_version": 1,
        "correction_id": f"tsv2-sealed-correction-{canonical_hash(seed)[:24]}",
        **seed,
        "model_id": contract["model_id"],
        "model_version": contract["model_version"],
        "frozen_coordinates_unchanged": True,
        "reason_summary": {
            "weekly_origin_target_alignment_and_seed_contract": (
                "The weekly completed-session close was excluded from training and "
                "the backtest seed omitted model id/version. The disclosed result is "
                "invalid for publication and remains preserved for audit."
            ),
            "sealed_ensemble_history_and_combined_ci_contract": (
                "The sealed interval reset the preregistered prior-52-origin ensemble "
                "history, and the combined 21/63-session bootstrap concatenated horizons "
                "instead of preserving weekly-origin pairing. The disclosed result is "
                "invalid for publication and remains preserved for audit."
            ),
        }[reason_code],
        "supersedes": seed["supersedes"],
    }
    append_unique(root, SEALED_CORRECTION_LEDGER, payload, key="correction_id")
    return payload


def backtest_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None, path_count: int = 20000,
    disclose_sealed: bool = True,
) -> dict[str, Any]:
    if disclose_sealed is not True:
        raise TimeSeriesV2PipelineError(
            "development-only candidate disclosure is disabled; use the non-sealed preflight"
        )
    protected_before = protected_hashes(root)
    contract = load_contract_v2(root)
    required_path_count = int(contract["model"]["distribution"]["path_count"])
    if path_count != required_path_count:
        raise TimeSeriesV2PipelineError(
            f"sealed V2 evaluation requires exactly {required_path_count} paths"
        )
    dfm_runtime_audit = verify_dfm_runtime_provenance(root)
    if not dfm_runtime_audit["ok"]:
        raise TimeSeriesV2PipelineError(
            "DFM cache runtime provenance is incomplete or incompatible with statsmodels==0.14.6"
        )
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    contract_digest = frozen_hash(contract)
    current_model_code_hash = model_code_hash(root)
    prior = _sealed_already_disclosed(
        root, model_id=contract["model_id"], contract_hash=contract_digest,
        replacement_model_code_hash=current_model_code_hash,
    )
    if prior is not None:
        return prior
    facts = read_facts(root)
    candidates: dict[str, dict[str, Any]] = {}
    score_cache: dict[str, list[OriginScore]] = {}
    bundles: dict[str, CandidateFeatureBundle] = {}
    for candidate_id in ("C1", "C2", "C3", "C4"):
        bundle = assemble_candidate_bundle(
            root, contract=contract, macro_facts=facts,
            candidate_id=candidate_id, knowledge_cutoff=cutoff,
        )
        bundles[candidate_id] = bundle
        manifest = _bundle_manifest(bundle)
        parquet_manifest = export_candidate_parquet(root, bundle) if bundle.dates else None
        manifest["parquet"] = parquet_manifest
        if bundle.status != "ready":
            candidates[candidate_id] = {**manifest, "development_score": None, "reason": "candidate_unavailable"}
            continue
        development_eligible, eligibility_reasons = _candidate_development_eligibility(
            bundle, contract=contract,
        )
        manifest["development_eligible"] = development_eligible
        if not development_eligible:
            candidates[candidate_id] = {
                **manifest,
                "development_score": None,
                "reason": "candidate_unavailable",
                "eligibility_reasons": eligibility_reasons,
            }
            continue
        cache_seed = {
            "contract_hash": contract_digest, "candidate_id": candidate_id,
            "bundle_hash": manifest["content_hash"], "path_count": path_count,
            "window": contract["model"]["windows"]["development"],
            "model_code_hash": current_model_code_hash,
        }
        cache_path = root / RUNS_RELATIVE / f"development_{candidate_id}_{canonical_hash(cache_seed)[:20]}.json"
        try:
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                scores = _rows_from_json(cached["scores"])
            else:
                # Candidate selection sees only the development endpoint plus the
                # longest target horizon. The selected winner alone is evaluated
                # on the sealed 2019+ interval below.
                development_end = contract["model"]["windows"]["development"][1]
                stop = next(
                    (index for index, day in enumerate(bundle.dates) if day > "2019-04-30"),
                    len(bundle.dates),
                )
                development_bundle = CandidateFeatureBundle(
                    candidate_id=bundle.candidate_id, status=bundle.status,
                    dates=bundle.dates[:stop], endogenous=bundle.endogenous[:stop],
                    endogenous_names=bundle.endogenous_names, exogenous=bundle.exogenous[:stop],
                    exogenous_names=bundle.exogenous_names, data_grades=bundle.data_grades,
                    missing_features=bundle.missing_features, dfm_cache_ids=bundle.dfm_cache_ids,
                    transform_manifest=bundle.transform_manifest,
                    dfm_cache_complete=bundle.dfm_cache_complete,
                )
                scores, _ = _run_backtest(
                    development_bundle, contract=contract, path_count=path_count,
                )
                cache_payload = {
                    "schema_version": 2, "cache_seed": cache_seed,
                    "development_end": development_end, "scores": _rows_to_json(scores),
                }
                cache_payload["content_hash"] = canonical_hash(cache_payload)
                _atomic_json(cache_path, cache_payload)
        except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
            candidates[candidate_id] = {**manifest, "development_score": None, "reason": str(exc)}
            continue
        score_cache[candidate_id] = scores
        candidates[candidate_id] = {
            **manifest,
            "development_score": _score_candidate(
                scores,
                start=contract["model"]["windows"]["development"][0],
                end=contract["model"]["windows"]["development"][1],
            ),
        }
    eligible = {
        key: value for key, value in candidates.items()
        if value.get("development_score") is not None and math.isfinite(value["development_score"])
    }
    if not eligible:
        raise TimeSeriesV2PipelineError("no frozen V2 candidate completed development evaluation")
    selected = min(eligible, key=lambda key: (eligible[key]["development_score"], key))
    development_scores = [
        row for row in score_cache[selected]
        if row.date <= contract["model"]["windows"]["development"][1]
    ]
    initial_expanding_crps, initial_rolling_crps = ensemble_history_21d(
        development_scores,
    )
    # The sealed interval is computed only after the candidate winner is frozen.
    sealed_scores, _ = walk_forward_backtest_v2(
        dates=bundles[selected].dates,
        endog=bundles[selected].endogenous,
        exog=bundles[selected].exogenous,
        endog_names=bundles[selected].endogenous_names,
        exog_names=bundles[selected].exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        outer_start=contract["model"]["windows"]["sealed"][0],
        path_count=path_count,
        initial_expanding_crps=initial_expanding_crps,
        initial_rolling_crps=initial_rolling_crps,
    )
    selected_scores = [*development_scores, *sealed_scores]
    all_summary = summarize_backtest_v2(
        selected_scores, minimum_origins=int(contract["evaluation"]["minimum_origins"]),
    )
    sealed_start = contract["model"]["windows"]["sealed"][0]
    sealed_summary = summarize_backtest_v2(
        sealed_scores, minimum_origins=int(contract["evaluation"]["minimum_origins"]),
    )
    sealed_summary["ensemble_initial_history_origins"] = min(
        len(initial_expanding_crps), len(initial_rolling_crps), 52,
    )
    events = read_events(root, knowledge_cutoff=cutoff)
    resolved_events = sum(event.outcome_return_5d is not None for event in events)
    candidates["C5"] = {
        "candidate_id": "C5",
        "status": "overlay_eligible" if resolved_events >= 10 else "candidate_unavailable",
        "selected_core": selected,
        "pit_event_count": resolved_events,
        "varx_coefficient_eligible": resolved_events >= 60,
        "role": "path_reweighting_only" if 10 <= resolved_events < 60 else (
            "eligible_pending_ablation" if resolved_events >= 60 else "insufficient_pit_history"
        ),
    }
    reasons = list(all_summary["reasons"])
    # Candidate selection ends in 2018.  Publication therefore requires the
    # same CRPS / coverage contract on the untouched 2019+ interval as well.
    # The 2008 regime is necessarily outside that sealed interval and remains
    # enforced by the full 2007+ summary above.
    sealed_reasons = [
        reason for reason in sealed_summary["reasons"]
        if "great_financial_crisis_2008" not in reason
    ]
    reasons.extend(f"봉인평가: {reason}" for reason in sealed_reasons)
    if verify_market_lineage(root)["receipt_linkage"] < 1.0:
        reasons.append("market receipt linkage below 100%")
    selected_bundle = bundles[selected]
    if not selected_bundle.dates or selected_bundle.dates[0] > contract["publication_gate"]["market_common_start_not_after"]:
        reasons.append("2007년 검증을 위한 공통 시장 표본 미확보")
    gate_pass = not reasons
    result_seed = {
        "model_id": contract["model_id"], "contract_hash": contract_digest,
        "knowledge_cutoff": cutoff, "selected_candidate": selected,
        "candidate_hashes": {key: value.get("content_hash") for key, value in candidates.items()},
        "path_count": path_count,
        "model_code_hash": current_model_code_hash,
    }
    run_id = f"tsv2-backtest-{canonical_hash(result_seed)[:24]}"
    protected_after = protected_hashes(root)
    protected_comparison = compare_protected_hashes(protected_before, protected_after)
    if not protected_comparison["ok"]:
        raise TimeSeriesV2PipelineError(
            f"protected path changed during V2 backtest: {protected_comparison}"
        )
    payload = {
        "schema_version": 2, "run_id": run_id, "model_id": contract["model_id"],
        "model_version": 2, "contract_hash": contract_digest,
        "knowledge_cutoff": cutoff, "candidate_inventory_frozen": True,
        "candidates": candidates, "selected_candidate": selected,
        "development_window": contract["model"]["windows"]["development"],
        "sealed_window": [sealed_start, cutoff[:10]],
        "sealed_disclosure_number": 1,
        "sealed_summary": sealed_summary,
        "summary": {**all_summary, "gate_pass": gate_pass, "status": "pass" if gate_pass else "hold", "reasons": reasons},
        "selected_scores": _rows_to_json(selected_scores),
        "hashes": {
            "contract": contract_digest,
            "model_code": current_model_code_hash,
            "source_ledgers": _source_ledger_hashes(root),
            "selected_feature_bundle": candidates[selected]["content_hash"],
        },
        "evaluation_runtime": runtime_manifest(),
        "dfm_runtime_audit": dfm_runtime_audit,
        "protected_manifest": protected_after,
        "protected_comparison": protected_comparison,
    }
    payload["content_hash"] = canonical_hash(payload)
    target = root / RUNS_RELATIVE / f"{run_id}.json"
    _atomic_json(target, payload)
    _atomic_json(root / RUNS_RELATIVE / "backtest_latest.json", {
        "schema_version": 2, "run_id": run_id,
        "path": target.relative_to(root).as_posix(), "content_hash": payload["content_hash"],
    })
    append_unique(root, SEALED_LEDGER, payload, key="run_id")
    fit_selected_timeseries_v2(
        root, bundle=selected_bundle, backtest=payload, knowledge_cutoff=cutoff,
    )
    return payload


def monitor_backtest_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None, path_count: int = 20000,
) -> dict[str, Any]:
    """Re-evaluate the frozen winner without reopening candidate selection or sealed disclosure."""
    protected_before = protected_hashes(root)
    contract = load_contract_v2(root)
    required_path_count = int(contract["model"]["distribution"]["path_count"])
    if path_count != required_path_count:
        raise TimeSeriesV2PipelineError(
            f"V2 monitoring requires exactly {required_path_count} paths"
        )
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    contract_digest = frozen_hash(contract)
    sealed = _sealed_already_disclosed(
        root, model_id=contract["model_id"], contract_hash=contract_digest,
        replacement_model_code_hash=model_code_hash(root),
    )
    if sealed is None:
        raise TimeSeriesV2PipelineError("sealed winner is absent; run the one-time V2 backtest")
    if sealed["summary"]["gate_pass"] is not True:
        raise TimeSeriesV2PipelineError("sealed evaluation failed; monitoring cannot reopen it")
    selected = str(sealed["selected_candidate"])
    bundle = assemble_candidate_bundle(
        root, contract=contract, macro_facts=read_facts(root),
        candidate_id=selected, knowledge_cutoff=cutoff,
    )
    if bundle.status != "ready":
        raise TimeSeriesV2PipelineError(
            f"frozen winner unavailable for monitoring: {bundle.missing_features}"
        )
    scores, _ = _run_backtest(bundle, contract=contract, path_count=path_count)
    summary = summarize_backtest_v2(
        scores, minimum_origins=int(contract["evaluation"]["minimum_origins"]),
    )
    seed = {
        "contract_hash": contract_digest, "selected_candidate": selected,
        "knowledge_cutoff": cutoff, "bundle_hash": _bundle_manifest(bundle)["content_hash"],
        "path_count": path_count, "sealed_run_id": sealed["run_id"],
    }
    run_id = f"tsv2-monitor-{canonical_hash(seed)[:24]}"
    protected_after = protected_hashes(root)
    protected_comparison = compare_protected_hashes(protected_before, protected_after)
    if not protected_comparison["ok"]:
        raise TimeSeriesV2PipelineError(
            f"protected path changed during V2 monitoring: {protected_comparison}"
        )
    payload = {
        "schema_version": 2, "run_id": run_id, "role": "post_sealed_fixed_winner_monitoring",
        "model_id": contract["model_id"], "model_version": 2,
        "contract_hash": contract_digest, "knowledge_cutoff": cutoff,
        "selected_candidate": selected, "candidate_inventory_frozen": True,
        "candidate_selection_reopened": False, "sealed_run_id": sealed["run_id"],
        "sealed_disclosure_number": 1, "sealed_summary": sealed["sealed_summary"],
        "candidates": sealed["candidates"], "summary": summary,
        "selected_scores": _rows_to_json(scores), "protected_manifest": protected_after,
        "protected_comparison": protected_comparison,
        "hashes": {
            "contract": contract_digest,
            "model_code": model_code_hash(root),
            "source_ledgers": _source_ledger_hashes(root),
            "selected_feature_bundle": _bundle_manifest(bundle)["content_hash"],
        },
    }
    payload["content_hash"] = canonical_hash(payload)
    target = root / RUNS_RELATIVE / f"{run_id}.json"
    _atomic_json(target, payload)
    _atomic_json(root / RUNS_RELATIVE / "backtest_latest.json", {
        "schema_version": 2, "run_id": run_id,
        "path": target.relative_to(root).as_posix(), "content_hash": payload["content_hash"],
    })
    return payload


def _write_fit_arrays(path: Path, expanding: RidgeVARXFit, rolling: RidgeVARXFit) -> None:
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


def fit_selected_timeseries_v2(
    root: Path, *, bundle: CandidateFeatureBundle, backtest: dict[str, Any], knowledge_cutoff: str,
) -> dict[str, Any]:
    contract = load_contract_v2(root)
    expanding = select_ridge_varx_v2(
        bundle.endogenous, bundle.exogenous,
        endog_names=bundle.endogenous_names, exog_names=bundle.exogenous_names,
        lag_candidates=contract["model"]["varx"]["lag_candidates"],
        alpha_candidates=contract["model"]["varx"]["ridge_alpha_candidates"],
    )
    rolling_start = max(0, len(bundle.dates) - int(contract["model"]["windows"]["rolling_sessions"]))
    rolling = select_ridge_varx_v2(
        bundle.endogenous, bundle.exogenous,
        endog_names=bundle.endogenous_names, exog_names=bundle.exogenous_names,
        lag_candidates=contract["model"]["varx"]["lag_candidates"],
        alpha_candidates=contract["model"]["varx"]["ridge_alpha_candidates"],
        train_start=rolling_start,
    )
    seed = deterministic_seed(contract["model_id"], 2, bundle.dates[-1])
    block, ewma, scores = select_distribution_parameters_v2(
        np.vstack((expanding.residuals, rolling.residuals)),
        block_candidates=contract["model"]["distribution"]["block_length_candidates"],
        ewma_candidates=contract["model"]["distribution"]["ewma_lambda_candidates"],
        seed=seed,
    )
    run_seed = {
        "contract_hash": frozen_hash(contract), "candidate": bundle.candidate_id,
        "knowledge_cutoff": knowledge_cutoff, "bundle_hash": _bundle_manifest(bundle)["content_hash"],
        "backtest_run_id": backtest["run_id"],
        "model_code_hash": model_code_hash(root),
    }
    run_id = f"tsv2-fit-{canonical_hash(run_seed)[:24]}"
    arrays = root / MODEL_RELATIVE / f"{run_id}.npz"
    _write_fit_arrays(arrays, expanding, rolling)
    payload = {
        "schema_version": 2, "run_id": run_id, "model_id": contract["model_id"],
        "model_version": 2, "candidate_id": bundle.candidate_id,
        "as_of": bundle.dates[-1], "knowledge_cutoff": knowledge_cutoff,
        "contract_hash": frozen_hash(contract), "bundle": _bundle_manifest(bundle),
        "expanding": expanding.manifest(), "rolling": rolling.manifest(),
        "distribution": {"block_length": block, "ewma_lambda": ewma, "selection_scores": scores},
        "arrays_path": arrays.relative_to(root).as_posix(),
        "arrays_sha256": hashlib.sha256(arrays.read_bytes()).hexdigest(),
        "backtest_run_id": backtest["run_id"],
        "backtest_gate_pass": backtest["summary"]["gate_pass"],
        "hashes": {
            "contract": frozen_hash(contract),
            "model_code": model_code_hash(root),
            "source_ledgers": _source_ledger_hashes(root),
            "feature_bundle": _bundle_manifest(bundle)["content_hash"],
        },
    }
    payload["content_hash"] = canonical_hash(payload)
    target = root / MODEL_RELATIVE / f"{run_id}.json"
    _atomic_json(target, payload)
    _atomic_json(root / MODEL_RELATIVE / "fit_latest.json", {
        "schema_version": 2, "run_id": run_id, "path": target.relative_to(root).as_posix(),
        "content_hash": payload["content_hash"],
    })
    return payload


def fit_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    """Weekly refit of the already selected frozen core candidate."""
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    backtest = _backtest_payload(root)
    contract = load_contract_v2(root)
    bundle = assemble_candidate_bundle(
        root, contract=contract, macro_facts=read_facts(root),
        candidate_id=backtest["selected_candidate"], knowledge_cutoff=cutoff,
    )
    if bundle.status != "ready":
        raise TimeSeriesV2PipelineError(
            f"selected V2 candidate is unavailable: {bundle.missing_features}"
        )
    return fit_selected_timeseries_v2(
        root, bundle=bundle, backtest=backtest, knowledge_cutoff=cutoff,
    )


def _load_fit(root: Path) -> tuple[dict[str, Any], RidgeVARXFit, RidgeVARXFit]:
    pointer_path = root / MODEL_RELATIVE / "fit_latest.json"
    if not pointer_path.is_file():
        raise TimeSeriesV2PipelineError("V2 selected fit is missing; run timeseries-v2-backtest")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    manifest = json.loads((root / pointer["path"]).read_text(encoding="utf-8"))
    expected_content = canonical_hash({
        key: value for key, value in manifest.items() if key != "content_hash"
    })
    if manifest.get("content_hash") != expected_content or pointer.get("content_hash") != expected_content:
        raise TimeSeriesV2PipelineError("V2 fit manifest hash mismatch")
    arrays_path = root / manifest["arrays_path"]
    if hashlib.sha256(arrays_path.read_bytes()).hexdigest() != manifest.get("arrays_sha256"):
        raise TimeSeriesV2PipelineError("V2 fit arrays hash mismatch")
    arrays = np.load(arrays_path)

    def restore(prefix: str) -> RidgeVARXFit:
        spec = manifest[prefix]
        return RidgeVARXFit(
            lag=int(spec["lag"]), alpha=float(spec["alpha"]),
            endog_names=tuple(spec["endogenous"]), exog_names=tuple(spec["exogenous"]),
            predictor_names=tuple(spec["predictors"]),
            coefficients=arrays[f"{prefix}_coefficients"],
            scaler=RobustScaler(arrays[f"{prefix}_median"], arrays[f"{prefix}_iqr"]),
            residuals=arrays[f"{prefix}_residuals"],
            train_start=int(spec["train_start"]), train_end=int(spec["train_end"]),
            selection_score=float(spec["selection_score"]),
        )

    return manifest, restore("expanding"), restore("rolling")


def _backtest_payload(root: Path) -> dict[str, Any]:
    pointer = json.loads((root / RUNS_RELATIVE / "backtest_latest.json").read_text(encoding="utf-8"))
    return json.loads((root / pointer["path"]).read_text(encoding="utf-8"))


def forecast_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None, ralph_run_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    contract = load_contract_v2(root)
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    backtest = _backtest_payload(root)
    facts = read_facts(root)
    selected = backtest["selected_candidate"]
    bundle = assemble_candidate_bundle(
        root, contract=contract, macro_facts=facts, candidate_id=selected,
        knowledge_cutoff=cutoff,
    )
    data_summary = {
        "candidate": selected, "sessions": len(bundle.dates),
        "start": bundle.dates[0] if bundle.dates else None,
        "data_grades": list(bundle.data_grades), "missing_features": list(bundle.missing_features),
        "dfm_cache_count": len(bundle.dfm_cache_ids),
    }
    market = read_market_observations(root, knowledge_cutoff=cutoff)
    freshness = _required_market_freshness(
        market, contract=contract, knowledge_cutoff=cutoff,
    )
    data_summary["required_market_freshness"] = freshness
    reasons = list(backtest["summary"]["reasons"])
    if bundle.status != "ready":
        reasons.append("latest candidate feature bundle is unavailable")
    operational_reasons, operational_monitoring = _operational_gate_reasons(
        root, contract=contract, fallback_scores=backtest["selected_scores"],
    )
    reasons.extend(operational_reasons)
    reasons.extend(f"필수 시장 입력 48시간 SLA 초과: {item}" for item in freshness["stale_groups"])
    data_summary["operational_monitoring"] = operational_monitoring
    if reasons:
        payload = blocked_latest(
            as_of=bundle.dates[-1] if bundle.dates else cutoff[:10],
            knowledge_cutoff=cutoff, contract_hash=frozen_hash(contract), reasons=reasons,
            data_summary=data_summary, ralph_run_id=ralph_run_id,
        )
        path = write_latest(root, payload)
        return path, payload
    manifest, expanding, rolling = _load_fit(root)
    history_scores = backtest["summary"].get("ensemble_crps_history_21d", {})
    weights = ensemble_weights(
        history_scores.get("expanding", []), history_scores.get("rolling_10y", []),
        minimum=contract["model"]["ensemble"]["minimum_weight"],
        maximum=contract["model"]["ensemble"]["maximum_weight"],
    )
    nasdaq = sorted((row for row in market if row.series_id == "NASDAQCOM"), key=lambda row: row.observation_time)
    if not nasdaq:
        raise TimeSeriesV2PipelineError("NASDAQ anchor is missing")
    anchor = float(nasdaq[-1].value)
    seed = deterministic_seed(contract["model_id"], 2, bundle.dates[-1])
    simulated = simulate_correlated_paths_v2(
        (expanding, rolling), weights=(weights[0], weights[1]),
        endog_history=bundle.endogenous, exog_last=bundle.exogenous[-1], anchor=anchor,
        path_count=contract["model"]["distribution"]["path_count"], horizon=63,
        block_length=int(manifest["distribution"]["block_length"]),
        ewma_lambda=float(manifest["distribution"]["ewma_lambda"]), seed=seed,
    )
    event_facts = read_events(root, knowledge_cutoff=cutoff)
    cutoff_dt = datetime.fromisoformat(cutoff)
    upcoming = [
        event for event in event_facts
        if event.actual is None and datetime.fromisoformat(event.scheduled_at) > cutoff_dt
    ]
    current_event = min(upcoming, key=lambda event: event.scheduled_at) if upcoming else None
    event_paths, event_overlay = apply_event_overlay(
        simulated["index_paths"], anchor=anchor, events=event_facts,
        current_event=current_event, contract=contract, seed=seed,
    )
    simulated["index_paths"] = event_paths
    simulated["path_hash"] = hashlib.sha256(
        np.ascontiguousarray(event_paths).view(np.uint8)
    ).hexdigest()
    summary = summarize_paths(simulated["index_paths"], anchor=anchor)
    monitoring: dict[str, Any] = {}
    baseline_rng = np.random.default_rng(seed + 17_000)
    for horizon in (21, 63):
        model_returns = np.log(simulated["index_paths"][:, horizon - 1] / anchor)
        baselines = _baseline_samples(
            bundle.endogenous[:, 0], horizon=horizon, count=1000, rng=baseline_rng,
        )
        monitoring[str(horizon)] = {
            "unit": "log_return_fraction",
            "model_sample": _monitoring_sample(model_returns),
            "baseline_samples": {
                name: _monitoring_sample(values) for name, values in baselines.items()
            },
        }
    left = expanding.target_contributions(bundle.endogenous, bundle.exogenous[-1])
    right = rolling.target_contributions(bundle.endogenous, bundle.exogenous[-1])
    contributions = {
        name: weights[0] * left.get(name, 0.0) + weights[1] * right.get(name, 0.0)
        for name in sorted(set(left) | set(right))
    }
    predicted = weights[0] * float(expanding.predict(bundle.endogenous, bundle.exogenous[-1])[0]) + weights[1] * float(rolling.predict(bundle.endogenous, bundle.exogenous[-1])[0])
    if abs(sum(contributions.values()) - predicted) > 1e-10:
        raise TimeSeriesV2PipelineError("one-day additive contributions do not sum to prediction")
    payload = {
        "schema_version": 2, "model_id": contract["model_id"], "model_version": 2,
        "status": "shadow_research_published", "display_state": "research_model",
        "as_of": bundle.dates[-1], "knowledge_cutoff": cutoff, "anchor": anchor,
        "target": "NASDAQCOM", "transform": "daily_log_return",
        "probability_unit": "fraction", "probability_space": "research_timeseries_v2_conditional",
        "publication": {
            "customer_numbers_visible": True, "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
        },
        "gate": {"pass": True, "reasons": []},
        "horizons": summary["horizons"], "path_quantiles": summary["path_quantiles"],
        "history": [{"date": row.observation_time, "value": row.value} for row in nasdaq[-63:]],
        "future_dates": [
            day.isoformat() for day in future_trading_days(
                datetime.fromisoformat(bundle.dates[-1]).date(), 63, load_calendar_contract(root),
            )
        ],
        "contributions": {
            "exact_prediction": predicted,
            "sum": sum(contributions.values()),
            "rows": [{"name": name, "value": value} for name, value in contributions.items()],
        },
        "ensemble": {
            "expanding_weight": weights[0], "rolling_weight": weights[1],
            "weight_reason": weights[2], "path_count": simulated["index_paths"].shape[0],
            "path_hash": simulated["path_hash"],
        },
        "event_overlay": event_overlay,
        "monitoring_distributions": monitoring,
        "backtest": backtest["summary"], "backtest_run_id": backtest["run_id"],
        "model_run_id": manifest["run_id"], "data_summary": data_summary,
        "hashes": {
            "contract": frozen_hash(contract),
            "model_code": model_code_hash(root),
            "source_ledgers": _source_ledger_hashes(root),
            "feature_bundle": manifest["hashes"]["feature_bundle"],
            "model_fit_content": manifest["content_hash"],
            "path_content": simulated["path_hash"],
        },
        "ralph_run_id": ralph_run_id,
        "footnote": "*미국 시장·미국 공식 거시자료 기준",
    }
    forecast_id = f"tsv2-forecast-{canonical_hash(payload)[:24]}"
    payload["forecast_id"] = forecast_id
    append_unique(root, Path("data/timeseries_v2/ledgers/forecasts.jsonl"), payload, key="forecast_id")
    path = write_latest(root, payload)
    return path, payload


def resolve_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    """Append realized outcomes for matured V2 shadow forecasts."""
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    forecasts_path = root / FORECAST_LEDGER
    forecasts = [] if not forecasts_path.is_file() else [
        json.loads(line) for line in forecasts_path.read_text(encoding="utf-8").splitlines() if line
    ]
    resolutions_path = root / RESOLUTION_LEDGER
    prior = [] if not resolutions_path.is_file() else [
        json.loads(line) for line in resolutions_path.read_text(encoding="utf-8").splitlines() if line
    ]
    identities = {(row["forecast_id"], int(row["horizon_sessions"])) for row in prior}
    market = read_market_observations(root, knowledge_cutoff=cutoff)
    nasdaq = sorted(
        (row for row in market if row.series_id == "NASDAQCOM"),
        key=lambda row: row.observation_time,
    )
    by_day = {row.observation_time: row.value for row in nasdaq}
    days = sorted(by_day)
    appended = 0
    for forecast in forecasts:
        as_of = forecast["as_of"]
        if as_of not in by_day:
            continue
        start = days.index(as_of)
        for horizon in (1, 5, 21, 63):
            key = (forecast["forecast_id"], horizon)
            if key in identities or start + horizon >= len(days):
                continue
            end_day = days[start + horizon]
            end_rows = [row for row in nasdaq if row.observation_time == end_day]
            if not end_rows or end_rows[-1].available_at > cutoff:
                continue
            realized = by_day[end_day] / float(forecast["anchor"]) - 1.0
            realized_log = float(math.log(by_day[end_day] / float(forecast["anchor"])))
            monitor = (forecast.get("monitoring_distributions") or {}).get(str(horizon))
            payload = {
                "resolution_id": f"tsv2-resolution-{canonical_hash({'forecast': key, 'end': end_day, 'value': realized})[:24]}",
                "forecast_id": forecast["forecast_id"], "horizon_sessions": horizon,
                "as_of": as_of, "resolved_at": cutoff, "target_date": end_day,
                "realized_return": float(realized), "return_unit": "fraction",
                "actual_log_return": realized_log,
                "source": end_rows[-1].data_grade,
            }
            if monitor is not None:
                model_sample = np.asarray(monitor["model_sample"], dtype=float)
                baseline_samples = {
                    name: np.asarray(values, dtype=float)
                    for name, values in monitor["baseline_samples"].items()
                }
                quantiles = forecast["horizons"][str(horizon)]["quantiles"]
                payload.update({
                    "model_crps": sample_crps(model_sample, realized_log),
                    "baseline_crps": {
                        name: sample_crps(values, realized_log)
                        for name, values in baseline_samples.items()
                    },
                    "covered_p10_p90": bool(
                        float(quantiles["p10"]) <= by_day[end_day] <= float(quantiles["p90"])
                    ),
                    "covered_p25_p75": bool(
                        float(quantiles["p25"]) <= by_day[end_day] <= float(quantiles["p75"])
                    ),
                })
            if append_unique(root, RESOLUTION_LEDGER, payload, key="resolution_id"):
                appended += 1
                identities.add(key)
    return {"forecasts": len(forecasts), "existing": len(prior), "appended": appended}


def verify_timeseries_v2(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        contract = load_contract_v2(root)
    except Exception as exc:  # pragma: no cover - summarized for CLI
        return {"ok": False, "errors": [str(exc)]}
    lineage = verify_market_lineage(root)
    errors.extend(lineage["errors"])
    dfm_runtime_audit = verify_dfm_runtime_provenance(root)
    if not dfm_runtime_audit["ok"]:
        errors.append("DFM cache runtime provenance incomplete or incompatible")
    manifests = read_dfm_manifest(root)
    if manifests and any(row["contract_hash"] != frozen_hash(contract) for row in manifests):
        errors.append("DFM cache contract hash drift")
    ready_cutoffs: set[str] = set()
    for row in manifests:
        path = root / row["path"]
        if not path.is_file():
            errors.append(f"DFM cache missing: {row['cache_id']}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_hash = canonical_hash({
            key: value for key, value in payload.items() if key != "content_hash"
        })
        if payload.get("content_hash") != expected_hash or row.get("content_hash") != expected_hash:
            errors.append(f"DFM cache hash mismatch: {row['cache_id']}")
        if payload.get("cutoff") != row.get("cutoff"):
            errors.append(f"DFM cache cutoff mismatch: {row['cache_id']}")
        if row.get("status") == "ready" and row.get("contract_hash") == frozen_hash(contract):
            ready_cutoffs.add(str(row["cutoff"]))
    evaluation_start = str(contract["evaluation"]["outer_start"])
    macro_facts = read_facts(root)
    latest_cutoff = max((row.available_at for row in macro_facts), default=None)
    expected_evaluation_cutoffs = set()
    if latest_cutoff is not None:
        expected_evaluation_cutoffs = set(macro_release_cutoffs(
            macro_facts, start=evaluation_start, end=latest_cutoff,
        ))
    missing_dfm = sorted(expected_evaluation_cutoffs - ready_cutoffs)
    if missing_dfm:
        errors.append(f"DFM evaluation cache incomplete: {len(missing_dfm)} cutoff(s)")
    if expected_evaluation_cutoffs and not any(
        cutoff[:10] < evaluation_start for cutoff in ready_cutoffs
    ):
        errors.append("DFM has no ready warmup cache before 2007")
    sealed = _sealed_already_disclosed(
        root, model_id=contract["model_id"], contract_hash=frozen_hash(contract),
        replacement_model_code_hash=model_code_hash(root),
    )
    if sealed is not None and (sealed.get("hashes") or {}).get("model_code") != model_code_hash(root):
        errors.append("sealed V2 model code hash drift")
    latest = read_latest(root)
    if latest is not None and latest["publication"]["customer_numbers_visible"]:
        if sealed is None or sealed["summary"]["gate_pass"] is not True:
            errors.append("V2 numbers visible without passing sealed evidence")
        if latest["probability_unit"] != "fraction":
            errors.append("V2 published probability unit drift")
        if (latest.get("hashes") or {}).get("model_code") != model_code_hash(root):
            errors.append("published V2 model code hash drift")
        market = read_market_observations(root, knowledge_cutoff=latest["knowledge_cutoff"])
        freshness = _required_market_freshness(
            market, contract=contract, knowledge_cutoff=latest["knowledge_cutoff"],
        )
        if not freshness["ok"]:
            errors.append("published V2 numbers violate required-market freshness SLA")
    return {
        "ok": not errors, "errors": errors, "market_lineage": lineage,
        "dfm_cache_entries": len(manifests), "sealed_disclosed": sealed is not None,
        "dfm_expected_evaluation_cutoffs": len(expected_evaluation_cutoffs),
        "dfm_missing_evaluation_cutoffs": len(missing_dfm),
        "dfm_runtime_provenance": dfm_runtime_audit,
        "numbers_visible": bool(latest and latest["publication"]["customer_numbers_visible"]),
    }


def quick_backtest_timeseries_v2(
    root: Path, *, knowledge_cutoff: str | None = None,
) -> dict[str, Any]:
    """Non-sealed calculation smoke test used by Ralph after each repair.

    This never selects the frozen candidate winner and never writes a performance
    disclosure.  It exercises the actual five-dimensional Ridge VARX and
    correlated path code on a bounded trailing training slice.
    """
    contract = load_contract_v2(root)
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundle = assemble_candidate_bundle(
        root, contract=contract, macro_facts=read_facts(root),
        candidate_id="C1", knowledge_cutoff=cutoff,
    )
    if bundle.status != "ready":
        return {
            "ok": True, "status": "data_hold", "reason": list(bundle.missing_features),
            "sessions": len(bundle.dates), "sealed_evaluation_used": False,
        }
    start = max(0, len(bundle.dates) - 1400)
    endog = bundle.endogenous[start:]
    exog = bundle.exogenous[start:]
    fit = select_ridge_varx_v2(
        endog, exog, endog_names=bundle.endogenous_names, exog_names=bundle.exogenous_names,
        lag_candidates=contract["model"]["varx"]["lag_candidates"],
        alpha_candidates=contract["model"]["varx"]["ridge_alpha_candidates"],
    )
    simulated = simulate_correlated_paths_v2(
        (fit, fit), weights=(0.5, 0.5), endog_history=endog, exog_last=exog[-1],
        anchor=1.0, path_count=200, horizon=21, block_length=10, ewma_lambda=0.97,
        seed=deterministic_seed(contract["model_id"], 2, bundle.dates[-1]),
    )
    summary = summarize_paths(simulated["index_paths"], anchor=1.0, horizons=(1, 5, 21))
    monotonic = all(
        row["quantiles"]["p10"] <= row["quantiles"]["p25"] <= row["quantiles"]["p50"]
        <= row["quantiles"]["p75"] <= row["quantiles"]["p90"]
        for row in summary["horizons"].values()
    )
    contributions = fit.target_contributions(endog, exog[-1])
    prediction = float(fit.predict(endog, exog[-1])[0])
    additive = abs(sum(contributions.values()) - prediction) <= 1e-10
    return {
        "ok": monotonic and additive, "status": "pass" if monotonic and additive else "calculation_hold",
        "sessions": len(endog), "lag": fit.lag, "alpha": fit.alpha,
        "quantile_monotonic": monotonic, "contribution_additive": additive,
        "sealed_evaluation_used": False,
    }
