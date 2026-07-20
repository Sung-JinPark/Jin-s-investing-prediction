"""P1.7-S1: ML 이력(JSONL→DB) 동기화·질의 테스트 — 합성 픽스처만 (백테스트 금지)."""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_fc.db import ingest, queries
from ai_fc.ml.history import append_run, iter_history
from ai_fc.ml.mapping import QUESTION_MAPS

REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    updated: 2099-06-01
    questions:
      - id: fixture-coin-ath
        title: "픽스처코인 ATH"
        question: "픽스처코인이 2099-12-31까지 사상 최고가를 경신할 확률은?"
        deadline: 2099-12-31
        resolution: "YES = 가공 거래소 종가 신고가"
        resolution_source: "가공 거래소"
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


def _connect(repo_path: Path):
    return ingest.connect(repo_path / "db" / "index.db")


def _fresh_ts(days_ago: float = 0) -> str:
    return (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _payload(run_ts: str, prob: float = 0.6, low_confidence: bool = False) -> dict:
    detail = {"low_confidence": True} if low_confidence else {}
    return {
        "run_ts": run_ts, "kind": "ml",
        "forecasts": [
            {"question_id": "fixture-coin-ath", "model": "bolt", "kind": "terminal",
             "prob": prob, "threshold": 100.0, "horizon_weeks": 10, "detail": detail},
            {"question_id": "fixture-coin-ath", "model": "ensemble", "kind": "terminal",
             "prob": prob, "threshold": 100.0, "horizon_weeks": 10, "detail": detail},
        ],
        "sentiment": [{"feed": "fixture-feed", "n_headlines": 10, "score": 0.1}],
    }


def test_jsonl_append_and_iter(repo: Path) -> None:
    append_run(repo, _payload(_fresh_ts(1)))
    append_run(repo, _payload(_fresh_ts(0), prob=0.7))
    runs = list(iter_history(repo))
    assert len(runs) == 2
    assert runs[0]["forecasts"][0]["prob"] == 0.6


def test_sync_idempotent_and_rebuild(repo: Path) -> None:
    append_run(repo, _payload(_fresh_ts(0)))
    conn = _connect(repo)
    ingest.sync(conn, repo)
    n1 = conn.execute("SELECT COUNT(*) AS n FROM ml_forecasts").fetchone()["n"]
    ingest.sync(conn, repo)  # 멱등 — 해시 동일 시 재적재 없음
    n2 = conn.execute("SELECT COUNT(*) AS n FROM ml_forecasts").fetchone()["n"]
    assert n1 == n2 == 2  # bolt + ensemble

    # rebuild 후 완전 복원 (파일이 진실)
    ingest.sync(conn, repo, rebuild=True)
    n3 = conn.execute("SELECT COUNT(*) AS n FROM ml_forecasts").fetchone()["n"]
    ns = conn.execute("SELECT COUNT(*) AS n FROM ml_sentiment").fetchone()["n"]
    assert n3 == 2 and ns == 1


def test_append_after_sync_reingests(repo: Path) -> None:
    """append-only 파일의 해시 변경은 드리프트가 아니라 정상 재적재."""
    conn = _connect(repo)
    append_run(repo, _payload(_fresh_ts(2)))
    report = ingest.sync(conn, repo)
    assert report.ok
    append_run(repo, _payload(_fresh_ts(0), prob=0.8))
    report = ingest.sync(conn, repo)
    assert report.ok  # E1 아님
    n = conn.execute("SELECT COUNT(*) AS n FROM ml_forecasts").fetchone()["n"]
    assert n == 4


def test_latest_ml_refs_freshness_and_confidence(repo: Path) -> None:
    conn = _connect(repo)
    append_run(repo, _payload(_fresh_ts(30), prob=0.9))          # 오래됨 — 제외
    append_run(repo, _payload(_fresh_ts(1), prob=0.55))          # 최신
    ingest.sync(conn, repo)
    refs = queries.latest_ml_refs(conn, max_age_days=7)
    assert refs["fixture-coin-ath"].prob == pytest.approx(0.55)
    assert refs["fixture-coin-ath"].low_confidence is False

    append_run(repo, _payload(_fresh_ts(0), prob=0.4, low_confidence=True))
    ingest.sync(conn, repo)
    refs = queries.latest_ml_refs(conn, max_age_days=7)
    assert refs["fixture-coin-ath"].low_confidence is True


def test_sentiment_delta(repo: Path) -> None:
    conn = _connect(repo)
    p_old = _payload(_fresh_ts(8))
    p_old["sentiment"] = [{"feed": "fixture-feed", "n_headlines": 10, "score": -0.2}]
    p_new = _payload(_fresh_ts(0))
    p_new["sentiment"] = [{"feed": "fixture-feed", "n_headlines": 12, "score": 0.1}]
    append_run(repo, p_old)
    append_run(repo, p_new)
    ingest.sync(conn, repo)
    assert queries.sentiment_delta(conn, "fixture-feed", days=7) == pytest.approx(0.3)
    assert queries.sentiment_delta(conn, "없는피드", days=7) is None


def test_question_maps_registry_alignment() -> None:
    """QUESTION_MAPS의 qid가 실제 registry.yaml에 존재하고 mode가 유효한지 (배선 계약)."""
    import yaml

    from ai_fc import config
    reg = yaml.safe_load((config.ROOT / "questions" / "registry.yaml").read_text(encoding="utf-8"))
    ids = {q["id"] for q in reg["questions"]}
    valid_modes = {"above_path", "below_path", "above_terminal", "below_terminal"}
    for qm in QUESTION_MAPS:
        assert qm.question_id in ids, f"registry에 없는 qid: {qm.question_id}"
        assert qm.mode in valid_modes
        if qm.window:
            assert qm.window[0] < qm.window[1]
