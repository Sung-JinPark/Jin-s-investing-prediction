from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from ai_fc.timeseries_v7.contract_runtime_audit import REQUIRED_FOLD_ROLES, audit_runtime_contract
from ai_fc.timeseries_v7.gate_linter import GateWindow, lint_gate_windows
from ai_fc.timeseries_v7.gates import HISTORICAL_SUITES, RegimeScore, evaluate_historical_stress, evaluate_prospective_regimes
from ai_fc.timeseries_v7.models.e0_anchor import ExactEmpiricalAnchor, assert_comparator_identity


REPO = Path(__file__).resolve().parents[3]
CONTRACT = yaml.safe_load((REPO / "data/contracts/multivariate_timeseries_v7.yaml").read_text(encoding="utf-8"))


def test_v6_style_sealed_window_plus_gfc_requirement_is_infeasible() -> None:
    report = lint_gate_windows(
        evaluation_start=date(2019, 1, 1), evaluation_end=date(2026, 8, 25),
        windows=[GateWindow("gfc", date(2008, 1, 1), date(2009, 12, 31), 20)],
    )
    assert report["pass"] is False and report["checks"][0]["available_capacity"] == 0


def test_v7_open_historical_gfc_window_is_feasible() -> None:
    report = lint_gate_windows(
        evaluation_start=date(2007, 1, 1), evaluation_end=date(2026, 8, 25),
        windows=[GateWindow("gfc", date(2008, 1, 1), date(2009, 12, 31), 20)],
    )
    assert report["pass"] is True


def test_absent_future_gfc_is_not_applicable_but_historical_is_mandatory() -> None:
    prospective = evaluate_prospective_regimes({"gfc": RegimeScore(0, 0.0)})
    assert prospective["regimes"]["gfc"]["decision"] == "not_applicable" and prospective["pass"]
    scores = {name: RegimeScore(20, 0.7) for name in HISTORICAL_SUITES if name != "gfc"}
    assert evaluate_historical_stress(scores)["pass"] is False


def test_exact_anchor_identity_is_shared_at_all_stages() -> None:
    anchor = ExactEmpiricalAnchor.create("origin", 63, [-0.2, -0.1, 0.0, 0.1, 0.3])
    hashes = {stage: anchor.sample_hash for stage in ("evaluation", "stacking", "calibration", "display")}
    assert_comparator_identity(anchor, hashes)
    assert anchor.quantile(0.5) == 0.0
    assert anchor.cdf(0.0) == 0.6


def test_anchor_rejects_stage_specific_reconstruction() -> None:
    anchor = ExactEmpiricalAnchor.create("origin", 21, [0, 1])
    with pytest.raises(ValueError, match="identity mismatch"):
        assert_comparator_identity(anchor, {"evaluation": anchor.sample_hash, "display": "0" * 64})


def compliant_runtime() -> dict:
    experts = {}
    for key, spec in CONTRACT["candidates"].items():
        experts[key] = {"algorithm": spec["algorithm"]}
        if key == "E2": experts[key]["objective"] = spec["objective"]
        if key == "E7": experts[key]["full_trajectory_required"] = True
    return {
        "experts": experts, "fold_roles": sorted(REQUIRED_FOLD_ROLES),
        "stacking": {"weights": "learned_nonnegative"},
        "path_forecast": {"implemented": True, "sample_count": 20000, "endpoint_forced_to_actual": False},
    }


def test_algorithmic_runtime_audit_passes_compliant_registry() -> None:
    assert audit_runtime_contract(CONTRACT, compliant_runtime())["pass"]


def test_known_v6_style_mismatches_are_detected() -> None:
    runtime = compliant_runtime()
    runtime["experts"]["E2"]["objective"] = "quantile_proxy"
    runtime["experts"]["E7"]["full_trajectory_required"] = False
    runtime["stacking"]["weights"] = "fixed"
    runtime["path_forecast"]["implemented"] = False
    codes = {row["code"] for row in audit_runtime_contract(CONTRACT, runtime)["findings"]}
    assert {"e2_objective_mismatch", "e7_missing_full_trajectory", "fixed_stacking_prohibited", "path_implementation_missing"} <= codes
