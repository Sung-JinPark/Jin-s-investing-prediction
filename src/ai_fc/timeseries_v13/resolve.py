"""V13-VOL 라이브 전진 채점 — 성숙한 원점만 라벨링해 append-only 원장에 남긴다.

계약 `live_forward_gate`(2026-09-08 사전등록, 어떤 원점도 성숙하기 전에 고정)의 채점 verb.
설계창 성적이 아니라 **배포 이후 실제로 확정된** 성적만 쌓는다 — 이것이 C1(전진 표본)의 유일한 경로다.

규율:
- 성숙 판정은 달력이 아니라 **아카이브에 들어온 거래일 인덱스**로 한다(V8 shadow_resolve 승계).
  원점 + h 세션이 아카이브에 없으면 건너뛰고 다음 실행에서 다시 시도한다.
- 라벨은 모형과 무관하다. 기록된 확률 p 를 그대로 채점하므로 계수가 나중에 재동결되어도 과거 행은 유효하다.
- 기후는 계약 `climatology_base_rates` 의 고정값(설계창) — 라이브에서 재추정하지 않는다.
- 판정(강등)은 하지 않는다. 성숙 원점이 셀당 `minimum_matured_origins_per_cell` 에 닿기 전에는
  '표본 부족'이며, 그 뒤의 강등 규칙 적용은 별도 단계다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v2.market_archive import read_market_observations
from ..timeseries_v8.artifact import append_unique
from . import contracts as C
from . import features as F

HISTORY_START = "2007-01-01"
RESOLUTION_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live_resolutions.jsonl")


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def climatology_map(contract: dict[str, Any], frozen: dict[str, Any] | None = None) -> dict[str, float]:
    """고정 기후 기저율을 셀 이름으로 색인한다 (라이브 재추정 금지).

    **출처는 동결 계수 아티팩트가 정본이다.** 계약 `climatology_base_rates` 표는 그 값의
    소수 4자리 전사인데, 2026-09-10 실측에서 RV 3셀의 전사가 어긋났다 —
    `rv_h21` 0.6760 vs 0.67084797(차 0.005152) · `rv_h63` 0.8751 vs 0.87647360 ·
    `rv_h5` 0.5523 vs 0.55243352. VIX 6셀은 4자리 반올림으로 일치한다.

    홀드아웃 채점(`holdout.py` G1)은 아티팩트 값을 썼다 — 기록된 `bs_baseline` 에서
    `BS = r(1-p)^2 + (1-r)p^2` 로 역산해 9/9 셀 잔차 1e-16 으로 확인했다. 라이브가 계약 표를
    쓰면 **같은 '기후 기준선'이 두 경로에서 달라지고**, 성숙 원점 60개 뒤 라이브 BSS 를
    홀드아웃 BSS 와 비교할 때 기준이 어긋난다. 배선 자격 셀(rv_h5·rv_h21)이 둘 다 그 안에 있다.

    계약 105행은 기후를 "climatology_base_rates 고정값(**설계창**)"이라 정의한다. 설계창의
    실제 무조건 빈도는 아티팩트 값이므로, 아티팩트를 읽는 것이 계약의 **정의**를 따르는 것이다.
    계약 표의 바이트는 건드리지 않는다 — 동결 좌표를 결과 후에 고치지 않기 위해서다.

    `frozen` 이 없으면 계약 표로 되돌아간다(과거 동작). 호출부는 아티팩트를 넘긴다.
    """
    if frozen:
        cells = frozen.get("cells") or {}
        out: dict[str, float] = {}
        for spec in C.cell_specs():
            cell = cells.get(spec["name"]) or {}
            if "clim_base_rate" not in cell:
                break
            out[spec["name"]] = float(cell["clim_base_rate"])
        else:
            return out

    base = contract.get("climatology_base_rates") or {}
    vix = base.get("vix_touch") or {}
    rv = base.get("rv_exceedance") or {}
    out = {}
    for spec in C.cell_specs():
        if spec["target"] == "vix_touch":
            out[spec["name"]] = float(vix[f"K{spec['K']}_h{spec['h']}"])
        else:
            out[spec["name"]] = float(rv[f"h{spec['h']}"])
    return out


def _labels_for(spec: dict[str, Any], vix: np.ndarray, rv: np.ndarray) -> np.ndarray:
    if spec["target"] == "vix_touch":
        return F.labels_vix(vix, spec["K"], spec["h"])
    return F.labels_rv(rv, spec["theta"], spec["h"])


def resolve_live_timeseries_v13_vol(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """성숙한 (원장 행 × 셀) 을 채점해 vol_live_resolutions.jsonl 에 append 한다."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    knowledge_cutoff = current.isoformat(timespec="seconds")
    contract = C.load_contract_v13(root)
    gate = contract.get("live_forward_gate") or {}
    minimum = int(gate.get("minimum_matured_origins_per_cell") or 60)
    pin = contract.get("frozen_coefficients") or {}
    try:
        frozen = C.load_frozen_coefficients(
            root,
            expected_sha256=pin.get("sha256"),
            expected_content_hash=pin.get("content_hash"),
            expected_finalist_id=(contract.get("gates", {}).get("champion") or {}).get("finalist_id"),
        )
    except Exception:
        frozen = None      # 핀이 어긋나면 계약 표로 되돌아간다 — 조용히 틀린 값을 쓰지 않는다
    clim = climatology_map(contract, frozen)

    live_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    if not live_rows:
        return {"resolved": 0, "pending": 0, "matured_by_cell": {}, "reason": "no live rows"}

    panel = F.build_panel(read_market_observations(root, knowledge_cutoff=knowledge_cutoff),
                          start=HISTORY_START)
    dates = [str(d) for d in panel["dates"]]
    index_by_date = {d: i for i, d in enumerate(dates)}
    labels = {spec["name"]: _labels_for(spec, panel["vix"], panel["rv21"]) for spec in C.cell_specs()}
    specs = {spec["name"]: spec for spec in C.cell_specs()}

    existing = _read_rows(root / RESOLUTION_LEDGER_RELATIVE)
    resolved_keys = {str(row.get("resolution_id")) for row in existing}
    appended = 0
    pending = 0
    for row in live_rows:
        origin = str(row.get("as_of") or "")
        origin_index = index_by_date.get(origin)
        if origin_index is None:
            pending += len(row.get("cells") or {})
            continue
        for cell_name, recorded in (row.get("cells") or {}).items():
            spec = specs.get(cell_name)
            if spec is None:
                continue
            key = f"{row.get('run_id')}-{cell_name}"
            if key in resolved_keys:
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
            base = clim[cell_name]
            payload = {
                "schema_version": 1,
                "resolution_id": key,
                "run_id": row.get("run_id"),
                "cell": cell_name,
                "origin": origin,
                "horizon_sessions": spec["h"],
                "resolved_session": dates[end],
                "probability": p,
                "label": float(label),
                "brier_model": round((p - float(label)) ** 2, 8),
                "brier_climatology": round((base - float(label)) ** 2, 8),
                "climatology_base_rate": base,
                "coefficients_sha256": row.get("coefficients_sha256"),
                "finalist_id": row.get("finalist_id"),
                "holdout_status_at_forecast": row.get("holdout_status"),
                "knowledge_cutoff": knowledge_cutoff,
            }
            payload["content_hash"] = C.canonical_hash(payload)
            if append_unique(root, RESOLUTION_LEDGER_RELATIVE, payload, key="resolution_id"):
                appended += 1
                resolved_keys.add(key)

    all_rows = _read_rows(root / RESOLUTION_LEDGER_RELATIVE)
    matured: dict[str, int] = {}
    for row in distinct_resolutions(all_rows, pinned_sha=str(pin.get("sha256") or "") or None):
        cell = str(row.get("cell"))
        matured[cell] = matured.get(cell, 0) + 1
    return {
        "resolved": appended, "pending": pending,
        # 원점은 distinct 로 센다 — 같은 원점의 재동결 중복행은 60 게이트 산정에서 하나다.
        "matured_by_cell": {name: matured.get(name, 0) for name in C.CELL_ORDER},
        "minimum_matured_origins_per_cell": minimum,
        "cells_at_minimum": sorted(k for k, v in matured.items() if v >= minimum),
        "total_resolutions": len(all_rows),
        "total_distinct_resolutions": sum(matured.values()),
    }


