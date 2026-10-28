"""F01 후속 — RV 셀 Brier 의 기계적/비기계적 원점 분해 (사전등록 → 실행, 진단 전용).

외부 리뷰(2026-10-27)가 확정한 간극: rv_mechanics 는 '양성 중 기계적 확정 비율'(85/70/55%)만
측정했고, 그것으로 "BSS 의 큰 몫" 을 귀속한 서술은 철회됐다 — 사건의 구성과 모델의 성적
기여는 다른 양이다. 이 모듈이 그 빠진 측정을 한다:

    ΔBS ≡ E[L_clim − L_PB]
        = P(M)·E[ΔL | M] + P(¬M)·E[ΔL | ¬M]        (정확 분해 — 재결합 항등 검사)

    M = 원점에서 기계적으로 확정된 양성 (rv_floor(k=1) > θ — Q4 정리: argmax_k ≡ 1)

코호트 2개:
1. **설계창** (2007-2014, stride 21 — rv_mechanics 와 동일 96원점, rv_h5/h21/h63):
   라벨·기계적 플래그는 rv_mechanics `results.json` 그대로(감사 추정식·NASDAQCOM 그리드),
   PB 확률은 동결 계수·생산 수식(compute_cells 의 per-row 동형)을 생산 패널
   (VIX∩NASDAQCOM 그리드)에서 결정론 재계산, climatology 는 동결 artifact 의
   clim_base_rate. **PB 계수가 이 창에서 적합됐으므로 in-sample 진단이다.**
2. **라이브 성숙 코호트** (vol_live_resolutions 의 rv 셀, (cell,origin) dedupe):
   원장의 p·climatology·label·Brier 를 그대로 쓰고(무수정), 기계적 플래그만 원점 정보로
   재계산한다. 표본이 작다 — 수치는 기술 통계이지 판정이 아니다.

주장의 경계 (prereg claims_excluded 와 동일):
- 진단·기술 분해다 — 캘리브레이션 표본 아님, 등록 검정 아님, 증분 예측력 증거 아님
  (CLAUDE.md 5-5 결정론 수치모델 예외 범위).
- 설계창 수치는 in-sample, 라이브 수치는 소표본 — 어느 쪽도 다른 창으로 외삽하지 않는다.
- V13 원장·동결 계수·게이트 판정 체계는 무수정·무영향.

읽기: 시장 아카이브(전 기간)·rv_mechanics 산출물·동결 계수·해소 원장 — 전부 read-only,
노출은 exposures.jsonl 에 기록한다 (purpose=audit, OPEN — 계약의 '소모' 아님).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ...timeseries_v2.market_archive import read_market_observations
from ...timeseries_v13 import contracts as C13
from ...timeseries_v13 import features as F13
from ...timeseries_v13.pipeline import HISTORY_START
from ...timeseries_v13.resolve import distinct_resolutions, pinned_coefficients_sha
from ..records import require_utc
from .rv_mechanics import EXPERIMENT_RELATIVE as RV_MECH_RELATIVE
from .rv_mechanics import mechanical_positive

EXPERIMENT_RELATIVE = Path("data/mts_research/experiments/rv_brier_decomposition")
RV_CELLS = ("rv_h5", "rv_h21", "rv_h63")


class MtsRvDecompError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 순수 분해 수학 — 합성 테스트 대상
# ---------------------------------------------------------------------------


def stratified_decomposition(
    delta_losses: np.ndarray, mechanical: np.ndarray
) -> dict[str, Any]:
    """ΔBS = P(M)·E[ΔL|M] + P(¬M)·E[ΔL|¬M] — 재결합 항등을 결과에 포함한다."""
    d = np.asarray(delta_losses, dtype=float)
    m = np.asarray(mechanical, dtype=bool)
    if d.shape != m.shape or d.ndim != 1 or d.size == 0 or not np.isfinite(d).all():
        raise MtsRvDecompError("ΔL 과 플래그는 같은 길이의 유한 1차원")
    n = d.size
    n_m = int(m.sum())
    share = n_m / n
    mean_total = float(d.mean())
    mean_m = float(d[m].mean()) if n_m else None
    mean_nm = float(d[~m].mean()) if n_m < n else None
    contribution_m = share * mean_m if mean_m is not None else 0.0
    contribution_nm = (1.0 - share) * mean_nm if mean_nm is not None else 0.0
    recombined = contribution_m + contribution_nm
    if abs(recombined - mean_total) > 1e-12:
        raise MtsRvDecompError(f"분해 재결합 불일치: {recombined} != {mean_total}")
    return {
        "n": n, "n_mechanical": n_m, "share_mechanical": round(share, 6),
        "delta_bs_total": round(mean_total, 8),
        "delta_bs_mechanical": None if mean_m is None else round(mean_m, 8),
        "delta_bs_nonmechanical": None if mean_nm is None else round(mean_nm, 8),
        "contribution_mechanical": round(contribution_m, 8),
        "contribution_nonmechanical": round(contribution_nm, 8),
    }


def stratum_scores(
    p_model: np.ndarray, p_clim: np.ndarray, y: np.ndarray, mask: np.ndarray
) -> dict[str, Any]:
    """한 층(stratum)의 Brier 수준·BSS — 분모 0 이면 NOT_IDENTIFIABLE (A.1)."""
    if not mask.any():
        return {"n": 0, "status": "EMPTY"}
    pm, pc, yy = p_model[mask], p_clim[mask], y[mask]
    loss_model = float(np.mean((pm - yy) ** 2))
    loss_clim = float(np.mean((pc - yy) ** 2))
    total_clim = float(np.sum((pc - yy) ** 2))
    out: dict[str, Any] = {
        "n": int(mask.sum()),
        "base_rate": round(float(yy.mean()), 6),
        "brier_model": round(loss_model, 8),
        "brier_climatology": round(loss_clim, 8),
    }
    if total_clim <= 0.0:
        out["bss"] = None
        out["status"] = "BSS_NOT_IDENTIFIABLE"
    else:
        out["bss"] = round(1.0 - loss_model / loss_clim, 6)
        out["status"] = "OK"
    return out


# ---------------------------------------------------------------------------
# 동결 PB 확률 — compute_cells 의 per-row 동형 (동결 모듈 무수정 import-only)
# ---------------------------------------------------------------------------


def pb_probability_at(frozen: dict[str, Any], panel: dict[str, np.ndarray],
                      index: int, cell_name: str) -> float:
    """생산 경로(pipeline.compute_cells)와 같은 수식을 패널의 임의 행에 적용한다.

    EWMA 는 인과(causal) 필터라 전체 배열의 [index] 값이 당시 계산값과 동일하다.
    생산과 동일하게 p 는 6자리 반올림으로 반환한다.
    """
    cell = frozen["cells"][cell_name]
    vix, rv = panel["vix"], panel["rv21"]
    vix_ewma = F13.ewma(vix, frozen["alpha_ewma"])
    rv_f = F13.fill_rv_nan(rv, frozen["rv_nan_fill_median"])
    rv_ewma = F13.ewma(rv_f, frozen["alpha_ewma"])
    inputs = {
        "vix_close": float(vix[index]), "vix_close_ewma21": float(vix_ewma[index]),
        "rv21_ann": float(rv_f[index]), "rv21_ann_ewma21": float(rv_ewma[index]),
    }
    x_row = np.array([inputs[key] for key in cell["feature_names"]], float)
    p_raw, _ = F13.delta_method_se(
        np.asarray(cell["beta"], float), np.asarray(cell["cov_beta"], float),
        np.asarray(cell["mu"], float), np.asarray(cell["sd"], float), x_row,
    )
    p = float(p_raw)
    if cell.get("iso_map"):
        p = float(F13.pav_apply(cell["iso_map"], p)[0])
    return round(p, 6)


# ---------------------------------------------------------------------------
# 실행 (prereg 선기록 — 결과 후 좌표 변경 금지)
# ---------------------------------------------------------------------------


def _nasdaq_returns(root: Path) -> tuple[list[str], np.ndarray]:
    """감사 그리드(NASDAQCOM 관측일 전체)의 로그수익 — rv_mechanics 와 동일 규약."""
    closes = F13._series(read_market_observations(root), "NASDAQCOM")
    dates = sorted(closes)
    prices = np.array([closes[d] for d in dates], dtype=float)
    returns = np.concatenate([[np.nan], np.diff(np.log(prices))])
    return dates, returns


def preregister_and_run(
    root: Path, *, now: datetime, output_root: Path | None = None
) -> dict[str, Any]:
    require_utc(now, field="now")
    output_root = output_root or root

    rv_mech_dir = root / RV_MECH_RELATIVE
    mech_prereg = json.loads((rv_mech_dir / "prereg.json").read_text(encoding="utf-8"))
    mech_results = json.loads((rv_mech_dir / "results.json").read_text(encoding="utf-8"))

    contract = C13.load_contract_v13(root)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    frozen = C13.load_frozen_coefficients(
        root,
        expected_sha256=frozen_cfg.get("sha256"),
        expected_content_hash=frozen_cfg.get("content_hash"),
        expected_finalist_id=frozen_cfg.get("finalist_id"),
    )
    theta = float(mech_prereg["theta"])

    prereg = {
        "experiment_id": "RV_BRIER_DECOMP_v1",
        "registered_at": now.isoformat(),
        "purpose": "F01 후속 — ΔBS 의 기계적/비기계적 층 분해 (진단)",
        "formula": "delta_bs_total == share_mech*delta_bs_mech + (1-share)*delta_bs_nonmech (항등 검사)",
        "mechanical_flag": "rv_floor(k=1) > theta (Q4: argmax_k==1)",
        "theta": theta,
        "design_cohort": {
            "source": "rv_mechanics results.json per_origin (라벨·플래그 그대로)",
            "source_prereg_hash": mech_prereg["content_hash"],
            "cells": list(RV_CELLS),
            "pb_probability": "동결 계수 + compute_cells per-row 동형, 생산 패널(VIX∩NASDAQCOM)",
            "climatology": "동결 artifact clim_base_rate (설계창 고정)",
            "caveat": "PB 계수가 같은 창에서 적합 — in-sample 진단",
        },
        "live_cohort": {
            "source": "vol_live_resolutions.jsonl rv 셀, (cell,origin) dedupe (계약 dedupe_rule)",
            "scores": "원장 brier_model/brier_climatology 그대로 (무수정)",
            "flags": "원점 시점 재계산 (감사 그리드 NASDAQCOM 수익)",
        },
        "grid_note": "라벨·플래그=NASDAQCOM 그리드(감사 규약), PB 확률=VIX∩NASDAQCOM 생산 그리드",
        "claims_excluded": [
            "캘리브레이션 표본 아님 — 진단 (CLAUDE.md 5-5)",
            "등록 검정 아님 — p-value·기각 없음, 기술 분해",
            "증분 예측력 증거 아님 — 설계창은 in-sample, 라이브는 소표본",
            "창 간 외삽 금지",
        ],
        "frozen_coefficients_sha256": frozen_cfg.get("sha256"),
    }
    prereg["content_hash"] = C13.canonical_hash(prereg)
    experiment_dir = output_root / EXPERIMENT_RELATIVE
    experiment_dir.mkdir(parents=True, exist_ok=True)
    prereg_path = experiment_dir / "prereg.json"
    if prereg_path.is_file():
        existing = json.loads(prereg_path.read_text(encoding="utf-8"))
        volatile = ("registered_at", "content_hash")
        if {k: v for k, v in existing.items() if k not in volatile} != {
            k: v for k, v in prereg.items() if k not in volatile
        }:
            raise MtsRvDecompError("prereg 가 이미 존재하고 좌표가 다르다 — 결과 후 변경 금지")
        prereg = existing  # 영속본이 정본 — 재실행이 해시를 새로 만들지 않는다
    else:
        prereg_path.write_text(
            json.dumps(prereg, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    # ── 공통 입력 ──────────────────────────────────────────────────────────
    dates, returns = _nasdaq_returns(root)
    date_index = {d: i for i, d in enumerate(dates)}
    panel = F13.build_panel(read_market_observations(root), start=HISTORY_START)
    panel_index = {str(d): i for i, d in enumerate(panel["dates"])}

    # ── 코호트 1: 설계창 ───────────────────────────────────────────────────
    design: dict[str, Any] = {}
    for cell_name in RV_CELLS:
        h = int(cell_name.rsplit("h", 1)[1])
        key = f"h{h}"
        clim = float(frozen["cells"][cell_name]["clim_base_rate"])
        y_list: list[float] = []
        p_list: list[float] = []
        m_list: list[bool] = []
        for row in mech_results["per_origin"]:
            origin = row["origin"]
            if origin not in panel_index:
                raise MtsRvDecompError(f"설계 원점 {origin} 이 생산 패널에 없다")
            # 플래그 교차검증 — 감사 그리드에서 재계산한 값이 저장 플래그와 일치해야 한다
            recomputed = mechanical_positive(returns, date_index[origin], h, theta)
            if bool(recomputed["mechanically_determined"]) != bool(row[key]["mechanically_determined"]):
                raise MtsRvDecompError(f"{origin} h{h}: 기계적 플래그 재계산 불일치")
            y_list.append(1.0 if row[key]["label"] else 0.0)
            m_list.append(bool(row[key]["mechanically_determined"]))
            p_list.append(pb_probability_at(frozen, panel, panel_index[origin], cell_name))
        y = np.array(y_list)
        p = np.array(p_list)
        m = np.array(m_list, dtype=bool)
        pc = np.full_like(p, clim)
        delta = (pc - y) ** 2 - (p - y) ** 2
        design[cell_name] = {
            "climatology": round(clim, 6),
            "decomposition": stratified_decomposition(delta, m),
            "mechanical": stratum_scores(p, pc, y, m),
            "nonmechanical": stratum_scores(p, pc, y, ~m),
            "all": stratum_scores(p, pc, y, np.ones_like(m, dtype=bool)),
        }

    # ── 코호트 2: 라이브 성숙 ──────────────────────────────────────────────
    live: dict[str, Any] = {}
    resolutions_path = root / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl"
    raw_rows = [
        json.loads(line)
        for line in resolutions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    deduped = distinct_resolutions(raw_rows, pinned_sha=pinned_coefficients_sha(root))
    for cell_name in RV_CELLS:
        rows = sorted(
            (r for r in deduped if r.get("cell") == cell_name),
            key=lambda r: str(r.get("origin")),
        )
        if not rows:
            live[cell_name] = {"n": 0, "status": "NO_MATURED_ORIGINS"}
            continue
        h = int(cell_name.rsplit("h", 1)[1])
        y = np.array([float(r["label"]) for r in rows])
        p = np.array([float(r["probability"]) for r in rows])
        pc = np.array([float(r["climatology_base_rate"]) for r in rows])
        delta = np.array(
            [float(r["brier_climatology"]) - float(r["brier_model"]) for r in rows]
        )
        m = np.array(
            [
                bool(
                    mechanical_positive(
                        returns, date_index[str(r["origin"])], h, theta
                    )["mechanically_determined"]
                )
                for r in rows
            ],
            dtype=bool,
        )
        live[cell_name] = {
            "decomposition": stratified_decomposition(delta, m),
            "mechanical": stratum_scores(p, pc, y, m),
            "nonmechanical": stratum_scores(p, pc, y, ~m),
            "all": stratum_scores(p, pc, y, np.ones_like(m, dtype=bool)),
            "note": "소표본 기술 통계 — 판정 아님",
        }

    results = {
        "prereg_content_hash": prereg["content_hash"],
        "generated_at": now.isoformat(),
        "design_window": design,
        "live_matured": live,
    }
    (experiment_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    # 노출 영수증 — 아카이브 전 기간 읽기(라벨 꼬리 포함)를 기록한다 (T50; 같은 body 재실행은 no-op)
    from ..artifacts import record_exposure

    record_exposure(
        output_root,
        run_id="rv-brier-decomp-v1",
        purpose="audit",
        series=["NASDAQCOM", "VIX"],
        window=[HISTORY_START, None],
        windows_hit=[],
        allowed=True,
        reason_codes=[
            "F01_FOLLOWUP_DIAGNOSTIC",
            f"prereg:{prereg['content_hash'][:16]}",
            "open-end window: 설계 라벨 꼬리(~2015-03-09)와 라이브 현재까지 포함",
        ],
    )
    return results
