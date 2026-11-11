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

## 판정불가(제한) — V13-D13 `live_claim_restriction` (추가 제약·완화 0)

사건 < 20 또는 국면 < 5 인 셀은 `positive_claim_allowed: false` — pass·BSS·배선·표시 승격을 주장할 수
없다. **status 산술은 그대로다**: 라벨은 긍정 주장만 막고 강등·T7(부정 귀결)은 막지도 미루지도 않는다.
임계·국면 계산은 live_scoreboard 와 같은 함수를 쓴다(화면과 verb 가 다른 라벨을 내지 않게).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import contracts as C
from . import scoring as S
from . import verdict_ledger as VL
from . import verdict_report as VR
from .live_scoreboard import claim_restriction_for, claim_thresholds
from .resolve import (HISTORY_START, RESOLUTION_LEDGER_RELATIVE, _read_rows, distinct_origin_count,
                      distinct_resolutions, pinned_coefficients_sha)

CLAIM_BLOCKED_NOTE = "positive claim blocked (V13-D13 live_claim_restriction)"

NULL_DRAWS = 120       # holdout.py 와 같은 귀무 추출 수
NULL_BOOT_B = 300      # holdout.py `_decide` 와 같은 내부 부트스트랩 반복


def _file_order_cell_rows(root: Path, *, as_of: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """셀별 distinct 해상 행 — **정렬하지 않는다**: (cell, origin) 이 해상 원장에 처음 기록된 순서(V13-D15 표본 규칙).

    값은 dedupe_rule(핀 sha 행 우선), 위치는 첫 등장 자리(dict 삽입 순서). `as_of` 가 있으면 먼저
    resolved_session <= as_of 행만 남긴다(실데이터 오라클 재현용).
    """
    raw = _read_rows(root / RESOLUTION_LEDGER_RELATIVE)
    if as_of:
        raw = [r for r in raw if str(r.get("resolved_session")) <= as_of]
    rows = distinct_resolutions(raw, pinned_sha=pinned_coefficients_sha(root))
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_cell.setdefault(str(row.get("cell")), []).append(row)
    return by_cell


def _cell_rows(root: Path, as_of: str | None = None) -> dict[str, list[dict[str, Any]]]:
    by_cell = {name: list(rows) for name, rows in _file_order_cell_rows(root, as_of=as_of).items()}
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

    # ── 60 도달: 계약 규칙(demotion_rule · negative_control)만으로 status 를 정한다 (적용은 하지 않는다) ──
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
    if null_invalid:
        out["status"] = "verdict_void_negative_control"
        out["note"] = "건전 귀무 통과율 > 0.10 — 계약 346행에 따라 판정 무효(강등도 확인도 아님·축적 계속)"
    elif would_hold:
        out["status"] = "demotion_candidate"
        out["note"] = "기후 대비 쌍대 손실차 CI90 하한 ≤ 0 — demotion_rule 해당. 적용은 사용자 승인 뒤 별도 단계"
    else:
        out["status"] = "gate_passed_descriptive"
        out["note"] = "기후 대비 CI90 하한 > 0 ∧ 귀무 ≤ 0.10 — 강등 사유 없음(승격 아님·판정 적용 없음)"
    # 가드는 status 를 정하지 않는다 — 반창(≈1000원점) 임계를 n=60 에 옮길 수 없고, 판정 보류형은 강등·종결을 느슨하게 한다.
    # 라벨(플래그)로만 병기한다: pass·BSS·배선·표시 승격을 '주장할 수 없음'의 근거.
    guard = S.degeneracy_report(y, min_events=min_events, min_episodes=min_episodes)
    out["degeneracy"] = guard
    out["events_below_holdout_guard"] = bool(min(events, n - events) < min_events)
    out["episode_thin"] = bool(guard["min_episodes"] < min_episodes)
    return out


def resolution_disclosure(n: int, h: int, block: int = C.BLOCK_LENGTH) -> dict[str, Any]:
    """해상도 공시 — ℓ=13 정지블록에서 n=60 은 재표집당 ≈4.6 블록, y-block 순열 공간은 (ceil(n/ℓ))! = 120."""
    import math
    blocks = math.ceil(n / block) if n else 0
    return {"effective_blocks": round(n / block, 2) if n else 0.0,
            "label_overlap_ratio": round(h / block, 2),
            "permutation_space": math.factorial(blocks) if blocks else 0,
            "low_resolution": bool(n and (n / block < 8 or h > block))}


def verdict_parameters(contract: dict[str, Any]) -> dict[str, Any]:
    """live_forward_gate·degeneracy_guard·T7·V13-D13 임계 — print(live-verdict) 와 apply 가 같은 값을 쓴다."""
    gate = contract.get("live_forward_gate") or {}
    rules = ((contract.get("degeneracy_guard") or {}).get("rules") or {})
    publication = contract.get("publication") or {}
    return {
        "minimum": int(gate.get("minimum_matured_origins_per_cell") or 60),
        "min_events": int(rules.get("min_events_per_half_per_class") or 20),
        "min_episodes": int(rules.get("min_episodes_per_half_per_class") or 5),
        "pass_cells": [str(c) for c in (publication.get("holdout_pass_cells") or [])],
        "t7": ((contract.get("live_forward_termination") or {}).get("T7") or {}),
        "claim": claim_thresholds(contract),          # V13-D13 임계(20/5) — 계약을 못 읽으면 예비값
    }


def checkpoint_step(contract: dict[str, Any]) -> int:
    block = contract.get("live_verdict_application") or {}
    return int(((block.get("checkpoints") or {}).get("step")) or VL.DEFAULT_STEP)


def load_report_panel(root: Path) -> tuple[dict[str, Any] | None, str]:
    """보고 확장(기계 확정)용 V13 패널 — 최신 개정 아카이브(PIT 아님). 실패·빈 패널이면 archive_unavailable."""
    try:
        from ..timeseries_v2.market_archive import read_market_observations
        from . import features as F

        panel = F.build_panel(read_market_observations(root), start=HISTORY_START)
    except Exception:  # noqa: BLE001 — 인쇄 전용 필드라 대체값 없이 비운다
        return None, "archive_unavailable"
    if panel is None or len(panel.get("dates", [])) == 0:
        return None, "archive_unavailable"
    return panel, "ok"


def _validated_as_of(value: str) -> str:
    """`--as-of` 는 YYYY-MM-DD 만 받는다. 절단은 문자열 비교라 '2026-11-9' 같은 표기는 조용히 틀린 표본을 만든다."""
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"--as-of must be YYYY-MM-DD, got {value!r}") from exc
    if len(text) != 10 or parsed.isoformat() != text:
        raise ValueError(f"--as-of must be YYYY-MM-DD, got {value!r}")
    return text


