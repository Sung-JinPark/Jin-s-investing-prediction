"""tools/v14_cond_diagnostics.py — V14 조건부 전이 P0: 조건부 부분집합 기준 라벨 미접촉 진단 + 에피소드 가드 실측.

정본 계약 `data/contracts/multivariate_timeseries_v14_conditional.yaml` · 서술 `docs/design/v14_conditional_transition_prereg_draft_261021.md`
· 후보 풀·규칙 R1~R4 `docs/design/v13_rung7_prereg_261021.md` §1. track_open(2026-10-22) 뒤 P0 — 평가 예산 0 소모.

산출 JSON 은 두 섹션을 **분리**하며, 각 섹션은 **별도 함수**가 만든다:
  label_free — `label_free_report`: x 열과 조건 마스크만 쓴다(라벨 접촉 0). 라벨 배열을 받지도 만들지도 않는다.
               조건부 부분집합 안의 셀×블록 커버리지·|corr|·최빈값 점유율 → R1~R4 등록.
  guard      — `guard_report`: 라벨을 만진다(계약 episode_guard.measurement: track_open 뒤 P0 에서 허용).
               반창×클래스 국면 수·사건 수·조건부 기저율.
`label_free_section_touches_labels` / `guard_section_touches_labels` 는 리터럴이 아니라 두 함수의 코드 객체를 정적으로
훑어(`_references_labels` — 전이적 co_names 스캔) 라벨 생성·접촉 이름이 참조되는지로 **구조에서** 정한다.
패널은 2005-01-01(국면기억 선행창)~2014-12-31 로 절단 — 홀드아웃(2015-2018)·봉인(2019+) 바이트 미열람.
블록 정의·조건·창·임계는 여기서 바꾸지 않는다. 결과를 보고 셀·문턱·창을 바꾸지 않는다(M3) — 미달은 그대로 받아들인다.
블록 빌더·규칙 임계는 `tools/v13_vol_rung7_diagnostics.py` 를 import 해 같은 코드를 쓴다(신규 구현 0).
산출 파일은 불변 — 이미 있으면 덮어쓰지 않고 exit 2 (재생성은 의도적 삭제 뒤에만 · 계약의 diagnostics_content_hash 갱신 필요).

    PYTHONUTF8=1 python tools/v14_cond_diagnostics.py [--root PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from ai_fc.timeseries_v13 import contracts as C  # noqa: E402  (DESIGN_WINDOW · canonical_hash)
from ai_fc.timeseries_v13 import features as F  # noqa: E402  (build_panel · labels_* · fill_rv_nan)
from ai_fc.timeseries_v13 import scoring as S  # noqa: E402  (degeneracy_report)
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402
import v13_vol_rung7_diagnostics as D  # noqa: E402  (블록 빌더 · RULES · _corr · _mode_share)

CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v14_conditional.yaml")
OUT_RELATIVE = Path("data/timeseries_v14/prereg/p0_conditional_diagnostics.json")
CONTRACT_ID = "timeseries_v14_conditional"
MODEL_ID = "event_probability.volatility_v14_conditional"
SPLIT = "2011-01-01"
VIX_COND_LT = 20.0                 # 조건: VIX_close_t < 20 (엄격) — 계약 targets.vix_conditional_transition.conditioning
BLOCK_ORDER = ("E1_fomc_in_window", "E2_macro_release_in_window", "E3_log_sessions_to_next_fomc",
               "P1_vix_lev_net_oi", "P3_nq_lev_net_oi",
               "D1_log_sessions_since_event", "D2_log_sessions_since_any_vix25")
CLASS_ORDER = {                    # 클래스당 primary → 대체 순서 (계약 candidate_blocks.inherited_from_rung7_prereg)
    "calendar": ("E1_fomc_in_window", "E2_macro_release_in_window", "E3_log_sessions_to_next_fomc"),
    "positioning": ("P1_vix_lev_net_oi", "P3_nq_lev_net_oi"),
    "regime_memory": ("D1_log_sessions_since_event", "D2_log_sessions_since_any_vix25"),
}
RULES = dict(D.RULES)              # R1 0.85 · R2 0.80 · R3 0.90 — rung-7 사전등록과 동일, 계약 registration_rules 와 일치
# 라벨을 만들거나 만지는 이름 — 이 이름을 (전이적으로) 참조하는 함수는 '라벨 접촉' 으로 판정한다(구조적 검사, 실행 아님).
LABEL_NAMES = frozenset({"full_labels", "labels_vix", "labels_rv", "guard_for_cell", "guard_report", "degeneracy_report"})


# ── 계약·셀 ──────────────────────────────────────────────────────────────────
def load_contract_v14(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        raise RuntimeError("V14 contract is missing: " + str(path))
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_id") != CONTRACT_ID or payload.get("model_id") != MODEL_ID:
        raise RuntimeError("V14 contract identity mismatch")
    return payload


def v14_cell_specs(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """6셀 사양 — 계약 targets 에서 읽는다. 이름·K·θ·h·조건 문턱은 계약이 정본(post_hoc 변경 금지)."""
    t = contract["targets"]
    vix_t, rv_t = t["vix_conditional_transition"], t["rv_conditional_transition"]
    if "< 20" not in str(vix_t["conditioning"]):
        raise RuntimeError("vix conditioning text does not state '< 20'")
    if "<= theta" not in str(rv_t["conditioning"]):
        raise RuntimeError("rv conditioning text does not state '<= theta'")
    specs: list[dict[str, Any]] = []
    for h, name in zip(vix_t["horizons"], vix_t["cells"]):
        if name != f"cvix25_h{h}":
            raise RuntimeError(f"unexpected vix cell name {name}")
        specs.append({"name": name, "target": "vix_conditional", "K": float(vix_t["K"]), "cond_lt": VIX_COND_LT, "h": int(h)})
    theta = float(rv_t["theta"])
    for h, name in zip(rv_t["horizons"], rv_t["cells"]):
        if name != f"crv_h{h}":
            raise RuntimeError(f"unexpected rv cell name {name}")
        specs.append({"name": name, "target": "rv_conditional", "theta": theta, "h": int(h)})
    if len(specs) != int(t["cell_count"]):
        raise RuntimeError("cell_count mismatch")
    return specs


# ── 조건부 부분집합 · 라벨 · champion 피처 ──────────────────────────────────
def conditional_subset(spec: dict[str, Any], vix: np.ndarray, rv_raw: np.ndarray) -> np.ndarray:
    """조건 충족 원점 마스크(전체 패널 길이). vix 셀 VIX_t<20 엄격 · rv 셀 raw RV21_t 유한 ∧ <=θ (NaN 은 부분집합 밖)."""
    if spec["target"] == "vix_conditional":
        return np.isfinite(vix) & (vix < spec["cond_lt"])
    return np.isfinite(rv_raw) & (rv_raw <= spec["theta"])


def champion_feature(spec: dict[str, Any], vix: np.ndarray, rv_raw: np.ndarray) -> np.ndarray:
    """조건부 PB 피처 = 당일 수준. rv 는 V13 과 같은 양(fill_rv_nan) — 부분집합 안에서는 raw 값 그대로."""
    if spec["target"] == "vix_conditional":
        return np.asarray(vix, float)
    return F.fill_rv_nan(np.asarray(rv_raw, float), spec["theta"])


def full_labels(spec: dict[str, Any], vix: np.ndarray, rv_raw: np.ndarray) -> np.ndarray:
    """전체 패널 라벨(미래창 i+1..i+h) — 부분집합 제한은 호출자가 마스크로 한다."""
    if spec["target"] == "vix_conditional":
        return F.labels_vix(vix, spec["K"], spec["h"])
    return F.labels_rv(rv_raw, spec["theta"], spec["h"])


# ── 블록 (rung-7 진단 · rung_public.build_block 과 같은 정의) ────────────────
def block_values(name: str, spec: dict[str, Any], *, vix: np.ndarray, rv_f: np.ndarray,
                 marks: dict[str, np.ndarray], p1: np.ndarray, p3: np.ndarray) -> np.ndarray:
    h = spec["h"]
    if name == "E1_fomc_in_window":
        return D.window_count(marks["fomc_scheduled"], h)
    if name == "E2_macro_release_in_window":
        return D.window_count(marks["bls_empsit"] + marks["bls_cpi"], h)
    if name == "E3_log_sessions_to_next_fomc":
        return np.log1p(D.sessions_to_next(marks["fomc_scheduled"]))
    if name == "P1_vix_lev_net_oi":
        return p1
    if name == "P3_nq_lev_net_oi":
        return p3
    if name == "D1_log_sessions_since_event":
        if spec["target"] == "vix_conditional":
            return np.log1p(D.sessions_since(vix >= spec["K"]))
        return np.log1p(D.sessions_since(rv_f > spec["theta"]))
    if name == "D2_log_sessions_since_any_vix25":
        return np.log1p(D.sessions_since(vix >= 25.0))
    raise KeyError(name)


def cell_blocks(spec: dict[str, Any], ctx: dict[str, Any]) -> dict[str, np.ndarray]:
    return {b: block_values(b, spec, vix=ctx["vix"], rv_f=ctx["rv_f"], marks=ctx["marks"], p1=ctx["p1"], p3=ctx["p3"])
            for b in BLOCK_ORDER}


# ── 패널 컨텍스트 ─────────────────────────────────────────────────────────────
def context_from_panel(dates: list[str], vix: np.ndarray, rv_raw: np.ndarray, *, theta: float,
                       marks: dict[str, np.ndarray], p1: np.ndarray, p3: np.ndarray) -> dict[str, Any]:
    """패널 배열 → 설계창·반창 마스크 + 블록 원료. 테스트는 합성 배열로 직접 호출한다."""
    vix = np.asarray(vix, float)
    rv_raw = np.asarray(rv_raw, float)
    design = np.array([C.DESIGN_WINDOW[0] <= d <= C.DESIGN_WINDOW[1] for d in dates], bool)
    before_split = np.array([d < SPLIT for d in dates], bool)
    return {
        "dates": list(dates), "vix": vix, "rv_raw": rv_raw, "rv_f": F.fill_rv_nan(rv_raw, theta),
        "design": design, "early": design & before_split, "late": design & ~before_split,
        "marks": marks, "p1": np.asarray(p1, float), "p3": np.asarray(p3, float),
    }


def panel_context(observations, *, theta: float) -> dict[str, Any]:
    """2005-01-01~2014-12-31 패널 + 설계창·반창 마스크 + 블록 원료. end 는 설계창 끝 — 2015+ 미열람."""
    panel = F.build_panel(observations, start=D.LOOKBACK_START, end=C.DESIGN_WINDOW[1])
    dates = [str(d) for d in panel["dates"]]
    return context_from_panel(dates, panel["vix"], panel["rv21"], theta=theta, marks=D.event_index_sets(dates),
                              p1=D.positioning_series(dates, "1170E1", "lev_net_over_oi"),
                              p3=D.positioning_series(dates, "209742", "lev_net_over_oi"))


# ── label_free 진단 ──────────────────────────────────────────────────────────
def _share(mask_num: np.ndarray, mask_den: np.ndarray) -> float | None:
    den = int(mask_den.sum())
    return float(mask_num.sum() / den) if den else None


def diagnose_block(x: np.ndarray, level: np.ndarray, sub: np.ndarray, sub_e: np.ndarray, sub_l: np.ndarray,
                   *, vix: np.ndarray | None = None, rv_f: np.ndarray | None = None) -> dict[str, Any]:
    """한 셀·한 블록: 조건부 부분집합 안의 커버리지·|corr|·최빈값 점유율 + R1~R3 플래그. 라벨 접촉 0."""
    xd = np.where(sub, x, np.nan)
    entry: dict[str, Any] = {
        "abs_corr_vs_conditional_champion_feature": D._corr(xd, np.where(sub, level, np.nan)),
        "abs_corr_vs_vix": D._corr(xd, np.where(sub, vix, np.nan)) if vix is not None else None,
        "abs_corr_vs_rv21": D._corr(xd, np.where(sub, rv_f, np.nan)) if rv_f is not None else None,
        "coverage_early": float(np.isfinite(x[sub_e]).mean()) if sub_e.any() else 0.0,
        "coverage_late": float(np.isfinite(x[sub_l]).mean()) if sub_l.any() else 0.0,
        "mode_share_early": D._mode_share(x[sub_e]),
        "mode_share_late": D._mode_share(x[sub_l]),
        "mean_early": float(np.nanmean(x[sub_e])) if np.isfinite(x[sub_e]).any() else None,
        "mean_late": float(np.nanmean(x[sub_l])) if np.isfinite(x[sub_l]).any() else None,
    }
    c = entry["abs_corr_vs_conditional_champion_feature"]
    entry["R1_auto_reject"] = bool(c is not None and c > RULES["auto_reject_abs_corr"])
    entry["R2_coverage_fail"] = bool(min(entry["coverage_early"], entry["coverage_late"]) < RULES["min_coverage_per_half"])
    entry["R3_block_degenerate_cell"] = bool(max(entry["mode_share_early"] or 0.0, entry["mode_share_late"] or 0.0)
                                             >= RULES["degenerate_mode_share"])
    return entry


def block_summary(cells: dict[str, dict[str, Any]], cell_names: list[str]) -> dict[str, dict[str, Any]]:
    """블록 단위 요약 — R1·R2 는 블록 단위(어느 셀이든 미달이면 블록 미달), R3 는 셀 단위."""
    out = {}
    for b in BLOCK_ORDER:
        per = [cells[c]["blocks"][b] for c in cell_names]
        out[b] = {
            "max_abs_corr_vs_conditional_champion": max((e["abs_corr_vs_conditional_champion_feature"] or 0.0) for e in per),
            "R1_auto_reject_any_cell": any(e["R1_auto_reject"] for e in per),
            "min_coverage": min(min(e["coverage_early"], e["coverage_late"]) for e in per),
            "R2_coverage_fail_any_cell": any(e["R2_coverage_fail"] for e in per),
            "R3_degenerate_cells": [c for c in cell_names if cells[c]["blocks"][b]["R3_block_degenerate_cell"]],
        }
    return out


def register(summary: dict[str, dict[str, Any]], cells: dict[str, dict[str, Any]], cell_names: list[str]) -> dict[str, Any]:
    """R1~R4 적용: 클래스별 첫 통과 후보 등록(블록 단위) · R3 는 그 셀만 family 제외 · 전부 미달이면 공석(R4)."""
    by_class: dict[str, Any] = {}
    for klass, order in CLASS_ORDER.items():
        chosen = None
        candidates = []
        for b in order:
            s = summary[b]
            passes = not s["R1_auto_reject_any_cell"] and not s["R2_coverage_fail_any_cell"]
            candidates.append({"id": b, "R1_auto_reject_any_cell": s["R1_auto_reject_any_cell"],
                               "R2_coverage_fail_any_cell": s["R2_coverage_fail_any_cell"], "passes_R1_R2": passes})
            if passes and chosen is None:
                chosen = b
        by_class[klass] = {"status": "registered" if chosen else "vacant_R4", "registered": chosen,
                           "order": list(order), "candidates": candidates,
                           "R3_degenerate_cells": summary[chosen]["R3_degenerate_cells"] if chosen else []}
    by_cell: dict[str, Any] = {}
    excluded: list[dict[str, str]] = []
    for c in cell_names:
        by_cell[c] = {}
        for klass, info in by_class.items():
            b = info["registered"]
            if b is None:
                by_cell[c][klass] = {"block": None, "status": "vacant_R4", "family_eligible": False}
                continue
            degenerate = bool(cells[c]["blocks"][b]["R3_block_degenerate_cell"])
            by_cell[c][klass] = {"block": b, "status": "registered", "R3_block_degenerate_cell": degenerate,
                                 "family_eligible": not degenerate}
            if degenerate:
                excluded.append({"cell": c, "block": b, "reason": "R3_block_degenerate: 조건부 부분집합 반창 최빈값 점유율 >= 0.90"})
    return {
        "rule_note": "R1·R2 는 블록 단위(6셀 중 하나라도 미달이면 블록 미달 → 같은 클래스 다음 후보). R3 는 셀 단위(그 셀만 family 분모 제외, 블록은 유지). R4: 클래스 내 전부 미달이면 공석 — 다른 클래스에서 채우지 않는다. 라벨 접촉 0.",
        "registered_blocks": [info["registered"] for info in by_class.values() if info["registered"]],
        "by_class": by_class, "by_cell": by_cell, "excluded_cells_proposed": excluded,
    }


# ── guard (라벨 접촉) ─────────────────────────────────────────────────────────
def v14_guard_verdict(report: dict[str, Any], guard_cfg: dict[str, Any]) -> dict[str, Any]:
    """계약 episode_guard: 사건·비사건 >= 20 필요조건 · 국면 >= 5 판정 자격 · [3,4] 표시만 · 미만 untestable."""
    lo, hi = (int(v) for v in guard_cfg["marginal_band"])
    ep = int(report["min_episodes"])
    if ep >= int(guard_cfg["min_episodes"]):
        band = "ok"
    elif lo <= ep <= hi:
        band = "marginal"
    else:
        band = "below_marginal"
    if not report["counts_ok"]:
        verdict, reason = "untestable_by_construction", "min_events_per_half_per_class"
    elif band == "below_marginal":
        verdict, reason = str(guard_cfg["below_marginal_action"]), "episodes_below_marginal_band"
    elif band == "marginal":
        verdict, reason = "episode_thin", "marginal_band_display_only"
    else:
        verdict, reason = "ok", None
    return {"episode_band": band, "verdict": verdict, "reason": reason}


def guard_for_cell(y_full: np.ndarray, sub: np.ndarray, early: np.ndarray, late: np.ndarray,
                   guard_cfg: dict[str, Any]) -> dict[str, Any]:
    """반창별 degeneracy_report(조건 충족 원점의 압축 부분열) + marginal band 분류 + 조건부 기저율."""
    out: dict[str, Any] = {}
    for half, mask in (("early", early), ("late", late)):
        y_half = np.asarray(y_full, float)[sub & mask]           # 압축 부분열 — NaN(창이 설계창을 넘는 원점)은 report 가 건너뛴다
        rep = S.degeneracy_report(y_half, min_events=int(guard_cfg["min_events_per_half_per_class"]),
                                  min_episodes=int(guard_cfg["min_episodes"]))
        v = v14_guard_verdict(rep, guard_cfg)
        out[half] = {"n_labelled": rep["n"], "events": rep["events"], "non_events": rep["non_events"],
                     "base_rate": rep["base_rate"], "event_runs": rep["event_runs"], "non_event_runs": rep["non_event_runs"],
                     "min_episodes": rep["min_episodes"], "counts_ok": rep["counts_ok"], "episodes_ok": rep["episodes_ok"],
                     "degeneracy_report_verdict": rep["verdict"], "episode_band": v["episode_band"],
                     "verdict": v["verdict"], "reason": v["reason"]}
    out["conditional_base_rate_early"] = out["early"]["base_rate"]
    out["conditional_base_rate_late"] = out["late"]["base_rate"]
    out["cell_verdict"] = ("untestable_by_construction"
                           if "untestable_by_construction" in (out["early"]["verdict"], out["late"]["verdict"])
                           else ("episode_thin" if "episode_thin" in (out["early"]["verdict"], out["late"]["verdict"]) else "ok"))
    return out


# ── 리포트 ───────────────────────────────────────────────────────────────────
def _clean(value: Any) -> Any:
    """JSON 직렬화 전 정리 — numpy 스칼라 → Python, NaN → None. 해시와 파일이 같은 바이트를 보도록."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_clean(v) for v in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return f if np.isfinite(f) else None
    return value


