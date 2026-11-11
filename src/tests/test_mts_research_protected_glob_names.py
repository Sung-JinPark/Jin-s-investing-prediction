"""보호 glob 회피 검사 — 2026-11-11 라이브 정합성 감사 산출물(설계 §3.0 공통 규칙).

보호 패턴(.github/workflows/timeseries*.yml, tools/*timeseries*, tools/*scenario*, tools/*v6*,
src/tests/test_multivariate_timeseries*.py)은 사용자 승인·보호 매니페스트 절차 없이 손대지 않는다.
이 감사가 만든 신규 파일 이름이 그 패턴에 걸리지 않는지, 감사 도구 6종의 verb·모듈에
V14 모듈 문자열이 없는지 고정한다. 저장소 파일 이름만 읽는다(쓰기 0, 네트워크 0).
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from ai_fc.mts_research.cli import RESEARCH_TOOLS
from mts_research_fixtures import ROOT

PROTECTED_GLOBS = (
    ".github/workflows/timeseries*.yml",
    "tools/*timeseries*",
    "tools/*scenario*",
    "tools/*v6*",
    "src/tests/test_multivariate_timeseries*.py",
)

# 감사(2026-11-11)가 새로 만든 소스·테스트·원장·파생·계약 파일
AUDIT_FILES = (
    "src/ai_fc/mts_research/v8_xnas_labels.py",
    "src/ai_fc/mts_research/v8_live_monitor.py",
    "src/ai_fc/mts_research/audits/v13_live_diagnostics.py",
    "src/ai_fc/mts_research/ingest_triage.py",
    "src/ai_fc/mts_research/fed_ebp_sidecar.py",
    "src/ai_fc/mts_research/monitor_thresholds.py",
    "src/tests/test_mts_research_v8_xnas_labels.py",
    "src/tests/test_mts_research_v8_live_monitor.py",
    "src/tests/test_mts_research_coherence_monitor.py",
    "src/tests/test_mts_research_v13_diagnostics.py",
    "src/tests/test_mts_research_ingest_triage.py",
    "src/tests/test_mts_research_fed_ebp_sidecar.py",
    "src/tests/test_mts_research_protected_glob_names.py",
    "data/mts_research/ledgers/v8_xnas_label_diagnostics.jsonl",
    "data/mts_research/ledgers/coherence_daily.jsonl",
    "data/mts_research/ledgers/v8_live_monitor.jsonl",
    "data/mts_research/ledgers/fed_ebp_v1.jsonl",
    "data/mts_research/derived/v8_xnas_label_summary.json",
    "data/mts_research/derived/coherence_monitor_latest.json",
    "data/mts_research/derived/v8_live_monitor.json",
    "data/mts_research/derived/v13_live_diagnostics.json",
    "data/mts_research/contracts/coherence_monitor_thresholds_v1.json",
    "data/mts_research/contracts/daily6m_display_constants_v1.json",
    "data/mts_research/contracts/v8_display_constants_v1.json",
    # U2a (2026-11-11): ingest-triage 관문·정책·보호 워크플로 편집 영수증
    "src/ai_fc/mts_research/triage_gate.py",
    "src/tests/test_mts_research_triage_gate.py",
    "src/tests/test_mts_research_triage_wiring.py",
    "data/mts_research/contracts/ingest_triage_policy_v1.json",
    "data/mts_research/contracts/protected_workflow_edit_receipts_v1.json",
    # U6·U7 (2026-11-11): V8 공식 라벨 basis 핀(U7)·V13 라이브 판정 보고·적용 경로(V13-D14/D15)·점프 라벨(V13-D16)
    "src/ai_fc/mts_research/label_basis.py",
    "data/mts_research/contracts/v8_official_label_basis_v1.json",
    "src/tests/test_mts_research_v8_official_basis.py",
    "src/ai_fc/timeseries_v13/verdict_report.py",
    "src/ai_fc/timeseries_v13/verdict_ledger.py",
    "src/ai_fc/timeseries_v13/verdict_apply.py",
    "src/ai_fc/timeseries_v13/verdict_replay.py",
    "data/timeseries_v13/ledgers/live_verdict_applications.jsonl",
    "src/tests/test_timeseries_v13_verdict_report.py",
    "src/tests/test_timeseries_v13_verdict_apply.py",
    "src/tests/test_timeseries_v13_jump_caveat.py",
    # U2b (2026-11-11): v2-refresh market 보고 분류 — 보호 워크플로 밖의 비라이터
    ".github/workflows/mts-ingest-triage.yml",
)

AUDIT_GLOBS = (
    "src/tests/fixtures/mts_ingest_triage/*",
    "docs/research/mts_upgrade/*_20261111.md",
)


def _protected(relative: str) -> list[str]:
    return [pattern for pattern in PROTECTED_GLOBS if fnmatchcase(relative, pattern)]


def _audit_paths() -> list[str]:
    paths = set(AUDIT_FILES)
    for pattern in AUDIT_GLOBS:
        paths.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern) if path.is_file())
    return sorted(paths)


def test_matcher_recognises_protected_names() -> None:
    """검사기 자체가 보호 이름을 잡는지 — 빈 패턴으로 초록이 되는 가짜 통과 방지."""
    assert _protected(".github/workflows/timeseries-v8.yml")
    assert _protected("tools/ralph_timeseries.py")
    assert _protected("tools/scenario_check.py")
    assert _protected("tools/audit_v6_gate.py")
    assert _protected("src/tests/test_multivariate_timeseries_v8.py")
    assert not _protected("src/tests/test_timeseries_v8_display.py")


def test_audit_file_names_avoid_protected_globs() -> None:
    paths = _audit_paths()
    assert len(paths) >= len(AUDIT_FILES)
    hits = {path: _protected(path) for path in paths if _protected(path)}
    assert hits == {}


def test_research_tool_verbs_and_modules_carry_no_v14_string() -> None:
    forbidden = "timeseries" + "_v14"  # 이 파일 자체가 검사 대상이라 리터럴을 쪼갠다
    for verb, (module, function) in RESEARCH_TOOLS.items():
        assert forbidden not in verb and forbidden not in module and forbidden not in function
    # 테스트 파일은 자기 부정 assert 에 리터럴을 쓰므로 소스 모듈만 본다.
    for relative in AUDIT_FILES:
        if relative.startswith("src/ai_fc/") and relative.endswith(".py"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            assert forbidden not in text, relative
