"""동결 PB(persistence_pb) 재현 adapter — REPLAY_IDENTITY (T49, V13 트랙).

`verify_timeseries_v13_vol` 이 포인터 1행에 쓰는 재계산(1e-9) 방법을 **원장 전 행**으로
일반화한다. 동결 모듈은 무수정 import-only:

- 정상 행: ``build_panel(read_market_observations(knowledge_cutoff=행값), start=2007-01-01)``
  → 마지막 날짜 == as_of 전제 → ``compute_cells`` → p·band80 비교 (1e-9).
- late_capture 행: ``_origin_panel(origin=as_of, cutoff=backfill_cutoff_used)``.
- 구 sha 행(재동결 이전): 계수 artifact 가 없으므로 hash 검증만 — 재계산 불가를 날조하지 않는다.
- 해소 행: 기록된 knowledge_cutoff 의 패널로 라벨 재계산 + Brier 재계산.
  climatology 는 artifact 값이 정본 (resolve.py 전사 불일치 문서 준수).

전제 드리프트(as_of != 패널 마지막 날짜 등)는 모델 불일치가 아니라
``REPLAY_PRECONDITION_DRIFT`` 로 보고한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ...timeseries_v2.market_archive import read_market_observations
from ...timeseries_v13 import contracts as C13
from ...timeseries_v13 import features as F13
from ...timeseries_v13.pipeline import HISTORY_START, _origin_panel, compute_cells
from ...timeseries_v13.resolve import RESOLUTION_LEDGER_RELATIVE, climatology_map

P_TOLERANCE = 1e-9
BRIER_TOLERANCE = 1e-8  # 원장 brier 는 8자리 반올림 저장


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _row_hash_ok(row: dict[str, Any]) -> bool:
    body = {k: v for k, v in row.items() if k != "content_hash"}
    return C13.canonical_hash(body) == row.get("content_hash")


def replay_vol_live_rows(root: Path, *, max_rows: int | None = None) -> dict[str, Any]:
    """vol_live.jsonl 전 행 재현. 반환: 행별 상태 + 집계."""
    contract = C13.load_contract_v13(root)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    pinned_sha = frozen_cfg.get("sha256")
    frozen = C13.load_frozen_coefficients(
        root,
        expected_sha256=pinned_sha,
        expected_content_hash=frozen_cfg.get("content_hash"),
        expected_finalist_id=frozen_cfg.get("finalist_id"),
    )
    rows = _rows(root / C13.LIVE_LEDGER_RELATIVE)
    if max_rows is not None:
        rows = rows[:max_rows]
    results: list[dict[str, Any]] = []
    for row in rows:
        run_id = row.get("run_id")
        if not _row_hash_ok(row):
            results.append({"run_id": run_id, "status": "HASH_MISMATCH"})
            continue
        if row.get("coefficients_sha256") != pinned_sha:
            # 재동결 이전 sha — artifact 없음: hash 검증까지가 정직한 한계
            results.append({"run_id": run_id, "status": "HASH_ONLY_OLD_SHA"})
            continue
        as_of = str(row["as_of"])
        if row.get("pit_grade") == "late_capture":
            cutoff = str(row["backfill_cutoff_used"])
            panel = _origin_panel(root, origin=as_of, cutoff=cutoff)
        else:
            cutoff = str(row["knowledge_cutoff"])
            panel = F13.build_panel(
                read_market_observations(root, knowledge_cutoff=cutoff), start=HISTORY_START
            )
        dates = [str(d) for d in panel["dates"]]
        if not dates or dates[-1] != as_of:
            results.append({
                "run_id": run_id, "status": "REPLAY_PRECONDITION_DRIFT",
                "detail": f"panel last date {dates[-1] if dates else None} != as_of {as_of}",
            })
            continue
        cells, _ = compute_cells(frozen, panel)
        mismatches: list[str] = []
        for name, recorded in (row.get("cells") or {}).items():
            computed = cells.get(name)
            if computed is None:
                mismatches.append(f"{name}: missing in recompute")
                continue
            if abs(float(computed["p"]) - float(recorded["p"])) > P_TOLERANCE:
                mismatches.append(
                    f"{name}: p {computed['p']} vs {recorded['p']}"
                )
            band = [float(v) for v in computed["band80"]]
            recorded_band = [float(v) for v in recorded.get("band80") or []]
            if recorded_band and any(
                abs(a - b) > P_TOLERANCE for a, b in zip(band, recorded_band)
            ):
                mismatches.append(f"{name}: band80 {band} vs {recorded_band}")
        results.append({
            "run_id": run_id,
            "status": "PASS" if not mismatches else "CELL_MISMATCH",
            **({"mismatches": mismatches} if mismatches else {}),
            "pit_grade": row.get("pit_grade", "normal"),
        })
    summary = {
        "ledger": str(C13.LIVE_LEDGER_RELATIVE).replace("\\", "/"),
        "rows": len(results),
        "pass": sum(1 for r in results if r["status"] == "PASS"),
        "hash_only_old_sha": sum(1 for r in results if r["status"] == "HASH_ONLY_OLD_SHA"),
        "precondition_drift": sum(
            1 for r in results if r["status"] == "REPLAY_PRECONDITION_DRIFT"
        ),
        "failures": [r for r in results if r["status"] in ("HASH_MISMATCH", "CELL_MISMATCH")],
        "results": results,
    }
    return summary


def replay_vol_resolutions(root: Path, *, max_rows: int | None = None) -> dict[str, Any]:
    """vol_live_resolutions.jsonl 전 행 재채점 — 라벨·Brier·기후 재계산 대조."""
    contract = C13.load_contract_v13(root)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    try:
        frozen = C13.load_frozen_coefficients(
            root,
            expected_sha256=frozen_cfg.get("sha256"),
            expected_content_hash=frozen_cfg.get("content_hash"),
            expected_finalist_id=frozen_cfg.get("finalist_id"),
        )
    except C13.TimeSeriesV13VolError:
        frozen = None
    clim = climatology_map(contract, frozen)
    specs = {spec["name"]: spec for spec in C13.cell_specs()}

    rows = _rows(root / RESOLUTION_LEDGER_RELATIVE)
    if max_rows is not None:
        rows = rows[:max_rows]
    # 같은 knowledge_cutoff 의 행이 많다 — 패널을 cutoff 별로 캐시한다 (read-only)
    panels: dict[str, dict[str, np.ndarray]] = {}
    results: list[dict[str, Any]] = []
    for row in rows:
        rid = row.get("resolution_id")
        if not _row_hash_ok(row):
            results.append({"resolution_id": rid, "status": "HASH_MISMATCH"})
            continue
        cutoff = str(row["knowledge_cutoff"])
        if cutoff not in panels:
            panels[cutoff] = F13.build_panel(
                read_market_observations(root, knowledge_cutoff=cutoff), start=HISTORY_START
            )
        panel = panels[cutoff]
        dates = [str(d) for d in panel["dates"]]
        origin = str(row["origin"])
        cell = str(row["cell"])
        spec = specs[cell]
        if origin not in dates:
            results.append({"resolution_id": rid, "status": "REPLAY_PRECONDITION_DRIFT",
                            "detail": "origin not in panel at recorded cutoff"})
            continue
        index = dates.index(origin)
        horizon = int(row["horizon_sessions"])
        if index + horizon >= len(dates):
            results.append({"resolution_id": rid, "status": "REPLAY_PRECONDITION_DRIFT",
                            "detail": "origin+h not matured in panel at recorded cutoff"})
            continue
        if spec["target"] == "vix_touch":
            labels = F13.labels_vix(panel["vix"], spec["K"], horizon)
        else:
            labels = F13.labels_rv(panel["rv21"], spec["theta"], horizon)
        label = labels[index]
        mismatches: list[str] = []
        if not np.isfinite(label):
            mismatches.append("label unresolved in recompute")
        else:
            if float(label) != float(row["label"]):
                mismatches.append(f"label {label} vs {row['label']}")
            probability = float(row["probability"])
            brier_model = round((probability - float(label)) ** 2, 8)
            if abs(brier_model - float(row["brier_model"])) > BRIER_TOLERANCE:
                mismatches.append(f"brier_model {brier_model} vs {row['brier_model']}")
            base_rate = clim.get(cell)
            if base_rate is not None:
                if abs(float(row["climatology_base_rate"]) - float(base_rate)) > 1e-9:
                    mismatches.append(
                        f"climatology_base_rate {base_rate} vs {row['climatology_base_rate']}"
                    )
                brier_clim = round((float(base_rate) - float(label)) ** 2, 8)
                if abs(brier_clim - float(row["brier_climatology"])) > BRIER_TOLERANCE:
                    mismatches.append(
                        f"brier_climatology {brier_clim} vs {row['brier_climatology']}"
                    )
            expected_resolved = dates[index + horizon]
            if str(row.get("resolved_session")) != expected_resolved:
                mismatches.append(
                    f"resolved_session {expected_resolved} vs {row.get('resolved_session')}"
                )
        results.append({
            "resolution_id": rid,
            "status": "PASS" if not mismatches else "SCORE_MISMATCH",
            **({"mismatches": mismatches} if mismatches else {}),
        })
    return {
        "ledger": str(RESOLUTION_LEDGER_RELATIVE).replace("\\", "/"),
        "rows": len(results),
        "pass": sum(1 for r in results if r["status"] == "PASS"),
        "precondition_drift": sum(
            1 for r in results if r["status"] == "REPLAY_PRECONDITION_DRIFT"
        ),
        "failures": [r for r in results if r["status"] in ("HASH_MISMATCH", "SCORE_MISMATCH")],
        "results": results,
    }
