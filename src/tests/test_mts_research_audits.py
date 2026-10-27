"""W4 감사 도구 테스트 — rv_floor 닫힌형·splice 탐지(T13)·섭동 하니스·단조성 보고."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ai_fc.mts_research.audits.coherence import v13_monotonicity_report
from ai_fc.mts_research.audits.objective_align import run_perturbation_harness
from ai_fc.mts_research.audits.rv_mechanics import (
    MtsRvAuditError,
    _rolling_rv_matrix,
    mechanical_positive,
    rv_floor,
    window_mechanics_probability,
)
from ai_fc.mts_research.audits.time_audit import splice_artifact_check
from ai_fc.mts_research.targets import RV_WINDOW, decompose_rv21, log_returns, rv21_annualized


def test_rv_floor_matches_numeric_minimum():
    """닫힌형 하한이 수치 최소화와 일치하고, 어떤 미래 경로도 하한 아래로 못 간다."""
    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.02, 120)
    t = 60
    for k in (1, 5, 10, 20):
        decomposition = decompose_rv21(returns, t, k)
        floor = rv_floor(
            decomposition.known_sum, decomposition.known_sumsq, decomposition.n_known, k
        )
        # 무작위 미래 경로 전수에서 floor 이하가 나오지 않는다
        best = math.inf
        for _ in range(3000):
            future = rng.normal(0, 0.02, k)
            total = decomposition.known_sum + future.sum()
            total_sq = decomposition.known_sumsq + (future**2).sum()
            variance = (total_sq - total * total / RV_WINDOW) / (RV_WINDOW - 1)
            best = min(best, math.sqrt(max(variance, 0.0) * 252.0))
        assert best >= floor - 1e-9
        # 최적 경로(모든 미래 수익 동일 = F1*/k)에서 floor 에 도달
        f1 = decomposition.known_sum * k / (RV_WINDOW - k)
        future_opt = np.full(k, f1 / k)
        total = decomposition.known_sum + future_opt.sum()
        total_sq = decomposition.known_sumsq + (future_opt**2).sum()
        achieved = math.sqrt(
            max((total_sq - total * total / RV_WINDOW) / (RV_WINDOW - 1), 0.0) * 252.0
        )
        # k=20 은 floor 가 수학적으로 0 (알려진 수익 1개 — 분산 기여 없음) → sqrt 근처
        # fp 노이즈만 남는다. 연율화 vol 척도에서 1e-6 이면 전 구간 충분히 엄격하다.
        assert achieved == pytest.approx(floor, abs=1e-6)
    assert rv_floor(0.1, 0.01, 0, 21) == 0.0  # k>=21: 알려진 부분 없음 → 하한 0


def test_mechanical_positive_detects_known_window():
    """원점 직전 폭등 수익만으로 사건이 확정되는 합성 사례를 탐지한다."""
    calm = np.full(140, 0.001)
    calm[100:105] = 0.09  # 원점 직전 5일 폭등 — known window 가 θ 를 기계적으로 넘김
    t = 104
    verdict = mechanical_positive(calm, t, 5, theta=0.1694)
    assert verdict["mechanically_determined"] is True and verdict["max_floor"] > 0.1694
    quiet = mechanical_positive(np.full(140, 0.001), 104, 5, theta=0.1694)
    assert quiet["mechanically_determined"] is False


def test_rolling_rv_matrix_matches_estimator():
    """경로 롤링 rv 가 실제 추정식(rv21_annualized)과 일치한다."""
    rng = np.random.default_rng(7)
    prices = 1000 * np.exp(np.cumsum(rng.normal(0, 0.012, 160)))
    returns = log_returns(prices)
    rv = rv21_annualized(prices)
    t, h = 100, 10
    known_tail = returns[t - 19 : t + 1]
    future = returns[t + 1 : t + 1 + h][None, :]
    matrix = _rolling_rv_matrix(known_tail, future)
    for k in range(1, h + 1):
        assert matrix[0, k - 1] == pytest.approx(rv[t + k], abs=1e-10)


def test_window_mechanics_probability_contract():
    rng = np.random.default_rng(3)
    returns = np.concatenate([[np.nan], rng.normal(0, 0.012, 600)])
    out = window_mechanics_probability(
        returns, 400, 21, 0.25, generator="iid_resample_2520", n_paths=200, seed=1
    )
    assert 0.0 <= out["probability"] <= 1.0
    assert out["expectation_variant"]["label"] == "not_a_probability"  # T21
    with pytest.raises(MtsRvAuditError):
        window_mechanics_probability(
            returns, 400, 21, 0.25, generator="fancy_gan", n_paths=200, seed=1
        )


def test_t13_splice_artifact_detection():
    """다른 base 척도의 level 직결 → 인공 return 플래그; 같은 척도 → 통과 (T13)."""
    flagged = splice_artifact_check(
        ("2018-12-31", 92.4), ("2019-01-02", 115.1), typical_daily_move=0.003
    )
    assert flagged["artificial_splice_flagged"] is True
    ok = splice_artifact_check(
        ("2018-12-31", 92.4), ("2019-01-02", 92.6), typical_daily_move=0.003
    )
    assert ok["artificial_splice_flagged"] is False


def test_objective_align_harness_core_claims():
    """FHS 시그니처에 VARX fit 없음 + λ 스위치는 장기 분포를 바꾼다 (§8.3 정적 추적 실증)."""
    result = run_perturbation_harness(seed=20261026)
    for horizon in ("h21", "h63"):
        assert result[horizon]["varx_fit_in_fhs_signature"] is False
        assert result[horizon]["same_lambda_fhs_max_abs_diff"] == 0.0
        assert result[horizon]["lambda_switch_fhs_max_abs_quantile_diff"] > 0.0


def test_v13_monotonicity_report_synthetic(tmp_path: Path):
    """단조성 위반 측정 — 보고만 하고 '정합화 공개' 경로가 없다."""
    root = tmp_path / "repo"
    ledger = root / "data/timeseries_v13/ledgers/vol_live.jsonl"
    ledger.parent.mkdir(parents=True)
    rows = [
        {"as_of": "2026-10-01", "cells": {
            "vix25_h5": {"p": 0.10}, "vix25_h21": {"p": 0.25}, "vix25_h63": {"p": 0.55},
            "vix30_h5": {"p": 0.05},
        }},
        {"as_of": "2026-10-02", "cells": {
            "vix25_h5": {"p": 0.30}, "vix25_h21": {"p": 0.20},  # 지평 역전
            "vix30_h5": {"p": 0.40},                             # 임계 역전 (p30 > p25)
        }},
    ]
    ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    report = v13_monotonicity_report(root)
    assert report["rows_checked"] == 2
    assert len(report["horizon_monotonicity_violations"]) == 1
    assert len(report["threshold_monotonicity_violations"]) == 1


def test_q4_rv_floor_nonincreasing_in_k_and_argmax_is_one():
    """외부 리뷰 Q4 정리: 하한은 k 에 비증가(SS 부분집합 단조성) → argmax_k ≡ 1."""
    from ai_fc.mts_research.audits.rv_mechanics import mechanical_positive, rv_floor

    rng = np.random.default_rng(42)
    returns = np.concatenate([[np.nan], rng.normal(0, 0.012, 400)])
    for t in (60, 150, 300):
        floors = []
        for k in range(1, RV_WINDOW):
            d = decompose_rv21(returns, t, k)
            floors.append(rv_floor(d.known_sum, d.known_sumsq, d.n_known, k))
        assert all(floors[i] >= floors[i + 1] - 1e-12 for i in range(len(floors) - 1))
        result = mechanical_positive(returns, t, 63, theta=0.0001)
        assert result["argmax_k"] == 1


def test_q4_rv_floor_k1_bounded_by_origin_rv21():
    """rv_floor(1) <= RV21(원점) — V14 평온 자격(RV21<=θ)이 기계적 양성을 구조적으로 배제."""
    from ai_fc.mts_research.audits.rv_mechanics import rv_floor

    rng = np.random.default_rng(7)
    returns = np.concatenate([[np.nan], rng.normal(0, 0.015, 300)])
    for t in range(40, 290, 13):
        d = decompose_rv21(returns, t, 1)
        floor1 = rv_floor(d.known_sum, d.known_sumsq, d.n_known, 1)
        origin_rv = float(np.std(returns[t - RV_WINDOW + 1 : t + 1], ddof=1) * np.sqrt(252.0))
        assert floor1 <= origin_rv + 1e-12
