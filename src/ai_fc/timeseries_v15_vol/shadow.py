"""V15-VOL 일일 섀도 발행 — V13 라이브 원장 행의 순수 함수(아카이브 읽기 0, PIT 는 V13 행에서 상속).

fail-closed 사전 검사(`_hold_reasons`): 계약 미무장 · 판정 코드 핀 불일치 · V13 계수 재동결/핀 불일치 · 상수 핀 불일치.
무장행(effective_from 의 유일 원천)은 계약 armed 상태로 main 예약 CI(step env V15_VOL_ARMING_CONTEXT=main_scheduled_ci)에서
처음 실행될 때만 1행 쓴다 — 사람이 고르는 날짜 0. 로컬·PR CI 는 hold arming_pending_ci(정상 — 쓰기 0).
표시·포인터 파일 없음(t0_internal). 출력은 참고 의견이며 매매 신호가 아니다.
"""

from __future__ import annotations

import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..timeseries_v13 import contracts as V13C
from ..timeseries_v8.artifact import append_unique
from . import arms as A
from . import contracts as C
from .resolve import _xnas_session_offset

ROUND_DIGITS = 10
RECOMPUTE_TOLERANCE = 1e-9


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _armed(contract: dict[str, Any]) -> bool:
    return ((contract.get("development_protocol") or {}).get("track_open") is True
            and (contract.get("gates") or {}).get("armed") is True)


def _hold_reasons(root: Path, contract: dict[str, Any], *,
                  require_armed: bool = True) -> tuple[list[str], dict[str, Any]]:
    """publish·resolve·verify 가 공유하는 사전 검사 — (hold 사유 목록, 로드된 맥락{v13_frozen, constants}).

    require_armed=False 는 verify 전용(철회 뒤에도 이미 쓴 행을 재계산 대조하기 위해 무장 검사만 건너뛴다).
    """
    context: dict[str, Any] = {}
    if require_armed and not _armed(contract):
        return ["not_armed"], context
    mismatched = C.check_code_pins(root, contract)
    if mismatched:
        return [f"code_pin_mismatch:{','.join(mismatched)}"], context
    parent = contract.get("parent_v13") or {}
    try:
        v13 = V13C.load_contract_v13(root)
    except V13C.TimeSeriesV13VolError as exc:
        return [f"v13_contract_unavailable:{exc}"], context
    if (v13.get("frozen_coefficients") or {}).get("sha256") != parent.get("coefficients_sha256"):
        return ["v13_refrozen"], context
    try:
        context["v13_frozen"] = V13C.load_frozen_coefficients(
            root, expected_sha256=parent.get("coefficients_sha256"),
            expected_content_hash=parent.get("coefficients_content_hash"),
            expected_finalist_id=parent.get("finalist_id"))
    except V13C.TimeSeriesV13VolError:
        return ["v13_coefficients_pin_mismatch"], context
    pin = contract.get("frozen_constants") or {}
    try:
        context["constants"] = C.load_constants(root, expected_sha256=pin.get("sha256"),
                                                expected_content_hash=pin.get("content_hash"))
    except (C.TimeSeriesV15VolError, OSError, ValueError):
        return ["constants_pin_mismatch"], context
    return [], context


def _effective_from_for(observed_at: datetime) -> str:
    return _xnas_session_offset(observed_at.astimezone(timezone.utc).date(), 1).isoformat()


def _arming_row(root: Path, contract: dict[str, Any], current: datetime) -> dict[str, Any] | None:
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if not run_id or not sha:
        return None
    row: dict[str, Any] = {
        "schema_version": 1,
        "kind": "v15_vol_arming",
        "armed_observed_at": current.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "effective_from": _effective_from_for(current),
        "contract_sha256": C.contract_sha256(root),
        "prereg_commit": (contract.get("development_protocol") or {}).get("prereg_commit"),
        "github_run_id": run_id,
        "github_sha": sha,
    }
    row["content_hash"] = C.canonical_hash(row)
    return row


