from __future__ import annotations

import gzip
import io
import json
import urllib.error
import zipfile
from pathlib import Path

import pytest

from ai_fc.cli import _v4_retrying_fetcher
from ai_fc.timeseries_v4.contracts import MODEL_ID, contract_hash, load_v4_contract
from ai_fc.timeseries_v4.source_store import (
    ParsedValue,
    append_observations,
    parse_cboe_index,
    parse_cboe_market_volume,
    parse_cleveland_nowcast,
    parse_spf_release_dates,
    parse_spf_workbook,
    persist_raw,
    read_v4_observations,
    verify_v4_source_store,
)
from ai_fc.timeseries_v4.features import _asof_series
from ai_fc.timeseries_v4.pipeline import _origin_risk_scores, verify_v4_run


ROOT = Path(__file__).resolve().parents[2]


def test_v4_contract_keeps_predecessors_and_gate_immutable():
    contract = load_v4_contract(ROOT)
    assert contract["model_id"] == MODEL_ID
    assert contract["inherits"]["v2_market_and_macro_ledgers_read_only"] is True
    assert contract["inherits"]["v3_fixed_comparator_read_only"] is True
    assert contract["research_gate"]["long_horizon_mean_crps_improvement_min"] == 0.02
    assert contract["publication"]["customer_numbers_visible_before_all_gates"] is False
    assert len(contract_hash(ROOT)) == 64


def test_cboe_index_and_market_volume_are_explicitly_timed_and_scaled():
    index = b"DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2020,10,12,9,11\n"
    rows = parse_cboe_index(index, series_id="VIX9D")
    assert rows[0].series_id == "VIX9D"
    assert rows[0].observation_time == "2020-01-02"
    assert rows[0].available_at > "2020-01-02T00:00:00+00:00"

    volume = (
        "Day,Market Participant,Tape C Notional,Total Notional,Total Trade Count\n"
        "2020-01-02,NASDAQ (Q),25,100,10\n"
        "2020-01-02,FINRA / Nasdaq TRF,25,50,5\n"
    ).encode()
    parsed = {row.series_id: row for row in parse_cboe_market_volume(volume)}
    assert parsed["US_EQ_TAPE_C_NOTIONAL_SHARE"].value == pytest.approx(1 / 3)
    assert parsed["US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE"].value == pytest.approx(1 / 3)
    assert parsed["US_EQ_TOTAL_TRADES"].value == 15


def test_cleveland_archive_preserves_as_of_and_target_period():
    payload = [{
        "chart": {"subcaption": "2020-1"},
        "categories": [{"category": [{"label": "12/31"}, {"label": "01/02"}]}],
        "dataset": [{"seriesname": "CPI Inflation", "data": [{"value": "0.2"}, {"value": "0.3"}]}],
    }]
    rows = parse_cleveland_nowcast(json.dumps(payload).encode(), frequency="month")
    assert [row.observation_time for row in rows] == ["2019-12-31", "2020-01-02"]
    assert rows[1].dimensions == {"target_period": "2020-1", "frequency": "month"}
    assert rows[1].data_grade == "reconstructed_official_forecast_archive"


def _minimal_xlsx() -> bytes:
    workbook = b'''<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Mean" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    rels = b'''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>'''
    sheet = b'''<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>YEAR</t></is></c><c r="B1" t="inlineStr"><is><t>QUARTER</t></is></c><c r="C1" t="inlineStr"><is><t>RECESS1</t></is></c></row><row r="2"><c r="A2"><v>2020</v></c><c r="B2"><v>1</v></c><c r="C2"><v>12.5</v></c></row></sheetData></worksheet>'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def test_spf_release_date_and_xlsx_become_pit_forecast_facts():
    dates = parse_spf_release_dates(b"2020 Q1  2/11/20  2/14/20\n     Q2  5/12/20  5/15/20\n")
    assert dates[(2020, 1)] == "2020-02-14"
    assert dates[(2020, 2)] == "2020-05-15"
    rows = parse_spf_workbook(_minimal_xlsx(), family="RECESS", release_dates=dates, statistic="MEAN")
    assert rows[0].series_id == "SPF_RECESS_MEAN_RECESS1"
    assert rows[0].observation_time == "2020-02-14"
    assert rows[0].value == 12.5


