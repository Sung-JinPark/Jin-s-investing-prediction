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

## 판정불가(제한) 라벨 — V13-D13 `live_claim_restriction`

사건 < 20 또는 국면(연속 구간) < 5 인 셀은 pass·BSS·배선·표시 승격을 **주장할 수 없다**.
라벨은 긍정 주장만 막는다 — 강등(demotion_rule)·T7 종결은 그대로 걸린다. 집계 시점의
누적값으로 매번 다시 계산하며(원장 무수정) 표본이 자라 임계를 넘으면 저절로 떨어진다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import contracts as C
from . import scoring as S
from .resolve import (RESOLUTION_LEDGER_RELATIVE, distinct_origin_count, distinct_resolutions,
                      pinned_coefficients_sha)

LIVE_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live.jsonl")
CLAIM_RESTRICTION_FORM = "restrictive_additive_only"
DEFAULT_MIN_EVENTS = 20       # 계약 live_claim_restriction.thresholds 를 못 읽을 때의 예비값(반창 가드와 동일)
DEFAULT_MIN_EPISODES = 5


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def claim_thresholds(contract: dict[str, Any] | None) -> dict[str, Any]:
    """계약 `live_claim_restriction` 의 임계·등록일. 키가 없거나 계약이 None 이면 20/5·registered None."""
    block = ((contract or {}).get("live_claim_restriction") or {})
    thresholds = block.get("thresholds") or {}
    registered = block.get("registered")
    return {
        "min_events": int(thresholds.get("min_events") or DEFAULT_MIN_EVENTS),
        "min_episodes": int(thresholds.get("min_episodes") or DEFAULT_MIN_EPISODES),
        "form": CLAIM_RESTRICTION_FORM,
        "registered": str(registered) if registered is not None else None,
    }


def claim_restriction_for(rows: list[dict[str, Any]], *, min_events: int, min_episodes: int) -> dict[str, Any]:
    """한 셀의 distinct 해상 행에서 판정불가(제한) 라벨을 계산한다.

    국면 단위는 `scoring.episode_runs` — `resolved_session` 순 라벨의 연속 구간 수(사건·비사건 각각).
    반환: episodes(행이 없으면 None) · claim_blocked · claim_block_reasons(실제 임계를 문자열에 박는다).
    """
    ordered = sorted(rows, key=lambda r: str(r.get("resolved_session")))
    if not ordered:
        return {"episodes": None, "claim_blocked": True, "claim_block_reasons": ["matured=0"]}
    labels = [float(r.get("label", 0.0)) for r in ordered]
    events = int(sum(1 for value in labels if value == 1.0))
    runs = S.episode_runs(labels)
    reasons: list[str] = []
    if events < min_events:
        reasons.append(f"events<{min_events}")
    if min(runs["event_runs"], runs["non_event_runs"]) < min_episodes:
        reasons.append(f"episodes<{min_episodes}")
    return {"episodes": {"event_runs": int(runs["event_runs"]), "non_event_runs": int(runs["non_event_runs"])},
            "claim_blocked": bool(reasons), "claim_block_reasons": reasons}


def projection(root: Path, *, minimum: Optional[int] = None) -> dict[str, Any]:
    """셀별 누적 현황. 원장이 비어 있어도 **진행만** 담아 돌려준다."""
    # 원점은 distinct 로 센다 — 2026-09-04 재동결 중복행(6셀 × 2)을 행 수로 세면 60 을 먼저 넘는다.
    resolutions = distinct_resolutions(_read_jsonl(root / RESOLUTION_LEDGER_RELATIVE),
                                       pinned_sha=pinned_coefficients_sha(root))
    origins = _read_jsonl(root / LIVE_LEDGER_RELATIVE)
    try:
        contract: dict[str, Any] | None = C.load_contract_v13(root)
    except Exception:  # noqa: BLE001 — 계약을 못 읽어도 화면은 진행을 보여 준다
        contract = None
    if minimum is None:
        gate = ((contract or {}).get("live_forward_gate") or {})
        minimum = int(gate.get("minimum_matured_origins_per_cell") or 60)
    restriction = claim_thresholds(contract)
    min_events, min_episodes = restriction["min_events"], restriction["min_episodes"]

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
            events = int(sum(1 for r in rows if float(r.get("label", 0.0)) == 1.0))
            entry.update({
                "brier_model": round(model, 5),
                "brier_climatology": round(clim, 5),
                # BSS 는 기후 대비 개선율. 기후 손실이 0 이면 정의되지 않는다.
                "bss": None if clim == 0 else round(1.0 - model / clim, 4),
                # 사건 수를 숫자 옆에 둔다 — 사건이 0 이면 BSS 는 '고정 기후가 평온기에 자명하게 지는'
                # 이득이지 실력이 아니다(홀드아웃 vix30 계열이 그 모양으로 무너졌다).
                "events": events,
                "expected_events_model": round(sum(float(r["probability"]) for r in rows), 2),
                "expected_events_climatology": round(sum(float(r["climatology_base_rate"]) for r in rows), 2),
                "skill_degenerate": events == 0,
                "last_resolved": rows[-1].get("resolved_session"),
                # trail(스파크라인) 은 화면이 읽지 않는 필드였다(2026-10-21 실측) — 임베드 예산만 먹어 제거.
            })
        # 판정불가(제한) — 긍정 주장만 막는 추가 라벨. 위 숫자·gate_met 은 그대로 둔다(강등 경로 무접촉).
        claim = claim_restriction_for(rows, min_events=min_events, min_episodes=min_episodes)
        if claim["episodes"] is not None:
            entry["episodes"] = claim["episodes"]
        entry["claim_blocked"] = claim["claim_blocked"]
        entry["claim_block_reasons"] = claim["claim_block_reasons"]
        cells.append(entry)

    total = sum(c["matured"] for c in cells)
    # pit_grade == late_capture 인 라이브 행의 distinct 원점 수 — 없는 행은 정상 행이다(오늘 0).
    late_capture = {str(r.get("as_of")) for r in origins
                    if r.get("as_of") and r.get("pit_grade") == "late_capture"}
    return {
        "status": "accumulating" if total else "empty",
        # 판정하지 않는다는 사실을 페이로드에 박아 둔다 — 화면이 이 값을 읽고
        # '통과/실패' 같은 문구를 만들지 못하게.
        "verdict": None,
        "verdict_blocked_reason": f"셀당 성숙 원점 {minimum} 미만 — 계약이 판정을 막는다",
        "minimum": minimum,
        "origins_recorded": distinct_origin_count(origins),
        "matured_total": total,
        "events_total": int(sum(c.get("events", 0) for c in cells)),
        "cells": cells,
        # V13-D13 — 셀 라벨의 임계 출처. 계약을 못 읽으면 20/5 예비값·registered None 으로 정직하게 표시.
        "claim_restriction": restriction,
        "late_capture_origins": len(late_capture),
    }
