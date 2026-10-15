"""Source overlay boundaries and daily-rate continuity, entirely synthetic."""

from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest

from ai_fc.timeseries_daily6m import features as F
from ai_fc.timeseries_daily6m import live_tail as L
from ai_fc.timeseries_daily6m.contracts import Daily6mContractError


AS_OF = "2026-10-15T02:30:00+00:00"
ORIGIN = "2026-10-14"


def native(series, day, value):
    return {"source_id": "alfred", "series_id": series, "observation_time": day, "value": value,
            "value_status": "ok", "available_at": "2026-10-14T03:59:59+00:00",
            "vintage_start": "2026-10-14T03:59:59+00:00", "vintage_end": None,
            "retrieved_at": "2026-10-14T05:00:00+00:00", "source_hash": "a" * 64}


def frame(*, completed=False):
    days = ["2026-10-09", "2026-10-12", "2026-10-13"] + ([ORIGIN] if completed else [])
    rows = [native(sid, day, 100 + i if sid == "NASDAQCOM" else 15 + i / 10)
            for i, day in enumerate(days) for sid in ("NASDAQCOM", "VIXCLS")]
    rows += [native("DGS2", "2026-10-09", 4.8), native("DTWEXBGS", "2026-10-09", 110)]
    rows += [native("T10Y2Y", day, 0.42) for day in days]
    if completed:
        rows += [native("DGS2", "2026-10-13", 4.79), native("DGS2", ORIGIN, 4.82)]
    return F.eligible_frame(rows, as_of=AS_OF)


