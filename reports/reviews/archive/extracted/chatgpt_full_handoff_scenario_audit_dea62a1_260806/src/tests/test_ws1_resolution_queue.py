"""WS-1 채점 회전율: macro/earnings 이중 출처 초안 + 경과일 큐."""

from __future__ import annotations

import json
import textwrap
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ai_fc.db import ingest
from ai_fc.registry import compute_due, load_registry
from ai_fc.resolver import (ResolutionObservation, SourceObservation,
                            _numeric_rule, draft_verdicts,
                            load_resolution_observations,
                            numeric_machine_check)


def _questions(tmp_path: Path, body: str):
    path = tmp_path / "questions" / "registry.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: 1\nquestions:\n" + textwrap.indent(textwrap.dedent(body), "  "),
        encoding="utf-8")
    return load_registry(path)


def _pair(qid: str, actual: str, *, reference: str | None = None,
          secondary_actual: str | None = None,
          secondary_reference: str | None = None) -> ResolutionObservation:
    return ResolutionObservation(
        question_id=qid,
        primary=SourceObservation(
            Decimal(actual), "https://official.example/release",
            Decimal(reference) if reference is not None else None,
            "2099-06-11", "jobs"),
        secondary=SourceObservation(
            Decimal(secondary_actual or actual), "https://secondary.example/check",
            Decimal(secondary_reference or reference)
            if (secondary_reference or reference) is not None else None,
            "2099-06-11", "jobs"),
    )


def test_macro_nfp_draft_requires_matching_two_sources(tmp_path: Path) -> None:
    q = _questions(tmp_path, """\
    - id: fixture-nfp
      title: NFP 최초치
      question: NFP가 10만 미만일 확률은?
      deadline: 2099-06-10
      resolution: YES = 최초 공표 기준 NFP < +100,000
      resolution_source: BLS 공식 보도자료
      domain: macro
      cadence: 1회
      status: active
      created: 2099-01-01
    """)[0]

    matched = numeric_machine_check(
        q, _pair(q.question_id, "90000"), today=date(2099, 6, 11))
    assert matched.outcome == "yes"
    assert matched.confidence == "high"
    assert matched.comparison_status == "matched"
    assert matched.secondary_check_needed is False
    assert "100000" in matched.evidence_value

    held = numeric_machine_check(
        q, _pair(q.question_id, "90000", secondary_actual="91000"),
        today=date(2099, 6, 11))
    assert held.outcome is None
    assert held.comparison_status == "held"
    assert "actual 불일치" in held.comparison_log
    assert held.secondary_check_needed is True

    same_provider = ResolutionObservation(
        q.question_id,
        SourceObservation(
            Decimal("90000"), "https://official.example/release",
            observed_at="2099-06-11", unit="jobs"),
        SourceObservation(
            Decimal("90000"), "https://www.official.example/table",
            observed_at="2099-06-11", unit="jobs"),
    )
    held = numeric_machine_check(q, same_provider, today=date(2099, 6, 11))
    assert held.comparison_status == "held"
    assert "source가 동일" in held.comparison_log


def test_earnings_multiplier_comes_from_registry_not_evidence(tmp_path: Path) -> None:
    q = _questions(tmp_path, """\
    - id: fixture-eps
      title: EPS 컨센서스 상회
      question: EPS가 컨센서스를 5% 이상 상회할 확률은?
      deadline: 2099-06-10
      resolution: YES = 발표 EPS >= D-1 컨센 x 1.05
      resolution_source: 회사 IR + D-1 컨센서스 스냅샷
      domain: earnings
      cadence: 1회
      status: active
      created: 2099-01-01
    """)[0]

    verdict = numeric_machine_check(
        q, _pair(q.question_id, "2.10", reference="2.00"),
        today=date(2099, 6, 11))
    assert verdict.outcome == "yes"  # 2.00 × 1.05와 정확히 같으므로 >= YES
    assert "× 1.05 = 2.1" in verdict.evidence_value
    assert verdict.comparison_status == "matched"


