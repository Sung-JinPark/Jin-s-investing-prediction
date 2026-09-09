"""C5 부수 증명서·게이트 거울 테스트 (설계도 §8).

핵심 고정점 세 가지:
1. 게이트 산술의 비대칭 — 문항은 DISTINCT, Brier 는 행 평균 (설계도 §1.2 A1).
2. 예리도 항등식 — 완전 캘리브레이션 하의 기대 Brier = p(1-p).
3. 부수 증명서는 **표시 계층**이며 게이트 판정을 바꾸지 않는다.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ai_fc import c5_certificate as C5

ROOT = Path(__file__).resolve().parents[2]


# ── 픽스처: 최소 저장소 ────────────────────────────────────────────

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _forecast(qid: str, rnd: int, prob: int, *, anchor: int | None = None,
              model: str = "claude-opus-5 (Claude Code)", status: str = "ok") -> str:
    body = f"""---
forecast_id: 2026-01-01_{qid}_r{rnd}
question_id: {qid}
probability: {prob}
model: {model}
research_status: {status}
---

## [1] Outside View — base rate""" + (f" (anchor: {anchor}%)" if anchor is not None else "")
    return body


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    # 2문항 · 3행. q1 은 2회차(재예측), q2 는 1회차.
    _write(tmp_path / "forecasts/2026/2026-01-01_q1_r1.md", _forecast("q1", 1, 40, anchor=45))
    _write(tmp_path / "forecasts/2026/2026-01-01_q1_r2.md", _forecast("q1", 2, 20, anchor=25))
    _write(tmp_path / "forecasts/2026/2026-01-01_q2_r1.md",
           _forecast("q2", 1, 80, anchor=70, model="gpt-5.6-terra"))
    _write(tmp_path / "calibration/ledger.csv", "\n".join([
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes",
        "2026-02-01,q1,2026-01-01_q1_r1,2026-01-01,40,0,0.16,macro,x",
        "2026-02-01,q1,2026-01-01_q1_r2,2026-01-01,20,0,0.04,macro,x",
        "2026-02-01,q2,2026-01-01_q2_r1,2026-01-01,80,1,0.04,earnings,x",
    ]) + "\n")
    _write(tmp_path / "calibration/research_status_overrides.csv",
           "forecast_id,status,reason,created_at\n")
    _write(tmp_path / "questions/registry.yaml", """version: 1
questions:
  - id: q1
    domain: macro
    status: resolved
    deadline: '2026-02-01'
    drivers: [fed-path]
  - id: q2
    domain: earnings
    status: resolved
    deadline: '2026-02-01'
    drivers: [ai-capex-cycle]
""")
    return tmp_path


# ── 게이트 산술 ────────────────────────────────────────────────────

def test_gate_counts_distinct_questions_but_averages_rows(repo: Path) -> None:
    """설계도 §1.2 A1 — 재예측은 문항 수에 0 기여, Brier 에는 기여한다."""
    gate = C5.gate_status(repo)
    assert gate["n_questions"] == 2          # q1 의 2회차는 하나로 센다
    assert gate["n_rows_primary"] == 3       # 그러나 Brier 는 3행 평균
    assert gate["brier"] == pytest.approx((0.16 + 0.04 + 0.04) / 3)
    assert gate["gate_p3"] is False          # 문항 2 < 50


def test_failed_override_excluded_from_primary(repo: Path) -> None:
    path = repo / "calibration/research_status_overrides.csv"
    with path.open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerow(
            ["2026-01-01_q1_r1", "failed", "리서치 전멸", "2026-02-01"])
    gate = C5.gate_status(repo)
    assert gate["n_excluded"] == 1
    assert gate["n_rows_primary"] == 2
    assert gate["n_questions"] == 2           # q1 은 r2 로 여전히 살아 있다


def test_frontmatter_research_status_failed_also_excluded(repo: Path) -> None:
    _write(repo / "forecasts/2026/2026-01-01_q2_r1.md",
           _forecast("q2", 1, 80, anchor=70, status="failed"))
    gate = C5.gate_status(repo)
    assert gate["n_excluded"] == 1
    assert gate["n_questions"] == 1


# ── 예리도 (D2) ────────────────────────────────────────────────────

def test_sharpness_is_row_level_and_matches_identity(repo: Path) -> None:
    s = C5.sharpness(repo)
    expected = (0.40 * 0.60 + 0.20 * 0.80 + 0.80 * 0.20) / 3
    assert s["rows"]["n"] == 3
    assert s["rows"]["mean_pq"] == pytest.approx(expected)
    assert s["rows"]["deficit"] == pytest.approx(0.18 * 3 - expected * 3)


def test_reforecast_sharpening_is_measured(repo: Path) -> None:
    """q1: 40% -> 20% 이므로 p(1-p) 가 0.24 -> 0.16 으로 예리해진다."""
    rf = C5.sharpness(repo)["reforecast"]
    assert rf["n"] == 1
    assert rf["first"] == pytest.approx(0.24)
    assert rf["latest"] == pytest.approx(0.16)
    assert rf["delta"] == pytest.approx(-0.08)
    assert rf["sharpened"] == 1


@pytest.mark.parametrize("target,expected", [(0.10, 3), (0.17, 21)])
def test_required_new_rows(target: float, expected: int) -> None:
    assert C5.required_new_rows(-0.2075, target) == expected


