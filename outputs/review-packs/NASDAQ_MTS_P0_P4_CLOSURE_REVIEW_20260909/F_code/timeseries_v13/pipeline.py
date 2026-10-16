"""V13-VOL 라이브 발행 — 동결 계수로 최신 관측의 9셀 기준율을 산출해 커밋 포인터 + append-only 원장에 기록한다.

fail-closed: 계약 미무장 · 계수 핀 불일치 · 신선도 미달 중 하나라도 있으면 status=hold 포인터(숫자 없음).
재적합 없음(holdout_refit·refit_prohibited). 봉인 market_archive 는 read-only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v2.market_archive import read_market_observations
from ..timeseries_v8.artifact import append_unique
from . import contracts as C
from . import features as F
from .freshness import freshness_report

HISTORY_START = "2007-01-01"


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def compute_cells(frozen: dict[str, Any], panel: dict[str, np.ndarray],
                  *, episode_thin: Any = None) -> tuple[dict[str, Any], dict[str, float]]:
    """전체 이력 패널의 마지막 행에 대해 셀별 (p, se, band80). EWMA 는 전체 이력에 연속 실행."""
    vix, rv = panel["vix"], panel["rv21"]
    vix_ewma = F.ewma(vix, frozen["alpha_ewma"])
    rv_f = F.fill_rv_nan(rv, frozen["rv_nan_fill_median"])
    rv_ewma = F.ewma(rv_f, frozen["alpha_ewma"])
    inputs = {"vix_close": float(vix[-1]), "vix_close_ewma21": float(vix_ewma[-1]),
              "rv21_ann": float(rv_f[-1]), "rv21_ann_ewma21": float(rv_ewma[-1])}
    thin = set(episode_thin or ())
    cells: dict[str, Any] = {}
    for name in C.CELL_ORDER:
        cell = frozen["cells"].get(name)
        if cell is None:
            continue
        x_row = np.array([inputs[key] for key in cell["feature_names"]], float)
        p_raw, se_raw = F.delta_method_se(np.asarray(cell["beta"], float), np.asarray(cell["cov_beta"], float),
                                          np.asarray(cell["mu"], float), np.asarray(cell["sd"], float), x_row)
        lo = max(0.0, p_raw - C.Z80 * se_raw); hi = min(1.0, p_raw + C.Z80 * se_raw)
        p = p_raw
        if cell.get("iso_map"):
            p = float(F.pav_apply(cell["iso_map"], p_raw)[0])
            lo = float(F.pav_apply(cell["iso_map"], lo)[0]); hi = float(F.pav_apply(cell["iso_map"], hi)[0])
            lo, hi = min(lo, p), max(hi, p)
        cells[name] = {
            "model": cell["model"], "target": cell["target"], "h": cell["h"],
            **({"K": cell["K"]} if cell["target"] == "vix_touch" else {"theta": cell["theta"]}),
            "p": round(p, 6), "p_raw": round(p_raw, 6), "se_raw": round(se_raw, 6),
            "band80": [round(lo, 6), round(hi, 6)], "derived_layer": cell.get("derived_layer", "raw"),
            "clim_base_rate": round(float(cell["clim_base_rate"]), 6),
            "reliability": "weak" if cell["h"] == 63 else "good",
            # degeneracy_guard(설계창 실측): 국면 표본이 얇은 셀 — 숫자는 싣되 해석 경고를 붙인다
            "episode_sample": "thin" if name in thin else "ok",
        }
    return cells, inputs


def _pointer_body(*, status: str, as_of: str | None, knowledge_cutoff: str, gate: dict[str, Any],
                  freshness: dict[str, Any], frozen_pin: dict[str, Any], holdout_status: str,
                  inputs: dict[str, float] | None, cells: dict[str, Any] | None) -> dict[str, Any]:
    live = status == "live"
    body: dict[str, Any] = {
        "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION,
        "status": status, "as_of": as_of, "knowledge_cutoff": knowledge_cutoff,
        "probability_unit": "fraction", "probability_space": C.PROBABILITY_SPACE,
        "coefficients": frozen_pin, "gate": gate, "freshness": freshness,
        "publication": {"customer_numbers_visible": live, "reference_opinion_only": True,
                        "combined_with_official_forecasts": False, "combined_with_scenario_v5_2": False,
                        "combined_with_timeseries_v8": False, "trading_signal": False,
                        "holdout_status": holdout_status},
        "footnote": ("설계창(2007-2014) 스킬 · 홀드아웃 " + ("통과" if holdout_status == "pass" else "미검증")
                     + " · 참고 의견 — 매매 신호 아님. 80% 대역은 계수 불확실성(델타법)이며 보정 대역이 아니다."),
    }
    if live:
        body["inputs"] = inputs
        body["cells"] = cells
    body["content_hash"] = C.canonical_hash(body)
    return body


def publish_latest_timeseries_v13_vol(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    contract = C.load_contract_v13(root)
    gates = contract.get("gates") or {}
    live_display = contract.get("live_display") or {}
    frozen_cfg = contract.get("frozen_coefficients") or {}
    holdout_status = str((contract.get("publication") or {}).get("holdout_status") or "not_consumed")
    reasons: list[str] = []
    armed = gates.get("armed") is True
    if not armed:
        reasons.append("gates_not_armed (V13-D4 pending)")
    frozen: dict[str, Any] | None = None
    try:
        frozen = C.load_frozen_coefficients(root, expected_sha256=frozen_cfg.get("sha256"),
                                            expected_content_hash=frozen_cfg.get("content_hash"),
                                            expected_finalist_id=frozen_cfg.get("finalist_id"))
    except C.TimeSeriesV13VolError as exc:
        reasons.append(f"coefficients_not_pinned: {exc}")
    design_pass = bool(frozen and frozen["cells"]
                       and all(c["gate_evidence"]["design_pass"] is True for c in frozen["cells"].values())
                       and frozen["reconciliation"]["pass"] is True)
    if frozen and not design_pass:
        reasons.append("design_gate_evidence_incomplete")

    panel = F.build_panel(read_market_observations(root, knowledge_cutoff=knowledge_cutoff), start=HISTORY_START)
    as_of = str(panel["dates"][-1]) if len(panel["dates"]) else None
    max_missing = int((live_display.get("freshness") or {}).get("max_missing_sessions", 1))
    freshness = freshness_report(root, as_of, current, max_missing_sessions=max_missing)
    if freshness["status"] != "fresh":
        reasons.append(f"stale: missing_sessions={freshness['missing_sessions']} > {max_missing}")

    gate = {"design_gate_pass": design_pass, "armed": armed, "coefficients_pinned": frozen is not None,
            "freshness_pass": freshness["status"] == "fresh", "holdout_status": holdout_status,
            "reasons": reasons}
    status = "live" if not reasons else "hold"
    inputs = cells = None
    if status == "live":
        thin = (live_display.get("episode_thin_cells") or [])
        cells, inputs = compute_cells(frozen, panel, episode_thin=thin)  # type: ignore[arg-type]
    pin = {"path": str(C.COEFFICIENTS_RELATIVE.as_posix()), "sha256": frozen_cfg.get("sha256"),
           "content_hash": frozen_cfg.get("content_hash"), "finalist_id": frozen_cfg.get("finalist_id")}
    body = _pointer_body(status=status, as_of=as_of, knowledge_cutoff=knowledge_cutoff, gate=gate,
                         freshness=freshness, frozen_pin=pin, holdout_status=holdout_status,
                         inputs=inputs, cells=cells)
    pointer = root / C.LATEST_RELATIVE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    tmp = pointer.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(tmp, pointer)

    appended = False
    if status == "live":
        # run_id 는 (as_of, 계수 sha 앞 8자) — 같은 관측·같은 계수의 재실행은 한 행(멱등), 재동결은 새 행(이력 보존).
        run_id = f"v13vol-{as_of}-{str(pin['sha256'])[:8]}"
        existing = {row.get("run_id") for row in _read_rows(root / C.LIVE_LEDGER_RELATIVE)}
        if run_id not in existing:
            row = {"schema_version": 1, "run_id": run_id, "as_of": as_of, "knowledge_cutoff": knowledge_cutoff,
                   "model_id": C.MODEL_ID, "finalist_id": pin["finalist_id"], "coefficients_sha256": pin["sha256"],
                   "inputs": inputs, "cells": {k: {"p": v["p"], "band80": v["band80"], "model": v["model"]}
                                               for k, v in (cells or {}).items()},
                   "pointer_content_hash": body["content_hash"], "holdout_status": holdout_status}
            row["content_hash"] = C.canonical_hash(row)
            appended = append_unique(root, C.LIVE_LEDGER_RELATIVE, row, key="run_id")
    return {"status": status, "as_of": as_of, "customer_numbers_visible": status == "live",
            "reasons": reasons, "ledger_appended": appended, "content_hash": body["content_hash"]}


def verify_timeseries_v13_vol(root: Path) -> dict[str, Any]:
    """포인터·원장·계수 핀의 정합 + 아카이브 재계산 대사 (abs diff < 1e-9)."""
    from ..timeseries_v13_vol_display import validate_latest  # 표시 모듈의 fail-closed 검증 재사용

    errors: list[str] = []
    contract = C.load_contract_v13(root)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    pointer = root / C.LATEST_RELATIVE
    if not pointer.is_file():
        return {"ok": False, "errors": ["pointer missing"]}
    latest = json.loads(pointer.read_text(encoding="utf-8"))
    try:
        validate_latest(latest)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pointer invalid: {exc}")
    rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    seen: set[str] = set()
    for row in rows:
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if C.canonical_hash(body) != row.get("content_hash"):
            errors.append(f"ledger row hash mismatch: {row.get('run_id')}")
        if row.get("run_id") in seen:
            errors.append(f"ledger duplicate run_id: {row.get('run_id')}")
        seen.add(str(row.get("run_id")))
    if latest.get("status") == "live":
        pointer_sha = (latest.get("coefficients") or {}).get("sha256")
        # 포인터 ↔ 원장 교차검사: 같은 as_of·같은 계수의 행이 정확히 1개 있고 셀(p·band80)이 일치해야 한다
        # (포인터는 재실행마다 knowledge_cutoff 가 바뀌어 다시 써지므로 해시가 아니라 내용을 대조한다).
        matching = [row for row in rows if row.get("as_of") == latest.get("as_of")
                    and row.get("coefficients_sha256") == pointer_sha]
        if len(matching) != 1:
            errors.append(f"ledger has {len(matching)} rows for pointer as_of/coefficients (expected 1)")
        else:
            for name, cell in (latest.get("cells") or {}).items():
                recorded = (matching[0].get("cells") or {}).get(name) or {}
                if recorded.get("p") != cell.get("p") or recorded.get("band80") != cell.get("band80"):
                    errors.append(f"ledger/pointer cell mismatch: {name}")
        try:
            frozen = C.load_frozen_coefficients(root, expected_sha256=frozen_cfg.get("sha256"),
                                                expected_content_hash=frozen_cfg.get("content_hash"),
                                                expected_finalist_id=frozen_cfg.get("finalist_id"))
            panel = F.build_panel(read_market_observations(root, knowledge_cutoff=latest["knowledge_cutoff"]),
                                  start=HISTORY_START)
            if str(panel["dates"][-1]) != latest["as_of"]:
                errors.append("as_of drifted from archive at the recorded knowledge cutoff")
            cells, _ = compute_cells(frozen, panel)
            for name, cell in cells.items():
                if abs(cell["p"] - float(latest["cells"][name]["p"])) > 1e-9:
                    errors.append(f"cell {name} recompute mismatch")
        except C.TimeSeriesV13VolError as exc:
            errors.append(f"coefficients: {exc}")
    return {"ok": not errors, "errors": errors, "rows": len(rows), "status": latest.get("status")}
