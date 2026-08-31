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

def test_gdelt_title_normalization_undoes_tokenization() -> None:
    """GDELT 제목은 토큰화 흔적으로 구두점 앞에 공백이 붙는다."""
    from ai_fc.ml.sentiment import normalize_title

    assert normalize_title("Nvidia Is My No . 1 Pick") == "Nvidia Is My No. 1 Pick"
    assert normalize_title("Up 401 % , DRAM Soars") == "Up 401%, DRAM Soars"
    assert normalize_title("  spaced   out  ") == "spaced out"


def test_gdelt_feeds_are_english_and_carry_attribution() -> None:
    """인용은 선택이 아니라 GDELT 허가의 조건이다 (DECISIONS 12-7)."""
    from ai_fc.ml import sentiment

    assert "gdeltproject.org" in sentiment.ATTRIBUTION
    assert len(sentiment.FEEDS) == 5
    for query in sentiment.FEEDS.values():
        assert "sourcelang:english" in query


def test_run_all_feeds_is_fail_soft_and_never_invents_neutral(monkeypatch) -> None:
    """수집이 전부 실패해도 0.0을 관측값으로 남기지 않는다."""
    from ai_fc.ml import sentiment

    def always_fails(*_args, **_kwargs):
        raise RuntimeError("GDELT down")

    monkeypatch.setattr(sentiment, "fetch_headlines", always_fails)
    monkeypatch.setattr(sentiment, "FEED_INTERVAL_SECONDS", 0.0)
    feeds = sentiment.run_all_feeds()

    assert len(feeds) == 5
    assert all(f.n_headlines == 0 for f in feeds)
    # runner는 총 헤드라인이 0이면 sentiment_overall을 None으로 기록한다.
    assert sum(f.n_headlines for f in feeds) == 0
