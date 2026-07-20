"""P1.7-S3: 고정 중앙값 결합·불일치 지수 테스트 — 합성 분위수만 (네트워크·모델 불필요)."""

from __future__ import annotations

import pytest

from ai_fc.ml.chronos_fc import QuantileForecast, combine_median, disagreement, _align_covariates


def _fc(offset: float, horizon: int = 5) -> QuantileForecast:
    base = {"q10": 80.0, "q25": 90.0, "q50": 100.0, "q75": 110.0, "q90": 120.0}
    return QuantileForecast(
        symbol="TEST", context_len=100, horizon=horizon,
        quantiles={k: [v + offset] * horizon for k, v in base.items()},
        last_value=100.0)


def test_combine_median_is_elementwise_median() -> None:
    combined = combine_median([_fc(0), _fc(10), _fc(40)])
    assert combined.terminal("q50") == 110.0  # median(100,110,140)
    assert combined.terminal("q10") == 90.0


def test_combine_median_preserves_quantile_monotonicity() -> None:
    combined = combine_median([_fc(0), _fc(-5), _fc(7)])
    for i in range(combined.horizon):
        vals = [combined.quantiles[q][i] for q in ("q10", "q25", "q50", "q75", "q90")]
        assert vals == sorted(vals)  # 각 모델이 단조이면 원소별 중앙값도 단조


def test_combine_median_single_and_empty() -> None:
    fc = _fc(0)
    assert combine_median([fc]) is fc
    with pytest.raises(ValueError):
        combine_median([])


def test_disagreement_boundaries() -> None:
    assert disagreement({"a": 0.5}) == 0.0
    assert disagreement({"a": 0.40, "b": 0.55}) == pytest.approx(0.15)
    assert disagreement({"a": 0.4, "b": 0.5, "c": 0.62}) == pytest.approx(0.22)


def test_align_covariates_tail_alignment() -> None:
    out = _align_covariates(5, {"long": [1, 2, 3, 4, 5, 6, 7], "short": [9, 8]})
    assert list(out["long"]) == [3, 4, 5, 6, 7]     # 앞을 잘라 뒤끝 정렬
    assert list(out["short"]) == [9, 9, 9, 9, 8]    # 첫 값으로 앞을 채움
    assert all(len(v) == 5 for v in out.values())
