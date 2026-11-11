"""Thinned-sample single-look verdicts and descriptive scorecard for the daily6m v2 shadow.

Inference (labels) uses only non-overlapping thinned samples: for lead k the
eligible origins are XNAS sessions with phase index i(o) mod k == 0, counted
from the first v2 origin.  Missing origins and runs outside the primary sample
(r3 pair_eligibility not identical_inputs / tolerance_equivalent) are counted,
never replaced.  The first n_k scored eligible origins (in origin order) form
the sample; each p value is computed once, when its sample first reaches n_k,
and is frozen in the append-only verdict ledger.  Every other number here is
descriptive, and no p value is published before its threshold.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .contracts import (
    ARM_INDEX, ARMS, PAIR_RULE_REVISION, PRIMARY_ELIGIBILITY, SCORECARD_RELATIVE, THRESHOLDS, VERDICT_LEDGER, canonical_hash,
    frozen_hash, ledger_pair_eligibility, load_contract, scorecard_code_hash,
)

SEED = 20261111
ALPHA = 0.05
BOOTSTRAP_REPLICATES = 9999
DESCRIPTIVE_LEADS = (63, 126)
FAMILY_TESTS = (("main", 1), ("zero_drift", 1), ("main", 5), ("term_structure", 5), ("zero_drift", 5))
H1_TESTS = (("main", 1), ("zero_drift", 1))
H5_TESTS = (("main", 5), ("term_structure", 5), ("zero_drift", 5))
BUCKETS = (("1-21", 1, 21), ("22-63", 22, 63), ("64-126", 64, 10 ** 6))
VERDICT_KINDS = ("h1_p_values_frozen", "family_verdict", "promotion_descriptive_h21")
COVERAGE_TARGET = 0.8
STALL_WARNING_SESSIONS = 10   # a blocking origin this many sessions past its lead-k target is reported (non-gating)
NON_GATING_VERDICT_FIELDS = ("scorecard_code_hash",)


def test_name(arm: str, lead: int) -> str:
    return f"{arm}_h{lead}"


# ---------------------------------------------------------------- statistics
def iid_bootstrap(values, *, lead: int, arm: str, replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ValueError("bootstrap needs finite paired differences")
    rng = np.random.default_rng([SEED, int(lead), ARM_INDEX[arm]])
    indexes = rng.integers(0, len(x), size=(replicates, len(x)))
    means = x[indexes].mean(axis=1)
    return {"n": int(len(x)), "mean": float(x.mean()),
            "ci90": [float(np.percentile(means, 5)), float(np.percentile(means, 95))],
            "p_better": float((1 + int(np.sum(means >= 0))) / (replicates + 1)), "_indexes": indexes}


def holm(p_values: dict[str, float], alpha: float = ALPHA) -> dict[str, bool]:
    ordered = sorted(p_values, key=lambda key: (p_values[key], key))
    rejected = {key: False for key in p_values}
    m = len(ordered)
    for rank, key in enumerate(ordered):
        if p_values[key] <= alpha / (m - rank):
            rejected[key] = True
        else:
            break
    return rejected


def label(rejected: bool, mean: float, ci90: list[float]) -> str:
    if rejected and mean < 0:
        return "superior"
    if ci90[0] > 0:
        return "inferior"
    return "indistinguishable"


def stationary_block_mean_ci(values, *, mean_block: int = 21, replicates: int = 2000, seed: int = SEED) -> list[float] | None:
    x = np.asarray(values, dtype=float)
    if len(x) < 2:
        return None
    rng = np.random.default_rng(seed)
    count = len(x)
    indexes = np.empty((replicates, count), dtype=np.int64)
    indexes[:, 0] = rng.integers(0, count, size=replicates)
    restart = rng.random((replicates, count)) < 1.0 / mean_block
    starts = rng.integers(0, count, size=(replicates, count))
    for step in range(1, count):
        indexes[:, step] = np.where(restart[:, step], starts[:, step], (indexes[:, step - 1] + 1) % count)
    means = x[indexes].mean(axis=1)
    return [float(np.percentile(means, 5)), float(np.percentile(means, 95))]


def secondary_metrics(series: dict[str, list[float]], indexes: np.ndarray) -> dict[str, dict[str, Any]]:
    """Secondary (CI only, no label) on the same thinned sample and the same bootstrap indexes as the primary.

    coverage80_abs_error = |cov_arm - 0.8| - |cov_v1 - 0.8| where cov is the hit share of the
    resampled origins (review B1: averaging per-origin |hit - 0.8| differences would instead give
    -0.6 * (cov_arm - cov_v1), a coverage difference that reads wider bands as better).
    Positive = the arm's 80% band is further from nominal coverage than v1's.
    """
    hit, v1_hit = (np.asarray(series[key], dtype=float) for key in ("hit80", "v1_hit80"))
    replicate_error = (np.abs(hit[indexes].mean(axis=1) - COVERAGE_TARGET)
                       - np.abs(v1_hit[indexes].mean(axis=1) - COVERAGE_TARGET))
    out = {"coverage80_abs_error": {
        "estimate": float(abs(hit.mean() - COVERAGE_TARGET) - abs(v1_hit.mean() - COVERAGE_TARGET)),
        "arm_coverage80": float(hit.mean()), "v1_coverage80": float(v1_hit.mean()),
        "ci90": [float(np.percentile(replicate_error, 5)), float(np.percentile(replicate_error, 95))]}}
    for name in ("qs5", "brier"):
        values = np.asarray(series[name], dtype=float)
        means = values[indexes].mean(axis=1)
        out[name] = {"estimate": float(values.mean()),
                     "ci90": [float(np.percentile(means, 5)), float(np.percentile(means, 95))]}
    return out


# ---------------------------------------------------------------- samples
def _sessions(first: str, last: str) -> list[str]:
    import exchange_calendars as xcals
    import pandas as pd
    if last < first:
        return []
    exchange = xcals.get_calendar("XNAS", start=(pd.Timestamp(first) - pd.Timedelta(days=7)).date().isoformat(),
                                  end=(pd.Timestamp(last) + pd.Timedelta(days=7)).date().isoformat())
    return [label.date().isoformat() for label in exchange.sessions_in_range(first, last)]


def _active(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    superseded = {row["supersedes"] for row in rows if row.get("supersedes")}
    return [row for row in rows if row["resolution_id"] not in superseded]


def build_index(forecasts: list[dict[str, Any]], resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    representative: dict[str, dict[str, Any]] = {}
    for row in forecasts:
        representative.setdefault(row["origin_session"], row)
    scored: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in _active(resolutions):
        scored[(row["v2_run_id"], row["arm"], int(row["lead"]))] = row
    phase = forecasts[0]["origin_session"] if forecasts else None
    sessions = _sessions(phase, max(representative)) if phase else []
    return {"phase_origin": phase, "sessions": sessions, "representative": representative, "scored": scored}


def thinned_sample(index: dict[str, Any], lead: int, n_target: int | None) -> dict[str, Any]:
    """Scan eligible origins in order; stop at the first pending origin or when n_target is reached.

    Stopping at the first pending origin keeps the sample a fixed prefix (a later resolution never
    changes it).  The blocking origin is reported so a permanently missing resolution is visible
    (review N2) instead of stalling the verdict silently.
    """
    origins, differences, missing, excluded, no_target, tolerance = [], {arm: [] for arm in ARMS}, 0, 0, 0, 0
    secondary = {arm: {"hit80": [], "v1_hit80": [], "qs5": [], "brier": []} for arm in ARMS}
    blocking_origin, blocking_position = None, None
    for position, origin in enumerate(index["sessions"]):
        if n_target is not None and len(origins) >= n_target:
            break
        if position % lead:
            continue
        run = index["representative"].get(origin)
        if run is None:
            missing += 1
            continue
        eligibility = ledger_pair_eligibility(run)
        if eligibility not in PRIMARY_ELIGIBILITY:   # r3: identical_inputs or tolerance_equivalent only
            excluded += 1
            continue
        if int(run["horizon_sessions"]) < lead:
            no_target += 1
            continue
        rows = {arm: index["scored"].get((run["forecast_id"], arm, lead)) for arm in ARMS}
        if any(row is None for row in rows.values()):
            blocking_origin, blocking_position = origin, position
            break
        origins.append(origin)
        tolerance += int(eligibility == "tolerance_equivalent")
        for arm, row in rows.items():
            differences[arm].append(float(row["crps39"]) - float(row["v1_crps39"]))
            secondary[arm]["hit80"].append(float(bool(row["hit80"])))
            secondary[arm]["v1_hit80"].append(float(bool(row["v1_hit80"])))
            secondary[arm]["qs5"].append(float(row["qs5"]) - float(row["v1_qs5"]))
            secondary[arm]["brier"].append(float(row["brier"]) - float(row["v1_brier"]))
    last_position = len(index["sessions"]) - 1
    return {"origins": origins, "differences": differences, "secondary": secondary,
            "n_missing": missing, "n_excluded": excluded, "n_no_target": no_target, "n_scored": len(origins),
            "n_tolerance_equivalent": tolerance,
            "n_pending_blocking": int(blocking_origin is not None), "blocking_origin": blocking_origin,
            "blocking_sessions_behind": None if blocking_position is None else last_position - blocking_position}


def stalled_scans(index: dict[str, Any]) -> list[str]:
    """Non-gating warnings: a thinned scan blocked long after its lead-k target should have resolved."""
    warnings = []
    for lead, n_target in THRESHOLDS.items():
        sample = thinned_sample(index, lead, n_target)
        behind = sample["blocking_sessions_behind"]
        if behind is not None and behind > lead + STALL_WARNING_SESSIONS:
            warnings.append(f"h{lead} thinned sample blocked at origin {sample['blocking_origin']} "
                            f"({behind} sessions behind the latest v2 origin) - verdict timing stalls until it resolves")
    return warnings


# ---------------------------------------------------------------- verdict rows
def _ledger_cut(forecasts, resolutions) -> dict[str, Any]:
    return {"forecasts_rows": len(forecasts), "resolutions_rows": len(resolutions),
            "last_content_hash": resolutions[-1]["content_hash"] if resolutions else None}


def _recorded_as_of(resolutions) -> str | None:
    from ai_fc.timeseries_daily6m import features as F
    return max((row["resolved_as_of"] for row in resolutions), key=lambda value: F.aware_time(value), default=None)


def _test_block(sample: dict[str, Any], arm: str, lead: int) -> dict[str, Any]:
    result = iid_bootstrap(sample["differences"][arm], lead=lead, arm=arm)
    result.pop("_indexes")
    return result


def _verdict_body(kind: str, forecasts, resolutions, contract_hash: str, frozen_h1: dict[str, Any] | None) -> dict[str, Any] | None:
    index = build_index(forecasts, resolutions)
    if kind == "h1_p_values_frozen":
        lead, tests = 1, H1_TESTS
    elif kind == "family_verdict":
        lead, tests = 5, H5_TESTS
    else:
        lead, tests = 21, tuple((arm, 21) for arm in ARMS)
    sample = thinned_sample(index, lead, THRESHOLDS[lead])
    if sample["n_scored"] < THRESHOLDS[lead]:
        return None
    by_test = {test_name(arm, test_lead): _test_block(sample, arm, test_lead) for arm, test_lead in tests}
    body: dict[str, Any] = {"schema_version": 1, "verdict_id": "daily6m-v2-verdict:" + kind, "kind": kind,
                            "recorded_as_of": _recorded_as_of(resolutions), "ledger_cut": _ledger_cut(forecasts, resolutions),
                            "phase_origin": index["phase_origin"], "lead": lead,
                            "sample_origin_hash": canonical_hash(sample["origins"]),
                            "n_missing": sample["n_missing"], "n_excluded": sample["n_excluded"],
                            "n_tolerance_equivalent": sample["n_tolerance_equivalent"], "pair_rule": PAIR_RULE_REVISION,
                            "contract_hash": contract_hash}
    if kind == "h1_p_values_frozen":
        body["by_test"] = by_test
        body["labels"] = None
    elif kind == "family_verdict":
        if frozen_h1 is None:
            return None
        family = {**{name: dict(value) for name, value in frozen_h1["by_test"].items()}, **by_test}
        rejected = holm({name: value["p_better"] for name, value in family.items()})
        body["by_test"] = family
        body["h1_source_verdict_hash"] = frozen_h1["content_hash"]
        body["holm"] = {"alpha": ALPHA, "m": len(family), "one_sided": True, "rejected": rejected}
        body["labels"] = {name: label(rejected[name], value["mean"], value["ci90"]) for name, value in family.items()}
    else:
        for value in by_test.values():
            value.pop("p_better", None)
            # inferiority not shown (CI90 lower <= 0); not a non-inferiority test with a margin (review N3)
            value["ci90_lower_le_0"] = value["ci90"][0] <= 0
        body["by_test"] = by_test
        body["labels"] = None
        body["note"] = "promotion input only — not a label; ci90_lower_le_0 means inferiority not shown, not non-inferiority"
    return body


def verdict_body_for_replay(row: dict[str, Any]) -> dict[str, Any]:
    """The recorded verdict minus chain hashes and non-gating diagnostics (scorecard code hash)."""
    return {key: value for key, value in row.items() if key not in ("previous_hash", "content_hash", *NON_GATING_VERDICT_FIELDS)}


def recompute_verdict(root: Path, row: dict[str, Any], *, forecasts, resolutions, contract) -> dict[str, Any] | None:
    cut = row["ledger_cut"]
    forecasts_cut = forecasts[:cut["forecasts_rows"]]
    resolutions_cut = resolutions[:cut["resolutions_rows"]]
    if (resolutions_cut[-1]["content_hash"] if resolutions_cut else None) != cut["last_content_hash"]:
        raise ValueError("verdict ledger cut no longer matches the resolution chain")
    frozen_h1 = None
    if row["kind"] == "family_verdict":
        from .pipeline import read_chain
        frozen_h1 = next((item for item in read_chain(root, VERDICT_LEDGER) if item["kind"] == "h1_p_values_frozen"), None)
    return _verdict_body(row["kind"], forecasts_cut, resolutions_cut, frozen_hash(contract), frozen_h1)


# ---------------------------------------------------------------- descriptive
def _primary_row(row: dict[str, Any]) -> bool:
    return ledger_pair_eligibility(row) in PRIMARY_ELIGIBILITY and row.get("v1_crps39") is not None


def _descriptive(index: dict[str, Any], resolutions) -> dict[str, Any]:
    active = [row for row in _active(resolutions) if _primary_row(row)]
    representative_ids = {row["forecast_id"] for row in index["representative"].values()}
    target: dict[str, Any] = {}
    for arm in ARMS:
        by_date: dict[str, list[tuple[float, float]]] = {}
        for row in active:
            if row["arm"] == arm:
                by_date.setdefault(row["date"], []).append((float(row["crps39"]), float(row["v1_crps39"])))
        dates = sorted(by_date)
        deltas = [float(np.mean([a for a, _ in by_date[d]]) - np.mean([b for _, b in by_date[d]])) for d in dates]
        total = sum(abs(value) for value in deltas)
        target[arm] = {"n_dates": len(dates), "mean_delta": float(np.mean(deltas)) if deltas else None,
                       "block_bootstrap_ci90": stationary_block_mean_ci(deltas),
                       "max_single_date_share": (max(abs(value) for value in deltas) / total) if total > 0 else None}
    buckets = {}
    for name, low, high in BUCKETS:
        buckets[name] = {}
        for arm in ARMS:
            values = [float(row["crps39"]) - float(row["v1_crps39"]) for row in active
                      if row["arm"] == arm and low <= int(row["lead"]) <= high]
            buckets[name][arm] = {"n_rows": len(values), "mean_delta": float(np.mean(values)) if values else None}
    differ = [row for row in _active(resolutions) if not _primary_row(row)]   # outside the primary sample (r3)
    sensitivity = {arm: {"n_rows": sum(1 for row in differ if row["arm"] == arm),
                         "qs5_mean_delta": (float(np.mean([float(row["qs5"]) - float(row["v1_qs5"]) for row in differ if row["arm"] == arm]))
                                            if any(row["arm"] == arm for row in differ) else None)} for arm in ARMS}
    twin = {}
    for left, right in (("main", "term_structure"), ("main", "zero_drift")):
        pairs: dict[tuple[str, str], dict[str, float]] = {}
        for row in active:
            if row["arm"] in (left, right):
                pairs.setdefault((row["v2_run_id"], row["date"]), {})[row["arm"]] = float(row["crps39"])
        values = [item[right] - item[left] for item in pairs.values() if left in item and right in item]
        twin[f"{right}_minus_{left}"] = {"n_rows": len(values), "mean": float(np.mean(values)) if values else None}
    return {"target_date_equal": target, "lead_buckets": buckets, "inputs_differ_sensitivity": sensitivity,
            "twin_contrasts": twin, "representative_runs": len(representative_ids),
            "note": "dependence underestimated (overlapping windows) — not a label basis; r1 rule false-rejection 0.29-0.46"}


def build_scorecard(forecasts, resolutions, verdicts) -> dict[str, Any]:
    index = build_index(forecasts, resolutions)
    thresholds_met = {row["lead"]: row for row in verdicts}
    thinned = {}
    for lead in (*THRESHOLDS, *DESCRIPTIVE_LEADS):
        n_target = THRESHOLDS.get(lead)
        sample = thinned_sample(index, lead, n_target)
        by_arm = {}
        for arm in ARMS:
            values = sample["differences"][arm]
            if values:
                result = iid_bootstrap(values, lead=lead, arm=arm)
                indexes = result.pop("_indexes")
                secondary = secondary_metrics(sample["secondary"][arm], indexes)
                result["p_better"] = None
                verdict = thresholds_met.get(lead)
                if verdict is not None and test_name(arm, lead) in verdict["by_test"]:
                    result["p_better"] = verdict["by_test"][test_name(arm, lead)].get("p_better")
                result["secondary"] = secondary
            else:
                result = {"n": 0, "mean": None, "ci90": None, "p_better": None, "secondary": None}
            by_arm[arm] = result
        thinned[f"h{lead}"] = {"n_target": n_target, "n_scored": sample["n_scored"], "n_missing": sample["n_missing"],
                               "n_excluded": sample["n_excluded"], "n_no_target": sample["n_no_target"],
                               "n_tolerance_equivalent": sample["n_tolerance_equivalent"],
                               "n_pending_blocking": sample["n_pending_blocking"], "blocking_origin": sample["blocking_origin"],
                               "blocking_sessions_behind": sample["blocking_sessions_behind"], "by_arm": by_arm}
    first_cut = min((row["ledger_cut"]["resolutions_rows"] for row in verdicts), default=None)
    post = 0 if first_cut is None else sum(1 for row in resolutions[first_cut:] if row.get("resolution_kind") == "correction")
    missing_pairs = sum(1 for origin in index["sessions"] if origin not in index["representative"])
    eligibility = {"identical_inputs": 0, "tolerance_equivalent": 0, "excluded": 0}
    for row in forecasts:
        eligibility[ledger_pair_eligibility(row)] += 1
    return {
        "schema_version": 1, "as_of": _recorded_as_of(resolutions), "phase_origin": index["phase_origin"],
        "n_runs": len(forecasts), "n_pairs_missing": missing_pairs,
        "pair_eligibility": {"rule": PAIR_RULE_REVISION, "runs": eligibility}, "thinned": thinned,
        "verdicts": [{key: value for key, value in row.items()} for row in verdicts],
        "descriptive": {**_descriptive(index, resolutions), "post_verdict_v1_revisions": post},
        "warnings": stalled_scans(index),
        "predictive_validation": "not_established", "rows_are_not_independent": True,
        "footnote": "연구 섀도 · 비공개 · 라벨은 verdicts 에서만 · 참고 의견, 매매 신호 아님",
    }


def write_scorecard(root: Path) -> dict[str, Any]:
    from .pipeline import _append, atomic_json, read_chain, writer_lock
    from .contracts import FORECAST_LEDGER, RESOLUTION_LEDGER
    with writer_lock(root):
        contract = load_contract(root)
        contract_hash = frozen_hash(contract)
        forecasts = read_chain(root, FORECAST_LEDGER)
        resolutions = read_chain(root, RESOLUTION_LEDGER)
        verdicts = read_chain(root, VERDICT_LEDGER)
        appended = []
        for kind in VERDICT_KINDS:
            if any(row["kind"] == kind for row in verdicts):
                continue
            frozen_h1 = next((row for row in verdicts if row["kind"] == "h1_p_values_frozen"), None)
            body = _verdict_body(kind, forecasts, resolutions, contract_hash, frozen_h1)
            if body is not None:
                # non-gating diagnostic (review B2): which verdict code produced the row; replay ignores it
                _append(root, VERDICT_LEDGER, {**body, "scorecard_code_hash": scorecard_code_hash()})
                appended.append(kind)
                verdicts = read_chain(root, VERDICT_LEDGER)
        scorecard = build_scorecard(forecasts, resolutions, verdicts)
        atomic_json(root / SCORECARD_RELATIVE, scorecard)
    return {"n_runs": scorecard["n_runs"], "n_pairs_missing": scorecard["n_pairs_missing"],
            "thinned_counts": {key: value["n_scored"] for key, value in scorecard["thinned"].items()},
            "verdicts_appended": appended}


def holm_reject_count(p_values: list[float]) -> int:
    return sum(holm({str(i): p for i, p in enumerate(p_values)}).values())


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)
