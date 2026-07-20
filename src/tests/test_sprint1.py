"""Sprint 1 단위 테스트 — 합성 미래 질문 픽스처만 사용 (백테스트 금지 원칙).

픽스처 이벤트는 전부 가공("fixture-coin ATH by 2099") — 실제 과거 질문을 쓰지 않는다.
"""

from __future__ import annotations

import shutil
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ai_fc import files as F
from ai_fc.db import ingest, queries
from ai_fc.models import ForecastRecord
from ai_fc.registry import (
    active_interval_days, compute_due, load_registry, propose_schedule,
)

NOW = datetime(2099, 6, 15, 9, 0)  # 합성 미래 기준시각


# ── 픽스처 리포 ──────────────────────────────────────────────────

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

      - id: fixture-rolling
        title: "픽스처 rolling"
        question: "90일 내 가공 지표 X가 임계값을 넘을 확률은?"
        deadline: rolling-90d
        resolution: "YES = 윈도우 내 X > 임계값"
        resolution_source: "가공 데이터"
        domain: fixture
        cadence: "주 2회"
        schedule:
          - per_week: 2
        action_link: "테스트"
        status: active
        created: 2099-06-01

      - id: fixture-manual
        title: "픽스처 manual"
        question: "schedule 없는 질문?"
        deadline: null
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "이상한 자유 텍스트 §%"
        action_link: "테스트"
        status: active
        created: 2099-06-01

      - id: fixture-expired
        title: "픽스처 기한경과"
        question: "기한 지난 질문?"
        deadline: 2099-06-01
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        action_link: "테스트"
        status: active
        created: 2099-05-01
""")

FORECAST_MD = textwrap.dedent("""\
    ---
    forecast_id: 2099-06-10_fixture-coin-ath_r1
    question_id: fixture-coin-ath
    question_snapshot: "픽스처코인 ATH?"
    timestamp: 2099-06-10 09:00 KST
    phase: P1
    model: test-model
    prompt_version: reasoning_core_v1
    probability: 42
    ci80: [30, 55]
    window_end: null
    snapshots:
      note: "테스트"
    market_implied: null
    edge: null
    sources_count: 3
    unknown_extra_key: "관대한 리더 검증"
    ---

    ## [5] 최종 출력
    - 최종 확률: 42%
""")

ROLLING_MD = textwrap.dedent("""\
    ---
    forecast_id: 2099-03-01_fixture-rolling_r1
    question_id: fixture-rolling
    question_snapshot: "rolling?"
    timestamp: 2099-03-01 09:00 KST
    phase: P1
    model: test-model
    prompt_version: reasoning_core_v1
    probability: 20
    ci80: [10, 35]
    window_end: 2099-05-30
    snapshots: {}
    market_implied: null
    edge: null
    sources_count: 2
    ---
    본문
