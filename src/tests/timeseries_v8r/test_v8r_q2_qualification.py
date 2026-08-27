from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_fc.timeseries_v8r.qualification import (
    benjamini_hochberg,
    cscv_pbo,
    horizon_mde,
)


ROOT = Path(__file__).resolve().parents[3]
FROZEN_GATE = ROOT / "src" / "ai_fc" / "timeseries_v7_r5" / "outer_gate.py"


def test_bh_uses_registry_attempt_count_and_is_pre_filter_only():
    result = benjamini_hochberg(
        {"a": 0.005, "b": 0.03, "c": 0.2}, registry_attempts=10, q=0.10
    )
    assert result["selected"] == ["a"]
    assert result["registry_attempts"] == 10
    assert result["usage"] == "pre_admission_filter_only"
    assert result["gate_formula_changed"] is False
    with pytest.raises(ValueError):
        benjamini_hochberg({"a": 0.1, "b": 0.2}, registry_attempts=1)


def test_cscv_s16_reports_overfit_probability_without_outer_rows():
    rows = []
    for index in range(64):
        durable = 0.2 + (index % 5) * 0.01
        unstable = 1.0 if index < 32 else -1.0
        noise = ((index * 17) % 11 - 5) / 10
        rows.append([durable, unstable, noise])
    result = cscv_pbo(rows)
    assert result["splits"] == 16
    assert result["combinations"] == 12870
    assert 0 <= result["pbo"] <= 1
    assert result["outer_rows_used"] == 0


def test_mde_is_horizon_specific_and_more_data_reduces_detection_floor():
    short = [(-1) ** i * 0.02 + 0.01 for i in range(40)]
    long = short * 4
    result = horizon_mde({1: short, 5: long})
    assert result["rows"]["5"]["mde_absolute"] < result["rows"]["1"]["mde_absolute"]
    assert result["rows"]["1"]["interpretation"] == "below_mde_is_underpowered_not_no_effect"
    assert result["outer_rows_used"] == 0


def test_q2_does_not_mutate_frozen_r5_gate():
    before = hashlib.sha256(FROZEN_GATE.read_bytes()).hexdigest()
    benjamini_hochberg({"registered": 0.01}, registry_attempts=1)
    horizon_mde({21: [0.01, -0.01, 0.02, -0.02]})
    after = hashlib.sha256(FROZEN_GATE.read_bytes()).hexdigest()
    assert after == before
