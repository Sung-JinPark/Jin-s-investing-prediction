"""Append-only daily research issuance, coefficient freezing and forward scoring.

The official forecast, scenario and benchmark ledgers are never write targets.
Replay inputs are frozen with each issuance; captured-current history is not
retroactively turned into historical forecasting evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from . import contracts as C


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(C.canonical_json(row) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _immutable(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(C.canonical_json(row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if _read(path) != row:
            raise C.MarketContextError("immutable artifact collision: " + path.name)


@contextmanager
def writer_lock(root: Path):
    path = root / "outputs/market_context/.writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise C.MarketContextError("another market-context writer owns the store lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_chain(root: Path, relative: Path) -> list[dict[str, Any]]:
    path = root / relative
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []
    previous = None
    seen: set[str] = set()
    active_days: dict[str, str] = {}
    for row in rows:
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("previous_hash") != previous or row.get("content_hash") != C.canonical_hash(body):
            raise C.MarketContextError("research ledger hash chain mismatch: " + str(relative))
        identity = row.get("ledger_id")
        if not identity or identity in seen:
            raise C.MarketContextError("missing or duplicate research ledger identity")
        if relative == C.FORECAST_LEDGER:
            day = str(row.get("issue_date", ""))
            target = row.get("supersedes")
            if not day or (target is None and day in active_days):
                raise C.MarketContextError("duplicate daily issuance without explicit supersedes")
            if target is not None and active_days.get(day) != target:
                raise C.MarketContextError("supersedes must name the active issuance in the same local day")
            active_days[day] = identity
        seen.add(identity)
        previous = row["content_hash"]
    return rows


def _append(root: Path, relative: Path, payload: dict[str, Any]) -> dict[str, Any]:
    rows = read_chain(root, relative)
    for row in rows:
        if row["ledger_id"] == payload["ledger_id"]:
            if any(row.get(key) != value for key, value in payload.items()):
                raise C.MarketContextError("append-only identity collision")
            return row
    body = {**payload, "previous_hash": rows[-1]["content_hash"] if rows else None}
    row = {**body, "content_hash": C.canonical_hash(body)}
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(C.canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


def _safe(root: Path, relative: str, parent: Path = C.STORE_RELATIVE) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to((root / parent).resolve()):
        raise C.MarketContextError("artifact escaped independent research store")
    return path


def hold_payload(reasons: list[str], *, as_of: str | None = None, status: str = "hold", **evidence) -> dict[str, Any]:
    body = {"schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION,
            "status": status, "as_of": as_of, "numbers_visible": False,
            "probability_unit": "fraction", "predictive_validation": "not_established",
            "numerical_context_applied": False, "score": None,
            "gate": {"pass": False, "reasons": list(dict.fromkeys(reasons))},
            "evidence": evidence, "footnote": "독립 연구 프리뷰 · 예측력 검증 전 · 수치 반영 보류"}
    if evidence.get("last_valid_forecast"):
        body["last_valid_forecast"] = evidence["last_valid_forecast"]
    if evidence.get("state_summary"):
        body["state_summary"] = evidence["state_summary"]
    return {**body, "content_hash": C.canonical_hash(body)}


def _hold_for_inputs(root: Path, reasons: list[str], cutoff: str, inputs: dict | None) -> dict:
    evidence = {}
    if inputs:
        events = [{key: event.get(key) for key in ("event_id", "revision_id", "title", "source_url", "axis", "family", "available_at",
                                                  "incident_group_id", "incident_group_status", "duplicate_of_revision_id")}
                  | {"used_numerically": False, "reason": "연구 발행 입력 검증 대기",
                     "exclusion_reason": event.get("reason")}
                  for event in inputs.get("events", [])[-20:]]
        evidence["state_summary"] = {"axes": [], "events": events, "source_statuses": inputs.get("source_statuses", []),
                                     "total_event_count": len(inputs.get("events", []))}
    prior = read_chain(root, C.FORECAST_LEDGER)
    if prior:
        last = prior[-1]
        evidence["last_valid_forecast"] = {key: last[key] for key in ("forecast_id", "as_of", "anchor_date")}
    return hold_payload(reasons, as_of=cutoff, **evidence)


def _pointer(root: Path, run: dict[str, Any]) -> None:
    body = {"schema_version": 1, "model_id": C.MODEL_ID, "status": run["status"],
            "forecast_id": run["forecast_id"], "as_of": run["as_of"],
            "anchor_date": run["anchor_date"], "run_path": run["run_path"],
            "run_content_hash": run["content_hash"]}
    _atomic(root / C.LATEST_RELATIVE, {**body, "content_hash": C.canonical_hash(body)})


def _active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    superseded = {row["supersedes"] for row in rows if row.get("supersedes")}
    return [row for row in rows if row["ledger_id"] not in superseded]


def load_run(root: Path, row: dict[str, Any], *, check_code: bool = True) -> dict[str, Any]:
    run = _read(_safe(root, row["run_path"], C.STORE_RELATIVE / "runs"))
    validate_run(run)
    if row.get("run_content_hash", row.get("content_hash")) != run["content_hash"] or row.get("forecast_id", row.get("ledger_id")) != run["forecast_id"]:
        raise C.MarketContextError("research run/ledger identity mismatch")
    if run["contract_hash"] != C.canonical_hash(C.load_contract(root)):
        raise C.MarketContextError("research contract changed; historical snapshot remains frozen")
    if check_code and run["model_code_hash"] != C.model_code_hash(root):
        raise C.MarketContextError("numerical code identity changed; original replay runtime required")
    return run


def _load_coefficients(root: Path, cutoff: str) -> dict[str, Any] | None:
    candidates = [row for row in read_chain(root, C.MODEL_LEDGER) if C.aware(row["available_at"]) <= C.aware(cutoff)]
    if not candidates:
        return None
    row = sorted(candidates, key=lambda value: (value["available_at"], value["ledger_id"]))[-1]
    artifact = _read_model_artifact(root, row)
    if C.aware(artifact["train_cutoff"]) > C.aware(cutoff) or C.aware(artifact["available_at"]) > C.aware(cutoff):
        raise C.MarketContextError("future coefficient artifact")
    return artifact


def _read_model_artifact(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    artifact = _read(_safe(root, row["artifact_path"], C.STORE_RELATIVE / "models"))
    if artifact.get("content_hash") != C.canonical_hash({k: v for k, v in artifact.items() if k != "content_hash"}) or artifact["content_hash"] != row["artifact_hash"]:
        raise C.MarketContextError("coefficient artifact hash mismatch")
    if artifact["contract_hash"] != C.canonical_hash(C.load_contract(root)):
        raise C.MarketContextError("coefficient artifact belongs to another contract")
    if (artifact.get("model_id") != C.MODEL_ID or artifact.get("model_version") != C.MODEL_VERSION
            or artifact.get("status") != "ready" or artifact.get("model_code_hash") != C.model_code_hash(root)):
        raise C.MarketContextError("coefficient artifact model/code identity mismatch")
    if (C.aware(artifact["train_cutoff"]) > C.aware(artifact["available_at"])
            or C.aware(row["available_at"]) != C.aware(artifact["available_at"])):
        raise C.MarketContextError("coefficient artifact availability does not follow training")
    from .model import _vector
    _vector(artifact["coef"], "coef")
    if np.any(_vector(artifact["scale"], "scale") <= 0):
        raise C.MarketContextError("coefficient feature scale must be positive")
    bootstrap = np.asarray(artifact.get("bootstrap_coefficients"), dtype=float)
    if bootstrap.shape != (200, 21) or not np.isfinite(bootstrap).all():
        raise C.MarketContextError("coefficient uncertainty must contain 200 finite complete draws")
    return artifact


def _state_summary(reference: dict[str, Any], numerical: dict[str, Any], coefficients: dict | None) -> dict:
    eligible = set((coefficients or {}).get("active_families", []))
    ref = np.asarray(reference.get("reference_vector", [0.] * 21), dtype=float).reshape(7, 3)
    vector = np.asarray(numerical.get("numerical_vector", [0.] * 21), dtype=float).reshape(7, 3)
    observed_axes = {event.get("axis") for event in reference.get("events", []) if event.get("surprise_z") is not None}
    axes = [{"axis": axis, "label": C.AXIS_LABELS[axis], "score": float(100 * np.tanh(ref[index, 1])) if axis in observed_axes else None,
             "applied": bool(np.any(vector[index])),
             "reason": "등록된 계수로 반영" if np.any(vector[index]) else "적격 자료·계수 부족 또는 중립 상태"}
            for index, axis in enumerate(C.AXES)]
    events = []
    numerical_rows = {event["revision_id"]: event for event in numerical.get("events", [])}
    for event in reference.get("events", []):
        applied_row = numerical_rows.get(event["revision_id"], {})
        used = applied_row.get("used_numerically") is True
        events.append({key: event.get(key) for key in ("event_id", "revision_id", "title", "source_url", "axis", "family", "available_at", "expectation_kind",
                                                      "incident_group_id", "incident_group_status", "duplicate_of_revision_id")} | {
            "used_numerically": used, "reason": "등록된 시황 계수로 반영" if used else "수치 반영 검증 대기",
            "exclusion_reason": applied_row.get("exclusion_reason") or event.get("reason")})
    return {"axes": axes, "events": events[-60:], "coverage": reference.get("coverage"),
            "active_families": sorted(eligible), "total_event_count": len(events)}


def _path_hash(paths: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(paths, dtype=np.float64).tobytes()).hexdigest()


def _active_input_issues(inputs: dict[str, Any], families: set[str], as_of: str, policy: dict | None = None) -> list[str]:
    """An already fitted feature is required; a failed capture is never news0."""
    from .features import INNOVATIONS
    required = {family: series for series, (family, _, _) in INNOVATIONS.items()}
    rows = inputs.get("market_features", [])
    policy = policy or {}
    completed = inputs["session_dates"]
    issues = []
    for family in sorted(families):
        series = required.get(family)
        if series:
            candidates = [row for row in rows if row["series_id"] == series]
            if not candidates:
                issues.append("missing_active_family_source:" + family)
                continue
            latest = max(candidates, key=lambda row: row["observation_time"])
            if family in MARKET_FAMILIES:
                age = sum(day > latest["observation_time"] for day in completed)
                allowed = int(policy.get("active_oil_max_age_sessions", 3) if series == "DCOILWTICO"
                              else policy.get("active_daily_max_age_sessions", 1))
                if age > allowed:
                    issues.append("stale_active_family_source:" + family)
            else:
                last_known = max(C.aware(latest["available_at"]), C.aware(latest["retrieved_at"]))
                if (C.aware(as_of) - last_known).total_seconds() > int(policy.get("active_release_max_age_days", 62)) * 86400:
                    issues.append("stale_active_release_source:" + family)
        else:
            evidence = [row for row in inputs["events"] if row.get("family") == family]
            source_ids = {row.get("source_id") for row in evidence}
            failed = [row for row in inputs.get("source_statuses", [])
                      if row.get("source_id") in source_ids and row.get("status") in {"failed", "error"}]
            if not evidence or failed:
                issues.append("missing_or_failed_active_event_source:" + family)
    return issues


def _comparison(baseline: np.ndarray, candidate: np.ndarray, delta: list[float]) -> dict[str, Any]:
    rows = []
    for horizon in (1, 5, 21, 63, 126, 252):
        before, after = baseline[:, horizon - 1], candidate[:, horizon - 1]
        rows.append({"horizon": horizon, "baseline_median": float(np.median(before)),
                     "candidate_median": float(np.median(after)), "delta_log": float(delta[horizon - 1]),
                     "median_difference": float(np.median(after) - np.median(before))})
    return {"same_inputs": True, "same_daily_shocks": True, "baseline": "unchanged_quant_mc_gbm_paths",
            "identical_at_zero_context": bool(np.array_equal(baseline, candidate)) if not np.any(delta) else None,
            "horizons": rows, "maximum_daily_level_difference": float(np.max(np.abs(candidate - baseline))),
            "after_63_additional_drift": 0.0, "predictive_validation": "not_established"}


def build_context(root: Path, *, as_of: str | None = None, supersedes: str | None = None,
                  save_paths: bool = True) -> dict[str, Any]:
    from . import features as F, model as M
    cutoff = C.aware(as_of).isoformat()
    with writer_lock(root):
        contract = C.load_contract(root)
        inputs = None
        try:
            inputs = F.load_inputs(root, as_of=cutoff)
            if not inputs.get("gate", {}).get("pass"):
                result = _hold_for_inputs(root, inputs.get("gate", {}).get("reasons", ["input gate did not pass"]), cutoff, inputs)
                _atomic(root / C.LATEST_RELATIVE, result)
                return result
            forecasts = read_chain(root, C.FORECAST_LEDGER)
            issue_date = C.aware(cutoff).astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
            active = [row for row in _active(forecasts) if row["issue_date"] == issue_date]
            if supersedes is None and active:
                return {**load_run(root, active[-1]), "skipped": "daily issuance already exists; use explicit supersedes to correct"}
            if supersedes is not None and (not active or active[-1]["ledger_id"] != supersedes):
                raise C.MarketContextError("supersedes must name the active daily issuance")
            coefficients = _load_coefficients(root, cutoff)
            families = set((coefficients or {}).get("active_families", []))
            active_issues = _active_input_issues(inputs, families, cutoff, contract.get("input"))
            if active_issues:
                raise C.MarketContextError("; ".join(active_issues))
            reference = M.score_state(inputs["events"], as_of=cutoff, session_dates=inputs["session_dates"], eligible_families=None)
            state = M.score_state(inputs["events"], as_of=cutoff, session_dates=inputs["session_dates"], eligible_families=families)
            frozen = {"as_of": cutoff, "dates": inputs["dates"], "closes": inputs["closes"],
                      "future_dates": inputs["future_dates"], "events": inputs["events"],
                      "session_dates": inputs["session_dates"], "lineage": inputs["lineage"],
                      "numerical_state": state["numerical_vector"], "reference_state": reference,
                      "coefficients": coefficients}
            input_hash = C.canonical_hash(frozen)
            forecast_id = "mc-" + C.canonical_hash({"model_id": C.MODEL_ID, "as_of": cutoff, "input_hash": input_hash, "supersedes": supersedes})[:24]
            projection = M.project_paths(inputs["closes"], state=state["numerical_vector"], coefficients=coefficients,
                                         future_dates=inputs["future_dates"], n_paths=C.PATH_COUNT, seed=C.SEED)
            baseline, candidate = projection["baseline_paths"], projection["candidate_paths"]
            summary = M.summarize_paths(candidate, anchor=inputs["anchor"], future_dates=inputs["future_dates"], baseline_paths=baseline)
            delta = np.asarray(projection["delta_log"], dtype=float).tolist()
            volatility = float(np.std(np.diff(np.log(inputs["closes"][-253:])), ddof=1))
            score = (float(100 * np.tanh(delta[20] / (volatility * math.sqrt(21))))
                     if coefficients is not None and volatility > 0 else None)
            body = {**{key: value for key, value in summary.items() if key != "daily"},
                    "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION,
                    "status": "research_preview", "numbers_visible": True, "forecast_id": forecast_id,
                    "as_of": cutoff, "issue_date": issue_date, "anchor_date": inputs["anchor_date"],
                    "anchor": inputs["anchor"], "forecast_end_date": inputs["future_dates"][-1],
                    "future_dates": inputs["future_dates"], "path_count": C.PATH_COUNT,
                    "probability_unit": "fraction", "probability_space": "research_market_context_conditional",
                    "predictive_validation": "not_established", "contract_hash": C.canonical_hash(contract),
                    "model_code_hash": C.model_code_hash(root), "runtime": C.runtime_identity(), "input_hash": input_hash,
                    "coefficient_hash": (coefficients or {}).get("content_hash"),
                    "numerical_context_applied": bool(projection["numerical_context_applied"]), "score": score,
                    "state_summary": _state_summary(reference, state, coefficients),
                    "attribution": projection.get("attribution", {}),
                    "attribution_basis": projection["attribution_basis"], "delta_log": delta,
                    "baseline_median": [float(inputs["anchor"])] + np.median(baseline, axis=0).tolist(),
                    "history": inputs.get("history", {"dates": inputs["dates"], "index": inputs["closes"]}),
                    "gate": {"pass": True, "reasons": []}, "source_lineage": inputs["lineage"],
                    "comparison": _comparison(baseline, candidate, delta),
                    "path_hash": _path_hash(candidate), "supersedes": supersedes,
                    "replay": frozen, "run_path": (C.STORE_RELATIVE / "runs" / f"{forecast_id}.json").as_posix(),
                    "footnote": "독립 연구 프리뷰 · 예측력 검증 전 · 굵은 선은 전체 분포의 실제 대표 모의경로이며 특정 하락일 예측이 아닙니다. 시황 추가 drift는 63거래일까지 추정합니다."}
            body["state_summary"]["source_statuses"] = inputs.get("source_statuses", [])
            if coefficients is None:
                body["gate"]["notes"] = ["시황 점수 수집 중 · 적격 학습 계수 없음 · 가격 보정 미적용"]
            if save_paths:
                path = root / "outputs/market_context/paths" / f"{forecast_id}.npz"
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    with np.load(path, allow_pickle=False) as archive:
                        if not np.array_equal(archive["index_paths"], candidate):
                            raise C.MarketContextError("immutable path artifact collision")
                else:
                    with path.open("xb") as handle:
                        np.savez_compressed(handle, index_paths=candidate)
                body["joint_path_artifact"] = {"path": path.relative_to(root).as_posix(),
                                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                               "optional_local_artifact": True}
            run = {**body, "content_hash": C.canonical_hash(body)}
            validate_run(run)
            # Recheck source selection at the append boundary without advancing as_of.
            recheck = F.load_inputs(root, as_of=cutoff)
            if not recheck.get("gate", {}).get("pass") or any(recheck[key] != inputs[key] for key in ("dates", "closes", "events", "future_dates", "lineage")):
                raise C.MarketContextError("inputs or publication gates changed before append")
            _immutable(root / run["run_path"], run)
            _append(root, C.FORECAST_LEDGER, {"ledger_id": forecast_id, "forecast_id": forecast_id,
                    "issue_date": issue_date, "as_of": cutoff, "anchor_date": inputs["anchor_date"],
                    "supersedes": supersedes, "run_path": run["run_path"], "run_content_hash": run["content_hash"]})
            _pointer(root, run)
            return run
        except (OSError, ValueError, RuntimeError, KeyError, ImportError) as exc:
            try:
                result = _hold_for_inputs(root, [str(exc)], cutoff, inputs)
            except (OSError, ValueError, KeyError):
                result = hold_payload([str(exc)], as_of=cutoff)
            _atomic(root / C.LATEST_RELATIVE, result)
            return result


def validate_run(run: dict[str, Any]) -> None:
    if (run.get("model_id") != C.MODEL_ID or run.get("status") != "research_preview"
            or run.get("probability_unit") != "fraction" or run.get("predictive_validation") != "not_established"
            or run.get("gate", {}).get("pass") is not True or run.get("path_count") != C.PATH_COUNT):
        raise C.MarketContextError("research run identity/unit/gates mismatch")
    cutoff = C.aware(run["as_of"])
    anchor = float(run["anchor"])
    dates = run["future_dates"]
    if not math.isfinite(anchor) or anchor <= 0 or len(dates) != C.HORIZON or dates != sorted(set(dates)) or dates[0] <= run["anchor_date"]:
        raise C.MarketContextError("invalid anchor or 252 future session dates")
    from .features import _calendar
    _, calendar_days, calendar_closes = _calendar(run["as_of"], run["anchor_date"], C.HORIZON)
    completed = [day for day, close in zip(calendar_days, calendar_closes) if close <= cutoff]
    expected = [day for day in calendar_days if day > run["anchor_date"]][:C.HORIZON]
    if not completed or completed[-1] != run["anchor_date"] or expected != dates:
        raise C.MarketContextError("anchor/future sessions differ from exchange calendar at issuance")
    records = run.get("records", [])
    if len(records) != C.HORIZON or [row["date"] for row in records] != dates:
        raise C.MarketContextError("every daily session must have one record")
    for row in records:
        for key in ("index_quantiles", "daily_return_quantiles", "drawdown_quantiles"):
            values = [float(row[key][name]) for name in C.QUANTILE_NAMES]
            if not all(math.isfinite(value) for value in values) or values != sorted(values):
                raise C.MarketContextError("invalid or crossing daily quantiles")
            if key == "index_quantiles" and values[0] <= 0:
                raise C.MarketContextError("index quantiles must be positive")
            if key == "drawdown_quantiles" and (values[0] < -1 or values[-1] > 0):
                raise C.MarketContextError("drawdown must be a fraction in [-1,0]")
        for key in ("probability_up_from_previous", "probability_down_from_previous", "probability_up_from_origin"):
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise C.MarketContextError("probability must be an explicit fraction in [0,1]")
        if row["probability_up_from_previous"] + row["probability_down_from_previous"] > 1 + 1e-12:
            raise C.MarketContextError("up/down probabilities cannot exceed unit mass")
    representative = run.get("representative", {})
    if representative.get("status") == "ok":
        values = representative.get("values", [])
        if len(values) != 253 or values[0] != anchor or not all(math.isfinite(float(value)) and value > 0 for value in values):
            raise C.MarketContextError("actual representative must contain anchor and all 252 daily values")
    if run.get("input_hash") != C.canonical_hash(run["replay"]):
        raise C.MarketContextError("immutable replay input hash mismatch")
    frozen = run["replay"]
    if (len(frozen["dates"]) != len(frozen["closes"]) or frozen["dates"] != sorted(set(frozen["dates"]))
            or frozen["dates"][-1] != run["anchor_date"] or frozen["closes"][-1] != anchor
            or frozen["future_dates"] != dates):
        raise C.MarketContextError("frozen close panel/calendar does not match issued anchor")
    for event in frozen["events"]:
        if any(C.aware(event[key]) > cutoff for key in ("available_at", "retrieved_at", "published_at") if event.get(key)):
            raise C.MarketContextError("future event publication or acquisition in frozen inputs")
    coefficients = frozen.get("coefficients")
    if coefficients and any(C.aware(coefficients[key]) > cutoff for key in ("train_cutoff", "available_at")):
        raise C.MarketContextError("future coefficient artifact in frozen inputs")
    from .model import score_state
    reproduced_state = score_state(frozen["events"], as_of=run["as_of"], session_dates=frozen["session_dates"],
                                   eligible_families=set((coefficients or {}).get("active_families", [])))
    if reproduced_state["numerical_vector"] != frozen["numerical_state"]:
        raise C.MarketContextError("frozen numerical state differs from eligible source events")
    if run.get("content_hash") != C.canonical_hash({key: value for key, value in run.items() if key != "content_hash"}):
        raise C.MarketContextError("immutable run hash mismatch")


def _replay(run: dict[str, Any]) -> dict[str, Any]:
    from . import model as M
    frozen = run["replay"]
    result = M.project_paths(frozen["closes"], state=frozen["numerical_state"], coefficients=frozen["coefficients"],
                             future_dates=frozen["future_dates"], n_paths=C.PATH_COUNT, seed=C.SEED)
    if _path_hash(result["candidate_paths"]) != run["path_hash"]:
        raise C.MarketContextError("replayed numerical paths differ from issued snapshot")
    summary = M.summarize_paths(result["candidate_paths"], anchor=run["anchor"], future_dates=run["future_dates"], baseline_paths=result["baseline_paths"])
    if summary["records"] != run["records"] or summary["representative"] != run["representative"]:
        raise C.MarketContextError("replayed daily statistics or actual member differ")
    if any(result[key] != run.get(key) for key in ("attribution", "attribution_basis", "delta_log")):
        raise C.MarketContextError("replayed context contributions differ")
    return result


def verify_context(root: Path, *, replay: bool = False) -> dict[str, Any]:
    errors, missing = [], []
    try:
        C.load_contract(root)
        from .ledger import verify_store
        store = verify_store(root)
        if not store["ok"]:
            raise C.MarketContextError("source store integrity: " + "; ".join(store["errors"]))
        forecasts = read_chain(root, C.FORECAST_LEDGER)
        resolutions = read_chain(root, C.RESOLUTION_LEDGER)
        for model_row in read_chain(root, C.MODEL_LEDGER):
            _read_model_artifact(root, model_row)
        identities = {row["ledger_id"] for row in forecasts}
        for row in forecasts:
            run = load_run(root, row)
            artifact = run.get("joint_path_artifact")
            if artifact:
                path = _safe(root, artifact["path"], Path("outputs/market_context/paths"))
                if not path.exists() and artifact.get("optional_local_artifact"):
                    missing.append(artifact["path"])
                else:
                    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                        raise C.MarketContextError("joint path artifact file hash mismatch")
                    with np.load(path, allow_pickle=False) as archive:
                        if archive["index_paths"].shape != (C.PATH_COUNT, C.HORIZON) or _path_hash(archive["index_paths"]) != run["path_hash"]:
                            raise C.MarketContextError("joint path artifact numerical hash mismatch")
            if replay:
                _replay(run)
        for row in resolutions:
            if row["forecast_id"] not in identities or row.get("probability_unit") != "fraction":
                raise C.MarketContextError("resolution references unknown forecast or unit")
        return {"ok": True, "forecasts": len(forecasts), "resolutions": len(resolutions),
                "replay_completed": replay, "missing_optional_path_artifacts": missing,
                "source_store": store,
                "predictive_validation": "not_established", "errors": []}
    except (OSError, ValueError, KeyError, ImportError, RuntimeError) as exc:
        errors.append(str(exc))
    return {"ok": False, "errors": errors, "predictive_validation": "not_established"}


MARKET_FAMILIES = {"vix_innovation", "treasury_2y_innovation", "treasury_10y_innovation",
                   "oil_innovation", "dollar_innovation"}


def _family_state(state: dict[str, Any], families: set[str]) -> list[float]:
    result = np.zeros(len(C.AXES) * len(C.HALF_LIVES))
    for family, values in state.get("state_by_family", {}).items():
        if family in families:
            result += np.asarray(values, dtype=float)
    return result.tolist()


def training_samples(root: Path, *, as_of: str) -> list[dict[str, Any]]:
    """Use only frozen forward states and first appended, matured target facts."""
    cutoff = C.aware(as_of)
    forecasts = [row for row in _active(read_chain(root, C.FORECAST_LEDGER)) if C.aware(row["as_of"]) <= cutoff]
    targets = {}
    for row in read_chain(root, C.RESOLUTION_LEDGER):
        if C.aware(row["available_at"]) <= cutoff:
            targets[(row["forecast_id"], row["horizon"])] = row
    # Calendar-day issuance may share a Friday anchor.  One earliest eligible
    # issuance per market origin prevents weekends inflating sample size.
    origins = {}
    for row in sorted(forecasts, key=lambda value: value["as_of"]):
        origins.setdefault(row["anchor_date"], row)
    samples = []
    for origin, row in sorted(origins.items()):
        run = load_run(root, row)
        resolved = [targets.get((row["forecast_id"], horizon)) for horizon in C.TRAIN_HORIZONS]
        if any(value is None for value in resolved):
            continue
        if any(C.aware(value["available_at"]) <= C.aware(run["as_of"]) for value in resolved):
            continue
        state = run["replay"]["reference_state"]
        log_returns = np.diff(np.log(run["replay"]["closes"][-253:]))
        samples.append({"origin_date": origin, "as_of": run["as_of"], "state_available_at": run["as_of"],
                        "state": _family_state(state, set(state.get("state_by_family", {}))),
                        "state_by_family": state.get("state_by_family", {}),
                        "event_ids_by_family": state.get("event_ids_by_family", {}),
                        "baseline_mu": float(log_returns.mean()), "baseline_sigma": float(log_returns.std(ddof=1)),
                        "targets": {str(h): math.log(target["actual_index"] / run["anchor"])
                                    for h, target in zip(C.TRAIN_HORIZONS, resolved)},
                        "target_available_at": {str(h): target["available_at"] for h, target in zip(C.TRAIN_HORIZONS, resolved)},
                        "forecast_id": run["forecast_id"], "historical_pit_eligible": True,
                        "data_grade": "captured_forward"})
    return samples


def fit_context(root: Path, *, train_cutoff: str | None = None) -> dict[str, Any]:
    """Freeze at most one ready artifact per month; insufficient data is explicit."""
    from . import training as T
    cutoff = C.aware(train_cutoff).isoformat()
    with writer_lock(root):
        contract = C.load_contract(root)
        month = C.aware(cutoff).astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")
        existing = [row for row in read_chain(root, C.MODEL_LEDGER) if row["training_month"] == month]
        if existing:
            return {"status": "skipped", "reason": "monthly coefficients already frozen", "model": existing[-1]}
        samples = training_samples(root, as_of=cutoff)
        fitted = T.fit_model(samples, train_cutoff=cutoff)
        if fitted["status"] != "ready":
            return fitted
        ablations = {}
        for role in ("market_only", "event_only"):
            selected = []
            for sample in samples:
                families = set(sample["state_by_family"])
                families = families & MARKET_FAMILIES if role == "market_only" else families - MARKET_FAMILIES
                components = {key: value for key, value in sample["state_by_family"].items() if key in families}
                selected.append({**sample, "state": _family_state({"state_by_family": components}, families),
                                 "state_by_family": components,
                                 "event_ids_by_family": {key: value for key, value in sample["event_ids_by_family"].items() if key in families}})
            ablations[role] = T.fit_model(selected, train_cutoff=cutoff)
        available = max(C.aware(), C.aware(cutoff)).isoformat()
        body = {**fitted, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION,
                "available_at": available, "contract_hash": C.canonical_hash(contract),
                "model_code_hash": C.model_code_hash(root), "runtime": C.runtime_identity(), "samples_hash": C.canonical_hash(samples),
                "training_month": month, "ablation_models": ablations,
                "automatic_promotion": False, "historical_pit_eligible": True}
        body.pop("artifact_sha256", None)
        artifact = {**body, "content_hash": C.canonical_hash(body)}
        artifact_id = "mcm-" + artifact["content_hash"][:24]
        path = C.STORE_RELATIVE / "models" / f"{artifact_id}.json"
        _immutable(root / path, artifact)
        _append(root, C.MODEL_LEDGER, {"ledger_id": artifact_id, "training_month": month,
                "available_at": available, "train_cutoff": cutoff, "artifact_path": path.as_posix(),
                "artifact_hash": artifact["content_hash"]})
        return {"status": "ready", "artifact_id": artifact_id, "available_at": available,
                "training_month": month, "active_families": fitted["active_families"],
                "diagnostics": fitted["diagnostics"], "predictive_validation": "not_established"}


def _fhs(run: dict[str, Any]) -> tuple[np.ndarray | None, str | None]:
    returns = np.diff(np.log(run["replay"]["closes"]))
    # This is an independent historical-window comparator.  No V8 fit or
    # calibrated performance is imported into the market-context model.
    if len(returns) < max(800, C.HORIZON + 90):
        return None, "insufficient_completed_history_for_independent_fhs"
    variance = np.empty(len(returns))
    variance[0] = returns[0] ** 2
    for index in range(1, len(returns)):
        variance[index] = .97 * variance[index - 1] + .03 * returns[index - 1] ** 2
    starts = np.arange(60, len(returns) - C.HORIZON + 1)
    if np.any(variance[starts] <= 0) or variance[-1] <= 0:
        return None, "zero_variance_in_fhs_reference_windows"
    windows = np.lib.stride_tricks.sliding_window_view(returns, C.HORIZON)[starts]
    mu = returns.mean()
    log_paths = mu + (windows - mu) * np.sqrt(variance[-1] / variance[starts])[:, None]
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        values = run["anchor"] * np.exp(np.cumsum(log_paths, axis=1))
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise C.MarketContextError("invalid independent FHS paths; clipping prohibited")
    return values, None


def resolve_context(root: Path, *, as_of: str | None = None) -> dict[str, Any]:
    from . import features as F, model as M
    from .evaluation import score_distribution, score_path_functionals, evaluate_resolutions
    cutoff = C.aware(as_of).isoformat()
    with writer_lock(root):
        C.load_contract(root)
        forecasts = read_chain(root, C.FORECAST_LEDGER)
        resolutions = read_chain(root, C.RESOLUTION_LEDGER)
        done = {(row["forecast_id"], row["horizon"]) for row in resolutions}
        facts = {row["observation_time"]: row for row in F.read_market_rows(root, as_of=cutoff) if row["series_id"] == "NASDAQCOM"}
        completed = set()
        if forecasts:
            _, session_dates, session_closes = F._calendar(cutoff, min(row["anchor_date"] for row in forecasts), C.HORIZON)
            completed = {day for day, close in zip(session_dates, session_closes) if close <= C.aware(cutoff)}
            close_by_date = dict(zip(session_dates, session_closes))
            facts = {day: fact for day, fact in facts.items()
                     if day in close_by_date and C.aware(fact["retrieved_at"]) >= close_by_date[day]}
        appended = 0
        for row in forecasts:
            if C.aware(row["as_of"]) > C.aware(cutoff):
                continue
            run = load_run(root, row)
            pending = [(h, day) for h, day in enumerate(run["future_dates"], 1)
                       if (run["forecast_id"], h) not in done and day in facts and day in completed
                       and max(C.aware(facts[day]["available_at"]), C.aware(facts[day]["retrieved_at"])) > C.aware(run["as_of"])]
            if not pending:
                continue
            projected = _replay(run)
            variants = {"baseline": projected["baseline_paths"], "combined": projected["candidate_paths"]}
            comparison_status = {}
            original_coef = run["replay"]["coefficients"] or {}
            for role in ("market_only", "event_only"):
                coef = original_coef.get("ablation_models", {}).get(role)
                families = set((coef or {}).get("active_families", []))
                vector = _family_state(run["replay"]["reference_state"], families)
                comparison_status[role] = (coef or {}).get("status", "not_fitted_baseline_identity")
                if coef and coef.get("status") == "ready":
                    variants[role] = M.project_paths(run["replay"]["closes"], state=vector, coefficients=coef,
                        future_dates=run["future_dates"], n_paths=C.PATH_COUNT, seed=C.SEED)["candidate_paths"]
            fhs, fhs_reason = _fhs(run)
            if fhs is not None:
                variants["fhs"] = fhs
            comparison_status["fhs"] = fhs_reason or "independent_completed_historical_windows"
            for horizon, day in pending:
                fact = facts[day]
                actual = float(fact["value"])
                record = run["records"][horizon - 1]
                previous_date = run["anchor_date"] if horizon == 1 else run["future_dates"][horizon - 2]
                previous_fact = facts.get(previous_date)
                previous = run["anchor"] if horizon == 1 else (float(previous_fact["value"]) if previous_fact else None)
                available = max(C.aware(fact["available_at"]), C.aware(fact["retrieved_at"]))
                if previous_fact:
                    available = max(available, C.aware(previous_fact["available_at"]), C.aware(previous_fact["retrieved_at"]))
                if available > C.aware(cutoff):
                    continue
                scores = {name: score_distribution(values[:, horizon - 1], actual) for name, values in variants.items()}
                actual_prefix = [facts[date]["value"] for date in run["future_dates"][:horizon] if date in facts]
                path_scores = ({name: score_path_functionals(values[:, :horizon], actual_prefix, anchor=run["anchor"])
                               for name, values in variants.items()}
                              if len(actual_prefix) == horizon and horizon in C.TRAIN_HORIZONS else None)
                payload = {"ledger_id": "mcr-" + C.canonical_hash({"forecast_id": run["forecast_id"], "horizon": horizon})[:24],
                    "forecast_id": run["forecast_id"], "anchor_date": run["anchor_date"], "as_of": run["as_of"],
                    "horizon": horizon, "target_date": day, "actual_index": actual, "available_at": available.isoformat(),
                    "resolved_at": cutoff, "source_id": fact["source_id"], "source_sha256": fact.get("source_sha256"),
                    "observation_vintage_rule": "latest_eligible_at_first_resolution_then_immutable",
                    "scoring_code_hash": C.model_code_hash(root),
                    "probability_unit": "fraction", "probability_up_from_previous": record["probability_up_from_previous"],
                    "actual_up_from_previous": None if previous is None else actual > previous,
                    "brier": None if previous is None else (record["probability_up_from_previous"] - float(actual > previous)) ** 2,
                    "scores": scores, "path_scores": path_scores,
                    "comparison_status": comparison_status, "data_grade": "captured_forward",
                    "predictive_validation": "not_established"}
                _append(root, C.RESOLUTION_LEDGER, payload)
                appended += 1
        all_rows = read_chain(root, C.RESOLUTION_LEDGER)
        evaluation = evaluate_resolutions(all_rows)
        return {"status": "ok", "resolved": appended, "evaluation": evaluation,
                "predictive_validation": "not_established"}
