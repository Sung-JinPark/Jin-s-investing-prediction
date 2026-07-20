"""Sprint 2 — orchestrator 파이프라인 테스트 (LLM 모킹, 합성 픽스처만)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import ai_fc.orchestrator as orch
from ai_fc import files as F
from ai_fc.db import ingest
from ai_fc.models import EvidenceBrief
from ai_fc.aggregator import AggregateResult
from ai_fc.schemas import Adjustment, ForecastResult, SnapshotItem

REGISTRY = textwrap.dedent("""\
    version: 1
    updated: 2099-06-01
    questions:
      - id: fixture-coin-ath
        title: "픽스처코인 ATH"
        question: "픽스처코인이 2099-12-31까지 ATH를 경신할 확률은?"
        deadline: 2099-12-31
        resolution: "YES = 가공 거래소 신고가"
        resolution_source: "가공 거래소"
        domain: fixture
        cadence: "주 1회"
        schedule: [{per_week: 1}]
        action_link: "테스트"
        status: active
        created: 2099-06-01
        required_snapshots: ["기준가"]
        # WS1 등록필터 (v2): 컷오프 이후 created 질문은 근거 마커 필수 — 픽스처도 준수
        notes: "등록필터: (a) 픽스처 base rate 극단 — 테스트용"

      - id: fixture-tbd
        title: "기한 미정"
        question: "미정 질문?"
        deadline: null
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule: [{per_week: 1}]
        action_link: "테스트"
        status: active
        created: 2099-06-01
""")


def _fake_result(snapshot_value: str = "$123.45") -> ForecastResult:
    return ForecastResult(
        question_check="해소가능 — 진행",
        reference_class="가공 참조 클래스",
        base_rates=["가공 base rate 1", "가공 2", "가공 3"],
        anchor_pct=30,
        adjustments=[Adjustment(evidence="가공 증거", direction="up", delta_pp=5.0)],
        decomposition="가공 분해",
        premortem=["원인1", "원인2", "원인3"],
        probability=35, ci80_lo=20, ci80_hi=50,
        key_reasons=["근거1", "근거2", "근거3"],
        observables=["지표1", "지표2"],
        snapshots_filled=[SnapshotItem(name="기준가", value=snapshot_value)],
        unverified_notes=[],
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(REGISTRY, encoding="utf-8")
    (tmp_path / "forecasts" / "2099").mkdir(parents=True)
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n",
        encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "reasoning_core_v1.md").write_text("절차", encoding="utf-8")

    monkeypatch.setattr(orch, "run_research", lambda *a, **k: [
        EvidenceBrief("general", "가공 종합 보고", 5, 0.30, 1000, 200),
        EvidenceBrief("devil", "가공 반대 보고", 3, 0.25, 800, 150),
    ])
    monkeypatch.setattr(orch.anthropic, "Anthropic", lambda **kw: object())
    monkeypatch.setattr(orch.config, "get_api_key", lambda: "sk-test-fixture")
    return tmp_path


def _patch_estimate(monkeypatch, result: ForecastResult) -> None:
    monkeypatch.setattr(orch.SingleRun, "estimate", lambda self, *a, **k: AggregateResult(
        probability=result.probability, ci80_lo=result.ci80_lo, ci80_hi=result.ci80_hi,
        result=result, runs=[result.probability]))


def test_forecast_writes_immutable_record(repo: Path, monkeypatch) -> None:
    _patch_estimate(monkeypatch, _fake_result())
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)

    msg = orch.run_forecast(conn, repo, "fixture-coin-ath", dry_run=False)
    assert "35%" in msg

    files = list(F.iter_forecast_files(repo / "forecasts"))
    assert len(files) == 1
    rec = F.parse_forecast_file(files[0])
    assert rec.probability == 35 and rec.round == 1
    assert rec.snapshots.get("기준가") == "$123.45"
    # 증거 부록 존재
    assert files[0].with_name(files[0].stem + "_evidence.md").exists()
    # DB 동기화됨
    n = conn.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
    assert n == 1
    # 재실행 → r2 (배타적 생성, round 증가)
    msg2 = orch.run_forecast(conn, repo, "fixture-coin-ath", dry_run=False)
    assert "r2" in msg2


def test_dry_run_touches_nothing(repo: Path, monkeypatch) -> None:
    _patch_estimate(monkeypatch, _fake_result())
    conn = ingest.connect(repo / "db" / "index.db")
    msg = orch.run_forecast(conn, repo, "fixture-coin-ath", dry_run=True)
    assert "[DRY]" in msg
    assert list(F.iter_forecast_files(repo / "forecasts")) == []
    assert any((repo / "db" / "scratch").glob("*_r1.md"))  # 스크래치에만


def test_missing_snapshot_aborts_without_write(repo: Path, monkeypatch) -> None:
    _patch_estimate(monkeypatch, _fake_result(snapshot_value="NOT FOUND"))
    conn = ingest.connect(repo / "db" / "index.db")
    with pytest.raises(orch.PreflightError, match="스냅샷"):
        orch.run_forecast(conn, repo, "fixture-coin-ath")
    assert list(F.iter_forecast_files(repo / "forecasts")) == []


def test_tbd_deadline_aborts(repo: Path, monkeypatch) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    with pytest.raises(orch.PreflightError, match="deadline"):
        orch.run_forecast(conn, repo, "fixture-tbd")


def test_lockfile_blocks_double_run(repo: Path, monkeypatch) -> None:
    _patch_estimate(monkeypatch, _fake_result())
    conn = ingest.connect(repo / "db" / "index.db")
    lock = repo / "db" / ".ai_fc.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("")
    with pytest.raises(orch.PreflightError, match="락파일"):
        orch.run_forecast(conn, repo, "fixture-coin-ath")
    lock.unlink()
