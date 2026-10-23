"""tools/v13_vol_rung7_diagnostics.py — rung-7 후보 블록의 **라벨 미접촉** 진단 (설계창 한정).

사전등록 문서 `docs/design/v13_rung7_prereg_261021.md` §1 의 규칙(R1~R4)이 먼저 적혔고, 이 도구는 그 규칙에
필요한 통계만 낸다: champion 피처 대비 |corr| · 반창별 유효 행 비율 · 반창별 최빈값 점유율 · 블록 간 상관.
**라벨 y 는 어디서도 계산하지 않는다** — 결과를 보고 블록을 고르는 것을 막기 위해서다.

    PYTHONUTF8=1 python tools/v13_vol_rung7_diagnostics.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_fc.timeseries_v13 import contracts as C  # noqa: E402
from ai_fc.timeseries_v13 import features as F  # noqa: E402
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402

EVENTS = ROOT / "data/timeseries_v13/exog/scheduled_events_2007_2014.jsonl"
TFF = ROOT / "data/timeseries_v13/exog/cftc_tff_positions.jsonl"
OUT = ROOT / "data/timeseries_v13/prereg/rung7_candidate_diagnostics.json"
LOOKBACK_START = "2005-01-01"      # D1/D2 선행창 — 설계창 첫 원점에도 '마지막 사건' 이 정의되게
SPLIT = "2011-01-01"
STALENESS_DAYS = 21                # P 블록: 최신 공표 보고가 이보다 오래되면 NaN
FROZEN_RV_MEDIAN = 0.1694207105468098
RULES = {"auto_reject_abs_corr": 0.85, "min_coverage_per_half": 0.80, "degenerate_mode_share": 0.90}


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _next_session_index(dates: list[str], day: str) -> int | None:
    """일정일 → 패널 세션 인덱스. 비세션이면 다음 세션으로 이월. 패널 밖이면 None."""
    import bisect
    i = bisect.bisect_left(dates, day)
    return i if i < len(dates) else None


def event_index_sets(dates: list[str]) -> dict[str, np.ndarray]:
    kinds = {"fomc_scheduled": [], "bls_empsit": [], "bls_cpi": []}
    carried = Counter()
    for r in _rows(EVENTS):
        if r["kind"] not in kinds or not r.get("in_block"):
            continue
        # PIT: 2013 셧다운으로 밀린 4건은 origin 시점에 공표돼 있던 **원래 예정일**(연초 일정 빈티지)을 쓴다 — 미래 정보 0.
        day = r.get("originally_scheduled") or r["event_date"]
        idx = _next_session_index(dates, day)
        if idx is None:
            continue
        if dates[idx] != day:
            carried[r["kind"]] += 1
        kinds[r["kind"]].append(idx)
    out = {k: np.zeros(len(dates)) for k in kinds}
    for k, idxs in kinds.items():
        for i in idxs:
            out[k][i] += 1
    out["_carried_to_next_session"] = dict(carried)
    return out


def window_count(marks: np.ndarray, h: int) -> np.ndarray:
    """세션 i+1..i+h 의 마크 합 — 라벨 창과 동일."""
    n = len(marks)
    cs = np.concatenate([[0.0], np.cumsum(marks)])
    out = np.full(n, np.nan)
    for i in range(n - h):
        out[i] = cs[i + 1 + h] - cs[i + 1]
    return out


def sessions_to_next(marks: np.ndarray) -> np.ndarray:
    n = len(marks)
    out = np.full(n, np.nan)
    nxt = None
    for i in range(n - 1, -1, -1):
        if nxt is not None:
            out[i] = nxt - i
        if marks[i] > 0:
            nxt = i
    return out


def sessions_since(flags: np.ndarray) -> np.ndarray:
    n = len(flags)
    out = np.full(n, np.nan)
    last = None
    for i in range(n):
        if flags[i]:
            last = i
        if last is not None:
            out[i] = i - last
    return out


def positioning_series(dates: list[str], code: str, field: str) -> np.ndarray:
    rows = sorted((r for r in _rows(TFF) if r["contract_code"] == code), key=lambda r: r["available_at"])
    out = np.full(len(dates), np.nan)
    j = 0
    latest = None
    for i, d in enumerate(dates):
        while j < len(rows) and rows[j]["available_at"] <= d:
            latest = rows[j]
            j += 1
        if latest is None or latest.get(field) is None:
            continue
        age = (date.fromisoformat(d) - date.fromisoformat(latest["report_date"])).days
        if age <= STALENESS_DAYS:
            out[i] = float(latest[field])
    return out


def _corr(a: np.ndarray, b: np.ndarray) -> float | None:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
        return None
    return float(abs(np.corrcoef(a[m], b[m])[0, 1]))


def _mode_share(x: np.ndarray) -> float | None:
    v = x[np.isfinite(x)]
    if v.size == 0:
        return None
    vals, counts = np.unique(np.round(v, 6), return_counts=True)
    return float(counts.max() / v.size)


def main() -> int:
    observations = list(read_market_observations(ROOT))
    panel = F.build_panel(observations, start=LOOKBACK_START, end=C.DESIGN_WINDOW[1])
    dates = [str(d) for d in panel["dates"]]
    vix = np.asarray(panel["vix"], float)
    rv = F.fill_rv_nan(np.asarray(panel["rv21"], float), FROZEN_RV_MEDIAN)
    design = np.array([C.DESIGN_WINDOW[0] <= d <= C.DESIGN_WINDOW[1] for d in dates])
    early = design & np.array([d < SPLIT for d in dates])
    late = design & ~np.array([d < SPLIT for d in dates])

    marks = event_index_sets(dates)
    fomc = marks["fomc_scheduled"]
    macro = marks["bls_empsit"] + marks["bls_cpi"]
    e3 = np.log1p(sessions_to_next(fomc))
    p1 = positioning_series(dates, "1170E1", "lev_net_over_oi")
    p3 = positioning_series(dates, "209742", "lev_net_over_oi")
    d2 = np.log1p(sessions_since(vix >= 25.0))

    report: dict = {
        "schema": "v13_vol_rung7_candidate_diagnostics",
        "label_free": True,
        "rules": RULES,
        "panel": {"lookback_start": LOOKBACK_START, "design_window": list(C.DESIGN_WINDOW), "split": SPLIT,
                  "sessions_design": int(design.sum()), "early": int(early.sum()), "late": int(late.sum())},
        "events_carried_to_next_session": marks["_carried_to_next_session"],
        "positioning_staleness_days": STALENESS_DAYS,
        "cells": {},
        "block_pairs": {},
    }

    for spec in C.cell_specs():
        name, h = spec["name"], spec["h"]
        level = vix if spec["target"] == "vix_touch" else rv
        if spec["target"] == "vix_touch":
            d1 = np.log1p(sessions_since(vix >= float(spec["K"])))
        else:
            d1 = np.log1p(sessions_since(rv > float(spec["theta"])))
        blocks = {
            "E1_fomc_in_window": window_count(fomc, h),
            "E2_macro_release_in_window": window_count(macro, h),
            "E3_log_sessions_to_next_fomc": e3,
            "P1_vix_lev_net_oi": p1,
            "P3_nq_lev_net_oi": p3,
            "D1_log_sessions_since_event": d1,
            "D2_log_sessions_since_any_vix25": d2,
        }
        cell_out = {}
        for bname, x in blocks.items():
            xd = np.where(design, x, np.nan)
            entry = {
                "abs_corr_vs_champion_feature": _corr(xd, np.where(design, level, np.nan)),
                "abs_corr_vs_vix": _corr(xd, np.where(design, vix, np.nan)),
                "abs_corr_vs_rv21": _corr(xd, np.where(design, rv, np.nan)),
                "coverage_early": float(np.isfinite(x[early]).mean()),
                "coverage_late": float(np.isfinite(x[late]).mean()),
                "mode_share_early": _mode_share(x[early]),
                "mode_share_late": _mode_share(x[late]),
                "mean_early": float(np.nanmean(x[early])) if np.isfinite(x[early]).any() else None,
                "mean_late": float(np.nanmean(x[late])) if np.isfinite(x[late]).any() else None,
            }
            c = entry["abs_corr_vs_champion_feature"]
            entry["R1_auto_reject"] = bool(c is not None and c > RULES["auto_reject_abs_corr"])
            entry["R2_coverage_fail"] = bool(min(entry["coverage_early"], entry["coverage_late"]) < RULES["min_coverage_per_half"])
            entry["R3_block_degenerate_cell"] = bool(max(entry["mode_share_early"] or 0, entry["mode_share_late"] or 0) >= RULES["degenerate_mode_share"])
            cell_out[bname] = entry
        report["cells"][name] = cell_out
        if name == "vix25_h5":
            for a, b in (("E1_fomc_in_window", "E2_macro_release_in_window"), ("E1_fomc_in_window", "E3_log_sessions_to_next_fomc"),
                         ("P1_vix_lev_net_oi", "P3_nq_lev_net_oi"), ("D1_log_sessions_since_event", "D2_log_sessions_since_any_vix25"),
                         ("P1_vix_lev_net_oi", "D1_log_sessions_since_event"), ("E1_fomc_in_window", "P1_vix_lev_net_oi")):
                report["block_pairs"][f"{a}|{b}@vix25_h5"] = _corr(np.where(design, blocks[a], np.nan), np.where(design, blocks[b], np.nan))

    # 블록 단위 요약 (R1·R2 는 블록 단위, R3 는 셀 단위)
    summary = {}
    for bname in ["E1_fomc_in_window", "E2_macro_release_in_window", "E3_log_sessions_to_next_fomc",
                  "P1_vix_lev_net_oi", "P3_nq_lev_net_oi", "D1_log_sessions_since_event", "D2_log_sessions_since_any_vix25"]:
        per = [report["cells"][c][bname] for c in C.CELL_ORDER]
        summary[bname] = {
            "max_abs_corr_vs_champion": max((e["abs_corr_vs_champion_feature"] or 0) for e in per),
            "R1_auto_reject_any_cell": any(e["R1_auto_reject"] for e in per),
            "min_coverage": min(min(e["coverage_early"], e["coverage_late"]) for e in per),
            "R2_coverage_fail": any(e["R2_coverage_fail"] for e in per),
            "R3_degenerate_cells": [c for c in C.CELL_ORDER if report["cells"][c][bname]["R3_block_degenerate_cell"]],
        }
    report["summary"] = summary
    report["content_hash"] = C.canonical_hash(report)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8", newline="\n")

    print("{:34s} {:>8s} {:>8s} {:>6s} {:>6s}  R1  R2  R3셀".format("블록", "max|ρ|", "min cov", "", ""))
    for b, s in summary.items():
        print("{:34s} {:8.3f} {:8.3f} {:>6s} {:>6s}  {}  {}  {}".format(
            b, s["max_abs_corr_vs_champion"], s["min_coverage"], "", "",
            "X" if s["R1_auto_reject_any_cell"] else "-", "X" if s["R2_coverage_fail"] else "-", s["R3_degenerate_cells"] or "-"))
    print("block pairs:", {k: (round(v, 3) if v is not None else None) for k, v in report["block_pairs"].items()})
    print("carried to next session:", marks["_carried_to_next_session"])
    print("wrote", OUT.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