def test_required_new_rows_impossible_at_or_above_threshold() -> None:
    """신규가 임계만큼 무디면 어떤 수로도 못 메운다 — ∞ 를 None 으로 표현."""
    assert C5.required_new_rows(-0.2075, 0.18) is None
    assert C5.required_new_rows(-0.2075, 0.25) is None
    assert C5.required_new_rows(0.5, 0.25) == 0     # 이미 흑자면 0


# ── 부수 증명서 ────────────────────────────────────────────────────

def test_bss_uses_anchor_and_skips_unrecoverable(repo: Path) -> None:
    _write(repo / "forecasts/2026/2026-01-01_q2_r1.md", _forecast("q2", 1, 80))  # anchor 없음
    gate = C5.gate_status(repo)
    bss = C5.bss_vs_anchor(repo, gate)
    assert bss["n"] == 2 and bss["missing"] == 1     # 추정으로 채우지 않는다
    assert bss["brier_anchor"] == pytest.approx((0.45 ** 2 + 0.25 ** 2) / 2)


def test_bss_positive_when_model_beats_anchor(repo: Path) -> None:
    bss = C5.bss_vs_anchor(repo, C5.gate_status(repo))
    assert bss["n"] == 3
    assert bss["bss"] > 0        # 40->0 (0.16) vs anchor 45 (0.2025) 등


def test_murphy_decomposition_identity(repo: Path) -> None:
    """Brier = REL − RES + UNC 항등식이 성립해야 한다."""
    mu = C5.murphy(C5.gate_status(repo))
    assert mu["brier"] == pytest.approx(
        mu["reliability"] - mu["resolution"] + mu["uncertainty"], abs=1e-9)


def test_ess_is_a_lower_bound(repo: Path) -> None:
    clusters = C5.driver_clusters(repo)
    ess = C5.effective_sample_size(clusters)
    assert ess["nominal"] == 2
    assert ess["ess_lower"] == pytest.approx(2.0)     # 두 클러스터에 1개씩 = 완전 독립


def test_ess_collapses_when_one_driver_dominates(tmp_path: Path) -> None:
    _write(tmp_path / "questions/registry.yaml", """version: 1
questions:
""" + "".join(f"  - {{id: q{i}, status: active, drivers: [ai-capex-cycle]}}\n"
               for i in range(10)))
    ess = C5.effective_sample_size(C5.driver_clusters(tmp_path))
    assert ess["nominal"] == 10
    assert ess["ess_lower"] == pytest.approx(1.0)     # 전부 한 덩어리
    assert ess["largest_share"] == pytest.approx(1.0)


def test_void_questions_excluded_from_clusters(tmp_path: Path) -> None:
    _write(tmp_path / "questions/registry.yaml", """version: 1
questions:
  - {id: a, status: active, drivers: [fed-path]}
  - {id: b, status: void, drivers: [fed-path]}
""")
    assert C5.driver_clusters(tmp_path) == {"fed-path": ["a"]}


def test_production_path_split_flags_unmetered(repo: Path) -> None:
    paths = C5.production_paths(repo)
    assert paths["claude_code (unmetered)"] == 2
    assert paths["cli/api"] == 1


# ── 큐·분산 ────────────────────────────────────────────────────────

def test_queues_flag_sla_breach(tmp_path: Path) -> None:
    from datetime import date
    _write(tmp_path / "questions/registry.yaml", """version: 1
questions:
  - {id: late, status: active, deadline: '2026-09-01', domain: macro}
  - {id: rolling, status: active, deadline: rolling-90d, domain: macro}
""")
    q = C5.queues(tmp_path, today=date(2026, 9, 9))
    ids = [x["id"] for x in q["resolve_overdue"]]
    assert ids == ["late"]                       # 날짜형이 아닌 rolling 은 건너뛴다
    assert q["resolve_overdue"][0]["sla_breach"] is True
    assert q["never_forecast"] == ["late", "rolling"]


def test_diversification_violations_are_counted(repo: Path) -> None:
    _write(repo / "questions/portfolio_prereg_v1.yaml", """schema_version: 1
diversification: {max_driver_share: 0.40, max_same_deadline: 1, min_domains: 4}
""")
    for q in repo.glob("questions/registry.yaml"):
        q.write_text(q.read_text(encoding="utf-8").replace("resolved", "active"),
                     encoding="utf-8")
    result = C5.diversification_check(repo)
    assert any("마감일" in v for v in result["violations"])
    assert any("도메인" in v for v in result["violations"])


# ── 게이트 무변경 보증 ─────────────────────────────────────────────

def test_certificate_never_changes_gate_arithmetic() -> None:
    """정본 뷰의 임계는 이 프로그램에서 바뀌지 않는다 (설계도 §8.1)."""
    schema = (ROOT / "src" / "ai_fc" / "db" / "schema.sql").read_text(encoding="utf-8")
    assert "COUNT(DISTINCT r.question_id) >= 50 AND AVG(r.brier) < 0.18" in schema
    assert "COUNT(DISTINCT r.question_id) >= 30 AND AVG(r.brier) < 0.20" in schema
    assert C5.BRIER_THRESHOLD_P3 == 0.18
    assert C5.QUESTIONS_THRESHOLD_P3 == 50


def test_module_is_read_only() -> None:
    """쓰기 호출이 들어오면 즉시 잡는다 — 이 모듈은 읽기 전용이어야 한다."""
    source = (ROOT / "src" / "ai_fc" / "c5_certificate.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "open(.*'w'", ".unlink(", "shutil."):
        assert forbidden not in source, f"읽기 전용 위반 후보: {forbidden}"
