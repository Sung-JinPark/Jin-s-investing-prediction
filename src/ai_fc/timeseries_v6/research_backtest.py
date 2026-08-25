"""Nested development selection and sealed V6 research evaluation."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .distribution_models import (
    E0ExactAnchor,
    E1QuantileElasticNet,
    E2StudentT,
    E3QuantileHGB,
    E4BayesianDynamicLinear,
    E5SoftRegimePartialPooling,
    E6AsymmetricEVTTail,
    E7PITAnalogTrajectory,
    DistributionForecast,
    convex_sample_mixture,
    empirical_crps,
)
from .research_dataset import ResearchDataset


class ResearchBacktestError(RuntimeError):
    pass


CANDIDATE_IMPLEMENTATION_VERSION = {
    "E1": "quantile_elastic_net_deterministic_runtime_v2",
    "E2": "student_t_location_scale_v1",
    "E3": "quantile_hgb_contract_v1",
    "E4": "bayesian_filtered_dlm_v1",
    "E5": "soft_regime_balanced_ess_v2",
    "E6": "asymmetric_evt_tail_v1",
    "E7": "pit_analog_trajectory_v1",
}


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def candidate_feature_profile(dataset: ResearchDataset, candidate_id: str) -> tuple[np.ndarray, str, str]:
    """Return the frozen data-grade profile for a candidate family.

    Core candidates use only reconstructed market archives.  The remaining
    challenger families may use reconstructed official archives, but their
    selection receipt says so explicitly.  This prevents the archive grade from
    being silently upgraded to native PIT evidence.
    """

    if candidate_id in {"E1", "E2", "E3"}:
        core_series = {"NASDAQCOM", "VIX", "VIX9D", "VIX3M", "VVIX", "SKEW", "DGS2", "T10Y2Y", "DTWEXBGS"}
        indexes = np.asarray(
            [index for index, series_id in enumerate(dataset.feature_series_ids) if series_id in core_series],
            dtype=int,
        )
        profile = "public_market_core_reconstructed_archive"
    else:
        indexes = np.arange(len(dataset.feature_names), dtype=int)
        profile = "official_archive_challenger"
    if len(indexes) == 0:
        raise ResearchBacktestError(f"candidate {candidate_id} has no eligible features")
    profile_hash = canonical_hash(
        {
            "base_dataset_hash": dataset.content_hash,
            "profile": profile,
            "features": [dataset.feature_names[index] for index in indexes],
            "grades": [dataset.feature_data_grades[index] for index in indexes],
        }
    )
    return indexes, profile, profile_hash


def candidate_grid(candidate_id: str) -> list[dict[str, Any]]:
    if candidate_id == "E1":
        return [{"alpha": alpha, "l1_ratio": ratio, "max_iter": 10000, "tolerance": 1e-7} for alpha in (0.0001, 0.001, 0.01, 0.1) for ratio in (0.1, 0.5, 0.9)]
    if candidate_id == "E2":
        return [{"degrees_of_freedom": df, "ridge_alpha": alpha, "scale_floor": 1e-6} for df in (4, 6, 8, 12) for alpha in (0.01, 0.1, 1.0)]
    if candidate_id == "E3":
        return [
            {"learning_rate": lr, "max_leaf_nodes": leaves, "max_iter": iterations, "l2_regularization": l2, "min_samples_leaf": minimum}
            for lr in (0.03, 0.07) for leaves in (7, 15) for iterations in (100, 300)
            for l2 in (0.0, 1.0) for minimum in (20, 50)
        ]
    if candidate_id == "E4":
        return [
            {"state_discount": discount, "prior_variance": prior}
            for discount in (0.98, 0.995)
            for prior in (1.0, 10.0)
        ]
    if candidate_id == "E5":
        return [
            {
                "global_shrinkage": shrinkage,
                "regime_count": 3,
                "minimum_effective_sample_size": 50,
            }
            for shrinkage in (0.25, 0.50, 0.75)
        ]
    if candidate_id == "E6":
        return [
            {
                "threshold_quantile": threshold,
                "minimum_exceedances_per_tail": 40,
                "shape_bounds": (-0.45, 0.45),
            }
            for threshold in (0.90, 0.95)
        ]
    if candidate_id == "E7":
        return [
            {"neighbor_count": count, "minimum_temporal_spacing_sessions": 126}
            for count in (10, 20, 40)
        ]
    raise ResearchBacktestError(f"unsupported selection candidate: {candidate_id}")


def _fit(candidate_id: str, x: np.ndarray, y: np.ndarray, spec: dict[str, Any]):
    if candidate_id == "E1": return E1QuantileElasticNet.fit(x, y, **spec)
    if candidate_id == "E2": return E2StudentT.fit(x, y, **spec)
    if candidate_id == "E3": return E3QuantileHGB.fit(x, y, **spec)
    if candidate_id == "E4": return E4BayesianDynamicLinear.fit(x, y, **spec)
    if candidate_id == "E5": return E5SoftRegimePartialPooling.fit(x, y, **spec)
    if candidate_id == "E6": return E6AsymmetricEVTTail.fit(x, y, **spec)
    if candidate_id == "E7": return E7PITAnalogTrajectory.fit(x, y, **spec)
    raise ResearchBacktestError(candidate_id)


def development_folds(origins: tuple[str, ...]) -> list[tuple[np.ndarray, np.ndarray]]:
    dates = np.asarray(origins)
    development = np.where((dates >= "2007-01-01") & (dates <= "2018-12-31"))[0]
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for validation_start in ("2013-01-01", "2015-01-01", "2017-01-01"):
        start = int(np.searchsorted(dates, validation_start))
        validation = np.arange(start, min(start + 52, len(dates)))
        validation = validation[dates[validation] <= "2018-12-31"]
        # The frozen 1996-2006 initial-training segment and all development
        # observations strictly before the purge boundary are available to the
        # inner fit.  Only validation origins remain in 2007-2018.
        train = np.arange(0, max(0, start - 68))
        if len(train) >= 200 and len(validation) >= 40:
            folds.append((train, validation))
    if len(folds) != 3:
        raise ResearchBacktestError("three purged development folds are required")
    return folds


class JsonlExperimentLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line); self.rows[row["experiment_id"]] = row

    def append(self, row: dict[str, Any]) -> None:
        experiment_id = row["experiment_id"]
        if experiment_id in self.rows:
            if self.rows[experiment_id] != row: raise ResearchBacktestError("experiment identity collision")
            return
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        self.rows[experiment_id] = row


def _evaluate_spec_process(
    candidate_id: str,
    horizon: int,
    spec: dict[str, Any],
    folds: list[tuple[np.ndarray, np.ndarray]],
    candidate_features: np.ndarray,
    target: np.ndarray,
    dataset_hash: str,
    feature_profile: str,
    profile_hash: str,
    existing_rows: dict[str, dict[str, Any]],
) -> tuple[float | None, dict[str, Any], str, list[dict[str, Any]]]:
    """Evaluate one frozen coordinate in an isolated process."""

    spec_hash = canonical_hash(spec)
    implementation_version = CANDIDATE_IMPLEMENTATION_VERSION[candidate_id]
    losses: list[float] = []
    failed = None
    pending: list[dict[str, Any]] = []
    for fold_index, (train, validation) in enumerate(folds):
        # Implementation identity is part of every immutable experiment key.
        # This prevents a numerical-runtime or estimator correction from
        # silently reusing a result produced by older code.
        implementation_tag = f"-{implementation_version}"
        experiment_id = (
            f"{candidate_id}{implementation_tag}-{profile_hash[:12]}-"
            f"h{horizon}-{spec_hash[:12]}-f{fold_index}"
        )
        existing = existing_rows.get(experiment_id)
        if existing:
            if existing["status"] == "succeeded":
                losses.append(existing["mean_crps"])
            else:
                failed = existing["reason"]
            continue
        try:
            model = _fit(candidate_id, candidate_features[train], target[train], spec)
            fold_losses = [
                empirical_crps(model.predict(candidate_features[index]).samples, float(target[index]))
                for index in validation
            ]
            row = {
                "experiment_id": experiment_id,
                "candidate_id": candidate_id,
                "horizon": horizon,
                "fold": fold_index,
                "spec": spec,
                "spec_hash": spec_hash,
                "implementation_version": implementation_version,
                "status": "succeeded",
                "mean_crps": float(np.mean(fold_losses)),
                "origin_count": len(validation),
                "dataset_hash": dataset_hash,
                "feature_profile": feature_profile,
                "feature_profile_hash": profile_hash,
            }
            pending.append(row)
            losses.append(row["mean_crps"])
        except Exception as exc:
            row = {
                "experiment_id": experiment_id,
                "candidate_id": candidate_id,
                "horizon": horizon,
                "fold": fold_index,
                "spec": spec,
                "spec_hash": spec_hash,
                "implementation_version": implementation_version,
                "status": "failed",
                "reason": f"{type(exc).__name__}:{exc}",
                "dataset_hash": dataset_hash,
                "feature_profile": feature_profile,
                "feature_profile_hash": profile_hash,
            }
            pending.append(row)
            failed = row["reason"]
    score = float(np.mean(losses)) if failed is None and len(losses) == len(folds) else None
    return score, spec, spec_hash, pending


def select_candidate(
    dataset: ResearchDataset,
    candidate_id: str,
    ledger_path: Path,
    *,
    horizons: tuple[int, ...] | None = None,
    max_workers: int = 8,
) -> dict[str, Any]:
    ledger = JsonlExperimentLedger(ledger_path)
    folds = development_folds(dataset.origins)
    feature_indexes, feature_profile, profile_hash = candidate_feature_profile(dataset, candidate_id)
    candidate_features = dataset.features[:, feature_indexes]
    selections: dict[str, Any] = {}
    supported_horizons = {
        "E1": (1, 5, 21, 63),
        "E2": (1, 5, 21, 63),
        "E3": (1, 5, 21, 63),
        "E4": (1, 5, 21, 63),
        "E5": (1, 5, 21, 63),
        "E6": (5, 21, 63),
        "E7": (21, 63),
    }[candidate_id]
    selected_horizons = supported_horizons if horizons is None else tuple(h for h in supported_horizons if h in horizons)
    if not selected_horizons:
        raise ResearchBacktestError(f"candidate {candidate_id} has no requested supported horizons")
    for horizon in selected_horizons:
        target = dataset.labels[horizon]
        scored: list[tuple[float, dict[str, Any], str]] = []
        # Process isolation avoids Python-level estimator contention.  Result
        # order is still irrelevant because tie-breaking is score/spec-hash
        # deterministic and only the parent process appends to the ledger.
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _evaluate_spec_process,
                    candidate_id,
                    horizon,
                    spec,
                    folds,
                    candidate_features,
                    target,
                    dataset.content_hash,
                    feature_profile,
                    profile_hash,
                    ledger.rows,
                )
                for spec in candidate_grid(candidate_id)
            ]
            for future in as_completed(futures):
                score, spec, spec_hash, pending = future.result()
                for row in pending:
                    ledger.append(row)
                if score is not None:
                    scored.append((score, spec, spec_hash))
        if not scored: raise ResearchBacktestError(f"all {candidate_id} specs failed for horizon {horizon}")
        score, spec, spec_hash = min(scored, key=lambda item: (item[0], item[2]))
        selections[str(horizon)] = {
            "mean_inner_crps": score,
            "spec": spec,
            "spec_hash": spec_hash,
            "fold_count": len(folds),
            "implementation_version": CANDIDATE_IMPLEMENTATION_VERSION[candidate_id],
        }
    return {"schema_version": 1, "candidate_id": candidate_id, "implementation_version": CANDIDATE_IMPLEMENTATION_VERSION[candidate_id], "dataset_hash": dataset.content_hash, "feature_profile": feature_profile, "feature_profile_hash": profile_hash, "feature_names": [dataset.feature_names[index] for index in feature_indexes], "selection": selections, "selection_hash": canonical_hash(selections)}


def _stress_regime(origin: str) -> str:
    if "2008-01-01" <= origin <= "2009-06-30": return "gfc"
    if "2020-02-01" <= origin <= "2020-06-30": return "pandemic"
    if "2022-01-01" <= origin <= "2022-12-31": return "tightening"
    if "2023-01-01" <= origin <= "2023-12-31": return "rebound"
    return "normal"


def sealed_backtest(dataset: ResearchDataset, selections: dict[str, dict[str, Any]], *, refit_every: int = 13) -> list[dict[str, Any]]:
    dates = np.asarray(dataset.origins)
    sealed = np.where(dates >= "2019-01-01")[0]
    rows: list[dict[str, Any]] = []
    floors = {1: 0.20, 5: 0.25, 21: 0.40, 63: 0.50}
    for horizon in (1, 5, 21, 63):
        choice = selections[str(horizon)]
        candidate_id = choice["candidate_id"]
        expected_implementation = CANDIDATE_IMPLEMENTATION_VERSION[candidate_id]
        if choice.get("implementation_version") != expected_implementation:
            raise ResearchBacktestError(
                f"sealed implementation mismatch for {candidate_id}: "
                f"{choice.get('implementation_version')} != {expected_implementation}"
            )
        spec = choice["spec"]
        feature_indexes, feature_profile, profile_hash = candidate_feature_profile(dataset, candidate_id)
        candidate_features = dataset.features[:, feature_indexes]
        if choice.get("feature_profile_hash") not in {None, profile_hash}:
            raise ResearchBacktestError("sealed feature profile differs from selected profile")
        model = None
        for position, index in enumerate(sealed):
            train = np.arange(0, index - 68)
            if len(train) < 250: continue
            if model is None or position % refit_every == 0:
                model = _fit(candidate_id, candidate_features[train], dataset.labels[horizon][train], spec)
            anchor = E0ExactAnchor.fit(dataset.labels[horizon][train]).predict()
            direct = model.predict(candidate_features[index])
            ensemble = convex_sample_mixture([anchor, direct], np.asarray([floors[horizon], 1 - floors[horizon]]))
            actual = float(dataset.labels[horizon][index])
            rows.append({
                "origin": dataset.origins[index], "horizon": horizon, "actual": actual,
                "candidate_id": candidate_id, "anchor_floor": floors[horizon],
                "implementation_version": expected_implementation,
                "feature_profile": feature_profile, "feature_profile_hash": profile_hash,
                "model_crps": empirical_crps(ensemble.samples, actual),
                "baseline_crps": empirical_crps(anchor.samples, actual),
                "p01": float(ensemble.quantiles[0]), "p10": float(ensemble.quantiles[2]),
                "p25": float(ensemble.quantiles[3]), "p50": float(ensemble.quantiles[4]),
                "p75": float(ensemble.quantiles[5]), "p90": float(ensemble.quantiles[6]),
                "p99": float(ensemble.quantiles[-1]), "up_probability": ensemble.up_probability,
                "baseline_p10": float(anchor.quantiles[2]), "baseline_p90": float(anchor.quantiles[6]),
                "stress_regime": _stress_regime(dataset.origins[index]),
            })
    return rows
