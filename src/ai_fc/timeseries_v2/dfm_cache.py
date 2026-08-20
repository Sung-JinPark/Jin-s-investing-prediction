"""Origin-specific DynamicFactorMQ cache for V2.

Every cache entry is fitted from the ALFRED facts that were available at its
release cutoff.  A later cache entry is never linked to an earlier forecast
origin.  Failed fits are recorded and are not silently replaced by a future fit.
"""

from __future__ import annotations

import json
import os
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from ai_fc.facts import ObservationFact
from ai_fc.timeseries.features import _deps as _dfm_deps
from ai_fc.timeseries.features import _monthly_panel

from .contracts import (
    DFM_CACHE_RELATIVE,
    LEDGER_RELATIVE,
    TimeSeriesV2ContractError,
    canonical_hash,
    frozen_hash,
    require_dfm_runtime,
    runtime_manifest,
)


DFM_MANIFEST = LEDGER_RELATIVE / "dfm_cache_manifest.jsonl"
FACTOR_SERIES = {
    "PAYEMS", "UNRATE", "INDPRO", "RSAFS", "HOUST", "GDPC1",
    "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE",
}


class DFMCacheError(RuntimeError):
    """Origin-specific DFM cache failed its PIT or replay contract."""


def fit_dynamic_factor_snapshot(
    facts: list[ObservationFact], *, knowledge_cutoff: str,
    start_parameters: dict[str, list[float]] | None = None,
    tolerance: float = 1e-5,
    cold_max_iterations: int = 300,
    warm_max_iterations: int = 300,
) -> dict[str, Any]:
    """Fit the two frozen factors, warm-starting only from an earlier PIT fit."""
    _, DynamicFactorMQ = _dfm_deps()
    groups = {
        "growth_factor": ("PAYEMS", "UNRATE", "INDPRO", "RSAFS", "HOUST", "GDPC1"),
        "inflation_factor": ("CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"),
    }
    states: dict[str, float | None] = {}
    converged: dict[str, bool] = {}
    parameters: dict[str, list[float]] = {}
    diagnostics: dict[str, dict[str, Any]] = {}
    for factor_name, series_ids in groups.items():
        panel, rows = _monthly_panel(facts, series_ids, knowledge_cutoff)
        usable = panel.dropna(axis=1, how="all").replace([np.inf, -np.inf], np.nan)
        if usable.shape[1] < 2 or usable.dropna(how="all").shape[0] < 36:
            states[factor_name] = None
            converged[factor_name] = False
            diagnostics[factor_name] = {
                "reason": "insufficient_origin_pit_panel",
                "rows": int(usable.dropna(how="all").shape[0]),
                "series": int(usable.shape[1]),
            }
            continue
        quarterly = None
        if factor_name == "growth_factor" and "GDPC1" in usable:
            quarterly = usable[["GDPC1"]].copy()
            quarterly.index = quarterly.index.asfreq("Q")
            quarterly = quarterly.groupby(level=0).last().sort_index().dropna(how="all")
            usable = usable.drop(columns=["GDPC1"])
        usable = usable.sort_index()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = DynamicFactorMQ(
                usable, endog_quarterly=quarterly, factors=1, factor_orders=1,
                idiosyncratic_ar1=True, standardize=True,
            )
            prior = None if start_parameters is None else start_parameters.get(factor_name)
            if prior is not None and len(prior) != int(model.k_params):
                prior = None
            max_iterations = cold_max_iterations if prior is None else warm_max_iterations
            result = model.fit_em(
                start_params=prior, maxiter=max_iterations,
                tolerance=tolerance, disp=False,
            )
            factor = result.factors.filtered.iloc[:, 0].dropna()
        messages = [str(item.message) for item in caught]
        retvals = getattr(result, "mle_retvals", {}) or {}
        likelihood = np.asarray(retvals.get("llf", []), dtype=float)
        criterion = None
        if likelihood.size >= 2 and np.isfinite(likelihood[-2:]).all() and likelihood[-2] != 0:
            criterion = float(abs((likelihood[-1] - likelihood[-2]) / likelihood[-2]))
        decreased = any("Log-likelihood decreased" in message for message in messages)
        states[factor_name] = None if factor.empty else float(factor.iloc[-1])
        parameters[factor_name] = [float(value) for value in result.params]
        finite = bool(
            states[factor_name] is not None
            and np.isfinite(states[factor_name])
            and np.isfinite(np.asarray(parameters[factor_name], dtype=float)).all()
            and np.isfinite(float(result.llf))
        )
        converged[factor_name] = bool(
            finite and not decreased and criterion is not None and criterion <= tolerance
        )
        diagnostics[factor_name] = {
            "rows": int(usable.dropna(how="all").shape[0]),
            "series": int(usable.shape[1]),
            "warm_start": prior is not None,
            "iterations": int(retvals.get("iter", max_iterations)),
            "maximum_iterations": int(max_iterations),
            "relative_log_likelihood_change": criterion,
            "tolerance": float(tolerance),
            "finite_state_and_parameters": finite,
            "log_likelihood_decreased": decreased,
            "warnings": messages,
        }
    return {
        "states": states,
        "converged": converged,
        "parameters": parameters,
        "diagnostics": diagnostics,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                identity = str(row.get("manifest_id") or row["cache_id"])
                existing[identity] = row
    manifest_id = str(payload.get("manifest_id") or payload["cache_id"])
    if manifest_id in existing:
        if existing[manifest_id] != payload:
            raise DFMCacheError(f"DFM cache manifest collision: {manifest_id}")
        return
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def factor_input_hash(facts: Iterable[ObservationFact], *, cutoff: str) -> str:
    cutoff_dt = datetime.fromisoformat(cutoff)
    rows = sorted(
        (
            row.model_dump(mode="json")
            for row in facts
            if row.series_id in FACTOR_SERIES and datetime.fromisoformat(row.available_at) <= cutoff_dt
        ),
        key=lambda row: (
            row["series_id"], row["observation_time"], row["available_at"],
            row.get("source_revision_id") or "",
        ),
    )
    return canonical_hash(rows)


def macro_release_cutoffs(
    facts: Iterable[ObservationFact], *, start: str = "1996-01-01", end: str | None = None,
) -> list[str]:
    end_value = end or "9999-12-31T23:59:59+00:00"
    output = {
        row.available_at
        for row in facts
        if row.series_id in FACTOR_SERIES and start <= row.available_at[:10] <= end_value[:10]
    }
    return sorted(output)


def build_origin_dfm_cache(
    root: Path, *, contract: dict[str, Any], facts: list[ObservationFact],
    end_cutoff: str, start: str = "1996-01-01", max_cutoffs: int | None = None,
    fitter: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fit_runtime = (
        require_dfm_runtime()
        if fitter is None
        else {**runtime_manifest(), "fit_engine": "injected_test_fitter"}
    )
    runtime_digest = canonical_hash(fit_runtime)[:12]
    active_by_cache = {
        str(row["cache_id"]): row for row in read_dfm_manifest(root)
    }
    cutoffs = macro_release_cutoffs(facts, start=start, end=end_cutoff)
    if max_cutoffs is not None:
        cutoffs = cutoffs[-max_cutoffs:]
    contract_digest = frozen_hash(contract)
    created = 0
    reused = 0
    failed = 0
    entries: list[dict[str, Any]] = []
    # Build exact as-of snapshots incrementally. Re-scanning the million-row
    # ALFRED ledger for every release would change no statistical coordinate but
    # would make the preregistered 2,000+ origin refits needlessly quadratic.
    events = sorted(
        (row for row in facts if row.series_id in FACTOR_SERIES),
        key=lambda row: (row.available_at, row.series_id, row.observation_time),
    )
    event_index = 0
    known: dict[tuple[str, str], ObservationFact] = {}
    previous_parameters: dict[str, list[float]] | None = None
    fit_settings = contract["model"]["dynamic_factor"]
    for cutoff in cutoffs:
        while event_index < len(events) and events[event_index].available_at <= cutoff:
            event = events[event_index]
            known[(event.series_id, event.observation_time)] = event
            event_index += 1
        snapshot = sorted(
            known.values(), key=lambda row: (row.series_id, row.observation_time, row.available_at),
        )
        input_digest = canonical_hash([row.model_dump(mode="json") for row in snapshot])
        cache_seed = {
            "contract_hash": contract_digest,
            "cutoff": cutoff,
            "input_hash": input_digest,
        }
        cache_id = f"dfm-v2-{canonical_hash(cache_seed)[:24]}"
        active_entry = active_by_cache.get(cache_id)
        active_runtime_matches = (
            active_entry is not None and active_entry.get("runtime") == fit_runtime
        )
        if active_runtime_matches and (root / str(active_entry["path"])).is_file():
            relative = Path(str(active_entry["path"]))
            manifest_id = str(active_entry.get("manifest_id") or cache_id)
            supersedes = active_entry.get("supersedes")
        else:
            # Keep the older derived cache and append-only row.  A corrected
            # numerical runtime writes a new physical artifact and explicitly
            # supersedes the formerly active manifest identity.
            relative = DFM_CACHE_RELATIVE / f"{cache_id}__{runtime_digest}.json"
            manifest_id = f"{cache_id}@{runtime_digest}"
            supersedes = (
                None if active_entry is None
                else str(active_entry.get("manifest_id") or active_entry["cache_id"])
            )
        target = root / relative
        if target.is_file():
            payload = json.loads(target.read_text(encoding="utf-8"))
            if payload.get("cache_key") != cache_seed:
                raise DFMCacheError(f"DFM cache replay mismatch: {cache_id}")
            if payload.get("runtime") != fit_runtime:
                raise DFMCacheError(
                    f"DFM cache runtime provenance missing or mismatched: {cache_id}"
                )
            reused += 1
        else:
            fitted: dict[str, Any] = {}
            try:
                fitted = (
                    fit_dynamic_factor_snapshot(
                        snapshot, knowledge_cutoff=cutoff, start_parameters=previous_parameters,
                        tolerance=float(fit_settings["em_tolerance"]),
                        cold_max_iterations=int(fit_settings["em_cold_max_iterations"]),
                        warm_max_iterations=int(fit_settings["em_warm_max_iterations"]),
                    )
                    if fitter is None
                    else fitter(snapshot, knowledge_cutoff=cutoff)
                )
                factor_values = {
                    name: fitted.get("states", {}).get(name)
                    for name in ("growth_factor", "inflation_factor")
                }
                converged = all(
                    fitted.get("converged", {}).get(name) is True
                    and factor_values[name] is not None
                    for name in factor_values
                )
                status = "ready" if converged else "fit_hold"
                errors = [] if converged else ["DynamicFactorMQ convergence/state gate failed"]
            except (RuntimeError, ValueError, ArithmeticError) as exc:
                factor_values = {"growth_factor": None, "inflation_factor": None}
                status = "fit_hold"
                errors = [str(exc)]
            payload = {
                "schema_version": 2,
                "cache_id": cache_id,
                "model_id": contract["model_id"],
                "cache_key": cache_seed,
                "cutoff": cutoff,
                "input_hash": input_digest,
                "parameter_estimation": "origin_specific_native_pit",
                "data_grade": "native_pit",
                "factors": factor_values,
                "fit_parameters": fitted.get("parameters", {}),
                "fit_diagnostics": fitted.get("diagnostics", {}),
                "runtime": fit_runtime,
                "status": status,
                "errors": errors,
            }
            payload["content_hash"] = canonical_hash(payload)
            _atomic_json(target, payload)
            created += 1
            if status != "ready":
                failed += 1
        if payload.get("fit_parameters"):
            stable_parameters = {
                factor_name: values
                for factor_name, values in payload["fit_parameters"].items()
                if payload.get("fit_diagnostics", {}).get(factor_name, {}).get(
                    "finite_state_and_parameters"
                ) is True
                and payload.get("fit_diagnostics", {}).get(factor_name, {}).get(
                    "log_likelihood_decreased"
                ) is False
            }
            if stable_parameters:
                previous_parameters = {**(previous_parameters or {}), **stable_parameters}
        manifest = {
            "manifest_id": manifest_id,
            "cache_id": cache_id,
            "cutoff": cutoff,
            "input_hash": input_digest,
            "contract_hash": contract_digest,
            "path": relative.as_posix(),
            "status": payload["status"],
            "runtime": payload["runtime"],
            "content_hash": payload["content_hash"],
        }
        if supersedes is not None:
            manifest["supersedes"] = supersedes
        _append_manifest(root / DFM_MANIFEST, manifest)
        active_by_cache[cache_id] = manifest
        entries.append(manifest)
    evaluation_start = str(contract["evaluation"]["outer_start"])
    blocking_failed = sum(
        row["status"] != "ready" and str(row["cutoff"])[:10] >= evaluation_start
        for row in entries
    )
    ready_before_evaluation = any(
        row["status"] == "ready" and str(row["cutoff"])[:10] < evaluation_start
        for row in entries
    )
    return {
        "cutoffs": len(cutoffs), "created": created, "reused": reused,
        "failed": failed, "blocking_failed": blocking_failed,
        "ready_before_evaluation": ready_before_evaluation, "entries": entries,
    }


def read_dfm_manifest(root: Path, *, active_only: bool = True) -> list[dict[str, Any]]:
    path = root / DFM_MANIFEST
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not active_only:
        return rows
    superseded = {
        str(row["supersedes"]) for row in rows if row.get("supersedes") is not None
    }
    return [
        row for row in rows
        if str(row.get("manifest_id") or row["cache_id"]) not in superseded
    ]


def verify_dfm_runtime_provenance(root: Path) -> dict[str, Any]:
    """Require every reusable DFM entry to name the exact numerical runtime."""
    entries = read_dfm_manifest(root)
    missing: list[str] = []
    mismatched: list[str] = []
    for entry in entries:
        runtime = entry.get("runtime")
        if not isinstance(runtime, dict):
            missing.append(str(entry.get("cache_id")))
            continue
        if runtime.get("fit_engine") == "injected_test_fitter":
            mismatched.append(str(entry.get("cache_id")))
            continue
        try:
            require_dfm_runtime(runtime)
        except TimeSeriesV2ContractError:
            mismatched.append(str(entry.get("cache_id")))
    return {
        "ok": bool(entries) and not missing and not mismatched,
        "entries": len(entries),
        "missing_runtime": missing,
        "mismatched_runtime": mismatched,
        "required": {"statsmodels": "0.14.6", "pandas": ">=2.2,<3"},
    }


def load_factor_states_for_sessions(
    root: Path, *, session_cutoffs: Iterable[str], contract_hash: str,
) -> list[dict[str, Any]]:
    entries = [
        row for row in read_dfm_manifest(root)
        if row.get("contract_hash") == contract_hash
    ]
    entries.sort(key=lambda row: row["cutoff"])
    output: list[dict[str, Any]] = []
    index = 0
    current: dict[str, Any] | None = None
    for origin in session_cutoffs:
        blocking_entry: dict[str, Any] | None = None
        while index < len(entries) and entries[index]["cutoff"] <= origin:
            entry = entries[index]
            if entry.get("status") != "ready":
                # A failed origin refit invalidates the prior state.  The old
                # factor is not carried forward as if the failed release had
                # never happened.
                current = None
                blocking_entry = entry
                index += 1
                continue
            path = root / entry["path"]
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if candidate["content_hash"] != canonical_hash({
                key: value for key, value in candidate.items() if key != "content_hash"
            }):
                raise DFMCacheError(f"DFM cache content hash mismatch: {entry['cache_id']}")
            current = candidate
            blocking_entry = None
            index += 1
        if current is None:
            output.append({
                "origin": origin, "cache_id": None, "growth_factor": None,
                "inflation_factor": None, "age_since_release_days": None,
                "blocked_by_cache_id": (
                    None if blocking_entry is None else blocking_entry.get("cache_id")
                ),
            })
            continue
        age = (datetime.fromisoformat(origin) - datetime.fromisoformat(current["cutoff"])).days
        output.append({
            "origin": origin,
            "cache_id": current["cache_id"],
            "cache_cutoff": current["cutoff"],
            "growth_factor": current["factors"]["growth_factor"],
            "inflation_factor": current["factors"]["inflation_factor"],
            "age_since_release_days": age,
        })
    return output
