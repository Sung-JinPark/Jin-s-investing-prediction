"""V13-VOL 홀드아웃(2015-2018) 1회 채점 — 비가역. 승인 원문 없이는 데이터를 읽기 전에 거부한다.

계약 `stopping_points.holdout` 이 절차·게이트를 전부 사전등록해 두었고(결과 전 커밋), 이 모듈은 그것을
**실행만** 한다. 새 규칙을 만들지 않는다.

정지점(V9 `timeseries_v9/pipeline.py` 패턴 승계):
  1. `holdout_execution_path` 가 named_verb_guarded 가 아니면 거부 — 계약 개정이 선행돼야 한다.
  2. 승인 영수증이 없거나 decision_id·finalist 가 어긋나면 거부 — **어떤 관측도 읽기 전에**.
  3. 같은 finalist 재소모·예산 초과 거부.
  4. 동결 계수 3자 핀(계약·파일 sha256·content_hash) 불일치 거부. 재적합 경로는 이 모듈에 존재하지 않는다.
  5. 패널은 observation_time <= 2018-12-31 로 절단 — 봉인창(2019+) 바이트를 열지 않는다.
  6. 퇴화·국면 가드를 **실행 시점에** 홀드아웃 창에 적용한다(사전 점검은 미열람 위반).
  7. 결과가 PASS 든 FAIL 이든 원장에 append 한다.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v2.market_archive import read_market_observations
from ..timeseries_v8.artifact import append_unique
from . import contracts as C
from . import features as F
from . import scoring as S

HISTORY_START = "2007-01-01"
RUNS_RELATIVE = Path("data/timeseries_v13/runs")
NULL_DRAWS = 200


class TimeSeriesV13HoldoutError(RuntimeError):
    """홀드아웃 소모의 사전 조건이 깨졌다 — 페일클로즈."""


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=root, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _require_named_verb(contract: dict[str, Any]) -> None:
    protocol = contract.get("development_protocol") or {}
    if protocol.get("holdout_execution_path") != "named_verb_guarded":
        raise TimeSeriesV13HoldoutError(
            "holdout consumption requires the contract to be amended first "
            "(holdout_execution_path is still absent_by_construction)")


def _require_approval(root: Path, receipt_id: str, finalist_id: str) -> dict[str, Any]:
    """★ 정지점: 승인 원문 없이는 어떤 관측도 읽지 않는다."""
    if not str(receipt_id or "").strip():
        raise TimeSeriesV13HoldoutError(
            "holdout consumption requires an explicit user-approval receipt "
            "(automatic_holdout_consumption is prohibited by contract)")
    receipts = [r for r in _rows(root / C.APPROVALS_LEDGER_RELATIVE)
                if r.get("receipt_id") == receipt_id]
    if not receipts:
        raise TimeSeriesV13HoldoutError(f"approval receipt not found: {receipt_id}")
    receipt = receipts[-1]
    if receipt.get("decision_id") != "V13-D3":
        raise TimeSeriesV13HoldoutError("approval receipt is not a V13-D3 holdout approval")
    if not str(receipt.get("approval_text") or "").strip():
        raise TimeSeriesV13HoldoutError("approval receipt carries no verbatim approval text")
    text = str(receipt["approval_text"])
    if "V13-D3" not in text or finalist_id not in text:
        raise TimeSeriesV13HoldoutError(
            "approval text must name V13-D3 and the exact finalist_id")
    if (receipt.get("approval_scope") or {}).get("holdout_single_scoring") is not True:
        raise TimeSeriesV13HoldoutError("approval scope does not cover holdout scoring")
    if (receipt.get("semantic_reference") or {}).get("finalist_id") != finalist_id:
        raise TimeSeriesV13HoldoutError("approval receipt finalist does not match the contract champion")
    return receipt


def _require_budget(root: Path, protocol: dict[str, Any], finalist_id: str) -> None:
    rows = _rows(root / C.HOLDOUT_LEDGER_RELATIVE)
    if any(row.get("finalist_id") == finalist_id for row in rows):
        raise TimeSeriesV13HoldoutError(f"this finalist already consumed its holdout scoring: {finalist_id}")
    maximum = int(protocol.get("holdout_maximum_finalists") or 0)
    if len({row.get("finalist_id") for row in rows}) >= maximum:
        raise TimeSeriesV13HoldoutError("holdout finalist budget is exhausted")
    registered = protocol.get("holdout_finalists_preregistered") or []
    if not any(str(finalist_id).startswith(str(name)) for name in registered):
        raise TimeSeriesV13HoldoutError(f"finalist is not pre-registered: {finalist_id}")


def _feature_matrix(cell: dict[str, Any], level: np.ndarray, smooth: np.ndarray) -> np.ndarray:
    return F.feature_matrix(cell["model"], level, smooth)


def _predict(cell: dict[str, Any], X: np.ndarray) -> np.ndarray:
    """동결 계수로만 예측한다 — 이 모듈에 적합 함수는 없다."""
    p = F.logit_predict(np.asarray(cell["beta"], float), np.asarray(cell["mu"], float),
                        np.asarray(cell["sd"], float), X)
    if cell.get("iso_map"):
        p = F.pav_apply(cell["iso_map"], p)
    return np.asarray(p, float)


def score_holdout(root: Path, *, approval_receipt_id: str,
                  knowledge_cutoff: str | None = None) -> dict[str, Any]:
    contract = C.load_contract_v13(root)
    protocol = contract.get("development_protocol") or {}
    champion = (contract.get("gates") or {}).get("champion") or {}
    finalist_id = str(champion.get("finalist_id") or "")
    if not finalist_id or not champion.get("cells"):
        raise TimeSeriesV13HoldoutError("champion is not fixed — nothing to score")

    _require_named_verb(contract)
    receipt = _require_approval(root, approval_receipt_id, finalist_id)
    _require_budget(root, protocol, finalist_id)

    frozen_cfg = contract.get("frozen_coefficients") or {}
    frozen = C.load_frozen_coefficients(
        root, expected_sha256=frozen_cfg.get("sha256"),
        expected_content_hash=frozen_cfg.get("content_hash"),
        expected_finalist_id=frozen_cfg.get("finalist_id"))

    guard_rules = ((contract.get("degeneracy_guard") or {}).get("rules") or {})
    min_events = int(guard_rules.get("min_events_per_half_per_class") or 20)
    min_episodes = int(guard_rules.get("min_episodes_per_half_per_class") or 5)
    holdout_start, holdout_end = contract["stopping_points"]["holdout"]["window"]
    clim_fixed = {name: float(cell["clim_base_rate"]) for name, cell in frozen["cells"].items()}

    # 패널은 홀드아웃 끝에서 절단한다 — 봉인창 바이트 미열람.
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    panel = F.build_panel(read_market_observations(root, knowledge_cutoff=cutoff),
                          start=HISTORY_START, end=holdout_end)
    dates = [str(d) for d in panel["dates"]]
    vix = panel["vix"]
    rv_filled = F.fill_rv_nan(panel["rv21"], frozen["rv_nan_fill_median"])
    vix_ewma = F.ewma(vix, frozen["alpha_ewma"])
    rv_ewma = F.ewma(rv_filled, frozen["alpha_ewma"])
    in_window = np.array([holdout_start <= d <= holdout_end for d in dates])

    cells_out: dict[str, Any] = {}
    for spec in C.cell_specs():
        name = spec["name"]
        cell = frozen["cells"].get(name)
        if cell is None:
            continue
        if spec["target"] == "vix_touch":
            y = F.labels_vix(vix, spec["K"], spec["h"])
            level, smooth = vix, vix_ewma
        else:
            y = F.labels_rv(panel["rv21"], spec["theta"], spec["h"])
            level, smooth = rv_filled, rv_ewma
        mask = in_window & np.isfinite(y)          # label-complete origins only
        y_window = np.where(mask, y, np.nan)
        guard = S.degeneracy_report(y_window, min_events=min_events, min_episodes=min_episodes)
        record: dict[str, Any] = {"model": cell["model"], "h": spec["h"], "guard": guard,
                                  "origins": int(mask.sum()),
                                  "first_origin": next((d for d, m in zip(dates, mask) if m), None),
                                  "last_origin": next((d for d, m in zip(reversed(dates), reversed(mask.tolist())) if m), None)}
        if guard["verdict"] == "untestable_by_construction":
            record["verdict"] = "untestable_by_construction"
            cells_out[name] = record
            continue

        yv = y[mask].astype(float)
        p = _predict(cell, _feature_matrix(cell, level, smooth)[mask])
        base = np.full(yv.shape, clim_fixed[name])
        g1 = S.paired_brier_ci(base, p, yv)
        record["G1_vs_climatology"] = g1
        record["bss_vs_climatology"] = S.brier_skill_score(p, yv, clim_fixed[name])
        record["reliability"] = S.murphy_reliability(p, yv)     # G3 보고 의무

        if cell["model"] == "persistence_pb":
            record["G2_not_inferior_to_pb"] = {"identity": True, "upper_ge_zero": True,
                                               "note": "champion 이 PB 이므로 항등 통과 (계약 G2)"}
            g2_ok = True
        else:
            pb = cell.get("baseline_pb")
            if not pb:
                raise TimeSeriesV13HoldoutError(f"cell {name} lacks a frozen PB baseline for G2")
            pb_cell = {**pb, "model": "persistence_pb", "iso_map": None}
            p_pb = _predict(pb_cell, F.feature_matrix("persistence_pb", level, None)[mask])
            g2 = S.paired_brier_ci(p_pb, p, yv)
            record["G2_not_inferior_to_pb"] = g2
            g2_ok = bool(g2["upper_ge_zero"])

        def _decide(perm: np.ndarray, _p=p, _base=clim_fixed[name]) -> bool:
            d = ((_base - perm) ** 2) - ((_p - perm) ** 2)
            return bool(S.block_boot_ci(d, b=300)["ci90"][0] > 0)

        null_rate = S.y_block_null_pass_rate(yv, _decide, draws=NULL_DRAWS, seed=C.BOOTSTRAP_SEED)
        record["G4_negative_control_pass_rate"] = null_rate
        g1_ok = bool(g1["lower_gt_zero"])
        g4_ok = bool(null_rate <= 0.10)
        passed = g1_ok and g2_ok and g4_ok
        record.update({"G1_pass": g1_ok, "G2_pass": g2_ok, "G4_pass": g4_ok,
                       "verdict": ("pass_but_episode_thin" if passed and guard["verdict"] == "episode_thin"
                                   else ("pass" if passed else "fail"))})
        cells_out[name] = record

    scored = {k: v for k, v in cells_out.items() if v["verdict"] != "untestable_by_construction"}
    pass_cells = sorted(k for k, v in scored.items() if v["verdict"].startswith("pass"))
    thin_cells = sorted(k for k, v in scored.items() if v["verdict"] == "pass_but_episode_thin")
    wiring_eligible = sorted(set(pass_cells) - set(thin_cells))
    family_p = S.family_p_binomial(len(pass_cells), len(scored)) if scored else None
    if not pass_cells:
        status = "fail"
    elif len(pass_cells) == len(scored) and len(scored) == len(cells_out):
        status = "pass"
    else:
        status = "partial"

    row = {
        "schema_version": 1, "finalist_id": finalist_id,
        "experiment_label": "V13VOL_holdout", "window_role": "holdout",
        "window": [holdout_start, holdout_end],
        "panel_truncated_at": holdout_end, "sealed_bytes_read": False,
        "coefficients_sha256": frozen_cfg.get("sha256"),
        "contract_status": (contract.get("publication") or {}).get("display_tier"),
        "approval_receipt_id": approval_receipt_id,
        "holdout_user_approval": receipt.get("approval_text"),
        "degeneracy_guard": {"min_events": min_events, "min_episodes": min_episodes},
        "cells": cells_out,
        "pass_cells": pass_cells, "episode_thin_pass_cells": thin_cells,
        "wiring_eligible_cells": wiring_eligible,
        "fail_cells": sorted(k for k, v in scored.items() if v["verdict"] == "fail"),
        "untestable_cells": sorted(k for k, v in cells_out.items()
                                   if v["verdict"] == "untestable_by_construction"),
        "family_p_binomial": family_p, "status": status,
        "knowledge_cutoff": cutoff, "git_head": _git_head(root),
    }
    row["content_hash"] = C.canonical_hash(row)
    append_unique(root, C.HOLDOUT_LEDGER_RELATIVE, row, key="finalist_id")   # 결과 무관 append
    runs = root / RUNS_RELATIVE
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"holdout_{finalist_id}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    return row


def verify_holdout(root: Path) -> dict[str, Any]:
    """홀드아웃 원장의 해시·승인·예산 규율 검증."""
    errors: list[str] = []
    contract = C.load_contract_v13(root)
    protocol = contract.get("development_protocol") or {}
    rows = _rows(root / C.HOLDOUT_LEDGER_RELATIVE)
    receipts = {r.get("receipt_id") for r in _rows(root / C.APPROVALS_LEDGER_RELATIVE)}
    for row in rows:
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if C.canonical_hash(body) != row.get("content_hash"):
            errors.append(f"holdout row hash mismatch: {row.get('finalist_id')}")
        if not str(row.get("holdout_user_approval") or "").strip():
            errors.append(f"holdout row without a user approval string: {row.get('finalist_id')}")
        if row.get("approval_receipt_id") not in receipts:
            errors.append(f"holdout row references an unknown receipt: {row.get('finalist_id')}")
        if row.get("sealed_bytes_read") is not False:
            errors.append("holdout row does not assert sealed bytes were untouched")
    if len({row.get("finalist_id") for row in rows}) > int(protocol.get("holdout_maximum_finalists") or 0):
        errors.append("holdout finalist budget exceeded")
    return {"ok": not errors, "errors": errors, "holdout_scorings": len(rows)}
