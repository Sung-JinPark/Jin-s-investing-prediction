"""WS6: divergence 정당화 스키마 강제 — 무정당화 divergence 기록 거부."""

from __future__ import annotations

from ai_fc.files import validate_new_record

BASE_FM = {
    "forecast_id": "2099-01-01_fx_r1", "question_id": "fx", "timestamp": "2099-01-01 09:00 KST",
    "phase": "P1", "model": "m", "prompt_version": "v1",
    "probability": 57, "ci80": [44, 70],
}


def test_divergence_requires_note_and_class() -> None:
    fm = dict(BASE_FM, ml_divergence_pp=18.0)
    errors = validate_new_record(fm)
    assert any("divergence_note 필수" in e for e in errors)
    assert any("divergence_class" in e for e in errors)


def test_divergence_with_justification_passes() -> None:
    fm = dict(BASE_FM, ml_divergence_pp=18.0,
              divergence_note="무조건부 모델이 창 내 FOMC 2회를 모름",
              divergence_class="event_conditionality")
    assert validate_new_record(fm) == []


def test_divergence_invalid_class_rejected() -> None:
    fm = dict(BASE_FM, ml_divergence_pp=20.0,
              divergence_note="정당화", divergence_class="vibes")
    assert any("divergence_class" in e for e in validate_new_record(fm))


def test_below_threshold_no_requirement() -> None:
    """15%p 미만 괴리는 정당화 비강제 (기록만)."""
    fm = dict(BASE_FM, ml_divergence_pp=14.9)
    assert validate_new_record(fm) == []
    fm_none = dict(BASE_FM)  # 괴리 미기록 (ML 참조 부재) — 무조건 통과
    assert validate_new_record(fm_none) == []
