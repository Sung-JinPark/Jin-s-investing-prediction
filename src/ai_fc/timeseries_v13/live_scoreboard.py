# -*- coding: utf-8 -*-
"""V13-VOL 라이브 전진 성적 — 화면에 올릴 **누적 현황**.

## 이것은 판정이 아니다

계약은 셀당 성숙 원점이 `minimum_matured_origins_per_cell`(60)에 닿기 전에는 강등도
승격도 하지 않는다고 고정했다. 그래서 이 표면은 **판정을 내리지 않는다** — 얼마나
모였는지(n/60)와, 모인 것까지의 누적 손실을 그대로 보여 준다. 문턱 전의 숫자를
성적표처럼 읽으면 표본이 얇을 때 우연히 좋은 셀을 실력으로 오해한다.

## 왜 홀드아웃 성적과 따로 두는가

홀드아웃(2015~2018)은 **1회 소모된 과거 표본**이고 이쪽은 **앞으로 쌓이는 표본**이다.
같은 칸에 나란히 놓으면 둘을 평균내고 싶어진다 — 계약이 금지한다. 화면에서도 절을
나누고, 홀드아웃 판정은 각 셀의 배지로만 따라붙는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import contracts as C
from .resolve import RESOLUTION_LEDGER_RELATIVE

LIVE_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live.jsonl")
TRAIL_POINTS = 40           # 셀당 스파크라인 상한 — 페이로드 예산을 지킨다


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def projection(root: Path, *, minimum: Optional[int] = None) -> dict[str, Any]:
    """셀별 누적 현황. 원장이 비어 있어도 **진행만** 담아 돌려준다."""
    resolutions = _read_jsonl(root / RESOLUTION_LEDGER_RELATIVE)
    origins = _read_jsonl(root / LIVE_LEDGER_RELATIVE)
    if minimum is None:
        try:
            gate = (C.load_contract_v13(root).get("live_forward_gate") or {})
            minimum = int(gate.get("minimum_matured_origins_per_cell") or 60)
        except Exception:  # noqa: BLE001 — 계약을 못 읽어도 화면은 진행을 보여 준다
            minimum = 60

    by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in resolutions:
        by_cell.setdefault(str(row.get("cell")), []).append(row)

    cells = []
    for name in C.CELL_ORDER:
        rows = sorted(by_cell.get(name, []), key=lambda r: str(r.get("resolved_session")))
        n = len(rows)
        entry: dict[str, Any] = {
            "cell": name,
            "matured": n,
            "minimum": minimum,
            "progress": round(min(1.0, n / minimum), 4) if minimum else 0.0,
            "gate_met": n >= minimum,
        }
        if rows:
            model = sum(float(r["brier_model"]) for r in rows) / n
            clim = sum(float(r["brier_climatology"]) for r in rows) / n
            entry.update({
                "brier_model": round(model, 5),
                "brier_climatology": round(clim, 5),
                # BSS 는 기후 대비 개선율. 기후 손실이 0 이면 정의되지 않는다.
                "bss": None if clim == 0 else round(1.0 - model / clim, 4),
                "last_resolved": rows[-1].get("resolved_session"),
                "trail": [round(float(r["brier_model"]), 4) for r in rows[-TRAIL_POINTS:]],
            })
        cells.append(entry)

    total = sum(c["matured"] for c in cells)
    return {
        "status": "accumulating" if total else "empty",
        # 판정하지 않는다는 사실을 페이로드에 박아 둔다 — 화면이 이 값을 읽고
        # '통과/실패' 같은 문구를 만들지 못하게.
        "verdict": None,
        "verdict_blocked_reason": f"셀당 성숙 원점 {minimum} 미만 — 계약이 판정을 막는다",
        "minimum": minimum,
        "origins_recorded": len(origins),
        "matured_total": total,
        "cells": cells,
    }
