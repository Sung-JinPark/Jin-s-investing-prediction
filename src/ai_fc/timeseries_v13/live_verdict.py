"""V13-VOL 라이브 전진 판정 — **읽기 전용** 사전 제작 verb.

## 왜 지금 만드는가

계약 `live_forward_gate`(2026-09-08 사전등록)는 "셀당 성숙 원점 60 도달 뒤 기후 대비 쌍대 Brier 손실차
CI90 하한 ≤ 0 이면 그 셀 표시 hold" 와 "y-block 귀무 통과율 ≤ 0.10" 을 규칙으로 고정했고, T7
(2026-09-10)은 "통과 3셀 중 2셀 이상 강등이면 종결" 을 추가했다. 그런데 그 **산술을 실행하는 코드가
없었다** — `timeseries-v13-vol-resolve` 는 채점만 한다("강등 판정은 하지 않는다"). 첫 셀이 60 에
닿는 2026-12 에 판정 코드를 그때 만들면 결과를 보고 만든 코드가 된다. 그래서 결과 전에 만든다.

## 이 verb 가 하지 않는 것

- 원장·포인터·계약에 **아무것도 쓰지 않는다**. 강등 적용은 사용자 승인 영수증 뒤의 별도 단계다.
- 규칙을 **바꾸지 않는다**. ℓ=13 · B=2000 · seed 20260907 · CI90 · 귀무 임계 0.10 · 최소 60 은 전부
  계약에서 읽는다. 결과를 본 뒤 이 파일의 산술을 고치는 것은 `gate_threshold_relaxation` 위반이다.
- 60 미만 셀에는 판정 문구를 만들지 않는다 — `insufficient_sample` 과 기술통계만 낸다.

## 퇴화 처리 (판정 '무효' — 강등도 확인도 아님)

사건이 0건이면 y-block 순열은 항등이라 귀무 통과율이 1.0 이 된다(홀드아웃 `vix30_h5` 가 정확히 이
모양으로 G4 실패). 계약 346행의 "초과 시 판정 무효화" 는 **강등이 아니라 판정 보류**다. 여기서는
`null_invalid: true` 로 표시만 하고, 실행 시점 degeneracy_guard(사건·국면 수)를 함께 낸다. 그 뒤의
귀결(보류·축적 계속)을 계약에 못 박는 것은 사용자 결정(V13-D12)이며 이 코드가 대신하지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import contracts as C
from . import scoring as S
from .resolve import (RESOLUTION_LEDGER_RELATIVE, _read_rows, distinct_origin_count,
                      distinct_resolutions, pinned_coefficients_sha)

NULL_DRAWS = 120       # holdout.py 와 같은 귀무 추출 수
NULL_BOOT_B = 300      # holdout.py `_decide` 와 같은 내부 부트스트랩 반복


def _cell_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    rows = distinct_resolutions(_read_rows(root / RESOLUTION_LEDGER_RELATIVE),
                                pinned_sha=pinned_coefficients_sha(root))
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_cell.setdefault(str(row.get("cell")), []).append(row)
    for name in by_cell:
        by_cell[name].sort(key=lambda r: str(r.get("origin")))      # 블록 부트스트랩은 시간 순서가 전제
    return by_cell


def _evaluate_cell(rows: list[dict[str, Any]], *, minimum: int, min_events: int, min_episodes: int,
                   draws: int) -> dict[str, Any]:
    n = len(rows)
    p = np.array([float(r["probability"]) for r in rows], float)
    y = np.array([float(r["label"]) for r in rows], float)
    base = np.array([float(r["climatology_base_rate"]) for r in rows], float)
    events = int((y == 1.0).sum())
    out: dict[str, Any] = {
        "matured": n, "minimum": minimum, "events": events, "non_events": int(n - events),
        "first_origin": rows[0]["origin"] if rows else None,
        "last_origin": rows[-1]["origin"] if rows else None,
    }
    if n:
        bs_model = float(((p - y) ** 2).mean()); bs_clim = float(((base - y) ** 2).mean())
        out.update({"brier_model": round(bs_model, 6), "brier_climatology": round(bs_clim, 6),
                    "bss": None if bs_clim == 0 else round(1.0 - bs_model / bs_clim, 4),
                    "expected_events_model": round(float(p.sum()), 3),
                    "expected_events_climatology": round(float(base.sum()), 3)})
    if n < minimum:
        out["status"] = "insufficient_sample"
        out["note"] = f"성숙 원점 {n}/{minimum} — 계약이 판정을 막는다(표본 부족)"
        return out

    # ── 60 도달: 계약 규칙을 그대로 실행한다 (적용은 하지 않는다) ──
    guard = S.degeneracy_report(y, min_events=min_events, min_episodes=min_episodes)
    out["degeneracy"] = guard
    d = ((base - y) ** 2) - ((p - y) ** 2)          # 양수 = 모형이 기후보다 낫다
    ci = S.block_boot_ci(d)                          # ℓ13 · B2000 · seed 20260907 · CI90 (계약 좌표)
    out["paired_loss_vs_climatology"] = ci
    would_hold = bool(ci["ci90"][0] <= 0)
    out["demotion_rule_would_hold"] = would_hold

    def _decide(perm: np.ndarray) -> bool:
        dd = ((base - perm) ** 2) - ((p - perm) ** 2)
        return bool(S.block_boot_ci(dd, b=NULL_BOOT_B)["ci90"][0] > 0)

    null_rate = S.y_block_null_pass_rate(y, _decide, draws=draws, seed=C.BOOTSTRAP_SEED)
    out["negative_control_pass_rate"] = null_rate
    null_invalid = bool(null_rate > 0.10)
    out["null_invalid"] = null_invalid
    out["null_degenerate"] = bool(events == 0 or events == n)
    if guard["verdict"] == "untestable_by_construction":
        out["status"] = "untestable_by_construction"
        out["note"] = "클래스별 사건 수 미달 — 판정 보류·축적 계속 (홀드아웃 가드 승계; 라이브 적용은 V13-D12 대기)"
    elif null_invalid:
        out["status"] = "verdict_void_negative_control"
        out["note"] = "건전 귀무 통과율 > 0.10 — 계약 346행에 따라 판정 무효(강등도 확인도 아님)"
    elif would_hold:
        out["status"] = "demotion_candidate"
        out["note"] = "기후 대비 쌍대 손실차 CI90 하한 ≤ 0 — demotion_rule 해당. 적용은 사용자 승인 뒤 별도 단계"
    else:
        out["status"] = "gate_passed_descriptive"
        out["note"] = "기후 대비 CI90 하한 > 0 ∧ 귀무 ≤ 0.10 — 강등 사유 없음(승격 아님·판정 적용 없음)"
    if guard["verdict"] == "episode_thin":
        out["episode_thin"] = True
    return out


def live_verdict(root: Path, *, draws: int = NULL_DRAWS, now: datetime | None = None) -> dict[str, Any]:
    """셀별 라이브 전진 판정 산술을 **인쇄용으로** 계산한다. 쓰기 0."""
    contract = C.load_contract_v13(root)
    gate = contract.get("live_forward_gate") or {}
    minimum = int(gate.get("minimum_matured_origins_per_cell") or 60)
    rules = ((contract.get("degeneracy_guard") or {}).get("rules") or {})
    min_events = int(rules.get("min_events_per_half_per_class") or 20)
    min_episodes = int(rules.get("min_episodes_per_half_per_class") or 5)
    publication = contract.get("publication") or {}
    pass_cells = [str(c) for c in (publication.get("holdout_pass_cells") or [])]
    t7 = ((contract.get("live_forward_termination") or {}).get("T7") or {})

    by_cell = _cell_rows(root)
    live_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    cells = {name: _evaluate_cell(by_cell.get(name, []), minimum=minimum, min_events=min_events,
                                  min_episodes=min_episodes, draws=draws) for name in C.CELL_ORDER}

    evaluable = [c for c in pass_cells if cells.get(c, {}).get("matured", 0) >= minimum]
    hold_candidates = [c for c in evaluable if cells[c].get("status") == "demotion_candidate"]
    t7_out = {
        "registered": bool(t7),
        "scope_cells": pass_cells,
        "cells_at_minimum": evaluable,
        "all_scope_cells_at_minimum": len(evaluable) == len(pass_cells) and bool(pass_cells),
        "demotion_candidates": hold_candidates,
        "would_trigger": (len(evaluable) == len(pass_cells) and bool(pass_cells) and len(hold_candidates) >= 2),
        "note": "T7 는 통과 3셀 전부가 60 에 닿은 뒤 2셀 이상 강등일 때 종결. 이 출력은 산술이며 적용이 아니다.",
    }
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "schema": "v13_vol_live_verdict_dry_run",
        "read_only": True,
        "writes": 0,
        "computed_at": stamp,
        "minimum_matured_origins_per_cell": minimum,
        "coefficients_sha256_pinned": pinned_coefficients_sha(root),
        "origins_recorded_distinct": distinct_origin_count(live_rows),
        "negative_control_draws": draws,
        "cells": cells,
        "T7": t7_out,
        "disclaimer": "참고 의견. 판정 적용(강등·종결)은 사용자 승인 영수증 뒤의 별도 단계이며 이 출력은 산술만 보여 준다.",
    }


def render_table(result: dict[str, Any]) -> str:
    lines = ["{:11s} {:>7s} {:>5s} {:>9s} {:>9s} {:>7s} {:>6s}  상태".format(
        "셀", "성숙", "사건", "Brier", "기후", "BSS", "귀무")]
    for name, c in result["cells"].items():
        bss = c.get("bss")
        null = c.get("negative_control_pass_rate")
        lines.append("{:11s} {:>3d}/{:<3d} {:>5d} {:>9s} {:>9s} {:>7s} {:>6s}  {}".format(
            name, c["matured"], c["minimum"], c["events"],
            "{:.4f}".format(c["brier_model"]) if "brier_model" in c else "—",
            "{:.4f}".format(c["brier_climatology"]) if "brier_climatology" in c else "—",
            "{:+.3f}".format(bss) if isinstance(bss, (int, float)) else "—",
            "{:.2f}".format(null) if isinstance(null, (int, float)) else "—",
            c["status"]))
    t7 = result["T7"]
    lines.append("T7: 범위 {} · 60도달 {} · 강등후보 {} · would_trigger={}".format(
        t7["scope_cells"], t7["cells_at_minimum"], t7["demotion_candidates"], t7["would_trigger"]))
    return "\n".join(lines)


def main_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1, default=float)