""")

LEDGER = (
    "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n"
    "2099-06-01,fixture-old,2099-05-01_fixture-old_r1,2099-05-01,70,1,0.09,fixture,테스트\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    fdir = tmp_path / "forecasts" / "2099"
    fdir.mkdir(parents=True)
    (fdir / "2099-06-10_fixture-coin-ath_r1.md").write_text(FORECAST_MD, encoding="utf-8")
    (fdir / "2099-03-01_fixture-rolling_r1.md").write_text(ROLLING_MD, encoding="utf-8")
    (fdir / "2099-03-01_fixture-rolling_r1_evidence.md").write_text("증거 부록", encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    return tmp_path


def _connect(repo_path: Path):
    return ingest.connect(repo_path / "db" / "index.db")


# ── 파서 ────────────────────────────────────────────────────────

def test_parse_forecast_lenient(repo: Path) -> None:
    rec = F.parse_forecast_file(
        repo / "forecasts" / "2099" / "2099-06-10_fixture-coin-ath_r1.md")
    assert rec.probability == 42
    assert rec.ci80_lo == 30 and rec.ci80_hi == 55
    assert rec.round == 1
    assert rec.extra["unknown_extra_key"] == "관대한 리더 검증"  # 알 수 없는 키 보존


def test_evidence_files_excluded(repo: Path) -> None:
    stems = [p.stem for p in F.iter_forecast_files(repo / "forecasts")]
    assert all(not s.endswith("_evidence") for s in stems)
    assert len(stems) == 2


def test_stem_parse() -> None:
    assert ForecastRecord.parse_stem("2099-06-10_fixture-coin-ath_r12") == ("fixture-coin-ath", 12)
    assert ForecastRecord.parse_stem("TEMPLATE") is None


# ── 라이터 (불변성) ──────────────────────────────────────────────

def test_write_exclusive_refuses_overwrite(repo: Path) -> None:
    target = repo / "forecasts" / "2099" / "2099-06-10_fixture-coin-ath_r1.md"
    with pytest.raises(F.ImmutabilityError):
        F.write_forecast_exclusive(target, "덮어쓰기 시도")
    assert "덮어쓰기" not in target.read_text(encoding="utf-8")


def test_next_round(repo: Path) -> None:
    assert F.next_round(repo / "forecasts", "fixture-coin-ath") == 2
    assert F.next_round(repo / "forecasts", "never-seen") == 1


def test_validate_new_record() -> None:
    ok = {"forecast_id": "x", "question_id": "q", "timestamp": "t", "phase": "P1",
          "model": "m", "prompt_version": "v", "probability": 42, "ci80": [30, 55]}
    assert F.validate_new_record(ok) == []
    assert F.validate_new_record({**ok, "probability": 0})
    assert F.validate_new_record({**ok, "probability": 100})
    assert F.validate_new_record({**ok, "ci80": [55, 30]})


# ── ingest 멱등성·드리프트 ────────────────────────────────────────

def test_ingest_idempotent(repo: Path) -> None:
    conn = _connect(repo)
    r1 = ingest.sync(conn, repo)
    assert r1.ok, r1.summary()
    n1 = conn.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
    r2 = ingest.sync(conn, repo)  # 2회 실행 = 동일
    assert r2.ok
    n2 = conn.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
    assert n1 == n2 == 2


def test_drift_file_modified(repo: Path) -> None:
    conn = _connect(repo)
    ingest.sync(conn, repo)
    target = repo / "forecasts" / "2099" / "2099-06-10_fixture-coin-ath_r1.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n변조", encoding="utf-8")
    report = ingest.sync(conn, repo)
    assert any("E1" in e for e in report.errors)


def test_drift_file_deleted(repo: Path) -> None:
    conn = _connect(repo)
    ingest.sync(conn, repo)
    (repo / "forecasts" / "2099" / "2099-06-10_fixture-coin-ath_r1.md").unlink()
    report = ingest.sync(conn, repo)
    assert any("E2" in e for e in report.errors)


def test_drift_ledger_shrunk(repo: Path) -> None:
    conn = _connect(repo)
    ingest.sync(conn, repo)
    (repo / "calibration" / "ledger.csv").write_text(LEDGER.splitlines()[0] + "\n", encoding="utf-8")
    report = ingest.sync(conn, repo)
    assert any("E3" in e for e in report.errors)


def test_drift_resolution_changed_warns(repo: Path) -> None:
    conn = _connect(repo)
    ingest.sync(conn, repo)
    reg = repo / "questions" / "registry.yaml"
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "YES = 가공 거래소 종가 신고가", "YES = 몰래 바꾼 판정기준"), encoding="utf-8")
    report = ingest.sync(conn, repo)
    assert any("W1" in w and "fixture-coin-ath" in w for w in report.warnings)


# ── due 계산 ─────────────────────────────────────────────────────

def test_due_matrix(repo: Path) -> None:
    conn = _connect(repo)
    ingest.sync(conn, repo)
    questions = load_registry(repo / "questions" / "registry.yaml")
    due = compute_due(
        questions,
        queries.latest_forecasts(conn),
        queries.open_rolling_windows(conn),
        queries.resolved_forecast_ids(conn),
        NOW,
    )
    kinds = {(d.question_id, d.kind) for d in due}
    # coin-ath: 마지막 예측 6/10, 주1회 간격, NOW=6/15 → 5일 < 7일 → due 아님
    assert ("fixture-coin-ath", "forecast") not in kinds
    # rolling: 마지막 예측 3/1 → 재예측 due + 윈도우(5/30) 종료 → resolve due + 스테일
    assert ("fixture-rolling", "forecast") in kinds
    assert ("fixture-rolling", "resolve") in kinds
    assert ("fixture-rolling", "stale") in kinds
    # manual: manual-review
    assert ("fixture-manual", "manual-review") in kinds
    # expired: 기한 경과 → resolve만, 재예측 없음
    assert ("fixture-expired", "resolve") in kinds
    assert ("fixture-expired", "forecast") not in kinds


def test_due_self_heals_after_gap(repo: Path) -> None:
    """놓친 날이 있어도 다음 실행에서 due가 그대로 잡힌다 (순수 함수)."""
    conn = _connect(repo)
    ingest.sync(conn, repo)
    questions = load_registry(repo / "questions" / "registry.yaml")
    later = NOW + timedelta(days=30)
    due = compute_due(questions, queries.latest_forecasts(conn),
                      queries.open_rolling_windows(conn),
                      queries.resolved_forecast_ids(conn), later)
    assert ("fixture-coin-ath", "forecast") in {(d.question_id, d.kind) for d in due}


def test_segment_activation() -> None:
    from ai_fc.models import Question
    q = Question(
        question_id="x", title="", question="", deadline_kind="fixed",
        deadline=date(2099, 7, 1), rolling_days=None, resolution="", resolution_source="",
        domain="fixture", cadence_raw="",
        schedule=[{"per_week": 1}, {"from": "D-14", "per_day": 1}],
        action_link="", status="active", created=None, notes="",
        required_snapshots=[], src_hash="")
    assert active_interval_days(q, date(2099, 6, 1)) == 7.0     # D-30: 기본 세그먼트
    assert active_interval_days(q, date(2099, 6, 25)) == 1.0    # D-6: 일 1회 세그먼트


# ── cadence 제안 ─────────────────────────────────────────────────

@pytest.mark.parametrize("cadence,expected", [
    ("주 1회", [{"per_week": 1}]),
    ("주 1회 + 뉴스 트리거", [{"per_week": 1}]),
    ("D-30부터 주 2회", [{"per_week": 1}, {"from": "D-30", "per_week": 2}]),
    ("주 1회, D-14부터 일 1회", [{"per_week": 1}, {"from": "D-14", "per_day": 1}]),
    ("일 1회 (P0에서는 주 2회로 완화)", [{"per_week": 2}]),
    ("1회성 (일간 인스턴스)", [{"once": True}]),
    ("FQ4 발표(9/29) 후 주 1회", [{"from_date": "2026-09-29", "per_week": 1}]),
    ("도무지 알 수 없는 텍스트", None),
])
def test_propose_schedule(cadence, expected) -> None:
    assert propose_schedule(cadence) == expected


# ── Brier 수기 대조 ──────────────────────────────────────────────

def test_brier_view(repo: Path) -> None:
    conn = _connect(repo)
    ingest.sync(conn, repo)
    row = conn.execute("SELECT * FROM v_gate_status").fetchone()
    assert row["n_resolved"] == 1
    assert abs(row["brier"] - 0.09) < 1e-9  # (0.70-1)^2 = 0.09 수기 계산
    assert not row["gate_p2"] and not row["gate_p3"]