def source(source_id, day, value):
    raw, _, unit = L.REGISTERED_SOURCES[source_id]
    uri = {"nasdaq_comp_official": "https://api.nasdaq.com/api/quote/COMP/info?assetclass=index",
           "cboe_vix_archive": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
           "us_treasury_yield_archive": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026"}[source_id]
    stamp = "2026-10-14T22:00:00+00:00"
    digest = hashlib.sha256((source_id + day).encode()).hexdigest()
    return {"source_id": source_id, "series_id": raw, "observation_time": day, "value": value,
            "unit": unit, "source_unit": unit, "data_grade": "captured_forward",
            "available_at": stamp, "vintage_start": stamp, "vintage_end": None, "retrieved_at": stamp,
            "raw_sha256": digest, "receipt_id": "receipt-" + source_id + day,
            "observation_id": "observation-" + source_id + day, "revision_seq": 1, "supersedes": None,
            "receipt_raw_path": f"data/timeseries_daily6m/raw/{source_id}/{digest}.gz",
            "receipt_source_uri": uri, "receipt_http_status": 200, "receipt_verified": True,
            "receipt_response_uri": uri, "receipt_response_uri_recorded": True,
            "native_overlap_verified": True, "native_overlap_count": 20, "native_overlap_max_abs_delta": 0.0}


def observations():
    return [source("nasdaq_comp_official", ORIGIN, 103), source("cboe_vix_archive", ORIGIN, 15.3),
            source("us_treasury_yield_archive", "2026-10-13", 4.79),
            source("us_treasury_yield_archive", ORIGIN, 4.82)]


def test_holiday_bridge_keeps_actual_daily_rate_moves_and_all_receipt_lineage(tmp_path):
    import pandas as pd
    base = frame()
    original = base.copy(deep=True)
    tails = L.select_live_tails(base, observations(), as_of=AS_OF, completed=ORIGIN)
    assert {r["observation_time"] for r in tails if r["series_id"] == "DGS2"} == {"2026-10-13", ORIGIN}
    assert all(r["observation_time"] != "2026-10-12" for r in tails)
    merged = F.eligible_frame(pd.concat([base, pd.DataFrame(tails)], ignore_index=True), as_of=AS_OF)
    factor = {"cutoff": "2026-10-08T00:00:00+00:00", "status": "ready", "cache_id": "fixture",
              "input_hash": "b" * 64, "content_hash": "c" * 64,
              "cache_materialized_at": "2026-10-08T00:00:00+00:00",
              "factors": {"growth_factor": 0.1, "inflation_factor": 0.2}}
    bundle = F.build_bundle(tmp_path, as_of=AS_OF, rows=merged, factor_entries=[factor])
    np.testing.assert_allclose(bundle.endogenous[:, 2], [0, -1, 3], atol=1e-12)
    assert bundle.anchor["date"] == ORIGIN and bundle.anchor["value"] == 103
    holiday = next(r for r in bundle.lineage["market_rows"] if r["series_id"] == "DGS2" and r["session"] == "2026-10-12")
    assert holiday["observation_time"] == "2026-10-09" and holiday["carried"] is True
    assert bundle.lineage["captured_tail_used"] is True
    assert all(r["receipt_response_uri_recorded"] is True and r["receipt_response_uri"] == r["receipt_source_uri"]
               for r in bundle.lineage["market_rows"] if r["source_id"] != "alfred")
    L.validate_tail_lineage_rows(bundle.lineage["market_rows"], ORIGIN)
    assert all(r["data_grade"] == "captured_forward" for r in bundle.lineage["market_rows"] if r["source_id"] != "alfred")
    pd.testing.assert_frame_equal(base, original)


def test_current_eligible_native_values_win_without_any_overlay():
    assert L.select_live_tails(frame(completed=True), observations(), as_of=AS_OF, completed=ORIGIN) == []


def test_native_only_overlay_is_identical_and_does_not_create_store(tmp_path):
    base = frame(completed=True)
    assert L.overlay_live_tails(tmp_path, base, as_of=AS_OF, completed=ORIGIN) is base
    assert not (tmp_path / "data").exists()


def test_missing_treasury_open_session_is_rejected_instead_of_aggregating_daily_move():
    rows = [r for r in observations() if r["observation_time"] != "2026-10-13"]
    with pytest.raises(Daily6mContractError, match="missing required quotes"):
        L.select_live_tails(frame(), rows, as_of=AS_OF, completed=ORIGIN)


def test_price_tail_does_not_fill_an_interior_native_gap():
    base = frame()
    base = base[~((base.series_id == "NASDAQCOM") & (base.day == "2026-10-13"))]
    with pytest.raises(Daily6mContractError, match="interior"):
        L.select_live_tails(base, observations(), as_of=AS_OF, completed=ORIGIN)


@pytest.mark.parametrize("change", [
    {"receipt_source_uri": "https://evil.example/data"}, {"source_unit": "basis_points"},
    {"receipt_verified": False}, {"receipt_http_status": 403}, {"native_overlap_verified": False},
    {"native_overlap_count": 4}, {"native_overlap_max_abs_delta": 0.01},
    {"available_at": "2026-10-15T02:31:00+00:00"},
])
def test_bad_receipt_unit_identity_and_future_capture_fail(change):
    rows = copy.deepcopy(observations())
    rows[0].update(change)
    with pytest.raises(Daily6mContractError):
        L.select_live_tails(frame(), rows, as_of=AS_OF, completed=ORIGIN)


def test_bridge_more_than_five_xnas_sessions_fails():
    base = frame()
    base.loc[base.series_id == "DGS2", ["day", "observation_time"]] = "2026-10-01"
    with pytest.raises(Daily6mContractError, match="five XNAS"):
        L.select_live_tails(base, observations(), as_of=AS_OF, completed=ORIGIN)


def test_lineage_cannot_hide_missing_bridge_observation():
    tails = L.select_live_tails(frame(), observations(), as_of=AS_OF, completed=ORIGIN)
    rows = [{**r, "session": r["observation_time"]} for r in tails if r["observation_time"] != "2026-10-13"]
    with pytest.raises(Daily6mContractError, match="omits"):
        L.validate_tail_lineage_rows(rows, ORIGIN)


def test_lineage_cannot_carry_captured_yield_across_an_unfilled_open_day():
    tails = L.select_live_tails(frame(), observations(), as_of=AS_OF, completed=ORIGIN)
    rows = [{**r, "session": r["observation_time"]} for r in tails]
    next(r for r in rows if r["series_id"] == "DGS2" and r["observation_time"] == "2026-10-13")["session"] = ORIGIN
    with pytest.raises(Daily6mContractError, match="incomplete"):
        L.validate_tail_lineage_rows(rows, ORIGIN)
