"""Thinned single-look verdicts on synthetic tmp ledgers (no assertion depends on real repository state, review B5)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_daily6m_v2 import contracts as C
from ai_fc.timeseries_daily6m_v2 import pipeline as V
from ai_fc.timeseries_daily6m_v2 import scorecard as S

REPO = Path(__file__).resolve().parents[2]


def sessions(count, start="2025-01-02"):
    import exchange_calendars as xcals
    exchange = xcals.get_calendar("XNAS", start="2024-12-01", end="2027-12-31")
    return [s.date().isoformat() for s in exchange.sessions if s.date().isoformat() >= start][:count]


def chain(rows):
    previous, out = None, []
    for row in rows:
        body = {**row, "previous_hash": previous}
        body["content_hash"] = C.canonical_hash(body)
        out.append(body)
        previous = body["content_hash"]
    return out


def forecast_rows(origins, *, differ=(), duplicate=(), skip=()):
    rows = []
    for i, origin in enumerate(origins):
        if origin in skip:
            continue
        rows.append({"forecast_id": f"run-{i}", "origin_session": origin, "paired_v1_forecast_id": f"v1-{i}",
                     "pair_status": "inputs_differ" if origin in differ else "identical_inputs", "horizon_sessions": 125})
        if origin in duplicate:
            rows.append({"forecast_id": f"run-{i}-rev", "origin_session": origin, "paired_v1_forecast_id": f"v1-{i}-rev",
                         "pair_status": "identical_inputs", "horizon_sessions": 125})
    return rows


def resolution_rows(forecasts, leads, *, diff=lambda run, arm, lead: 0.0, resolved="2026-01-01T00:00:00+00:00"):
    rows = []
    for run in forecasts:
        for lead in leads:
            for arm in C.ARMS:
                value = diff(run, arm, lead)
                rows.append({"resolution_id": f"{run['forecast_id']}:{arm}:{lead}", "v2_run_id": run["forecast_id"], "arm": arm,
                             "lead": lead, "date": f"d{lead}-{run['origin_session']}", "pair_status": run["pair_status"],
                             "crps39": 0.01 + value, "v1_crps39": None if run["pair_status"] != "identical_inputs" else 0.01,
                             "hit80": True, "v1_hit80": False, "qs5": 0.02, "v1_qs5": 0.021, "brier": 0.2, "v1_brier": 0.25,
                             "resolved_as_of": resolved, "supersedes": None, "resolution_kind": "initial"})
    return rows


def noise(run, arm, lead):
    rng = np.random.default_rng([int(run["forecast_id"].split("-")[1]), lead, C.ARM_INDEX[arm]])
    return float(rng.normal(-0.002, 0.004))


def test_thinning_counts_missing_excluded_and_first_run_per_origin():
    days = sessions(30)
    forecasts = forecast_rows(days, differ={days[10]}, duplicate={days[0]}, skip={days[5]})
    resolutions = resolution_rows(forecasts, (1, 5))
    index = S.build_index(forecasts, resolutions)
    assert index["phase_origin"] == days[0] and index["representative"][days[0]]["forecast_id"] == "run-0"
    sample = S.thinned_sample(index, 5, 50)
    assert sample["origins"] == [days[i] for i in (0, 15, 20, 25)]
    assert sample["n_missing"] == 1 and sample["n_excluded"] == 1
    assert S.thinned_sample(index, 1, None)["n_scored"] == 28
    pending = S.thinned_sample(S.build_index(forecasts, resolution_rows(forecasts[:12], (1,))), 1, 50)
    assert (pending["n_scored"], pending["n_missing"], pending["n_excluded"]) == (10, 1, 1)  # forecasts[:12] holds the duplicate revision of days[0]


def test_holm_examples():
    assert S.holm_reject_count([0.005, 0.01, 0.02, 0.03, 0.04]) == 2
    assert S.holm_reject_count([0.009] * 5) == 5
    rejected = S.holm({"a": 0.005, "b": 0.01, "c": 0.02, "d": 0.03, "e": 0.04})
    assert rejected == {"a": True, "b": True, "c": False, "d": False, "e": False}


def test_iid_bootstrap_definition_and_determinism():
    x = np.random.default_rng(1).normal(-0.001, 0.01, 50)
    result = S.iid_bootstrap(x, lead=5, arm="term_structure", replicates=999)
    again = S.iid_bootstrap(x, lead=5, arm="term_structure", replicates=999)
    assert result["p_better"] == again["p_better"] and result["ci90"] == again["ci90"]
    rng = np.random.default_rng([20261111, 5, 1])
    means = x[rng.integers(0, 50, size=(999, 50))].mean(axis=1)
    assert result["p_better"] == (1 + int(np.sum(means >= 0))) / 1000
    assert result["ci90"] == [float(np.percentile(means, 5)), float(np.percentile(means, 95))]


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "repo"
    (root / C.CONTRACT_RELATIVE).parent.mkdir(parents=True)
    (root / C.CONTRACT_RELATIVE).write_text((REPO / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"), encoding="utf-8")
    return root


def write_ledgers(root, forecasts, resolutions):
    for relative, rows in ((C.FORECAST_LEDGER, forecasts), (C.RESOLUTION_LEDGER, resolutions)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in chain(rows)), encoding="utf-8")


def test_single_look_h1_freeze_and_family_verdict(root):
    days = sessions(260)
    forecasts = forecast_rows(days)
    h1 = resolution_rows(forecasts, (1,), diff=noise)
    write_ledgers(root, forecasts, h1[:49 * 3])
    result = S.write_scorecard(root)
    card = json.loads((root / C.SCORECARD_RELATIVE).read_text(encoding="utf-8"))
    assert result["verdicts_appended"] == [] and not (root / C.VERDICT_LEDGER).exists()
    assert card["thinned"]["h1"]["n_scored"] == 49 and card["thinned"]["h1"]["by_arm"]["main"]["p_better"] is None
    write_ledgers(root, forecasts, h1[:50 * 3])
    assert S.write_scorecard(root)["verdicts_appended"] == ["h1_p_values_frozen"]
    frozen = V.read_chain(root, C.VERDICT_LEDGER)
    assert len(frozen) == 1 and frozen[0]["labels"] is None and set(frozen[0]["by_test"]) == {"main_h1", "zero_drift_h1"}
    before = (root / C.VERDICT_LEDGER).read_bytes()
    # the 51st resolution never alters the frozen row or its sample
    write_ledgers(root, forecasts, h1[:51 * 3])
    S.write_scorecard(root)
    assert (root / C.VERDICT_LEDGER).read_bytes() == before
    # h5 reaches 50 thinned origins (250 sessions) -> one family verdict using the frozen h1 p values
    rows = h1 + resolution_rows(forecasts[:250], (5,), diff=noise)
    write_ledgers(root, forecasts, rows)
    assert S.write_scorecard(root)["verdicts_appended"] == ["family_verdict"]
    verdicts = V.read_chain(root, C.VERDICT_LEDGER)
    family = verdicts[1]
    assert family["kind"] == "family_verdict" and family["holm"]["m"] == 5
    assert family["by_test"]["main_h1"] == frozen[0]["by_test"]["main_h1"]
    assert family["h1_source_verdict_hash"] == frozen[0]["content_hash"]
    assert "term_structure_h1" not in family["by_test"]
    assert set(family["labels"].values()) <= {"superior", "inferior", "indistinguishable"}
    assert S.write_scorecard(root)["verdicts_appended"] == []
    # verdict replay from the ledger cut reproduces both rows byte for byte
    contract = C.load_contract(root)
    resolutions = V.read_chain(root, C.RESOLUTION_LEDGER)
    for row in verdicts:
        assert row["scorecard_code_hash"] == C.scorecard_code_hash()      # non-gating diagnostic, excluded from replay
        body = {k: v for k, v in row.items() if k not in ("previous_hash", "content_hash", "scorecard_code_hash")}
        assert S.verdict_body_for_replay(row) == body
        assert S.recompute_verdict(root, row, forecasts=V.read_chain(root, C.FORECAST_LEDGER), resolutions=resolutions, contract=contract) == body


def test_post_verdict_revisions_are_counted_not_applied(root):
    days = sessions(60)
    forecasts = forecast_rows(days)
    rows = resolution_rows(forecasts[:50], (1,), diff=noise)
    write_ledgers(root, forecasts, rows)
    S.write_scorecard(root)
    before = (root / C.VERDICT_LEDGER).read_bytes()
    correction = {**rows[0], "resolution_id": rows[0]["resolution_id"] + ":fix", "supersedes": rows[0]["resolution_id"],
                  "resolution_kind": "correction", "crps39": 9.0, "v1_resolution_id": "v1-fix"}
    write_ledgers(root, forecasts, rows + [correction])
    S.write_scorecard(root)
    card = json.loads((root / C.SCORECARD_RELATIVE).read_text(encoding="utf-8"))
    assert (root / C.VERDICT_LEDGER).read_bytes() == before
    assert card["descriptive"]["post_verdict_v1_revisions"] == 1


def test_descriptive_target_date_equal_and_share():
    days = sessions(4)
    forecasts = forecast_rows(days)
    rows = []
    for run, (day, delta) in zip(forecasts, (("A", 0.03), ("A", 0.01), ("A", 0.02), ("B", -0.04))):
        for arm in C.ARMS:
            rows.append({"resolution_id": run["forecast_id"] + arm, "v2_run_id": run["forecast_id"], "arm": arm, "lead": 1,
                         "date": day, "pair_status": "identical_inputs", "crps39": 0.1 + delta, "v1_crps39": 0.1,
                         "qs5": 0.0, "v1_qs5": 0.0, "resolved_as_of": "2026-01-01T00:00:00+00:00"})
    desc = S._descriptive(S.build_index(forecasts, rows), rows)["target_date_equal"]["main"]
    assert desc["n_dates"] == 2 and abs(desc["mean_delta"] - (0.02 + -0.04) / 2) < 1e-12
    assert abs(desc["max_single_date_share"] - 0.04 / 0.06) < 1e-12
    assert S.stationary_block_mean_ci([0.1, 0.2, 0.3]) == S.stationary_block_mean_ci([0.1, 0.2, 0.3])


def test_size_regression_gaussian_null_h1():
    # Disclosure (review N8): every call uses the same fixed rng key [seed, 1, main], so all 400 simulated
    # datasets share one bootstrap index matrix. That is still a valid size check of the decision rule, but the
    # 400 rejections are not independent across bootstrap draws.
    rng = np.random.default_rng(20261111)
    rejections = 0
    for _ in range(400):
        sign = rng.choice([-1.0, 1.0], size=50)
        x = rng.normal(0, 1, 50) + sign * 0.25 - (sign * 0.25).mean() * 0  # symmetric location, null mean 0
        if S.iid_bootstrap(x - 0.0, lead=1, arm="main", replicates=499)["p_better"] <= 0.05:
            rejections += 1
    assert 0.02 <= rejections / 400 <= 0.09


def test_state_independent_invariants_on_the_real_repository():
    path = REPO / C.SCORECARD_RELATIVE
    if not path.exists():
        return
    forecasts = V.read_chain(REPO, C.FORECAST_LEDGER)
    resolutions = V.read_chain(REPO, C.RESOLUTION_LEDGER)
    verdicts = V.read_chain(REPO, C.VERDICT_LEDGER)
    card = S.build_scorecard(forecasts, resolutions, verdicts)
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(card))
    assert card["n_pairs_missing"] >= 0


def test_coverage80_abs_error_is_distance_from_nominal_hand_computed():
    """Review B1: over-coverage (arm 1.00 vs v1 0.80) must read worse (+0.20), never better."""
    arm = [1.0] * 50
    v1 = [0.0 if i % 5 == 0 else 1.0 for i in range(50)]           # 40 / 50 = 0.80
    indexes = S.iid_bootstrap(np.zeros(50), lead=1, arm="main", replicates=999)["_indexes"]
    series = {"hit80": arm, "v1_hit80": v1, "qs5": [0.0] * 50, "brier": [0.0] * 50}
    worse = S.secondary_metrics(series, indexes)["coverage80_abs_error"]
    assert abs(worse["estimate"] - 0.2) < 1e-12
    assert (worse["arm_coverage80"], worse["v1_coverage80"]) == (1.0, 0.8)
    assert 0 < worse["ci90"][0] <= worse["ci90"][1] <= 0.2 + 1e-12
    # the replaced per-origin formula averaged |hit-0.8| differences and gave -0.6 * (1.0 - 0.8) = -0.12
    old = float(np.mean([abs(a - 0.8) - abs(b - 0.8) for a, b in zip(arm, v1)]))
    assert abs(old + 0.12) < 1e-12 and worse["estimate"] > 0
    better = S.secondary_metrics({**series, "hit80": v1, "v1_hit80": arm}, indexes)["coverage80_abs_error"]
    assert abs(better["estimate"] + 0.2) < 1e-12 and better["ci90"][1] < 0
    # per replicate: the statistic is computed on the same resampled origins for both sides
    i = indexes[0]
    expected = abs(np.asarray(arm)[i].mean() - 0.8) - abs(np.asarray(v1)[i].mean() - 0.8)
    replicate = np.abs(np.asarray(arm)[indexes].mean(axis=1) - 0.8) - np.abs(np.asarray(v1)[indexes].mean(axis=1) - 0.8)
    assert abs(replicate[0] - expected) < 1e-12


def test_scorecard_secondary_metrics_on_the_thinned_sample(root):
    days = sessions(60)
    forecasts = forecast_rows(days)
    rows = resolution_rows(forecasts, (1,), diff=noise)
    for row in rows:
        position = int(row["v2_run_id"].split("-")[1])
        row["v1_hit80"] = position % 5 != 0
    write_ledgers(root, forecasts, rows)
    S.write_scorecard(root)
    card = json.loads((root / C.SCORECARD_RELATIVE).read_text(encoding="utf-8"))
    secondary = card["thinned"]["h1"]["by_arm"]["main"]["secondary"]
    assert card["thinned"]["h1"]["n_scored"] == 50
    assert abs(secondary["coverage80_abs_error"]["estimate"] - 0.2) < 1e-12
    assert abs(secondary["qs5"]["estimate"] - (0.02 - 0.021)) < 1e-12
    assert abs(secondary["brier"]["estimate"] - (0.2 - 0.25)) < 1e-12
    assert secondary["qs5"]["ci90"][0] <= secondary["qs5"]["estimate"] <= secondary["qs5"]["ci90"][1]


def test_blocking_origin_is_reported_and_warned():
    """Review N2: a permanently missing resolution must not stall the verdict silently."""
    days = sessions(40)
    forecasts = forecast_rows(days)
    rows = [row for row in resolution_rows(forecasts, (1,)) if row["v2_run_id"] != "run-3"]
    index = S.build_index(forecasts, rows)
    sample = S.thinned_sample(index, 1, 50)
    assert (sample["n_scored"], sample["n_pending_blocking"], sample["blocking_origin"]) == (3, 1, days[3])
    assert sample["blocking_sessions_behind"] == 36
    warnings = S.stalled_scans(index)
    assert any(item.startswith(f"h1 thinned sample blocked at origin {days[3]}") for item in warnings)
    card = S.build_scorecard(forecasts, rows, [])
    assert card["thinned"]["h1"]["blocking_origin"] == days[3] and card["warnings"] == warnings
    # a pending origin at the live edge is normal and not warned
    recent = [row for row in resolution_rows(forecasts, (1,)) if row["v2_run_id"] != "run-39"]
    edge = S.thinned_sample(S.build_index(forecasts, recent), 1, 50)
    assert edge["blocking_origin"] == days[39] and edge["blocking_sessions_behind"] == 0
    assert not any(item.startswith("h1 ") for item in S.stalled_scans(S.build_index(forecasts, recent)))


def test_r3_tolerance_equivalent_rows_enter_the_thinned_sample_and_r2_rows_keep_their_meaning():
    days = sessions(12)
    forecasts = forecast_rows(days, differ={days[2], days[3]})
    forecasts[2]["pair_eligibility"] = "tolerance_equivalent"   # r3 run: inputs_differ(path_hash) within 1e-12
    forecasts[3]["pair_eligibility"] = "excluded"               # r3 run outside the tolerance
    resolutions = resolution_rows(forecasts, (1,))
    for row in resolutions:
        if row["v2_run_id"] == forecasts[2]["forecast_id"]:
            row.update(pair_eligibility="tolerance_equivalent", v1_crps39=0.01)
    index = S.build_index(forecasts, resolutions)
    sample = S.thinned_sample(index, 1, None)
    assert days[2] in sample["origins"] and days[3] not in sample["origins"]
    assert (sample["n_excluded"], sample["n_tolerance_equivalent"], sample["n_scored"]) == (1, 1, 11)
    card = S.build_scorecard(forecasts, resolutions, [])
    assert card["pair_eligibility"] == {"rule": "r3", "runs": {"identical_inputs": 10, "tolerance_equivalent": 1, "excluded": 1}}
    assert card["thinned"]["h1"]["n_tolerance_equivalent"] == 1
    assert card["descriptive"]["inputs_differ_sensitivity"]["main"]["n_rows"] == 1   # only the excluded run
    # r2 rows (no pair_eligibility field): inputs_differ stays excluded, exactly as before r3
    legacy = forecast_rows(days, differ={days[2]})
    legacy_sample = S.thinned_sample(S.build_index(legacy, resolution_rows(legacy, (1,))), 1, None)
    assert legacy_sample["n_excluded"] == 1 and legacy_sample["n_tolerance_equivalent"] == 0
