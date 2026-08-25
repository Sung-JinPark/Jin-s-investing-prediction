"""V5 collection, direct-distribution backtest, Gate, forecast and verification."""

from __future__ import annotations

import json
import os
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .artifact import LATEST_RELATIVE, validate_latest
from .contracts import MODEL_ID, MODEL_VERSION, PROBABILITY_SPACE, compare_protected, contract_hash, load_contract, model_code_hash, protected_manifest
from .evaluation import evaluate
from .features import feature_snapshot, load_research_frame
from .identifiers import content_hash, stable_id
from .lineage import ObservationVersion, verify_lineage
from .models import FROZEN_SPECS, QUANTILE_LEVELS, DirectDistributionModel, approximate_anchor_samples, choose_spec_inner, convex_mix_samples, empirical_crps
from .sources import HttpClient, SOURCE_REGISTRY, _available_at, collect_source, expanded_source_specs, sanitized_uri
from .storage.local_store import LocalControlPlane
from .storage.object_store import LocalObjectStore
from .storage.parquet_store import export_partition, write_manifest


V5_DATA = Path("data/timeseries_v5"); PRIVATE_DEFAULT = Path("outputs/timeseries_v5/private_store")
V4_POINTER = Path("data/timeseries_v4/multivariate_v4_latest.json")
PROTECTED_BASELINE = V5_DATA / "manifests/protected_baseline.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp"); temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8"); os.replace(temporary, path)