def _row_inputs(v13_row: dict[str, Any]) -> dict[str, float]:
    inputs = v13_row.get("inputs") or {}
    return {"vix_close": float(inputs["vix_close"]), "rv21_ann": float(inputs["rv21_ann"])}


def derive_cells(v13_row: dict[str, Any], constants: dict[str, Any], v13_frozen: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """V13 행 하나의 섀도 열(반올림 10자리) — 행에 없는 셀은 cells_missing."""
    inputs = _row_inputs(v13_row)
    recorded = v13_row.get("cells") or {}
    cells: dict[str, Any] = {}
    missing: list[str] = []
    for spec in C.cell_specs():
        name = spec["name"]
        if name not in recorded or recorded[name].get("p") is None:
            missing.append(name)
            continue
        clim = float(v13_frozen["cells"][name]["clim_base_rate"])
        cols = A.cell_columns(spec, inputs, float(recorded[name]["p"]), constants, clim=clim)
        cells[name] = {key: (value if isinstance(value, bool) else round(float(value), ROUND_DIGITS))
                       for key, value in cols.items()}
    return cells, missing


def _shadow_row(v13_row: dict[str, Any], *, contract_sha: str, constants_pin: dict[str, Any],
                constants: dict[str, Any], v13_frozen: dict[str, Any], derived_at: str) -> dict[str, Any]:
    v13_sha = str(v13_row["coefficients_sha256"])
    const_sha = str(constants_pin["sha256"])
    cells, missing = derive_cells(v13_row, constants, v13_frozen)
    row: dict[str, Any] = {
        "schema_version": 1,
        "run_id": f"v15vol-{v13_row['as_of']}-{v13_sha[:8]}-{const_sha[:8]}",
        "as_of": v13_row["as_of"],
        "model_id": C.MODEL_ID,
        "probability_space": C.PROBABILITY_SPACE,
        "reference_opinion_only": True,
        "trading_signal": False,
        "holdout_status": "not_applicable_live_forward",
        "contract_sha256": contract_sha,
        "constants_sha256": const_sha,
        "constants_content_hash": constants_pin["content_hash"],
        "v13_run_id": v13_row["run_id"],
        "v13_row_content_hash": v13_row.get("content_hash"),
        "v13_coefficients_sha256": v13_sha,
        "v13_knowledge_cutoff": v13_row.get("knowledge_cutoff"),
        "v13_pit_grade": v13_row.get("pit_grade") or "captured_forward",
        "derived_at": derived_at,
        "derivation": "pure_function_of_v13_row",
        "inputs": _row_inputs(v13_row),
        "cells": cells,
        "cells_missing": missing,
    }
    row["content_hash"] = C.canonical_hash(row)
    return row


def _v13_candidates(root: Path, pinned_sha: str, effective_from: str) -> tuple[list[dict[str, Any]], int]:
    rows = C.read_rows(root / V13C.LIVE_LEDGER_RELATIVE)
    pinned = [r for r in rows if r.get("coefficients_sha256") == pinned_sha]
    before = sum(1 for r in pinned if str(r.get("as_of")) < effective_from)
    after = sorted((r for r in pinned if str(r.get("as_of")) >= effective_from), key=lambda r: str(r.get("as_of")))
    return after, before


def publish_shadow_v15_vol(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """V13 원장 행(핀 sha ∧ as_of ≥ effective_from)마다 V15 섀도 행 1개를 append 한다(멱등)."""
    current = _now(now)
    contract = C.load_contract_v15_vol(root)
    reasons, context = _hold_reasons(root, contract)
    if reasons:
        return {"status": "hold", "reasons": reasons, "appended": 0}
    armed_now = False
    arming = C.read_arming(root)
    if arming is None:
        if os.environ.get(C.ARMING_ENV) != C.ARMING_ENV_VALUE:
            return {"status": "hold", "reasons": ["arming_pending_ci"], "appended": 0}
        arming = _arming_row(root, contract, current)
        if arming is None:
            return {"status": "hold", "reasons": ["arming_context_incomplete"], "appended": 0}
        append_unique(root, C.ARMING_LEDGER_RELATIVE, arming, key="kind")
        armed_now = True
    arming_errors: list[str] = []
    _verify_arming(root, arming_errors, contract)
    if arming_errors:   # 위조·오작성 무장행으로 소급 행을 append 하지 않는다(append-only 라 되돌릴 수 없다 — 리뷰 N2)
        return {"status": "hold", "reasons": ["arming_row_invalid"], "appended": 0, "errors": arming_errors}
    effective_from = str(arming["effective_from"])
    parent_sha = str((contract.get("parent_v13") or {})["coefficients_sha256"])
    constants_pin = contract["frozen_constants"]
    contract_sha = C.contract_sha256(root)
    existing = {str(r.get("run_id")) for r in C.read_rows(root / C.SHADOW_LEDGER_RELATIVE)}
    candidates, before = _v13_candidates(root, parent_sha, effective_from)
    derived_at = current.isoformat(timespec="seconds")
    appended = 0
    for v13_row in candidates:
        row = _shadow_row(v13_row, contract_sha=contract_sha, constants_pin=constants_pin,
                          constants=context["constants"], v13_frozen=context["v13_frozen"], derived_at=derived_at)
        if row["run_id"] in existing:
            continue
        if append_unique(root, C.SHADOW_LEDGER_RELATIVE, row, key="run_id"):
            appended += 1
            existing.add(row["run_id"])
    return {"status": "live", "appended": appended, "skipped_before_effective_from": before,
            "armed_now": armed_now, "effective_from": effective_from, "errors": []}


def _aware(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("naive timestamp")
    return parsed


def _verify_arming(root: Path, errors: list[str], contract: dict[str, Any]) -> dict[str, Any] | None:
    try:
        arming = C.read_arming(root)
    except C.TimeSeriesV15VolError as exc:
        errors.append(f"arming: {exc}")
        return None
    if arming is None:
        return None
    if arming.get("kind") != "v15_vol_arming":
        errors.append("arming row kind mismatch")
    if not str(arming.get("github_run_id") or "").strip() or not str(arming.get("github_sha") or "").strip():
        errors.append("arming row lacks github_run_id/github_sha")
    observed: datetime | None = None
    try:
        observed = _aware(arming.get("armed_observed_at"))
        if _effective_from_for(observed) != arming.get("effective_from"):
            errors.append("arming effective_from is not the first XNAS session strictly after armed_observed_at (UTC)")
    except (TypeError, ValueError):
        errors.append("arming armed_observed_at unparseable")
    # 사고 방지(리뷰 N2): 무장행은 커밋 B(prereg_commit·armed_at 기입) 뒤의 main CI 만 쓴다.
    prereg = (contract.get("development_protocol") or {}).get("prereg_commit")
    if prereg and arming.get("prereg_commit") != prereg:
        errors.append("arming prereg_commit differs from contract development_protocol.prereg_commit")
    armed_at = (contract.get("live_shadow") or {}).get("armed_at")
    if armed_at and observed is not None:
        try:
            if observed < _aware(armed_at):
                errors.append("arming armed_observed_at is earlier than contract live_shadow.armed_at")
        except (TypeError, ValueError):
            errors.append("contract live_shadow.armed_at unparseable")
    return arming


# 재계산 대조에서 빼는 필드: derived_at(늦은 계산 허용·정보), contract_sha256(row_contract_sha256: informational),
# content_hash(별도 대조), cells(아래에서 |Δ|≤1e-9 로 대조).
RECOMPUTE_EXEMPT_FIELDS = frozenset({"derived_at", "contract_sha256", "content_hash", "cells"})


def verify_shadow_v15_vol(root: Path) -> dict[str, Any]:
    """해시·중복·effective_from·V13 참조 해시·핀·전 필드 재계산(셀 |Δ|≤1e-9)·완전성·코드 핀·무장행·조용한 hold 차단.

    완전성 기준 구간(리뷰 B1): 발행이 진행되는 상태(armed ∧ hold 없음, 또는 armed ∧ hold ∧ 종결 미확인 — 이때는
    armed_but_holding 이 이미 오류)에서는 effective_from 이후 V13 핀 행 전부. 발행이 정당하게 멈춘 상태 — 철회(계약
    미무장인데 무장행 존재, notes disarmed_after_arming) 또는 parent_v13.termination_acknowledged 로 확인된 hold — 에서는
    effective_from ~ 이미 쓴 마지막 V15 as_of 까지만 본다(그 안의 구멍은 여전히 오류, 그 뒤 V13 행은 면제).
    """
    errors: list[str] = []
    notes: list[str] = []
    contract = C.load_contract_v15_vol(root)
    rows = C.read_rows(root / C.SHADOW_LEDGER_RELATIVE)
    arming = _verify_arming(root, errors, contract)
    armed = _armed(contract)
    stopped = False
    if armed:
        reasons, context = _hold_reasons(root, contract)
        if arming is not None and reasons:
            ack = (contract.get("parent_v13") or {}).get("termination_acknowledged")
            if ack:
                notes.append(f"v13_terminated_acknowledged:{ack}")
                stopped = True
            else:
                errors.append(f"armed_but_holding:{','.join(reasons)}")
        if arming is None and os.environ.get(C.ARMING_ENV) == C.ARMING_ENV_VALUE and not reasons:
            errors.append("arming_not_written")
        elif arming is None and os.environ.get(C.ARMING_ENV) == C.ARMING_ENV_VALUE:
            errors.append(f"arming_not_written:{','.join(reasons)}")
    else:
        reasons, context = ["not_armed"], {}
        if arming is not None:
            # 철회(영수증 revocation: gates.armed false·track_open false) — 발행 0 은 정상, 이미 쓴 행은 계속 재계산 대조.
            notes.append("disarmed_after_arming")
            stopped = True
            pre, context = _hold_reasons(root, contract, require_armed=False)
            if pre:
                notes.append(f"disarmed_recompute_unavailable:{','.join(pre)}")
    mismatched = C.check_code_pins(root, contract)
    if mismatched and mismatched != ["unpinned"]:
        errors.append(f"code_pin_mismatch:{','.join(mismatched)}")
    if rows and arming is None:
        errors.append("rows_without_arming")     # 무장 여부와 무관 — 무장행 없이 행이 생기는 정당한 경로는 없다
    effective_from = str(arming["effective_from"]) if arming else None
    parent = contract.get("parent_v13") or {}
    pin = contract.get("frozen_constants") or {}
    v13_frozen = context.get("v13_frozen")
    constants = context.get("constants")
    if v13_frozen is not None:
        for name, cell in (v13_frozen.get("cells") or {}).items():
            if cell.get("derived_layer", "raw") != "raw" or cell.get("iso_map") is not None:
                errors.append(f"v13_derived_layer_changed:{name}")
    v13_rows = {str(r.get("run_id")): r for r in C.read_rows(root / V13C.LIVE_LEDGER_RELATIVE)}
    seen: set[str] = set()
    contract_sha = C.contract_sha256(root)
    for row in rows:
        run_id = str(row.get("run_id"))
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if C.canonical_hash(body) != row.get("content_hash"):
            errors.append(f"shadow row hash mismatch: {run_id}")
        if run_id in seen:
            errors.append(f"duplicate run_id: {run_id}")
        seen.add(run_id)
        if effective_from and str(row.get("as_of")) < effective_from:
            errors.append(f"row before effective_from: {run_id}")
        if row.get("probability_space") != C.PROBABILITY_SPACE or row.get("model_id") != C.MODEL_ID:
            errors.append(f"identity mismatch: {run_id}")
        if row.get("reference_opinion_only") is not True or row.get("trading_signal") is not False:
            errors.append(f"reference_opinion_only/trading_signal invalid: {run_id}")
        if row.get("v13_coefficients_sha256") != parent.get("coefficients_sha256"):
            errors.append(f"v13 pin mismatch: {run_id}")
        if row.get("constants_sha256") != pin.get("sha256") or row.get("constants_content_hash") != pin.get("content_hash"):
            errors.append(f"constants pin mismatch: {run_id}")
        try:
            if _aware(row.get("derived_at")).astimezone(timezone.utc).date().isoformat() < str(row.get("as_of")):
                errors.append(f"derived_at before as_of: {run_id}")
        except (TypeError, ValueError):
            errors.append(f"derived_at unparseable: {run_id}")
        source = v13_rows.get(str(row.get("v13_run_id")))
        if source is None:
            errors.append(f"v13 row missing: {run_id}")
            continue
        if source.get("content_hash") != row.get("v13_row_content_hash"):
            errors.append(f"v13 row hash differs: {run_id}")
        if str(source.get("as_of")) != str(row.get("as_of")):
            errors.append(f"v13 row as_of differs: {run_id}")
        if constants is None or v13_frozen is None:
            continue
        expected = _shadow_row(source, contract_sha=contract_sha, constants_pin=pin, constants=constants,
                               v13_frozen=v13_frozen, derived_at=str(row.get("derived_at")))
        if expected["run_id"] != run_id or expected["cells_missing"] != row.get("cells_missing"):
            errors.append(f"recompute identity: {run_id}")
        for key in sorted((set(expected) | set(row)) - RECOMPUTE_EXEMPT_FIELDS):
            if expected.get(key) != row.get(key):
                errors.append(f"recompute field {key}: {run_id}")
        if set(expected["cells"]) != set(row.get("cells") or {}):
            errors.append(f"recompute cell set: {run_id}")
            continue
        for name, cols in expected["cells"].items():
            got = row["cells"][name]
            if set(cols) != set(got) or cols["calm"] != got.get("calm"):
                errors.append(f"recompute columns: {run_id}/{name}")
                continue
            for key, value in cols.items():
                if key == "calm":
                    continue
                if not math.isclose(float(got[key]), float(value), abs_tol=RECOMPUTE_TOLERANCE):
                    errors.append(f"recompute: {run_id}/{name}/{key}")
    upper = max((str(r.get("as_of")) for r in rows), default=None) if stopped else None
    if effective_from:
        by_as_of: dict[str, int] = {}
        for row in rows:
            by_as_of[str(row.get("as_of"))] = by_as_of.get(str(row.get("as_of")), 0) + 1
        for v13_row in v13_rows.values():
            if v13_row.get("coefficients_sha256") != parent.get("coefficients_sha256"):
                continue
            as_of = str(v13_row.get("as_of"))
            if as_of < effective_from:
                continue
            if stopped and (upper is None or as_of > upper):
                continue                 # 발행이 정당하게 멈춘 뒤의 V13 행 — 면제(B1)
            count = by_as_of.get(as_of, 0)
            if count == 0:
                errors.append(f"shadow incomplete: {as_of}")
            elif count > 1:
                errors.append(f"shadow duplicate as_of: {as_of}")
    return {"ok": not errors, "errors": errors, "notes": notes, "rows": len(rows),
            "armed": armed, "arming_present": arming is not None, "effective_from": effective_from,
            "hold_reasons": reasons, "completeness_upper": upper}


def effective_from_for_date(day: date) -> str:
    """테스트·문서용: UTC 날짜 day 의 무장행 effective_from(엄격히 뒤 첫 XNAS 세션)."""
    return _xnas_session_offset(day, 1).isoformat()
