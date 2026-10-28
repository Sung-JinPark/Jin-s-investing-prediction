"""V14 조건부 전이 라이브 전진 채점 — 성숙한 **조건 충족** 원점만 라벨링해 append-only 원장에 남긴다.

계약 `live_forward_gate`(2026-10-21 사전등록, 라이브 원장 0행 시점)의 채점 단계. 판정(강등·T7)은 하지 않는다 —
그 산술은 읽기 전용 verb(live_verdict)가 인쇄만 한다.

규율(V13 resolve 승계):
- 성숙 판정은 달력이 아니라 **아카이브 거래일 인덱스**로 한다. 원점 + h 세션이 아카이브에 없으면 건너뛰고 다음에 다시 본다.
- **조건 불충족 원점(condition_met=false)은 채점하지 않는다** — 포인터·원장에 기록됐을 뿐 표본이 아니다(계약 scoring).
- 라벨은 모형과 무관하다: cvix = 원점 뒤 h 세션 안에 VIX_close >= 25 · crv = 원점 뒤 h 세션 안에 RV21_ann > θ.
  기록된 p 를 그대로 채점하므로 재동결 뒤에도 과거 행은 유효하다.
- 기후는 원장 행이 기록한 동결 조건부 기저율(설계창 조건 충족 원점의 사건 빈도) — 라이브 재추정 금지.
- 집계는 (cell, origin) distinct — 핀된 계수 sha 행 우선(V13 distinct_resolutions 를 그대로 재사용, 행 키가 같다).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v8.artifact import append_unique
from ..timeseries_v13.resolve import distinct_resolutions
from . import contracts as C
from .pipeline import _read_rows, build_live_panel, labels_for


def pinned_coefficients_sha(root: Path) -> str | None:
    """계약에 핀된 동결 계수 sha256 — 같은 원점이 두 계수로 채점됐을 때 어느 행이 정본인지 정한다."""
    try:
        frozen = C.load_contract_v14(root).get("frozen_coefficients") or {}
    except Exception:  # noqa: BLE001 — 계약을 못 읽으면 핀 없음으로 취급(최근 행 우선)
        return None
    sha = frozen.get("sha256")
    return str(sha) if sha else None


def resolve_live_timeseries_v14(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """성숙한 (원장 행 × 조건 충족 셀) 을 채점해 v14_live_resolutions.jsonl 에 append 한다."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    C.load_contract_v14(root)                       # 계약 정체·표적 대조(fail-closed)
    pinned = pinned_coefficients_sha(root)
    live_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    if not live_rows:
        return {"resolved": 0, "pending": 0, "not_condition_met": 0, "matured_by_cell": {}, "reason": "no live rows"}

    panel = build_live_panel(root, knowledge_cutoff=knowledge_cutoff)
    dates = [str(d) for d in panel["dates"]]
    index_by_date = {d: i for i, d in enumerate(dates)}
    specs = {spec["name"]: spec for spec in C.cell_specs()}
    labels = {name: labels_for(spec, panel["vix"], panel["rv21"]) for name, spec in specs.items()}

    existing = _read_rows(root / C.RESOLUTION_LEDGER_RELATIVE)
    resolved_keys = {str(row.get("resolution_id")) for row in existing}
    appended = pending = not_met = 0
    for row in live_rows:
        origin = str(row.get("as_of") or "")
        origin_index = index_by_date.get(origin)
        for cell_name, recorded in (row.get("cells") or {}).items():
            spec = specs.get(cell_name)
            if spec is None:
                continue
            if recorded.get("condition_met") is not True or recorded.get("p") is None:
                not_met += 1                       # 조건 불충족 — 표본이 아니다(기록만)
                continue
            key = f"{row.get('run_id')}-{cell_name}"
            if key in resolved_keys:
                continue
            if origin_index is None:
                pending += 1
                continue
            end = origin_index + spec["h"]
            if end >= len(dates):
                pending += 1
                continue
            label = labels[cell_name][origin_index]
            if not np.isfinite(label):
                pending += 1
                continue
            p = float(recorded["p"])
            base = float(recorded["clim_base_rate"])
            payload = {
                "schema_version": 1,
                "resolution_id": key,
                "run_id": row.get("run_id"),
                "cell": cell_name,
                "origin": origin,
                "role": recorded.get("role"),
                "target": spec["target"],
                "horizon_sessions": spec["h"],
                "resolved_session": dates[end],
                "probability": p,
                "label": float(label),
                "climatology_base_rate": base,
                "brier_model": round((p - float(label)) ** 2, 8),
                "brier_climatology": round((base - float(label)) ** 2, 8),
                "coefficients_sha256": row.get("coefficients_sha256"),
                "knowledge_cutoff": knowledge_cutoff,
            }
            payload["content_hash"] = C.canonical_hash(payload)
            if append_unique(root, C.RESOLUTION_LEDGER_RELATIVE, payload, key="resolution_id"):
                appended += 1
                resolved_keys.add(key)

    matured = matured_counts(root, pinned_sha=pinned)
    return {
        "resolved": appended, "pending": pending, "not_condition_met": not_met,
        "matured_by_cell": matured,                 # distinct (cell, origin) — 행 수가 아니다
        "minimum_matured_origins_per_cell": C.MIN_MATURED,
        "cells_at_minimum": sorted(k for k, v in matured.items() if v >= C.MIN_MATURED),
        "total_resolutions": len(_read_rows(root / C.RESOLUTION_LEDGER_RELATIVE)),
        "total_distinct_resolutions": sum(matured.values()),
    }


