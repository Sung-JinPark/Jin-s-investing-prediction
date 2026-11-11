"""V13-D14 라이브 판정 보고 확장 — **인쇄 전용**(print_only · 판정 다리 아님).

`timeseries-v13-vol-live-verdict` 가 셀별로 함께 인쇄하는 보고 필드를 계산한다:
- 로그점수(평균 음의 로그우도, nats) — 모형 · 등록 기후 · 설계창 두 반창 상수. p ∉ (0,1) 이면 None(클리핑 없음).
- Murphy 신뢰도 — `scoring.murphy_reliability` 10등분 그대로(계약 gate.reliability 의 라이브 보고).
- 사전 상수 기준선 — 등록 기후(동결 아티팩트) + 설계창 두 반창 무조건 빈도를 **항상 대칭으로**.
  한쪽 반창만 고르는 경로는 없다(리뷰 B4). 값은 2026-09-08 해시 고정 파일에서만 읽는다.
- RV 기계 확정 — 원점 정보만으로 정해지는 rv21 하한이 θ 를 넘는 원점의 비율.

status·T7 산술(`live_verdict._evaluate_cell`)에는 아무것도 들어가지 않는다. 우열 문장·skill 주장을 만들지 않는다.
RV 하한 닫힌형은 연구 계층 `mts_research/audits/rv_mechanics.py`(rv_floor·mechanical_positive)와 같은 식이며,
생산 패키지가 연구 계층을 import 하지 않도록 복제했다(역방향 없음). 동치는 테스트가 1e-12 로 고정한다.
참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from . import contracts as C
from . import scoring as S

SCOPE_NOTE = "print_only — 판정 다리 아님(live_forward_verdict_report_extension). status·T7 산술은 live_forward_gate 그대로"
PANEL_VINTAGE = "latest_archive_not_pit"
RV_WINDOW = 21
RV_ANNUALIZATION = 252.0

#: 두 반창을 항상 함께 낸다 — 한쪽만 고르는 경로 없음(리뷰 B4).
HALF_DIRECTIONS = {"early_fit": "early_to_late",   # 이 방향의 clim_base_rate = 전반창(2007~2010) fit 빈도
                   "late_fit": "late_to_early"}    # 이 방향의 clim_base_rate = 후반창(2011~2014) fit 빈도
HALF_NOTE = "두 반창 대칭 보고 — 판정·skill·무능 주장 근거 아님"


def _r6(value: float | None) -> float | None:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return round(float(value), 6)


def log_score(p: Any, y: Any) -> float | None:
    """평균 음의 로그우도(nats). p ∉ (0,1) 이거나 비유한이면 None — 클리핑 없음."""
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    if p.size == 0 or p.shape != y.shape or not np.all(np.isfinite(p)) or not np.all((p > 0) & (p < 1)):
        return None
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _half_windows(split: str | None) -> dict[str, list[str]]:
    """반창 경계 — ladder 의 split 메타(2011-01-01)를 옮겨 적는다. 없으면 계약 설계창 분할 기본값."""
    start, end = C.DESIGN_WINDOW
    cut = str(split or "2011-01-01")
    try:
        from datetime import date, timedelta
        before = (date.fromisoformat(cut) - timedelta(days=1)).isoformat()
    except ValueError:
        before = "2010-12-31"
        cut = "2011-01-01"
    return {"early_fit": [start, before], "late_fit": [cut, end]}


def design_half_constants(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """ladder_pb_baseline.json 의 셀별 두 반창 clim_base_rate — 파일 sha256 == 계약 핀일 때만, 둘 다 있을 때만."""
    pin = ((((contract.get("gates") or {}).get("design_evidence") or {}).get("persistence_pb") or {})
           .get("sha256"))
    path = Path(root) / C.LADDER_PB_RELATIVE
    if not path.is_file():
        return {"status": "missing", "values": {}}
    if not pin or C.sha256_file(path) != pin:
        return {"status": "pin_mismatch", "values": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = payload.get("cells") or {}
    values: dict[str, dict[str, float]] = {}
    for name in C.CELL_ORDER:
        pv = (cells.get(name) or {}).get("pb_vs_clim") or {}
        pair = {key: (pv.get(direction) or {}).get("clim_base_rate") for key, direction in HALF_DIRECTIONS.items()}
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pair.values()):
            values[name] = {key: float(v) for key, v in pair.items()}   # 한쪽만 있으면 셀 통째로 생략(대칭 유지)
    return {"status": "ok", "sha256": pin, "values": values, "windows": _half_windows(payload.get("split"))}


def rv_mechanical_floor(returns: np.ndarray, t: int, h: int) -> float:
    """원점 t 정보만으로 정해지는 max_{k=1..min(h,20)} rv21[t+k] 의 하한(연율).

    창 = returns[t+k-20 .. t+k] 21개, 알려진 부분 = 인덱스 ≤ t (21−k 개).
    S1=Σknown, S2=Σknown², F1*=S1·k/(21−k), F2*=F1*²/k, var=(S2+F2*−(S1+F1*)²/21)/20, floor=sqrt(max(var,0)·252).
    알려진 부분이 자료 밖이거나 비유한이면 nan.
    """
    returns = np.asarray(returns, float)
    best = 0.0
    for k in range(1, min(int(h), RV_WINDOW - 1) + 1):
        start = t + k - (RV_WINDOW - 1)
        if start < 0 or t >= returns.size:
            return float("nan")
        known = returns[start: t + 1]
        if known.size != RV_WINDOW - k or not np.all(np.isfinite(known)):
            return float("nan")
        s1 = float(known.sum())
        s2 = float((known * known).sum())
        f1 = s1 * k / (RV_WINDOW - k)
        f2 = f1 * f1 / k
        total = s1 + f1
        floor = math.sqrt(max((s2 + f2 - total * total / RV_WINDOW) / (RV_WINDOW - 1), 0.0) * RV_ANNUALIZATION)
        if floor > best:
            best = floor
    return best


def panel_returns(panel: dict[str, Any]) -> np.ndarray:
    """V13 패널 수익 r = [nan] ++ diff(log ndx) — 라벨(features.labels_rv)과 같은 VIX∩NASDAQCOM 그리드."""
    ndx = np.asarray(panel.get("ndx"), float)
    if ndx.size == 0:
        return np.array([], float)
    return np.concatenate([[np.nan], np.diff(np.log(ndx))])


def _half_block(cell: str, half: dict[str, Any], y: np.ndarray) -> dict[str, Any]:
    status = half.get("status")
    if status != "ok":
        return {"status": status or "missing"}
    values = (half.get("values") or {}).get(cell)
    if not values:
        return {"status": "cell_absent"}
    windows = half.get("windows") or _half_windows(None)
    out: dict[str, Any] = {"status": "ok"}
    for key in HALF_DIRECTIONS:
        c = float(values[key])
        out[key] = {"value": c, "fit_window": list(windows[key]),
                    "brier": _r6(float(np.mean((c - y) ** 2))),
                    "log_score": _r6(log_score(np.full(y.shape, c), y))}
    out.update({"sha256_pinned": half.get("sha256"), "value_committed": "2026-09-08", "n": int(y.size),
                "events": int((y == 1.0).sum()), "single_episode_caveat": True, "note": HALF_NOTE})
    return out


def _mechanical_block(cell: str, rows: list[dict[str, Any]], panel: dict[str, Any] | None, panel_status: str,
                      p: np.ndarray, pi: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    unavailable = {"status": "archive_unavailable", "panel_vintage": PANEL_VINTAGE}
    if panel is None or panel_status != "ok":
        return unavailable
    dates = [str(d) for d in (panel.get("dates") if panel.get("dates") is not None else [])]
    if not dates:
        return unavailable
    index = {d: i for i, d in enumerate(dates)}
    h = int(cell.split("_h")[1])
    returns = panel_returns(panel)
    located = np.zeros(len(rows), bool)
    flags = np.zeros(len(rows), bool)
    for i, row in enumerate(rows):
        t = index.get(str(row.get("origin")))
        if t is None:
            continue
        located[i] = True
        floor = rv_mechanical_floor(returns, t, h)
        flags[i] = bool(math.isfinite(floor) and floor > C.THETA_RV)
    if not located.any():
        return unavailable
    violations = [str(rows[i].get("origin")) for i in range(len(rows)) if flags[i] and y[i] != 1.0]
    if violations:
        return {"status": "invariant_violation", "panel_vintage": PANEL_VINTAGE, "origins": violations}
    events = int((y == 1.0).sum())
    mech = int((flags & (y == 1.0)).sum())
    rest = located & ~flags
    nm: dict[str, Any] = {"n": int(rest.sum())}
    if rest.any():
        bm = float(np.mean((p[rest] - y[rest]) ** 2))
        bc = float(np.mean((pi[rest] - y[rest]) ** 2))
        nm.update({"brier_model": _r6(bm), "brier_climatology": _r6(bc),
                   "bss": None if bc == 0 else round(1.0 - bm / bc, 4)})
    unlocated = int((~located).sum())
    out: dict[str, Any] = {
        "status": "partial" if unlocated else "ok", "theta": C.THETA_RV, "panel_vintage": PANEL_VINTAGE,
        "mechanical_positives": mech, "events": events,
        "share_of_events": None if events == 0 else round(mech / events, 4),
        "mechanical_origins": int(flags.sum()), "nonmechanical": nm,
    }
    if unlocated:
        out["unlocated"] = unlocated
    return out


def report_extension(cell: str, rows: list[dict[str, Any]], *, panel: dict[str, Any] | None, panel_status: str,
                     half_constants: dict[str, Any]) -> dict[str, Any]:
    """한 셀의 보고 필드(인쇄 전용). rows = distinct 해상 행(origin 순)."""
    n = len(rows)
    if n == 0:
        return {"scope": SCOPE_NOTE, "n": 0}
    p = np.array([float(r["probability"]) for r in rows], float)
    y = np.array([float(r["label"]) for r in rows], float)
    pi = np.array([float(r["climatology_base_rate"]) for r in rows], float)
    reliability = dict(S.murphy_reliability(p, y))
    reliability["curve_n_total"] = n
    out: dict[str, Any] = {
        "scope": SCOPE_NOTE, "n": n, "events": int((y == 1.0).sum()),
        "log_score": {"model": _r6(log_score(p, y)), "climatology": _r6(log_score(pi, y)), "unit": "nats/원점"},
        "reliability": reliability,
        "constant_baselines": {
            "climatology": {"value": _r6(float(pi[0])),
                            "source": "champion_coefficients.json cells[*].clim_base_rate (설계창 2007~2014)",
                            "registered": "2026-09-07"},
            "design_half_constants": _half_block(cell, half_constants, y),
        },
    }
    if cell.startswith("rv_"):
        out["mechanical"] = _mechanical_block(cell, rows, panel, panel_status, p, pi, y)
    else:
        out["mechanical"] = {"status": "not_applicable_vix"}   # VIX 터치는 원점 정보로 확정되지 않는다
    return out
