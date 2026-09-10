"""C5 질문 프리플라이트·예산 실측 대사 테스트 (2026-09-09 신설).

배경: Q3 신규 20문항 중 **6건(30%)이 결함**이었다 — 판정 문언이 출처의 리터럴 문자열에
의존(2건), 결정 발표일이 아닌 회합 첫날을 지목(1건), **결과가 이미 확정된 과거 사건**(3건).
셋째 유형은 CLAUDE.md 5원칙 5(라이브 포워드 only) 정면 위반이라 예측했다면 원장이
오염됐을 것이다. 이 테스트들은 그 재발을 코드로 막는다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ai_fc import c5_certificate as C5

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _registry(tmp_path: Path, body: str) -> Path:
    _write(tmp_path / "questions/registry.yaml", "version: 1\nquestions:\n" + body)
    return tmp_path


# ── 결함 유형 ①: 기간형인데 시작일 없음 (과거 사건 유입 경로) ──────

def test_window_question_without_start_date_is_flagged(tmp_path: Path) -> None:
    """ai-ipo-2b-plus 가 등록 시점에 이미 YES 였던 바로 그 결함."""
    repo = _registry(tmp_path, """
  - id: no-start
    status: active
    deadline: '2026-11-30'
    question: 2026-11-30까지 조달액 20억 달러 이상 IPO 가 1회 이상 발생할 확률은?
    resolution: YES = 기간 중 조달액 >= $2.0B 인 건이 1건 이상.
""")
    flags = C5.question_preflight(repo)
    assert [f["id"] for f in flags] == ["no-start"]
    assert "시작일" in flags[0]["flags"][0]


def test_window_question_with_start_date_passes(tmp_path: Path) -> None:
    repo = _registry(tmp_path, """
  - id: has-start
    status: active
    deadline: '2026-11-30'
    question: 2026-09-10부터 2026-11-30까지 VIX 종가가 하루라도 30 이상일 확률은?
    resolution: YES = 해당 기간 중 어느 거래일이든 VIX 종가 >= 30.0.
""")
    assert C5.question_preflight(repo) == []


def test_start_date_in_question_only_still_passes(tmp_path: Path) -> None:
    """시작일이 question 에만 있고 resolution 이 '해당 기간 중'으로 되받는 형태는 정상."""
    repo = _registry(tmp_path, """
  - id: split-window
    status: active
    deadline: '2026-12-18'
    question: 2026-09-14 주부터 2026-12-18까지 주간 급등이 1회 이상 발생할 확률은?
    resolution: YES = 어느 주든 종가 상승률 >= 50%.
""")
    assert C5.question_preflight(repo) == []


# ── 결함 유형 ②: 판정이 출처의 리터럴 문자열에 의존 ────────────────

def test_literal_string_dependency_is_flagged(tmp_path: Path) -> None:
    """Warsh 체제에서 성명 문구가 바뀌어 'Voting against this action' 이 사라진 사건."""
    repo = _registry(tmp_path, """
  - id: literal-dep
    status: active
    deadline: '2026-09-16'
    question: 반대표가 있을 확률은?
    resolution: YES = 성명의 'Voting against this action' 항목에 1명 이상 기재.
""")
    flags = C5.question_preflight(repo)
    assert [f["id"] for f in flags] == ["literal-dep"]
    assert "리터럴" in flags[0]["flags"][0]


def test_literal_quoted_but_explicitly_neutralized_is_not_flagged(tmp_path: Path) -> None:
    """리터럴을 인용하되 '문구 형태와 무관하게' 판정한다고 명시하면 오탐이 아니다."""
    repo = _registry(tmp_path, """
  - id: neutralized
    status: active
    deadline: '2026-09-16'
    question: 반대표가 있을 확률은?
    resolution: >-
      YES = 표결 집계의 반대 측 수가 1 이상. 문구 형태와 무관하게 집계 기준으로 판정한다
      ('Voting against this action' / 'Voting against the monetary policy action' 모두 동일 취급).
""")
    assert C5.question_preflight(repo) == []


# ── 결함 유형 ③: 과거 사건 — 정적 탐지 불가이므로 근거 기재를 강제 ──

def test_new_question_requires_preflight_block(tmp_path: Path) -> None:
    """2026-09-10 이후 등록 질문은 preflight 근거 없이는 통과할 수 없다."""
    repo = _registry(tmp_path, """
  - id: newq
    status: active
    created: 2026-09-11
    deadline: '2027-01-31'
    question: 어떤 사건이 일어날 확률은?
    resolution: YES = 사건 발생.
