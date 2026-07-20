"""v3 WS-B lite 티어 + WS-E retro 제외: 데블스 강제 유지·검색 상한 전달·티어 기록."""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import ai_fc.agents.base as agents_base
from ai_fc.agents.profiles import PROFILES, get_profile
from ai_fc.db import ingest
from ai_fc.files import iter_forecast_files, parse_forecast_file, validate_new_record
from ai_fc.llm import PipelineBudget, Usage
from ai_fc.registry import load_registry

REG = """\
    version: 1
    questions:
      - id: fx-lite
        title: "lite 픽스처"
        question: "lite?"
        deadline: 2099-08-04
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: earnings
        cadence: "r1 + D-3"
        status: active
        created: 2026-07-01
        tier: lite
        schedule: [{once: true}]
      - id: fx-std
        title: "standard 픽스처"
        question: "std?"
        deadline: 2099-08-04
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: macro
        cadence: "r1"
        status: active
        created: 2026-07-01
        schedule: [{once: true}]
      - id: fx-typo
        title: "오타 티어"
        question: "typo?"
        deadline: 2099-08-04
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: macro
        cadence: "r1"
        status: active
        created: 2026-07-01
        tier: ultra
        schedule: [{once: true}]
"""


def _questions(tmp_path: Path):
    p = tmp_path / "registry.yaml"
    p.write_text(textwrap.dedent(REG), encoding="utf-8")
    return {q.question_id: q for q in load_registry(p)}


def test_tier_parsing_lenient(tmp_path: Path) -> None:
    qs = _questions(tmp_path)
    assert qs["fx-lite"].tier == "lite"
    assert qs["fx-std"].tier == "standard"       # 미지정 기본
    assert qs["fx-typo"].tier == "standard"      # 오타 → standard (관대한 리더)


def test_get_profile_words_substitution() -> None:
    std = get_profile("devil", 900)
    lite = get_profile("devil", 450)
    assert "900단어 이내" in std and "450단어 이내" in lite
    # 임무 텍스트 불변 — 분량 지시만 다름
    assert std.replace("900단어", "450단어") == lite
    assert "데블스 애드버킷" in lite               # 데블스 임무 유지
    assert get_profile("general", 900) == PROFILES["general"]


def test_run_research_lite_wiring(tmp_path: Path, monkeypatch) -> None:
    """lite: 검색 상한 4·450단어 전달, 프로필 구성(데블스 포함)은 티어 무관 동일."""
    qs = _questions(tmp_path)
    calls: list[tuple[str, object]] = []

    def fake_research_call(client, system, user, budget, max_search_uses=None):
        calls.append((system, max_search_uses))
        return "가공 보고", 3, Usage(10, 10, 0.01)

    monkeypatch.setattr(agents_base, "research_call", fake_research_call)
    budget = PipelineBudget(limit_usd=10)

    briefs = agents_base.run_research(None, qs["fx-lite"], 2, budget, date(2099, 7, 1))
    assert [b.profile for b in briefs] == ["general", "devil"]   # 데블스 강제 유지
    assert all(mu == 4 for _, mu in calls)                        # lite 검색 상한
    assert all("450단어 이내" in s for s, _ in calls)

    calls.clear()
    briefs = agents_base.run_research(None, qs["fx-std"], 2, budget, date(2099, 7, 1))
    assert [b.profile for b in briefs] == ["general", "devil"]
    assert all(mu is None for _, mu in calls)                     # 전역 기본(8) 사용
    assert all("900단어 이내" in s for s, _ in calls)


def test_pipeline_tier_recorded_and_parsed(tmp_path: Path) -> None:
    fm = {"forecast_id": "2099-08-01_fx-lite_r1", "question_id": "fx-lite",
          "timestamp": "2099-08-01 09:00 KST", "phase": "P1", "model": "m",
          "prompt_version": "v1", "probability": 70, "ci80": [60, 80],
          "pipeline_tier": "lite"}
    assert validate_new_record(fm) == []
    d = tmp_path / "forecasts" / "2099"
    d.mkdir(parents=True)
    p = d / "2099-08-01_fx-lite_r1.md"
    p.write_text("---\n" + "\n".join(
        f"{k}: {v}" for k, v in fm.items()) + "\n---\n본문", encoding="utf-8")
    rec = parse_forecast_file(p)
    assert rec.pipeline_tier == "lite"


def test_retro_excluded_from_sync(tmp_path: Path) -> None:
    """WS-E(D1): retro/는 가변 노트 — iter 제외, sync 무오류."""
    fdir = tmp_path / "forecasts" / "2026"
    (fdir / "retro").mkdir(parents=True)
    (fdir / "retro" / "2026-07-30_fomc_retro.md").write_text("# 회고", encoding="utf-8")
    (fdir / "retro" / "TEMPLATE.md").write_text("# 템플릿", encoding="utf-8")
    assert list(iter_forecast_files(tmp_path / "forecasts")) == []

    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(
        "version: 1\nquestions: []\n", encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n",
        encoding="utf-8")
    conn = ingest.connect(tmp_path / "db" / "index.db")
    report = ingest.sync(conn, tmp_path)
    assert report.ok and not report.warnings     # E6(고아 evidence)도 아님 — retro는 비대상