def live_verdict(root: Path, *, draws: int = NULL_DRAWS, now: datetime | None = None,
                 as_of: str | None = None, panel: dict[str, Any] | None = None) -> dict[str, Any]:
    """셀별 라이브 전진 판정 산술을 **인쇄용으로** 계산한다. 쓰기 0.

    V13-D14: 셀별 `report`(로그점수·Murphy·두 반창 상수·RV 기계확정 — 판정 다리 아님),
    `checkpoint`(도달한 최대 체크포인트 k 의 절단 표본 산술, draws 120 고정 — apply 가 쓸 값과 같다),
    `applied`(적용 원장 요약). `as_of` 는 resolved_session <= as_of 절단(재현용).
    """
    if as_of is not None:
        as_of = _validated_as_of(as_of)
    contract = C.load_contract_v13(root)
    params = verdict_parameters(contract)
    minimum = params["minimum"]
    min_events = params["min_events"]
    min_episodes = params["min_episodes"]
    pass_cells = params["pass_cells"]
    t7 = params["t7"]
    claim = params["claim"]
    step = checkpoint_step(contract)

    by_cell = _cell_rows(root, as_of=as_of)
    file_order = _file_order_cell_rows(root, as_of=as_of)
    if panel is None:
        panel, panel_status = load_report_panel(root)
    else:
        panel_status = "ok" if len(panel.get("dates", [])) else "archive_unavailable"
    half = VR.design_half_constants(root, contract)
    applications = VL.read_applications(root)
    live_rows = _read_rows(root / C.LIVE_LEDGER_RELATIVE)
    horizons = {spec["name"]: int(spec["h"]) for spec in C.cell_specs()}
    cells = {}
    for name in C.CELL_ORDER:
        rows = by_cell.get(name, [])
        cell = _evaluate_cell(rows, minimum=minimum, min_events=min_events,
                              min_episodes=min_episodes, draws=draws)
        cell["resolution"] = resolution_disclosure(cell["matured"], horizons[name])
        # 판정불가(제한) — status 는 위에서 이미 정해졌다. 여기서는 긍정 주장 가능 여부만 병기한다.
        label = claim_restriction_for(rows, min_events=claim["min_events"], min_episodes=claim["min_episodes"])
        cell["positive_claim_allowed"] = not label["claim_blocked"]
        cell["claim_block_reasons"] = label["claim_block_reasons"]
        if cell.get("status") == "gate_passed_descriptive" and label["claim_blocked"]:
            cell["status_note"] = CLAIM_BLOCKED_NOTE
        # ── V13-D14 보고 확장 — status 를 읽기만 한다(판정 다리 아님) ──
        cell["report"] = VR.report_extension(name, rows, panel=panel, panel_status=panel_status,
                                             half_constants=half)
        k = VL.reached_checkpoint(len(rows), first=minimum, step=step)
        if k is not None:
            sample = VL.checkpoint_sample(file_order.get(name, []), k)   # 첫 기록 순 앞 k → origin 재정렬
            cp = _evaluate_cell(sample, minimum=minimum, min_events=min_events,
                                min_episodes=min_episodes, draws=NULL_DRAWS)   # CLI --draws 와 무관하게 120
            cell["checkpoint"] = {"k": k, "status": cp["status"],
                                  "ci90": cp["paired_loss_vs_climatology"]["ci90"],
                                  "negative_control_pass_rate": cp["negative_control_pass_rate"],
                                  "draws": NULL_DRAWS, "sample_rule": "ledger_first_recorded_k"}
        cell["applied"] = VL.cell_application_summary(applications, name)
        cells[name] = cell

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
    block = contract.get("live_forward_verdict_report_extension") or {}
    matured = {name: int(cells[name]["matured"]) for name in cells}
    return {
        "schema": "v13_vol_live_verdict_dry_run",
        "read_only": True,
        "writes": 0,
        "computed_at": stamp,
        "minimum_matured_origins_per_cell": minimum,
        "coefficients_sha256_pinned": pinned_coefficients_sha(root),
        "origins_recorded_distinct": distinct_origin_count(live_rows),
        "negative_control_draws": draws,
        "claim_restriction": claim,
        "cells": cells,
        "T7": t7_out,
        "report_extension": {"registered": block.get("registered"), "approval_receipt": block.get("approval_receipt"),
                             "print_only": True, "judgement_leg": False},
        "applications": {"status": applications["status"], "demoted_cells": sorted(applications["demoted"]),
                         "t7_applied": applications["t7"] is not None,
                         "pending": VL.pending_checkpoints(matured, applications, pass_cells,
                                                           first=minimum, step=step)},
        "as_of": as_of,
        "disclaimer": "참고 의견. 판정 적용(강등·종결)은 사용자 승인 영수증 뒤의 별도 단계이며 이 출력은 산술만 보여 준다.",
    }


