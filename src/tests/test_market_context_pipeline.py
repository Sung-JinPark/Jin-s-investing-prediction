"""Research publication, immutable replay, and genuinely forward scoring."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from ai_fc.market_context import contracts as C, display as D, features as F, pipeline as P

ISSUED = "2026-10-15T05:30:00+00:00"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def context(tmp_path, monkeypatch):
    path = tmp_path / C.CONTRACT_RELATIVE
    path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / C.CONTRACT_RELATIVE, path)
    monkeypatch.setattr(C, "model_code_hash", lambda _root: "e" * 64)
    _, sessions, closes = F._calendar(ISSUED, "2025-01-01", 252)
    completed = [day for day, stamp in zip(sessions, closes) if stamp <= C.aware(ISSUED)]
    dates = completed[-300:]
    prices = 100 * np.exp(np.cumsum(np.random.default_rng(19).normal(.0003, .01, len(dates))))
    future = [day for day in sessions if day > dates[-1]][:252]
    event = {"event_id": "incident", "revision_id": "revision", "family": "cpi_model_innovation",
             "axis": "inflation", "kind": "model_innovation", "title": "CPI 공개값",
             "available_at": "2026-10-14T12:30:00+00:00", "published_at": "2026-10-14T12:30:00+00:00",
             "retrieved_at": "2026-10-14T12:31:00+00:00", "source_url": "https://www.bls.gov/cpi/",
             "surprise_z": 1.2, "numerical_eligible": True, "effective_session": dates[-1],
             "reason": "ready_model_innovation", "expectation_kind": "model_innovation"}
    inputs = {"dates": dates, "closes": prices.tolist(), "anchor_date": dates[-1], "anchor": float(prices[-1]),
              "future_dates": future, "events": [event], "session_dates": completed,
              "lineage": {"source": "isolated_fixture", "available_at_max": event["available_at"]},
              "history": {"dates": dates, "index": prices.tolist()}, "gate": {"pass": True, "reasons": []}}
    monkeypatch.setattr(F, "load_inputs", lambda _root, **_kwargs: copy.deepcopy(inputs))
    return tmp_path, inputs


@pytest.fixture
def published(context):
    root, inputs = context
    run = P.build_context(root, as_of=ISSUED, save_paths=False)
    assert run["status"] == "research_preview", run
    return root, inputs, run


def _rehash(row):
    row["content_hash"] = C.canonical_hash({key: value for key, value in row.items() if key != "content_hash"})
    return row


def test_contract_pins_numerical_coordinates_and_no_official_writes(context):
    root, _ = context
    contract = C.load_contract(root)
    assert contract["publication"]["official_ledger_write"] is False
    contract["model"]["half_lives"] = [1, 2, 3]
    import yaml
    (root / C.CONTRACT_RELATIVE).write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(C.MarketContextError, match="numerical"):
        C.load_contract(root)


def test_independent_baseline_preview_and_all_daily_data_are_immutable(published):
    root, inputs, run = published
    assert len(run["records"]) == 252 and len(run["representative"]["values"]) == 253
    assert run["numerical_context_applied"] is False and run["score"] is None
    assert run["comparison"]["identical_at_zero_context"] is True
    assert run["runtime"]["packages"]["numpy"]
    assert set(run["attribution_basis"]) == set(C.AXES)
    assert run["replay"]["reference_state"]["state_by_family"]
    assert run["state_summary"]["events"][0]["used_numerically"] is False
    assert run["state_summary"]["events"][0]["title"] == "CPI 공개값"
    assert run["state_summary"]["axes"][0]["score"] is None
    assert not (root / "data/scenarios").exists() and not (root / "calibration").exists()
    before = (root / C.FORECAST_LEDGER).read_bytes()
    replay = P.build_context(root, as_of=ISSUED, save_paths=False)
    assert replay["forecast_id"] == run["forecast_id"] and replay["skipped"]
    assert (root / C.FORECAST_LEDGER).read_bytes() == before
    assert P.verify_context(root, replay=True)["ok"]
    projection = D.load_projection(root, now=C.aware(ISSUED))
    assert projection["status"] == "research_preview"
    assert projection["coefficient_hash"] == "not_fitted"
    assert projection["representative"]["path_id"].startswith("simulation-")
    assert "replay" not in projection and "daily" not in projection


def test_explicit_revision_appends_and_preserves_original_bytes(published):
    root, inputs, run = published
    before = (root / C.FORECAST_LEDGER).read_bytes()
    original = (root / run["run_path"]).read_bytes()
    inputs["events"][0]["surprise_z"] = -.5
    revision = P.build_context(root, as_of="2026-10-15T05:31:00+00:00", supersedes=run["forecast_id"], save_paths=False)
    assert revision["status"] == "research_preview"
    assert revision["supersedes"] == run["forecast_id"]
    assert (root / C.FORECAST_LEDGER).read_bytes().startswith(before)
    assert (root / run["run_path"]).read_bytes() == original
    invalid = P.build_context(root, as_of="2026-10-15T05:32:00+00:00", supersedes=run["forecast_id"], save_paths=False)
    assert invalid["status"] == "hold"
    assert len(P.read_chain(root, C.FORECAST_LEDGER)) == 2


def test_freshness_short_circuits_model_and_write_time_recheck_is_fail_closed(context, monkeypatch):
    root, inputs = context
    inputs["gate"] = {"pass": False, "reasons": ["stale_index"]}
    held = P.build_context(root, as_of=ISSUED)
    assert held["status"] == "hold" and "records" not in held
    assert not (root / C.FORECAST_LEDGER).exists()
    inputs["gate"] = {"pass": True, "reasons": []}
    calls = []

    def change_at_append(_root, as_of):
        calls.append(as_of)
        value = copy.deepcopy(inputs)
        if len(calls) > 1:
            value["gate"] = {"pass": False, "reasons": ["changed"]}
        return value

    monkeypatch.setattr(F, "load_inputs", change_at_append)
    held = P.build_context(root, as_of=ISSUED, save_paths=False)
    assert held["status"] == "hold" and "before append" in held["gate"]["reasons"][0]
    assert not (root / C.FORECAST_LEDGER).exists()


def test_rehashed_bad_probability_and_future_frozen_event_still_rejected(published):
    _, _, run = published
    bad = copy.deepcopy(run)
    bad["records"][0]["probability_up_from_previous"] = 55
    with pytest.raises(C.MarketContextError, match="fraction"):
        P.validate_run(_rehash(bad))
    bad = copy.deepcopy(run)
    bad["replay"]["events"][0]["retrieved_at"] = "2026-10-16T01:00:00Z"
    bad["input_hash"] = C.canonical_hash(bad["replay"])
    with pytest.raises(C.MarketContextError, match="future event"):
        P.validate_run(_rehash(bad))
    bad = copy.deepcopy(run)
    bad["replay"]["numerical_state"][0] = 1
    bad["input_hash"] = C.canonical_hash(bad["replay"])
    with pytest.raises(C.MarketContextError, match="numerical state"):
        P.validate_run(_rehash(bad))


def test_display_holds_stale_or_tampered_pointer_without_substitution(published):
    root, _, run = published
    held = D.load_projection(root, now=C.aware("2026-10-22T22:00:00Z"))
    assert held["status"] == "hold" and "records" not in held
    pointer = json.loads((root / C.LATEST_RELATIVE).read_text(encoding="utf-8"))
    pointer["run_content_hash"] = "f" * 64
    (root / C.LATEST_RELATIVE).write_text(C.canonical_json(_rehash(pointer)), encoding="utf-8")
    assert D.load_projection(root, now=C.aware(ISSUED))["status"] == "hold"
    assert (root / run["run_path"]).is_file()


def test_resolution_matures_after_exchange_close_once_without_invented_ablations(published, monkeypatch):
    root, inputs, run = published
    target = run["future_dates"][0]
    fact = {"series_id": "NASDAQCOM", "source_id": "fixture", "observation_time": target,
            "value": run["anchor"] * .98, "available_at": target + "T21:00:00Z",
            "retrieved_at": target + "T21:01:00Z", "source_sha256": "a" * 64}
    monkeypatch.setattr(F, "read_market_rows", lambda _root, **_kwargs: [fact])
    premature = P.resolve_context(root, as_of=target + "T19:00:00Z")
    assert premature["resolved"] == 0
    resolved = P.resolve_context(root, as_of=target + "T22:00:00Z")
    assert resolved["resolved"] == 1
    assert P.resolve_context(root, as_of=target + "T23:00:00Z")["resolved"] == 0
    row = P.read_chain(root, C.RESOLUTION_LEDGER)[0]
    assert row["actual_up_from_previous"] is False
    assert row["scores"]["combined"]["crps"] >= 0
    assert "market_only" not in row["scores"] and "event_only" not in row["scores"]
    assert "fhs" not in row["scores"]
    assert row["comparison_status"]["market_only"] == "not_fitted_baseline_identity"
    assert row["observation_vintage_rule"] == "latest_eligible_at_first_resolution_then_immutable"


def test_empty_fit_is_blocked_without_fabricating_model_or_history(context):
    root, _ = context
    result = P.fit_context(root, train_cutoff=ISSUED)
    assert result["status"] == "blocked" and result["predictive_validation"] == "not_established"
    assert not (root / C.MODEL_LEDGER).exists()
    assert P.training_samples(root, as_of=ISSUED) == []


def test_subsecond_issuance_cutoff_is_not_rewound_before_collection(context):
    root, inputs = context
    inputs["events"][0].update({"available_at": "2026-10-15T05:30:00.900000+00:00",
                               "retrieved_at": "2026-10-15T05:30:00.900000+00:00",
                               "effective_session": inputs["future_dates"][0]})
    run = P.build_context(root, as_of="2026-10-15T05:30:00.950000+00:00", save_paths=False)
    assert run["status"] == "research_preview", run
    assert run["as_of"] == "2026-10-15T05:30:00.950000+00:00"
    assert run["replay"]["reference_state"]["reference_vector"][3] == 1.2


def test_provisional_intraday_fact_cannot_mature_as_close_later(published, monkeypatch):
    root, _, run = published
    target = run["future_dates"][0]
    fact = {"series_id": "NASDAQCOM", "source_id": "fixture", "observation_time": target,
            "value": 999., "available_at": target + "T17:00:00Z", "retrieved_at": target + "T17:01:00Z",
            "source_sha256": "a" * 64}
    monkeypatch.setattr(F, "read_market_rows", lambda _root, **_kwargs: [fact])
    result = P.resolve_context(root, as_of=target + "T23:00:00Z")
    assert result["resolved"] == 0
    assert not (root / C.RESOLUTION_LEDGER).exists()


def test_fitted_family_missing_input_holds_instead_of_neutral_substitution(context, monkeypatch):
    root, _ = context
    monkeypatch.setattr(P, "_load_coefficients", lambda *_args, **_kwargs: {"active_families": ["vix_innovation"]})
    held = P.build_context(root, as_of=ISSUED, save_paths=False)
    assert held["status"] == "hold"
    assert "missing_active_family_source:vix_innovation" in held["gate"]["reasons"][0]


def test_ready_frozen_coefficients_apply_only_to_future_paths_and_replay(context):
    root, inputs = context
    coef = [0.] * 21
    coef[3] = -.0002
    model = {"model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "status": "ready", "coef": coef, "scale": [1.] * 21,
             "bootstrap_coefficients": [coef] * 200, "coefficient_units": "raw_feature",
             "active_families": ["cpi_model_innovation"], "train_cutoff": "2026-10-01T00:00:00Z",
             "available_at": "2026-10-02T00:00:00Z", "training_month": "2026-10",
             "contract_hash": C.canonical_hash(C.load_contract(root)), "model_code_hash": "e" * 64}
    model = _rehash(model)
    path = C.STORE_RELATIVE / "models/fixture.json"
    P._immutable(root / path, model)
    P._append(root, C.MODEL_LEDGER, {"ledger_id": "model-fixture", "training_month": "2026-10",
              "available_at": model["available_at"], "train_cutoff": model["train_cutoff"],
              "artifact_path": path.as_posix(), "artifact_hash": model["content_hash"]})
    inputs["market_features"] = [{"series_id": "CPIAUCSL", "observation_time": "2026-09-01",
                                  "available_at": "2026-10-14T12:30:00Z", "retrieved_at": "2026-10-14T12:31:00Z"}]
    run = P.build_context(root, as_of=ISSUED, save_paths=False)
    assert run["status"] == "research_preview", run
    assert run["numerical_context_applied"] is True and run["score"] < 0
    assert run["anchor"] == inputs["anchor"]
    assert run["delta_log"][20] < 0 and len(set(run["delta_log"][62:])) == 1
    assert all(row["candidate_median"] < row["baseline_median"] for row in run["comparison"]["horizons"])
    assert run["state_summary"]["events"][0]["used_numerically"] is True
    assert P.verify_context(root, replay=True)["ok"]
    assert P.fit_context(root, train_cutoff=ISSUED)["status"] == "skipped"


def test_future_coefficient_availability_does_not_leak_into_issuance(context):
    root, _ = context
    P._append(root, C.MODEL_LEDGER, {"ledger_id": "future-model", "training_month": "2026-11",
              "available_at": "2026-11-01T00:00:00Z", "artifact_path": "does/not/exist.json", "artifact_hash": "f" * 64})
    assert P._load_coefficients(root, ISSUED) is None


def test_verify_rejects_unreferenced_missing_model_artifact(context):
    root, _ = context
    P._append(root, C.MODEL_LEDGER, {"ledger_id": "missing-model", "training_month": "2026-10",
              "available_at": ISSUED, "artifact_path": "data/market_context/models/missing.json", "artifact_hash": "f" * 64})
    result = P.verify_context(root)
    assert not result["ok"] and "missing.json" in result["errors"][0]


def test_workflow_is_daily_keyless_scoped_and_watched():
    import yaml
    text = (ROOT / ".github/workflows/market-context-daily.yml").read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    triggers = document.get("on", document.get(True))
    assert triggers["schedule"][0]["cron"] == "20 5 * * *"
    assert "secrets." not in text and "FRED_API_KEY" not in text
    assert "git add data/market_context" in text
    assert "group: investing-data-writer" in text
    assert text.index("market-context-collect") < text.index("market-context-build")
    assert 'report["as_of"]' in text
    assert 'market-context-build --as-of "$MARKET_CONTEXT_AS_OF"' in text
    assert 'market-context-fit --train-cutoff "$MARKET_CONTEXT_AS_OF"' in text
    assert "git add data/scenarios" not in text
    for name in ("pages.yml", "verify.yml", "ops-failure-alert.yml"):
        assert "market-context-daily" in (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
