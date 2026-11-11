"""daily6m v2 pipeline on a tmp_path store with synthetic v1 ledgers (never the real repository)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

import ai_fc.timeseries_daily6m.contracts as v1C
import ai_fc.timeseries_daily6m.features as F
import ai_fc.timeseries_daily6m.pipeline as P
from ai_fc.timeseries_daily6m_v2 import contracts as C
from ai_fc.timeseries_daily6m_v2 import kernel as K
from ai_fc.timeseries_daily6m_v2 import model as M
from ai_fc.timeseries_daily6m_v2 import pipeline as V

REPO = Path(__file__).resolve().parents[2]
TEST_CONSTANTS = {"schema_version": 1, "constants_id": "test", "persistence_by_column": {}, "long_run_rule": {"registered": "slow_ewma_0.996"},
                  "selection": {"seed": 20261111, "replicates": 2, "paths": 50, "validation_horizon": 21}}
ORIGINS = {
    "2026-10-09": ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"],
    "2026-10-12": ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"],
}
ISSUE = {"2026-10-09": "2026-10-12T00:00:00+00:00", "2026-10-12": "2026-10-13T00:00:00+00:00"}


def paths_for(seed: int, horizon: int, scale: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(0, scale, (400, horizon)), axis=1))


def make_v1_run(origin: str, run_id: str, *, identical: bool = True) -> dict:
    dates = ORIGINS[origin]
    v1_paths = paths_for(len(run_id), len(dates))
    records = K.summarize_compact(v1_paths, anchor=100.0, future_dates=dates)
    return {"run_id": run_id, "content_hash": hashlib.sha256(run_id.encode()).hexdigest(), "anchor_date": origin,
            "dates": dates, "records": records, "path_hash": "p" * 64, "model_code_hash": "c" * 64,
            "contract_hash": "k" * 64, "path_count": 400, "anchor": {"value": 100.0},
            "model_config": {"block_length": 10, "ewma_lambda": 0.97}, "_paths": v1_paths, "_identical": identical}


def fake_generate(bundle, *, anchor, as_of, future_dates, v1_run, previous_selection, constants, path_count=None, root=None):
    horizon = len(future_dates)
    main = paths_for(7 + horizon + len(v1_run["run_id"]), horizon)
    term = main.copy()
    term[:, 1:] = 100.0 * np.exp(np.log(main[:, 1:] / 100.0) * 1.3)
    zero = main * 0.995
    arm_paths = {"main": main, "term_structure": term, "zero_drift": zero}
    identical = v1_run["_identical"]
    chosen = [21, 0.94] if previous_selection else [10, 0.97]
    payload = {
        "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "contract_id": C.CONTRACT_ID,
        "issued_at": as_of, "origin_session": v1_run["anchor_date"], "anchor_date": v1_run["anchor_date"],
        "anchor": {"series_id": "NASDAQCOM", "date": v1_run["anchor_date"], "value": 100.0, "available_at": None},
        "dates": future_dates, "horizon_sessions": horizon, "path_count": 400, "probability_unit": "fraction",
        "probability_space": C.PROBABILITY_SPACE, "status": "shadow_research", "numbers_visible": False,
        "parent": {"v1_run_id": v1_run["run_id"], "v1_run_content_hash": v1_run["content_hash"]},
        "pair_status": "identical_inputs" if identical else "inputs_differ",
        "inputs_differ_reason": None if identical else "path_hash",
        "selection": {"previous": previous_selection, "chosen": chosen},
        "quantile_levels": list(K.GRID_LEVELS),
        "arms": {arm: {"path_hash": M._path_hash(value), "records": K.summarize_compact(value, anchor=100.0, future_dates=future_dates),
                       "quantile_grid": K.quantile_grid(value, anchor=100.0).tolist()} for arm, value in arm_paths.items()},
        "v1_reference": {"run_id": v1_run["run_id"], "records": [{"date": r["date"], "band_index": r["band_index"],
                                                                    "probability_up_from_previous": r["probability_up_from_previous"]}
                                                                   for r in v1_run["records"]],
                         "quantile_grid": K.quantile_grid(v1_run["_paths"], anchor=100.0).tolist() if identical else None},
        "footnote": C.FOOTNOTE,
    }
    payload["content_hash"] = C.canonical_hash(payload)
    return payload, arm_paths


class Bundle:
    def __init__(self, origin):
        self.anchor = {"date": origin, "value": 100.0}
        self.issues = ()
        self.lineage = {"market_rows": [], "factor_rows": []}
        self.freshness = ()


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    contract = yaml.safe_load((REPO / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["design_constants"]["canonical_hash"] = C.canonical_hash(TEST_CONSTANTS)
    (root / C.CONTRACT_RELATIVE).parent.mkdir(parents=True)
    (root / C.CONTRACT_RELATIVE).write_text(yaml.safe_dump(contract, allow_unicode=True), encoding="utf-8")
    (root / C.CONSTANTS_RELATIVE).parent.mkdir(parents=True)
    (root / C.CONSTANTS_RELATIVE).write_text(json.dumps(TEST_CONSTANTS), encoding="utf-8")
    runs: dict[str, dict] = {}
    clock = {"now": ISSUE["2026-10-09"], "origin": "2026-10-09"}
    monkeypatch.setattr(V, "model_code_hash", lambda _root: "m" * 64)
    monkeypatch.setattr(V, "_now", lambda: F.aware_time(clock["now"]))
    monkeypatch.setattr(F, "last_completed_session", lambda _now: clock["origin"])
    monkeypatch.setattr(F, "read_native_frame", lambda _root, as_of: None)
    monkeypatch.setattr(F, "build_bundle", lambda _root, as_of, rows: Bundle(clock["origin"]))
    monkeypatch.setattr(P, "load_run", lambda _root, row: runs[row["forecast_id"]])
    monkeypatch.setattr(M, "generate_v2_forecast", fake_generate)
    return root, runs, clock


def add_v1_forecast(root, runs, origin, run_id, *, identical=True):
    run = make_v1_run(origin, run_id, identical=identical)
    runs[run_id] = run
    iso = "2026-W41" if origin == "2026-10-09" else "2026-W42"
    P._append(root, v1C.FORECAST_LEDGER, {"forecast_id": run_id, "as_of": ISSUE[origin], "origin_session": origin, "iso_week": iso,
                                          "supersedes": None, "run_path": f"data/timeseries_daily6m/runs/{run_id}.json",
                                          "run_content_hash": run["content_hash"], "probability_unit": "fraction"}, identity="forecast_id")
    return run


def add_v1_resolution(root, run, day, actual, previous, *, revision="r0", supersedes=None, resolved="2026-10-20T00:00:00+00:00"):
    index = run["dates"].index(day)
    record = run["records"][index]
    p = record["probability_up_from_previous"]
    outcome = actual > previous
    payload = {"forecast_id": run["run_id"], "date": day, "resolved_as_of": resolved, "source_revision_hash": revision,
               "supersedes": supersedes, "actual_index": actual, "actual_previous_index": previous, "outcome_up": outcome,
               "probability_up_from_previous": p, "brier": (p - int(outcome)) ** 2,
               "inside_p10_p90": record["band_index"]["p10"] <= actual <= record["band_index"]["p90"],
               "resolution_kind": "initial" if supersedes is None else "correction"}
    payload["resolution_id"] = run["run_id"] + ":" + day + ("" if supersedes is None else ":" + revision)
    return P._append(root, v1C.RESOLUTION_LEDGER, payload, identity="resolution_id")


def ledger_bytes(root, relative):
    path = root / relative
    return path.read_bytes() if path.exists() else b""


def test_first_issue_skip_and_closed_window(store):
    root, runs, clock = store
    add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    result = V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)
    assert result["status"] == "issued" and result["pair_status"] == "identical_inputs"
    rows = V.read_chain(root, C.FORECAST_LEDGER)
    assert len(rows) == 1 and len(list((root / C.RUNS_RELATIVE).glob("*.json"))) == 1
    run = V.load_run(root, rows[0])
    assert run["selection"]["previous"] is None and run["paired_v1_forecast_id"] == "daily6m-a"
    before = ledger_bytes(root, C.FORECAST_LEDGER)
    again = V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)
    assert again["status"] == "skipped" and ledger_bytes(root, C.FORECAST_LEDGER) == before
    add_v1_forecast(root, runs, "2026-10-12", "daily6m-bb")
    clock.update(now="2026-10-13T21:00:00+00:00", origin="2026-10-12")
    closed = V.forecast_daily6m_v2(root, as_of="2026-10-13T21:00:00+00:00", save_paths=False)
    assert closed["status"] == "hold" and closed["reasons"] == ["pair_window_closed"]
    assert ledger_bytes(root, C.FORECAST_LEDGER) == before


def test_selection_state_is_threaded_and_v1_untouched(store):
    root, runs, clock = store
    add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    v1_before = ledger_bytes(root, v1C.FORECAST_LEDGER)
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)
    add_v1_forecast(root, runs, "2026-10-12", "daily6m-bb")
    v1_before = ledger_bytes(root, v1C.FORECAST_LEDGER)
    clock.update(now=ISSUE["2026-10-12"], origin="2026-10-12")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-12"], save_paths=False)
    rows = V.read_chain(root, C.FORECAST_LEDGER)
    second = V.load_run(root, rows[1])
    assert second["selection"]["previous"] == V.load_run(root, rows[0])["selection"]["chosen"]
    assert ledger_bytes(root, v1C.FORECAST_LEDGER) == v1_before
    assert V.verify_daily6m_v2(root)["ok"] is True


def test_resolve_hand_scores_corrections_and_inputs_differ(store):
    root, runs, clock = store
    v1a = add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)
    v1b = add_v1_forecast(root, runs, "2026-10-12", "daily6m-bb", identical=False)
    clock.update(now=ISSUE["2026-10-12"], origin="2026-10-12")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-12"], save_paths=False)
    add_v1_resolution(root, v1a, "2026-10-12", 101.0, 100.0)
    add_v1_resolution(root, v1a, "2026-10-13", 99.0, 101.0)
    add_v1_resolution(root, v1b, "2026-10-13", 99.0, 101.0)
    clock.update(now="2026-10-21T03:00:00+00:00")
    result = V.resolve_daily6m_v2(root, as_of="2026-10-20T01:00:00+00:00")
    assert result["resolved"] == 9
    rows = V.read_chain(root, C.RESOLUTION_LEDGER)
    forecasts = V.read_chain(root, C.FORECAST_LEDGER)
    run = V.load_run(root, forecasts[0])
    row = next(r for r in rows if r["v2_run_id"] == run["run_id"] and r["arm"] == "main" and r["date"] == "2026-10-12")
    y = math.log(101.0 / 100.0)
    grid = [column[0] for column in run["arms"]["main"]["quantile_grid"]]
    assert abs(row["crps39"] - K.crps_grid39(y, grid)) < 1e-12
    bands = run["arms"]["main"]["records"][0]["band_index"]
    hand = 0.4 * sum((y - math.log(bands[n] / 100.0)) * (t - (1 if y < math.log(bands[n] / 100.0) else 0))
                     for t, n in zip(K.BAND_LEVELS, K.BAND_NAMES))
    assert abs(row["qs5"] - hand) < 1e-12
    assert row["hit80"] == (bands["p10"] <= 101.0 <= bands["p90"])
    p = run["arms"]["main"]["records"][0]["probability_up_from_previous"]
    assert abs(row["brier"] - (p - 1) ** 2) < 1e-12
    v1_row = V.P.read_chain(root, v1C.RESOLUTION_LEDGER)[0]
    assert row["v1_hit80"] == v1_row["inside_p10_p90"] and abs(row["v1_brier"] - v1_row["brier"]) < 1e-12
    differ = [r for r in rows if r["pair_status"] == "inputs_differ"]
    assert len(differ) == 3 and all(r["v1_crps39"] is None for r in differ)
    # v1 correction -> three v2 corrections, originals preserved
    first = V.P.read_chain(root, v1C.RESOLUTION_LEDGER)[0]
    add_v1_resolution(root, v1a, "2026-10-12", 101.5, 100.0, revision="r1", supersedes=first["resolution_id"],
                      resolved="2026-10-21T00:00:00+00:00")
    again = V.resolve_daily6m_v2(root, as_of="2026-10-21T01:00:00+00:00")
    assert again["resolved"] == 3 and again["corrected"] == 3
    after = V.read_chain(root, C.RESOLUTION_LEDGER)
    corrections = [r for r in after if r["resolution_kind"] == "correction"]
    assert len(after) == 12 and len(corrections) == 3
    assert all(r["supersedes"] in {x["resolution_id"] for x in rows} and r["revision_reason"] for r in corrections)
    assert V.resolve_daily6m_v2(root, as_of="2026-10-21T02:00:00+00:00")["resolved"] == 0
    assert V.verify_daily6m_v2(root)["ok"] is True


def _issue_two(store):
    root, runs, clock = store
    add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)
    add_v1_forecast(root, runs, "2026-10-12", "daily6m-bb")
    clock.update(now=ISSUE["2026-10-12"], origin="2026-10-12")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-12"], save_paths=False)
    add_v1_resolution(root, runs["daily6m-a"], "2026-10-12", 101.0, 100.0)
    clock.update(now="2026-10-20T02:00:00+00:00")
    V.resolve_daily6m_v2(root, as_of="2026-10-20T01:00:00+00:00")
    assert V.verify_daily6m_v2(root)["ok"]
    return root


def rechain(root, relative, rows):
    """Rewrite a ledger with a consistent hash chain so only the intended verify branch can fire."""
    previous, lines = None, []
    for row in rows:
        body = {k: v for k, v in row.items() if k not in ("previous_hash", "content_hash")}
        body["previous_hash"] = previous
        body["content_hash"] = C.canonical_hash(body)
        previous = body["content_hash"]
        lines.append(json.dumps(body, sort_keys=True, separators=(",", ":")))
    (root / relative).write_text("\n".join(lines) + "\n", encoding="utf-8")


def rewrite_run(root, position, mutate):
    """Mutate one run, re-hash it and point its (re-chained) forecast ledger row at the new content hash."""
    rows = V.read_chain(root, C.FORECAST_LEDGER)
    run_path = root / rows[position]["run_path"]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    mutate(run)
    run["content_hash"] = C.canonical_hash({k: v for k, v in run.items() if k != "content_hash"})
    run_path.write_text(json.dumps(run), encoding="utf-8")
    rows[position]["run_content_hash"] = run["content_hash"]
    rechain(root, C.FORECAST_LEDGER, rows)


def tamper_resolution(root, position, delta):
    rows = V.read_chain(root, C.RESOLUTION_LEDGER)
    rows[position]["crps39"] += delta
    rechain(root, C.RESOLUTION_LEDGER, rows)
    return rows[position]


def first_error(root):
    result = V.verify_daily6m_v2(root)
    assert result["ok"] is False
    return result["errors"][0]


def test_verify_resolution_replay_branch(store):
    root = _issue_two(store)
    rows = V.read_chain(root, C.RESOLUTION_LEDGER)
    assert [r["arm"] for r in rows] == ["main", "term_structure", "zero_drift"]
    tampered = tamper_resolution(root, 2, 1e-6)          # zero_drift: not part of the h1 identity pair
    assert first_error(root) == "v2 resolution replay mismatch: " + tampered["resolution_id"]


def test_verify_h1_identity_branch(store):
    # validate_run already pins grid column 0 and record 0 of term_structure to main, so a run-side change
    # never reaches this branch; a re-chained ledger row that breaks the pair does, before the generic replay.
    root = _issue_two(store)
    tamper_resolution(root, 1, 1e-6)                      # term_structure lead 1
    assert first_error(root) == "term_structure h1 identity check failed"


def test_verify_selection_chain_branch(store):
    root = _issue_two(store)
    rewrite_run(root, 1, lambda run: run["selection"].__setitem__("previous", [5, 0.94]))
    assert first_error(root) == "selection state chain broken (previous != prior run chosen)"


def test_verify_run_byte_branch(store):
    root = _issue_two(store)
    path = root / V.read_chain(root, C.FORECAST_LEDGER)[0]["run_path"]
    path.write_text(path.read_text(encoding="utf-8").replace(C.FOOTNOTE, C.FOOTNOTE + " ", 1), encoding="utf-8")
    assert first_error(root) == "v2 run content hash mismatch"


def test_verify_v1_reference_branch(store):
    root = _issue_two(store)

    def mutate(run):
        run["v1_reference"]["records"][4]["probability_up_from_previous"] += 0.01   # an unresolved date
    rewrite_run(root, 0, mutate)
    assert first_error(root) == "v1 reference records disagree with the paired v1 run (band or probability)"


@pytest.fixture
def one_session_thresholds(monkeypatch):
    """Thresholds of 1 let the two-run store record a real h1 verdict row through write_scorecard."""
    from ai_fc.timeseries_daily6m_v2 import scorecard as S
    monkeypatch.setattr(S, "THRESHOLDS", {1: 1, 5: 1, 21: 1})
    return S


def test_verify_verdict_replay_branch(store, one_session_thresholds):
    S = one_session_thresholds
    root = _issue_two(store)
    assert S.write_scorecard(root)["verdicts_appended"] == ["h1_p_values_frozen"]
    verdicts = V.read_chain(root, C.VERDICT_LEDGER)
    assert verdicts[0]["scorecard_code_hash"] == C.scorecard_code_hash()
    clean = V.verify_daily6m_v2(root)
    assert clean["ok"] is True and clean["diagnostics"]["verdicts_recorded_by_other_scorecard_code"] == []
    verdicts[0]["by_test"]["main_h1"]["p_better"] = 0.5 if verdicts[0]["by_test"]["main_h1"]["p_better"] != 0.5 else 0.25
    rechain(root, C.VERDICT_LEDGER, verdicts)
    assert first_error(root) == "verdict replay mismatch: h1_p_values_frozen"


def test_verdict_scorecard_code_hash_is_a_non_gating_diagnostic(store, one_session_thresholds):
    S = one_session_thresholds
    root = _issue_two(store)
    S.write_scorecard(root)
    verdicts = V.read_chain(root, C.VERDICT_LEDGER)
    verdicts[0]["scorecard_code_hash"] = "0" * 64           # as if scorecard.py was edited after recording
    rechain(root, C.VERDICT_LEDGER, verdicts)
    result = V.verify_daily6m_v2(root)
    assert result["ok"] is True
    assert result["diagnostics"]["verdicts_recorded_by_other_scorecard_code"] == ["h1_p_values_frozen"]


def test_verify_verdict_cut_and_duplicate_kind(store):
    root = _issue_two(store)
    V._append(root, C.VERDICT_LEDGER, {"verdict_id": "daily6m-v2-verdict:h1_p_values_frozen", "kind": "h1_p_values_frozen",
                                        "ledger_cut": {"forecasts_rows": 2, "resolutions_rows": 3, "last_content_hash": "x"}})
    assert first_error(root) == "verdict ledger cut no longer matches the resolution chain"
    path = root / C.VERDICT_LEDGER
    first = {"verdict_id": "a", "kind": "family_verdict", "previous_hash": None}
    first["content_hash"] = C.canonical_hash(first)
    second = {"verdict_id": "b", "kind": "family_verdict", "previous_hash": first["content_hash"]}
    second["content_hash"] = C.canonical_hash(second)
    path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    assert first_error(root) == "a verdict kind may be recorded only once"


def test_verify_raw_ledger_edit_trips_the_chain(store):
    root = _issue_two(store)
    path = root / C.RESOLUTION_LEDGER
    text = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(text[2])
    row["crps39"] += 1e-6
    text[2] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    assert first_error(root).startswith("ledger hash chain mismatch")


def test_orchestration_code_drift_is_disclosed_not_gating(store):
    root = _issue_two(store)
    run = V.load_run(root, V.read_chain(root, C.FORECAST_LEDGER)[0])
    assert run["orchestration_code_hashes"] == C.orchestration_code_hashes()
    rewrite_run(root, 0, lambda r: r["orchestration_code_hashes"].__setitem__(C.ORCHESTRATION_CODE_PATHS[1], "0" * 64))
    result = V.verify_daily6m_v2(root)
    assert result["ok"] is True and result["diagnostics"]["runs_with_changed_orchestration_code"] == 1


def test_gating_code_hash_covers_numerical_files_only(tmp_path):
    for relative in (*C.NUMERICAL_CODE_PATHS, *C.ORCHESTRATION_CODE_PATHS):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / relative).read_bytes())
    assert C.model_code_hash(tmp_path) == C.model_code_hash(REPO)
    assert not set(C.NUMERICAL_CODE_PATHS) & set(C.ORCHESTRATION_CODE_PATHS)
    before = C.model_code_hash(tmp_path)
    for relative in C.ORCHESTRATION_CODE_PATHS:     # a comment in pipeline/scorecard/contracts keeps every run loadable
        with (tmp_path / relative).open("a", encoding="utf-8") as handle:
            handle.write("\n# comment\n")
    assert C.model_code_hash(tmp_path) == before
    assert C.orchestration_code_hashes(tmp_path) != C.orchestration_code_hashes(REPO)
    with (tmp_path / "src/ai_fc/timeseries_daily6m_v2/kernel.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# numerical file edit\n")
    assert C.model_code_hash(tmp_path) != before


def test_resolve_as_of_guards(store):
    root, runs, clock = store
    v1a = add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)
    add_v1_resolution(root, v1a, "2026-10-12", 101.0, 100.0, resolved="2026-10-20T00:00:00+00:00")
    clock.update(now="2026-10-20T02:00:00+00:00")
    with pytest.raises(V.Daily6mV2PipelineError, match="future"):
        V.resolve_daily6m_v2(root, as_of="2026-10-21T00:00:00+00:00")
    with pytest.raises(V.Daily6mV2PipelineError, match="precede the v1 resolution"):
        V.resolve_daily6m_v2(root, as_of="2026-10-19T23:00:00+00:00")
    assert not (root / C.RESOLUTION_LEDGER).exists()
    assert V.resolve_daily6m_v2(root)["resolved"] == 3   # default cutoff = now


def test_concurrent_writer_is_rejected(store):
    root, runs, _ = store
    add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    with V.writer_lock(root):
        with pytest.raises(V.Daily6mV2PipelineError, match="lock"):
            V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=False)


def test_future_as_of_is_refused(store):
    root, runs, _ = store
    add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    with pytest.raises(V.Daily6mV2PipelineError, match="future"):
        V.forecast_daily6m_v2(root, as_of="2026-10-14T00:00:00+00:00", save_paths=False)


def test_path_artifact_is_saved_and_verified(store):
    root, runs, _ = store
    add_v1_forecast(root, runs, "2026-10-09", "daily6m-a")
    V.forecast_daily6m_v2(root, as_of=ISSUE["2026-10-09"], save_paths=True)
    run = V.load_run(root, V.read_chain(root, C.FORECAST_LEDGER)[0])
    artifact = root / run["path_artifact"]["path"]
    assert artifact.exists() and artifact.is_relative_to(root / "outputs/timeseries_daily6m_v2/paths")
    assert V.verify_daily6m_v2(root)["ok"] is True