def matured_counts(root: Path, *, pinned_sha: str | None = None) -> dict[str, int]:
    """셀별 성숙 원점 수(distinct (cell, origin)) — 판정 산술 전의 '표본 부족(n/60)' 카운터."""
    rows = distinct_resolutions(_read_rows(root / C.RESOLUTION_LEDGER_RELATIVE),
                                pinned_sha=pinned_sha if pinned_sha is not None else pinned_coefficients_sha(root))
    counts = {name: 0 for name in C.CELL_ORDER}
    for row in rows:
        if str(row.get("cell")) in counts:
            counts[str(row.get("cell"))] += 1
    return counts


def _verification_cutoff(rows: list[dict[str, Any]], now: datetime | None) -> str:
    """재계산 패널의 knowledge_cutoff — 해상 행 중 가장 늦은 knowledge_cutoff(파싱 가능한 것), 없으면 now."""
    stamps: list[datetime] = []
    for row in rows:
        try:
            stamp = datetime.fromisoformat(str(row.get("knowledge_cutoff")))
        except (TypeError, ValueError):
            continue
        stamps.append(stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc))
    if stamps:
        return max(stamps).isoformat(timespec="seconds")
    current = now or datetime.now(timezone.utc)
    return (current if current.tzinfo else current.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")


def verify_live_resolutions(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """해상 원장의 해시·중복·창 규율 + 라이브 원장 대조(조건 충족 행만 채점됐고 p·기후·계수 sha 가 기록과 같은가)
    + 아카이브 재계산 대조(셀 사양의 지평·표적, resolved_session = dates[idx(origin)+h], 라벨·기후 Brier 재계산).

    재계산 패널은 한 번만 만든다 — 해상 행의 가장 늦은 knowledge_cutoff 로(available_at <= cutoff) 읽은 라이브 패널.
    """
    errors: list[str] = []
    rows = _read_rows(root / C.RESOLUTION_LEDGER_RELATIVE)
    live = {str(row.get("run_id")): row for row in _read_rows(root / C.LIVE_LEDGER_RELATIVE)}
    specs = {spec["name"]: spec for spec in C.cell_specs()}
    dates: list[str] = []
    index_by_date: dict[str, int] = {}
    labels: dict[str, np.ndarray] = {}
    if rows:
        panel = build_live_panel(root, knowledge_cutoff=_verification_cutoff(rows, now))
        dates = [str(d) for d in panel["dates"]]
        index_by_date = {d: i for i, d in enumerate(dates)}
        labels = {name: labels_for(spec, panel["vix"], panel["rv21"]) for name, spec in specs.items()}
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("resolution_id"))
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if C.canonical_hash(body) != row.get("content_hash"):
            errors.append(f"resolution hash mismatch: {key}")
        if key in seen:
            errors.append(f"duplicate resolution_id: {key}")
        seen.add(key)
        if str(row.get("cell")) not in C.CELL_ORDER or row.get("role") not in C.ROLES:
            errors.append(f"resolution cell/role invalid: {key}")
        if str(row.get("resolved_session") or "") <= str(row.get("origin") or ""):
            errors.append(f"resolved_session not after origin: {key}")
        label = float(row.get("label", -1))
        if label not in (0.0, 1.0):
            errors.append(f"label must be 0 or 1: {key}")
        p = float(row.get("probability", -1))
        if not 0.0 <= p <= 1.0:
            errors.append(f"probability out of [0, 1]: {key}")
        if abs(float(row.get("brier_model", -1)) - round((p - label) ** 2, 8)) > 1e-12:
            errors.append(f"brier_model inconsistent: {key}")
        base = float(row.get("climatology_base_rate", -1))
        # 생산자와 같은 반올림(round(·, 8)) — resolve_live_timeseries_v14 의 brier_climatology 식 그대로
        if abs(float(row.get("brier_climatology", -1)) - round((base - label) ** 2, 8)) > 1e-12:
            errors.append(f"brier_climatology inconsistent: {key}")
        source = live.get(str(row.get("run_id")))
        cell = ((source or {}).get("cells") or {}).get(str(row.get("cell"))) or {}
        if source is None:
            errors.append(f"resolution has no live ledger row: {key}")
        elif cell.get("condition_met") is not True:
            errors.append(f"resolution scored a condition-not-met origin: {key}")
        elif (cell.get("p") != row.get("probability") or cell.get("clim_base_rate") != row.get("climatology_base_rate")
              or cell.get("role") != row.get("role") or source.get("as_of") != row.get("origin")):
            errors.append(f"resolution differs from its live ledger row: {key}")
        if source is not None and source.get("coefficients_sha256") != row.get("coefficients_sha256"):
            errors.append(f"resolution coefficients_sha256 differs from its live ledger row: {key}")
        # 아카이브 재계산 — 셀 사양·성숙 세션·라벨은 기록이 아니라 패널에서 다시 유도한다
        spec = specs.get(str(row.get("cell")))
        if spec is None:
            continue
        if row.get("horizon_sessions") != spec["h"] or row.get("target") != spec["target"]:
            errors.append(f"resolution horizon/target differ from the cell spec: {key}")
            continue
        origin_index = index_by_date.get(str(row.get("origin") or ""))
        end = None if origin_index is None else origin_index + spec["h"]
        if end is None or end >= len(dates):
            errors.append(f"resolution not reproducible: origin + h not in the archive panel: {key}")
            continue
        if str(row.get("resolved_session")) != dates[end]:
            errors.append(f"resolved_session differs from dates[idx(origin)+h] = {dates[end]}: {key}")
        recomputed = float(labels[spec["name"]][origin_index])
        if not np.isfinite(recomputed) or recomputed != label:
            errors.append(f"label differs from the archive recompute ({recomputed}): {key}")
    return {"ok": not errors, "errors": errors, "rows": len(rows)}
