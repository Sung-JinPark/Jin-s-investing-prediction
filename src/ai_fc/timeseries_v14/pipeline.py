"""V14 조건부 전이 라이브 발행 — 동결 계수로 최신 관측의 6셀 조건부 확률을 포인터 + append-only 원장에 기록한다.

모형: conditional_persistence_pb — 셀별 로짓(절편 + 표준화 당일 수준 1피처: cvix 셀 VIX_t · crv 셀 RV21_t).
p 는 **조건 충족 원점에서만** 낸다(cvix: VIX_t < 20 엄격 · crv: RV21_t 유한 ∧ <= θ). 조건 불충족 원점은 포인터·원장에
condition_met=false · p=null 로 기록되며 채점 표본이 아니다(계약 live_forward_gate.scoring). 80% 대역은 없다.

fail-closed(status=hold, 숫자 없음, 원장 무기록): 승인 영수증(V14-D10) 부재 · 계수 핀 null/불일치 · 계약 분할과 동결 역할
불일치 · 신선도 미달. 재적합 없음. 봉인 market_archive 는 read-only.

원점 백필(계약 live_pointer.origin_backfill) — V13 기계(V13-D12)를 그대로 승계한다: effective_from 이후·포인터 as_of 이전
거래일 중 **어떤 계수 sha 로도 행이 없는** 원점을, 그 원점 관측의 첫 vintage available_at 으로 되감은 cutoff 로 읽고
원점에서 절단한 패널(end=origin)로 계산해 pit_grade=late_capture 행으로 쓴다. 첫 vintage 색인·cutoff 계산은 V13 함수를
import 한다(_first_capture_index · _backfill_cutoff). 기계적·무조건 — 결과를 보고 쓰거나 빼는 경로가 없다.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..forecast_refresh import _v13_semantics as _pointer_semantics   # 시계(knowledge_cutoff·evaluated_at)만 빼는 비교
# 개정(revision_seq>1) 포함 전량(dedupe 전) — 원점의 **첫** vintage available_at 을 찾는 데만 쓴다. 봉인 모듈 read-only.
from ..timeseries_v2.market_archive import _current_facts as read_market_facts
from ..timeseries_v2.market_archive import read_market_observations
from ..timeseries_v8.artifact import append_unique
from ..timeseries_v13 import features as F
from ..timeseries_v13.freshness import freshness_report
from ..timeseries_v13.pipeline import _backfill_cutoff, _first_capture_index
from . import contracts as C

BACKFILL_SERIES = ("VIX", "NASDAQCOM")      # 계약 data_policy.series 가 없을 때의 기본값
FOOTNOTE = ("조건부 확률 — 조건 충족 원점(VIX<20 · RV21<=θ)에서만 p. 설계창(2007-2014) 적합 · 홀드아웃 없음 · "
            "라이브 전진 판정 전 · 참고 의견, 매매 신호 아님. V13 무조건부 확률과 다른 probability space — 산술 결합·직접 비교 금지.")


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


# ── 셀 정의 (조건·피처·라벨) — 동결 도구·발행·채점이 같은 함수를 쓴다 ─────────────────────
def condition_mask(spec: dict[str, Any], vix: np.ndarray, rv: np.ndarray) -> np.ndarray:
    """조건 충족 원점 마스크. cvix: VIX_t < 20 (엄격) · crv: RV21_t 유한 ∧ <= θ (NaN 원점은 부분집합 밖)."""
    vix = np.asarray(vix, float); rv = np.asarray(rv, float)
    if spec["target"] == "vix_conditional":
        return np.isfinite(vix) & (vix < spec["cond_lt"])
    return np.isfinite(rv) & (rv <= spec["theta"])


def level_series(spec: dict[str, Any], vix: np.ndarray, rv: np.ndarray) -> np.ndarray:
    """조건부 PB 피처 = 당일 수준(원값). 조건 충족 원점에서는 유한하므로 NaN 채움이 필요 없다."""
    return np.asarray(vix if spec["target"] == "vix_conditional" else rv, float)


def labels_for(spec: dict[str, Any], vix: np.ndarray, rv: np.ndarray) -> np.ndarray:
    """전체 패널 라벨(미래창 i+1..i+h) — V13 공유 라벨러. cvix: VIX >= 25 터치 · crv: RV21 > θ(유한값만)."""
    if spec["target"] == "vix_conditional":
        return F.labels_vix(np.asarray(vix, float), spec["K"], spec["h"])
    return F.labels_rv(np.asarray(rv, float), spec["theta"], spec["h"])


def build_live_panel(root: Path, *, knowledge_cutoff: str, end: str | None = None) -> dict[str, np.ndarray]:
    """라이브 창 패널 — 아카이브 꼬리(LIVE_PANEL_START 이후)만, available_at <= knowledge_cutoff."""
    return F.build_panel(read_market_observations(root, knowledge_cutoff=knowledge_cutoff),
                         start=C.LIVE_PANEL_START, end=end)


def compute_cells(frozen: dict[str, Any], panel: dict[str, np.ndarray],
                  roles: dict[str, str]) -> tuple[dict[str, Any], dict[str, float | None]]:
    """패널 마지막 행에 대해 셀별 {condition_met, level, p(조건 충족일 때만), clim_base_rate, role}."""
    vix_t = float(panel["vix"][-1]); rv_t = float(panel["rv21"][-1])
    inputs = {"vix_close": _finite_or_none(vix_t), "rv21_ann": _finite_or_none(rv_t)}
    cells: dict[str, Any] = {}
    for spec in C.cell_specs():
        name = spec["name"]
        cell = frozen["cells"][name]
        level = vix_t if spec["target"] == "vix_conditional" else rv_t
        met = bool(condition_mask(spec, np.array([vix_t]), np.array([rv_t]))[0])
        p: float | None = None
        if met:
            raw = F.logit_predict(np.asarray(cell["beta"], float), np.asarray(cell["mu"], float),
                                  np.asarray(cell["sd"], float), np.array([[level]], float))
            p = round(float(raw[0]), 6)
        cells[name] = {
            "model": C.MODEL_NAME, "target": spec["target"], "h": spec["h"],
            **({"K": spec["K"]} if spec["target"] == "vix_conditional" else {"theta": spec["theta"]}),
            "condition": spec["condition"], "condition_met": met, "level": _finite_or_none(level), "p": p,
            "clim_base_rate": float(cell["clim_base_rate"]), "role": roles[name],
        }
    return cells, inputs


def _publication(display_tier: str) -> dict[str, Any]:
    return {"display_tier": display_tier, "customer_numbers_visible": False, "shadow_cells_displayable": False,
            "reference_opinion_only": True, "trading_signal": False,
            "combined_with_official_forecasts": False, "combined_with_timeseries_v13": False,
            "combined_with_timeseries_v8": False, "combined_with_scenario_v5_2": False,
            "holdout_status": "not_applicable_live_forward"}


def _pointer_body(*, status: str, as_of: str | None, knowledge_cutoff: str, gate: dict[str, Any],
                  freshness: dict[str, Any], pin: dict[str, Any], cfg: dict[str, Any],
                  inputs: dict[str, Any] | None, cells: dict[str, Any] | None,
                  backfill: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "model": C.MODEL_NAME,
        "status": status, "as_of": as_of, "knowledge_cutoff": knowledge_cutoff,
        "probability_unit": "fraction", "probability_space": C.PROBABILITY_SPACE,
        "coefficients": pin, "gate": gate, "freshness": freshness,
        # 판정 범위는 champion_cells 뿐 — shadow 는 기록·채점되지만 강등·T7·승격 주장 밖이며 표시되지 않는다.
        "scope": {"champion_cells": list(cfg["champion_cells"]), "shadow_cells": list(cfg["shadow_cells"]),
                  "verdict_scope": "champion_cells", "shadow_in_verdict_scope": False,
                  "approval_receipt": cfg["approval_receipt"]},
        "publication": _publication(cfg["display_tier"]),
        "footnote": FOOTNOTE,
    }
    if status == "live":
        body["inputs"] = inputs
        body["cells"] = cells
    if backfill is not None:
        body["backfill"] = backfill
    body["content_hash"] = C.canonical_hash(body)
    return body


def _run_id(as_of: str, sha: str) -> str:
    return f"v14cond-{as_of}-{str(sha)[:8]}"


def _ledger_row(*, as_of: str, knowledge_cutoff: str, pin: dict[str, Any], inputs: dict[str, Any] | None,
                cells: dict[str, Any] | None, display_tier: str) -> dict[str, Any]:
    """원장 행 공통 본문 — pointer_content_hash·content_hash(·백필 필드)는 호출부가 뒤에 채운다.

    run_id 는 (as_of, 계수 sha 앞 8자) — 같은 관측·같은 계수의 재실행은 한 행(멱등), 재동결은 새 행(이력 보존).
    """
    return {"schema_version": 1, "run_id": _run_id(as_of, pin["sha256"]), "as_of": as_of,
            "knowledge_cutoff": knowledge_cutoff, "model_id": C.MODEL_ID, "model": C.MODEL_NAME,
            "coefficients_sha256": pin["sha256"], "coefficients_content_hash": pin["content_hash"],
            "inputs": inputs, "display_tier": display_tier,
            "cells": {k: {"condition_met": v["condition_met"], "p": v["p"], "level": v["level"], "role": v["role"],
                          "clim_base_rate": v["clim_base_rate"]} for k, v in (cells or {}).items()}}


# ── 원점 백필 (V13-D12 기계 승계) ───────────────────────────────────────────
def _origin_panel(root: Path, *, origin: str, cutoff: str) -> dict[str, np.ndarray]:
    """되감은 cutoff 로 읽고 원점에서 절단한 패널(end=origin) — V13 _origin_panel 과 같은 규칙, V14 라이브 창."""
    return build_live_panel(root, knowledge_cutoff=cutoff, end=origin)


def _rolled_back(root: Path, *, origin: str, first_capture: dict[tuple[str, str], str],
                 series: tuple[str, ...]) -> tuple[str | None, dict[str, np.ndarray] | None, str | None]:
    """(cutoff_used, 절단 패널, unfillable 사유) — 사유가 None 일 때만 채울 수 있다. 발행과 verify 가 같은 함수를 쓴다."""
    cutoff = _backfill_cutoff(first_capture, origin, series)
    if cutoff is None:
        return None, None, "no_observation"
    back = _origin_panel(root, origin=origin, cutoff=cutoff)
    if not len(back["dates"]) or str(back["dates"][-1]) != origin:
        return cutoff, back, "as_of_drift"
    return cutoff, back, None


def _series_of(contract: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(s) for s in ((contract.get("data_policy") or {}).get("series") or BACKFILL_SERIES))


def _prepare_backfill(root: Path, *, effective_from: str, panel: dict[str, np.ndarray], as_of: str,
                      knowledge_cutoff: str, pin: dict[str, Any], ledger_rows: list[dict[str, Any]],
                      frozen: dict[str, Any], roles: dict[str, str], display_tier: str,
                      series: tuple[str, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """effective_from 이후·as_of 이전 패널 거래일 중 **어떤 계수 sha 로도 행이 없는** 원점 전부(forward_only).

    반환: (쓸 행[원점 오름차순 — pointer_content_hash·captured_by_run·content_hash 는 호출부가 채움], unfillable).
    """
    dates = [str(d) for d in panel["dates"]]
    have = {str(row.get("as_of")) for row in ledger_rows}
    candidates = [d for d in dates if effective_from <= d < as_of and d not in have]
    pending: list[dict[str, Any]] = []
    unfillable: list[dict[str, Any]] = []
    if not candidates:
        return pending, unfillable
    first_capture = _first_capture_index(read_market_facts(root), series)
    for origin in candidates:
        cutoff_used, back, reason = _rolled_back(root, origin=origin, first_capture=first_capture, series=series)
        if reason is not None or back is None or cutoff_used is None:
            unfillable.append({"origin": origin, "reason": reason or "as_of_drift"})
            continue
        cells, inputs = compute_cells(frozen, back, roles)
        row = _ledger_row(as_of=origin, knowledge_cutoff=knowledge_cutoff, pin=pin, inputs=inputs, cells=cells,
                          display_tier=display_tier)
        row.update({"pit_grade": C.LATE_CAPTURE, "backfill_cutoff_used": cutoff_used,
                    "late_capture_sessions": dates.index(as_of) - dates.index(origin)})
        pending.append(row)
    return pending, unfillable


def _frozen_roles(frozen: dict[str, Any]) -> dict[str, str]:
    return {name: str(cell.get("role")) for name, cell in (frozen.get("cells") or {}).items()}


# ── 발행 ────────────────────────────────────────────────────────────────────
def publish_latest_timeseries_v14(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    contract = C.load_contract_v14(root)
    cfg = C.live_pointer_config(contract)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    effective_from = cfg["effective_from"]
    series = _series_of(contract)
    reasons: list[str] = []
    receipt_ok = C.approval_receipt_present(root, cfg["approval_receipt"])
    if not receipt_ok:
        reasons.append(f"approval_receipt_missing: {cfg['approval_receipt'] or 'null'} not in approvals ledger")
    frozen: dict[str, Any] | None = None
    try:
        frozen = C.load_frozen_coefficients(root, expected_sha256=frozen_cfg.get("sha256"),
                                            expected_content_hash=frozen_cfg.get("content_hash"))
    except C.TimeSeriesV14Error as exc:
        reasons.append(f"coefficients_not_pinned: {exc}")
    roles_ok = frozen is not None and _frozen_roles(frozen) == cfg["roles"]
    if frozen is not None and not roles_ok:
        reasons.append("role_partition_mismatch: frozen coefficient roles differ from live_pointer champion/shadow cells")

    panel = build_live_panel(root, knowledge_cutoff=knowledge_cutoff)
    as_of = str(panel["dates"][-1]) if len(panel["dates"]) else None
    max_missing = cfg["max_missing_sessions"]
    freshness = freshness_report(root, as_of, current, max_missing_sessions=max_missing)
    if freshness["status"] != "fresh":
        reasons.append(f"{freshness['status']}: missing_sessions={freshness['missing_sessions']} > {max_missing}"
                       if freshness["status"] == "stale" else "no_observation: archive has no VIX∩NASDAQCOM session")
    panel_ok = len(panel["dates"]) > C.RV_WINDOW      # RV21_t 는 최근 22 종가가 있어야 정의된다
    if as_of and not panel_ok:
        reasons.append(f"panel_too_short_for_rv21: {len(panel['dates'])} sessions since {C.LIVE_PANEL_START}")

    gate = {"approval_receipt_present": receipt_ok, "coefficients_pinned": frozen is not None,
            "roles_consistent": bool(roles_ok), "freshness_pass": freshness["status"] == "fresh",
            "panel_sufficient": panel_ok, "reasons": reasons}
    status = "live" if not reasons else "hold"
    inputs = cells = None
    if status == "live":
        cells, inputs = compute_cells(frozen, panel, cfg["roles"])  # type: ignore[arg-type]
    pin = {"path": C.COEFFICIENTS_RELATIVE.as_posix(), "sha256": frozen_cfg.get("sha256"),
           "content_hash": frozen_cfg.get("content_hash")}

    # 백필 후보는 포인터 본문보다 먼저 — `backfill` 블록이 포인터 content_hash 안에 들어가야 한다.
    ledger_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    pending: list[dict[str, Any]] = []
    unfillable: list[dict[str, Any]] = []
    if status == "live" and effective_from and as_of:
        pending, unfillable = _prepare_backfill(root, effective_from=effective_from, panel=panel, as_of=as_of,
                                                knowledge_cutoff=knowledge_cutoff, pin=pin, ledger_rows=ledger_rows,
                                                frozen=frozen, roles=cfg["roles"],  # type: ignore[arg-type]
                                                display_tier=cfg["display_tier"], series=series)
    # 포인터에는 매 실행 같은 값으로 다시 유도되는 것만(effective_from·unfillable) — 실행별 산출은 반환값에만.
    backfill_block = {"effective_from": effective_from, "unfillable": unfillable} if effective_from else None
    body = _pointer_body(status=status, as_of=as_of, knowledge_cutoff=knowledge_cutoff, gate=gate,
                         freshness=freshness, pin=pin, cfg=cfg, inputs=inputs, cells=cells, backfill=backfill_block)
    pointer = root / C.LATEST_RELATIVE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    tmp = pointer.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False),
                   encoding="utf-8", newline="\n")
    os.replace(tmp, pointer)

    appended = False
    backfilled: list[str] = []
    if status == "live":
        run_id = _run_id(str(as_of), str(pin["sha256"]))
        for row in pending:                       # 백필 행(원점 오름차순) 먼저 — 전부 이 발행의 포인터·run_id 를 가리킨다
            row["pointer_content_hash"] = body["content_hash"]
            row["captured_by_run"] = run_id
            row["content_hash"] = C.canonical_hash(row)
            if append_unique(root, C.LIVE_LEDGER_RELATIVE, row, key="run_id"):
                backfilled.append(str(row["as_of"]))
        if run_id not in {row.get("run_id") for row in ledger_rows}:
            row = _ledger_row(as_of=str(as_of), knowledge_cutoff=knowledge_cutoff, pin=pin, inputs=inputs,
                              cells=cells, display_tier=cfg["display_tier"])
            row["pointer_content_hash"] = body["content_hash"]
            row["content_hash"] = C.canonical_hash(row)
            appended = append_unique(root, C.LIVE_LEDGER_RELATIVE, row, key="run_id")
    late_existing = sum(1 for row in ledger_rows if row.get("pit_grade") == C.LATE_CAPTURE)
    return {"status": status, "as_of": as_of, "reasons": reasons, "ledger_appended": appended,
            "content_hash": body["content_hash"], "champion_cells": cfg["champion_cells"],
            "shadow_cells": cfg["shadow_cells"],
            "condition_met": {k: v["condition_met"] for k, v in (cells or {}).items()},
            "backfilled": backfilled, "unfillable": unfillable,
            "late_capture_rows_total": late_existing + len(backfilled)}


def v14_pointer_changed(root: Path) -> bool:
    """워크플로 커밋 판단 — HEAD 포인터와 시계(knowledge_cutoff·freshness.evaluated_at·content_hash)만 다르면 False.

    V13 forecast_refresh.v13_pointer_changed 와 같은 비교(같은 _v13_semantics). 첫 발행(HEAD 에 없음)은 True.
    """
    relative = C.LATEST_RELATIVE.as_posix()
    current = json.loads((root / relative).read_text(encoding="utf-8"))
    previous = subprocess.run(["git", "show", "HEAD:" + relative], cwd=root, capture_output=True, check=False)
    if previous.returncode:
        return True
    return _pointer_semantics(json.loads(previous.stdout)) != _pointer_semantics(current)


# ── 검증 ────────────────────────────────────────────────────────────────────
class TimeSeriesV14PointerError(ValueError):
    """The V14 latest pointer failed closed."""


GATE_KEYS = ("approval_receipt_present", "coefficients_pinned", "roles_consistent", "freshness_pass", "panel_sufficient")
ISOLATION_KEYS = ("combined_with_official_forecasts", "combined_with_timeseries_v13", "combined_with_timeseries_v8",
                  "combined_with_scenario_v5_2", "trading_signal", "customer_numbers_visible", "shadow_cells_displayable")


def validate_latest(value: dict[str, Any], *, roles: dict[str, str] | None = None) -> None:
    if value.get("model_id") != C.MODEL_ID or value.get("model_version") != C.MODEL_VERSION \
            or value.get("model") != C.MODEL_NAME:
        raise TimeSeriesV14PointerError("V14 model identity mismatch")
    if value.get("probability_space") != C.PROBABILITY_SPACE or value.get("probability_unit") != "fraction":
        raise TimeSeriesV14PointerError("V14 probability space/unit mismatch")
    body = dict(value)
    if body.pop("content_hash", None) != C.canonical_hash(body):
        raise TimeSeriesV14PointerError("V14 latest content hash mismatch")
    status = value.get("status")
    if status not in {"live", "hold"}:
        raise TimeSeriesV14PointerError("V14 pointer status must be live or hold")
    gate = value.get("gate"); publication = value.get("publication")
    if not isinstance(gate, dict) or not isinstance(publication, dict):
        raise TimeSeriesV14PointerError("V14 pointer gate/publication must be objects")
    if all(gate.get(key) is True for key in GATE_KEYS) is not (status == "live"):
        raise TimeSeriesV14PointerError("V14 status must equal all gate decisions")
    if publication.get("reference_opinion_only") is not True or any(publication.get(k) is not False
                                                                        for k in ISOLATION_KEYS):
        raise TimeSeriesV14PointerError("V14 must remain reference-only, isolated, non-signal and undisplayed")
    if status == "hold":
        if value.get("cells") or value.get("inputs"):
            raise TimeSeriesV14PointerError("V14 HOLD surface must carry no probabilities")
        return
    cells = value.get("cells") or {}
    if not isinstance(cells, dict) or set(cells) != set(C.CELL_ORDER):
        raise TimeSeriesV14PointerError("V14 live cell set must be the six cells")
    for name, cell in cells.items():
        if cell.get("role") not in C.ROLES or (roles is not None and cell.get("role") != roles.get(name)):
            raise TimeSeriesV14PointerError(f"V14 cell {name} role invalid or differs from the contract")
        met = cell.get("condition_met")
        if not isinstance(met, bool):
            raise TimeSeriesV14PointerError(f"V14 cell {name} condition_met must be boolean")
        p = cell.get("p")
        if met:
            if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0.0 <= float(p) <= 1.0:
                raise TimeSeriesV14PointerError(f"V14 cell {name} probability out of [0, 1]")
        elif p is not None:
            raise TimeSeriesV14PointerError(f"V14 cell {name} carries p although its condition is not met")


def _cell_view(cell: dict[str, Any]) -> tuple[Any, ...]:
    return (cell.get("condition_met"), cell.get("p"), cell.get("role"), cell.get("level"), cell.get("clim_base_rate"))


def _recompute_errors(frozen: dict[str, Any], panel: dict[str, np.ndarray], recorded: dict[str, Any],
                      roles: dict[str, str], label: str) -> list[str]:
    errors: list[str] = []
    cells, _ = compute_cells(frozen, panel, roles)
    for name, cell in cells.items():
        got = (recorded.get(name) or {})
        if got.get("condition_met") is not cell["condition_met"]:
            errors.append(f"{label} cell {name} condition_met recompute mismatch")
        elif cell["p"] is None:
            if got.get("p") is not None:
                errors.append(f"{label} cell {name} carries p although its condition is not met")
        elif got.get("p") is None or abs(cell["p"] - float(got["p"])) > 1e-9:
            errors.append(f"{label} cell {name} recompute mismatch")
    return errors


def verify_timeseries_v14(root: Path) -> dict[str, Any]:
    """포인터·원장·계수 핀의 정합 + 아카이브 재계산 대사(|Δp| < 1e-9) + 백필 규칙(V13 origin_backfill.verify_rules 승계)."""
    errors: list[str] = []
    unfillable_disclosed: list[dict[str, Any]] = []
    contract = C.load_contract_v14(root)
    cfg = C.live_pointer_config(contract)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    pinned_sha = frozen_cfg.get("sha256")
    effective_from = cfg["effective_from"]
    series = _series_of(contract)
    pointer = root / C.LATEST_RELATIVE
    if not pointer.is_file():
        return {"ok": False, "errors": ["pointer missing"]}
    latest = json.loads(pointer.read_text(encoding="utf-8"))
    try:
        validate_latest(latest, roles=cfg["roles"])
    except TimeSeriesV14PointerError as exc:
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
        for name, cell in (row.get("cells") or {}).items():
            if name not in C.CELL_ORDER or cell.get("role") not in C.ROLES:
                errors.append(f"ledger cell {name} unknown or role invalid: {row.get('run_id')}")
            elif (cell.get("p") is None) is bool(cell.get("condition_met")):
                errors.append(f"ledger cell {name} p/condition_met inconsistent: {row.get('run_id')}")
    late_rows = [row for row in rows if row.get("pit_grade") == C.LATE_CAPTURE]
    live = latest.get("status") == "live"
    frozen: dict[str, Any] | None = None
    # 핀(sha256)이 있으면 포인터 상태와 무관하게 언제나 계수를 싣고 역할 분할을 대조한다 — 핀 뒤의 계수 결손·변조·
    # 역할 불일치는 hold 포인터 뒤에 숨는 일시 상태가 아니라 구성 오류다(잡 실패 → ops-failure-alert).
    # 핀이 null(동결 전)이면 hold 가 정상 상태이고, live 포인터만 계수를 요구한다.
    if pinned_sha or live:
        try:
            frozen = C.load_frozen_coefficients(root, expected_sha256=pinned_sha,
                                                expected_content_hash=frozen_cfg.get("content_hash"))
        except C.TimeSeriesV14Error as exc:
            errors.append(f"coefficients: {exc}")
        if frozen is not None and _frozen_roles(frozen) != cfg["roles"]:
            errors.append("coefficients: frozen coefficient roles differ from live_pointer champion/shadow cells")
    if pinned_sha:
        if not C.approval_receipt_present(root, cfg["approval_receipt"]):
            errors.append(f"approval receipt missing or superseded: {cfg['approval_receipt'] or 'null'}")
        # 핀 뒤의 hold 는 신선도·패널 길이(시간이 풀어 주는 것)로만 정당하다 — 영수증·핀·역할 hold 는 오류다.
        gate = latest.get("gate") if isinstance(latest.get("gate"), dict) else {}
        if latest.get("status") == "hold":
            structural = [k for k in ("approval_receipt_present", "coefficients_pinned", "roles_consistent")
                          if gate.get(k) is not True]
            if structural:
                errors.append(f"pointer held by a structural gate while coefficients are pinned: {structural}")
    if frozen is not None:
        frozen_clim = {name: float(cell["clim_base_rate"]) for name, cell in frozen["cells"].items()}
        for row in rows:
            if row.get("coefficients_sha256") != pinned_sha:
                continue
            for name, cell in (row.get("cells") or {}).items():
                if cell.get("clim_base_rate") != frozen_clim.get(name):
                    errors.append(f"ledger cell {name} climatology differs from the frozen artifact: {row.get('run_id')}")
    if live:
        pointer_sha = (latest.get("coefficients") or {}).get("sha256")
        as_of = str(latest.get("as_of"))
        # [1] 포인터 ↔ 원장: 같은 as_of·같은 계수의 행이 정확히 1개, 셀 내용 일치(포인터는 재실행마다 다시 써져 해시가 아니라 내용 대조)
        matching = [row for row in rows if row.get("as_of") == as_of and row.get("coefficients_sha256") == pointer_sha]
        if len(matching) != 1:
            errors.append(f"ledger has {len(matching)} rows for pointer as_of/coefficients (expected 1)")
        else:
            for name, cell in (latest.get("cells") or {}).items():
                if _cell_view((matching[0].get("cells") or {}).get(name) or {}) != _cell_view(cell):
                    errors.append(f"ledger/pointer cell mismatch: {name}")
        panel = build_live_panel(root, knowledge_cutoff=latest["knowledge_cutoff"])
        dates = [str(d) for d in panel["dates"]]
        if not dates or dates[-1] != as_of:
            errors.append("as_of drifted from archive at the recorded knowledge cutoff")
        elif frozen is not None:
            errors += _recompute_errors(frozen, panel, latest.get("cells") or {}, cfg["roles"], "pointer")
        if effective_from:
            # [4] 완전성 — effective_from 이후·as_of 이전 패널 거래일마다 행(어떤 sha 든). 기록된 unfillable 은 다시 유도해 공시.
            by_origin = Counter(str(row.get("as_of")) for row in rows)
            by_origin_sha = Counter((str(row.get("as_of")), str(row.get("coefficients_sha256"))) for row in rows)
            disclosed = {str(u.get("origin")): u for u in ((latest.get("backfill") or {}).get("unfillable") or [])}
            first_capture: dict[tuple[str, str], str] | None = None
            for origin in dates:
                if origin < effective_from or origin >= as_of:
                    continue
                count = by_origin.get(origin, 0)
                if count == 0 and origin in disclosed:
                    if first_capture is None:
                        first_capture = _first_capture_index(read_market_facts(root), series)
                    _, _, reason = _rolled_back(root, origin=origin, first_capture=first_capture, series=series)
                    if reason is None:
                        errors.append(f"unfillable not reproducible: {origin}")
                    else:
                        unfillable_disclosed.append(dict(disclosed[origin]))
                elif count == 0:
                    errors.append(f"backfill incomplete: {origin}")
                else:
                    for (day, sha), n in sorted(by_origin_sha.items()):
                        if day == origin and n > 1:
                            errors.append(f"ledger has {n} rows for origin {origin}/coefficients {sha[:8]} (expected 1)")
    # [2·3] late_capture 행 — 포인터 상태와 무관하게 원장 전 행
    for row in late_rows:
        run_id = row.get("run_id")
        try:
            cutoff_used = datetime.fromisoformat(str(row.get("backfill_cutoff_used")))
            if cutoff_used > datetime.fromisoformat(str(row.get("knowledge_cutoff"))):
                errors.append(f"late_capture cutoff after publication: {run_id}")
        except (TypeError, ValueError):
            errors.append(f"late_capture cutoff unparseable: {run_id}")
            continue
        sessions = row.get("late_capture_sessions")
        if isinstance(sessions, bool) or not isinstance(sessions, int) or sessions < 1:
            errors.append(f"late_capture sessions < 1: {run_id}")
        if effective_from and str(row.get("as_of")) < effective_from:
            errors.append(f"late_capture before effective_from: {run_id}")
        if frozen is None or row.get("coefficients_sha256") != pinned_sha:
            continue  # 재동결 전 계수의 행은 재계산할 계수가 없다(핀은 하나) — 해시·규칙 3 까지만
        origin = str(row.get("as_of"))
        back = _origin_panel(root, origin=origin, cutoff=str(row["backfill_cutoff_used"]))
        if not len(back["dates"]) or str(back["dates"][-1]) != origin:
            errors.append(f"late_capture as_of drifted at backfill cutoff: {run_id}")
            continue
        errors += [f"{e}: {run_id}" for e in _recompute_errors(frozen, back, row.get("cells") or {}, cfg["roles"],
                                                               "late_capture")]
    return {"ok": not errors, "errors": errors, "rows": len(rows), "status": latest.get("status"),
            "unfillable_disclosed": unfillable_disclosed}