def render_table(result: dict[str, Any]) -> str:
    lines = ["{:11s} {:>7s} {:>5s} {:>9s} {:>9s} {:>7s} {:>6s} {:>6s} {:>4s}  상태 (플래그)".format(
        "셀", "성숙", "사건", "Brier", "기후", "BSS", "귀무", "블록", "주장")]
    for name, c in result["cells"].items():
        bss = c.get("bss")
        null = c.get("negative_control_pass_rate")
        flags = [k for k in ("events_below_holdout_guard", "episode_thin", "null_degenerate") if c.get(k)]
        res = c.get("resolution") or {}
        lines.append("{:11s} {:>3d}/{:<3d} {:>5d} {:>9s} {:>9s} {:>7s} {:>6s} {:>6s} {:>4s}  {}{}{}".format(
            name, c["matured"], c["minimum"], c["events"],
            "{:.4f}".format(c["brier_model"]) if "brier_model" in c else "—",
            "{:.4f}".format(c["brier_climatology"]) if "brier_climatology" in c else "—",
            "{:+.3f}".format(bss) if isinstance(bss, (int, float)) else "—",
            "{:.2f}".format(null) if isinstance(null, (int, float)) else "—",
            "{:.1f}".format(res["effective_blocks"]) if res else "—",
            "가능" if c.get("positive_claim_allowed") else "제한",      # V13-D13 — 긍정 주장 가능 여부
            c["status"], " [" + ",".join(flags) + "]" if flags else "",
            " (" + c["status_note"] + ")" if c.get("status_note") else ""))
    t7 = result["T7"]
    lines.append("T7: 범위 {} · 60도달 {} · 강등후보 {} · would_trigger={}".format(
        t7["scope_cells"], t7["cells_at_minimum"], t7["demotion_candidates"], t7["would_trigger"]))
    lines.extend(render_report_block(result))
    return "\n".join(lines)