def test_raw_receipt_observation_and_revision_are_append_only(tmp_path):
    receipt = persist_raw(
        tmp_path, source_id="cboe_vix9d", source_uri="https://cdn.cboe.com/x.csv",
        payload=b"one", retrieved_at="2020-01-03T00:00:00+00:00", content_type="text/csv",
    )
    first = ParsedValue(
        "VIX9D", "2020-01-02", 11.0, "index", "2020-01-02T21:15:00+00:00",
        "reconstructed_market_archive", {},
    )
    assert append_observations(tmp_path, [first], receipt)["appended"] == 1
    second_receipt = persist_raw(
        tmp_path, source_id="cboe_vix9d", source_uri="https://cdn.cboe.com/x.csv",
        payload=b"two", retrieved_at="2020-01-04T00:00:00+00:00", content_type="text/csv",
    )
    assert append_observations(tmp_path, [first], second_receipt)["appended"] == 0
    revised = ParsedValue(
        "VIX9D", "2020-01-02", 11.5, "index", "2020-01-04T00:00:00+00:00",
        "captured_forward", {},
    )
    assert append_observations(tmp_path, [revised], second_receipt)["appended"] == 1
    rows = read_v4_observations(tmp_path)
    assert len(rows) == 1 and rows[0].revision_seq == 2 and rows[0].supersedes
    assert verify_v4_source_store(tmp_path)["ok"] is True
    with gzip.open(tmp_path / receipt.raw_path, "rb") as handle:
        assert handle.read() == b"one"


def test_availability_alignment_never_backfills_before_release():
    import pandas as pd

    sessions = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    rows = [{
        "available_at": "2020-01-03T15:00:00+00:00",
        "value": 12.5,
        "revision_seq": 1,
        "observation_id": "one",
    }]
    aligned = _asof_series(rows, sessions, name="forecast")
    assert pd.isna(aligned.loc["2020-01-02"])
    assert aligned.loc["2020-01-03"] == 12.5
    assert aligned.loc["2020-01-06"] == 12.5


def test_origin_risk_score_uses_only_prior_rows():
    import pandas as pd

    frame = pd.DataFrame(
        {"one": list(range(100)), "two": [1.0] * 100},
        index=pd.date_range("2020-01-01", periods=100, freq="B"),
    )
    settings = {
        "anomaly_history_sessions": 80,
        "anomaly_minimum_observations": 60,
        "anomaly_aggregation_quantile": 0.75,
        "input_features": ["one", "two"],
    }
    day = frame.index[80].date().isoformat()
    score, audit = _origin_risk_scores(frame, [day], settings=settings)
    changed = frame.copy()
    changed.loc[changed.index[81]:, "one"] = 1e9
    replay, _ = _origin_risk_scores(changed, [day], settings=settings)
    assert score == replay
    assert audit["feature_use_min"] == 2


def test_repository_v4_run_is_hash_bound_and_fail_closed():
    result = verify_v4_run(ROOT)
    assert result["ok"] is True
    assert result["gate_pass"] is False
    assert result["status"] == "shadow_gate_hold"
    assert result["customer_numbers_visible"] is False


def test_v4_collect_fetcher_retries_read_timeouts_with_backoff_then_succeeds():
    calls = {"count": 0}
    naps: list[float] = []

    def flaky(url: str):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("The read operation timed out")
        return 200, b"DATE,VALUE\n2026-08-29,100\n", "text/csv"

    fetch = _v4_retrying_fetcher(flaky, sleep=naps.append)
    status, payload, content_type = fetch("https://example.invalid/fredgraph.csv")
    assert status == 200
    assert payload.startswith(b"DATE")
    assert content_type == "text/csv"
    assert calls["count"] == 3
    assert naps == [2.0, 4.0]


def test_v4_collect_fetcher_is_bounded_and_never_retries_http_answers():
    naps: list[float] = []

    def always_times_out(url: str):
        raise TimeoutError("The read operation timed out")

    with pytest.raises(TimeoutError):
        _v4_retrying_fetcher(always_times_out, attempts=3, sleep=naps.append)("https://example.invalid/x")
    assert len(naps) == 2  # bounded: attempts-1 backoffs, no infinite loop

    http_calls = {"count": 0}

    def definitive_answer(url: str):
        http_calls["count"] += 1
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    with pytest.raises(urllib.error.HTTPError):
        _v4_retrying_fetcher(definitive_answer, sleep=naps.append)("https://example.invalid/x")
    assert http_calls["count"] == 1  # an HTTP status is information, not noise
