"""Independent append-only weekly forecasts and daily maturation for daily6m."""

from __future__ import annotations

import hashlib
import gzip
import json
import math
import os
import re
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

import numpy as np

from . import contracts as C
from . import features as F

_SOURCE_REVISION_KEYS = ("source_id", "series_id", "observation_time", "value", "available_at", "vintage_start", "source_hash")


class Daily6mPipelineError(RuntimeError):
    """An append, correction, or immutable forecast artifact was invalid."""


@contextmanager
def writer_lock(root: Path):
    """Serialize local and CI writers; operating-system locks release on exit."""
    path = root / "outputs/timeseries_daily6m/.writer.lock"
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
            raise Daily6mPipelineError("another daily6m writer owns the research-store lock") from exc
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


def serialized_writer(function):
    @wraps(function)
    def run(root: Path, *args, **kwargs):
        with writer_lock(root):
            return function(root, *args, **kwargs)
    return run


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _immutable(path: Path, value: dict[str, Any]) -> None:
    if path.is_file():
        if _json(path) != value:
            raise Daily6mPipelineError("immutable run collision: " + path.name)
        return
    _atomic(path, value)


def read_chain(root: Path, relative: Path) -> list[dict[str, Any]]:
    rows = _rows(root / relative)
    previous = None
    identities = set()
    active_weeks: dict[str, str] = {}
    seen_forecasts: dict[str, dict[str, Any]] = {}
    active_resolutions: dict[tuple[str, str], str] = {}
    seen_resolutions: dict[str, dict[str, Any]] = {}
    for row in rows:
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("previous_hash") != previous or row.get("content_hash") != C.canonical_hash(body):
            raise Daily6mPipelineError("ledger hash chain mismatch: " + str(relative))
        identity = row.get("forecast_id") if relative == C.FORECAST_LEDGER else row.get("resolution_id")
        if not identity or identity in identities:
            raise Daily6mPipelineError("duplicate or missing ledger identity")
        identities.add(identity)
        if relative == C.FORECAST_LEDGER:
            week = str(row.get("iso_week", ""))
            target = row.get("supersedes")
            if not week:
                raise Daily6mPipelineError("forecast ISO week missing")
            if target is None:
                if week in active_weeks:
                    raise Daily6mPipelineError("multiple active forecasts in one ISO week")
            elif target not in seen_forecasts or seen_forecasts[target].get("iso_week") != week or active_weeks.get(week) != target:
                raise Daily6mPipelineError("supersedes must refer to an earlier active forecast in the same ISO week")
            active_weeks[week] = str(identity)
            seen_forecasts[str(identity)] = row
        elif relative == C.RESOLUTION_LEDGER:
            key = (row.get("forecast_id"), row.get("date"))
            target = row.get("supersedes")
            if not all(isinstance(value, str) and value for value in key):
                raise Daily6mPipelineError("resolution forecast/date identity missing")
            if target is None:
                if key in active_resolutions:
                    raise Daily6mPipelineError("multiple active resolutions for one forecast/date")
            elif (not isinstance(target, str) or target not in seen_resolutions
                  or active_resolutions.get(key) != target):
                raise Daily6mPipelineError("resolution supersedes must identify the earlier active revision for the same forecast/date")
            if target is not None:
                prior = seen_resolutions[target]
                if (F.aware_time(row["resolved_as_of"]) < F.aware_time(prior["resolved_as_of"])
                        or row.get("source_revision_hash") == prior.get("source_revision_hash")):
                    raise Daily6mPipelineError("resolution correction must preserve time order and change a source revision")
            active_resolutions[key] = str(identity)
            seen_resolutions[str(identity)] = row
        previous = row["content_hash"]
    return rows


def _append(root: Path, relative: Path, payload: dict[str, Any], *, identity: str) -> dict[str, Any]:
    rows = read_chain(root, relative)
    for row in rows:
        if row.get(identity) == payload.get(identity):
            if any(row.get(key) != value for key, value in payload.items()):
                raise Daily6mPipelineError("append-only identity collision")
            return row
    body = {**payload, "previous_hash": rows[-1]["content_hash"] if rows else None}
    row = {**body, "content_hash": C.canonical_hash(body)}
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


