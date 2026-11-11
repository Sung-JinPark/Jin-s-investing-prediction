"""V13-D15 라이브 판정 적용 — 사람이 대화형 세션에서 돌리는 verb 본체 (사전 승인 영수증 필수).

계약 `live_verdict_application`(2026-11-11 등록, 어떤 셀도 60 에 닿기 전)이 정한 것을 **실행만** 한다:
- 체크포인트 = 성숙 60, 이후 +20. 성숙 n < k 이면 그 체크포인트 행을 만들 경로가 없다(조기 적용 금지).
- 표본 = 셀의 distinct 해상 행 중 해상 원장에 처음 기록된 순서로 앞 k 개 → origin 재정렬. append-only 원장의
  앞 k 개는 이후 append 로 바뀌지 않으므로 늦게 돌려도 같은 결과다(실행 시점 재량 0).
- 산술 = `live_verdict._evaluate_cell` 그대로(ℓ13·B2000·seed 20260907·CI90·y-block 귀무 120 draws). draws 는 인자로 못 바꾼다.
- 결과: demotion_candidate → demotion_applied(영구, 표시 hold·배선 자격 상실) · 그 외는 기록만.
- T7: 통과 3셀 전부 k=60 행이 있고 강등 셀(누적) >= 2 → t7_termination 행(카드 전체 hold) + 후속 체크리스트 인쇄.

정지점: 영수증이 없거나 범위가 맞지 않으면 **원장·패널을 읽기 전에** 거부한다(holdout `_require_approval` 패턴).
GitHub Actions·CI 환경변수에서는 쓰기 실행을 거부한다(--dry-run·--verify-only 는 허용). 데스크톱 예약 작업·cron
에이전트는 기계로 막을 수 없어 계약·영수증·런북 문언으로 금지한다. 해제·재무장 경로는 이 모듈에 없다.
참고 의견. 적용은 표시 hold·배선 자격 상실뿐 — 재학습·재예측·승격 없음.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v8.artifact import append_unique
from . import contracts as C
from . import verdict_ledger as VL
from .contracts import TimeSeriesV13VolError
from .live_scoreboard import claim_restriction_for
from .live_verdict import NULL_BOOT_B, NULL_DRAWS, _evaluate_cell, _file_order_cell_rows, verdict_parameters
from .resolve import RESOLUTION_LEDGER_RELATIVE, _read_rows

DECISION_ID = "V13-D15"
SAMPLE_RULE = "ledger_first_recorded_k"
NOTICE = "참고 의견, 매매 신호 아님"
DISCLAIMER = "참고 의견. 적용은 표시 hold·배선 자격 상실뿐 — 재학습·재예측·승격 없음"
RECOMPUTE_TOLERANCE = 1e-9
OUTCOME_BY_STATUS = {
    "demotion_candidate": ("demotion_applied", "cell_display_hold"),
    "verdict_void_negative_control": ("verdict_void", "none"),
    "gate_passed_descriptive": ("no_demotion", "none"),
}
AFTER_DEMOTION = ("recorded_after_demotion", "none")
VERDICT_KEYS = ("status", "matured", "events", "brier_model", "brier_climatology", "bss",
                "paired_loss_vs_climatology", "negative_control_pass_rate", "null_invalid", "null_degenerate",
                "events_below_holdout_guard", "episode_thin")


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def running_in_ci() -> bool:
    return _truthy_env("GITHUB_ACTIONS") or _truthy_env("CI")


def _parse_instant(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo is not None else None


def _approvals(root: Path) -> list[dict[str, Any]]:
    return _read_rows(Path(root) / C.APPROVALS_LEDGER_RELATIVE)


def _git_head(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True,
                                       stderr=subprocess.DEVNULL).strip() or None
    except Exception:  # noqa: BLE001
        return None


def require_application_receipt(root: Path, receipt_id: str, contract: dict[str, Any], *,
                                now: datetime | None = None) -> dict[str, Any]:
    """★ 정지점: 원장·패널을 읽기 전에 영수증을 확인한다. 하나라도 어긋나면 TimeSeriesV13VolError."""
    if not str(receipt_id or "").strip():
        raise TimeSeriesV13VolError(
            "live verdict application requires the V13-D15 approval receipt (--approval-receipt)")
    rows = _approvals(root)
    matches = [r for r in rows if r.get("receipt_id") == receipt_id]
    if not matches:
        raise TimeSeriesV13VolError(f"approval receipt not found: {receipt_id}")
    receipt = matches[-1]
    if receipt.get("decision_id") != DECISION_ID:
        raise TimeSeriesV13VolError("approval receipt is not a V13-D15 live verdict application approval")
    if any(r.get("supersedes") == receipt_id for r in rows):
        raise TimeSeriesV13VolError("approval receipt has been superseded (revoked or corrected) — refusing")
    scope = receipt.get("approval_scope") or {}
    pass_cells = [str(c) for c in ((contract.get("publication") or {}).get("holdout_pass_cells") or [])]
    if scope.get("apply_demotion_rule") is not True:
        raise TimeSeriesV13VolError("approval scope does not cover applying the demotion rule")
    if not set(pass_cells) <= set(scope.get("cells") or []):
        raise TimeSeriesV13VolError("approval scope cells do not cover publication.holdout_pass_cells")
    if scope.get("apply_t7_on_trigger") is not True:
        raise TimeSeriesV13VolError("approval scope does not cover T7 on trigger")
    if scope.get("early_application") is not False:
        raise TimeSeriesV13VolError("approval scope must prohibit early application")
    if scope.get("automation") is not False:
        raise TimeSeriesV13VolError("approval scope must prohibit automation (interactive human session only)")
    # 승인된 체크포인트 일정 == 계약 일정. 계약 step/first 를 결과 뒤에 바꾸면 영수증 범위 밖 → 거부(리뷰 비차단 5).
    contract_checkpoints = (contract.get("live_verdict_application") or {}).get("checkpoints") or {}
    scope_checkpoints = scope.get("checkpoints") or {}
    try:
        same_schedule = all(
            not isinstance(scope_checkpoints[key], bool) and not isinstance(contract_checkpoints[key], bool)
            and int(scope_checkpoints[key]) == int(contract_checkpoints[key]) for key in ("first", "step"))
    except (KeyError, TypeError, ValueError):
        same_schedule = False
    if not same_schedule:
        raise TimeSeriesV13VolError("approval scope checkpoints do not match contract live_verdict_application.checkpoints")
    if not str(receipt.get("approval_text") or "").strip():
        raise TimeSeriesV13VolError("approval receipt carries no verbatim approval text")
    if receipt.get("literal_template_match") is False and (
            receipt.get("approval_form") != "delegated_bundle_instruction"
            or not str(receipt.get("template_text") or "").strip()):
        raise TimeSeriesV13VolError("delegated approval receipt lacks approval_form/template_text")
    stamp = _parse_instant(receipt.get("approved_at"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if stamp is None:
        raise TimeSeriesV13VolError("approval receipt approved_at must carry a timezone")
    if stamp > current:
        raise TimeSeriesV13VolError("approval receipt approved_at is in the future")
    block = contract.get("live_verdict_application")
    if not isinstance(block, dict) or block.get("approval_receipt") != receipt_id:
        raise TimeSeriesV13VolError("contract live_verdict_application does not point at this receipt")
    return receipt


def _file_order_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    """distinct 해상 행, 해상 원장 첫 기록 순(as_of 없음) — 표본 규칙 §3.2.2."""
    return _file_order_cell_rows(root)


def _sha_ids(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _verdict_record(v: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    out = {key: v.get(key) for key in VERDICT_KEYS}
    out["positive_claim_allowed"] = not claim["claim_blocked"]
    out["claim_block_reasons"] = list(claim["claim_block_reasons"])
    return out


def _evaluate_sample(sample: list[dict[str, Any]], params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    v = _evaluate_cell(sample, minimum=params["minimum"], min_events=params["min_events"],
                       min_episodes=params["min_episodes"], draws=NULL_DRAWS)   # 120 고정
    claim = claim_restriction_for(sample, min_events=params["claim"]["min_events"],
                                  min_episodes=params["claim"]["min_episodes"])
    return v, claim


def _checkpoint_row(cell: str, k: int, sample: list[dict[str, Any]], v: dict[str, Any], claim: dict[str, Any],
                    outcome: str, effect: str, receipt_id: str, contract: dict[str, Any], root: Path,
                    computed_at: str) -> dict[str, Any]:
    ids = [str(r["resolution_id"]) for r in sample]
    horizons = {spec["name"]: int(spec["h"]) for spec in C.cell_specs()}
    contract_path = Path(root) / C.CONTRACT_RELATIVE
    row: dict[str, Any] = {
        "schema_version": 1,
        "application_id": f"v13-apply:{cell}:k{k}",
        "kind": "checkpoint_verdict",
        "cell": cell, "checkpoint": int(k), "horizon_sessions": horizons.get(cell),
        "sample_rule": SAMPLE_RULE,
        "origins": [str(r["origin"]) for r in sample],
        "resolution_ids": ids,
        "first_origin": str(sample[0]["origin"]), "last_origin": str(sample[-1]["origin"]),
        "last_resolved_session": max(str(r.get("resolved_session")) for r in sample),
        "resolution_ids_sha256": _sha_ids(ids),
        "numpy_version": np.__version__,
        "coefficients_sha256": (contract.get("frozen_coefficients") or {}).get("sha256"),
        "contract_sha256": C.sha256_file(contract_path) if contract_path.is_file() else None,
        "arithmetic": {"block_length": C.BLOCK_LENGTH, "replicates": C.BOOTSTRAP_REPLICATES,
                       "seed": C.BOOTSTRAP_SEED, "interval": [5, 95], "null_draws": NULL_DRAWS,
                       "null_inner_replicates": NULL_BOOT_B, "null_threshold": 0.10},
        "verdict": _verdict_record(v, claim),
        "outcome": outcome, "effect": effect,
        "approval_receipt": receipt_id,
        "computed_at": computed_at, "git_head": _git_head(root),
        "notice": NOTICE,
    }
    row["content_hash"] = C.canonical_hash(row)
    return row


def _t7_row(scope: list[str], demoted: set[str], rows: list[dict[str, Any]], receipt_id: str, followups: list[str],
            root: Path, computed_at: str) -> dict[str, Any]:
    basis = [str(r["application_id"]) for r in rows
             if r.get("kind") == "checkpoint_verdict" and r.get("outcome") == "demotion_applied"
             and r.get("cell") in scope]
    row: dict[str, Any] = {
        "schema_version": 1, "application_id": "v13-apply:T7", "kind": "t7_termination",
        "scope_cells": list(scope), "demoted_cells": [c for c in scope if c in demoted],
        "basis_application_ids": basis, "effect": "card_hold", "followups": list(followups),
        "approval_receipt": receipt_id, "computed_at": computed_at, "git_head": _git_head(root),
        "notice": NOTICE,
    }
    row["content_hash"] = C.canonical_hash(row)
    return row


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("kind") == "t7_termination":
        return {"application_id": row["application_id"], "kind": row["kind"], "demoted_cells": row["demoted_cells"],
                "effect": row["effect"]}
    verdict = row.get("verdict") or {}
    return {"application_id": row["application_id"], "cell": row["cell"], "checkpoint": row["checkpoint"],
            "status": verdict.get("status"), "outcome": row["outcome"], "effect": row["effect"],
            "ci90": (verdict.get("paired_loss_vs_climatology") or {}).get("ci90"),
            "negative_control_pass_rate": verdict.get("negative_control_pass_rate")}


def apply_live_verdicts(root: Path, *, approval_receipt_id: str, dry_run: bool = False,
                        now: datetime | None = None) -> dict[str, Any]:
    """체크포인트 도달 셀의 계약 산술을 계산해 적용 원장에 append 한다(dry_run 이면 계산만)."""
    root = Path(root)
    contract = C.load_contract_v13(root)
    block = contract.get("live_verdict_application")
    if not isinstance(block, dict):
        raise TimeSeriesV13VolError("live_verdict_application not registered in the V13 contract")
    if not dry_run and running_in_ci():
        raise TimeSeriesV13VolError(
            "timeseries-v13-vol-apply-verdict writes only from an interactive human session "
            "(GITHUB_ACTIONS/CI detected) — use --dry-run or --verify-only")
    receipt = require_application_receipt(root, approval_receipt_id, contract, now=now)  # ← 여기까지 원장 0 읽기
    params = verdict_parameters(contract)
    checkpoints = block.get("checkpoints") or {}
    try:
        first, step = int(checkpoints["first"]), int(checkpoints["step"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TimeSeriesV13VolError("live_verdict_application.checkpoints first/step missing") from exc
    if first != params["minimum"]:
        raise TimeSeriesV13VolError("checkpoint first != live_forward_gate minimum_matured_origins_per_cell")
    scope = [c for c in C.CELL_ORDER if c in params["pass_cells"]]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    computed_at = current.astimezone(timezone.utc).isoformat(timespec="seconds")

    by_cell = _file_order_rows(root)
    existing = VL.read_applications(root)
    if existing["status"] != "ok":
        raise TimeSeriesV13VolError(f"application ledger unreadable — refusing to append: {existing['error']}")
    ids = set(existing["by_id"])
    demoted = set(existing["demoted"])
    planned: list[dict[str, Any]] = []
    for cell in scope:
        rows = by_cell.get(cell, [])
        for k in VL.checkpoint_schedule(len(rows), first=first, step=step):
            app_id = f"v13-apply:{cell}:k{k}"
            if app_id in ids:
                continue                                         # 멱등 — 재실행은 아무것도 쓰지 않는다
            sample = VL.checkpoint_sample(rows, k)
            v, claim = _evaluate_sample(sample, params)
            if cell in demoted:
                outcome, effect = AFTER_DEMOTION
            elif v["status"] in OUTCOME_BY_STATUS:
                outcome, effect = OUTCOME_BY_STATUS[v["status"]]
                if outcome == "demotion_applied":
                    demoted.add(cell)
            else:
                raise TimeSeriesV13VolError(f"unexpected status at checkpoint: {v['status']}")
            planned.append(_checkpoint_row(cell, k, sample, v, claim, outcome, effect, approval_receipt_id,
                                           contract, root, computed_at))
            ids.add(app_id)

    t7_block = block.get("t7") or {}
    followups = [str(f) for f in (t7_block.get("on_trigger_followups") or [])]
    combined = list(existing["rows"]) + planned
    have_first = {r["cell"] for r in combined if r.get("kind") == "checkpoint_verdict" and r.get("checkpoint") == first}
    t7_new = False
    if set(scope) <= have_first and len(demoted & set(scope)) >= 2 and existing["t7"] is None:
        planned.append(_t7_row(scope, demoted, combined, approval_receipt_id, followups, root, computed_at))
        t7_new = True

    written = 0
    if not dry_run:
        for row in planned:
            if append_unique(root, VL.APPLICATIONS_LEDGER_RELATIVE, row, key="application_id"):
                written += 1
    merged = {"status": "ok", "by_id": {**existing["by_id"], **{r["application_id"]: r for r in planned}}}
    matured = {cell: len(by_cell.get(cell, [])) for cell in scope}
    return {
        "dry_run": bool(dry_run), "written": written,
        "approval_receipt": receipt.get("receipt_id"),
        "planned": [_summary(r) for r in planned],
        "demoted_cells": [c for c in scope if c in demoted],
        "t7_applied": bool(existing["t7"] is not None or t7_new),
        "pending": VL.pending_checkpoints(matured, merged, scope, first=first, step=step),
        "matured": matured,
        "followups": followups if t7_new else [],
        "disclaimer": DISCLAIMER,
    }


def _major_minor(version: Any) -> tuple[str, ...]:
    return tuple(str(version or "").split(".")[:2])


def _close(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= RECOMPUTE_TOLERANCE
    except (TypeError, ValueError):
        return a is None and b is None


def verify_live_verdict_applications(root: Path) -> dict[str, Any]:
    """적용 원장 엄격 검증 — errors 가 있으면 ok=false. 호출 위치에 따라 종료코드 효과가 다르다(계약 verify)."""
    root = Path(root)
    errors: list[str] = []
    warnings: list[str] = []
    recompute = {"compared": 0, "skipped_numpy_version": 0}
    apps = VL.read_applications(root)
    if apps["status"] != "ok":
        return {"ok": False, "errors": [f"ledger unreadable: {apps['error']}"], "warnings": [], "rows": 0,
                "recompute": recompute}
    rows = apps["rows"]
    contract = C.load_contract_v13(root)
    block = contract.get("live_verdict_application")
    params = verdict_parameters(contract)
    if not isinstance(block, dict):
        if rows:
            errors.append("application rows exist but live_verdict_application is not registered")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "rows": len(rows), "recompute": recompute}
    checkpoints = block.get("checkpoints") or {}
    first = int(checkpoints.get("first") or VL.DEFAULT_FIRST)
    step = int(checkpoints.get("step") or VL.DEFAULT_STEP)
    scope = [c for c in C.CELL_ORDER if c in params["pass_cells"]]

    approvals = _approvals(root)
    by_receipt = {r.get("receipt_id"): r for r in approvals}
    revocations: dict[str, list[datetime]] = {}
    for r in approvals:
        if r.get("supersedes"):
            stamp = _parse_instant(r.get("approved_at"))
            if stamp is not None:
                revocations.setdefault(str(r["supersedes"]), []).append(stamp)

    resolution_rows = {str(r.get("resolution_id")): r for r in _read_rows(root / RESOLUTION_LEDGER_RELATIVE)}
    by_cell_now = _file_order_rows(root)
    current_np = np.__version__
    demoted_so_far: set[str] = set()
    seen_checkpoints: dict[str, list[int]] = {}
    for row in rows:
        app_id = str(row.get("application_id"))
        receipt = by_receipt.get(row.get("approval_receipt"))
        if receipt is None or receipt.get("decision_id") != DECISION_ID:
            errors.append(f"{app_id}: approval receipt missing or not V13-D15")
        else:
            computed = _parse_instant(row.get("computed_at"))
            for revoked_at in revocations.get(str(row.get("approval_receipt")), []):
                if computed is None or computed > revoked_at:
                    errors.append(f"{app_id}: computed after the approval receipt was superseded")
        if row.get("kind") != "checkpoint_verdict":
            continue
        cell = str(row.get("cell"))
        k = int(row.get("checkpoint") or 0)
        if cell not in scope:
            errors.append(f"{app_id}: cell outside publication.holdout_pass_cells")
            continue
        if k < first or (k - first) % step:
            errors.append(f"{app_id}: checkpoint {k} not in schedule ({first}+{step}n)")
        seen_checkpoints.setdefault(cell, []).append(k)
        origins = [str(o) for o in (row.get("origins") or [])]
        ids = [str(i) for i in (row.get("resolution_ids") or [])]
        if len(origins) != k or len(ids) != k:
            errors.append(f"{app_id}: origins/resolution_ids length != checkpoint")
        if origins != sorted(set(origins)) or len(origins) != len(set(origins)):
            errors.append(f"{app_id}: origins not strictly ascending/unique")
        if row.get("resolution_ids_sha256") != _sha_ids(ids):
            errors.append(f"{app_id}: resolution_ids_sha256 mismatch")
        missing = [i for i in ids if i not in resolution_rows]
        if missing:
            errors.append(f"{app_id}: {len(missing)} resolution_ids not in the resolution ledger")
        # 셀 소속 — 다른 셀의 해상 행(같은 원점)으로 바꿔 해시를 다시 맞춘 행은 origins 대조·재계산을 통과할 수 있다.
        foreign = [i for i in ids if i in resolution_rows and str(resolution_rows[i].get("cell")) != cell]
        if foreign:
            errors.append(f"{app_id}: {len(foreign)} resolution_ids belong to another cell")
        status = (row.get("verdict") or {}).get("status")
        expected = AFTER_DEMOTION if cell in demoted_so_far else OUTCOME_BY_STATUS.get(status)
        if expected is None or (row.get("outcome"), row.get("effect")) != expected:
            errors.append(f"{app_id}: outcome {row.get('outcome')} inconsistent with status {status}")
        if row.get("outcome") == "demotion_applied":
            demoted_so_far.add(cell)
        # 현재 dedupe 로 다시 고른 첫 기록 순 앞 k — append-only 라면 같아야 한다(다르면 손상 신호 경고)
        now_rows = by_cell_now.get(cell, [])
        if len(now_rows) >= k:
            rederived = {str(r["resolution_id"]) for r in now_rows[:k]}
            if rederived != set(ids):
                warnings.append(f"{app_id}: first-recorded k resolution_ids differ from the stored list")
        if missing or foreign or len(ids) != k:
            continue
        sample = sorted((resolution_rows[i] for i in ids), key=lambda r: str(r["origin"]))
        if [str(r["origin"]) for r in sample] != origins:
            errors.append(f"{app_id}: stored origins differ from the resolution rows")
        if _major_minor(row.get("numpy_version")) != _major_minor(current_np):
            recompute["skipped_numpy_version"] += 1
            warnings.append(f"recompute_skipped_numpy_version {app_id} {row.get('numpy_version')}->{current_np}")
            continue
        v, _claim = _evaluate_sample(sample, params)
        recompute["compared"] += 1
        stored = row.get("verdict") or {}
        if v["status"] != stored.get("status"):
            errors.append(f"{app_id}: recompute status {v['status']} != stored {stored.get('status')}")
            continue
        ci_new = (v.get("paired_loss_vs_climatology") or {})
        ci_old = (stored.get("paired_loss_vs_climatology") or {})
        pairs = [(ci_new.get("mean"), ci_old.get("mean")),
                 ((ci_new.get("ci90") or [None, None])[0], (ci_old.get("ci90") or [None, None])[0]),
                 ((ci_new.get("ci90") or [None, None])[1], (ci_old.get("ci90") or [None, None])[1]),
                 (v.get("negative_control_pass_rate"), stored.get("negative_control_pass_rate")),
                 (v.get("brier_model"), stored.get("brier_model")),
                 (v.get("brier_climatology"), stored.get("brier_climatology"))]
        if not all(_close(a, b) for a, b in pairs):
            errors.append(f"{app_id}: recompute numbers differ beyond {RECOMPUTE_TOLERANCE}")

    for cell, ks in seen_checkpoints.items():
        expected_prefix = list(range(first, first + step * len(ks), step))
        if sorted(ks) != expected_prefix:
            errors.append(f"{cell}: checkpoint rows are not a prefix of the schedule {sorted(ks)}")

    t7_rows = [r for r in rows if r.get("kind") == "t7_termination"]
    if len(t7_rows) > 1:
        errors.append("more than one t7_termination row")
    for t7 in t7_rows[:1]:
        t7_at = _parse_instant(t7.get("computed_at"))
        before = [r for r in rows if r.get("kind") == "checkpoint_verdict"
                  and (_parse_instant(r.get("computed_at")) or t7_at) <= (t7_at or datetime.max.replace(tzinfo=timezone.utc))]
        firsts = {r.get("cell") for r in before if r.get("checkpoint") == first}
        demoted_then = {r.get("cell") for r in before if r.get("outcome") == "demotion_applied"} & set(scope)
        if not set(scope) <= firsts:
            errors.append("t7_termination recorded before every scope cell had its first checkpoint row")
        if len(demoted_then) < 2:
            errors.append("t7_termination recorded with fewer than 2 demoted scope cells")

    try:
        from .resolve import matured_counts
        matured = matured_counts(root)
    except Exception:  # noqa: BLE001
        matured = {cell: len(by_cell_now.get(cell, [])) for cell in scope}
    for item in VL.pending_checkpoints(matured, apps, scope, first=first, step=step):
        if item.get("error"):
            warnings.append(str(item["error"]))
        else:
            warnings.append(f"{item['cell']} checkpoint {item['checkpoint']} reached (matured {item['matured']}) "
                            "— no application row")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "rows": len(rows), "recompute": recompute}