""")
    flags = C5.question_preflight(repo)
    assert any("preflight 블록 부재" in f for f in flags[0]["flags"])


def test_partial_preflight_block_reports_missing_keys(tmp_path: Path) -> None:
    repo = _registry(tmp_path, """
  - id: partial
    status: active
    created: 2026-09-11
    deadline: '2027-01-31'
    question: 어떤 사건이 일어날 확률은?
    resolution: YES = 사건 발생.
    preflight:
      not_yet_occurred: EDGAR 조회 2026-09-09 — 미발생 확인
""")
    flags = C5.question_preflight(repo)
    msg = next(f for f in flags[0]["flags"] if "누락" in f)
    assert "window_start" in msg and "resolution_wording_checked" in msg


def test_complete_preflight_block_passes(tmp_path: Path) -> None:
    repo = _registry(tmp_path, """
  - id: complete
    status: active
    created: 2026-09-11
    deadline: '2027-01-31'
    question: 2026-09-10부터 2027-01-31까지 사건이 일어날 확률은?
    resolution: YES = 2026-09-10 이후 사건 발생.
    preflight:
      not_yet_occurred: FRED 직접 조회 2026-09-09 — 미도달 확인
      window_start: '2026-09-10'
      resolution_wording_checked: 계열 ID·단위 확인 2026-09-09
""")
    assert C5.question_preflight(repo) == []


def test_old_questions_are_grandfathered(tmp_path: Path) -> None:
    """컷오프 이전 질문에는 preflight 를 소급 요구하지 않는다 (불변 기록 존중)."""
    repo = _registry(tmp_path, """
  - id: oldq
    status: active
    created: 2026-07-20
    deadline: '2027-01-31'
    question: 2026-09-10부터 사건이 일어날 확률은?
    resolution: YES = 사건 발생 (2026-09-10 이후).
""")
    assert C5.question_preflight(repo) == []


def test_void_questions_are_not_flagged(tmp_path: Path) -> None:
    """폐기된 질문은 점검 대상이 아니다 — 이미 처리된 결함을 계속 울리면 알림이 죽는다."""
    repo = _registry(tmp_path, """
  - id: voided
    status: void
    created: 2026-09-11
    deadline: '2026-11-30'
    question: 2026-11-30까지 사건이 일어날 확률은?
    resolution: YES = 발생.
""")
    assert C5.question_preflight(repo) == []


def test_preflight_cutoff_is_the_documented_date() -> None:
    assert C5.PREFLIGHT_CUTOFF == date(2026, 9, 10)
    assert set(C5.PREFLIGHT_KEYS) == {
        "not_yet_occurred", "window_start", "resolution_wording_checked"}


# ── 예산 실측 대사 ─────────────────────────────────────────────────

def _budget_repo(tmp_path: Path) -> Path:
    _write(tmp_path / "questions/registry.yaml", """version: 1
questions:
  - id: q-scored
    status: active
    notes: '[C5 Q3 · 분류 macro_threshold · 예상확률 20% (첫 예측 전 고정)]'
  - id: q-pending
    status: active
    notes: '[C5 Q3 · 분류 macro_threshold · 예상확률 30% (첫 예측 전 고정)]'
  - id: q-void
    status: void
    notes: '[C5 Q3 · 분류 corporate_event · 예상확률 25% (첫 예측 전 고정)]'
  - id: q-research
    status: active
    notes: '[C5 Q3 대체 · 예상확률 80% (리서치 이후 산정 — 사전추정 정확도 표본 제외)]'
