"""L0 Batch 1 — forecast math contracts and append-only read compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc import files as F
from ai_fc.llm_provider import ProviderOutputError, validate_forecast_output
from ai_fc.schemas import FORECAST_ARITHMETIC_TOLERANCE_PP


def _payload(
    *,
    probability: int = 60,
    ci80_lo: int = 40,
    ci80_hi: int = 75,
    anchor_pct: int | None = None,
    adjustments: list[dict] | None = None,
) -> dict:
    return {
        "question_check": "판정 가능",
        "reference_class": "등록된 가공 참조 클래스",
        "base_rates": ["a", "b", "c"],
        "anchor_pct": probability if anchor_pct is None else anchor_pct,
        "adjustments": [] if adjustments is None else adjustments,
        "decomposition": "가공 분해",
        "premortem": ["a", "b", "c"],
        "probability": probability,
        "ci80_lo": ci80_lo,
        "ci80_hi": ci80_hi,
        "key_reasons": ["a", "b", "c"],
        "observables": ["a", "b"],
        "snapshots_filled": [],
        "unverified_notes": [],
    }


def _adjustment(evidence: str, direction: str, delta_pp: float) -> dict:
    return {"evidence": evidence, "direction": direction, "delta_pp": delta_pp}


@pytest.mark.parametrize(
    ("point", "low", "high"),
    [
        (60, 40, 75),
        (40, 40, 75),
        (75, 40, 75),
    ],
)
def test_ci_contains_point_including_boundaries(point: int, low: int, high: int) -> None:
    result = validate_forecast_output(
        _payload(probability=point, ci80_lo=low, ci80_hi=high)
    )

    assert (result.ci80_lo, result.probability, result.ci80_hi) == (low, point, high)


@pytest.mark.parametrize(
    "payload",
    [
        _payload(probability=39, ci80_lo=40, ci80_hi=75),
        _payload(probability=76, ci80_lo=40, ci80_hi=75),
        _payload(probability=60, ci80_lo=75, ci80_hi=40),
        _payload(probability=0, ci80_lo=1, ci80_hi=75),
        _payload(probability=60, ci80_lo=0, ci80_hi=75),
        _payload(probability=60, ci80_lo=40, ci80_hi=100),
    ],
)
def test_ci_rejects_non_containment_order_and_range(payload: dict) -> None:
    with pytest.raises(ProviderOutputError):
        validate_forecast_output(payload)


def test_frontmatter_validator_rejects_ci_that_excludes_point() -> None:
    fm = {
        "forecast_id": "fixture-r1",
        "question_id": "fixture",
        "timestamp": "2099-01-01 12:00 KST",
        "phase": "P1",
        "model": "fixture-model",
        "prompt_version": "fixture-v1",
        "probability": 60,
        "ci80": [61, 75],
    }

    assert any("포함" in error for error in F.validate_new_record(fm))


def test_forecast_arithmetic_exact_match() -> None:
    result = validate_forecast_output(
        _payload(
            probability=60,
            anchor_pct=55,
            adjustments=[_adjustment("상향 근거", "up", 5.0)],
        )
    )

    assert result.probability == 60


def test_forecast_arithmetic_mixed_positive_and_negative_adjustments() -> None:
    result = validate_forecast_output(
        _payload(
            probability=55,
            anchor_pct=50,
            adjustments=[
                _adjustment("상향 근거", "up", 10.0),
                _adjustment("하향 근거", "down", 5.0),
            ],
        )
    )

    assert result.probability == 55


def test_forecast_arithmetic_rejects_mismatch_and_sign_error() -> None:
    with pytest.raises(ProviderOutputError, match="signed adjustments"):
        validate_forecast_output(
            _payload(
                probability=61,
                anchor_pct=55,
                adjustments=[_adjustment("상향 근거", "up", 5.0)],
            )
        )

    with pytest.raises(ProviderOutputError, match="signed adjustments"):
        validate_forecast_output(
            _payload(
                probability=55,
                anchor_pct=50,
                adjustments=[_adjustment("부호 오류", "down", 5.0)],
            )
        )


def test_forecast_arithmetic_rounding_tolerance_boundary() -> None:
    within = _payload(
        probability=60,
        anchor_pct=55,
        adjustments=[_adjustment("반올림 경계", "up", 5.0 + FORECAST_ARITHMETIC_TOLERANCE_PP)],
    )
    assert validate_forecast_output(within).probability == 60

    outside = _payload(
        probability=60,
        anchor_pct=55,
        adjustments=[
            _adjustment(
                "반올림 경계 초과",
                "up",
                5.0 + FORECAST_ARITHMETIC_TOLERANCE_PP + 0.001,
            )
        ],
    )
    with pytest.raises(ProviderOutputError, match="signed adjustments"):
        validate_forecast_output(outside)


def test_forecast_arithmetic_rejects_missing_and_duplicate_adjustments() -> None:
    missing = _payload()
    del missing["adjustments"]
    with pytest.raises(ProviderOutputError):
        validate_forecast_output(missing)

    duplicate = _adjustment("중복 근거", "up", 5.0)
    with pytest.raises(ProviderOutputError, match="duplicate adjustment"):
        validate_forecast_output(
            _payload(
                probability=60,
                anchor_pct=50,
                adjustments=[duplicate, dict(duplicate)],
            )
        )


def test_historical_ledger_read_is_backward_compatible_and_non_mutating(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.csv"
    original = (
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n"
        "2026-01-02,legacy-q,2025-12-01_legacy-q_r1,2025-12-01,60,1,0.16,fixture,legacy\n"
    ).encode("utf-8")
    ledger.write_bytes(original)

    rows = F.parse_ledger(ledger)

    assert len(rows) == 1
    assert rows[0].forecast_id == "2025-12-01_legacy-q_r1"
    assert ledger.read_bytes() == original
