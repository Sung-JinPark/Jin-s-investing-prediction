"""ml 레이어 단위 테스트 — 네트워크·모델 다운로드 불필요 (래퍼 로직만)."""

from __future__ import annotations

import pytest

from ai_fc.ml.chronos_fc import QuantileForecast
from ai_fc.ml.sentiment import FeedSentiment


def _fc(vals: dict[str, float]) -> QuantileForecast:
    return QuantileForecast(
        symbol="TEST", context_len=100, horizon=10,
        quantiles={k: [v] * 10 for k, v in vals.items()},
        last_value=100.0)


def test_prob_above_interpolation() -> None:
    fc = _fc({"q10": 80, "q25": 90, "q50": 100, "q75": 110, "q90": 120})
    assert fc.prob_above(100) == pytest.approx(0.50, abs=0.01)   # 중앙값 = 50%
    assert fc.prob_above(110) == pytest.approx(0.25, abs=0.01)   # q75 상회 = 25%
    assert fc.prob_above(85) == pytest.approx(0.825, abs=0.01)   # q10~q25 보간
    assert fc.prob_above(70) > 0.9                                # 분포 하단 밖 캡
    assert fc.prob_above(130) < 0.1                               # 분포 상단 밖 캡


def test_terminal_pct() -> None:
    fc = _fc({"q10": 80, "q25": 90, "q50": 105, "q75": 110, "q90": 120})
    assert fc.terminal_pct("q50") == pytest.approx(0.05)


def test_feed_sentiment_dataclass_defaults() -> None:
    f = FeedSentiment(feed="x", n_headlines=0, score=0.0)
    assert f.top_negative == [] and f.top_positive == []


def test_ml_gate_docstring_present() -> None:
    """ML 게이트 준수 선언이 패키지에 명문화되어 있는지 (문서 계약 검증)."""
    import ai_fc.ml as ml
    assert "학습" in ml.__doc__ and "추론" in ml.__doc__
