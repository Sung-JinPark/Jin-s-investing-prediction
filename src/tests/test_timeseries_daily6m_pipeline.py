"""Isolated input, publication, and append-only daily6m regression checks."""

from __future__ import annotations

import copy
import json
import gzip
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_daily6m import contracts as C, display as D, features as F, model as M, pipeline as P

ISSUED = "2026-09-12T12:00:00+00:00"


def _fact(series: str, day: str, value: float, *, available: str = "2026-09-12T00:00:00+00:00") -> dict:
    return {"source_id": "alfred", "series_id": series, "observation_time": day, "value": value, "value_status": "ok", "available_at": available, "vintage_start": available, "vintage_end": None, "retrieved_at": available, "source_hash": "a" * 64}


def _fresh_frame():
    rows = [_fact(sid, "2026-09-11", value) for sid, value in (("NASDAQCOM", 100), ("VIXCLS", 15), ("DGS2", 4), ("T10Y2Y", 0.5), ("DTWEXBGS", 110))]
    return F.eligible_frame(rows, as_of=ISSUED)


def _factor(cutoff: str, growth: float = 0.1, inflation: float = 0.2) -> dict:
    return {"cutoff": cutoff, "status": "ready", "cache_id": "fixture-factor", "input_hash": "c" * 64, "content_hash": "d" * 64, "cache_materialized_at": cutoff, "factors": {"growth_factor": growth, "inflation_factor": inflation}}


