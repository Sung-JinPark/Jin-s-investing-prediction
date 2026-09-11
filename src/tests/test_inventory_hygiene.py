"""T05 — 재고 위생·처리량·품질 티어를 고정한다.

세 가지를 못박는다: lite 은퇴가 **등록 기록을 지우지 않고** 실행 시점에만 적용될 것 ·
마감 null 이 남아 있지 않을 것 · 소실률 정본이 계약값 그대로일 것.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "questions/registry.yaml").read_text(encoding="utf-8"))


# ── lite 은퇴 ────────────────────────────────────────────────────────

def test_lite_is_retired_at_the_recorded_date() -> None:
    from ai_fc import config
    assert config.LITE_TIER_RETIRED_AT == date(2026, 9, 11)


def test_effective_tier_promotes_lite_after_retirement() -> None:
    from ai_fc.registry import effective_tier, load_registry
    qs = load_registry(ROOT / "questions/registry.yaml")
    lite = [q for q in qs if q.tier == "lite"]
    assert lite, "lite 등록분이 사라졌다 — 역사 기록을 지우면 안 된다"
    assert {effective_tier(q, date(2026, 9, 10)) for q in lite} == {"lite"}
    assert {effective_tier(q, date(2026, 9, 11)) for q in lite} == {"standard"}
    std = [q for q in qs if q.tier == "standard"]
    assert {effective_tier(q, date(2026, 9, 11)) for q in std} == {"standard"}


def test_registry_still_records_what_was_registered(registry) -> None:
    """은퇴를 레지스트리 일괄 수정으로 했다면 '그때 무엇으로 등록했는가'가 지워진다."""
    lite = [q for q in registry["questions"] if q.get("tier") == "lite"]
    assert len(lite) >= 40, f"lite 등록 기록이 줄었다: {len(lite)}"


def test_research_path_reads_the_effective_tier_not_the_raw_field() -> None:
    source = (ROOT / "src/ai_fc/agents/base.py").read_text(encoding="utf-8")
    assert "effective_tier(q, today)" in source
    assert 'getattr(q, "tier", "standard") == "lite"' not in source, \
        "원시 필드를 그대로 보면 은퇴가 적용되지 않는다"


def test_forecast_frontmatter_keeps_both_tiers() -> None:
    """하나만 남기면 은퇴 전후 회차를 나중에 구별할 수 없다."""
    source = (ROOT / "src/ai_fc/orchestrator.py").read_text(encoding="utf-8")
    assert '"pipeline_tier": effective_tier(q, now.date()),' in source
    assert '"registered_tier": getattr(q, "tier", "standard"),' in source


def test_retirement_rationale_names_the_confound() -> None:
    """lite 4건은 전부 openai, 비교군 4건은 전부 anthropic — 두 축이 겹쳐 있다."""
    source = (ROOT / "src/ai_fc/config.py").read_text(encoding="utf-8")
    assert "티어와 제공자를 분리하지 못한다" in source
    assert "gpt-5.6-terra" in source and "claude-opus-4-8" in source


# ── 마감 위생 ────────────────────────────────────────────────────────

def test_no_active_question_has_a_null_deadline(registry) -> None:
    """deadline 이 null 이면 orchestrator 가 예측을 거부해 영구 미예측으로 남는다."""
    from ai_fc.c5_certificate import as_date
    bad = [q["id"] for q in registry["questions"]
           if q.get("status") == "active" and as_date(q.get("deadline")) is None
           and not str(q.get("deadline") or "").startswith("rolling")]
    assert not bad, f"마감 미기재 활성 질문: {bad}"


def test_micron_deadline_records_that_it_is_an_upper_bound(registry) -> None:
    q = next(x for x in registry["questions"] if x["id"] == "mu-margin-qoq-fq1fy27")
    assert str(q["deadline"]).startswith("2026-12-31")
    basis = q["deadline_basis"]
    assert "[미검증]" in basis and "재확인" in basis
    assert "판정기준(resolution)은 한 글자도 바뀌지 않았고" in basis


# ── 소실률 정본 ──────────────────────────────────────────────────────

def test_expected_void_rate_is_unchanged_after_seeing_the_data() -> None:
    """사용자 확정(2026-09-11): 계약값 14.9% 유지.

    실측이 12.7% 로 나왔다고 사전등록 파라미터를 갈아끼우면, 같은 움직임이 불리한
    방향으로도 허용된다는 선례가 남는다.
    """
    contract = yaml.safe_load(
        (ROOT / "questions/portfolio_prereg_v1.yaml").read_text(encoding="utf-8"))
    plan = contract["new_registration"]
    assert plan["expected_void_rate"] == 0.149
    assert plan["expected_survivors"] == 10.2


def test_measured_loss_rates_are_recorded_separately(registry) -> None:
    """정본은 계약값이지만 실측도 남긴다 — 둘이 다르다는 사실이 보여야 한다."""
    doc = (ROOT / "docs/p3_gate_path/T05_RESULT.md").read_text(encoding="utf-8")
    for token in ("12.7%", "0.0%", "11.1%", "14.9%"):
        assert token in doc, f"실측 {token} 이 결과 문서에 없다"


def test_all_voids_were_caught_before_any_forecast_was_spent(registry) -> None:
    """void 10건이 전부 예측 0건이라는 사실이 '구조적 소실 0'의 근거다."""
    from ai_fc.c5_certificate import read_forecasts
    spent = {f.question_id for f in read_forecasts(ROOT)}
    voids = [q["id"] for q in registry["questions"] if q.get("status") == "void"]
    assert voids, "void 표본이 없다"
    assert not (set(voids) & spent), "예측을 소모한 뒤 void 된 질문이 생겼다 — 구조적 소실 0 이 깨졌다"


# ── 품질 티어 단가 실측표 ────────────────────────────────────────────

def test_tier_cost_table_is_reproducible_from_forecast_frontmatter() -> None:
    costs: dict[str, list[tuple[float, str]]] = {}
    for path in sorted((ROOT / "forecasts/2026").glob("*.md")):
        if path.name.endswith("_evidence.md"):
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        fm = text.split("---", 2)[1]

        def g(key: str, fm: str = fm) -> str | None:
            m = re.search(r"^" + key + r":\s*(.+)$", fm, re.M)
            return m.group(1).strip() if m else None

        cost = g("cost_usd")
        if not cost:
            continue
        costs.setdefault(g("pipeline_tier") or "(표기 없음)", []).append(
            (float(cost), g("research_status") or "ok"))

    lite = costs.get("lite") or []
    assert len(lite) == 4, f"lite 과금 회차가 4건이 아니다: {len(lite)}"
    assert all(rs != "ok" for _, rs in lite), "lite 4/4 가 degraded/failed 라는 근거가 깨졌다"
    assert sum(c for c, _ in lite) / len(lite) == pytest.approx(0.2129, abs=5e-4)

    other = costs.get("(표기 없음)") or []
    assert len(other) == 4 and all(rs == "ok" for _, rs in other)
    assert sum(c for c, _ in other) / len(other) == pytest.approx(1.7197, abs=5e-4)


def test_monthly_subcap_arithmetic_holds_at_three_per_week() -> None:
    """주 3건 = 13회차/월. 실측 단가에서 월 sub-cap $25 가 성립하는가."""
    rounds_per_month = 13
    assert 1.7197 * rounds_per_month == pytest.approx(22.36, abs=0.01)
    assert 1.7197 * rounds_per_month <= 25.0
    # 설계서 표준 목표 단가($2.5~4)로 실현되면 주 3건은 한도를 넘는다 — 그 사실도 고정한다.
    assert 2.5 * rounds_per_month > 25.0
    assert int(25.0 / 1.7197) == 14
