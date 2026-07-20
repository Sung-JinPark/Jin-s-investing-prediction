"""P1.7-S4: base_rates 다이제스트 테스트 — 앵커링 방지 계약 포함."""

from __future__ import annotations

import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ai_fc import base_rates
from ai_fc.db import ingest
from ai_fc.ml.history import append_run
from ai_fc.models import EvidenceBrief, Question
from ai_fc.reasoning_core import build_user_prompt

REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    updated: 2099-06-01
    questions:
      - id: fixture-coin-ath
        title: "픽스처코인 ATH"
        question: "픽스처코인이 2099-12-31까지 사상 최고가를 경신할 확률은?"
        deadline: 2099-12-31
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        action_link: "테스트"
        status: active
        created: 2099-06-01
""")

LEDGER = "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    (tmp_path / "forecasts").mkdir()
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    return tmp_path


def _ml_payload(run_ts: str) -> dict:
    return {
        "run_ts": run_ts, "kind": "ml",
        "forecasts": [
            # 매핑 참조 확률 0.7317 — 다이제스트에 절대 나타나면 안 되는 값
            {"question_id": "fixture-coin-ath", "model": "ensemble", "kind": "terminal",
             "prob": 0.7317, "threshold": 27000.0, "horizon_weeks": 10, "detail": {}},
        ],
        "sentiment": [{"feed": "fx", "n_headlines": 10, "score": 0.05}],
        "series_bands": {
            "q_ixic": {"symbol": "^IXIC", "horizon_weeks": 10, "last_value": 26107.0,
                       "terminal": {"q10": 23477.0, "q25": 25264.0, "q50": 27125.0,
                                    "q75": 28942.0, "q90": 30683.0},
                       "median_pct": 0.039,
                       "gbm": {"mu_w": 0.001, "sigma_w": 0.025}},
        },
        "sentiment_overall": 0.05,
    }


def test_digest_contains_bands_not_mapped_probs(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    append_run(repo, _ml_payload(datetime.now().isoformat(timespec="seconds")))
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath")
    assert d is not None
    assert "27,125" in d            # 분위수 밴드는 포함
    assert "0.7317" not in d        # 매핑 참조 확률은 미포함 (앵커링 방지 계약)
    assert "73%" not in d
    assert "매매 신호 아님" in d


def test_digest_stale_returns_none(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    old = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    append_run(repo, _ml_payload(old))
    ingest.sync(conn, repo)
    assert base_rates.ml_digest(repo, conn, "fixture-coin-ath") is None


def test_digest_absent_history_returns_none(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    assert base_rates.ml_digest(repo, conn, "fixture-coin-ath") is None


def test_digest_max_chars_cut(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    append_run(repo, _ml_payload(datetime.now().isoformat(timespec="seconds")))
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath", max_chars=50)
    assert d is not None and len(d) <= 50


def test_prompt_unchanged_without_aux() -> None:
    q = Question(
        question_id="fixture-coin-ath", title="t", question="q?",
        deadline_kind="fixed", deadline=date(2099, 12, 31), rolling_days=None,
        resolution="YES", resolution_source="src", domain="fixture",
        cadence_raw="주 1회", schedule=[{"per_week": 1}], action_link="",
        status="active", created=date(2099, 6, 1), notes="",
        required_snapshots=[], src_hash="x")
    briefs = [EvidenceBrief("general", "본문", 3, 0.1, 100, 50)]
    base = build_user_prompt(q, briefs, date(2099, 6, 15), None)
    same = build_user_prompt(q, briefs, date(2099, 6, 15), None, aux_context=None)
    assert base == same
    with_aux = build_user_prompt(q, briefs, date(2099, 6, 15), None, aux_context="참조 A")
    assert "참조 A" in with_aux and "Outside view 보조" in with_aux
