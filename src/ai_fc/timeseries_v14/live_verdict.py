"""V14 조건부 전이 라이브 전진 판정 — **읽기 전용** verb. 계약 `live_forward_gate` 산술을 그대로 실행해 인쇄만 한다.

## 산술 (계약 2026-10-21 사전등록 — 결과 전, 라이브 원장 0행 시점에 고정)

셀별 (cell, origin) distinct · 성숙 · 조건 충족 원점 n:
1. n < 60                                   → insufficient_sample ('판정 전(n/60)' — Brier·개선% 숫자 없음, bss_display)
2. 사건·비사건 **각각** >= max(5, ceil(0.1·n)) 미달 → untestable (판정 보류·축적 계속 — 강등 아님·확인 아님)
3. d = BS_clim − BS_model (양수 = 모형 우세), 정지 블록 ℓ13 · B2000 · seed 20261021 · CI90 — 공유 scoring.block_boot_ci
4. y-block(ℓ13) 귀무 통과율 > 0.10           → verdict_void_negative_control (판정 무효 — 강등 아님·확인 아님·축적 계속)
   귀무 구성(계약 live_forward_gate.negative_control_construction)은 V13 live_verdict 와 같다: 라벨 블록 순열 120회마다
   같은 쌍대 CI(ℓ13 · B=300 · seed 20261021)의 하한 > 0 비율. 추출 수가 120 이 아니면 계산을 거부하고,
   통과율이 유한하지 않으면(정의 안 됨) 귀무를 건너뛰지 않고 verdict_void_negative_control 로 닫는다.
5. CI90 하한 <= 0                            → demotion_candidate (적용은 사용자 승인 뒤 별도 단계)
6. 그 밖                                     → gate_passed_descriptive (승격 아님)
국면 수(scoring.episode_runs)는 **라벨만**(episode_thin) — 보류·판정 사유가 아니다.

## 범위 — champion 만 판정 범위, shadow 는 인쇄만

계약 live_pointer.champion_cells 가 판정 범위다(데이터 — 어떤 분할이든 받는다). shadow 셀도 같은 산술로 계산·인쇄하지만
`in_verdict_scope: false` 이며 T7 분모·강등·승격 주장에 들어가지 않는다.
T7(termination_T7_form): 판정 가능(status ∈ {demotion_candidate, gate_passed_descriptive}) **champion** 셀이 2개 이상일 때
그중 과반이 demotion_candidate 면 would_trigger. champion 셀이 2개 미만이면 T7 은 구조상 걸릴 수 없다 — 그렇게 인쇄한다.

## 하지 않는 것

원장·포인터·계약에 아무것도 쓰지 않는다. 규칙을 바꾸지 않는다 — 계약 문면(min_events_rule · T7 rule · 귀무 임계 ·
uncertainty · negative_control_construction 의 draws 120·B=300·non-finite 무효)이 아래 상수와 다르면 계산하지 않고
raise 한다(결과 후 산술 변경 = gate_threshold_relaxation 위반). 호출부의 draws 도 120 외에는 거부한다(CLI 옵션 없음).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v13 import scoring as S
from ..timeseries_v13.resolve import distinct_resolutions
from . import contracts as C
from .pipeline import _read_rows
from .resolve import pinned_coefficients_sha

NULL_DRAWS = 120            # V13 live_verdict·holdout 과 같은 귀무 추출 수
NULL_BOOT_B = 300           # 귀무 내부 부트스트랩 반복 (V13 live_verdict `_decide` 와 같다)
NULL_THRESHOLD = 0.10
MIN_EVENTS_FLOOR = 5
MIN_EVENTS_FRACTION = 0.1
TESTABLE = ("demotion_candidate", "gate_passed_descriptive")
REGISTERED_FORMS = {        # 계약 문면 ↔ 코드 산술 대조. 하나라도 빠지면 verb 는 계산하지 않는다.
    "degeneracy.min_events_rule": "max(5, ceil(0.1·n))",
    "negative_control": "0.10",
    "uncertainty": "seed 20261021",
    "termination_T7_form.rule": "2개 이상",
    "negative_control_construction.decide": f"B={NULL_BOOT_B}",
    "negative_control_construction.non_finite_rate": "verdict_void_negative_control",
}


def min_events_required(n: int) -> int:
    """계약 degeneracy.min_events_rule — 사건·비사건 각각 >= max(5, ceil(0.1·n))."""
    return max(MIN_EVENTS_FLOOR, math.ceil(MIN_EVENTS_FRACTION * n))


def _require_registered_draws(draws: Any) -> None:
    """귀무 추출 수는 계약 negative_control_construction.draws(120) 하나뿐 — 다른 값(0 포함)이면 계산하지 않는다.

    draws=0 이면 통과율이 NaN 이 되어 `NaN > 0.10` 이 거짓 → 귀무를 건너뛴 채 강등·통과가 나온다. 그 경로를 입구에서 닫는다.
    """
    if isinstance(draws, bool) or not isinstance(draws, int) or draws != NULL_DRAWS:
        raise C.TimeSeriesV14Error(f"negative-control draws must be the registered {NULL_DRAWS} "
                                   f"(live_forward_gate.negative_control_construction.draws) — got {draws!r}; "
                                   "the verb refuses to compute a null that differs from the registered construction")


def _lookup(block: dict[str, Any], dotted: str) -> str:
    value: Any = block
    for part in dotted.split("."):
        value = (value or {}).get(part) if isinstance(value, dict) else None
    return str(value or "")


def registered_form(contract: dict[str, Any]) -> dict[str, Any]:
    """live_forward_gate 문면이 코드 산술과 같은지 대조하고 판정 좌표를 돌려준다."""
    gate = contract.get("live_forward_gate") or {}
    for dotted, needle in REGISTERED_FORMS.items():
        if needle not in _lookup(gate, dotted):
            raise C.TimeSeriesV14Error(f"live_forward_gate.{dotted} no longer states '{needle}' — "
                                       "the verb refuses to compute a rule that differs from the registered text")
    if "과반" not in _lookup(gate, "termination_T7_form.rule"):
        raise C.TimeSeriesV14Error("live_forward_gate.termination_T7_form.rule no longer states a majority (과반)")
    construction = gate.get("negative_control_construction")
    registered_draws = construction.get("draws") if isinstance(construction, dict) else None
    if isinstance(registered_draws, bool) or registered_draws != NULL_DRAWS:
        raise C.TimeSeriesV14Error(f"live_forward_gate.negative_control_construction.draws no longer states {NULL_DRAWS} "
                                   f"(got {registered_draws!r}) — the verb refuses to compute a different null")
    min_episodes = int((contract.get("episode_guard") or {}).get("min_episodes") or 5)
    return {"minimum": C.MIN_MATURED, "block_length": C.BLOCK, "replicates": C.B, "seed": C.SEED,
            "interval": list(C.CI_INTERVAL), "null_threshold": NULL_THRESHOLD,
            "null_draws": NULL_DRAWS, "null_boot_replicates": NULL_BOOT_B,
            "min_events_rule": "max(5, ceil(0.1·n)) for events and non-events each",
            "episode_label_min_runs": min_episodes, "registered": str(gate.get("registered") or "")}


def _cell_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    rows = distinct_resolutions(_read_rows(root / C.RESOLUTION_LEDGER_RELATIVE), pinned_sha=pinned_coefficients_sha(root))
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_cell.setdefault(str(row.get("cell")), []).append(row)
    for name in by_cell:
        by_cell[name].sort(key=lambda r: str(r.get("origin")))      # 블록 부트스트랩은 시간 순서가 전제
    return by_cell


def evaluate_cell(rows: list[dict[str, Any]], *, draws: int = NULL_DRAWS, min_episodes: int = 5) -> dict[str, Any]:
    _require_registered_draws(draws)
    n = len(rows)
    p = np.array([float(r["probability"]) for r in rows], float)
    y = np.array([float(r["label"]) for r in rows], float)
    base = np.array([float(r["climatology_base_rate"]) for r in rows], float)
    events = int((y == 1.0).sum())
    need = min_events_required(n)
    runs = S.episode_runs(y)
    out: dict[str, Any] = {
        "matured": n, "minimum": C.MIN_MATURED, "events": events, "non_events": int(n - events),
        "min_events_required": need,
        "expected_events_model": round(float(p.sum()), 3),           # 모형 Σp — 판정 전에도 내는 유일한 확률 합
        "expected_events_climatology": round(float(base.sum()), 3),
        "first_origin": rows[0]["origin"] if rows else None, "last_origin": rows[-1]["origin"] if rows else None,
        "episodes": {"event_runs": int(runs["event_runs"]), "non_event_runs": int(runs["non_event_runs"])},
        # 국면 수는 라벨만 — status 를 정하지 않는다(계약 degeneracy.episode_count)
        "episode_thin": bool(n and min(runs["event_runs"], runs["non_event_runs"]) < min_episodes),
        "roles_recorded": sorted({str(r.get("role")) for r in rows}),
    }
    if n < C.MIN_MATURED:
        out["status"] = "insufficient_sample"
        out["note"] = f"판정 전({n}/{C.MIN_MATURED}) — 계약이 판정을 막는다(표본 부족). Brier·개선% 는 내지 않는다"
        return out
    if events < need or (n - events) < need:
        out["status"] = "untestable"
        out["note"] = (f"사건 {events} · 비사건 {n - events} 중 하나가 max(5, ceil(0.1·{n}))={need} 미만 — "
                       "판정 보류·축적 계속(강등 아님·확인 아님)")
        return out

    d = ((base - y) ** 2) - ((p - y) ** 2)                 # 양수 = 모형이 기후보다 낫다
    ci = S.block_boot_ci(d, seed=C.SEED, b=C.B, block=C.BLOCK)

    def _decide(perm: np.ndarray) -> bool:
        dd = ((base - perm) ** 2) - ((p - perm) ** 2)
        return bool(S.block_boot_ci(dd, seed=C.SEED, b=NULL_BOOT_B, block=C.BLOCK)["ci90"][0] > 0)

    null_rate = float(S.y_block_null_pass_rate(y, _decide, draws=draws, seed=C.SEED, block=C.BLOCK))
    null_finite = math.isfinite(null_rate)
    bs_model = float(((p - y) ** 2).mean()); bs_clim = float(((base - y) ** 2).mean())
    out.update({
        "paired_loss_vs_climatology": ci,
        "demotion_rule_would_hold": bool(ci["ci90"][0] <= 0),
        # 정의되지 않은 통과율은 숫자로 내지 않는다(NaN 은 JSON 이 아니다) — null + negative_control_finite=false 로 공시
        "negative_control_pass_rate": null_rate if null_finite else None,
        "negative_control_finite": null_finite,
        "null_invalid": bool(not null_finite or null_rate > NULL_THRESHOLD),
    })
    if not null_finite:
        # 계약 negative_control_construction.non_finite_rate — `NaN > 0.10` 이 거짓이라 귀무를 통과한 것처럼 읽히는 경로를 닫는다
        out["status"] = "verdict_void_negative_control"
        out["note"] = "y-block 귀무 통과율이 정의되지 않음(non-finite) — 판정 무효(강등 아님·확인 아님·축적 계속)"
        return out
    if null_rate > NULL_THRESHOLD:
        out["status"] = "verdict_void_negative_control"
        out["note"] = "y-block 귀무 통과율 > 0.10 — 판정 무효(강등 아님·확인 아님·축적 계속)"
        return out
    out.update({"brier_model": round(bs_model, 6), "brier_climatology": round(bs_clim, 6),
                "bss": None if bs_clim == 0 else round(1.0 - bs_model / bs_clim, 4)})
    if ci["ci90"][0] <= 0:
        out["status"] = "demotion_candidate"
        out["note"] = "기후 대비 쌍대 손실차 CI90 하한 <= 0 — demotion_rule 해당. 적용은 사용자 승인 뒤 별도 단계"
    else:
        out["status"] = "gate_passed_descriptive"
        out["note"] = "기후 대비 CI90 하한 > 0 ∧ 귀무 <= 0.10 — 강등 사유 없음(승격 아님·판정 적용 없음)"
    return out


def t7_report(cells: dict[str, dict[str, Any]], champion_cells: list[str]) -> dict[str, Any]:
    """termination_T7_form — champion 범위만. untestable·무효·표본 부족 셀은 분모 밖."""
    testable = [c for c in champion_cells if cells.get(c, {}).get("status") in TESTABLE]
    demoted = [c for c in testable if cells[c]["status"] == "demotion_candidate"]
    by_construction = len(champion_cells) < 2
    would = (not by_construction) and len(testable) >= 2 and len(demoted) * 2 > len(testable)
    if by_construction:
        note = (f"T7 cannot trigger: champion scope has {len(champion_cells)} cell(s) — the rule needs >= 2 testable "
                "champion cells. Shadow cells never enter the T7 denominator.")
    elif len(testable) < 2:
        note = f"T7 not armed yet: {len(testable)} testable champion cell(s) < 2."
    else:
        note = f"T7 majority test: {len(demoted)}/{len(testable)} testable champion cells are demotion candidates."
    return {"scope_cells": list(champion_cells), "testable_cells": testable, "demotion_candidates": demoted,
            "cannot_trigger_by_construction": by_construction, "would_trigger": bool(would), "note": note,
            "applies_termination": False}


def live_verdict(root: Path, *, draws: int = NULL_DRAWS, now: datetime | None = None) -> dict[str, Any]:
    """셀별 라이브 전진 판정 산술을 **인쇄용으로** 계산한다. 쓰기 0. draws 는 등록값(120) 외에는 거부한다."""
    _require_registered_draws(draws)
    contract = C.load_contract_v14(root)
    cfg = C.live_pointer_config(contract)
    form = registered_form(contract)
    by_cell = _cell_rows(root)
    live_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    cells: dict[str, dict[str, Any]] = {}
    for name in C.CELL_ORDER:
        cell = evaluate_cell(by_cell.get(name, []), draws=draws, min_episodes=form["episode_label_min_runs"])
        role = cfg["roles"][name]
        cell["role"] = role
        cell["in_verdict_scope"] = role == "champion"
        cell["role_mismatch_in_rows"] = bool(cell["roles_recorded"]) and cell["roles_recorded"] != [role]
        cells[name] = cell
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "schema": "v14_conditional_live_verdict_dry_run",
        "read_only": True,
        "writes": 0,
        "computed_at": stamp,
        "registered_form": form,
        "draws": draws,
        "coefficients_sha256_pinned": pinned_coefficients_sha(root),
        "origins_recorded_distinct": len({str(r.get("as_of")) for r in live_rows if r.get("as_of")}),
        "champion_cells": cfg["champion_cells"],
        "shadow_cells": cfg["shadow_cells"],
        "cells": cells,
        "T7": t7_report(cells, cfg["champion_cells"]),
        "disclaimer": ("참고 의견. 판정 적용(강등·종결)은 사용자 승인 영수증 뒤의 별도 단계이며 이 출력은 산술만 보여 준다. "
                       "shadow 셀은 판정 범위 밖(in_verdict_scope=false)이며 표시되지 않는다."),
    }


def render_table(result: dict[str, Any]) -> str:
    lines = ["{:11s} {:8s} {:>7s} {:>5s} {:>4s} {:>8s} {:>8s} {:>7s} {:>6s}  상태 (플래그)".format(
        "셀", "역할", "성숙", "사건", "필요", "모형Σp", "기후Σp", "BSS", "귀무")]
    for name, c in result["cells"].items():
        bss = c.get("bss"); null = c.get("negative_control_pass_rate")
        flags = [k for k in ("episode_thin", "role_mismatch_in_rows") if c.get(k)]
        if c.get("negative_control_finite") is False:
            flags.append("null_non_finite")
        if not c["in_verdict_scope"]:
            flags.append("out_of_verdict_scope")
        lines.append("{:11s} {:8s} {:>3d}/{:<3d} {:>5d} {:>4d} {:>8.3f} {:>8.3f} {:>7s} {:>6s}  {}{}".format(
            name, c["role"], c["matured"], c["minimum"], c["events"], c["min_events_required"],
            c["expected_events_model"], c["expected_events_climatology"],
            "{:+.3f}".format(bss) if isinstance(bss, (int, float)) else "—",
            "{:.2f}".format(null) if isinstance(null, (int, float)) else "—",
            c["status"], " [" + ",".join(flags) + "]" if flags else ""))
    t7 = result["T7"]
    lines.append("T7: 범위 {} · 판정가능 {} · 강등후보 {} · would_trigger={}".format(
        t7["scope_cells"], t7["testable_cells"], t7["demotion_candidates"], t7["would_trigger"]))
    lines.append(t7["note"])
    return "\n".join(lines)


def main_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1, default=float)
