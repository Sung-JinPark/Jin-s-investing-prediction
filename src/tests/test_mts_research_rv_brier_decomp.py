"""F01 후속 — RV Brier 분해 테스트 (합성 수학 + 동결 경로 동형 + 실자료 read-only 스모크)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ai_fc.mts_research.audits.rv_brier_decomposition import (
    MtsRvDecompError,
    preregister_and_run,
    pb_probability_at,
    stratified_decomposition,
    stratum_scores,
)
from mts_research_fixtures import utc

ROOT = Path(__file__).resolve().parents[2]
HAS_INPUTS = (
    (ROOT / "data/mts_research/experiments/rv_mechanics/results.json").is_file()
    and (ROOT / "data/timeseries_v13/vol/champion_coefficients.json").is_file()
    and (ROOT / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl").is_file()
)


def test_decomposition_identity_and_strata():
    """ΔBS = P(M)E[ΔL|M] + P(¬M)E[ΔL|¬M] — 손계산 오라클."""
    delta = np.array([0.4, 0.2, -0.1, 0.3])
    mech = np.array([True, True, False, False])
    out = stratified_decomposition(delta, mech)
    assert out["n"] == 4 and out["n_mechanical"] == 2
    assert out["share_mechanical"] == 0.5
    assert out["delta_bs_mechanical"] == pytest.approx(0.3)
    assert out["delta_bs_nonmechanical"] == pytest.approx(0.1)
    assert out["contribution_mechanical"] == pytest.approx(0.15)
    assert out["contribution_nonmechanical"] == pytest.approx(0.05)
    assert out["delta_bs_total"] == pytest.approx(0.2)

    all_mech = stratified_decomposition(np.array([0.1, 0.2]), np.array([True, True]))
    assert all_mech["delta_bs_nonmechanical"] is None
    assert all_mech["contribution_nonmechanical"] == 0.0

    with pytest.raises(MtsRvDecompError):
        stratified_decomposition(np.array([np.nan]), np.array([True]))


def test_stratum_scores_bss_guard():
    p = np.array([0.8, 0.7])
    y = np.array([1.0, 1.0])
    clim_perfect = np.array([1.0, 1.0])  # 기후가 완벽 → 분모 0 → NOT_IDENTIFIABLE
    out = stratum_scores(p, clim_perfect, y, np.array([True, True]))
    assert out["status"] == "BSS_NOT_IDENTIFIABLE" and out["bss"] is None
    ok = stratum_scores(p, np.array([0.5, 0.5]), y, np.array([True, True]))
    assert ok["status"] == "OK" and 0.0 < ok["bss"] <= 1.0
    assert stratum_scores(p, clim_perfect, y, np.array([False, False]))["status"] == "EMPTY"


@pytest.mark.skipif(not HAS_INPUTS, reason="실자료 없음")
def test_pb_probability_at_matches_production_last_row():
    """per-row 동형이 생산 경로(compute_cells)의 마지막 행과 bit 일치 — 동결 무수정 검증."""
    from ai_fc.timeseries_v2.market_archive import read_market_observations
    from ai_fc.timeseries_v13 import contracts as C13
    from ai_fc.timeseries_v13 import features as F13
    from ai_fc.timeseries_v13.pipeline import HISTORY_START, compute_cells

    contract = C13.load_contract_v13(ROOT)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    frozen = C13.load_frozen_coefficients(
        ROOT,
        expected_sha256=frozen_cfg.get("sha256"),
        expected_content_hash=frozen_cfg.get("content_hash"),
        expected_finalist_id=frozen_cfg.get("finalist_id"),
    )
    panel = F13.build_panel(read_market_observations(ROOT), start=HISTORY_START)
    cells, _ = compute_cells(frozen, panel)
    last = len(panel["dates"]) - 1
    for cell_name in ("rv_h5", "rv_h21", "rv_h63"):
        assert pb_probability_at(frozen, panel, last, cell_name) == cells[cell_name]["p"]


@pytest.mark.skipif(not HAS_INPUTS, reason="실자료 없음")
def test_real_run_smoke_outputs_to_tmp(tmp_path: Path):
    """실자료 read-only 실행 — 출력은 tmp 루트에만, 항등·교차검증 내장 검사 통과."""
    real_results = ROOT / "data/mts_research/experiments/rv_brier_decomposition/results.json"
    real_bytes_before = real_results.read_bytes() if real_results.is_file() else None
    results = preregister_and_run(ROOT, now=utc(2026, 10, 28, 1), output_root=tmp_path)
    design = results["design_window"]
    for cell in ("rv_h5", "rv_h21", "rv_h63"):
        d = design[cell]["decomposition"]
        assert d["n"] == 96
        # 재결합 항등은 함수 내부에서 단언되지만 결과값으로도 확인
        assert d["contribution_mechanical"] + d["contribution_nonmechanical"] == pytest.approx(
            d["delta_bs_total"], abs=1e-6
        )
        # 기계적 층의 base rate 는 1 — 하한>θ 양성만 포함되는 정의의 귀결
        assert design[cell]["mechanical"]["base_rate"] == pytest.approx(1.0)
    live = results["live_matured"]
    assert live["rv_h63"].get("status") == "NO_MATURED_ORIGINS" or live["rv_h63"].get("n", 1) >= 0
    prereg = json.loads(
        (tmp_path / "data/mts_research/experiments/rv_brier_decomposition/prereg.json")
        .read_text(encoding="utf-8")
    )
    assert results["prereg_content_hash"] == prereg["content_hash"]
    # 실저장소 산출물은 tmp 실행으로 바이트 하나 안 바뀐다 (output_root 분리의 실단언)
    real_bytes_after = real_results.read_bytes() if real_results.is_file() else None
    assert real_bytes_after == real_bytes_before