def test_numeric_draft_is_explicit_when_data_or_rule_is_missing(tmp_path: Path) -> None:
    questions = _questions(tmp_path, """\
    - id: fixture-cpi
      title: CPI 가속
      question: CPI가 가속할 확률은?
      deadline: 2099-06-10
      resolution: YES = CPI-U YoY가 4.3% 이상
      resolution_source: BLS
      domain: macro
      cadence: 1회
      status: active
      created: 2099-01-01
    - id: fixture-narrative
      title: 경기 국면 전환
      question: 경기 국면이 전환할 확률은?
      deadline: 2099-06-10
      resolution: YES = 종합적으로 경기 국면이 전환했다고 판단
      resolution_source: 사람 위원회
      domain: macro
      cadence: 1회
      status: active
      created: 2099-01-01
    """)
    pending = numeric_machine_check(questions[0], None, today=date(2099, 6, 11))
    assert pending.outcome is None and pending.comparison_status == "pending"
    assert "--resolution-data" in pending.note

    unsupported = numeric_machine_check(
        questions[1], _pair(questions[1].question_id, "1"),
        today=date(2099, 6, 11))
    assert unsupported.outcome is None
    assert unsupported.comparison_status == "unsupported"
    assert "판정불가 유형" in unsupported.note


def test_resolution_json_loader_and_draft_write_nothing(tmp_path: Path) -> None:
    questions = _questions(tmp_path, """\
    - id: fixture-fomc
      title: FOMC 25bp 인상
      question: 목표범위를 인상할 확률은?
      deadline: 2099-06-10
      resolution: YES = 목표범위 상단이 직전 대비 +25bp 이상
      resolution_source: Federal Reserve 성명서
      domain: macro
      cadence: 1회
      status: active
      created: 2099-01-01
    """)
    data = {
        "observations": [{
            "question_id": questions[0].question_id,
            "primary": {
                "actual": 0, "unit": "bp", "observed_at": "2099-06-10",
                "source": "https://federalreserve.example/statement",
            },
            "secondary": {
                "actual": 0, "unit": "bp", "observed_at": "2099-06-10",
                "source": "https://secondary.example/fomc",
            },
        }],
    }
    data_path = tmp_path / "resolution.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")
    observations = load_resolution_observations(data_path)
    conn = ingest.connect(tmp_path / "db" / "index.db")

    verdicts = draft_verdicts(
        conn, tmp_path, today=date(2099, 6, 11),
        observations=observations)
    assert len(verdicts) == 1
    assert verdicts[0].outcome == "no"
    assert verdicts[0].comparison_status == "matched"
    assert not (tmp_path / "calibration" / "ledger.csv").exists()
    assert not (tmp_path / "calibration" / "benchmark_ledger.csv").exists()


def test_resolve_queue_is_sorted_by_overdue_days(tmp_path: Path) -> None:
    questions = _questions(tmp_path, """\
    - id: recent
      title: 최근 만료
      question: 최근 만료?
      deadline: 2099-06-09
      resolution: YES = 조건 충족
      resolution_source: fixture
      domain: macro
      cadence: 1회
      status: active
      created: 2099-01-01
    - id: oldest
      title: 오래된 만료
      question: 오래된 만료?
      deadline: 2099-05-01
      resolution: YES = 조건 충족
      resolution_source: fixture
      domain: macro
      cadence: 1회
      status: active
      created: 2099-01-01
    """)
    due = compute_due(
        questions, {}, {}, set(), datetime(2099, 6, 10, 9, 0))
    resolves = [item for item in due if item.kind == "resolve"]
    assert [item.question_id for item in resolves] == ["oldest", "recent"]
    assert [item.overdue_days for item in resolves] == [40, 1]


def test_real_registry_deterministic_rules_do_not_read_no_examples() -> None:
    """실제 판정 문언 전수 가드: Unicode 비교·중간 설명·상대 기준을 안전 해석."""
    repo = Path(__file__).resolve().parents[2]
    questions = {
        q.question_id: q
        for q in load_registry(repo / "questions" / "registry.yaml")
    }
    expected = {
        "amd-eps-beat-2026q2": ("gt", Decimal("1")),
        "cpi-jul2026-reaccel": ("ge", Decimal("3.8")),
        "cpi-oct2026-reaccel": ("gt", Decimal("1")),
        "gdp-q3adv-2026-beat": ("gt", Decimal("1")),
    }
    for qid, (operator, target) in expected.items():
        rule = _numeric_rule(questions[qid])
        assert rule is not None, qid
        assert rule.operator == operator
        assert (rule.threshold if rule.threshold is not None
                else rule.reference_multiplier) == target
