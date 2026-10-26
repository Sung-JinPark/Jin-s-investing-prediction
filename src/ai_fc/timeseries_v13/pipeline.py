"""V13-VOL 라이브 발행 — 동결 계수로 최신 관측의 9셀 기준율을 산출해 커밋 포인터 + append-only 원장에 기록한다.

fail-closed: 계약 미무장 · 계수 핀 불일치 · 신선도 미달 중 하나라도 있으면 status=hold 포인터(숫자 없음).
재적합 없음(holdout_refit·refit_prohibited). 봉인 market_archive 는 read-only.

원점 백필(계약 `origin_backfill`, V13-D12 2026-10-22): 아카이브 refresh 가 늦어 발행이 건너뛴 원점은
effective_from 이후·포인터 as_of 이전 거래일에 한해 **그 원점 관측의 첫 vintage available_at 으로 되감은 cutoff**
로 읽고 **원점에서 절단한 패널**(end=origin)로 다시 계산해 pit_grade=late_capture 행으로 쓴다. 기계적·무조건 —
결과를 보고 쓰거나 빼는 경로가 없다. 결손은 **어떤 계수 sha 로도 행이 없는 원점**이다(재동결 뒤 옛 sha 행이 있는
원점은 다시 채점하지 않는다 — forward_only). 정상 행에는 pit_grade 가 없다(captured_forward 로 읽는다) — 기존 행
해시를 그대로 둔다.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

# 개정(revision_seq>1) 포함 전량(dedupe 전) — 원점의 **첫** vintage available_at 을 찾는 데만 쓴다. 봉인 모듈 read-only.
from ..timeseries_v2.market_archive import _current_facts as read_market_facts
from ..timeseries_v2.market_archive import read_market_observations
from ..timeseries_v8.artifact import append_unique
from . import contracts as C
from . import features as F
from .freshness import freshness_report

HISTORY_START = "2007-01-01"
BACKFILL_SERIES = ("VIX", "NASDAQCOM")      # 계약 data_policy.series 가 없을 때의 기본값
LATE_CAPTURE = "late_capture"


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
                  inputs: dict[str, float] | None, cells: dict[str, Any] | None,
                  backfill: dict[str, Any] | None = None) -> dict[str, Any]:
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
    if backfill is not None:
        body["backfill"] = backfill          # 포인터는 여전히 as_of 1개만 가리킨다 — 백필 요약은 해시 안에 싣는다
    body["content_hash"] = C.canonical_hash(body)
    return body


def _ledger_row(*, as_of: str, knowledge_cutoff: str, pin: dict[str, Any], inputs: dict[str, float] | None,
                cells: dict[str, Any] | None, holdout_status: str) -> dict[str, Any]:
    """원장 행 공통 본문 — pointer_content_hash·content_hash(·백필 필드)는 호출부가 뒤에 채운다.

    run_id 는 (as_of, 계수 sha 앞 8자) — 같은 관측·같은 계수의 재실행은 한 행(멱등), 재동결은 새 행(이력 보존).
    """
    return {"schema_version": 1, "run_id": f"v13vol-{as_of}-{str(pin['sha256'])[:8]}", "as_of": as_of,
            "knowledge_cutoff": knowledge_cutoff, "model_id": C.MODEL_ID, "finalist_id": pin["finalist_id"],
            "coefficients_sha256": pin["sha256"], "inputs": inputs,
            "cells": {k: {"p": v["p"], "band80": v["band80"], "model": v["model"]} for k, v in (cells or {}).items()},
            "holdout_status": holdout_status}


def _first_capture_index(facts: Any, series: tuple[str, ...]) -> dict[tuple[str, str], str]:
    """(series, 관측일) → 첫 vintage(revision_seq 최소) 의 available_at(ISO).

    되감은 cutoff(backfill_cutoff_used)의 재료 — 원점 관측 자체는 첫 vintage 시각에 알 수 있었다. 개정(revision_seq>1)의
    포함 여부는 이 색인이 아니라 cutoff 가 정한다: available_at > cutoff 면 제외, 그 전에 도착했으면 제때 발행과 같은
    규칙(max revision_seq dedupe)으로 포함된다(first/single vintage 는 cutoff 시점 기준).
    """
    out: dict[tuple[str, str], tuple[int, str]] = {}
    for row in facts:
        if row.series_id not in series:
            continue
        key = (row.series_id, str(row.observation_time)[:10])
        if key not in out or int(row.revision_seq) < out[key][0]:
            out[key] = (int(row.revision_seq), str(row.available_at))
    return {key: stamp for key, (_, stamp) in out.items()}


def _backfill_cutoff(first_capture: dict[tuple[str, str], str], origin: str,
                     series: tuple[str, ...]) -> str | None:
    """원점의 되감은 cutoff — 계열별 첫 vintage available_at 의 최댓값. 어느 계열이든 원점 관측이 없으면 None."""
    stamps = [first_capture.get((sid, origin)) for sid in series]
    if any(stamp is None for stamp in stamps):
        return None
    return max((str(s) for s in stamps), key=datetime.fromisoformat)


def _origin_panel(root: Path, *, origin: str, cutoff: str) -> dict[str, np.ndarray]:
    """되감은 cutoff 로 읽고 원점에서 절단한 패널(end=origin).

    아카이브의 captured_forward 행은 available_at 이 영수증 수집 시각이라 한 refresh 로 한꺼번에 들어온 여러 세션이
    같은 시각을 갖는다 — 원점 뒤 세션이 같은 cutoff 안에 있어도 절단으로 p 에 들어가지 않는다. 피처는 t 이하 관측만
    쓰므로 원점의 p 는 절단 전후가 같고, PIT(available_at <= cutoff)도 그대로 성립한다(늦게 쓴 사실은 late_capture
    등급이 공시한다). 마지막 날짜가 원점과 다르면 원점 관측 자체가 cutoff 패널에 없는 것이다(as_of_drift).
    """
    return F.build_panel(read_market_observations(root, knowledge_cutoff=cutoff), start=HISTORY_START, end=origin)


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
                      frozen: dict[str, Any], thin: list[str], holdout_status: str,
                      series: tuple[str, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """계약 origin_backfill — effective_from 이후·as_of 이전 패널 거래일 중 **어떤 계수 sha 로도 행이 없는** 원점 전부.

    재동결 뒤 옛 sha 행이 있는 원점은 결손이 아니다(forward_only — 새 계수로 다시 채점하지 않는다).
    각 원점의 cutoff 는 VIX·NASDAQCOM 당일 관측의 첫 vintage available_at 최댓값으로 되감고, 패널은 원점에서 절단한다.
    절단 패널의 마지막 날짜가 원점과 다르면(as_of_drift) · 원점 관측이 없으면(no_observation) unfillable — 행을 쓰지 않는다.
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
        cells, inputs = compute_cells(frozen, back, episode_thin=thin)
        row = _ledger_row(as_of=origin, knowledge_cutoff=knowledge_cutoff, pin=pin, inputs=inputs, cells=cells,
                          holdout_status=holdout_status)
        row.update({"pit_grade": LATE_CAPTURE, "backfill_cutoff_used": cutoff_used,
                    "late_capture_sessions": dates.index(as_of) - dates.index(origin)})
        pending.append(row)
    return pending, unfillable