def _fmt(value: Any, spec: str = "{:.4f}") -> str:
    return spec.format(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else "—"


def render_report_block(result: dict[str, Any]) -> list[str]:
    """V13-D14 보조 블록 — 기존 표 아래. 판정 다리 아님. 우열 문장 없음(숫자만 대칭 병기)."""
    cells = result.get("cells") or {}
    if not any("report" in c for c in cells.values()):
        return []
    lines = ["", "보고(판정 다리 아님 · V13-D14 · 반창 상수는 대칭 병기, 단일 국면 표본)",
             "{:11s} {:31s} {:13s} {:13s} {}".format("셀", "로그 모형/기후/전반/후반", "rel/res", "기계확정 k/e",
                                                     "체크포인트")]
    for name, c in cells.items():
        rep = c.get("report") or {}
        if not rep.get("n"):
            continue
        ls = rep.get("log_score") or {}
        half = (rep.get("constant_baselines") or {}).get("design_half_constants") or {}
        early = (half.get("early_fit") or {}).get("log_score") if half.get("status") == "ok" else None
        late = (half.get("late_fit") or {}).get("log_score") if half.get("status") == "ok" else None
        logs = "/".join(_fmt(v) for v in (ls.get("model"), ls.get("climatology"), early, late))
        rel = rep.get("reliability") or {}
        relres = "{}/{}".format(_fmt(rel.get("reliability"), "{:.3f}"), _fmt(rel.get("resolution"), "{:.3f}"))
        mech = rep.get("mechanical") or {}
        if mech.get("status") in {"ok", "partial"}:
            mk = "{}/{}".format(mech.get("mechanical_positives"), mech.get("events"))
        elif mech.get("status") == "invariant_violation":
            mk = "불변식위반!"
        elif mech.get("status") == "archive_unavailable":
            mk = "아카이브없음"
        else:
            mk = "—"
        cp = c.get("checkpoint")
        cps = "k{} {}".format(cp["k"], cp["status"]) if cp else "—"
        applied = c.get("applied")
        if applied:
            cps += " · 적용 k{} {}".format(applied.get("checkpoint"), applied.get("outcome"))
        lines.append("{:11s} {:31s} {:13s} {:13s} {}".format(name, logs, relres, mk, cps))
    apps = result.get("applications") or {}
    pending = apps.get("pending") or []
    lines.append("적용 원장: {} · 강등 {} · T7 {} · 도래 {}".format(
        apps.get("status"), apps.get("demoted_cells") or [], "적용" if apps.get("t7_applied") else "없음",
        ["{}:k{}".format(p.get("cell"), p.get("checkpoint")) if not p.get("error") else p["error"] for p in pending]))
    return lines


def main_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1, default=float)