def _official_vix_fixture(root: Path, *, captured="2026-09-12T00:00:00+00:00"):
    payload = b"DATE,OPEN,HIGH,LOW,CLOSE\n09/11/2026,15.0,15.3,14.9,15.2\n"
    digest = hashlib.sha256(payload).hexdigest()
    raw = Path("data/timeseries_v2/raw/market/cboe_vix_archive") / (digest + ".gz")
    (root / raw).parent.mkdir(parents=True, exist_ok=True)
    (root / raw).write_bytes(gzip.compress(payload))
    observation = {"observation_id": "fixture-vix", "series_id": "VIX", "observation_time": "2026-09-11", "source_id": "cboe_vix_archive", "value": 15.2, "unit": "index", "data_grade": "captured_forward", "available_at": captured, "vintage_start": captured, "vintage_end": None, "raw_sha256": digest, "receipt_id": "fixture-receipt", "revision_seq": 1}
    receipt = {"receipt_id": "fixture-receipt", "source_id": "cboe_vix_archive", "retrieved_at": captured, "http_status": 200, "raw_sha256": digest, "raw_path": raw.as_posix(), "source_uri": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"}
    ledger = root / "data/timeseries_v2/ledgers"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "market_observations.jsonl").write_text(json.dumps(observation) + "\n", encoding="utf-8")
    (ledger / "market_raw_receipts.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    return observation, receipt


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_contract", lambda root: {"identity": "fixed"})
    monkeypatch.setattr(C, "model_code_hash", lambda root: "b" * 64)
    aware = F.aware_time
    monkeypatch.setattr(F, "aware_time", lambda value=None: aware(ISSUED if value is None else value))
    frame = _fresh_frame()
    monkeypatch.setattr(F, "read_native_frame", lambda root, as_of: frame.copy())
    source = {"session": "2026-09-11", "series_id": "NASDAQCOM", "source_id": "alfred", "source_hash": "a" * 64, "available_at": "2026-09-12T00:00:00+00:00", "vintage_start": "2026-09-12T00:00:00+00:00", "retrieved_at": "2026-09-12T00:00:00+00:00"}
    lineage = {"source": "native_alfred_vintages", "market_rows": [{**source, "series_id": sid} for sid in ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y", "DTWEXBGS")], "factor_rows": [_factor("2026-09-01T00:00:00+00:00")], "mapping": {"curve_change_bps": "T10Y2Y"}}
    bundle = F.Daily6mFeatureBundle(tuple(["2026-09-11"] * 800), np.ones((800, 5)), np.ones((800, 3)), F.ENDOG_NAMES, F.EXOG_NAMES, {"date": "2026-09-11", "value": 100.0, "series_id": "NASDAQCOM", "available_at": "2026-09-12T00:00:00+00:00"}, {"dates": ["2026-09-11"], "index": [100.0]}, lineage, (), F.source_freshness(frame, ISSUED), 0)
    monkeypatch.setattr(F, "build_bundle", lambda *args, **kwargs: bundle)

    def generate(bundle, *, anchor, as_of, future_dates, **kwargs):
        slopes = np.linspace(-0.1, 0.1, C.PATH_COUNT)[:, None]
        paths = anchor * np.exp(slopes * np.linspace(1 / len(future_dates), 1, len(future_dates))[None, :])
        records, samples = M.summarize_joint_paths(paths, anchor=anchor, future_dates=future_dates)
        body = {"records": records, "sample_paths": samples, "path_count": C.PATH_COUNT, "path_hash": M._path_hash(paths), "comparison": {"v8_raw_identity": {"pass": True}, "fhs": {"status": "reported"}}, "content_hash": "original-model-hash"}
        return body, paths

    monkeypatch.setattr(M, "generate_forecast_with_paths", generate)
    run = P.forecast_timeseries_daily6m(tmp_path, as_of=ISSUED)
    return tmp_path, run, frame


def test_input_vintage_and_capture_are_separate_and_future_data_rejected():
    prior = _fact("NASDAQCOM", "2026-09-11", 100)
    future = {**prior, "value": 999, "available_at": "2026-09-13T00:00:00+00:00", "vintage_start": "2026-09-13T00:00:00+00:00"}
    selected = F.eligible_frame([prior, future], as_of=ISSUED)
    assert selected.iloc[0]["value"] == 100
    late_capture = {**prior, "retrieved_at": "2026-09-13T00:00:00+00:00"}
    with pytest.raises(F.Daily6mFeatureError, match="captured after"):
        F.eligible_frame([late_capture], as_of=ISSUED)
    with pytest.raises(F.Daily6mFeatureError, match="timezone"):
        F.aware_time("2026-09-12T12:00:00")


def test_intraday_observation_cannot_enter_a_completed_close_forecast():
    row = _fact("NASDAQCOM", "2026-09-14", 100, available="2026-09-14T16:00:00+00:00")
    with pytest.raises(F.Daily6mFeatureError, match="completed"):
        F.eligible_frame([row], as_of="2026-09-14T18:00:00+00:00")


def test_rates_and_fx_carries_are_audited_but_price_vix_gaps_hold(tmp_path):
    rows = [_fact(sid, day, value) for day in ("2026-09-10", "2026-09-11") for sid, value in (("NASDAQCOM", 100), ("VIXCLS", 15))]
    rows.extend(_fact(sid, "2026-09-10", value) for sid, value in (("DGS2", 4), ("T10Y2Y", 0.5), ("DTWEXBGS", 110)))
    factors = [_factor("2026-09-09T00:00:00+00:00")]
    bundle = F.build_bundle(tmp_path, as_of=ISSUED, rows=rows, factor_entries=factors)
    carried = [row for row in bundle.lineage["market_rows"] if row["session"] == "2026-09-11" and row["carried"]]
    assert {row["series_id"] for row in carried} == {"DGS2", "T10Y2Y", "DTWEXBGS"}
    assert bundle.endogenous[0, 2:].tolist() == [0, 0, 0]
    gap = F.build_bundle(tmp_path, as_of=ISSUED, rows=[row for row in rows if not (row["series_id"] == "VIXCLS" and row["observation_time"] == "2026-09-11")], factor_entries=factors)
    assert "daily gap VIXCLS 2026-09-11" in gap.issues


def test_fx_bridge_uses_same_series_predecessor_and_retains_its_lineage(tmp_path):
    stamp = "2019-01-03T12:00:00+00:00"
    available = "2019-01-03T00:00:00+00:00"
    rows = [_fact(sid, day, value, available=available) for day in ("2018-12-31", "2019-01-02") for sid, value in (("NASDAQCOM", 100), ("VIXCLS", 15), ("DGS2", 4), ("T10Y2Y", 0.5))]
    rows.extend([_fact("DTWEXB", "2018-12-31", 10, available=available), _fact("DTWEXBGS", "2018-12-31", 100, available=available), _fact("DTWEXBGS", "2019-01-02", 101, available=available)])
    factors = [_factor("2018-12-30T00:00:00+00:00")]
    bundle = F.build_bundle(tmp_path, as_of=stamp, rows=rows, factor_entries=factors)
    assert bundle.endogenous[0, 4] == pytest.approx(np.log(1.01))
    assert any(row.get("role") == "registered_fx_bridge_previous_observation" for row in bundle.lineage["market_rows"])


def test_new_known_factor_at_intraday_issuance_keeps_training_rows_unchanged(tmp_path):
    available = "2026-09-15T00:00:00+00:00"
    rows = [_fact(sid, day, value, available=available) for day in ("2026-09-11", "2026-09-14") for sid, value in (("NASDAQCOM", 100), ("VIXCLS", 15), ("DGS2", 4), ("T10Y2Y", 0.5), ("DTWEXBGS", 110))]
    factors = [_factor("2026-09-10T00:00:00+00:00"), _factor("2026-09-15T14:00:00+00:00", 0.3, 0.4)]
    bundle = F.build_bundle(tmp_path, as_of="2026-09-15T16:00:00+00:00", rows=rows, factor_entries=factors)
    assert bundle.exogenous[-1, :2].tolist() == [0.1, 0.2]
    assert bundle.issuance_exogenous[:2].tolist() == [0.3, 0.4]
    assert bundle.issuance_factor_lineage["cutoff"] == "2026-09-15T14:00:00+00:00"


def test_leading_native_coverage_warmup_is_disclosed_and_retained_gaps_still_hold(tmp_path):
    available = "2026-09-12T00:00:00+00:00"
    # An isolated early native point must not turn the unobserved pre-training
    # interval into a permanent HOLD after a complete common range begins.
    rows = [_fact("NASDAQCOM", "2026-09-04", 100, available=available)]
    rows += [_fact(sid, day, value, available=available) for day in ("2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11") for sid, value in (("VIXCLS", 15), ("DGS2", 4), ("T10Y2Y", 0.5), ("DTWEXBGS", 110))]
    rows += [_fact("NASDAQCOM", day, 100, available=available) for day in ("2026-09-09", "2026-09-10", "2026-09-11")]
    bundle = F.build_bundle(tmp_path, as_of=ISSUED, rows=rows, factor_entries=[_factor("2026-09-01T00:00:00+00:00")])
    assert bundle.dates[0] == "2026-09-10"
    assert bundle.lineage["initial_unavailable_sessions"] > 0
    assert {"series_id": "NASDAQCOM", "session": "2026-09-08"} in bundle.lineage["initial_missing_daily_inputs"]
    assert not any(reason.startswith("daily gap") for reason in bundle.issues)
    missing_tail = [row for row in rows if not (row["series_id"] == "VIXCLS" and row["observation_time"] == "2026-09-11")]
    blocked = F.build_bundle(tmp_path, as_of=ISSUED, rows=missing_tail, factor_entries=[_factor("2026-09-01T00:00:00+00:00")])
    assert "daily gap VIXCLS 2026-09-11" in blocked.issues


def test_registered_current_official_vix_tail_resolves_only_latest_native_lag(tmp_path):
    observation, _ = _official_vix_fixture(tmp_path)
    tail = F.captured_vix_tail(tmp_path, session="2026-09-11", as_of=ISSUED)
    assert tail["data_grade"] == "captured_forward" and tail["series_id"] == "VIXCLS"
    assert tail["source_hash"] == observation["raw_sha256"]
    rows = [_fact(sid, day, value) for day in ("2026-09-10", "2026-09-11") for sid, value in (("NASDAQCOM", 100), ("DGS2", 4), ("T10Y2Y", 0.5), ("DTWEXBGS", 110))]
    rows += [_fact("VIXCLS", "2026-09-10", 15), tail]
    bundle = F.build_bundle(tmp_path, as_of=ISSUED, rows=rows, factor_entries=[_factor("2026-09-01T00:00:00+00:00")])
    assert not any(reason.startswith("daily gap VIXCLS") for reason in bundle.issues)
    assert bundle.endogenous[-1, 1] == pytest.approx(np.log(15.2 / 15))
    assert bundle.lineage["source"] == "native_alfred_vintages_plus_official_captured_tail"
    source = [row for row in bundle.lineage["market_rows"] if row["source_id"] == "cboe_vix_archive"][0]
    assert source["receipt_id"] == "fixture-receipt" and source["data_grade"] == "captured_forward"
    with pytest.raises(F.Daily6mFeatureError, match="latest completed"):
        F.captured_vix_tail(tmp_path, session="2026-09-10", as_of=ISSUED)


def test_official_vix_tail_denies_future_capture_and_invalid_receipt(tmp_path):
    _official_vix_fixture(tmp_path, captured="2026-09-13T00:00:00+00:00")
    with pytest.raises(F.Daily6mFeatureError, match="available at issuance"):
        F.captured_vix_tail(tmp_path, session="2026-09-11", as_of=ISSUED)
    _, receipt = _official_vix_fixture(tmp_path)
    receipt["source_id"] = "unregistered_provider"
    (tmp_path / "data/timeseries_v2/ledgers/market_raw_receipts.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    with pytest.raises(F.Daily6mFeatureError, match="valid CBOE raw receipt"):
        F.captured_vix_tail(tmp_path, session="2026-09-11", as_of=ISSUED)


def test_official_vix_tail_verifies_actual_source_value(tmp_path):
    observation, _ = _official_vix_fixture(tmp_path)
    observation["value"] = 999
    (tmp_path / "data/timeseries_v2/ledgers/market_observations.jsonl").write_text(json.dumps(observation) + "\n", encoding="utf-8")
    with pytest.raises(F.Daily6mFeatureError, match="raw source close"):
        F.captured_vix_tail(tmp_path, session="2026-09-11", as_of=ISSUED)


def test_stale_sources_short_circuit_before_feature_or_model_work(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "load_contract", lambda root: {})
    frame = _fresh_frame()
    monkeypatch.setattr(F, "read_native_frame", lambda *args, **kwargs: frame)
    monkeypatch.setattr(F, "build_bundle", lambda *args, **kwargs: pytest.fail("stale inputs reached fitting"))
    result = P.forecast_timeseries_daily6m(tmp_path, as_of="2026-10-12T03:00:00+00:00")
    assert result["status"] == "hold" and result["numbers_visible"] is False
    assert "records" not in result and not (tmp_path / C.FORECAST_LEDGER).exists()


def test_publish_replay_and_immutable_paths_are_independent(published):
    root, run, _ = published
    assert run["forecast_end_date"] == run["dates"][-1]
    assert run["calendar_end_date"] == "2027-03-11"
    assert run["probability_space"] == "research_timeseries_daily6m_conditional"
    artifact = root / run["joint_path_artifact"]["path"]
    assert artifact.is_relative_to(root / "outputs/timeseries_daily6m/paths")
    assert P.verify_timeseries_daily6m(root)["ok"]
    prior = (root / C.FORECAST_LEDGER).read_bytes()
    replay = P.forecast_timeseries_daily6m(root, as_of=ISSUED)
    assert replay["run_id"] == run["run_id"]
    assert (root / C.FORECAST_LEDGER).read_bytes() == prior
    P.publish_latest_timeseries_daily6m(root, as_of=ISSUED)
    first = D.load_projection(root, now=F.aware_time(ISSUED))
    second = D.load_projection(root, now=F.aware_time("2026-09-12T12:00:01+00:00"))
    assert first["projection_hash"] == second["projection_hash"]
    assert "market_rows" not in first["source_lineage"]
    stale = D.load_projection(root, now=F.aware_time("2026-10-12T03:00:00+00:00"))
    assert stale["status"] == "hold" and "records" not in stale


def test_supersedes_preserves_prior_and_scoring_covers_both_revisions(published, monkeypatch):
    root, run, frame = published
    original = (root / C.FORECAST_LEDGER).read_bytes()
    revision = P.forecast_timeseries_daily6m(root, as_of="2026-09-12T12:01:00+00:00", supersedes=run["run_id"])
    assert revision["supersedes"] == run["run_id"]
    assert (root / C.FORECAST_LEDGER).read_bytes().startswith(original)
    with pytest.raises(P.Daily6mPipelineError, match="active revision"):
        P.forecast_timeseries_daily6m(root, as_of="2026-09-12T12:02:00+00:00", supersedes=run["run_id"])
    actual = F.eligible_frame([_fact("NASDAQCOM", "2026-09-11", 100), _fact("NASDAQCOM", "2026-09-14", 102, available="2026-09-15T00:00:00+00:00")], as_of="2026-09-15T12:00:00+00:00")
    monkeypatch.setattr(F, "read_native_frame", lambda *args, **kwargs: actual)
    assert P.resolve_timeseries_daily6m(root, as_of="2026-09-15T12:00:00+00:00")["resolved"] == 2
    assert P.resolve_timeseries_daily6m(root, as_of="2026-09-15T12:00:00+00:00")["resolved"] == 0
    resolutions = P.read_chain(root, C.RESOLUTION_LEDGER)
    assert {row["forecast_id"] for row in resolutions} == {run["run_id"], revision["run_id"]}
    assert all(row["brier"] == 0.25 for row in resolutions)


def test_rehashed_invalid_probability_or_calendar_cannot_display(published):
    root, run, _ = published
    invalid = copy.deepcopy(run)
    invalid["records"][0]["probability_up_from_previous"] = 51
    invalid["content_hash"] = C.canonical_hash({key: value for key, value in invalid.items() if key != "content_hash"})
    with pytest.raises(P.Daily6mPipelineError, match="fraction"):
        P.validate_run(invalid)
    invalid = copy.deepcopy(run)
    invalid["dates"] = invalid["dates"][1:]
    invalid["records"] = invalid["records"][1:]
    invalid["content_hash"] = C.canonical_hash({key: value for key, value in invalid.items() if key != "content_hash"})
    with pytest.raises(P.Daily6mPipelineError, match="six calendar"):
        P.validate_run(invalid)


def test_missing_or_corrupt_latest_always_returns_non_numeric_status(tmp_path):
    assert D.load_projection(tmp_path)["status"] == "absent"
    path = tmp_path / C.LATEST_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"model_id": C.MODEL_ID, "content_hash": "bad"}), encoding="utf-8")
    result = D.load_projection(tmp_path)
    assert result["status"] == "hold" and result["numbers_visible"] is False


def test_absent_pointer_imports_without_optional_numerical_packages(tmp_path):
    script = f"""import builtins,sys
sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r})
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {{'pandas','pyarrow','exchange_calendars'}}:
        raise ModuleNotFoundError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from pathlib import Path
from ai_fc.timeseries_daily6m.display import load_projection
assert load_projection(Path({str(tmp_path)!r}))['status']=='absent'
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_active_pointer_missing_runtime_fails_closed(published, monkeypatch):
    root, _, _ = published
    P.publish_latest_timeseries_daily6m(root, as_of=ISSUED)
    def unavailable(*args, **kwargs):
        raise ModuleNotFoundError("pandas")
    monkeypatch.setattr(F, "read_native_frame", unavailable)
    result = D.load_projection(root, now=F.aware_time(ISSUED))
    assert result["status"] == "hold" and "records" not in result


def test_writer_lock_is_exclusive_and_released(tmp_path):
    with P.writer_lock(tmp_path):
        with pytest.raises(P.Daily6mPipelineError, match="writer"):
            with P.writer_lock(tmp_path):
                pytest.fail("second writer acquired an occupied lock")
    with P.writer_lock(tmp_path):
        pass


def test_no_forecast_pointer_preserves_real_stale_preflight_reasons(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "read_native_frame", lambda *args, **kwargs: _fresh_frame())
    absent = P.publish_latest_timeseries_daily6m(tmp_path, as_of=ISSUED)
    assert absent["status"] == "absent" and absent["numbers_visible"] is False
    stale = P.publish_latest_timeseries_daily6m(tmp_path, as_of="2026-10-12T10:00:00+00:00")
    assert stale["status"] == "hold" and stale["as_of"] == "2026-10-12T10:00:00+00:00"
    assert "required source NASDAQCOM stale" in stale["gate"]["reasons"]
    assert len(stale["evidence"]["source_freshness"]) == 5
    assert not (tmp_path / C.FORECAST_LEDGER).exists()
    assert "records" not in stale and "dates" not in stale
    assert D.load_projection(tmp_path)["gate"]["reasons"] == stale["gate"]["reasons"]