def _code_names(code: types.CodeType) -> set[str]:
    """코드 객체(중첩 코드 객체 포함)가 참조하는 전역·속성 이름."""
    names = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _code_names(const)
    return names


def _references_labels(func: Any, _seen: set[int] | None = None) -> bool:
    """함수가 LABEL_NAMES 의 이름을 (이 모듈 안 호출 그래프를 따라 전이적으로) 참조하는가 — 정적·구조적 판정, 실행 아님."""
    seen = set() if _seen is None else _seen
    code = getattr(func, "__code__", None)
    if code is None or id(code) in seen:
        return False
    seen.add(id(code))
    names = _code_names(code)
    if names & LABEL_NAMES:
        return True
    module = sys.modules[__name__]
    for name in sorted(names):
        target = getattr(module, name, None)
        if callable(target) and getattr(target, "__module__", None) == __name__ and _references_labels(target, seen):
            return True
    return False


def label_free_report(contract: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """label_free 섹션 — 부분집합 마스크 → 블록 진단 → 요약 → 등록(R1~R4). 라벨 배열을 받지도 만들지도 않는다.

    구조 보증: `_references_labels(label_free_report)` 가 False 여야 한다(LABEL_NAMES 미참조). ctx 에는 라벨이 없다
    (vix·rv_raw·마스크·블록 원료뿐).
    """
    specs = v14_cell_specs(contract)
    theta = float(contract["targets"]["rv_conditional_transition"]["theta"])
    cell_names = [s["name"] for s in specs]
    cells: dict[str, Any] = {}
    for spec in specs:
        cond = conditional_subset(spec, ctx["vix"], ctx["rv_raw"])
        sub = ctx["design"] & cond
        sub_e, sub_l = sub & ctx["early"], sub & ctx["late"]
        level = champion_feature(spec, ctx["vix"], ctx["rv_raw"])
        blocks = cell_blocks(spec, ctx)
        cells[spec["name"]] = {
            "target": spec["target"], "h": spec["h"],
            "conditioning": (f"VIX_t < {spec['cond_lt']:g}" if spec["target"] == "vix_conditional" else f"RV21_t <= {theta!r} (raw, finite)"),
            "n_subset_early": int(sub_e.sum()), "n_subset_late": int(sub_l.sum()),
            "subset_share_early": _share(sub_e, ctx["early"]), "subset_share_late": _share(sub_l, ctx["late"]),
            "blocks": {b: diagnose_block(blocks[b], level, sub, sub_e, sub_l, vix=ctx["vix"], rv_f=ctx["rv_f"]) for b in BLOCK_ORDER},
        }
    summary = block_summary(cells, cell_names)
    registration = register(summary, cells, cell_names)
    # 정보 병기(등록 규칙 아님): 표적 부분집합(vix / rv)별로 R1·R2 를 따로 보면 어떻게 되는가 — 라벨 접촉 0.
    by_target = {}
    for target in ("vix_conditional", "rv_conditional"):
        names = [s["name"] for s in specs if s["target"] == target]
        by_target[target] = block_summary(cells, names)
    summary_by_target = {"note": "정보 병기 — 등록은 block_summary(6셀 전체, 블록 단위) 로만 한다", "by_target": by_target}
    return {"cells": cells, "summary": summary, "summary_by_target": summary_by_target, "registration": registration}


def guard_report(contract: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """guard 섹션 — 라벨 접촉. label_free 와 별도 함수이며 등록(register)에는 쓰지 않는다."""
    specs = v14_cell_specs(contract)
    guard_cfg = contract["episode_guard"]
    cell_names = [s["name"] for s in specs]
    cells: dict[str, Any] = {}
    for spec in specs:
        sub = ctx["design"] & conditional_subset(spec, ctx["vix"], ctx["rv_raw"])
        cells[spec["name"]] = guard_for_cell(full_labels(spec, ctx["vix"], ctx["rv_raw"]), sub, ctx["early"], ctx["late"], guard_cfg)
    return {
        "cells": cells,
        "measured_after_track_open": True,
        "selection_after_measurement": "none — 셀·문턱·창·블록 순서는 측정 전 고정값 그대로(M3). 가드 미달 셀은 family 분모에서 제외만 한다(페일클로즈).",
        "cells_untestable": [c for c in cell_names if cells[c]["cell_verdict"] == "untestable_by_construction"],
        "cells_episode_thin": [c for c in cell_names if cells[c]["cell_verdict"] == "episode_thin"],
        "cells_ok": [c for c in cell_names if cells[c]["cell_verdict"] == "ok"],
    }


def build_report(contract: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    theta = float(contract["targets"]["rv_conditional_transition"]["theta"])
    guard_cfg = contract["episode_guard"]
    label_free = label_free_report(contract, ctx)       # 라벨 없음 — 구조적으로 보증(아래 플래그)
    guard = guard_report(contract, ctx)                  # 라벨 접촉 — 등록에 쓰지 않는다
    report = {
        "schema": "v14_cond_p0_diagnostics",
        "contract_id": contract["contract_id"],
        "label_free_section_touches_labels": _references_labels(label_free_report),
        "guard_section_touches_labels": _references_labels(guard_report),
        "label_contact_check": {
            "method": "label_free_report / guard_report 코드 객체의 전역·속성 이름을 모듈 내 호출 그래프를 따라 정적으로 스캔(_references_labels) — 리터럴 아님",
            "label_names": sorted(LABEL_NAMES),
            "label_free_function": "label_free_report", "guard_function": "guard_report",
        },
        "evaluations_consumed": 0,
        "holdout_read": False,
        "sealed_read": False,
        "panel": {"lookback_start": D.LOOKBACK_START, "design_window": list(C.DESIGN_WINDOW), "split": SPLIT,
                  "sessions_design": int(ctx["design"].sum()), "early": int(ctx["early"].sum()), "late": int(ctx["late"].sum())},
        "conditioning": {
            "vix_cells": {"rule": "VIX_close_t < 20 (strict)", "threshold": VIX_COND_LT, "K": 25.0, "pb_feature": "VIX_t"},
            "rv_cells": {"rule": "RV21_ann_t <= theta (raw, finite)", "theta": theta, "pb_feature": "RV21_t (fill_rv_nan(theta) — 부분집합 안에서는 raw 와 동일)"},
            "conditioning_note": "rv 셀: RV21 이 NaN 인 원점(패널 첫 21세션 — 2005 선행창 안)은 조건 판정이 불가하므로 부분집합에 넣지 않는다. 라벨은 전체 패널(미래창 i+1..i+h)에서 계산한 뒤 조건 충족 원점으로 제한한다.",
            "subset_share_denominator": "그 반창의 설계창 전체 원점 수",
        },
        "rules": {"R1_auto_reject_abs_corr_gt": RULES["auto_reject_abs_corr"], "R2_min_coverage_per_half": RULES["min_coverage_per_half"],
                  "R3_block_degenerate_mode_share_ge": RULES["degenerate_mode_share"],
                  "R4_class_vacancy": "클래스 내 전부 미달 → 공석(다른 클래스에서 채우지 않는다)",
                  "champion_feature": "vix 셀 VIX_t · rv 셀 RV21_t — 조건부 부분집합 안에서 계산"},
        "episode_guard_form": {"unit": guard_cfg["unit"], "min_episodes": guard_cfg["min_episodes"], "marginal_band": list(guard_cfg["marginal_band"]),
                               "below_marginal_action": guard_cfg["below_marginal_action"],
                               "min_events_per_half_per_class": guard_cfg["min_events_per_half_per_class"]},
        "events_carried_to_next_session": ctx["marks"].get("_carried_to_next_session", {}),
        "positioning_staleness_days": D.STALENESS_DAYS,
        "label_free": label_free,
        "guard": guard,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    report = _clean(report)
    report["content_hash"] = C.canonical_hash(report)
    return report


def print_summary(report: dict[str, Any]) -> None:
    lf, guard = report["label_free"], report["guard"]
    p = report["panel"]
    print(f"V14 P0 조건부 진단 — 설계창 {p['sessions_design']}세션 (early {p['early']} · late {p['late']}) · 평가 소모 0 · 홀드아웃·봉인 미열람")
    print("{:34s} {:>8s} {:>8s}  R1  R2  R3셀".format("블록(조건부 부분집합)", "max|ρ|", "min cov"))
    for b, s in lf["summary"].items():
        print("{:34s} {:8.3f} {:8.3f}  {}  {}  {}".format(
            b, s["max_abs_corr_vs_conditional_champion"], s["min_coverage"],
            "X" if s["R1_auto_reject_any_cell"] else "-", "X" if s["R2_coverage_fail_any_cell"] else "-",
            s["R3_degenerate_cells"] or "-"))
    reg = lf["registration"]["by_class"]
    print("등록: " + " · ".join(f"{k}={v['registered'] or 'VACANT(R4)'}" for k, v in reg.items()))
    print()
    print("{:11s} {:>12s} {:>12s} {:>8s} {:>8s}  {:>32s}  {:>32s}  셀".format(
        "셀", "subset e", "subset l", "share e", "share l", "guard early", "guard late"))
    for name, cell in lf["cells"].items():
        g = guard["cells"][name]
        reg_cell = lf["registration"]["by_cell"][name]
        degenerate = [v["block"] for v in reg_cell.values() if v.get("R3_block_degenerate_cell")]
        def _g(h: dict[str, Any]) -> str:
            return "{}(ev {}/{} runs {}/{} br {:.3f})".format(h["verdict"], h["events"], h["non_events"],
                                                            h["event_runs"], h["non_event_runs"], h["base_rate"] if h["base_rate"] is not None else float("nan"))
        print("{:11s} {:12d} {:12d} {:8.3f} {:8.3f}  {:>32s}  {:>32s}  {}{}".format(
            name, cell["n_subset_early"], cell["n_subset_late"], cell["subset_share_early"] or 0.0, cell["subset_share_late"] or 0.0,
            _g(g["early"]), _g(g["late"]), g["cell_verdict"], (" R3:" + ",".join(degenerate)) if degenerate else ""))
    print("guard: untestable {} · episode_thin {} · ok {}".format(
        guard["cells_untestable"] or "-", guard["cells_episode_thin"] or "-", guard["cells_ok"] or "-"))
    if lf["registration"]["excluded_cells_proposed"]:
        print("R3 제외 제안: " + ", ".join(f"{e['cell']}|{e['block']}" for e in lf["registration"]["excluded_cells_proposed"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="저장소 루트(테스트용 임시 복사본 지정 가능)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    contract = load_contract_v14(root)
    if contract.get("development_protocol", {}).get("track_open") is not True:
        print("track_open 이 true 가 아니다 — P0 는 track_open 승인 뒤에만 측정한다.")
        return 2
    out = root / OUT_RELATIVE
    if out.exists():
        # 사전등록 근거(등록·가드 실측)는 불변 산출물이다 — 조용히 덮어쓰면 계약 diagnostics_content_hash 와 어긋난 채 등록 근거가 바뀐다.
        print(f"{OUT_RELATIVE.as_posix()} 가 이미 있다 — P0 산출물은 덮어쓰지 않는다(exit 2, 아카이브 미열람). "
              "재생성이 정말 의도라면 그 파일을 먼저 의도적으로 삭제한 뒤 다시 실행하고, 새 content_hash 를 계약 "
              "rung1_conditional_blocks.diagnostics_content_hash 와 episode_guard.measurement.measured_by 에 옮겨 적어야 한다.")
        return 2
    theta = float(contract["targets"]["rv_conditional_transition"]["theta"])
    ctx = panel_context(read_market_observations(root), theta=theta)
    report = build_report(contract, ctx)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n",
                   encoding="utf-8", newline="\n")
    print_summary(report)
    print("wrote", out.relative_to(root).as_posix(), "·", report["content_hash"][:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())