def publish_latest_timeseries_v13_vol(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    contract = C.load_contract_v13(root)
    gates = contract.get("gates") or {}
    live_display = contract.get("live_display") or {}
    frozen_cfg = contract.get("frozen_coefficients") or {}
    holdout_status = str((contract.get("publication") or {}).get("holdout_status") or "not_consumed")
    # origin_backfill 키가 없으면 백필 비활성(포인터 블록도 없음) — 등록된 계약은 effective_from 을 갖는다
    effective_from = str((contract.get("origin_backfill") or {}).get("effective_from") or "") or None
    series = _series_of(contract)
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
    thin = list(live_display.get("episode_thin_cells") or [])
    inputs = cells = None
    if status == "live":
        cells, inputs = compute_cells(frozen, panel, episode_thin=thin)  # type: ignore[arg-type]
    pin = {"path": str(C.COEFFICIENTS_RELATIVE.as_posix()), "sha256": frozen_cfg.get("sha256"),
           "content_hash": frozen_cfg.get("content_hash"), "finalist_id": frozen_cfg.get("finalist_id")}

    # 백필 후보는 포인터 본문보다 먼저 계산한다 — `backfill` 블록이 포인터 content_hash 안에 들어가야 한다.
    ledger_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    pending: list[dict[str, Any]] = []
    unfillable: list[dict[str, Any]] = []
    if status == "live" and effective_from and as_of:
        pending, unfillable = _prepare_backfill(root, effective_from=effective_from, panel=panel, as_of=as_of,
                                                knowledge_cutoff=knowledge_cutoff, pin=pin, ledger_rows=ledger_rows,
                                                frozen=frozen, thin=thin, holdout_status=holdout_status,  # type: ignore[arg-type]
                                                series=series)
    backfill_block: dict[str, Any] | None = None
    if effective_from:
        # 포인터에는 매 실행 같은 값으로 다시 유도되는 것만 싣는다(effective_from·unfillable). 실행별 산출(쓴 원점·
        # 누적 late_capture 수)은 반환값에만 — 포인터에 실으면 백필 다음 실행이 빈 실행 기록만으로 '변경'이 되어
        # (forecast_refresh.v13_pointer_changed) 숫자 변화 없는 포인터가 커밋된다.
        backfill_block = {"effective_from": effective_from, "unfillable": unfillable}
    body = _pointer_body(status=status, as_of=as_of, knowledge_cutoff=knowledge_cutoff, gate=gate,
                         freshness=freshness, frozen_pin=pin, holdout_status=holdout_status,
                         inputs=inputs, cells=cells, backfill=backfill_block)
    pointer = root / C.LATEST_RELATIVE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    tmp = pointer.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(tmp, pointer)

    appended = False
    backfilled: list[str] = []
    if status == "live":
        run_id = f"v13vol-{as_of}-{str(pin['sha256'])[:8]}"
        # 백필 행(원점 오름차순) 먼저 — 전부 이 발행의 포인터 해시·run_id 를 가리킨다. run_id 멱등(append_unique).
        for row in pending:
            row["pointer_content_hash"] = body["content_hash"]
            row["captured_by_run"] = run_id
            row["content_hash"] = C.canonical_hash(row)
            if append_unique(root, C.LIVE_LEDGER_RELATIVE, row, key="run_id"):
                backfilled.append(str(row["as_of"]))
        existing = {row.get("run_id") for row in ledger_rows}
        if run_id not in existing:
            row = _ledger_row(as_of=str(as_of), knowledge_cutoff=knowledge_cutoff, pin=pin, inputs=inputs,
                              cells=cells, holdout_status=holdout_status)
            row["pointer_content_hash"] = body["content_hash"]
            row["content_hash"] = C.canonical_hash(row)
            appended = append_unique(root, C.LIVE_LEDGER_RELATIVE, row, key="run_id")
    late_existing = sum(1 for row in ledger_rows if row.get("pit_grade") == LATE_CAPTURE)
    return {"status": status, "as_of": as_of, "customer_numbers_visible": status == "live",
            "reasons": reasons, "ledger_appended": appended, "content_hash": body["content_hash"],
            "backfilled": backfilled, "unfillable": unfillable,
            "late_capture_rows_total": late_existing + len(backfilled)}


def verify_timeseries_v13_vol(root: Path) -> dict[str, Any]:
    """포인터·원장·계수 핀의 정합 + 아카이브 재계산 대사 (abs diff < 1e-9) + 계약 origin_backfill.verify_rules."""
    from ..timeseries_v13_vol_display import validate_latest  # 표시 모듈의 fail-closed 검증 재사용

    errors: list[str] = []
    unfillable_disclosed: list[dict[str, Any]] = []   # [verify_rules 4] 포인터가 기록한 unfillable 원점 — 실패 아님·공시
    contract = C.load_contract_v13(root)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    pinned_sha = frozen_cfg.get("sha256")
    effective_from = str((contract.get("origin_backfill") or {}).get("effective_from") or "") or None
    series = _series_of(contract)
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
    late_rows = [row for row in rows if row.get("pit_grade") == LATE_CAPTURE]
    live = latest.get("status") == "live"
    frozen: dict[str, Any] | None = None
    if live or any(row.get("coefficients_sha256") == pinned_sha for row in late_rows):
        try:
            frozen = C.load_frozen_coefficients(root, expected_sha256=pinned_sha,
                                                expected_content_hash=frozen_cfg.get("content_hash"),
                                                expected_finalist_id=frozen_cfg.get("finalist_id"))
        except C.TimeSeriesV13VolError as exc:
            errors.append(f"coefficients: {exc}")
    if live:
        pointer_sha = (latest.get("coefficients") or {}).get("sha256")
        as_of = str(latest.get("as_of"))
        # [verify_rules 1] 포인터 ↔ 원장 교차검사: 같은 as_of·같은 계수의 행이 정확히 1개 있고 셀(p·band80)이 일치해야 한다
        # (포인터는 재실행마다 knowledge_cutoff 가 바뀌어 다시 써지므로 해시가 아니라 내용을 대조한다).
        matching = [row for row in rows if row.get("as_of") == as_of and row.get("coefficients_sha256") == pointer_sha]
        if len(matching) != 1:
            errors.append(f"ledger has {len(matching)} rows for pointer as_of/coefficients (expected 1)")
        else:
            for name, cell in (latest.get("cells") or {}).items():
                recorded = (matching[0].get("cells") or {}).get(name) or {}
                if recorded.get("p") != cell.get("p") or recorded.get("band80") != cell.get("band80"):
                    errors.append(f"ledger/pointer cell mismatch: {name}")
        panel = F.build_panel(read_market_observations(root, knowledge_cutoff=latest["knowledge_cutoff"]),
                              start=HISTORY_START)
        dates = [str(d) for d in panel["dates"]]
        if not dates or dates[-1] != as_of:
            errors.append("as_of drifted from archive at the recorded knowledge cutoff")
        if frozen is not None:
            cells, _ = compute_cells(frozen, panel)
            for name, cell in cells.items():
                if abs(cell["p"] - float(latest["cells"][name]["p"])) > 1e-9:
                    errors.append(f"cell {name} recompute mismatch")
        if effective_from:
            # [verify_rules 4] 완전성 — effective_from 이후·as_of 이전 패널 거래일마다 행이 있어야 한다(어떤 계수 sha 든,
            # 정상 또는 late_capture). 재동결 뒤 옛 sha 행만 있는 원점은 결손이 아니다(forward_only — 새 계수로 다시
            # 채점하지 않는다). 같은 (원점, sha) 행이 둘이면 오류(재동결로 sha 가 다른 행 하나씩은 정상 — 2026-09-04 꼴).
            # as_of 자체는 위 규칙 1 이 본다. 포인터 backfill.unfillable 은 자기 주장으로 받지 않는다 — 아카이브에서
            # 되감은 cutoff·절단 패널을 다시 유도해 정말 채울 수 없을 때만 unfillable_disclosed 로 공시하고(숨기지
            # 않는다), 채울 수 있는 원점이면 실패다. 기록 없이 빠진 원점도 실패다(선택 백필 차단).
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
    # [verify_rules 2·3] late_capture 행 — 포인터 상태와 무관하게 원장 전 행
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
        back = _origin_panel(root, origin=origin, cutoff=str(row["backfill_cutoff_used"]))   # 발행과 같은 절단
        if not len(back["dates"]) or str(back["dates"][-1]) != origin:
            errors.append(f"late_capture as_of drifted at backfill cutoff: {run_id}")
            continue
        cells, _ = compute_cells(frozen, back)
        for name, cell in cells.items():
            recorded = ((row.get("cells") or {}).get(name) or {}).get("p")
            if recorded is None or abs(cell["p"] - float(recorded)) > 1e-9:
                errors.append(f"late_capture cell {name} recompute mismatch: {run_id}")
    return {"ok": not errors, "errors": errors, "rows": len(rows), "status": latest.get("status"),
            "unfillable_disclosed": unfillable_disclosed}
