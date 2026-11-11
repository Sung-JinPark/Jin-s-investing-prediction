"""Append-only paired issuance, paired scoring and verification for the daily6m v2 shadow.

v1 files are read only.  Every v2 run pairs with one v1 run (its latest active
forecast) and is issued before the first target close; missed origins are never
back-filled.  Scoring reuses the v1 resolution ledger's pinned native closes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.timeseries_daily6m import contracts as v1C
from ai_fc.timeseries_daily6m import features as F
from ai_fc.timeseries_daily6m import pipeline as P

from . import kernel as K
from .contracts import (
    ARMS, CONSTANTS_RELATIVE, Daily6mV2ContractError, FOOTNOTE, FORECAST_LEDGER, MODEL_ID, MODEL_VERSION,
    OUTPUTS_RELATIVE, PAIR_RULE_REVISION, PRIMARY_ELIGIBILITY, PRIOR_IDENTITIES, PROBABILITY_SPACE, RESOLUTION_LEDGER,
    RUNS_RELATIVE, STORE_RELATIVE, VERDICT_LEDGER, canonical_hash, classify_pair, frozen_hash, load_constants, load_contract,
    model_code_hash, orchestration_code_hashes,
)

LEDGER_IDENTITY = {FORECAST_LEDGER: "forecast_id", RESOLUTION_LEDGER: "resolution_id", VERDICT_LEDGER: "verdict_id"}
FUTURE_AS_OF_TOLERANCE = timedelta(minutes=5)
V1_REFERENCE_TOLERANCE = 1e-9   # run v1_reference.records vs the paired v1 run file (spec §3.5)


class Daily6mV2PipelineError(RuntimeError):
    """A v2 append, immutable run or replay check failed."""


def _now() -> datetime:
    return F.aware_time(None)


@contextmanager
def writer_lock(root: Path):
    path = root / OUTPUTS_RELATIVE / ".writer.lock"
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
            raise Daily6mV2PipelineError("another daily6m v2 writer owns the shadow-store lock") from exc
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


def atomic_json(path: Path, value: dict[str, Any], *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if compact:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    temporary.write_text(text + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _immutable(path: Path, value: dict[str, Any]) -> None:
    if path.is_file():
        if _json(path) != value:
            raise Daily6mV2PipelineError("immutable v2 run collision: " + path.name)
        return
    atomic_json(path, value, compact=True)  # runs are compact (≈ 380 KB/run budget, acceptance ≤ 500 KB)


def read_chain(root: Path, relative: Path) -> list[dict[str, Any]]:
    """Hash chain plus per-ledger identity rules."""
    rows = _rows(root / relative)
    identity_key = LEDGER_IDENTITY[relative]
    previous = None
    identities: set[str] = set()
    paired: set[str] = set()
    kinds: set[str] = set()
    active: dict[tuple, str] = {}
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        body = {key: value for key, value in row.items() if key != "content_hash"}
        if row.get("previous_hash") != previous or row.get("content_hash") != canonical_hash(body):
            raise Daily6mV2PipelineError("ledger hash chain mismatch: " + relative.as_posix())
        identity = row.get(identity_key)
        if not isinstance(identity, str) or not identity or identity in identities:
            raise Daily6mV2PipelineError("duplicate or missing ledger identity: " + relative.as_posix())
        identities.add(identity)
        if relative == FORECAST_LEDGER:
            pair = row.get("paired_v1_forecast_id")
            if not isinstance(pair, str) or pair in paired or row.get("supersedes") is not None:
                raise Daily6mV2PipelineError("one v2 run per v1 run, without supersedes")
            paired.add(pair)
        elif relative == RESOLUTION_LEDGER:
            key = (row.get("v2_run_id"), row.get("arm"), row.get("date"))
            target = row.get("supersedes")
            if target is None:
                if key in active:
                    raise Daily6mV2PipelineError("multiple active v2 resolutions for one run/arm/date")
            else:
                if active.get(key) != target:
                    raise Daily6mV2PipelineError("v2 resolution supersedes must identify the active row for the same run/arm/date")
                prior = seen[target]
                if (F.aware_time(row["resolved_as_of"]) < F.aware_time(prior["resolved_as_of"])
                        or row.get("v1_resolution_id") == prior.get("v1_resolution_id")):
                    raise Daily6mV2PipelineError("v2 correction must follow time order and a changed v1 resolution")
            active[key] = identity
            seen[identity] = row
        else:
            kind = row.get("kind")
            if kind in kinds:
                raise Daily6mV2PipelineError("a verdict kind may be recorded only once")
            kinds.add(kind)
        previous = row["content_hash"]
    return rows


def _append(root: Path, relative: Path, payload: dict[str, Any]) -> dict[str, Any]:
    identity = LEDGER_IDENTITY[relative]
    rows = read_chain(root, relative)
    for row in rows:
        if row.get(identity) == payload.get(identity):
            if any(row.get(key) != value for key, value in payload.items()):
                raise Daily6mV2PipelineError("append-only identity collision")
            return row
    body = {**payload, "previous_hash": rows[-1]["content_hash"] if rows else None}
    row = {**body, "content_hash": canonical_hash(body)}
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    read_chain(root, relative)
    return row


def active_rows(rows: list[dict[str, Any]], identity: str = "resolution_id") -> list[dict[str, Any]]:
    superseded = {row["supersedes"] for row in rows if row.get("supersedes")}
    return [row for row in rows if row[identity] not in superseded]


def hold(reasons: list[str], *, as_of: str | None, status: str = "hold") -> dict[str, Any]:
    return {"schema_version": 1, "model_id": MODEL_ID, "status": status, "numbers_visible": False, "as_of": as_of,
            "reasons": list(dict.fromkeys(reasons)), "probability_unit": "fraction", "footnote": FOOTNOTE}


# ---------------------------------------------------------------- run validation
def validate_run(run: dict[str, Any]) -> None:
    if (run.get("model_id") != MODEL_ID or run.get("model_version") != MODEL_VERSION or run.get("status") != "shadow_research"
            or run.get("numbers_visible") is not False or run.get("probability_unit") != "fraction"
            or run.get("probability_space") != PROBABILITY_SPACE):
        raise Daily6mV2PipelineError("v2 run identity, unit or visibility mismatch")
    dates = run.get("dates") or []
    horizon = len(dates)
    if not dates or dates != sorted(set(dates)) or dates[0] <= run.get("origin_session", "") or run.get("horizon_sessions") != horizon:
        raise Daily6mV2PipelineError("v2 run dates must be ordered future sessions")
    if run.get("pair_status") not in ("identical_inputs", "inputs_differ"):
        raise Daily6mV2PipelineError("v2 pair status missing")
    if list(run.get("quantile_levels") or []) != list(K.GRID_LEVELS) or sorted(run.get("arms", {})) != sorted(ARMS):
        raise Daily6mV2PipelineError("v2 run grid levels or arm set mismatch")
    anchor = float(run["anchor"]["value"])
    if not math.isfinite(anchor) or anchor <= 0:
        raise Daily6mV2PipelineError("v2 anchor must be positive and finite")

    def check_grid(grid, records, label):
        values = np.asarray(grid, dtype=float)
        if values.shape != (39, horizon) or not np.isfinite(values).all() or np.any(np.diff(values, axis=0) < 0):
            raise Daily6mV2PipelineError(label + " quantile grid shape, finiteness or monotonicity invalid")
        bands = np.array([[math.log(float(record["band_index"][name]) / anchor) for record in records] for name in K.BAND_NAMES])
        if np.max(np.abs(values[list(K.BAND_ROWS)] - bands)) > 1e-9:
            raise Daily6mV2PipelineError(label + " quantile grid disagrees with its band_index")
        return values

    grids = {}
    for arm in ARMS:
        block = run["arms"][arm]
        records = block.get("records") or []
        if [record["date"] for record in records] != dates:
            raise Daily6mV2PipelineError("v2 arm records must cover every date")
        for record in records:
            bands = [float(record["band_index"][name]) for name in K.BAND_NAMES]
            if not all(math.isfinite(value) and value > 0 for value in bands) or bands != sorted(bands):
                raise Daily6mV2PipelineError("v2 band crossing or invalid level")
            for key in ("probability_up_from_previous", "probability_up_from_origin"):
                value = record[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise Daily6mV2PipelineError("v2 probability outside explicit fraction bounds")
        grids[arm] = check_grid(block["quantile_grid"], records, arm)
    if not np.array_equal(grids["main"][:, 0], grids["term_structure"][:, 0]) \
            or run["arms"]["main"]["records"][0] != run["arms"]["term_structure"]["records"][0]:
        raise Daily6mV2PipelineError("term_structure lead 1 must be bit identical to main (g[0] = 1)")
    reference = run.get("v1_reference") or {}
    v1_records = reference.get("records") or []
    if [record["date"] for record in v1_records] != dates:
        raise Daily6mV2PipelineError("v1 reference records must cover every date")
    eligibility = run.get("pair_eligibility")
    if eligibility is None:   # r2 run (prior identity): a v1 grid exactly when identical_inputs
        stores_grid = run["pair_status"] == "identical_inputs"
    else:                     # r3 run: the recorded block must replay from the run's own recorded fields
        if eligibility.get("rule") != PAIR_RULE_REVISION or eligibility != classify_pair(run):
            raise Daily6mV2PipelineError("v2 pair eligibility does not replay from the run's recorded fields")
        stores_grid = eligibility["status"] in PRIMARY_ELIGIBILITY
    if stores_grid:
        if reference.get("quantile_grid") is None:
            raise Daily6mV2PipelineError("primary-eligible run must store the reconstructed v1 grid")
        check_grid(reference["quantile_grid"], v1_records, "v1 reference")
    elif reference.get("quantile_grid") is not None:
        raise Daily6mV2PipelineError("inputs_differ run must not store a v1 grid unless tolerance_equivalent")
    expected = run.get("content_hash")
    if expected != canonical_hash({key: value for key, value in run.items() if key != "content_hash"}):
        raise Daily6mV2PipelineError("v2 run content hash mismatch")


def load_run(root: Path, row: dict[str, Any], *, contract_hash: str | None = None, code_hash: str | None = None) -> dict[str, Any]:
    path = (root / str(row["run_path"])).resolve()
    if not path.is_relative_to((root / RUNS_RELATIVE).resolve()):
        raise Daily6mV2PipelineError("v2 run path outside the shadow store")
    run = _json(path)
    validate_run(run)
    if run["content_hash"] != row.get("run_content_hash") or run["run_id"] != row.get("forecast_id"):
        raise Daily6mV2PipelineError("v2 ledger/run identity mismatch")
    contract_hash = frozen_hash(load_contract(root)) if contract_hash is None else contract_hash
    code_hash = model_code_hash(root) if code_hash is None else code_hash
    # gate = contract + numerical code only (contracts.NUMERICAL_CODE_PATHS); orchestration edits are diagnostics.
    # r3: runs issued under the pinned r2 identity stay loadable and are told apart by the absent pair_eligibility.
    if run_identity(run, contract_hash=contract_hash, code_hash=code_hash) is None:
        raise Daily6mV2PipelineError("v2 contract or numerical code identity changed")
    if row.get("pair_eligibility") != (run.get("pair_eligibility") or {}).get("status"):
        raise Daily6mV2PipelineError("v2 ledger row disagrees with its run (pair_eligibility)")
    if (run.get("paired_v1_forecast_id") != row.get("paired_v1_forecast_id")
            or run["parent"]["v1_run_content_hash"] != row.get("paired_v1_run_content_hash")
            or run.get("pair_status") != row.get("pair_status") or run["selection"]["chosen"] != row.get("selection_chosen")
            or run.get("horizon_sessions") != row.get("horizon_sessions") or run.get("origin_session") != row.get("origin_session")):
        raise Daily6mV2PipelineError("v2 ledger row disagrees with its run")
    return run


def run_identity(run: dict[str, Any], *, contract_hash: str, code_hash: str) -> str | None:
    """'current' (r3, must record pair_eligibility), a prior revision id (must not), or None (refused)."""
    identity = (run.get("contract_hash"), run.get("model_code_hash"))
    if identity == (contract_hash, code_hash):
        return "current" if run.get("pair_eligibility") is not None else None
    for prior in PRIOR_IDENTITIES:
        if identity == (prior["contract_hash"], prior["model_code_hash"]):
            return prior["revision"] if run.get("pair_eligibility") is None else None
    return None


# ---------------------------------------------------------------- issuance
@serialized_writer
def forecast_daily6m_v2(root: Path, *, as_of: str | datetime | None = None, path_count: int | None = None,
                        save_paths: bool = True) -> dict[str, Any]:
    from .model import generate_v2_forecast, session_close
    now = _now()
    cutoff = now if as_of is None else F.aware_time(as_of)
    stamp = cutoff.isoformat()
    if cutoff > now + FUTURE_AS_OF_TOLERANCE:
        raise Daily6mV2PipelineError("v2 issuance time cannot be in the future")
    contract = load_contract(root)
    constants = load_constants(root, contract)
    v1_active = P._active(P.read_chain(root, v1C.FORECAST_LEDGER))
    if not v1_active:
        return hold(["no active v1 forecast to pair"], as_of=stamp)
    v1_row = v1_active[-1]
    v2_rows = read_chain(root, FORECAST_LEDGER)
    for row in v2_rows:
        if row["paired_v1_forecast_id"] == v1_row["forecast_id"]:
            return {"status": "skipped", "skipped": "v2 pair already exists for the latest v1 run", "run_id": row["forecast_id"],
                    "paired_v1_forecast_id": v1_row["forecast_id"], "pair_status": row["pair_status"],
                    "origin_session": row["origin_session"], "reasons": []}
    v1_run = P.load_run(root, v1_row)
    close = session_close(v1_run["dates"][0])
    if cutoff >= close:
        return {**hold(["pair_window_closed"], as_of=stamp), "paired_v1_forecast_id": v1_row["forecast_id"],
                "origin_session": v1_run["anchor_date"]}
    try:
        frame = F.read_native_frame(root, as_of=cutoff)
        bundle = F.build_bundle(root, as_of=cutoff, rows=frame)
    except (F.Daily6mFeatureError, OSError, ValueError, RuntimeError) as exc:
        return hold([str(exc)], as_of=stamp)
    if bundle.issues:
        return hold(list(bundle.issues), as_of=stamp)
    if bundle.anchor["date"] != v1_run["anchor_date"]:
        return hold(["v2 bundle anchor differs from the paired v1 origin"], as_of=stamp)
    previous = v2_rows[-1]["selection_chosen"] if v2_rows else None
    payload, paths = generate_v2_forecast(bundle, anchor=float(bundle.anchor["value"]), as_of=stamp, future_dates=v1_run["dates"],
                                          v1_run=v1_run, previous_selection=previous, constants=constants,
                                          path_count=path_count, root=root)
    payload.pop("content_hash", None)
    contract_hash, code_hash = frozen_hash(contract), model_code_hash(root)
    seed = {"model_id": MODEL_ID, "issued_at": payload["issued_at"], "origin": payload["origin_session"],
            "contract_hash": contract_hash, "model_code_hash": code_hash, "paired_v1_forecast_id": v1_row["forecast_id"],
            "arm_path_hashes": {arm: payload["arms"][arm]["path_hash"] for arm in ARMS}}
    run_id = "daily6m-v2-" + canonical_hash(seed)[:24]
    lineage = bundle.lineage or {}
    body = {**payload, "run_id": run_id, "contract_hash": contract_hash, "model_code_hash": code_hash,
            "design_constants_hash": contract["design_constants"]["canonical_hash"],
            # non-gating diagnostic (review B2): orchestration code that issued this run
            "orchestration_code_hashes": orchestration_code_hashes(),
            "paired_v1_forecast_id": v1_row["forecast_id"],
            "lineage_digest": {"market_rows_hash": canonical_hash(lineage.get("market_rows", [])),
                               "factor_rows_hash": canonical_hash(lineage.get("factor_rows", []))},
            "source_freshness": json.loads(json.dumps(list(bundle.freshness), default=str))}
    if save_paths:
        relative = OUTPUTS_RELATIVE / "paths" / f"{run_id}.npz"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            with temporary.open("wb") as handle:
                np.savez_compressed(handle, **{arm: np.asarray(paths[arm], dtype=np.float64) for arm in ARMS})
            os.replace(temporary, target)
        body["path_artifact"] = {"path": relative.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                                 "optional_local_artifact": True}
    run = {**body, "content_hash": canonical_hash(body)}
    validate_run(run)
    boundary = _now()
    if boundary >= close or F.last_completed_session(boundary) != payload["origin_session"]:
        return hold(["write-time pair window or origin gate failed"], as_of=stamp)
    run_path = RUNS_RELATIVE / f"{run_id}.json"
    _immutable(root / run_path, run)
    _append(root, FORECAST_LEDGER, {
        "forecast_id": run_id, "issued_at": payload["issued_at"], "origin_session": payload["origin_session"],
        "paired_v1_forecast_id": v1_row["forecast_id"], "paired_v1_run_content_hash": v1_run["content_hash"],
        "pair_status": payload["pair_status"], "run_path": run_path.as_posix(), "run_content_hash": run["content_hash"],
        "selection_chosen": payload["selection"]["chosen"], "horizon_sessions": payload["horizon_sessions"],
        "pair_eligibility": payload["pair_eligibility"]["status"],
        "supersedes": None, "probability_unit": "fraction"})
    return {"status": "issued", "run_id": run_id, "paired_v1_forecast_id": v1_row["forecast_id"],
            "pair_status": payload["pair_status"], "pair_eligibility": payload["pair_eligibility"]["status"],
            "origin_session": payload["origin_session"], "skipped": None, "reasons": []}


# ---------------------------------------------------------------- scoring
def resolution_id(run_id: str, arm: str, day: str, *, v1_resolution_id: str, supersedes: str | None) -> str:
    initial = f"{run_id}:{arm}:{day}"
    if supersedes is None:
        return initial
    return initial + ":" + canonical_hash({"v1_resolution_id": v1_resolution_id, "supersedes": supersedes})[:24]


def score_row(run: dict[str, Any], arm: str, v1_row: dict[str, Any], *, supersedes: str | None, resolved_as_of: str) -> dict[str, Any]:
    day = v1_row["date"]
    if v1_row.get("forecast_id") != run["paired_v1_forecast_id"] or day not in run["dates"]:
        raise Daily6mV2PipelineError("v1 resolution does not belong to the paired v1 run")
    index = run["dates"].index(day)
    anchor = float(run["anchor"]["value"])
    actual, previous = float(v1_row["actual_index"]), float(v1_row["actual_previous_index"])
    if not (math.isfinite(actual) and math.isfinite(previous) and actual > 0 and previous > 0):
        raise Daily6mV2PipelineError("v1 resolution closes must be finite and positive")
    outcome = actual > previous
    if v1_row.get("outcome_up") is not outcome:
        raise Daily6mV2PipelineError("v1 resolution outcome disagrees with its closes")
    y = math.log(actual / anchor)
    record = run["arms"][arm]["records"][index]
    grid = run["arms"][arm]["quantile_grid"]
    v1_record = run["v1_reference"]["records"][index]
    p, v1_p = float(record["probability_up_from_previous"]), float(v1_record["probability_up_from_previous"])
    v1_hit = v1_record["band_index"]["p10"] <= actual <= v1_record["band_index"]["p90"]
    v1_brier = (v1_p - int(outcome)) ** 2
    if (v1_hit != v1_row.get("inside_p10_p90") or not math.isclose(v1_brier, float(v1_row["brier"]), rel_tol=0, abs_tol=1e-12)
            or not math.isclose(v1_p, float(v1_row["probability_up_from_previous"]), rel_tol=0, abs_tol=1e-12)):
        raise Daily6mV2PipelineError("v1 reference disagrees with the v1 resolution (band or Brier)")
    v1_grid = run["v1_reference"].get("quantile_grid")
    payload = {
        "schema_version": 1, "v2_run_id": run["run_id"], "arm": arm, "date": day, "lead": index + 1,
        "origin_session": run["origin_session"], "pair_status": run["pair_status"],
        "v1_forecast_id": v1_row["forecast_id"], "v1_resolution_id": v1_row["resolution_id"],
        "v1_source_revision_hash": v1_row.get("source_revision_hash"),
        "actual_index": actual, "actual_previous_index": previous, "outcome_up": outcome,
        "crps39": K.crps_grid39(y, [column[index] for column in grid]),
        "qs5": K.qs5(y, record["band_index"], anchor),
        "hit80": record["band_index"]["p10"] <= actual <= record["band_index"]["p90"],
        "p_up_prev": p, "brier": (p - int(outcome)) ** 2,
        "v1_crps39": None if v1_grid is None else K.crps_grid39(y, [column[index] for column in v1_grid]),
        "v1_qs5": K.qs5(y, v1_record["band_index"], anchor), "v1_hit80": v1_hit, "v1_brier": v1_brier,
        "resolved_as_of": resolved_as_of, "supersedes": supersedes,
        "resolution_kind": "initial" if supersedes is None else "correction",
        "revision_reason": None if supersedes is None else "v1 resolution corrected (native close revision); prior v2 row preserved",
        "probability_unit": "fraction",
    }
    if run.get("pair_eligibility") is not None:   # r3 runs only - rows of r2 runs keep their recorded shape
        payload["pair_eligibility"] = run["pair_eligibility"]["status"]
    payload["resolution_id"] = resolution_id(run["run_id"], arm, day, v1_resolution_id=v1_row["resolution_id"], supersedes=supersedes)
    return payload


def _load_forecasts(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = read_chain(root, FORECAST_LEDGER)
    contract_hash, code_hash = frozen_hash(load_contract(root)), model_code_hash(root)
    runs = {row["forecast_id"]: load_run(root, row, contract_hash=contract_hash, code_hash=code_hash) for row in rows}
    return rows, runs


@serialized_writer
def resolve_daily6m_v2(root: Path, *, as_of: str | datetime | None = None) -> dict[str, Any]:
    now = _now()
    cutoff = now if as_of is None else F.aware_time(as_of)
    if cutoff > now + FUTURE_AS_OF_TOLERANCE:
        raise Daily6mV2PipelineError("v2 resolution time cannot be in the future")
    load_constants(root)
    v1_rows = P.read_chain(root, v1C.RESOLUTION_LEDGER)
    forecasts, runs = _load_forecasts(root)
    by_pair = {run["paired_v1_forecast_id"]: run for run in runs.values()}
    existing = read_chain(root, RESOLUTION_LEDGER)
    active = {(row["v2_run_id"], row["arm"], row["date"]): row for row in active_rows(existing)}
    appended = corrected = 0
    for v1_row in active_rows(v1_rows):
        run = by_pair.get(v1_row["forecast_id"])
        if run is None:
            continue
        for arm in ARMS:
            key = (run["run_id"], arm, v1_row["date"])
            prior = active.get(key)
            if prior is not None and prior["v1_resolution_id"] == v1_row["resolution_id"]:
                continue
            if prior is not None and cutoff < F.aware_time(prior["resolved_as_of"]):
                raise Daily6mV2PipelineError("v2 correction cannot precede the active v2 resolution time")
            if cutoff < F.aware_time(v1_row["resolved_as_of"]):
                raise Daily6mV2PipelineError("v2 resolution time cannot precede the v1 resolution it scores")
            payload = score_row(run, arm, v1_row, supersedes=None if prior is None else prior["resolution_id"],
                                resolved_as_of=cutoff.isoformat())
            active[key] = _append(root, RESOLUTION_LEDGER, payload)
            appended += 1
            corrected += int(prior is not None)
    return {"status": "ok", "resolved": appended, "corrected": corrected, "total_resolutions": len(existing) + appended,
            "runs": len(forecasts), "probability_unit": "fraction", "predictive_validation": "not_established"}


# ---------------------------------------------------------------- verification
def _check_v1_reference(run: dict[str, Any], v1_run: dict[str, Any]) -> None:
    """The v1 copy inside the v2 run must equal the paired v1 run file (review N6, spec §3.5)."""
    reference = run["v1_reference"]["records"]
    source = v1_run.get("records") or []
    if [record["date"] for record in reference] != [record["date"] for record in source]:
        raise Daily6mV2PipelineError("v1 reference records disagree with the paired v1 run (dates)")
    for mine, theirs in zip(reference, source):
        values = [(float(mine["band_index"][name]), float(theirs["band_index"][name])) for name in K.BAND_NAMES]
        values.append((float(mine["probability_up_from_previous"]), float(theirs["probability_up_from_previous"])))
        if any(not abs(a - b) <= V1_REFERENCE_TOLERANCE for a, b in values):
            raise Daily6mV2PipelineError("v1 reference records disagree with the paired v1 run (band or probability)")


def verify_daily6m_v2(root: Path) -> dict[str, Any]:
    from . import scorecard as S
    try:
        contract = load_contract(root)
        load_constants(root, contract)
        forecasts, runs = _load_forecasts(root)
        current_orchestration = orchestration_code_hashes()
        orchestration_changed = 0
        previous = None
        v1_forecasts = {row["forecast_id"]: row for row in P.read_chain(root, v1C.FORECAST_LEDGER)}
        contract_hash, code_hash = frozen_hash(contract), model_code_hash(root)
        seen_current = False
        eligibility_counts = {"identical_inputs": 0, "tolerance_equivalent": 0, "excluded": 0}
        prior_runs = []
        for row in forecasts:
            run = runs[row["forecast_id"]]
            identity = run_identity(run, contract_hash=contract_hash, code_hash=code_hash)
            if identity == "current":
                seen_current = True
                eligibility_counts[run["pair_eligibility"]["status"]] += 1
            else:
                if seen_current:
                    raise Daily6mV2PipelineError("prior-identity v2 run issued after an r3 run")
                # recorded fields only: an r2 inputs_differ run never stored a v1 grid, so r3 cannot admit it
                view = classify_pair(run)
                legacy = "identical_inputs" if run["pair_status"] == "identical_inputs" else "excluded"
                if view["status"] != legacy:
                    raise Daily6mV2PipelineError("prior-identity run would change class under r3: " + run["run_id"])
                eligibility_counts[legacy] += 1
                prior_runs.append({"run_id": run["run_id"], "identity": identity, "status": legacy, "failed": view["failed"]})
            if run["selection"]["previous"] != previous:
                raise Daily6mV2PipelineError("selection state chain broken (previous != prior run chosen)")
            previous = run["selection"]["chosen"]
            v1_row = v1_forecasts.get(row["paired_v1_forecast_id"])
            if v1_row is None or v1_row["run_content_hash"] != row["paired_v1_run_content_hash"]:
                raise Daily6mV2PipelineError("paired v1 forecast missing or its run hash changed")
            _check_v1_reference(run, P.load_run(root, v1_row))
            if run.get("orchestration_code_hashes") != current_orchestration:
                orchestration_changed += 1
            artifact = run.get("path_artifact")
            if artifact:
                path = (root / artifact["path"]).resolve()
                if not path.is_relative_to((root / OUTPUTS_RELATIVE / "paths").resolve()):
                    raise Daily6mV2PipelineError("v2 path artifact containment mismatch")
                if path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                        raise Daily6mV2PipelineError("v2 path artifact hash mismatch")
                    with np.load(path, allow_pickle=False) as arrays:
                        for arm in ARMS:
                            values = arrays[arm]
                            digest = hashlib.sha256(np.ascontiguousarray(values, dtype=np.float64).tobytes()).hexdigest()
                            if digest != run["arms"][arm]["path_hash"]:
                                raise Daily6mV2PipelineError("v2 path artifact numerical content mismatch")
                            if K.quantile_grid(values, anchor=run["anchor"]["value"]).tolist() != run["arms"][arm]["quantile_grid"]:
                                raise Daily6mV2PipelineError("v2 path artifact grid mismatch")
        v1_resolutions = {row["resolution_id"]: row for row in P.read_chain(root, v1C.RESOLUTION_LEDGER)}
        resolutions = read_chain(root, RESOLUTION_LEDGER)
        # h1 identity first so its own message is reachable (validate_run already pins grid column 0 and
        # record 0; this catches a re-chained ledger row that breaks the pair before the generic replay does)
        active = active_rows(resolutions)
        main_h1 = {(item["v2_run_id"], item["date"]): item for item in active if item["arm"] == "main" and item["lead"] == 1}
        for row in active:
            if row["arm"] == "term_structure" and row["lead"] == 1:
                twin = main_h1.get((row["v2_run_id"], row["date"]))
                if twin is None or twin["crps39"] != row["crps39"]:
                    raise Daily6mV2PipelineError("term_structure h1 identity check failed")
        for row in resolutions:
            run = runs.get(row["v2_run_id"])
            v1_row = v1_resolutions.get(row["v1_resolution_id"])
            if run is None or v1_row is None:
                raise Daily6mV2PipelineError("v2 resolution references a missing v2 run or v1 resolution")
            if F.aware_time(row["resolved_as_of"]) < F.aware_time(v1_row["resolved_as_of"]):
                raise Daily6mV2PipelineError("v2 resolution precedes its v1 resolution: " + row["resolution_id"])
            expected = score_row(run, row["arm"], v1_row, supersedes=row.get("supersedes"), resolved_as_of=row["resolved_as_of"])
            body = {key: value for key, value in row.items() if key not in ("previous_hash", "content_hash")}
            if body != expected:
                raise Daily6mV2PipelineError("v2 resolution replay mismatch: " + row["resolution_id"])
        verdicts = read_chain(root, VERDICT_LEDGER)
        current_scorecard = S.scorecard_code_hash()
        scorecard_changed = []
        for row in verdicts:
            recomputed = S.recompute_verdict(root, row, forecasts=forecasts, resolutions=resolutions, contract=contract)
            if recomputed != S.verdict_body_for_replay(row):
                raise Daily6mV2PipelineError("verdict replay mismatch: " + row["kind"])
            if row.get("scorecard_code_hash") != current_scorecard:
                scorecard_changed.append(row["kind"])
        warnings = S.stalled_scans(S.build_index(forecasts, resolutions)) if forecasts else []
        return {"ok": True, "errors": [], "warnings": warnings, "forecasts": len(forecasts), "resolutions": len(resolutions),
                "verdicts": len(verdicts), "v1_read_only": True, "predictive_validation": "not_established",
                # non-gating (review B2): numbers were re-derived above; these only disclose code drift since recording
                "diagnostics": {"runs_with_changed_orchestration_code": orchestration_changed,
                                "verdicts_recorded_by_other_scorecard_code": scorecard_changed,
                                # r3: primary-sample admission per run; prior-identity runs are classified, never rewritten
                                "pair_eligibility_counts": eligibility_counts, "prior_identity_runs": prior_runs}}
    except (OSError, EOFError, ValueError, KeyError, TypeError, IndexError, Daily6mV2PipelineError,
            Daily6mV2ContractError, P.Daily6mPipelineError, v1C.Daily6mContractError) as exc:
        return {"ok": False, "errors": [str(exc)]}