def _append_unique(path: Path, payload: dict[str, Any], *, identity: str) -> bool:
    """Append once and reject identity collisions with different content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            prior = json.loads(line)
            if prior.get(identity) == payload.get(identity):
                if prior != payload:
                    raise ValueError(f"append-only collision for {payload.get(identity)}")
                return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush(); os.fsync(handle.fileno())
    return True


def _v4_scores(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pointer = json.loads((root / V4_POINTER).read_text(encoding="utf-8")); run = json.loads((root / pointer["run_path"]).read_text(encoding="utf-8")); return run, list(run["scores"])


def initialize_v5(root: Path) -> dict[str, Any]:
    """Freeze the protected V1-V4/scenario/official baseline once."""
    load_contract(root); path = root / PROTECTED_BASELINE; current = protected_manifest(root)
    if path.is_file():
        prior = json.loads(path.read_text(encoding="utf-8")); comparison = compare_protected(prior["files"], current)
        if not comparison["ok"]: raise RuntimeError(f"protected V5 baseline drift: {comparison}")
        return prior
    value = {"created_at": datetime.now(timezone.utc).isoformat(), "files": current, "manifest_hash": content_hash(current)}; _atomic_json(path, value); return value


def collect_v5(root: Path, *, source_ids: list[str] | None = None, private_root: Path | None = None) -> dict[str, Any]:
    load_contract(root); selected = source_ids or [key for key, value in SOURCE_REGISTRY.items() if value.required_core or key in {"cboe_vix9d", "cboe_vix3m", "cboe_vvix", "cboe_skew", "ofr_fsi", "fed_ebp", "chicago_fed_nfci", "treasury_dts", "nyfed_reference_rates", "fed_h41_walcl", "fred_tga", "nyfed_rrp"}]
    unknown = sorted(set(selected) - set(SOURCE_REGISTRY))
    if unknown: raise ValueError(f"unknown V5 sources: {unknown}")
    store_root = private_root or root / PRIVATE_DEFAULT
    managed = bool(os.environ.get("TSV5_DATABASE_URL") and os.environ.get("TSV5_S3_BUCKET"))
    if managed:
        from .storage.config import ManagedStorageConfig
        from .storage.object_store import S3ObjectStore
        from .storage.postgres import PostgresControlPlane
        settings = ManagedStorageConfig.from_environment(); control = PostgresControlPlane(settings.database_url); control.migrate(root); objects = S3ObjectStore(bucket=settings.bucket, endpoint_url=settings.endpoint_url, access_key_id=settings.access_key_id, secret_access_key=settings.secret_access_key, quota_bytes=settings.quota_bytes, hold_fraction=settings.hold_fraction)
    else:
        control = LocalControlPlane(store_root); objects = LocalObjectStore(store_root)
    client = HttpClient(); run_id = stable_id("collect", {"sources": selected, "at": datetime.now(timezone.utc).isoformat()}); results = []
    for source_id in selected:
        for expanded in expanded_source_specs(SOURCE_REGISTRY[source_id]):
            try: results.append(collect_source(expanded, run_id=run_id, control=control, objects=objects, client=client))
            except Exception as exc: results.append({"source_id": source_id, "source_uri": sanitized_uri(expanded.url), "outcome": "collection_failed", "reason": f"{type(exc).__name__}:{exc}"})
    lineage = verify_lineage(control.rows("raw_receipts"), control.rows("parse_outcomes"), control.rows("observations"), control.rows("receipt_fact_links")); summary = {"run_id": run_id, "results": results, "lineage": lineage, "private_store": str(store_root), "generated_at": datetime.now(timezone.utc).isoformat()}
    _atomic_json(root / V5_DATA / "manifests/collection_latest.json", {**summary, "managed_store": managed, "private_store": "external_or_local_private_store"}); return summary


def materialize_v5(root: Path, *, private_root: Path | None = None) -> dict[str, Any]:
    store_root = private_root or root / PRIVATE_DEFAULT
    if os.environ.get("TSV5_DATABASE_URL"):
        from .storage.postgres import PostgresControlPlane
        control = PostgresControlPlane(os.environ["TSV5_DATABASE_URL"]); control.migrate(root)
    else: control = LocalControlPlane(store_root)
    receipts = control.rows("raw_receipts"); outcomes = control.rows("parse_outcomes"); rows = control.rows("observations"); links = control.rows("receipt_fact_links"); files = []
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in rows: by_source.setdefault(str(row["source_id"]), []).append(row)
    for source_id, selected in sorted(by_source.items()):
        files.append({"source_id": source_id, **export_partition(selected, store_root / f"parquet/observations/source_id={source_id}/observations.parquet", sort_keys=["series_id", "observation_time", "revision_seq"])})
    manifest = write_manifest(store_root / "parquet/observations/manifest.json", files)
    lineage = verify_lineage(receipts, outcomes, rows, links)
    public = {
        **manifest,
        "files": [{**row, "uri": f"private://observations/source_id={row['source_id']}/observations.parquet"} for row in files],
        "lineage": {
            **lineage,
            "receipt_linkage": lineage["observation_linkage"],
            "pit_leakage_count": 0 if lineage["ok"] else 1,
            "pit_mapping_rule": "available_at_to_first_xnas_close_at_or_after",
        },
    }
    _atomic_json(root / V5_DATA / "manifests/parquet_latest.json", public); return public


def reconcile_availability_v5(root: Path, *, private_root: Path | None = None) -> dict[str, Any]:
    """Append conservative availability revisions for reconstructed archives."""
    store_root = private_root or root / PRIVATE_DEFAULT
    if os.environ.get("TSV5_DATABASE_URL"):
        from .storage.postgres import PostgresControlPlane
        control = PostgresControlPlane(os.environ["TSV5_DATABASE_URL"]); control.migrate(root)
    else: control = LocalControlPlane(store_root)
    rows = control.rows("observations")
    active: dict[str, dict[str, Any]] = {}
    for row in rows:
        prior = active.get(str(row["observation_key"]))
        if prior is None or int(row["revision_seq"]) > int(prior["revision_seq"]): active[str(row["observation_key"])] = row
    appended = 0; corrected_by_source: dict[str, int] = {}; now = datetime.now(timezone.utc)
    pending_observations: list[dict[str, Any]] = []; pending_links: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal appended, pending_observations, pending_links
        if not pending_observations: return
        written = control.append_bundle([("observations", pending_observations, "observation_id"), ("receipt_fact_links", pending_links, "link_id")])
        if written % 2: raise RuntimeError("availability correction fact/link write mismatch")
        appended += written // 2; pending_observations = []; pending_links = []

    for row in active.values():
        source_id = str(row["source_id"])
        if source_id not in {"cftc_tff", "nyfed_cmdi"}: continue
        observation_day = datetime.fromisoformat(str(row["observation_time"]).replace("Z", "+00:00")).date().isoformat()
        expected = _available_at(SOURCE_REGISTRY[source_id], observation_day)
        current = datetime.fromisoformat(str(row["available_at"]).replace("Z", "+00:00"))
        if current == expected and row.get("parser_semantic_version") == "availability-v2": continue
        payload = {key: row.get(key) for key in ("series_id", "observation_time", "value", "unit", "data_grade", "dimensions", "vintage_start", "vintage_end", "normalization_rule_version")}
        payload.update({"available_at": expected, "parser_semantic_version": "availability-v2"})
        core = {**payload, "source_id": source_id, "receipt_id": row["receipt_id"], "raw_sha256": row["raw_sha256"], "observation_key": row["observation_key"], "revision_seq": int(row["revision_seq"]) + 1, "supersedes": row["observation_id"], "created_at": now}
        version = ObservationVersion(observation_id=stable_id("obs", core), **core).model_dump(mode="json")
        link = {"link_id": stable_id("link", [row["receipt_id"], version["observation_id"], "availability_revision"]), "receipt_id": row["receipt_id"], "observation_id": version["observation_id"], "relation": "availability_revision"}
        pending_observations.append(version); pending_links.append(link); corrected_by_source[source_id] = corrected_by_source.get(source_id, 0) + 1
        if len(pending_observations) >= 25_000: flush()
    flush()
    core = {"rule_version": "availability-v2", "corrected_by_source": corrected_by_source, "appended_observations": appended, "generated_at": now.isoformat()}
    correction = {**core, "correction_id": stable_id("availability-correction", core), "content_hash": content_hash(core)}
    control.append("normalization_corrections", correction, identity="correction_id")
    _atomic_json(root / V5_DATA / "manifests/availability_reconciliation_latest.json", correction)
    return correction


def mature_labels_v5(root: Path, *, private_root: Path | None = None) -> dict[str, Any]:
    """Materialize direct-horizon labels without moving their observation date."""
    _, features, targets, _, _ = load_research_frame(root)
    control = LocalControlPlane(private_root or root / PRIVATE_DEFAULT)
    appended = 0
    for origin_index, day in enumerate(features.index):
        for horizon in (1, 5, 21, 63):
            value = float(targets[horizon][origin_index])
            if not np.isfinite(value):
                continue
            matured_index = origin_index + horizon
            if matured_index >= len(features):
                continue
            core = {"origin": day.date().isoformat(), "horizon_sessions": horizon, "matured_at_session": features.index[matured_index].date().isoformat(), "target": "NASDAQCOM cumulative log return", "value": value, "unit": "signed_fraction", "data_grade": "reconstructed_market_archive"}
            row = {**core, "label_id": stable_id("tsv5-label", core), "content_hash": content_hash(core)}
            appended += int(control.append("labels", row, identity="label_id"))
    summary = {"label_count": len(control.rows("labels")), "appended": appended, "generated_at": datetime.now(timezone.utc).isoformat()}
    _atomic_json(root / V5_DATA / "manifests/labels_latest.json", summary)
    return summary


def train_v5(root: Path) -> dict[str, Any]:
    """Freeze the preregistered bundle; model fitting occurs origin-by-origin."""
    contract = load_contract(root)
    bundle = [{"id": "E0", "family": "fixed_anchor"}, *[dict(row) for row in FROZEN_SPECS]]
    maximum = int(contract["candidate_bundle"]["maximum_experiments"])
    if len(bundle) > maximum:
        raise RuntimeError(f"preregistered V5 experiment bundle exceeds {maximum}")
    return {"model_id": MODEL_ID, "contract_hash": contract_hash(root), "experiment_bundle_hash": content_hash(bundle), "experiment_count": len(bundle), "max_experiments": maximum, "event_local_projection": "blocked_until_60_independent_events", "frozen": True}


def gate_v5(root: Path) -> dict[str, Any]:
    pointer = json.loads((root / V5_DATA / "runs/backtest_latest.json").read_text(encoding="utf-8"))
    run = json.loads((root / pointer["path"]).read_text(encoding="utf-8"))
    return {"run_id": run["run_id"], "research_gate": run["research_gate"], "operational_gate": _operational_gate(root, run["data_cutoff"]), "numbers_visible": bool(run["research_gate"]["pass"] and _operational_gate(root, run["data_cutoff"])["pass"])}


def _apply_quantile_calibration(samples: np.ndarray, adjustments: dict[str, float]) -> np.ndarray:
    """Apply inner-fold quantile residuals and monotonically rearrange."""
    if not adjustments:
        return np.sort(np.asarray(samples, dtype=float))
    base = np.quantile(np.asarray(samples, dtype=float), QUANTILE_LEVELS)
    corrected = np.asarray([base[index] + float(adjustments.get(str(level), 0.0)) for index, level in enumerate(QUANTILE_LEVELS)])
    corrected = np.maximum.accumulate(corrected)
    u = (np.arange(len(samples), dtype=float) + 0.5) / len(samples)
    return np.sort(np.interp(u, QUANTILE_LEVELS, corrected))


def _select_weight(train_rows: list[dict[str, Any]], train_x: np.ndarray, train_y: np.ndarray, spec: dict[str, float], anchor_floor: float, *, feature_names: list[str]) -> tuple[float, dict[str, float]]:
    if len(train_y) < 220: return 0.0, {"reason": "insufficient_inner_history"}
    split = len(train_y) - 52
    model = DirectDistributionModel.fit(train_x[:split], train_y[:split], alpha=float(spec["alpha"]), df=float(spec["df"]), family=str(spec.get("family", "student_t_location_scale")), feature_names=feature_names)
    direct_samples = [model.predict(row, sample_count=512)["samples"] for row in train_x[split:]]
    anchor_samples = [
        approximate_anchor_samples(float(row["baseline_p10"]), float(row["baseline_p90"]), sample_count=512)
        for row in train_rows[split:]
    ]
    maximum_direct = 1.0 - anchor_floor
    weights = np.linspace(0.0, maximum_direct, 21)
    grid_scores: dict[str, float] = {}
    for weight in weights:
        losses = [
            empirical_crps(convex_mix_samples(anchor, direct, float(weight)), float(actual))
            for anchor, direct, actual in zip(anchor_samples, direct_samples, train_y[split:], strict=True)
        ]
        grid_scores[f"{weight:.6f}"] = float(np.mean(losses))
    weight = float(min(weights, key=lambda value: grid_scores[f"{value:.6f}"]))
    baseline = grid_scores["0.000000"]
    direct = float(np.mean([empirical_crps(samples, float(actual)) for samples, actual in zip(direct_samples, train_y[split:], strict=True)]))
    mixed_quantiles = np.asarray([
        np.quantile(convex_mix_samples(anchor, direct_sample, weight), QUANTILE_LEVELS)
        for anchor, direct_sample in zip(anchor_samples, direct_samples, strict=True)
    ])
    residuals = train_y[split:, None] - mixed_quantiles
    adjustments = {str(level): float(np.quantile(residuals[:, index], level)) for index, level in enumerate(QUANTILE_LEVELS)}
    return weight, {"direct_inner_crps": direct, "baseline_inner_crps": baseline, "selected_direct_weight": weight, "stacking_grid_crps": grid_scores, "quantile_calibration": adjustments, "calibration_origins": len(residuals)}


def backtest_v5(root: Path, *, sample_count: int = 4000, bootstrap_iterations: int | None = None, persist: bool = True) -> dict[str, Any]:
    contract = load_contract(root); protected_before = protected_manifest(root); v4, comparator_rows = _v4_scores(root); base, features, targets, _, metadata = load_research_frame(root); date_to_index = {day.date().isoformat(): index for index, day in enumerate(features.index)}; feature_values = features.to_numpy(dtype=float)
    output: list[dict[str, Any]] = []; selections: list[dict[str, Any]] = []
    for horizon in (1, 5, 21, 63):
        rows = sorted([row for row in comparator_rows if int(row["horizon"]) == horizon], key=lambda row: row["origin"]); floor = float(contract["ensemble"]["anchor_floor"][horizon]); cached: tuple[DirectDistributionModel, float, dict[str, Any]] | None = None
        for ordinal, row in enumerate(rows):
            origin_index = date_to_index[str(row["origin"])]; eligible = [prior for prior in rows[:ordinal] if date_to_index[str(prior["origin"])] <= origin_index - horizon - int(contract["evaluation"]["purge_sessions"]) - int(contract["evaluation"]["embargo_sessions"])]
            # 150 fitting + 52 validation + 14 inner purge rows are required.
            # Before that point the fixed comparator remains the only admissible
            # forecast; selecting an arbitrary first candidate would be leakage-prone.
            if len(eligible) >= 230 and (cached is None or ordinal % 26 == 0):
                indexes = np.asarray([date_to_index[str(prior["origin"])] for prior in eligible]); train_x = feature_values[indexes]; train_y = np.asarray([float(prior["actual"]) for prior in eligible]); specs = [{"alpha": float(spec["alpha"]), "df": float(spec["df"]), "id": str(spec["id"]), "family": str(spec["family"])} for spec in FROZEN_SPECS]
                feature_names = list(features.columns)
                selected, inner = choose_spec_inner(train_x, train_y, specs=specs, feature_names=feature_names); weight, weight_audit = _select_weight(eligible, train_x, train_y, selected, floor, feature_names=feature_names); model = DirectDistributionModel.fit(train_x, train_y, alpha=float(selected["alpha"]), df=float(selected["df"]), family=str(selected["family"]), feature_names=feature_names); audit = {"origin": row["origin"], "horizon": horizon, "training_rows": len(eligible), "training_last_origin": eligible[-1]["origin"], "selected_spec": selected, "active_feature_names": list(model.active_feature_names), "inner_crps": inner, **weight_audit}; selections.append(audit); cached = (model, weight, audit)
            actual = float(row["actual"]); anchor = approximate_anchor_samples(float(row["baseline_p10"]), float(row["baseline_p90"]), sample_count=sample_count)
            if cached is None or cached[1] == 0.0:
                p10, p25, p50, p75, p90 = (float(np.quantile(anchor, level)) for level in (.10, .25, .50, .75, .90)); model_crps = float(row["baseline_crps"]); quantiles = {"0.1": p10, "0.25": p25, "0.5": p50, "0.75": p75, "0.9": p90}; direct_weight = 0.0; spec_id = "E0"
            else:
                model, direct_weight, audit = cached; prediction = model.predict(feature_values[origin_index], sample_count=sample_count); mixed = convex_mix_samples(anchor, prediction["samples"], direct_weight); mixed = _apply_quantile_calibration(mixed, audit.get("quantile_calibration", {})); p10, p25, p50, p75, p90 = (float(np.quantile(mixed, value)) for value in (.10, .25, .50, .75, .90)); model_crps = empirical_crps(mixed, actual); quantiles = {str(level): float(np.quantile(mixed, level)) for level in QUANTILE_LEVELS}; spec_id = str(audit["selected_spec"]["id"])
            output.append({"origin": row["origin"], "horizon": horizon, "actual": actual, "model_crps": model_crps, "baseline_crps": float(row["baseline_crps"]), "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90, "baseline_p10": float(row["baseline_p10"]), "baseline_p90": float(row["baseline_p90"]), "quantiles": quantiles, "stress_regime": row["stress_regime"], "trend_regime": row["trend_regime"], "direct_weight": direct_weight, "selected_spec": spec_id})
    if bootstrap_iterations is not None: contract["evaluation"]["bootstrap"]["iterations"] = int(bootstrap_iterations)
    parquet_manifest_path = root / V5_DATA / "manifests/parquet_latest.json"
    parquet_manifest = json.loads(parquet_manifest_path.read_text(encoding="utf-8")) if parquet_manifest_path.is_file() else {}
    source_lineage = parquet_manifest.get("lineage") or {}
    leakage_count = int(source_lineage.get("pit_leakage_count", 0 if source_lineage.get("ok") else 1))
    linkage = float(source_lineage.get("receipt_linkage", 0.0))
    gate = evaluate(output, contract, pit_leakage_count=leakage_count, lineage_linkage=linkage)
    event_policy = v4.get("captured_event_policy") or {"minimum_history": 60, "observed_history": {}, "coefficient_weight": 0.0, "reason": "no captured event history"}
    latest_selection = {
        str(horizon): next((row for row in reversed(selections) if int(row["horizon"]) == horizon), None)
        for horizon in (1, 5, 21, 63)
    }
    core = {"schema_version": 5, "model_id": MODEL_ID, "model_version": MODEL_VERSION, "probability_space": PROBABILITY_SPACE, "probability_unit": "fraction", "status": "shadow_gate_pass" if gate["pass"] else "shadow_gate_hold", "contract_hash": contract_hash(root), "model_code_hash": model_code_hash(root), "comparator_run_id": v4["predecessor_run_id"], "comparator": contract["evaluation"]["fixed_comparator"], "data_cutoff": v4["data_cutoff"], "origin_count": len({row["origin"] for row in output}), "score_count": len(output), "sample_count": sample_count, "research_gate": gate, "source_lineage": source_lineage, "feature_metadata": metadata, "candidate_bundle": [{"id": "E0", "family": "fixed_anchor"}, *[dict(row) for row in FROZEN_SPECS]], "event_overlay": {**event_policy, "synthetic_backfill": False, "coefficient_use": False}, "selection_history_hash": content_hash(selections), "latest_selection_by_horizon": latest_selection, "protected_non_mutation": compare_protected(protected_before, protected_manifest(root)), "combined_with_official_forecasts": False, "combined_with_scenario_v5_2": False, "official_write": False}
    run_id = stable_id("tsv5-research", core); summary = {**core, "run_id": run_id}; summary["content_hash"] = content_hash(summary)
    full = {**summary, "scores": output, "selection_history": selections}; full["full_content_hash"] = content_hash(full)
    if persist:
        private = root / PRIVATE_DEFAULT / "backtests" / f"{run_id}.json"; _atomic_json(private, full); public = {**summary, "private_run_uri": f"private://backtests/{run_id}.json", "full_content_hash": full["full_content_hash"]}; _atomic_json(root / V5_DATA / "runs" / f"{run_id}.json", public); _atomic_json(root / V5_DATA / "runs/backtest_latest.json", {"run_id": run_id, "path": (V5_DATA / "runs" / f"{run_id}.json").as_posix(), "status": summary["status"], "content_hash": summary["content_hash"]})
    return full


def _operational_gate(root: Path, data_cutoff: str) -> dict[str, Any]:
    try:
        from .market_calendar import missing_completed_sessions
        today = datetime.now(timezone.utc).date().isoformat(); missing = missing_completed_sessions(data_cutoff, through_session=today); reasons = [] if missing <= 1 else [f"NASDAQ target is {missing} completed XNAS sessions stale"]
        return {"pass": not reasons, "reasons": reasons, "missing_completed_sessions": missing}
    except Exception as exc: return {"pass": False, "reasons": [f"canonical XNAS freshness unavailable: {type(exc).__name__}"], "missing_completed_sessions": None}


def forecast_v5(root: Path) -> dict[str, Any]:
    pointer = json.loads((root / V5_DATA / "runs/backtest_latest.json").read_text(encoding="utf-8")); backtest = json.loads((root / pointer["path"]).read_text(encoding="utf-8")); research = backtest["research_gate"]; operational = _operational_gate(root, backtest["data_cutoff"]); visible = bool(research["pass"] and operational["pass"])
    body: dict[str, Any] = {"schema_version": 5, "model_id": MODEL_ID, "model_version": MODEL_VERSION, "status": "shadow_research_visible" if visible else "shadow_validation_hold", "probability_space": PROBABILITY_SPACE, "probability_unit": "fraction", "numbers_visible": visible, "as_of": backtest["data_cutoff"], "knowledge_cutoff": datetime.now(timezone.utc).isoformat(), "research_gate": research, "operational_gate": operational, "backtest_run_id": backtest["run_id"], "combined_with_existing_models": False, "label": "연구모델 · 기존 전망과 미결합", "footnote": "*미국 시장·미국 공식 거시자료 기준", "horizons": {}, "path": {}}
    if visible:
        _, comparator_rows = _v4_scores(root)
        _, features, targets, _, metadata = load_research_frame(root)
        origin_index = len(features) - 1
        origin = features.index[origin_index].date().isoformat()
        date_to_index = {day.date().isoformat(): index for index, day in enumerate(features.index)}
        feature_values = features.to_numpy(dtype=float)
        endpoint_samples: dict[int, np.ndarray] = {}
        horizon_rows: dict[str, Any] = {}
        contribution_rows: list[dict[str, Any]] = []
        ensemble_rows: dict[str, Any] = {}
        contract = load_contract(root)
        for horizon in (1, 5, 21, 63):
            history = [row for row in comparator_rows if int(row["horizon"]) == horizon and str(row["origin"]) < origin]
            latest_selection = (backtest.get("latest_selection_by_horizon") or {}).get(str(horizon))
            if latest_selection is None or len(history) < 156:
                raise RuntimeError(f"V5 horizon {horizon} has no mature selected training state")
            train_indexes = np.asarray([date_to_index[str(row["origin"])] for row in history if str(row["origin"]) in date_to_index])
            train_indexes = train_indexes[train_indexes <= origin_index - horizon]
            train_x = feature_values[train_indexes]
            train_y = np.asarray(targets[horizon], dtype=float)[train_indexes]
            spec = latest_selection["selected_spec"]
            model = DirectDistributionModel.fit(train_x, train_y, alpha=float(spec["alpha"]), df=float(spec["df"]), family=str(spec["family"]), feature_names=list(features.columns))
            direct = model.predict(feature_values[origin_index], sample_count=20000)
            historical = np.asarray(targets[horizon], dtype=float)[max(0, origin_index - 2520):origin_index - horizon + 1]
            historical = historical[np.isfinite(historical)]
            if len(historical) < 100:
                raise RuntimeError(f"V5 horizon {horizon} anchor history is incomplete")
            positions = (np.arange(20000, dtype=float) + 0.5) / 20000
            anchor = np.quantile(historical, positions)
            floor = float(contract["ensemble"]["anchor_floor"][horizon])
            direct_weight = min(1.0 - floor, float(latest_selection.get("selected_direct_weight", 0.0)))
            mixed = convex_mix_samples(anchor, direct["samples"], direct_weight)
            mixed = _apply_quantile_calibration(mixed, latest_selection.get("quantile_calibration", {}))
            endpoint_samples[horizon] = mixed
            quantile_returns = {f"p{int(level * 100):02d}": float(np.quantile(mixed, level)) for level in QUANTILE_LEVELS}
            up_probability = float(np.mean(mixed > 0.0))
            horizon_rows[str(horizon)] = {"horizon_sessions": horizon, "point_return": float(np.median(mixed)), "median_index": None, "quantiles": quantile_returns, "up_probability": up_probability, "probability_up": up_probability, "direct_weight": direct_weight, "anchor_weight": 1.0 - direct_weight, "selected_spec": spec["id"]}
            ensemble_rows[str(horizon)] = {"direct": direct_weight, "fixed_anchor": 1.0 - direct_weight}
            if horizon == 1:
                design = model._design(feature_values[origin_index])
                raw = design * model.location_coef * direct_weight
                contribution_rows.append({"name": "fixed_anchor", "value": float((1.0 - direct_weight) * np.median(anchor))})
                contribution_rows.append({"name": "direct_intercept", "value": float(raw[0])})
                active_count = len(model.active_feature_names)
                contribution_rows.extend({"name": str(name), "value": float(value)} for name, value in zip(model.active_feature_names, raw[1:1 + active_count], strict=True))
                if len(raw) > 1 + active_count: contribution_rows.append({"name": "nonlinear_or_regime_terms", "value": float(np.sum(raw[1 + active_count:]))})

        pd = __import__("pandas")
        market = pd.read_parquet(root / "data/timeseries_v2/parquet/market_observations.parquet")
        nasdaq = market.loc[market["series_id"] == "NASDAQCOM"].sort_values(["observation_time", "revision_seq"]).drop_duplicates("observation_time", keep="last")
        nasdaq = nasdaq.loc[nasdaq["observation_time"].astype(str) <= origin]
        if nasdaq.empty:
            raise RuntimeError("V5 NASDAQ index anchor is unavailable")
        anchor_value = float(nasdaq.iloc[-1]["value"]); anchor_date = str(nasdaq.iloc[-1]["observation_time"])
        for row in horizon_rows.values():
            row["median_index"] = anchor_value * math.exp(float(row["quantiles"]["p50"]))
            row["quantiles"] = {key: anchor_value * math.exp(value) for key, value in row["quantiles"].items()}
        from .market_calendar import future_sessions
        future_dates = future_sessions(anchor_date, 63)
        path: dict[str, Any] = {"history_dates": [str(value) for value in nasdaq.tail(63)["observation_time"]], "history_index": [float(value) for value in nasdaq.tail(63)["value"]], "dates": future_dates}
        knots = np.asarray([0, 1, 5, 21, 63], dtype=float)
        for key, level in (("p10", .10), ("p25", .25), ("p50", .50), ("p75", .75), ("p90", .90)):
            levels = np.asarray([anchor_value] + [anchor_value * math.exp(float(np.quantile(endpoint_samples[h], level))) for h in (1, 5, 21, 63)])
            path[key] = [float(value) for value in np.exp(np.interp(np.arange(1, 64), knots, np.log(levels)))]
        exact_prediction = float(sum(row["value"] for row in contribution_rows))
        ranked = sorted(contribution_rows, key=lambda row: abs(float(row["value"])), reverse=True)
        ui_metrics = {str(horizon): {"crps_improvement_vs_best": row["improvement"], "coverage_p10_p90": row["p10_p90_coverage"], "coverage_p25_p75": row["p25_p75_coverage"]} for horizon, row in research["by_horizon"].items()}
        body.update({"forecast_id": stable_id("tsv5-forecast", {"as_of": anchor_date, "run_id": backtest["run_id"]}), "as_of": anchor_date, "anchor": {"date": anchor_date, "value": anchor_value, "unit": "NASDAQ Composite index"}, "horizons": horizon_rows, "path": path, "contributions_1d": {"exact_prediction": exact_prediction, "sum": exact_prediction, "components": {row["name"]: row["value"] for row in ranked[:7]}}, "ensemble": {"path_count": 20000, "weights": ensemble_rows}, "backtest": {"metrics": {"horizons": ui_metrics}, "run_id": backtest["run_id"]}, "freshness": {"feature_origin": origin, "market_anchor": anchor_date, "data_grade": metadata["data_grade"]}})
    body["content_hash"] = content_hash(body)
    validate_latest(body)
    if body.get("forecast_id"):
        _append_unique(root / V5_DATA / "ledgers/forecasts.jsonl", body, identity="forecast_id")
    _atomic_json(root / LATEST_RELATIVE, body); return body


def resolve_v5(root: Path) -> dict[str, Any]:
    """Append outcomes for matured visible forecasts; never rewrites forecasts."""
    ledger = root / V5_DATA / "ledgers/forecasts.jsonl"
    if not ledger.is_file():
        return {"resolved": 0, "reason": "no visible V5 forecasts"}
    pd = __import__("pandas")
    market = pd.read_parquet(root / "data/timeseries_v2/parquet/market_observations.parquet")
    nasdaq = market.loc[market["series_id"] == "NASDAQCOM"].sort_values(["observation_time", "revision_seq"]).drop_duplicates("observation_time", keep="last")
    values = {str(row["observation_time"]): float(row["value"]) for _, row in nasdaq.iterrows()}
    dates = sorted(values); appended = 0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        forecast = json.loads(line); as_of = str(forecast["as_of"])
        if as_of not in dates:
            continue
        position = dates.index(as_of); anchor = float(forecast["anchor"]["value"])
        for horizon in (1, 5, 21, 63):
            if position + horizon >= len(dates):
                continue
            maturity = dates[position + horizon]
            core = {"forecast_id": forecast["forecast_id"], "horizon_sessions": horizon, "matured_at_session": maturity, "actual_log_return": math.log(values[maturity] / anchor), "unit": "signed_fraction", "resolved_at": datetime.now(timezone.utc).isoformat()}
            row = {**core, "resolution_id": stable_id("tsv5-resolution", {"forecast_id": forecast["forecast_id"], "horizon": horizon}), "content_hash": content_hash(core)}
            appended += int(_append_unique(root / V5_DATA / "ledgers/resolutions.jsonl", row, identity="resolution_id"))
    return {"resolved": appended}


def verify_v5(root: Path, *, private_root: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []; contract = load_contract(root); latest_path = root / LATEST_RELATIVE
    if latest_path.is_file():
        try: validate_latest(json.loads(latest_path.read_text(encoding="utf-8")))
        except (ValueError, json.JSONDecodeError) as exc: errors.append(str(exc))
    else: errors.append("V5 latest projection missing")
    store_root = private_root or root / PRIVATE_DEFAULT; control = LocalControlPlane(store_root); receipts = control.rows("raw_receipts")
    if receipts:
        lineage = verify_lineage(receipts, control.rows("parse_outcomes"), control.rows("observations"), control.rows("receipt_fact_links"))
    else:
        manifest_path = root / V5_DATA / "manifests/parquet_latest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        lineage = manifest.get("lineage") or {"ok": False, "errors": ["V5 lineage manifest missing"]}
    if not lineage["ok"]: errors.extend(lineage.get("errors", []))
    baseline_path = root / PROTECTED_BASELINE
    if not baseline_path.is_file(): errors.append("V5 protected baseline missing"); comparison = {"ok": False, "added": [], "removed": [], "changed": []}
    else: comparison = compare_protected(json.loads(baseline_path.read_text(encoding="utf-8"))["files"], protected_manifest(root)); errors.extend([f"protected drift:{item}" for item in comparison.get("changed", [])])
    return {"ok": not errors, "errors": errors, "model_id": MODEL_ID, "contract_hash": contract_hash(root), "lineage": lineage, "protected_non_mutation": comparison, "automatic_champion": contract["promotion"]["automatic_promotion"], "official_write": False}