""")
    for qid, rnd, prob in (("q-scored", 1, 65), ("q-scored", 2, 70), ("q-research", 1, 78)):
        _write(tmp_path / f"forecasts/2026/2026-01-01_{qid}_r{rnd}.md",
               f"---\nquestion_id: {qid}\nprobability: {prob}\n---\n")
    return tmp_path


def test_budget_uses_first_round_not_latest(tmp_path: Path) -> None:
    """예산 대사는 **첫 예측** 확률을 쓴다 — 재예측으로 사후 조정되면 대사가 무의미해진다."""
    b = C5.budget_reconciliation(_budget_repo(tmp_path))
    row = next(r for r in b["rows"] if r["id"] == "q-scored")
    assert row["actual"] == pytest.approx(0.65)      # r2(0.70)가 아니라 r1


def test_budget_excludes_void_and_blends_pending(tmp_path: Path) -> None:
    b = C5.budget_reconciliation(_budget_repo(tmp_path))
    assert b["n_live"] == 3 and b["n_scored"] == 2 and b["n_pending"] == 1
    # 채점분은 실측, 미채점분은 예상으로 혼합
    expected = (0.65 * 0.35 + 0.78 * 0.22 + 0.30 * 0.70) / 3
    assert b["mean_blended_pq"] == pytest.approx(expected)


def test_budget_excludes_research_informed_from_error_sample(tmp_path: Path) -> None:
    """리서치 이후 산정된 대체 질문은 '사전 추정 정확도' 표본이 아니다."""
    b = C5.budget_reconciliation(_budget_repo(tmp_path))
    assert len(b["estimate_errors_pp"]) == 1                  # q-research 제외
    assert b["mean_abs_error_pp"] == pytest.approx(45.0)      # |65 - 20|


def test_budget_reports_actual_cap_breach(tmp_path: Path) -> None:
    """상한 초과는 등록 시점이 아니라 첫 예측 뒤에 확정된다."""
    b = C5.budget_reconciliation(_budget_repo(tmp_path))
    assert b["over_cap"] == ["q-scored"]                      # 0.65 -> p(1-p)=0.2275 > 0.21


def test_budget_handles_empty_registry(tmp_path: Path) -> None:
    _write(tmp_path / "questions/registry.yaml", "version: 1\nquestions: []\n")
    b = C5.budget_reconciliation(tmp_path)
    assert b["n_live"] == 0 and b["mean_blended_pq"] is None


# ── 실제 저장소 회귀 ───────────────────────────────────────────────

def test_repo_q3_questions_have_no_preflight_flags() -> None:
    """실제 레지스트리에서 C5 Q3 질문은 전부 프리플라이트를 통과해야 한다."""
    import yaml
    reg = yaml.safe_load((ROOT / "questions/registry.yaml").read_text(encoding="utf-8"))
    q3 = {q["id"] for q in reg["questions"]
          if "C5 Q3" in str(q.get("notes") or "") and q.get("status") == "active"}
    flagged = {f["id"] for f in C5.question_preflight(ROOT)}
    assert not (q3 & flagged), f"Q3 질문에 프리플라이트 플래그: {sorted(q3 & flagged)}"


# ── 가드가 조용히 꺼져 있던 문제 (T05, 2026-09-11) ──────────────────

def test_quoted_created_string_still_triggers_the_cutoff(tmp_path: Path) -> None:
    """`created: '2026-09-11'` 처럼 따옴표가 있으면 YAML 이 str 로 준다.

    실측 계기: 79문항 중 36건이 문자열 created 였고, `isinstance(created, date)` 로만 보던
    구현이 그 전부를 None 으로 떨어뜨려 **preflight 필수 규칙이 조용히 꺼져 있었다.**
    가드가 꺼진 줄 모르고 통과하는 것이 가드가 없는 것보다 나쁘다.
    """
    repo = _registry(tmp_path, """
  - id: quoted-created
    status: active
    created: '2026-09-11'
    deadline: '2027-01-31'
    question: 어떤 사건이 일어날 확률은?
    resolution: YES = 사건 발생.
""")
    flags = C5.question_preflight(repo)
    assert flags and any("preflight 블록 부재" in f for f in flags[0]["flags"])


def test_quoted_created_string_still_triggers_the_factory_filter(tmp_path: Path) -> None:
    """등록필터도 같은 경로로 꺼져 있었다."""
    from ai_fc.registry import factory_filter_violation, load_registry

    _write(tmp_path / "questions/registry.yaml", """version: 1
questions:
  - id: quoted-no-marker
    status: active
    created: '2026-09-11'
    deadline: '2027-01-31'
    question: 확률은?
    resolution: YES = 발생.
""")
    q = load_registry(tmp_path / "questions/registry.yaml")[0]
    assert q.created == date(2026, 9, 11), "문자열 created 가 date 로 정규화돼야 한다"
    assert factory_filter_violation(q), "등록필터가 근거 없는 신규 등록을 잡아야 한다"


def test_as_date_normalizes_the_forms_the_registry_actually_contains() -> None:
    from datetime import datetime

    from ai_fc.c5_certificate import as_date
    assert as_date(date(2026, 9, 11)) == date(2026, 9, 11)
    assert as_date("2026-09-11") == date(2026, 9, 11)
    assert as_date(datetime(2026, 9, 11, 12, 0)) == date(2026, 9, 11)
    assert as_date(None) is None
    assert as_date("미정") is None
