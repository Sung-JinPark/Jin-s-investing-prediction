"""T07 — 질문 발굴 엔진 · 사구간 감시 · 추론 코어 v1.1 을 고정한다.

세 모듈이 공유하는 규율 하나: **후보를 내는 쪽도, 감시하는 쪽도 확률을 밀지 않는다.**
임계는 사람이 정하고, 사구간 경고의 올바른 반응은 확률 조정이 아니라 질문 재설계다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── 발굴 엔진 ────────────────────────────────────────────────────────

def test_engine_never_proposes_a_threshold() -> None:
    """후보를 내는 쪽이 임계도 정하면 z 규율이 자기충족이 된다."""
    from ai_fc.question_discovery import Candidate, discover
    cands = discover(ROOT, today=date(2026, 9, 11), horizon_days=365)
    assert all(c.threshold is None for c in cands)
    source = (ROOT / "src/ai_fc/question_discovery.py").read_text(encoding="utf-8")
    for forbidden in ("ledger.csv", "read_ledger"):
        assert forbidden not in source, "발굴 엔진이 성적을 보면 선택 편향이다"


def test_engine_only_surfaces_events_with_an_issuer_forecast() -> None:
    from ai_fc.question_discovery import ISSUER_FORECASTS, NO_ISSUER_FORECAST, discover
    cands = discover(ROOT, today=date(2026, 9, 11), horizon_days=365)
    assert cands, "캘린더 지평 안에 후보가 하나도 없다"
    kinds = {c.kind for c in cands}
    assert kinds <= set(ISSUER_FORECASTS)
    assert not (kinds & NO_ISSUER_FORECAST)
    assert all(c.issuer_forecast for c in cands)


def test_engine_does_not_claim_three_of_three() -> None:
    """임계 원거리는 사람이 임계를 넣은 뒤에만 판정된다."""
    from ai_fc.question_discovery import discover
    cands = discover(ROOT, today=date(2026, 9, 11), horizon_days=365)
    assert all(c.properties_met <= 2 for c in cands)
    assert all("스스로 주장하지 않는다" in c.note for c in cands)


def test_engine_respects_the_deadline_cap() -> None:
    from ai_fc.question_discovery import discover
    cap = date(2027, 1, 15)
    cands = discover(ROOT, today=date(2026, 9, 11), horizon_days=730, deadline_cap=cap)
    assert cands and all(c.deadline <= cap for c in cands)


def test_engine_flags_deadline_collisions_with_registered_questions() -> None:
    """같은 마감에 문항이 몰리면 분산 규칙 위반이 된다 — 후보 단계에서 보여야 한다."""
    from ai_fc.question_discovery import discover
    cands = discover(ROOT, today=date(2026, 9, 11), horizon_days=365)
    assert any(c.already_registered for c in cands), "기등록 충돌이 하나도 안 잡힌다"


def test_evaluate_uses_only_human_supplied_numbers() -> None:
    from ai_fc.question_discovery import discover, evaluate
    cand = discover(ROOT, today=date(2026, 9, 11), horizon_days=365)[0]
    ok = evaluate(ROOT, cand, threshold=-75_000, center=70_000, sigma=95_000,
                  sigma_source="data/base_rates/macro.md", honest_probability=0.09,
                  domain="macro", question_id="test-far")
    assert ok["accepted"] and ok["z"] == pytest.approx(1.5263, abs=1e-3)

    near = evaluate(ROOT, cand, threshold=100_000, center=55_000, sigma=95_000,
                    sigma_source="data/base_rates/macro.md", honest_probability=0.68,
                    domain="macro", question_id="test-near")
    assert not near["accepted"] and "사구간" in near["reason"]


# ── 사구간 감시 ──────────────────────────────────────────────────────

def test_band_comes_from_the_contract() -> None:
    from ai_fc.dead_zone_watch import band_and_thresholds
    (lo, hi), z_reject, cap = band_and_thresholds(ROOT)
    assert (lo, hi) == (0.235, 0.765)
    assert z_reject == pytest.approx(0.7)
    assert cap == pytest.approx(0.21)
    assert abs(lo * hi - 0.18) < 5e-4


def test_registration_blocks_but_forecast_only_warns() -> None:
    """예측 시점에 차단하면 확률을 미는 압력이 된다 — 그것이 극단화다."""
    from ai_fc.dead_zone_watch import check
    at_reg = check(ROOT, question_id="q", honest_probability=0.50, z=0.2,
                   stage="registration")
    at_fc = check(ROOT, question_id="q", honest_probability=0.50, z=0.2, stage="forecast")
    assert at_reg and all(w.blocking for w in at_reg)
    assert at_fc and not any(w.blocking for w in at_fc)


def test_forecast_warning_says_not_to_move_the_probability() -> None:
    from ai_fc.dead_zone_watch import NO_EXTREMIZATION, check
    warnings = check(ROOT, question_id="q", honest_probability=0.5, z=0.2, stage="forecast")
    assert all(NO_EXTREMIZATION in w.message for w in warnings)
    assert "극단화" in NO_EXTREMIZATION and "8-8" in NO_EXTREMIZATION


def test_clean_question_raises_nothing() -> None:
    from ai_fc.dead_zone_watch import check
    assert check(ROOT, question_id="q", honest_probability=0.09, z=1.53,
                 stage="registration") == []


def test_registry_scan_is_display_only() -> None:
    from ai_fc.dead_zone_watch import scan_coverage, scan_registry, watch_lines
    warnings = scan_registry(ROOT)
    assert all(not w.blocking for w in warnings), "기등록 질문에 소급 차단을 걸면 안 된다"
    lines = " ".join(watch_lines(warnings, scan_coverage(ROOT)))
    assert "소급하지 않는다" in lines


def test_zero_warnings_is_reported_with_its_coverage() -> None:
    """경고 0건을 '사구간 문항이 없다'로 읽으면 안 된다 — 볼 수 있는 것 중에 없는 것이다."""
    from ai_fc.dead_zone_watch import scan_coverage, scan_registry, watch_lines
    cov = scan_coverage(ROOT)
    assert cov["active"] > cov["covered"] > 0
    assert cov["uncovered"] == cov["active"] - cov["covered"]
    lines = " ".join(watch_lines(scan_registry(ROOT), cov))
    assert f"{cov['covered']}/{cov['active']}" in lines
    assert "판정 자체가 불가능하다" in lines


def test_the_twelve_new_questions_raise_no_dead_zone_warning() -> None:
    """T02 등록분은 계약 훅을 통과했으므로 감시기도 조용해야 한다."""
    import yaml

    from ai_fc.dead_zone_watch import check
    data = yaml.safe_load((ROOT / "questions/registry.yaml").read_text(encoding="utf-8"))
    prereg = [q for q in data["questions"] if isinstance(q.get("prereg"), dict)]
    assert len(prereg) == 12
    for q in prereg:
        p = q["prereg"]
        hits = check(ROOT, question_id=q["id"],
                     honest_probability=p["honest_probability_estimate"],
                     z=float(p["z"]), stage="forecast")
        assert not hits, f"{q['id']}: {[w.message for w in hits]}"


# ── 추론 코어 v1.1 ───────────────────────────────────────────────────

def test_prompt_version_is_v1_1_and_the_file_exists() -> None:
    from ai_fc import config
    assert config.PROMPT_VERSION == "reasoning_core_v1_1"
    assert (ROOT / "prompts/reasoning_core_v1_1.md").is_file()
    assert (ROOT / "prompts/reasoning_core_v1.md").is_file(), "v1 원본은 남긴다 (코호트 구별)"


def test_premortem_checklist_has_all_three_items() -> None:
    text = (ROOT / "prompts/reasoning_core_v1_1.md").read_text(encoding="utf-8")
    for item in ("전제 개정 취약성", "컨센서스 존재 여부", "임계 z"):
        assert item in text, f"필수 항목 {item} 이 없다"
    assert "생략 불가" in text


def test_checklist_forbids_extremization_explicitly() -> None:
    """z 가 작다는 사실이 확률을 미는 근거로 읽히면 체크리스트가 해가 된다."""
    text = (ROOT / "prompts/reasoning_core_v1_1.md").read_text(encoding="utf-8")
    assert "사구간 밖으로 밀지 마라" in text
    assert "극단화" in text and "8-8" in text
    assert "확률을 바꿀 근거가 아니라" in text


def test_v1_1_is_a_prompt_change_not_a_model_change() -> None:
    """ML 게이트 저촉 0 — 가중 학습·보정은 건드리지 않는다."""
    config_src = (ROOT / "src/ai_fc/config.py").read_text(encoding="utf-8")
    assert "가중 학습 아님" in config_src
    text = (ROOT / "prompts/reasoning_core_v1_1.md").read_text(encoding="utf-8")
    for forbidden in ("isotonic", "Platt", "가중 결합"):
        assert forbidden not in text


def test_v1_1_keeps_the_devils_advocate_rule() -> None:
    text = (ROOT / "prompts/reasoning_core_v1_1.md").read_text(encoding="utf-8")
    assert "데블스 애드버킷" in text and "생략 불가" in text
