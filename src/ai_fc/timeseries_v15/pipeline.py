"""V15 오케스트레이션 — 계산 단계화·수집·identity·해소·상태·무결성·health·판정 (kernel 밖).

- forecast: 팔 1개를 V8 원점·V8 knowledge_cutoff·그 시각 main 스냅숏(data_root)에서 계산해 staging
  JSON 으로만 쓴다(원장 체인 필드 없음).
- collect: A0 를 V8 행과 대조(≤1e-12)하고 A0..A4 순으로 해시체인 원장에 append. identity FAIL 원점도
  행은 커밋된다(전 팔 excluded a0_identity_fail). 같은 forecast_id 가 있으면 비교 없이 건너뛴다.
- verify: 무결성만(체인·kernel·fork patch·rule hash·verdict hash·prereg 핀). identity 는 보지 않는다.
- health: 커밋 뒤 — 최근 3개 V8 원점의 A0 가 모두 identity FAIL 이고 미-ack 이면 exit 1(ops 경보).
판정·승격·화면 연결은 여기서 자동으로 하지 않는다. 모든 출력은 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ai_fc.timeseries_v8.contracts import canonical_hash
from ai_fc.timeseries_v8.pipeline import _chain_append, _read_chain, verify_chain

from .arms import ARMS, SEED_MODEL_ID, SEED_MODEL_VERSION, WEEKLY_ARMS, arm_spec
from .contracts import (
    APPROVAL_TEXT,
    APPROVALS_LEDGER,
    ATTEMPTS_LEDGER,
    DECISIONS,
    FORKED,
    FORK_PATCH_RELATIVE,
    ISSUANCE_LEDGER,
    MDE_SUMMARY_RELATIVE,
    MODEL_ID,
    MODEL_VERSION,
    NOTICE,
    PREREG_RELATIVE,
    RESOLUTION_LEDGER,
    SHADOW_LEDGER,
    STATUS_RELATIVE,
    V8_SHADOW_LEDGER,
    VERDICTS_LEDGER,
    TimeSeriesV15ContractError,
    assert_track_open,
    frozen_hash,
    kernel_code_hash,
    load_contract_v15,
    pipeline_code_hash,
    read_contract_raw,
    rule_hash,
    verdict_code_hash,
)

IDENTITY_TOLERANCE = 1e-12  # 계약 arms.A0.identity_tolerance(rule 잠금)와 같아야 한다 — verify 가 대조
HORIZON_KEYS = ("1", "5", "21", "63")
A5_DEADLINE_MARGIN_SECONDS = 300
SNAPSHOT_METHOD = "rev_list_first_parent_before_cutoff"
IDENTITY_FILE = re.compile(r"a0_live_identity_(\d{4}-\d{2}-\d{2})_a(\d+)\.json$")
IDENTITY_STREAK = 3
ATTEMPT_KINDS = frozenset({
    "compute_failed", "a0_missing", "a0_identity_fail", "a5_deadline_missed", "a5_origin_unavailable",
    "gap_outside_catchup", "kernel_hash_drift", "identity_streak_ack",
})


class TimeSeriesV15PipelineError(RuntimeError):
    """V15 운영 단계 fail-closed."""


# ── 공용 ────────────────────────────────────────────────────────────────────


def _utc(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise TimeSeriesV15PipelineError("now 는 timezone-aware 여야 한다")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise TimeSeriesV15PipelineError(f"시간대 없는 시각: {value!r}")
    return stamp.astimezone(timezone.utc)


def iso_week(day: str) -> str:
    iso = date.fromisoformat(str(day)[:10]).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def read_ledger(root: Path, relative: Path) -> list[dict[str, Any]]:
    return _read_chain(root, relative)


def read_v8_rows(root: Path) -> list[dict[str, Any]]:
    return sorted(_read_chain(root, V8_SHADOW_LEDGER), key=lambda row: (row["origin"], row["forecast_id"]))


def v8_row(root: Path, forecast_id: str) -> dict[str, Any]:
    for row in _read_chain(root, V8_SHADOW_LEDGER):
        if row.get("forecast_id") == forecast_id:
            return row
    raise TimeSeriesV15PipelineError(f"V8 섀도 행이 없다: {forecast_id}")


def _write_json(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _attempt_rows(root: Path) -> list[dict[str, Any]]:
    return _read_chain(root, ATTEMPTS_LEDGER)


def record_attempt(
    root: Path, *, origin: str | None, arm: str | None, kind: str, detail: str,
    now: datetime | None = None, dedupe: bool = False,
) -> dict[str, Any] | None:
    if kind not in ATTEMPT_KINDS:
        raise TimeSeriesV15PipelineError(f"등록되지 않은 attempts kind: {kind}")
    if dedupe and any(row.get("origin") == origin and row.get("arm") == arm and row.get("kind") == kind
                      for row in _attempt_rows(root)):
        return None
    recorded = _stamp(_utc(now))
    body = {"schema_version": 1, "origin": origin, "arm": arm, "kind": kind,
            "detail": str(detail), "recorded_at": recorded, "notice": NOTICE}
    body["attempt_id"] = "tsv15-attempt-" + canonical_hash(body)[:24]
    return _chain_append(root, ATTEMPTS_LEDGER, body, key="attempt_id")


def _v8_setup(root: Path) -> dict[str, Any]:
    from ai_fc.timeseries_v8.contracts import load_contract_v8
    from ai_fc.timeseries_v8.pipeline import build_config_from_grids

    contract_v8 = load_contract_v8(root)
    config = build_config_from_grids(
        contract_v8, json.loads(json.dumps(contract_v8["frozen_winner"]["config_overrides"])),
    )
    return {
        "config": config,
        "outer_start": str(contract_v8["evaluation"]["outer_start"]),
        "path_count": int(contract_v8["model"]["distribution"]["sealed_path_count"]),
        "pit_min_matured": int(contract_v8["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]),
    }


def _runtime() -> dict[str, Any]:
    from ai_fc.timeseries_v2.contracts import runtime_manifest

    from .calendar import exchange_calendars_version

    return {"runtime_manifest": runtime_manifest(), "exchange_calendars_version": exchange_calendars_version()}


def _provenance_summary(provenance: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in provenance.items():
        if isinstance(value, list):
            summary[key] = {"count": len(value), "tail": value[-10:]}
        elif isinstance(value, dict) and key == "carried_sessions":
            items = sorted(value.items())
            summary[key] = {"count": len(items), "tail": dict(items[-10:])}
        else:
            summary[key] = value
    return summary


# ── 계산 (staging) ───────────────────────────────────────────────────────────


def compute_arm(
    root: Path, *, data_root: Path, arm: str, knowledge_cutoff: str, origin: str | None = None,
    path_count: int | None = None,
) -> dict[str, Any]:
    """팔 1개를 knowledge_cutoff 의 data_root 번들에서 전체 walk-forward 로 계산한다."""
    from ai_fc.timeseries_v2.contracts import require_dfm_runtime

    from .backtest import walk_forward_v15
    from .bundle import bundle_at, truncate_bundle

    spec = arm_spec(arm)
    require_dfm_runtime()
    setup = _v8_setup(root)
    bundle, provenance = bundle_at(data_root, knowledge_cutoff=knowledge_cutoff, frame_mode=spec.frame_mode)
    if origin is not None:
        bundle = truncate_bundle(bundle, last_date=origin)
        if not bundle.dates or bundle.dates[-1] != origin:
            raise TimeSeriesV15PipelineError(
                f"{arm} 번들 마지막 세션 {bundle.dates[-1] if bundle.dates else None} != V8 원점 {origin}"
            )
    scores, summary = walk_forward_v15(
        dates=bundle.dates, endog=bundle.endogenous, exog=bundle.exogenous,
        endog_names=bundle.endogenous_names, exog_names=bundle.exogenous_names,
        model_id=SEED_MODEL_ID, model_version=SEED_MODEL_VERSION, config=setup["config"],
        outer_start=setup["outer_start"], outer_end=bundle.dates[-1],
        path_count=int(path_count or setup["path_count"]), pit_min_matured=setup["pit_min_matured"],
        collect_cramer_audit=False, emit_forecast=True, arm=spec,
    )
    forecast = summary["shadow_forecast"]
    tail_structural: list[str] = []
    if spec.issuance_mode == "next_open_asof":
        week = iso_week(bundle.dates[-1])
        tail_structural = [day for day in bundle.dates if iso_week(day) == week]
    return {
        "forecast": forecast, "config": setup["config"].as_manifest(),
        "matured_origins_at_emit": len({row.date for row in scores}),
        "provenance": provenance, "dates_tail": list(bundle.dates[-10:]),
        "tail_rows_structural": tail_structural,
    }


def _post_dated(origin: str, issued_at: datetime) -> dict[str, bool]:
    """post_dated_k = 1[issued_at > XNAS close(s_k)] — 조기폐장일은 실제 close."""
    from .calendar import session_table

    start = date.fromisoformat(origin)
    table = session_table(start, start + timedelta(days=150))
    if not table or table[0].session != start.isoformat():
        raise TimeSeriesV15PipelineError(f"원점이 XNAS 세션이 아니다: {origin}")
    return {key: bool(issued_at > table[int(key)].close_utc) for key in HORIZON_KEYS}


def stage_arm_forecast(
    root: Path, *, arm: str, stage_out: Path, v8_forecast_id: str | None = None,
    data_root: Path | None = None, snapshot_sha: str | None = None, issue_now: bool = False,
    v8_run_head_sha: str | None = None, now: datetime | None = None, path_count: int | None = None,
) -> dict[str, Any]:
    from .calendar import calendar_hash, last_completed_session, open_utc, session_offset

    contract = load_contract_v15(root)
    assert_track_open(contract)
    spec = arm_spec(arm)
    current = _utc(now)
    if spec.issuance_mode == "next_open_asof":
        if not issue_now:
            raise TimeSeriesV15PipelineError("A5 는 --issue-now 로만 계산한다(발행 시각 = knowledge_cutoff)")
        cutoff = _stamp(current)
        source = root
        v8_id = None
        origin = None
    else:
        if issue_now or not v8_forecast_id or data_root is None or not snapshot_sha:
            raise TimeSeriesV15PipelineError("A0~A4 는 --v8-forecast-id·--data-root·--snapshot-sha 가 필요하다")
        reference = v8_row(root, v8_forecast_id)
        cutoff = str(reference["knowledge_cutoff"])
        source = Path(data_root)
        v8_id = v8_forecast_id
        origin = str(reference["origin"])
    computed = compute_arm(root, data_root=source, arm=arm, knowledge_cutoff=cutoff, origin=origin,
                           path_count=path_count)
    forecast = computed["forecast"]
    origin = str(forecast["origin"])
    payload: dict[str, Any] = {
        "schema_version": 1, "kind": "v15_staged_forecast",
        "model_id": MODEL_ID, "model_version": MODEL_VERSION, "arm": arm, "arm_spec": spec.as_manifest(),
        "origin": origin, "iso_week": iso_week(origin), "knowledge_cutoff": cutoff,
        "data_snapshot_sha": snapshot_sha or "main_at_issue", "v8_forecast_id": v8_id,
        "contract_hash": frozen_hash(contract), "kernel_code_hash": kernel_code_hash(root),
        "pipeline_code_hash": pipeline_code_hash(root),
        "seed": int(forecast["seed"]),
        "seed_identity": {"model_id": SEED_MODEL_ID, "model_version": SEED_MODEL_VERSION},
        "config": computed["config"], "grid_levels_count": forecast["grid_levels_count"],
        "ensemble_weights": forecast["ensemble_weights"], "block_length": forecast["block_length"],
        "ewma_lambda": forecast["ewma_lambda"], "ewma_lambda_selected": forecast["ewma_lambda"],
        "vol_mode_note": {"lambda_mix": "mix_0.94_0.97", "fresh": "fresh", "v8": "v8"}[spec.vol_mode],
        "horizons": forecast["horizons"], "matured_origins_at_emit": computed["matured_origins_at_emit"],
        "frame_provenance": _provenance_summary(computed["provenance"]),
        "calendar_hash": calendar_hash(origin), **_runtime(),
        "snapshot_method": SNAPSHOT_METHOD if spec.issuance_mode != "next_open_asof" else "main_at_issue",
        "v8_run_head_sha": v8_run_head_sha or None,
        "probability_unit": "fraction", "official_status": "shadow_research_not_official", "notice": NOTICE,
    }
    if spec.issuance_mode == "next_open_asof":
        next_session = session_offset(date.fromisoformat(origin), 1)
        deadline = open_utc(next_session) - timedelta(seconds=A5_DEADLINE_MARGIN_SECONDS)
        provenance = computed["provenance"]
        payload["issuance"] = {
            "next_session": next_session.isoformat(), "deadline_utc": _stamp(deadline),
            "expected_origin": last_completed_session(current).isoformat(),
            "tail_rows_structural": computed["tail_rows_structural"],
            "tail_rows_asof": list(provenance.get("dollar_tail_asof") or []),
            "dollar_last_obs_asof": provenance.get("dollar_last_obs_asof"),
        }
    payload["content_hash"] = canonical_hash(payload)
    _write_json(Path(stage_out), payload)
    return {"arm": arm, "origin": origin, "stage_out": str(stage_out), "content_hash": payload["content_hash"]}


# ── identity ─────────────────────────────────────────────────────────────────


def contract_identity_tolerance(contract: Mapping[str, Any]) -> float:
    """계약 arms.A0.identity_tolerance (rule_hash 대상) — 코드 상수가 아니라 잠긴 값을 쓴다."""
    value = float(((contract.get("arms") or {}).get("A0") or {}).get("identity_tolerance"))
    if not math.isfinite(value) or value <= 0:
        raise TimeSeriesV15PipelineError(f"arms.A0.identity_tolerance 가 양의 유한값이 아니다: {value!r}")
    return value


def identity_compare(
    forecast: Mapping[str, Any], reference: Mapping[str, Any], *, tolerance: float = IDENTITY_TOLERANCE,
) -> dict[str, Any]:
    """V15 A0 vs V8 행 — grid·baseline grid max|Δ| ≤ tolerance(계약 1e-12), block·λ 정확,
    앙상블 |Δ| ≤ tolerance, recalibrated·matured_pit_count 정확."""
    mismatched: list[str] = []
    worst = 0.0
    for key in HORIZON_KEYS:
        left = forecast["horizons"][key]
        right = reference["horizons"][key]
        for field in ("quantile_grid", "baseline_quantile_grid"):
            a = np.asarray(left[field], dtype=float)
            b = np.asarray(right[field], dtype=float)
            if a.shape != b.shape:
                mismatched.append(f"h{key}.{field}.shape")
                worst = math.inf
                continue
            diff = float(np.max(np.abs(a - b))) if a.size else 0.0
            worst = max(worst, diff)
            if not diff <= tolerance:
                mismatched.append(f"h{key}.{field}")
        for field in ("recalibrated", "matured_pit_count"):
            if left.get(field) != right.get(field):
                mismatched.append(f"h{key}.{field}")
    for field in ("block_length", "ewma_lambda"):
        if forecast.get(field) != reference.get(field):
            mismatched.append(field)
    for side in ("expanding", "rolling"):
        diff = abs(float(forecast["ensemble_weights"][side]) - float(reference["ensemble_weights"][side]))
        worst = max(worst, diff)
        if not diff <= tolerance:
            mismatched.append(f"ensemble_weights.{side}")
    if str(forecast.get("origin")) != str(reference.get("origin")):
        mismatched.append("origin")
    return {"status": "PASS" if not mismatched else "FAIL",
            "max_abs_diff": worst if math.isfinite(worst) else None,
            "mismatched_fields": mismatched, "tolerance": float(tolerance)}


def _staged(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    if payload.get("content_hash") != canonical_hash(body):
        raise TimeSeriesV15PipelineError(f"staging 무결성 실패: {path.name}")
    return payload


def forecast_id_for(payload: Mapping[str, Any]) -> str:
    seed = {"model_id": MODEL_ID, "arm": payload["arm"], "origin": payload["origin"],
            "v8_forecast_id": payload.get("v8_forecast_id"), "kernel_code_hash": payload["kernel_code_hash"]}
    return f"tsv15-{payload['arm']}-{canonical_hash(seed)[:24]}"


def _row_from_stage(payload: Mapping[str, Any], *, issued_at: datetime, excluded: list[str],
                    identity: Mapping[str, Any] | None) -> dict[str, Any]:
    row = {key: value for key, value in payload.items() if key not in ("content_hash", "kind")}
    row["forecast_id"] = forecast_id_for(payload)
    row["issued_at"] = _stamp(issued_at)
    row["post_dated"] = _post_dated(str(payload["origin"]), issued_at)
    row["excluded_reasons"] = sorted(set(excluded))
    if identity is not None:
        row["identity_vs_v8"] = dict(identity)
    return row


# ── 수집 ─────────────────────────────────────────────────────────────────────


def catch_up_targets(
    v8_rows: Sequence[Mapping[str, Any]], *, first_origin_not_before: str | None, latest_only: bool,
    window: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = [dict(row) for row in v8_rows
                if not first_origin_not_before or str(row["origin"]) >= str(first_origin_not_before)]
    eligible.sort(key=lambda row: row["origin"])
    size = 1 if latest_only else window
    return eligible[-size:], eligible[:-window] if len(eligible) > window else []


def _ledger_a0_row(root: Path, v8_forecast_id: str) -> dict[str, Any] | None:
    """원장에 이미 있는 그 V8 행의 A0 행(최초 행이 정본)."""
    for row in _read_chain(root, SHADOW_LEDGER):
        if row.get("arm") == "A0" and str(row.get("v8_forecast_id")) == str(v8_forecast_id):
            return row
    return None


def _existing_arms(root: Path) -> dict[str, set[str]]:
    present: dict[str, set[str]] = {}
    for row in _read_chain(root, SHADOW_LEDGER):
        present.setdefault(str(row.get("v8_forecast_id")), set()).add(str(row["arm"]))
    return present


def collect_staged(
    root: Path, *, staging: Path, expected_arms: Sequence[str], v8_forecast_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    contract = load_contract_v15(root)
    assert_track_open(contract)
    current = _utc(now)
    frozen_kernel = str(contract["fork"]["frozen_kernel_code_hash"])
    reference = v8_row(root, v8_forecast_id)
    origin = str(reference["origin"])
    existing_ids = {row["forecast_id"] for row in _read_chain(root, SHADOW_LEDGER)}
    staged: dict[str, dict[str, Any]] = {}
    attempts: list[str] = []
    for arm in expected_arms:
        if arm not in WEEKLY_ARMS:
            raise TimeSeriesV15PipelineError(f"주간 수집 대상이 아닌 팔: {arm}")
        payload = _staged(Path(staging) / f"{arm}.json")
        if payload is None:
            record_attempt(root, origin=origin, arm=arm, kind="compute_failed",
                           detail=f"staging/{arm}.json 없음 (v8 {v8_forecast_id})", now=current)
            attempts.append(f"{arm}:compute_failed")
            continue
        if payload.get("v8_forecast_id") != v8_forecast_id or payload.get("origin") != origin:
            raise TimeSeriesV15PipelineError(f"{arm} staging 이 다른 V8 행을 가리킨다")
        if payload.get("kernel_code_hash") != frozen_kernel:
            record_attempt(root, origin=origin, arm=arm, kind="kernel_hash_drift",
                           detail=f"staged {payload.get('kernel_code_hash')} != frozen {frozen_kernel}", now=current)
            attempts.append(f"{arm}:kernel_hash_drift")
            continue
        staged[arm] = payload
    common: list[str] = []
    identity = None
    a0_seed: int | None = None
    a0_source = "none"
    ledger_a0 = _ledger_a0_row(root, v8_forecast_id)
    if ledger_a0 is not None:
        # 원장의 A0 행이 정본 — 실패 팔만 재시도하는 run(staging 에 A0 없음)도, A0 를 다시 계산한 run 도
        # 그 행의 identity 판정·시드를 승계한다(재계산 부동소수 차로 판정이 갈리지 않게, attempts 중복 없음).
        common.extend(str(reason) for reason in (ledger_a0.get("excluded_reasons") or []))
        identity = ledger_a0.get("identity_vs_v8")
        a0_seed = int(ledger_a0["seed"])
        a0_source = "ledger"
    elif "A0" in staged:
        identity = identity_compare(staged["A0"], reference, tolerance=contract_identity_tolerance(contract))
        if identity["status"] != "PASS":
            common.append("a0_identity_fail")
            record_attempt(root, origin=origin, arm="A0", kind="a0_identity_fail",
                           detail=json.dumps(identity, ensure_ascii=False, sort_keys=True), now=current)
            attempts.append("A0:a0_identity_fail")
        a0_seed = int(staged["A0"]["seed"])
        a0_source = "staging"
    else:
        common.append("a0_missing")
        record_attempt(root, origin=origin, arm="A0", kind="a0_missing",
                       detail=f"A0 staging·원장 행 모두 없음 — 전 팔 제외 (v8 {v8_forecast_id})", now=current)
        attempts.append("A0:a0_missing")
    appended: list[str] = []
    skipped: list[str] = []
    for arm in WEEKLY_ARMS:
        if arm not in staged:
            continue
        payload = staged[arm]
        excluded = list(common)
        if arm != "A0" and a0_seed is not None and int(payload["seed"]) != a0_seed:
            excluded.append("crn_violation")
        row = _row_from_stage(payload, issued_at=current, excluded=excluded,
                              identity=identity if arm == "A0" else None)
        if row["forecast_id"] in existing_ids:
            skipped.append(arm)  # 최초 행이 정본 — 재계산 부동소수 차로 충돌하지 않게 비교 없이 건너뛴다
            continue
        _chain_append(root, SHADOW_LEDGER, row, key="forecast_id")
        existing_ids.add(row["forecast_id"])
        appended.append(arm)
    gaps = record_catch_up_gaps(root, contract=contract, now=current)
    return {"origin": origin, "v8_forecast_id": v8_forecast_id, "appended": appended, "skipped": skipped,
            "identity": identity, "a0_source": a0_source, "attempts": attempts, "gaps_recorded": gaps}


def record_catch_up_gaps(root: Path, *, contract: Mapping[str, Any], now: datetime) -> int:
    """따라잡기 창(2원점) 밖의 누락 팔을 gap_outside_catchup 으로 1회만 남긴다 — 계산하지 않는다."""
    fonb = _first_origin(contract)
    _, outside = catch_up_targets(read_v8_rows(root), first_origin_not_before=fonb, latest_only=False,
                                  window=int(contract["live"]["catch_up_window_v8_origins"]))
    present = _existing_arms(root)
    count = 0
    for row in outside:
        missing = [arm for arm in WEEKLY_ARMS if arm not in present.get(str(row["forecast_id"]), set())]
        for arm in missing:
            if record_attempt(root, origin=str(row["origin"]), arm=arm, kind="gap_outside_catchup",
                              detail=f"v8 {row['forecast_id']} — 창 밖 누락, 계산하지 않음", now=now, dedupe=True):
                count += 1
    return count


def _first_origin(contract: Mapping[str, Any]) -> str | None:
    value = (contract.get("live") or {}).get("first_origin_not_before")
    return str(value) if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)) else None


def collect_a5(root: Path, *, staging: Path, now: datetime | None = None) -> dict[str, Any]:
    contract = load_contract_v15(root)
    assert_track_open(contract)
    current = _utc(now)
    payload = _staged(Path(staging) / "A5.json")
    if payload is None:
        record_attempt(root, origin=None, arm="A5", kind="a5_origin_unavailable",
                       detail="staging/A5.json 없음", now=current)
        return {"appended": False, "status": "a5_origin_unavailable"}
    origin = str(payload["origin"])
    issuance = payload["issuance"]
    if payload.get("kernel_code_hash") != str(contract["fork"]["frozen_kernel_code_hash"]):
        record_attempt(root, origin=origin, arm="A5", kind="kernel_hash_drift",
                       detail=str(payload.get("kernel_code_hash")), now=current)
        return {"appended": False, "status": "kernel_hash_drift"}
    expected_origin = str(issuance["expected_origin"])
    if origin != expected_origin:
        # 원천 지연(예: 월요일에 금요일 종가 미포착 → 목요일 원점)은 마감 검사보다 먼저 분류한다 — 원점이 기대
        # 원점보다 이르면 그 다음 세션 개장(=마감)도 이미 지나 a5_deadline_missed 로 잘못 남기 때문이다.
        record_attempt(root, origin=origin, arm="A5", kind="a5_origin_unavailable",
                       detail=f"원점 {origin} != 기대 원점 {expected_origin} (기대 ISO 주 {iso_week(expected_origin)})",
                       now=current)
        return {"appended": False, "status": "a5_origin_unavailable"}
    deadline = _parse(issuance["deadline_utc"])
    if current > deadline:
        record_attempt(root, origin=origin, arm="A5", kind="a5_deadline_missed",
                       detail=f"now {_stamp(current)} > deadline {issuance['deadline_utc']}", now=current)
        return {"appended": False, "status": "a5_deadline_missed"}
    rows = _read_chain(root, ISSUANCE_LEDGER)
    if any(row.get("iso_week") == payload["iso_week"] for row in rows):
        return {"appended": False, "status": "already_issued_this_iso_week"}
    row = _row_from_stage(payload, issued_at=current, excluded=[], identity=None)
    row["issuance"] = {**issuance, "issued_before_open": bool(current <= deadline)}
    _chain_append(root, ISSUANCE_LEDGER, row, key="forecast_id")
    return {"appended": True, "status": "issued", "origin": origin, "forecast_id": row["forecast_id"]}


# ── 해소 ─────────────────────────────────────────────────────────────────────


def resolve_v15(root: Path, *, now: datetime | None = None, observations: Sequence[Any] | None = None) -> dict[str, Any]:
    from ai_fc.timeseries.backtest import sample_crps

    from .calendar import CALENDAR_START, calendar_hash, exchange_calendars_version
    from .labels import LABEL_BASIS, MEASURED_TOLERANCE, NasdaqArchive, V15LabelError, XnasCalendar, pit_mid, xnas_label

    load_contract_v15(root)
    current = _utc(now)
    forecasts = ([("shadow", row) for row in _read_chain(root, SHADOW_LEDGER)]
                 + [("issuance", row) for row in _read_chain(root, ISSUANCE_LEDGER)])
    if not forecasts:
        return {"resolved": 0, "corrections": 0, "note": "no V15 forecasts yet"}
    if observations is None:
        from ai_fc.timeseries_v2.market_archive import read_market_observations

        observations = read_market_observations(root, knowledge_cutoff=_stamp(current))
    archive = NasdaqArchive.from_observations(observations, as_of=current.date())
    last_origin = max(date.fromisoformat(str(row["origin"])) for _, row in forecasts)
    cal = XnasCalendar.build(CALENDAR_START, last_origin + timedelta(days=150))
    version = exchange_calendars_version()
    resolutions = _read_chain(root, RESOLUTION_LEDGER)
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    counts: dict[tuple[str, int], int] = {}
    for row in resolutions:
        key = (row["forecast_id"], int(row["horizon"]))
        latest[key] = row
        counts[key] = counts.get(key, 0) + 1
    appended = corrections = 0
    for ledger, forecast in forecasts:
        origin = date.fromisoformat(str(forecast["origin"]))
        for key_h in HORIZON_KEYS:
            h = int(key_h)
            try:
                labelled = xnas_label(origin, h, cal, archive)
            except V15LabelError:
                continue
            if labelled is None:
                continue
            target, y = labelled
            key = (forecast["forecast_id"], h)
            previous = latest.get(key)
            if previous is not None and abs(float(previous["y"]) - y) <= MEASURED_TOLERANCE:
                continue
            block = forecast["horizons"][key_h]
            grid = np.asarray(block["quantile_grid"], dtype=float)
            baseline = np.asarray(block["baseline_quantile_grid"], dtype=float)
            levels = int(forecast["grid_levels_count"])
            p_up = float(block["p_up"])
            revision = counts.get(key, 0) + 1
            resolution_id = f"{forecast['forecast_id']}-h{h}-{LABEL_BASIS}"
            if revision > 1:
                resolution_id += f"-r{revision}"
            payload = {
                "schema_version": 1, "resolution_id": resolution_id, "forecast_id": forecast["forecast_id"],
                "ledger": ledger, "arm": forecast["arm"], "origin": forecast["origin"], "horizon": h,
                "label_basis": LABEL_BASIS, "target_session": target.isoformat(), "y": float(y),
                "crps_model": float(sample_crps(grid, y)), "crps_baseline": float(sample_crps(baseline, y)),
                "pit": pit_mid(grid, y),
                "cov80": bool(float(grid[int(0.10 * levels)]) <= y <= float(grid[int(0.90 * levels)])),
                "p_up": p_up, "up_brier": (p_up - (1.0 if y > 0 else 0.0)) ** 2,
                "input_hash": archive.input_hash([origin, target]),
                "calendar_hash": calendar_hash(origin), "exchange_calendars_version": version,
                "resolved_at": _stamp(current),
                "excluded_reasons": list(forecast.get("excluded_reasons") or []),
                "supersedes": None if previous is None else previous["resolution_id"],
                "notice": NOTICE,
            }
            stored = _chain_append(root, RESOLUTION_LEDGER, payload, key="resolution_id")
            latest[key] = stored
            counts[key] = revision
            appended += 1
            corrections += int(previous is not None)
    return {"resolved": appended, "corrections": corrections,
            "total_resolutions": len(_read_chain(root, RESOLUTION_LEDGER))}


# ── 상태 ─────────────────────────────────────────────────────────────────────


def status_payload(root: Path) -> dict[str, Any]:
    from .verdict import counts_only

    contract = load_contract_v15(root)
    shadow = _read_chain(root, SHADOW_LEDGER)
    issuance = _read_chain(root, ISSUANCE_LEDGER)
    resolutions = _read_chain(root, RESOLUTION_LEDGER)
    attempts = _read_chain(root, ATTEMPTS_LEDGER)
    kinds: dict[str, int] = {}
    for row in attempts:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    attempts_files = identity_attempts(root)
    return {
        "schema_version": 1, "model_id": MODEL_ID, "contract_hash": frozen_hash(contract),
        "track_open": bool(contract["development_protocol"].get("track_open")),
        "mde_status": contract["mde"].get("status"),
        "counts": {"shadow_forecasts": len(shadow), "issuance_forecasts": len(issuance),
                   "shadow_resolutions": len(resolutions), "attempts": kinds,
                   "verdicts": len(_read_chain(root, VERDICTS_LEDGER)),
                   "a0_identity_attempts": len(attempts_files)},
        "families": counts_only(shadow=shadow, issuance=issuance, resolutions=resolutions,
                                first_origin_not_before=_first_origin(contract)),
        "display": "none — 화면 없음(scoring_excluded_from_official). d̄·CI 는 이 파일에 두지 않는다",
        "notice": NOTICE,
    }


def write_status(root: Path) -> dict[str, Any]:
    payload = status_payload(root)
    _write_json(root / STATUS_RELATIVE, payload)
    return payload


# ── identity 시도 파일 ────────────────────────────────────────────────────────


def identity_attempts(root: Path) -> list[dict[str, Any]]:
    folder = root / PREREG_RELATIVE
    rows = []
    if not folder.is_dir():
        return rows
    for path in sorted(folder.glob("a0_live_identity_*_a*.json")):
        match = IDENTITY_FILE.search(path.name)
        if not match:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append({"path": path.relative_to(root).as_posix(), "v8_origin": match.group(1),
                     "attempt": int(match.group(2)), "status": payload.get("status"),
                     "computed_at": payload.get("computed_at")})
    rows.sort(key=lambda row: (str(row["computed_at"]), row["v8_origin"], row["attempt"]))
    return rows


def latest_identity_status(root: Path) -> str | None:
    rows = identity_attempts(root)
    return rows[-1]["status"] if rows else None


def a0_identity_attempt(
    root: Path, *, v8_forecast_id: str, data_root: Path, snapshot_sha: str, stage_out: Path,
    now: datetime | None = None, path_count: int | None = None,
) -> dict[str, Any]:
    """V15 A0 를 V8 행의 knowledge_cutoff·스냅숏에서 전체 재생해 대조(라벨 미열람)."""
    contract = load_contract_v15(root)
    reference = v8_row(root, v8_forecast_id)
    computed = compute_arm(root, data_root=Path(data_root), arm="A0",
                           knowledge_cutoff=str(reference["knowledge_cutoff"]),
                           origin=str(reference["origin"]), path_count=path_count)
    identity = identity_compare(computed["forecast"], reference, tolerance=contract_identity_tolerance(contract))
    payload = {
        "schema_version": 1, "kind": "v15_a0_live_identity_attempt",
        "v8_forecast_id": v8_forecast_id, "v8_origin": str(reference["origin"]),
        "v8_knowledge_cutoff": str(reference["knowledge_cutoff"]), "snapshot_sha": snapshot_sha,
        "snapshot_method": SNAPSHOT_METHOD, **identity, **_runtime(),
        "kernel_code_hash": kernel_code_hash(root), "computed_at": _stamp(_utc(now)),
        "outcome_blind": True, "notice": NOTICE,
    }
    payload["content_hash"] = canonical_hash(payload)
    _write_json(Path(stage_out), payload)
    return {"status": identity["status"], "max_abs_diff": identity["max_abs_diff"],
            "mismatched_fields": identity["mismatched_fields"], "stage_out": str(stage_out)}


def record_identity_attempt(root: Path, *, staged: Path) -> dict[str, Any]:
    payload = _staged(Path(staged))
    if payload is None or payload.get("kind") != "v15_a0_live_identity_attempt":
        raise TimeSeriesV15PipelineError("identity staging 파일이 없거나 형식이 다르다")
    origin = str(payload["v8_origin"])
    existing = [row for row in identity_attempts(root) if row["v8_origin"] == origin]
    attempt = max((row["attempt"] for row in existing), default=0) + 1
    target = root / PREREG_RELATIVE / f"a0_live_identity_{origin}_a{attempt}.json"
    _write_json(target, payload, exclusive=True)  # write-once — 기존 시도 파일은 바이트 불변
    return {"written": target.relative_to(root).as_posix(), "status": payload["status"], "attempt": attempt}


# ── 무결성 ───────────────────────────────────────────────────────────────────


def fork_patch_errors(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = {entry["target"]: entry for entry in manifest.get("files", [])}
    for source, target in FORKED:
        entry = entries.get(target)
        if entry is None or entry.get("source") != source:
            errors.append(f"fork patch: {target} 항목 없음")
            continue
        original = (root / source).read_bytes()
        forked = (root / target).read_bytes()
        if hashlib.sha256(original).hexdigest() != entry["source_sha256"]:
            errors.append(f"fork patch: 봉인 원본 {source} sha256 불일치")
        if hashlib.sha256(forked).hexdigest() != entry["target_sha256"]:
            errors.append(f"fork patch: 포크 {target} sha256 불일치")
        diff = "".join(difflib.unified_diff(
            original.decode("utf-8").splitlines(keepends=True), forked.decode("utf-8").splitlines(keepends=True),
            fromfile=source, tofile=target,
        ))
        if diff != entry["unified_diff"]:
            errors.append(f"fork patch: {target} diff 재현 실패")
    return errors


def _mapping_keys(node: Any) -> set[str]:
    """중첩 dict·list 안 모든 dict 키(값 문자열은 세지 않는다)."""
    if isinstance(node, Mapping):
        keys = {str(key) for key in node}
        for value in node.values():
            keys |= _mapping_keys(value)
        return keys
    if isinstance(node, list):
        keys: set[str] = set()
        for value in node:
            keys |= _mapping_keys(value)
        return keys
    return set()


def _prereg_errors(root: Path, contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    manifest_path = root / FORK_PATCH_RELATIVE
    if not manifest_path.is_file():
        return [f"{FORK_PATCH_RELATIVE.as_posix()} 없음"]
    body = manifest_path.read_bytes()
    pinned = str((contract.get("fork") or {}).get("patch_manifest_sha256"))
    if hashlib.sha256(body).hexdigest() != pinned:
        errors.append("fork_patch_v1.json sha256 != 계약 fork.patch_manifest_sha256")
    manifest = json.loads(body.decode("utf-8"))
    content = {key: value for key, value in manifest.items() if key != "content_hash"}
    if manifest.get("content_hash") != canonical_hash(content):
        errors.append("fork_patch_v1.json content_hash 불일치")
    errors.extend(fork_patch_errors(root, manifest))
    for (source, _), entry in zip(FORKED, ((contract.get("fork") or {}).get("copied_and_patched") or [])):
        if entry.get("source") != source or entry.get("source_sha256") != hashlib.sha256((root / source).read_bytes()).hexdigest():
            errors.append(f"계약 fork.copied_and_patched 핀 불일치: {source}")
    summary = root / MDE_SUMMARY_RELATIVE
    pinned_summary = ((contract.get("mde") or {}).get("artifacts") or {}).get("summary_sha256")
    if summary.is_file():
        payload = json.loads(summary.read_text(encoding="utf-8"))
        if pinned_summary and re.fullmatch(r"[0-9a-f]{64}", str(pinned_summary)):
            if hashlib.sha256(summary.read_bytes()).hexdigest() != pinned_summary:
                errors.append("mde_v1.json sha256 != 계약 mde.artifacts.summary_sha256")
        for arm, digest in (payload.get("replay_sha256") or {}).items():
            replay = root / PREREG_RELATIVE / f"mde_replay_{arm}.json"
            if not replay.is_file() or hashlib.sha256(replay.read_bytes()).hexdigest() != digest:
                errors.append(f"mde_replay_{arm}.json sha256 불일치")
        # 키로만 검사한다 — 요약의 `excludes` 목록이 두 이름을 값으로 공시하므로 문자열 포함 검사는 거짓 경보다.
        if _mapping_keys(payload) & {"design_delta_rel", "power_at_design_estimate"}:
            errors.append("mde_v1 에 효과 추정치 키가 있다")
    elif contract.get("mde", {}).get("status") == "computed":
        errors.append("mde.status computed 인데 mde_v1.json 이 없다")
    for row in identity_attempts(root):
        payload = json.loads((root / row["path"]).read_text(encoding="utf-8"))
        content = {key: value for key, value in payload.items() if key != "content_hash"}
        if payload.get("content_hash") != canonical_hash(content):
            errors.append(f"{row['path']} content_hash 불일치")
    return errors


def _approval_errors(root: Path, contract: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = _read_chain(root, APPROVALS_LEDGER)  # 영수증 원장(체인 아님 — V14 선례) 줄 단위 읽기
    recorded = (contract.get("provenance") or {}).get("rule_hash_r2")
    for decision in DECISIONS:
        matching = [row for row in rows if row.get("decision_id") == decision]
        if len(matching) < 1:
            errors.append(f"approvals: {decision} 영수증 없음")
            continue
        first = matching[0]
        if first.get("approval_text") != APPROVAL_TEXT:
            errors.append(f"approvals: {decision} approval_text 원문 불일치")
        if first.get("rule_hash_r2") != recorded:
            errors.append(f"approvals: {decision} rule_hash_r2 불일치")
    return errors


def _contract_hash_errors(root: Path, contract: Mapping[str, Any]) -> list[str]:
    """라이브 행이 생긴 뒤 계약 frozen 좌표(live.first_origin_not_before·mde 값 포함)는 움직이지 않는다.

    r3 허용 목록은 rule_hash 에서만 빠질 뿐 frozen_hash 에는 들어 있다 — 결과를 본 뒤 첫 원점을 미는 통로를
    막으려고, 모든 라이브 행의 contract_hash 가 서로 같고 현재 frozen_hash 와 같아야 한다.
    """
    current = frozen_hash(dict(contract))
    seen: set[str] = set()
    for relative in (SHADOW_LEDGER, ISSUANCE_LEDGER):
        for row in _read_chain(root, relative):
            seen.add(str(row.get("contract_hash")))
    if not seen:
        return []
    errors: list[str] = []
    if len(seen) > 1:
        errors.append(f"라이브 행의 contract_hash 가 {len(seen)}종 — 라이브 개시 뒤 계약 frozen 좌표가 바뀌었다")
    if seen != {current}:
        errors.append("라이브 행 contract_hash != 현재 계약 frozen_hash (r3 뒤 frozen 좌표 변경 금지 — 새 계약 필요)")
    return errors


def verify_v15(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    contract: dict[str, Any] | None = None
    try:
        contract = load_contract_v15(root)
    except (OSError, ValueError, KeyError) as exc:
        errors.append(f"contract: {exc}")
    relatives = (SHADOW_LEDGER, ISSUANCE_LEDGER, RESOLUTION_LEDGER, ATTEMPTS_LEDGER, VERDICTS_LEDGER)
    for relative in relatives:
        errors.extend(verify_chain(root, relative))
    current_kernel = None
    try:
        current_kernel = kernel_code_hash(root)
    except ValueError as exc:
        errors.append(str(exc))
    if contract is not None:
        frozen_kernel = str(contract["fork"]["frozen_kernel_code_hash"])
        if current_kernel != frozen_kernel:
            errors.append("현재 kernel_code_hash != fork.frozen_kernel_code_hash (mutate_v15_kernel_after_freeze)")
        for relative in (SHADOW_LEDGER, ISSUANCE_LEDGER):
            for row in _read_chain(root, relative):
                if row.get("kernel_code_hash") != frozen_kernel:
                    errors.append(f"{relative.name}: {row.get('forecast_id')} kernel_code_hash 불일치")
        if verdict_code_hash(root) != str(contract["verdict_rule"]["frozen_verdict_code_hash"]):
            errors.append("verdict_code_hash != verdict_rule.frozen_verdict_code_hash")
        try:
            if contract_identity_tolerance(contract) != IDENTITY_TOLERANCE:
                errors.append("pipeline.IDENTITY_TOLERANCE != 계약 arms.A0.identity_tolerance")
        except (TypeError, ValueError) as exc:
            errors.append(f"arms.A0.identity_tolerance: {exc}")
        errors.extend(_contract_hash_errors(root, contract))
        errors.extend(_prereg_errors(root, contract))
        errors.extend(_approval_errors(root, contract))
    return {
        "ok": not errors, "errors": errors, "model_id": MODEL_ID,
        "contract_hash": None if contract is None else frozen_hash(contract),
        "rule_hash": None if contract is None else rule_hash(contract),
        "kernel_code_hash": current_kernel,
        "counts": {relative.name: len(_read_chain(root, relative)) for relative in relatives},
        "scope": "integrity_only — identity·연속 실패는 health 가 본다",
    }


# ── health ───────────────────────────────────────────────────────────────────


def health_v15(root: Path) -> dict[str, Any]:
    shadow = _read_chain(root, SHADOW_LEDGER)
    a0_rows = sorted((row for row in shadow if row.get("arm") == "A0"),
                     key=lambda row: (row["origin"], row["issued_at"]))
    by_origin: dict[str, dict[str, Any]] = {}
    for row in a0_rows:
        by_origin.setdefault(row["origin"], row)
    recent = [by_origin[origin] for origin in sorted(by_origin)][-IDENTITY_STREAK:]
    streak = (len(recent) == IDENTITY_STREAK
              and all("a0_identity_fail" in (row.get("excluded_reasons") or []) for row in recent))
    acked = False
    if streak:
        third = _parse(recent[-1]["issued_at"])
        acked = any(row.get("kind") == "identity_streak_ack" and _parse(row["recorded_at"]) >= third
                    for row in _read_chain(root, ATTEMPTS_LEDGER))
    warnings: list[str] = []
    resolutions = _read_chain(root, RESOLUTION_LEDGER)
    forecasts = {row["forecast_id"]: row for row in shadow + _read_chain(root, ISSUANCE_LEDGER)}
    drift = sum(1 for row in resolutions
                if row["forecast_id"] in forecasts
                and row.get("calendar_hash") != forecasts[row["forecast_id"]].get("calendar_hash"))
    if drift:
        warnings.append(f"calendar_drift 해소 행 {drift}개 — 판정 쌍에서 제외(행 수정 없음)")
    gaps = sum(1 for row in _read_chain(root, ATTEMPTS_LEDGER) if row.get("kind") == "gap_outside_catchup")
    if gaps:
        warnings.append(f"따라잡기 창 밖 누락 {gaps}건")
    return {"identity_streak": bool(streak), "acknowledged": bool(acked),
            "recent_a0_origins": [row["origin"] for row in recent],
            "alert": bool(streak and not acked), "warnings": warnings}


def ack_identity_streak(root: Path, *, reason: str, now: datetime | None = None) -> dict[str, Any]:
    if not str(reason).strip():
        raise TimeSeriesV15PipelineError("--reason 이 필요하다(원인 기록)")
    row = record_attempt(root, origin=None, arm="A0", kind="identity_streak_ack", detail=reason, now=now)
    return {"recorded": row["attempt_id"] if row else None}


# ── 판정 (사람 실행 — 워크플로는 부르지 않는다) ───────────────────────────────


def verdict_v15(root: Path, *, family: str, append: bool = False, now: datetime | None = None) -> dict[str, Any]:
    from .verdict import family_verdict

    contract = load_contract_v15(root)
    observed = verdict_code_hash(root)
    frozen = str(contract["verdict_rule"]["frozen_verdict_code_hash"])
    if observed != frozen:
        raise TimeSeriesV15ContractError(f"verdict_code_hash {observed} != 계약 고정값 {frozen} — 판정 거부")
    current = _utc(now)
    result = family_verdict(
        family=family, shadow=_read_chain(root, SHADOW_LEDGER), issuance=_read_chain(root, ISSUANCE_LEDGER),
        resolutions=_read_chain(root, RESOLUTION_LEDGER), first_origin_not_before=_first_origin(contract),
        now=current, verdict_code_hash=observed, rule_hash=rule_hash(contract),
    )
    if not append:
        if result["status"] == "pending":
            return result
        return {**result, "append": False}
    if result["status"] != "decided":
        raise TimeSeriesV15PipelineError("T*_F 미확정·마감 컷 전 — 판정 append 거부(조기 판정 금지)")
    existing = [row for row in _read_chain(root, VERDICTS_LEDGER) if row.get("family") == family]
    if existing:
        raise TimeSeriesV15PipelineError(f"{family} 판정은 이미 기록됐다 — 가족당 1회")
    row = {**result, "verdict_id": f"tsv15-verdict-{family}", "recorded_at": _stamp(current)}
    stored = _chain_append(root, VERDICTS_LEDGER, row, key="verdict_id")
    return {**result, "append": True, "verdict_id": stored["verdict_id"]}


def first_origin_not_before(v8_rows: Sequence[Mapping[str, Any]], *, r3_committed_at: str) -> str | None:
    """N9 규칙: V8 행 knowledge_cutoff > r3 커밋 시각(UTC)인 첫 V8 행의 origin."""
    cut = _parse(r3_committed_at)
    eligible = sorted((row for row in v8_rows if _parse(str(row["knowledge_cutoff"])) > cut),
                      key=lambda row: (_parse(str(row["knowledge_cutoff"])), row["origin"]))
    return str(eligible[0]["origin"]) if eligible else None
