"""Sprint 3 — resolver·report 테스트 (합성 픽스처)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ai_fc import files as F
from ai_fc.db import ingest
from ai_fc.report import render_report
from ai_fc.resolver import resolve_question

REGISTRY = textwrap.dedent("""\
    version: 1
    questions:
      - id: fixture-past
        title: "픽스처 기한경과"
        question: "가공 이벤트?"
        deadline: 2099-06-01
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule: [{per_week: 1}]
        action_link: "테스트"
        status: active
        created: 2099-05-01
""")

FORECAST = textwrap.dedent("""\
    ---
    forecast_id: 2099-05-10_fixture-past_r1
    question_id: fixture-past
    question_snapshot: "가공 이벤트?"
    timestamp: 2099-05-10 09:00 KST
    phase: P1
    model: test
    prompt_version: reasoning_core_v1
    probability: 70
    ci80: [55, 85]
    window_end: null
    snapshots: {}
    market_implied: null
    edge: null
    sources_count: 1
    ---
    본문
""")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(REGISTRY, encoding="utf-8")
    fdir = tmp_path / "forecasts" / "2099"
    fdir.mkdir(parents=True)
    (fdir / "2099-05-10_fixture-past_r1.md").write_text(FORECAST, encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n",
        encoding="utf-8")
    return tmp_path


def test_resolve_appends_ledger_and_scores(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    resolve_question(conn, repo, "fixture-past", outcome="yes",
                     forecast_id=None, evidence="가공 근거", assume_yes=True)
    rows = F.parse_ledger(repo / "calibration" / "ledger.csv")
    assert len(rows) == 1
    assert rows[0].brier == pytest.approx(0.09)  # (0.7-1)^2 수기 계산
    # 멱등: 재실행 시 이미 채점됨 → 원장 무변화
    resolve_question(conn, repo, "fixture-past", outcome="yes",
                     forecast_id=None, evidence="", assume_yes=True)
    assert len(F.parse_ledger(repo / "calibration" / "ledger.csv")) == 1


def test_resolve_void_writes_nothing(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    resolve_question(conn, repo, "fixture-past", outcome="void",
                     forecast_id=None, evidence="", assume_yes=True)
    assert len(F.parse_ledger(repo / "calibration" / "ledger.csv")) == 0


def test_report_renders(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    resolve_question(conn, repo, "fixture-past", outcome="no",
                     forecast_id=None, evidence="", assume_yes=True)
    out = render_report(conn, repo)
    html = out.read_text(encoding="utf-8")
    assert "캘리브레이션" in html
    assert "0.49" in html  # (0.7-0)^2 = 0.49
    assert "미성숙" in html  # 표본 30 미만 배너
