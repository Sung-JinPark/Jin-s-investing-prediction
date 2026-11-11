"""daily6m v2 contract r3 (2026-11-12, pre-outcome): tolerance-equivalent pairing derived from recorded run fields."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from ai_fc.timeseries_daily6m_v2 import contracts as C
from ai_fc.timeseries_daily6m_v2 import pipeline as V

ROOT = Path(__file__).resolve().parents[2]
TRIGGER_RUN = "daily6m-v2-9cc54ec98c2d1051208c45de"
R2_CONTRACT_HASH = "ddf1d6f33289e9c3898d083759326dd625876c44b4d3560f42873b4627d19958"
RUNTIME = {"numpy": "2.5.4", "scipy": "1.18.1", "pandas": "2.3.3", "statsmodels": "0.14.6", "python": "3.12.16",
           "exchange_calendars": "4.13.2"}


def evidence_run(*, coefficient_gap=4.2e-16, band_gap=8.0e-16, scaler_equal=True, code_equal=True, runtime=None,
                 reason="path_hash", grid=True) -> dict:
    structure = {"equal": scaler_equal, "differing_keys": [] if scaler_equal else ["scaler"], "max_abs_scaler_diff": 0.0}
    return {
        "pair_status": "inputs_differ", "inputs_differ_reason": reason,
        "reduction_identity": {
            "v1_code_hash_equal": code_equal, "block_length": 21, "ewma_lambda": 0.97,
            "runtime": dict(RUNTIME) if runtime is None else runtime, "v1_runtime": dict(RUNTIME),
            "magnitude": {"max_abs_log_band_diff": band_gap,
                          "max_abs_coefficient_diff": {"expanding": coefficient_gap, "rolling": coefficient_gap}},
            "input_evidence": {"anchor_equal": True, "fit_structure": {"expanding": structure, "rolling": dict(structure)},
                               "lineage": {"market_rows_same_observations": True, "factor_rows_equal_excluding_materialization": True}},
        },
        "projection_exogenous": {"source": "v1_run_model_config", "values": [0.6, -4.2, 0.0]},
        "v1_reference": {"block_length": 21, "ewma_lambda": 0.97, "issuance_exogenous": [0.6, -4.2, 0.0],
                         "quantile_grid": [[0.0]] if grid else None},
    }


def test_ulp_gap_is_tolerance_equivalent():
    result = C.classify_pair(evidence_run(coefficient_gap=1e-16, band_gap=1e-16))
    assert result["status"] == "tolerance_equivalent" and result["failed"] == [] and result["tolerance_abs"] == 1e-12


def test_tolerance_boundary_is_inclusive_and_1e9_is_excluded():
    assert C.classify_pair(evidence_run(coefficient_gap=1e-12, band_gap=1e-12))["status"] == "tolerance_equivalent"
    over = C.classify_pair(evidence_run(coefficient_gap=1e-9))
    assert over["status"] == "excluded" and over["failed"] == ["coefficients_within_tolerance"]
    band = C.classify_pair(evidence_run(band_gap=1e-9))
    assert band["failed"] == ["bands_within_tolerance"]
    for bad in (float("nan"), float("inf"), None, True):
        assert "coefficients_within_tolerance" in C.classify_pair(evidence_run(coefficient_gap=bad))["failed"]


def test_code_runtime_reason_structure_and_missing_grid_each_exclude():
    assert C.classify_pair(evidence_run(code_equal=False))["failed"] == ["v1_code_hash_equal"]
    assert C.classify_pair(evidence_run(runtime={**RUNTIME, "numpy": "2.4.3"}))["failed"] == ["runtime_equal"]
    assert C.classify_pair(evidence_run(reason="v1_code_hash"))["failed"] == ["path_hash_only"]
    assert C.classify_pair(evidence_run(scaler_equal=False))["failed"] == ["fit_structure_equal"]
    assert C.classify_pair(evidence_run(grid=False))["failed"] == ["v1_reference_grid_recorded"]
    identical = C.classify_pair({**evidence_run(), "pair_status": "identical_inputs", "inputs_differ_reason": None})
    assert identical == {"rule": "r3", "status": "identical_inputs", "tolerance_abs": 1e-12, "criteria": None, "failed": []}


def test_missing_evidence_is_never_assumed():
    run = evidence_run()
    del run["reduction_identity"]["input_evidence"]
    failed = C.classify_pair(run)["failed"]
    assert failed == ["fit_structure_equal", "anchor_equal", "factor_rows_equal_excluding_materialization", "market_rows_same_observations"]


def test_fit_structure_and_lineage_comparisons():
    fit = {"lag": 1, "alpha": 100.0, "endogenous": ["a"], "exogenous": ["b"], "predictors": ["a_lag1", "b"], "residual_count": 9,
           "train_start": 0, "train_end": 10, "scaler": {"median": [0.1, 0.2], "iqr": [1.0, 2.0]}, "coefficients": [[1.0]]}
    assert C.fit_structure_comparison(fit, copy.deepcopy(fit))["equal"] is True
    near = copy.deepcopy(fit)
    near["scaler"]["iqr"][1] += 2e-16
    assert C.fit_structure_comparison(fit, near)["equal"] is True
    far = copy.deepcopy(fit)
    far["scaler"]["median"][0] += 1e-9
    assert C.fit_structure_comparison(fit, far)["differing_keys"] == ["scaler"]
    assert C.fit_structure_comparison(fit, {**fit, "train_start": 1})["differing_keys"] == ["train_start"]
    assert C.fit_structure_comparison(fit, None)["equal"] is False
    market = [{"session": "2026-11-10", "series_id": "VIXCLS", "observation_time": "2026-11-10", "carried": False,
               "source_id": "alfred", "data_grade": "native_pit"}]
    factor = [{"session": "2026-11-10", "content_hash": "c", "cache_materialized_at": "2026-11-11T16:50:00+00:00"}]
    captured = [{**market[0], "source_id": "cboe_vix_archive", "data_grade": "captured_forward"}]
    other_mtime = [{**factor[0], "cache_materialized_at": "2026-11-11T11:17:54+00:00"}]
    view = C.lineage_comparison({"market_rows": market, "factor_rows": factor}, {"market_rows": captured, "factor_rows": other_mtime})
    assert view["market_rows_same_observations"] and view["factor_rows_equal_excluding_materialization"]
    assert view["market_rows_metadata_differ"] == 1
    carried = [{**market[0], "observation_time": "2026-11-09", "carried": True}]
    assert C.lineage_comparison({"market_rows": market, "factor_rows": factor},
                                {"market_rows": carried, "factor_rows": factor})["market_rows_same_observations"] is False
    assert C.lineage_comparison({"market_rows": market, "factor_rows": factor}, None)["recorded"] is False


def test_r3_contract_is_r2_plus_declared_additions_only():
    """Removing exactly the r3 additions reproduces the registered r2 frozen hash (nothing else moved)."""
    contract = C.load_contract(ROOT)
    r2 = copy.deepcopy(contract)
    r2.pop("revisions")
    r2["pairing"].pop("tolerance_equivalence")
    r2["approvals"].pop("revision_receipts")
    r2["evaluation"]["primary_sample"] = "pair_status_identical_inputs"
    assert C.frozen_hash(r2) == R2_CONTRACT_HASH == C.PRIOR_IDENTITIES[0]["contract_hash"]
    r3 = next(item for item in contract["revisions"] if item["revision"] == "r3")
    assert r3["pre_outcome_evidence"]["v2_resolution_rows"] == 0 and r3["pre_outcome_evidence"]["v2_verdict_rows"] == 0
    assert contract["pairing"]["tolerance_equivalence"]["tolerance_abs"] == C.PAIR_TOLERANCE == 1e-12


def test_r3_receipt_states_an_invariant_not_a_row_count_condition():
    """Review (merge precondition): the receipt's validity is the outcome-independent no-reclassification
    invariant (re-checked by verify), while the 0-row counts are the evidence recorded at revision time."""
    rows = [json.loads(line) for line in (ROOT / C.APPROVAL_LEDGER).read_text(encoding="utf-8").splitlines() if line.strip()]
    receipt = next(row for row in rows if row["receipt_id"] == "daily6m-v2-approval:U4:2026-11-12:contract-r3")
    assert receipt["approval_form"] == "delegated_bundle_instruction" and receipt["literal_template_match"] is False
    assert not any("상태에서만 유효" in condition for condition in receipt["conditions"])
    assert any("재분류하지 않는다" in condition for condition in receipt["conditions"])
    r3 = next(item for item in C.load_contract(ROOT)["revisions"] if item["revision"] == "r3")
    assert "재분류하지 않는다" in r3["validity_invariant"]


def test_contract_loader_rejects_r3_tampering(tmp_path):
    base = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    edits = (
        lambda c: c["pairing"]["tolerance_equivalence"].__setitem__("tolerance_abs", 1e-9),
        lambda c: c["pairing"]["tolerance_equivalence"]["criteria"].remove("runtime_equal"),
        lambda c: c["evaluation"].__setitem__("primary_sample", "pair_status_identical_inputs"),
        lambda c: c["revisions"][0]["prior_identity"].__setitem__("model_code_hash", "0" * 64),
        lambda c: c["revisions"][0]["pre_outcome_evidence"].__setitem__("v2_resolution_rows", 3),
        lambda c: c["revisions"][0]["pre_outcome_evidence"].__setitem__("v2_verdict_rows", 1),
        lambda c: c.pop("revisions"),
    )
    target = tmp_path / C.CONTRACT_RELATIVE
    target.parent.mkdir(parents=True)
    for edit in edits:
        contract = copy.deepcopy(base)
        edit(contract)
        target.write_text(yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
        with pytest.raises(C.Daily6mV2ContractError):
            C.load_contract(tmp_path)


def test_trigger_run_classification_is_fixed_from_its_recorded_fields():
    """Real data (immutable run file): the run that motivated r3 is excluded under r3 — no v1 grid, no input evidence."""
    path = ROOT / C.RUNS_RELATIVE / f"{TRIGGER_RUN}.json"
    if not path.exists():   # runs are append-only; absent only in a partial checkout
        pytest.skip("trigger run not present")
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["contract_hash"] == R2_CONTRACT_HASH and "pair_eligibility" not in run
    result = C.classify_pair(run)
    assert result["status"] == "excluded"
    assert result["failed"] == ["fit_structure_equal", "anchor_equal", "factor_rows_equal_excluding_materialization",
                                "market_rows_same_observations", "v1_reference_grid_recorded"]
    passed = [name for name, value in result["criteria"].items() if value]
    assert passed == ["path_hash_only", "v1_code_hash_equal", "runtime_equal", "selection_reused", "projection_exogenous_from_v1",
                      "coefficients_within_tolerance", "bands_within_tolerance"]
    magnitude = run["reduction_identity"]["magnitude"]
    assert max(magnitude["max_abs_coefficient_diff"].values()) < 1e-15 and magnitude["max_abs_log_band_diff"] < 1e-15
    assert C.ledger_pair_eligibility({"pair_status": run["pair_status"]}) == "excluded"   # same class as under r2


def test_every_recorded_run_still_loads_under_r3():
    """State-independent: each ledger row (r2 or r3 identity) loads with the current contract and code."""
    rows = V.read_chain(ROOT, C.FORECAST_LEDGER)
    contract_hash, code_hash = C.frozen_hash(C.load_contract(ROOT)), C.model_code_hash(ROOT)
    for row in rows:
        run = V.load_run(ROOT, row, contract_hash=contract_hash, code_hash=code_hash)
        assert V.run_identity(run, contract_hash=contract_hash, code_hash=code_hash) in ("current", "r2")
