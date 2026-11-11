"""Identity, paths, contract/constants loaders and code hash for the daily6m v2 shadow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_fc.timeseries_daily6m.contracts import canonical_hash  # same canonical JSON as the parent track

from .pairing import (  # noqa: F401 - the r3 rule is re-exported for callers and tests
    EQUIVALENCE_CRITERIA, FACTOR_VOLATILE_KEYS, FIT_STRUCTURE_KEYS, GRID_CRITERION, MARKET_OBSERVATION_KEYS,
    PAIR_RULE_REVISION, PAIR_TOLERANCE, PRIMARY_ELIGIBILITY, classify_pair, equivalence_criteria,
    fit_structure_comparison, ledger_pair_eligibility, lineage_comparison,
)

MODEL_ID = "research.nasdaq_daily6m_varx_v2"
MODEL_VERSION = 1
CONTRACT_ID = "timeseries_daily6m_v2"
CONTRACT_RELATIVE = Path("data/contracts/timeseries_daily6m_v2.yaml")
STORE_RELATIVE = Path("data/timeseries_daily6m_v2")
FORECAST_LEDGER = STORE_RELATIVE / "ledgers/forecasts.jsonl"
RESOLUTION_LEDGER = STORE_RELATIVE / "ledgers/resolutions.jsonl"
VERDICT_LEDGER = STORE_RELATIVE / "ledgers/verdicts.jsonl"
APPROVAL_LEDGER = STORE_RELATIVE / "ledgers/approvals.jsonl"
RUNS_RELATIVE = STORE_RELATIVE / "runs"
SCORECARD_RELATIVE = STORE_RELATIVE / "derived/scorecard.json"
CONSTANTS_RELATIVE = STORE_RELATIVE / "prereg/design_constants_v1.json"
REPORT_RELATIVE = STORE_RELATIVE / "prereg/design_report_v1.json"
OUTPUTS_RELATIVE = Path("outputs/timeseries_daily6m_v2")
DESIGN_WINDOW = ("2007-01-01", "2014-12-31")
ARMS = ("main", "term_structure", "zero_drift")
ARM_INDEX = {"main": 0, "term_structure": 1, "zero_drift": 2}
PATH_COUNT = 20000
PROBABILITY_SPACE = "research_timeseries_daily6m_v2_shadow"
PARENT_CONTRACT_HASH = "53f023f79829778c37bfc460698ff5e2224894b9ec7ecfd03f2d18fddeeb83dc"
PARENT_MODEL_CODE_HASH_AT_REGISTRATION = "c3fe06c1fbe3b0862e299f8eeb0a2018f8f35940f2fe12be06366905b2fda539"
LEAD_MULTIPLIER_REJECTED = "rejected_design_window_evidence_insufficient"
FAMILY = ("main_h1", "zero_drift_h1", "main_h5", "term_structure_h5", "zero_drift_h5")
FOOTNOTE = "연구 섀도 · 비공개 · 참고 의견, 매매 신호 아님"


class Daily6mV2ContractError(RuntimeError):
    """The v2 shadow cannot satisfy its preregistered contract."""


def frozen_hash(contract: dict[str, Any]) -> str:
    return canonical_hash(contract)


EXPECTED_SELECTION = {
    "candidates": {"block": [5, 10, 21], "ewma_lambda": [0.94, 0.97]},
    "validation": {"origins": 52, "paths": 1000, "horizon": 21, "minimum_rows": 500, "fallback": [10, 0.97],
                   "origin_rule": "anchored_position_grid_mod_21"},
    "scale_used_in_selection": "fresh_without_term_structure",
    "bootstrap": "crn_predrawn_starts_and_uniforms_restart_if_u_lt_1_over_block",
    "common_random_numbers": {"seed": 20261111, "rng_key": ["seed", "replicate", "validation_origin_index"],
                              "replicates": 8, "shared_across": "all_six_candidates"},
    "hysteresis": {"incumbent": "previous_v2_run_selection_in_ledger_order", "first_run_incumbent": [10, 0.97],
                   "switch_if": "mean_paired_margin_gt_1.0_mc_sd", "mc_sd": "sd_over_replicates_div_sqrt_R"},
}

EXPECTED_EVALUATION_SUBSET = {
    "resolution_source": "v1_resolutions_ledger_active_rows",
    "primary_sample": "pair_eligibility_identical_inputs_or_tolerance_equivalent",   # r3 (was pair_status_identical_inputs)
    "differences": "paired_same_run_arm_minus_v1",
    "bootstrap": {"kind": "iid", "replicates": 9999, "rng_key": [20261111, "lead", "arm_index"], "ci": "percentile_90"},
    "family": list(FAMILY),
    "multiplicity": "holm_alpha_0.05_one_sided_m5",
}
# thinned-sample thresholds per lead: h1/h5 from evaluation.inference_sample.n, h21 from publication.promotion.requires
THRESHOLDS = {1: 50, 5: 50, 21: 30}
EXPECTED_INFERENCE_SAMPLE = {
    "design": "non_overlapping_thinned_fixed_lead",
    "phase_origin": "first_v2_forecast_origin_session",
    "eligible_origin": "xnas_session_index_mod_lead_eq_0",
    "representative_run": "earliest_issued_v2_run_per_origin",
    "missing_or_inputs_differ": "counted_not_replaced",
    "sample": "first_n_scored_eligible_origins_in_origin_order",
    "n": {"h1": THRESHOLDS[1], "h5": THRESHOLDS[5]},
}
EXPECTED_VERDICT_TIMING = {
    "h1_p_values": "frozen_once_when_h1_sample_first_reaches_50",
    "family_verdict": "once_when_h5_sample_first_reaches_50_using_frozen_h1_p_values",
    "interim_verdicts": "none_all_pre_threshold_numbers_descriptive",
    "pre_threshold_p_values_published": False,
    "ledger": "data/timeseries_daily6m_v2/ledgers/verdicts.jsonl",
    "one_row_per_kind": True,
    "later_v1_revisions_change_verdict": False,
}
EXPECTED_LABELS = {"superior": "holm_reject_and_negative_mean", "inferior": "ci90_lower_gt_0_disclosed",
                   "indistinguishable": "otherwise"}
EXPECTED_P_VALUE = "one_sided_share_of_bootstrap_means_ge_0_plus_one_over_B_plus_one"
EXPECTED_SECONDARY = ("coverage80_abs_error", "qs5_band_crosscheck", "brier_daily_up")

# ---------------------------------------------------------------- r3 pairing eligibility (pre-outcome amendment, 2026-11-12)
# The rule itself (thresholds, criteria, classify_pair) lives in pairing.py, which is part of the gating
# model_code_hash; this module re-exports it (import at the top) and pins the contract text and the prior
# (r2) run identity.
R3_UNCHANGED = ("evaluation.metrics", "evaluation.inference_sample", "evaluation.family", "evaluation.multiplicity",
                "evaluation.bootstrap", "evaluation.p_value", "evaluation.labels", "evaluation.verdict_timing",
                "publication.promotion", "design_constants", "model")
# Runs issued under the registered r2 contract stay loadable: they never record pair_eligibility and r3
# classifies them from their recorded fields (an r2 inputs_differ run never stored a v1 grid -> excluded).
PRIOR_IDENTITIES = (
    {"revision": "r2", "contract_hash": "ddf1d6f33289e9c3898d083759326dd625876c44b4d3560f42873b4627d19958",
     "model_code_hash": "441c4984029aab1fedde25459305d38820566a38edd1ab55af6753323a55b8b0"},
)
EXPECTED_TOLERANCE_EQUIVALENCE = {
    "rule_id": PAIR_RULE_REVISION,
    "applies_to": "pair_status_inputs_differ_reason_path_hash",
    "pair_status": "unchanged_recorded_value",
    "tolerance_abs": PAIR_TOLERANCE,
    "criteria": list(EQUIVALENCE_CRITERIA),
    "status": {"identical_inputs": "pair_status_identical_inputs",
               "tolerance_equivalent": "all_criteria_true_and_v1_reference_grid_recorded",
               "excluded": "otherwise"},
    "v1_reference_grid": "reconstructed_grid_rounded_10dp_stored_only_when_all_criteria_true",
    "record": {"run": "pair_eligibility", "forecast_ledger": "pair_eligibility", "resolution_ledger": "pair_eligibility_when_run_records_it"},
    "runs_without_pair_eligibility": "prior_identity_only_classified_from_recorded_fields_no_posthoc_recompute",
    "lineage_metadata_differences": "diagnostic_only",
}


def load_contract(root: Path) -> dict[str, Any]:
    import yaml
    path = root / CONTRACT_RELATIVE
    with path.open(encoding="utf-8") as handle:
        contract = yaml.safe_load(handle)
    if not isinstance(contract, dict):
        raise Daily6mV2ContractError("daily6m v2 contract must be a mapping")
    identity = {"contract_id": CONTRACT_ID, "model_id": MODEL_ID, "model_version": MODEL_VERSION,
                "status": "shadow_research_unpublished"}
    if any(contract.get(key) != value for key, value in identity.items()):
        raise Daily6mV2ContractError("daily6m v2 contract identity mismatch")
    parent = contract.get("parent") or {}
    if (parent.get("contract_id") != "timeseries_daily6m_v1" or parent.get("contract_hash") != PARENT_CONTRACT_HASH
            or parent.get("model_code_hash_at_registration") != PARENT_MODEL_CODE_HASH_AT_REGISTRATION
            or parent.get("parent_bytes_changed") is not False or parent.get("parent_display_unchanged") is not True):
        raise Daily6mV2ContractError("daily6m v2 parent pin mismatch")
    target = contract.get("target") or {}
    if (target.get("series_id") != "NASDAQCOM" or target.get("exchange") != "XNAS" or target.get("calendar_months") != 6
            or target.get("calendar_end_rule") != "preserve_month_end_else_same_day_clamped"):
        raise Daily6mV2ContractError("daily6m v2 target differs from the parent track")
    probability = contract.get("probability_contract") or {}
    if (probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]
            or probability.get("space") != PROBABILITY_SPACE
            or any(probability.get(key) is not False for key in ("combine_with_v1", "combine_with_official_forecasts", "combine_with_scenarios"))):
        raise Daily6mV2ContractError("daily6m v2 probability space or no-combination rule mismatch")
    model = contract.get("model") or {}
    if (model.get("path_count") != PATH_COUNT or model.get("seed_rule") != "v1_seed_crn"
            or model.get("inherited_from_v8") != "none"
            or model.get("projection_exogenous") != "v1_run_model_config_issuance_exogenous"
            or model.get("fit_call_path") != "ai_fc.timeseries_daily6m.model.select_ridge_varx_v2"
            or model.get("distribution_selection") != EXPECTED_SELECTION
            or model.get("simulation_bootstrap") != "sealed_v2_stationary_bootstrap_batch_same_consumption_order"
            or model.get("lead_width_multiplier") != LEAD_MULTIPLIER_REJECTED
            or sorted((model.get("arms") or {}).keys()) != sorted(ARMS)
            or model.get("learned_calibration_from_live") != "prohibited_until_unique_resolutions_100"):
        raise Daily6mV2ContractError("daily6m v2 model coordinates differ from the implementation")
    term = model.get("variance_term_structure") or {}
    precedent = term.get("mechanism_precedent") or {}
    if (term.get("long_run_rule") != "slow_ewma_0.996" or term.get("persistence_source") != "design_constants.persistence_by_column"
            or precedent.get("grid") != "B1_volatility_term_structure"
            or precedent.get("dev_runs") != ["tsv8-exp-92d143bb7d6754e673c7", "tsv8-exp-b3d95536b64d0aa07e20"]):
        raise Daily6mV2ContractError("daily6m v2 term structure or V8 B1 precedent disclosure mismatch")
    evaluation = contract.get("evaluation") or {}
    if any(evaluation.get(key) != value for key, value in EXPECTED_EVALUATION_SUBSET.items()):
        raise Daily6mV2ContractError("daily6m v2 evaluation rule differs from the implementation")
    # whole-block comparison (review N4): every rule the scorecard code implements is matched, not a subset
    if (evaluation.get("inference_sample") != EXPECTED_INFERENCE_SAMPLE
            or evaluation.get("verdict_timing") != EXPECTED_VERDICT_TIMING
            or evaluation.get("labels") != EXPECTED_LABELS
            or evaluation.get("p_value") != EXPECTED_P_VALUE
            or (evaluation.get("metrics") or {}).get("primary") != "crps_quantile_grid_39_trapezoid_log_return"
            or (evaluation.get("metrics") or {}).get("secondary") != list(EXPECTED_SECONDARY)):
        raise Daily6mV2ContractError("daily6m v2 thinned-sample single-look rule mismatch")
    publication = contract.get("publication") or {}
    if (publication.get("site_display") != "none" or publication.get("dashboard_payload") != "none"
            or publication.get("official_ledger_write") is not False or publication.get("automatic_promotion") is not False
            or publication.get("predictive_validation") != "not_established"
            or f"h21_thinned_n{THRESHOLDS[21]}_ci90_lower_le_0" not in ((publication.get("promotion") or {}).get("requires") or [])):
        raise Daily6mV2ContractError("daily6m v2 must stay unpublished and unpromoted")
    constants = contract.get("design_constants") or {}
    if constants.get("path") != CONSTANTS_RELATIVE.as_posix() or not isinstance(constants.get("canonical_hash"), str):
        raise Daily6mV2ContractError("daily6m v2 design constants pin missing")
    # r3 (2026-11-12): tolerance pairing rule and the prior (r2) run identity it keeps loadable
    if (contract.get("pairing") or {}).get("tolerance_equivalence") != EXPECTED_TOLERANCE_EQUIVALENCE:
        raise Daily6mV2ContractError("daily6m v2 r3 tolerance pairing rule differs from the implementation")
    revisions = contract.get("revisions") or []
    r3 = [item for item in revisions if isinstance(item, dict) and item.get("revision") == PAIR_RULE_REVISION]
    evidence = (r3[0].get("pre_outcome_evidence") or {}) if len(r3) == 1 else {}
    if (len(r3) != 1 or [r3[0].get("prior_identity")] != [dict(item) for item in PRIOR_IDENTITIES]
            or evidence.get("v2_resolution_rows") != 0 or evidence.get("v2_verdict_rows") != 0
            or r3[0].get("unchanged") != list(R3_UNCHANGED)):
        raise Daily6mV2ContractError("daily6m v2 r3 revision block (prior identity, pre-outcome evidence) mismatch")
    return contract


def load_constants(root: Path, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = load_contract(root) if contract is None else contract
    constants = json.loads((root / CONSTANTS_RELATIVE).read_text(encoding="utf-8"))
    if canonical_hash(constants) != contract["design_constants"]["canonical_hash"]:
        raise Daily6mV2ContractError("daily6m v2 design constants hash differs from the contract pin")
    if constants.get("long_run_rule", {}).get("registered") != "slow_ewma_0.996" or "lead_multipliers" in constants:
        raise Daily6mV2ContractError("daily6m v2 design constants differ from the registered rule")
    return constants


# Gating identity (B2, 2026-11-11 review; widened by r3, 2026-11-12): the files whose
# bytes can change a forecast number OR which runs enter the primary sample.  pairing.py
# decides whether a run stores the reconstructed v1 grid (input of the primary metric
# v1_crps39) and its pair_eligibility, so a more lenient edit there must not admit new
# runs silently — it is gated like the kernel.  load_run refuses a run whose
# model_code_hash differs from this, so an edit here needs a new contract.  Orchestration
# files (contracts, pipeline, scorecard) are hashed separately as non-gating diagnostics:
# resolution replay (score_row) and verdict replay (recompute_verdict) already re-derive
# every stored number byte for byte, and validate_run replays classify_pair, so a comment
# or logging edit must not stop the track.
NUMERICAL_CODE_PATHS = (
    "src/ai_fc/timeseries_daily6m_v2/kernel.py",
    "src/ai_fc/timeseries_daily6m_v2/model.py",
    "src/ai_fc/timeseries_daily6m_v2/pairing.py",
    "src/ai_fc/timeseries/model.py",
    "src/ai_fc/timeseries/backtest.py",
    "src/ai_fc/timeseries_v2/model.py",
)
CODE_PATHS = NUMERICAL_CODE_PATHS  # the run field ``model_code_hash`` covers exactly these files
ORCHESTRATION_CODE_PATHS = (
    "src/ai_fc/timeseries_daily6m_v2/contracts.py",
    "src/ai_fc/timeseries_daily6m_v2/pipeline.py",
    "src/ai_fc/timeseries_daily6m_v2/scorecard.py",
)
SCORECARD_CODE_PATH = "src/ai_fc/timeseries_daily6m_v2/scorecard.py"
_PACKAGE_REPO_ROOT = Path(__file__).resolve().parents[3]


def _normalized_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def model_code_hash(root: Path) -> str:
    """Numerical v2 files plus the sealed V2 kernel they import — never the v1 files (pinned separately per run)."""
    digest = hashlib.sha256()
    for relative in NUMERICAL_CODE_PATHS:
        name = relative.encode("utf-8")
        body = _normalized_bytes(root / relative)
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def orchestration_code_hashes(root: Path | None = None) -> dict[str, str]:
    """Non-gating diagnostic: sha256 (LF-normalized) of each orchestration file actually executing."""
    base = _PACKAGE_REPO_ROOT if root is None else root
    return {relative: hashlib.sha256(_normalized_bytes(base / relative)).hexdigest() for relative in ORCHESTRATION_CODE_PATHS}


def scorecard_code_hash(root: Path | None = None) -> str:
    """Non-gating diagnostic recorded on verdict rows: the verdict-computing code at record time."""
    return orchestration_code_hashes(root)[SCORECARD_CODE_PATH]
