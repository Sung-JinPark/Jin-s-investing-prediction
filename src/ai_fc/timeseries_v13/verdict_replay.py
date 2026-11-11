"""V13-D15 다중 체크포인트 거짓 강등률 추정 — 설계창(2007~2014) 결정론 재생 (읽기 전용·CLI 없음·원장 쓰기 0).

목적: 사전 승인(V13-D15)의 크기 근거를 [미검증] 문장 대신 수치로 공시한다(계약 `disclosed_limit`·KNOWN_LIMITS).
방향이 제한뿐이라 이 수치가 무엇이든 등록을 막지 않는다 — 공시용 base rate 참조다.

절차(CLAUDE.md 원칙 5 수치모델 예외 — LLM 무관):
1. 설계창만 패널로 만든다(end=2014-12-31). 2015 이후(홀드아웃·봉인 바이트)로는 아무것도 계산하지 않는다.
2. 동결 계수(계약 sha 3자 대조)로 원점별 p — `holdout._feature_matrix`/`_predict` 를 그대로 재사용한다(적합 함수 없음).
   라벨 창이 2014-12-31 안에서 끝나는 원점만(패널 절단으로 자동).
3. 셀별로 원점을 겹치지 않는 `episode` 원점 에피소드로 자르고, 각 에피소드 앞 60·80·100·120 원점에
   `live_verdict._evaluate_cell(draws=120)` — 적용 verb 와 같은 산술.
4. 셀별 rate_any_checkpoint(하나라도 demotion_candidate)·rate_k60_only·n_episodes·Wilson 90%(에피소드 iid 가정).

caveat: ① 계수가 같은 설계창에 적합돼 in-sample skill 과대 → 라이브 거짓 강등률의 **하한 성격** ② 국면 의존(GFC 가
몇 에피소드에 몰림) ③ 120원점 길이·비중첩 분할은 이 추정을 위해 고른 하이퍼파라미터 ④ base rate 참조이지 판정·승격 근거 아님.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import contracts as C
from .live_verdict import NULL_DRAWS, _evaluate_cell, verdict_parameters

DESIGN_START, DESIGN_END = C.DESIGN_WINDOW
CHECKPOINTS = (60, 80, 100, 120)
WILSON_Z90 = 1.6448536269514722
CAVEATS = (
    "계수가 같은 설계창에 적합돼 in-sample skill 이 과대 — 라이브 거짓 강등률의 하한 성격",
    "에피소드 간 국면 의존(GFC 2008~09 가 몇 에피소드에 몰림) — Wilson 구간은 에피소드 iid 가정",
    "120원점 길이·비중첩 분할은 이 추정을 위해 고른 하이퍼파라미터",
    "base rate 참조이지 판정·승격 근거 아님",
)


def wilson_interval(successes: int, n: int, z: float = WILSON_Z90) -> list[float] | None:
    if n <= 0:
        return None
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def replay_rows(rows_by_cell: dict[str, list[dict[str, Any]]], params: dict[str, Any], *, episode: int = 120,
                checkpoints: Iterable[int] = CHECKPOINTS) -> dict[str, Any]:
    """셀별 origin 순 행 → 비중첩 에피소드 × 체크포인트 산술. 핵심 루프(합성 스모크 테스트 대상)."""
    checkpoints = tuple(int(k) for k in checkpoints)
    if not checkpoints or max(checkpoints) > episode or min(checkpoints) < params["minimum"]:
        raise ValueError("checkpoints must lie within [minimum, episode]")
    out: dict[str, Any] = {}
    for cell, rows in rows_by_cell.items():
        rows = sorted(rows, key=lambda r: str(r["origin"]))
        if any(str(r["origin"]) > DESIGN_END for r in rows):
            raise ValueError("design replay must not read origins after the design window")
        episodes = [rows[i:i + episode] for i in range(0, len(rows) - episode + 1, episode)]
        statuses: list[dict[str, str]] = []
        for chunk in episodes:
            per = {}
            for k in checkpoints:
                v = _evaluate_cell(chunk[:k], minimum=params["minimum"], min_events=params["min_events"],
                                   min_episodes=params["min_episodes"], draws=NULL_DRAWS)
                per[str(k)] = v["status"]
            statuses.append(per)
        n = len(statuses)
        any_hits = sum(1 for s in statuses if "demotion_candidate" in s.values())
        k60_hits = sum(1 for s in statuses if s.get(str(checkpoints[0])) == "demotion_candidate")
        void = sum(1 for s in statuses if s.get(str(checkpoints[0])) == "verdict_void_negative_control")
        out[cell] = {
            "n_episodes": n, "episode_origins": episode, "checkpoints": list(checkpoints),
            "rate_any_checkpoint": round(any_hits / n, 4) if n else None,
            "rate_k60_only": round(k60_hits / n, 4) if n else None,
            "wilson90_any": wilson_interval(any_hits, n), "wilson90_k60": wilson_interval(k60_hits, n),
            "k60_void_episodes": void,
            "first_origin": str(episodes[0][0]["origin"]) if episodes else None,
            "last_origin": str(episodes[-1][-1]["origin"]) if episodes else None,
            "statuses": statuses,
        }
    return out


def design_rows(root: Path, contract: dict[str, Any], cells: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """설계창 원점별 (p, 라벨, 기후) — 동결 계수만, 패널은 2014-12-31 절단."""
    from ..timeseries_v2.market_archive import read_market_observations
    from . import features as F
    from .holdout import _feature_matrix, _predict

    pin = contract.get("frozen_coefficients") or {}
    frozen = C.load_frozen_coefficients(
        root, expected_sha256=pin.get("sha256"), expected_content_hash=pin.get("content_hash"),
        expected_finalist_id=pin.get("finalist_id"))
    panel = F.build_panel(read_market_observations(root), start=DESIGN_START, end=DESIGN_END)
    dates = [str(d) for d in panel["dates"]]
    if not dates or dates[-1] > DESIGN_END:
        raise ValueError("design panel is empty or exceeds the design window")
    vix = panel["vix"]
    rv_filled = F.fill_rv_nan(panel["rv21"], frozen["rv_nan_fill_median"])
    vix_ewma = F.ewma(vix, frozen["alpha_ewma"])
    rv_ewma = F.ewma(rv_filled, frozen["alpha_ewma"])
    specs = {s["name"]: s for s in C.cell_specs()}
    out: dict[str, list[dict[str, Any]]] = {}
    for name in cells:
        spec = specs[name]
        cell = frozen["cells"][name]
        if spec["target"] == "vix_touch":
            y = F.labels_vix(vix, spec["K"], spec["h"]); level, smooth = vix, vix_ewma
        else:
            y = F.labels_rv(panel["rv21"], spec["theta"], spec["h"]); level, smooth = rv_filled, rv_ewma
        p = _predict(cell, _feature_matrix(cell, level, smooth))
        base = float(cell["clim_base_rate"])
        out[name] = [{"origin": dates[i], "probability": float(p[i]), "label": float(y[i]),
                      "climatology_base_rate": base}
                     for i in range(len(dates)) if np.isfinite(y[i]) and np.isfinite(p[i])]
    return out


def design_replay_demotion_rates(root: Path, *, cells: Iterable[str] | None = None, episode: int = 120,
                                 checkpoints: Iterable[int] = CHECKPOINTS) -> dict[str, Any]:
    root = Path(root)
    contract = C.load_contract_v13(root)
    params = verdict_parameters(contract)
    scope = list(cells) if cells is not None else [c for c in C.CELL_ORDER if c in params["pass_cells"]]
    rows = design_rows(root, contract, scope)
    return {"schema": "v13_live_verdict_design_replay", "window": [DESIGN_START, DESIGN_END],
            "draws": NULL_DRAWS, "cells": replay_rows(rows, params, episode=episode, checkpoints=checkpoints),
            "caveats": list(CAVEATS), "writes": 0,
            "notice": "참고 의견, 매매 신호 아님 — 설계창 base rate 참조(판정·승격 근거 아님)"}
