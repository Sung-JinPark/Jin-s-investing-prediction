"""T06 — 정지 규칙·부정결과 선언·금지 행위 감지를 고정한다.

부정 선언은 늦게 정할수록 안 하게 된다. 20에서는 '표본이 얇다', 30에서는 '이번 분기가
특이했다', 49에서는 '한 건만 더'. 그래서 문턱과 조건을 결과 보기 전에 코드로 박고,
사람이 다시 해석할 여지를 남기지 않는다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── 계약에서 읽는가 ──────────────────────────────────────────────────

def test_stopping_parameters_come_from_the_contract() -> None:
    from ai_fc.gate_review import stopping_parameters
    p = stopping_parameters(ROOT)
    assert p["review_at"] == (20, 30)
    assert p["negative_at"] == 30
    assert p["negative_ci_lower_above"] == pytest.approx(0.20)
    assert set(p["never"]) == {"stop_at_49_and_cherry_pick", "post_hoc_failed_tagging",
                               "gate_arithmetic_change"}
    assert p["status_wording"].startswith("미결")


def test_missing_contract_falls_back_closed(tmp_path: Path) -> None:
    """계약을 못 읽으면 기본값은 **통과 쪽으로 기울지 않는다**."""
    from ai_fc.gate_review import (FALLBACK_NEGATIVE_AT, FALLBACK_NEGATIVE_CI_LOWER,
                                   FALLBACK_REVIEW_AT, stopping_parameters)
    p = stopping_parameters(tmp_path)
    assert p["review_at"] == FALLBACK_REVIEW_AT
    assert p["negative_at"] == FALLBACK_NEGATIVE_AT
    assert p["negative_ci_lower_above"] == FALLBACK_NEGATIVE_CI_LOWER


# ── 판정 ─────────────────────────────────────────────────────────────

def test_current_sample_is_below_every_milestone() -> None:
    from ai_fc.gate_review import verdict
    v = verdict(ROOT)
    if v.n_questions >= 20:
        pytest.skip(f"표본이 중간검토 문턱에 도달했다 ({v.n_questions}문항)")
    assert not v.review_due and not v.negative_declared
    assert "다음 중간검토 문턱 20" in v.reason


def test_negative_declaration_needs_both_conditions() -> None:
    """문항 수 **또는** CI 하한 하나만으로는 발동하지 않는다."""
    from ai_fc.gate_review import interim_review
    review = interim_review(ROOT)
    n_q, lower = review["n_questions_primary"], review["ci90_lower"]
    at, above = review["negative_at"], review["negative_ci_lower_above"]
    assert review["negative_declared"] == (n_q >= at and lower is not None and lower > above)


def test_review_never_says_the_forbidden_word() -> None:
    from ai_fc.gate_review import interim_review, render_markdown
    text = render_markdown(interim_review(ROOT), today="2026-09-11")
    assert "통과가 아니다" in text, "미충족을 통과로 읽히게 두면 안 된다"
    # '통과' 는 '통과가 아니다' 문맥에서만 등장해야 한다.
    assert text.count("통과") == text.count("통과가 아니다")
    assert "미결" in text


def test_report_badge_never_renders_the_word_pass() -> None:
    source = (ROOT / "src/ai_fc/report.py").read_text(encoding="utf-8")
    assert '{"통과" if gate["gate_p3"]' not in source
    assert '{"통과" if gate["gate_p2"]' not in source
    assert "산술 충족 · 통계적 <b>미결</b>" in source


def test_markdown_carries_the_reserved_loss_and_the_never_list() -> None:
    from ai_fc.gate_review import interim_review, render_markdown
    text = render_markdown(interim_review(ROOT), today="2026-09-11")
    assert "예약 손실 시나리오" in text and "0.20582" in text
    for item in ("stop_at_49_and_cherry_pick", "post_hoc_failed_tagging",
                 "gate_arithmetic_change"):
        assert item in text


def test_module_writes_no_state_file() -> None:
    """낡은 상태 파일은 잘못된 다음 행동을 부른다 — 리포트는 stdout 으로만 낸다."""
    for name in ("src/ai_fc/gate_review.py", "src/ai_fc/gate_guard.py", "tools/gate_review.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        for forbidden in ("write_text(", "to_csv", "mkdir("):
            assert forbidden not in source, f"{name} 이 {forbidden} 로 파일을 쓴다"


# ── 금지 행위 감지기 — 3케이스 ───────────────────────────────────────

def _repo(tmp_path: Path) -> Path:
    """작은 git 저장소를 만들어 기준선을 갖춘다."""
    root = tmp_path / "repo"
    (root / "src/ai_fc/db").mkdir(parents=True)
    (root / "calibration").mkdir(parents=True)
    (root / "forecasts/2026").mkdir(parents=True)
    (root / "src/ai_fc/db/schema.sql").write_text(
        "CREATE VIEW v_gate_status AS SELECT\n"
        "  COUNT(DISTINCT r.question_id) >= 50 AND AVG(r.brier) < 0.18 AS gate_p3,\n"
        "  COUNT(DISTINCT r.question_id) >= 30 AND AVG(r.brier) < 0.20 AS gate_p2\n"
        "FROM resolutions r;\n", encoding="utf-8")
    (root / "src/ai_fc/config.py").write_text(
        'GATE_P3 = {"n": 50, "brier": 0.18}\n', encoding="utf-8")
    (root / "calibration/ledger.csv").write_text(
        "resolved_date,question_id,forecast_id,brier\n"
        "2026-07-10,a,fa,0.25\n2026-07-11,b,fb,0.10\n", encoding="utf-8")
    (root / "calibration/research_status_overrides.csv").write_text(
        "forecast_id,research_status,reason\nfa,failed,전멸\n", encoding="utf-8")
    (root / "forecasts/2026/2026-07-10_a_r1.md").write_text(
        "---\nquestion_id: a\n---\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "baseline")
    return root


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_detects_gate_arithmetic_change(tmp_path: Path) -> None:
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    assert check_all(root) == []
    path = root / "src/ai_fc/db/schema.sql"
    path.write_text(path.read_text(encoding="utf-8").replace("< 0.18", "< 0.20"),
                    encoding="utf-8")
    hits = check_all(root)
    assert any(v.rule == "gate_arithmetic_change" for v in hits)


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_detects_ledger_row_deletion(tmp_path: Path) -> None:
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    path = root / "calibration/ledger.csv"
    kept = [l for l in path.read_text(encoding="utf-8").splitlines(True)
            if not l.startswith("2026-07-10")]
    path.write_text("".join(kept), encoding="utf-8")
    hits = check_all(root)
    assert any(v.rule == "ledger_append_only" for v in hits)
    assert any("append-only 위반" in v.detail for v in hits)


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_detects_post_hoc_failed_tag_change(tmp_path: Path) -> None:
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    path = root / "calibration/research_status_overrides.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("fa,failed", "fb,failed"),
                    encoding="utf-8")
    hits = check_all(root)
    assert any(v.rule == "post_hoc_failed_tagging" for v in hits)


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_appending_a_new_row_is_allowed(tmp_path: Path) -> None:
    """새 예측이 생기면 원장 행도 태그도 늘어난다 — 추가는 위반이 아니다."""
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    with (root / "calibration/ledger.csv").open("a", encoding="utf-8") as fh:
        fh.write("2026-07-12,c,fc,0.04\n")
    with (root / "calibration/research_status_overrides.csv").open("a", encoding="utf-8") as fh:
        fh.write("fc,degraded,검색 부족\n")
    assert check_all(root) == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_detects_forecast_file_modification(tmp_path: Path) -> None:
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    path = root / "forecasts/2026/2026-07-10_a_r1.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n수정\n", encoding="utf-8")
    hits = check_all(root)
    assert any("기존 파일이 수정·삭제됐다" in v.detail for v in hits)


def test_unreadable_baseline_is_not_a_pass(tmp_path: Path) -> None:
    """git 을 못 읽으면 '보류'다. 보류는 통과가 아니다."""
    from ai_fc.gate_guard import check_ledger_append_only
    hits = check_ledger_append_only(tmp_path / "not-a-repo", "HEAD")
    assert hits and "보류는 통과가 아니다" in hits[0].detail


def test_live_repository_has_no_violations() -> None:
    from ai_fc.gate_guard import check_all
    assert check_all(ROOT) == [], "현 작업 트리에 금지 행위가 감지된다"


# ── 추가는 위반이 아니다 (2026-09-11 오탐) ───────────────────────────

@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_a_new_forecast_file_is_not_a_violation(tmp_path: Path) -> None:
    """불변 규약은 '생성 후 수정·삭제 금지'이지 '새 파일 금지'가 아니다.

    실측 계기: W1 배치의 신규 예측 4건을 커밋하려는데 감지기가
    'forecasts/ 가 수정됐다'로 막았다. 새 예측은 언제나 새 파일로 들어오므로
    (재예측도 r<N> 신규 파일) 추가를 막으면 감지기가 파이프라인 자체를 막는다.
    """
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    (root / "forecasts/2026/2026-09-11_new_r1.md").write_text(
        "---\nquestion_id: new\n---\n", encoding="utf-8")
    assert check_all(root) == [], "신규 예측 파일 추가가 위반으로 잡힌다"


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_modifying_an_existing_forecast_is_still_a_violation(tmp_path: Path) -> None:
    """추가를 허용해도 **수정은 여전히** 잡혀야 한다 — 그게 이 감지기의 본래 목적이다."""
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    path = root / "forecasts/2026/2026-07-10_a_r1.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nprobability: 99\n", encoding="utf-8")
    hits = check_all(root)
    assert any("기존 파일이 수정·삭제됐다" in v.detail for v in hits)


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_deleting_a_forecast_is_a_violation(tmp_path: Path) -> None:
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    (root / "forecasts/2026/2026-07-10_a_r1.md").unlink()
    hits = check_all(root)
    assert any("기존 파일이 수정·삭제됐다" in v.detail for v in hits)


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_hashes_anchor_is_append_only_not_frozen(tmp_path: Path) -> None:
    """.hashes 는 새 예측마다 줄이 붙는다 — 추가는 허용, 삭제는 위반."""
    from ai_fc.gate_guard import check_all
    root = _repo(tmp_path)
    anchor = root / "forecasts/.hashes"
    anchor.write_text("2026-07-10_a_r1  deadbeef\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)

    git("add", "-A")
    git("commit", "-qm", "anchor")

    with anchor.open("a", encoding="utf-8") as fh:      # 추가 — 정상
        fh.write("2026-09-11_new_r1  cafebabe\n")
    assert check_all(root) == []

    anchor.write_text("2026-09-11_new_r1  cafebabe\n", encoding="utf-8")   # 기존 줄 삭제
    hits = check_all(root)
    assert any(".hashes" in v.detail and "사라지거나" in v.detail for v in hits)