def pinned_coefficients_sha(root: Path) -> str | None:
    """계약에 핀된 동결 계수 sha256 — 같은 원점이 두 계수로 채점됐을 때 어느 행이 정본인지 정한다."""
    try:
        frozen = C.load_contract_v13(root).get("frozen_coefficients") or {}
    except Exception:  # noqa: BLE001 — 계약을 못 읽으면 핀 없음으로 취급(최근 행 우선)
        return None
    sha = frozen.get("sha256")
    return str(sha) if sha else None


def distinct_resolutions(rows: list[dict[str, Any]], *, pinned_sha: str | None = None) -> list[dict[str, Any]]:
    """(cell, origin) 당 한 행만 남긴다 — **원점은 한 번만 센다**.

    2026-09-04 원점이 구 계수(51815bde…)와 재동결 계수(1a857850…)로 두 번 발행돼 해상 원장에
    6셀 × 2행이 있다(run_id 가 계수 sha 를 품어 멱등 키가 다르다). 행 수로 세면 60원점 게이트를
    원점 하나 먼저 넘고 첫 원점의 Brier 가 2배 가중된다. 원장은 무수정이고 **읽기만** 바꾼다.
    우선순위: 계약에 핀된 계수 sha 의 행 → 그 다음 `knowledge_cutoff` 가 가장 늦은 행.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("cell")), str(row.get("origin")))
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        row_pinned = pinned_sha is not None and row.get("coefficients_sha256") == pinned_sha
        cur_pinned = pinned_sha is not None and current.get("coefficients_sha256") == pinned_sha
        if row_pinned and not cur_pinned:
            best[key] = row
        elif row_pinned == cur_pinned and str(row.get("knowledge_cutoff") or "") > str(current.get("knowledge_cutoff") or ""):
            best[key] = row
    return list(best.values())


def distinct_origin_count(live_rows: list[dict[str, Any]]) -> int:
    """라이브 원장의 **고유 원점(as_of) 수** — 재동결로 같은 원점이 두 행이어도 하나로 센다."""
    return len({str(row.get("as_of")) for row in live_rows if row.get("as_of")})


def matured_counts(root: Path) -> dict[str, int]:
    """셀별 성숙 원점 수(distinct origin) — 표시 계층의 '표본 부족' 카운터용(확률 없음)."""
    counts: dict[str, int] = {name: 0 for name in C.CELL_ORDER}
    rows = distinct_resolutions(_read_rows(root / RESOLUTION_LEDGER_RELATIVE),
                                pinned_sha=pinned_coefficients_sha(root))
    for row in rows:
        cell = str(row.get("cell"))
        if cell in counts:
            counts[cell] += 1
    return counts


def verify_live_resolutions(root: Path) -> dict[str, Any]:
    """해상 원장의 해시·중복·창 규율 검증."""
    errors: list[str] = []
    rows = _read_rows(root / RESOLUTION_LEDGER_RELATIVE)
    seen: set[str] = set()
    for row in rows:
        body = {k: v for k, v in row.items() if k != "content_hash"}
        if C.canonical_hash(body) != row.get("content_hash"):
            errors.append(f"resolution hash mismatch: {row.get('resolution_id')}")
        key = str(row.get("resolution_id"))
        if key in seen:
            errors.append(f"duplicate resolution_id: {key}")
        seen.add(key)
        if str(row.get("resolved_session") or "") <= str(row.get("origin") or ""):
            errors.append(f"resolved_session not after origin: {key}")
        if float(row.get("label", -1)) not in (0.0, 1.0):
            errors.append(f"label must be 0 or 1: {key}")
    return {"ok": not errors, "errors": errors, "rows": len(rows)}