def hold_payload(reasons: list[str], *, as_of: str | None = None, status: str = "hold", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    body = {"schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "status": status, "numbers_visible": False, "as_of": as_of, "probability_unit": "fraction", "probability_space": "research_timeseries_daily6m_conditional", "combined_with_existing_models": False, "gate": {"pass": False, "reasons": list(dict.fromkeys(reasons))}, "evidence": {"strict_historical_pit": "not_established", "predictive_validation": "not_established", "research_only": True, **(evidence or {})}, "footnote": "연구 미리보기 · 일별 예측 확률의 예측력은 아직 검증되지 않았습니다 · 참고 의견이며 매매 신호가 아닙니다."}
    return {**body, "content_hash": C.canonical_hash(body)}


def validate_run(run: dict[str, Any]) -> None:
    from .model import future_session_dates
    if run.get("model_id") != C.MODEL_ID or run.get("probability_unit") != "fraction" or run.get("probability_space") != "research_timeseries_daily6m_conditional" or run.get("numbers_visible") is not True or run.get("status") != "research_preview":
        raise Daily6mPipelineError("forecast model/unit/visibility contract mismatch")
    F.aware_time(run["as_of"])
    if run.get("anchor_date") != F.last_completed_session(run["as_of"]):
        raise Daily6mPipelineError("new forecast anchor must precede only uncompleted target sessions at issuance")
    if not isinstance(run.get("anchor"), dict) or not math.isfinite(float(run["anchor"]["value"])) or float(run["anchor"]["value"]) <= 0:
        raise Daily6mPipelineError("forecast anchor must be positive and finite")
    dates, records = run.get("dates") or [], run.get("records") or []
    if not dates or dates != sorted(set(dates)) or dates != [row["date"] for row in records] or dates[0] <= run["anchor_date"]:
        raise Daily6mPipelineError("forecast dates must be ordered future sessions")
    expected_dates, calendar_end, calendar_hash = future_session_dates(run["anchor_date"])
    if dates != expected_dates or run.get("calendar_end_date") != calendar_end or run.get("calendar_hash") != calendar_hash or run.get("path_count") != C.PATH_COUNT:
        raise Daily6mPipelineError("forecast must contain exactly six calendar months of 20000 joint paths")
    samples = run.get("sample_paths") or []
    if len(samples) != 5 or len({row["path_id"] for row in samples}) != 5:
        raise Daily6mPipelineError("forecast needs exactly five distinct actual sample paths")
    if run.get("gate", {}).get("pass") is not True or run.get("comparison", {}).get("v8_raw_identity", {}).get("pass") is not True or not run.get("comparison", {}).get("fhs") or run.get("evidence", {}).get("predictive_validation") != "not_established":
        raise Daily6mPipelineError("research preview gates or comparison disclosure missing")
    for row in records:
        bands = [float(row["band_index"][key]) for key in C.QUANTILE_NAMES]
        if not all(math.isfinite(value) and value > 0 for value in bands) or bands != sorted(bands) or not math.isclose(float(row["median_index"]), bands[2], rel_tol=1e-10, abs_tol=1e-8):
            raise Daily6mPipelineError("forecast band crossing or median mismatch")
        for key in ("probability_up_from_previous", "probability_up_from_origin"):
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise Daily6mPipelineError("forecast probability outside explicit fraction bounds")
    for row in run.get("sample_paths") or []:
        if len(row["values"]) != len(dates) or not all(math.isfinite(float(value)) and float(value) > 0 for value in row["values"]):
            raise Daily6mPipelineError("sample path length or level invalid")
    for row in run.get("source_lineage", {}).get("market_rows", []):
        native = row.get("source_id") == "alfred"
        tail = (row.get("source_id") == "cboe_vix_archive" and row.get("series_id") == "VIXCLS" and row.get("session") == run["anchor_date"] and row.get("observation_time") == run["anchor_date"] and row.get("data_grade") == "captured_forward" and row.get("receipt_verified") is True and bool(row.get("receipt_id")) and row.get("raw_sha256") == row.get("source_hash"))
        if (not native and not tail) or not isinstance(row.get("source_hash"), str) or re.fullmatch(r"[0-9a-f]{64}", row["source_hash"]) is None:
            raise Daily6mPipelineError("forecast native source identity or SHA256 provenance missing")
        if F.aware_time(row["available_at"]) > F.aware_time(run["as_of"]) or F.aware_time(row["vintage_start"]) > F.aware_time(run["as_of"]):
            raise Daily6mPipelineError("forecast source became available after issuance")
        if not row.get("retrieved_at") or F.aware_time(row["retrieved_at"]) > F.aware_time(run["as_of"]):
            raise Daily6mPipelineError("forecast source capture is after issuance or missing")
    for row in run.get("source_lineage", {}).get("factor_rows", []):
        if any(not isinstance(row.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", row[key]) is None for key in ("input_hash", "content_hash")):
            raise Daily6mPipelineError("forecast derived-factor SHA256 provenance missing")
        if F.aware_time(row["cutoff"]) > F.aware_time(run["as_of"]) or (row.get("cache_materialized_at") is not None and F.aware_time(row["cache_materialized_at"]) > F.aware_time(run["as_of"])):
            raise Daily6mPipelineError("forecast derived factor became available after issuance")
    if not run.get("source_lineage", {}).get("market_rows") or not run.get("source_lineage", {}).get("factor_rows"):
        raise Daily6mPipelineError("forecast must preserve market and derived-factor provenance")
    groups = {row["series_id"] for row in run["source_lineage"]["market_rows"]}
    if not {"NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y"}.issubset(groups) or not groups.intersection({"DTWEXB", "DTWEXBGS"}):
        raise Daily6mPipelineError("forecast five logical market input groups lack lineage")
    expected = run.get("content_hash")
    if expected is not None and expected != C.canonical_hash({key: value for key, value in run.items() if key != "content_hash"}):
        raise Daily6mPipelineError("forecast run content hash mismatch")


def load_run(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    relative = Path(str(row["run_path"]))
    path = (root / relative).resolve()
    if not path.is_relative_to((root / C.STORE_RELATIVE / "runs").resolve()):
        raise Daily6mPipelineError("forecast run path outside research store")
    run = _json(path)
    validate_run(run)
    if run["content_hash"] != row.get("run_content_hash") or run["run_id"] != row.get("forecast_id"):
        raise Daily6mPipelineError("forecast ledger/run identity mismatch")
    if run.get("contract_hash") != C.frozen_hash(C.load_contract(root)) or run.get("model_code_hash") != C.model_code_hash(root):
        raise Daily6mPipelineError("forecast contract or numerical dependency identity changed")
    return run


def _active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    superseded = {row["supersedes"] for row in rows if row.get("supersedes")}
    return [row for row in rows if row["forecast_id"] not in superseded]


def _outcome_source(source: Any) -> dict[str, Any]:
    """Pin the exact native close, publication vintage, and source capture."""
    end = source.get("vintage_end")
    end = None if end is None or str(end) in {"NaT", "nan", "<NA>"} else F.aware_time(str(end)).isoformat()
    return {
        "source_id": str(source["source_id"]), "series_id": str(source["series_id"]),
        "observation_time": str(source["observation_time"]), "value": float(source["value"]),
        "available_at": F.aware_time(str(source["available_at"])).isoformat(),
        "vintage_start": F.aware_time(str(source["vintage_start"])).isoformat(),
        "vintage_end": end, "retrieved_at": F.aware_time(str(source["retrieved_at"])).isoformat(),
        "source_hash": str(source["source_hash"]), "data_grade": str(source.get("data_grade", "native_pit")),
    }


def _source_revision_hash(actual: dict[str, Any], previous: dict[str, Any]) -> str:
    # A receipt recapture alone is not a published-close correction. Retain the
    # initial capture provenance when only retrieved_at or vintage_end changes.
    return C.canonical_hash({"actual": {key: actual[key] for key in _SOURCE_REVISION_KEYS}, "previous": {key: previous[key] for key in _SOURCE_REVISION_KEYS}})


def _pinned_source_hash(source: dict[str, Any]) -> str:
    return C.canonical_hash({key: source[key] for key in (*_SOURCE_REVISION_KEYS, "retrieved_at", "data_grade")})


def _native_outcome_source_index(root: Path) -> set[str]:
    """Replay preserved facts, including same-vintage corrections no longer in Parquet."""
    rows = _rows(root / "data/timeseries/ledgers/observations.jsonl")
    chunk_root = (root / "data/timeseries/facts/observation_chunks").resolve()
    for manifest in _rows(root / "data/timeseries/ledgers/observation_chunks.jsonl"):
        if manifest.get("series_id") != "NASDAQCOM":
            continue
        path = (root / manifest["chunk_path"]).resolve()
        if not path.is_relative_to(chunk_root):
            raise Daily6mPipelineError("resolution native fact chunk escaped its registered container")
        body = gzip.decompress(path.read_bytes())
        digest = hashlib.sha256(body).hexdigest()
        if digest != manifest.get("content_sha256") or digest != manifest.get("chunk_id"):
            raise Daily6mPipelineError("resolution native fact chunk SHA256 mismatch")
        chunk_rows = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        if len(chunk_rows) != manifest.get("row_count"):
            raise Daily6mPipelineError("resolution native fact chunk row count mismatch")
        rows.extend(chunk_rows)
    return {_pinned_source_hash(_outcome_source(row)) for row in rows
            if row.get("source_id") == "alfred" and row.get("series_id") == "NASDAQCOM" and row.get("value_status") == "ok"}


def _validate_resolution_source_replay(row: dict[str, Any], source_index: set[str]) -> None:
    if any(_pinned_source_hash(row[key]) not in source_index for key in ("actual_source", "previous_source")):
        raise Daily6mPipelineError("resolution close or capture provenance does not match a preserved native fact")


def _resolution_id(row: dict[str, Any]) -> str:
    initial = row["forecast_id"] + ":" + row["date"]
    if row.get("supersedes") is None:
        return initial
    return initial + ":" + C.canonical_hash({"source_revision_hash": row["source_revision_hash"], "supersedes": row["supersedes"]})[:24]


def validate_resolution(row: dict[str, Any], run: dict[str, Any]) -> None:
    """Replay scoring against the immutable forecast and pinned native facts."""
    if row.get("schema_version") != 1 or row.get("forecast_id") != run["run_id"] or row.get("probability_unit") != "fraction":
        raise Daily6mPipelineError("resolution forecast/unit contract mismatch")
    dates = run["dates"]
    day = row.get("date")
    if day not in dates:
        raise Daily6mPipelineError("resolution date is not an immutable forecast target")
    index = dates.index(day)
    previous_day = dates[index - 1] if index else run["anchor_date"]
    if row.get("previous_session") != previous_day:
        raise Daily6mPipelineError("resolution previous session differs from the immutable forecast")
    if not isinstance(row.get("resolved_as_of"), str) or not row["resolved_as_of"].strip():
        raise Daily6mPipelineError("resolution time must be explicit and timezone aware")
    cutoff = F.aware_time(row["resolved_as_of"])
    if cutoff < F.aware_time(run["as_of"]) or day > F.last_completed_session(cutoff):
        raise Daily6mPipelineError("resolution target close was not completed at resolution time")
    for key in ("actual_index", "actual_previous_index", "probability_up_from_previous", "brier"):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise Daily6mPipelineError("resolution numerical values must be finite and explicit")
    actual, previous = row["actual_index"], row["actual_previous_index"]
    p, brier = row["probability_up_from_previous"], row["brier"]
    record = run["records"][index]
    if actual <= 0 or previous <= 0 or not 0 <= p <= 1 or not math.isclose(p, record["probability_up_from_previous"], rel_tol=0, abs_tol=1e-12):
        raise Daily6mPipelineError("resolution close or immutable forecast probability mismatch")
    outcome = actual > previous
    inside = record["band_index"]["p10"] <= actual <= record["band_index"]["p90"]
    if type(row.get("outcome_up")) is not bool or row["outcome_up"] != outcome:
        raise Daily6mPipelineError("resolution outcome does not match the two native closes")
    if not 0 <= brier <= 1 or not math.isclose(brier, (p - int(outcome)) ** 2, rel_tol=0, abs_tol=1e-12):
        raise Daily6mPipelineError("resolution Brier score differs from the immutable probability and outcome")
    if type(row.get("inside_p10_p90")) is not bool or row["inside_p10_p90"] != inside:
        raise Daily6mPipelineError("resolution band inclusion differs from the immutable forecast")
    for key, expected_day, value in (("actual_source", day, actual), ("previous_source", previous_day, previous)):
        source = row.get(key)
        if (not isinstance(source, dict) or source.get("source_id") != "alfred" or source.get("series_id") != "NASDAQCOM"
                or source.get("observation_time") != expected_day or source.get("data_grade") != "native_pit"
                or not isinstance(source.get("source_hash"), str) or re.fullmatch(r"[0-9a-f]{64}", source["source_hash"]) is None):
            raise Daily6mPipelineError("resolution native close source identity or SHA256 missing")
        source_value = source.get("value")
        if isinstance(source_value, bool) or not isinstance(source_value, (int, float)) or not math.isfinite(source_value) or source_value != value:
            raise Daily6mPipelineError("resolution native source close differs from the scored close")
        timestamps = ("available_at", "vintage_start", "retrieved_at")
        if any(not isinstance(source.get(name), str) or not source[name].strip() for name in timestamps):
            raise Daily6mPipelineError("resolution native publication, vintage and capture times must be explicit")
        if any(F.aware_time(source[name]) > cutoff for name in timestamps):
            raise Daily6mPipelineError("resolution native source publication or capture is after resolution time")
        if source.get("vintage_end") is not None:
            if not isinstance(source["vintage_end"], str) or F.aware_time(source["vintage_end"]) <= cutoff:
                raise Daily6mPipelineError("resolution native close vintage was expired or invalid at resolution time")
    current_source, prior_source = row["actual_source"], row["previous_source"]
    aliases = {"available_at": current_source["available_at"], "source_vintage_start": current_source["vintage_start"], "previous_available_at": prior_source["available_at"], "previous_vintage_start": prior_source["vintage_start"]}
    if any(row.get(key) != value for key, value in aliases.items()) or row.get("source_revision_hash") != _source_revision_hash(current_source, prior_source):
        raise Daily6mPipelineError("resolution source revision provenance mismatch")
    supersedes = row.get("supersedes")
    if (row.get("resolution_id") != _resolution_id(row)
            or row.get("resolution_kind") != ("initial" if supersedes is None else "correction")
            or (supersedes is not None and (not isinstance(row.get("revision_reason"), str) or not row["revision_reason"].strip()))):
        raise Daily6mPipelineError("resolution identity or explicit correction reason mismatch")


@serialized_writer
def forecast_timeseries_daily6m(root: Path, *, as_of: str | datetime | None = None, supersedes: str | None = None, save_paths: bool = True, path_count: int = C.PATH_COUNT) -> dict[str, Any]:
    """Append one independent forecast per ISO week, or an explicit revision."""
    from .model import future_session_dates, generate_forecast_with_paths
    cutoff = F.aware_time(as_of)
    stamp = cutoff.isoformat()
    contract = C.load_contract(root)
    try:
        frame = F.read_native_frame(root, as_of=cutoff)
        early_freshness = F.source_freshness(frame, cutoff)
        if any(row["status"] != "fresh" for row in early_freshness):
            return hold_payload(["required source " + row["group"] + " " + row["status"] for row in early_freshness if row["status"] != "fresh"], as_of=stamp, evidence={"source_freshness": list(early_freshness)})
        bundle = F.build_bundle(root, as_of=cutoff, rows=frame)
    except (F.Daily6mFeatureError, OSError, ValueError, RuntimeError) as exc:
        return hold_payload([str(exc)], as_of=stamp)
    if bundle.issues:
        return hold_payload(list(bundle.issues), as_of=stamp, evidence={"source_freshness": list(bundle.freshness)})
    prior = read_chain(root, C.FORECAST_LEDGER)
    iso = datetime.fromisoformat(bundle.anchor["date"]).date().isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    existing = [row for row in _active(prior) if row["iso_week"] == week]
    if supersedes is None and existing:
        return {**load_run(root, existing[-1]), "skipped": "forecast already exists for this ISO week"}
    if supersedes is not None:
        target = [row for row in _active(prior) if row["forecast_id"] == supersedes]
        if len(target) != 1 or target[0]["iso_week"] != week:
            raise Daily6mPipelineError("supersedes must identify the active revision in the same ISO week")
    dates, end, calendar_hash = future_session_dates(bundle.anchor["date"])
    modeled, paths = generate_forecast_with_paths(bundle, anchor=bundle.anchor["value"], as_of=stamp, future_dates=dates, history=bundle.history, lineage=bundle.lineage, path_count=path_count)
    modeled.pop("content_hash", None)
    modeled.pop("lineage", None)
    seed = {"model_id": C.MODEL_ID, "as_of": stamp, "origin_session": bundle.anchor["date"], "contract_hash": C.frozen_hash(contract), "model_code_hash": C.model_code_hash(root), "path_hash": modeled["path_hash"], "supersedes": supersedes}
    run_id = "daily6m-" + C.canonical_hash(seed)[:24]
    body = {**modeled, **seed, "schema_version": 1, "model_version": C.MODEL_VERSION, "run_id": run_id, "status": "research_preview", "numbers_visible": True, "probability_unit": "fraction", "probability_space": "research_timeseries_daily6m_conditional", "combined_with_existing_models": False, "anchor": bundle.anchor, "anchor_date": bundle.anchor["date"], "dates": dates, "calendar_end_date": end, "forecast_end_date": dates[-1], "calendar_hash": calendar_hash, "history": bundle.history, "iso_week": week, "source_lineage": bundle.lineage, "source_freshness": list(bundle.freshness), "gate": {"pass": True, "reasons": [], "origin_age_sessions_at_issue": bundle.origin_age_sessions}, "evidence": {"strict_historical_pit": "not_established", "predictive_validation": "not_established", "research_only": True}, "footnote": hold_payload([])["footnote"]}
    if supersedes is not None:
        body["revision_reason"] = "explicit supersedes request; prior immutable revision retained"
    if save_paths:
        relative = Path("outputs/timeseries_daily6m/paths") / f"{run_id}.npz"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            with np.load(target, allow_pickle=False) as previous:
                if not np.array_equal(previous["index_paths"], paths):
                    raise Daily6mPipelineError("immutable joint path collision")
        else:
            temporary = target.with_suffix(".tmp")
            with temporary.open("wb") as handle:
                np.savez_compressed(handle, index_paths=np.asarray(paths, dtype=np.float64))
            os.replace(temporary, target)
        body["joint_path_artifact"] = {"path": relative.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "shape": list(paths.shape), "optional_local_artifact": True}
    run = {**body, "content_hash": C.canonical_hash(body)}
    validate_run(run)
    # Recheck the read-only inputs at the append boundary, where freshness and
    # availability may have changed during the numerical run.
    boundary = F.aware_time()
    freshness = F.source_freshness(F.read_native_frame(root, as_of=boundary), boundary)
    if any(row["status"] != "fresh" for row in freshness) or F.origin_age(bundle.anchor["date"], boundary) >= 10 or F.last_completed_session(boundary) != bundle.anchor["date"]:
        return hold_payload(["write-time source freshness or origin-age gate failed"], as_of=stamp)
    run_path = C.STORE_RELATIVE / "runs" / f"{run_id}.json"
    _immutable(root / run_path, run)
    _append(root, C.FORECAST_LEDGER, {"forecast_id": run_id, "as_of": stamp, "origin_session": bundle.anchor["date"], "iso_week": week, "supersedes": supersedes, "run_path": run_path.as_posix(), "run_content_hash": run["content_hash"], "probability_unit": "fraction"}, identity="forecast_id")
    return run


@serialized_writer
def resolve_timeseries_daily6m(root: Path, *, as_of: str | datetime | None = None) -> dict[str, Any]:
    cutoff = F.aware_time(as_of)
    frame = F.read_native_frame(root, as_of=cutoff)
    observed = frame[frame["series_id"] == "NASDAQCOM"].set_index("day")
    forecasts = read_chain(root, C.FORECAST_LEDGER)
    resolved = read_chain(root, C.RESOLUTION_LEDGER)
    runs = {forecast["forecast_id"]: load_run(root, forecast) for forecast in forecasts}
    source_index = _native_outcome_source_index(root) if forecasts else set()
    active: dict[tuple[str, str], dict[str, Any]] = {}
    for row in resolved:
        if row["forecast_id"] not in runs:
            raise Daily6mPipelineError("resolution references a missing forecast")
        validate_resolution(row, runs[row["forecast_id"]])
        _validate_resolution_source_replay(row, source_index)
        active[(row["forecast_id"], row["date"])] = row
    completed = F.last_completed_session(cutoff)
    latest_observed = str(observed.index.max()) if not observed.empty else None
    # Missing unpublished closes wait. A hole before a later published close
    # is an input error, checked before any resolution append in this run.
    for run in runs.values():
        previous_day = run["anchor_date"]
        for day in run["dates"]:
            if latest_observed is not None and day <= min(completed, latest_observed):
                if day not in observed.index or previous_day not in observed.index:
                    raise Daily6mPipelineError("resolution native close gap " + (day if day not in observed.index else previous_day))
            previous_day = day
    appended = corrected = 0
    # Every preserved issuance keeps accruing outcomes, including superseded
    # revisions. Selecting a current display must not hide historical results.
    for forecast in forecasts:
        run = runs[forecast["forecast_id"]]
        previous_day = run["anchor_date"]
        for record in run["records"]:
            day = record["date"]
            key = (run["run_id"], day)
            if day <= completed and day in observed.index and previous_day in observed.index:
                actual_source = _outcome_source(observed.loc[day])
                previous_source = _outcome_source(observed.loc[previous_day])
                revision_hash = _source_revision_hash(actual_source, previous_source)
                prior = active.get(key)
                if prior is not None and prior["source_revision_hash"] == revision_hash:
                    previous_day = day
                    continue
                if prior is not None and cutoff < F.aware_time(prior["resolved_as_of"]):
                    raise Daily6mPipelineError("resolution correction cannot precede the active resolution time")
                actual, previous = actual_source["value"], previous_source["value"]
                outcome = bool(actual > previous)
                p = float(record["probability_up_from_previous"])
                payload = {
                    "schema_version": 1, "forecast_id": run["run_id"], "date": day, "previous_session": previous_day,
                    "available_at": actual_source["available_at"], "resolved_as_of": cutoff.isoformat(),
                    "actual_index": actual, "actual_previous_index": previous,
                    "previous_available_at": previous_source["available_at"], "previous_vintage_start": previous_source["vintage_start"],
                    "probability_up_from_previous": p, "probability_unit": "fraction", "outcome_up": outcome,
                    "brier": (p - int(outcome)) ** 2, "inside_p10_p90": record["band_index"]["p10"] <= actual <= record["band_index"]["p90"],
                    "source_vintage_start": actual_source["vintage_start"], "actual_source": actual_source, "previous_source": previous_source,
                    "source_revision_hash": revision_hash, "supersedes": prior["resolution_id"] if prior is not None else None,
                    "resolution_kind": "correction" if prior is not None else "initial",
                    "revision_reason": "native published close or source vintage revised; previous resolution preserved" if prior is not None else None,
                }
                payload["resolution_id"] = _resolution_id(payload)
                validate_resolution(payload, run)
                _validate_resolution_source_replay(payload, source_index)
                active[key] = _append(root, C.RESOLUTION_LEDGER, payload, identity="resolution_id")
                appended += 1
                corrected += int(prior is not None)
            previous_day = day
    return {"resolved": appended, "corrected": corrected, "total_resolutions": len(resolved) + appended, "active_resolutions": len(active), "probability_unit": "fraction", "predictive_validation": "not_established"}


@serialized_writer
def publish_latest_timeseries_daily6m(root: Path, *, as_of: str | datetime | None = None) -> dict[str, Any]:
    from .display import project_run
    cutoff = F.aware_time(as_of)
    active = _active(read_chain(root, C.FORECAST_LEDGER))
    if active:
        result = project_run(root, load_run(root, active[-1]), now=cutoff)
    else:
        reasons = ["no independent daily6m forecast exists"]
        evidence = {}
        state = "absent"
        try:
            frame = F.read_native_frame(root, as_of=cutoff)
            freshness = F.source_freshness(frame, cutoff)
            evidence["source_freshness"] = list(freshness)
            rejected = ["required source " + row["group"] + " " + row["status"] for row in freshness if row["status"] != "fresh"]
            if rejected:
                reasons.extend(rejected)
                state = "hold"
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            reasons.append("current preflight rejected: " + str(exc))
            state = "hold"
        result = hold_payload(reasons, as_of=cutoff.isoformat(), status=state, evidence=evidence)
    if result["numbers_visible"]:
        body = {"schema_version": 1, "model_id": C.MODEL_ID, "run_id": result["run_id"], "run_path": active[-1]["run_path"], "run_content_hash": result["content_hash"], "status": "research_preview", "numbers_visible": True, "as_of": result["as_of"]}
        pointer = {**body, "content_hash": C.canonical_hash(body)}
    else:
        pointer = result
    _atomic(root / C.LATEST_RELATIVE, pointer)
    return result


def verify_timeseries_daily6m(root: Path) -> dict[str, Any]:
    errors = []
    missing_artifacts = []
    try:
        C.load_contract(root)
        forecasts = read_chain(root, C.FORECAST_LEDGER)
        resolutions = read_chain(root, C.RESOLUTION_LEDGER)
        by_id = {row["forecast_id"]: row for row in forecasts}
        runs = {}
        for row in forecasts:
            if row.get("supersedes") and row["supersedes"] not in by_id:
                raise Daily6mPipelineError("supersedes missing prior forecast")
            run = load_run(root, row)
            runs[row["forecast_id"]] = run
            artifact = run.get("joint_path_artifact")
            if artifact:
                path = (root / artifact["path"]).resolve()
                if not path.is_relative_to((root / "outputs/timeseries_daily6m/paths").resolve()):
                    raise Daily6mPipelineError("joint path artifact containment mismatch")
                if not path.exists() and artifact.get("optional_local_artifact") is True:
                    missing_artifacts.append(str(artifact["path"]))
                else:
                    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                        raise Daily6mPipelineError("joint path artifact hash mismatch")
                    with np.load(path, allow_pickle=False) as arrays:
                        values = arrays["index_paths"]
                        if values.shape != (C.PATH_COUNT, len(run["dates"])) or list(values.shape) != artifact["shape"] or hashlib.sha256(np.ascontiguousarray(values, dtype=np.float64).tobytes()).hexdigest() != run["path_hash"]:
                            raise Daily6mPipelineError("joint path shape or numerical content mismatch")
                        from .model import summarize_joint_paths
                        records, samples = summarize_joint_paths(values, anchor=run["anchor"]["value"], future_dates=run["dates"])
                        if records != run["records"] or samples != run["sample_paths"]:
                            raise Daily6mPipelineError("joint-path summary or sample members mismatch")
        for row in resolutions:
            if row["forecast_id"] not in by_id:
                raise Daily6mPipelineError("resolution forecast/unit contract mismatch")
            validate_resolution(row, runs[row["forecast_id"]])
        if resolutions:
            source_index = _native_outcome_source_index(root)
            for row in resolutions:
                _validate_resolution_source_replay(row, source_index)
        return {"ok": True, "errors": [], "forecasts": len(forecasts), "resolutions": len(resolutions), "missing_optional_path_artifacts": missing_artifacts, "predictive_validation": "not_established"}
    except (OSError, EOFError, ValueError, KeyError, TypeError, Daily6mPipelineError, C.Daily6mContractError) as exc:
        errors.append(str(exc))
    return {"ok": False, "errors": errors}
