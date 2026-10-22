from __future__ import annotations

import calendar
import io
import zipfile
from datetime import date
from pathlib import Path
import shutil

import pytest

from ai_fc.statistics_native import NativeCollector, NativeSourceError, H6, parse_native, verify_overlap, collect_current


def monthly_zip(*, adjustment="SA", unit="1e+09", value="100", duplicate=False):
    observations = ''.join(
        f'<Obs OBS_STATUS="A" OBS_VALUE="{value}" TIME_PERIOD="{year}-{month:02d}-{calendar.monthrange(year, month)[1]}"/>'
        for year in [2024, 2025] for month in range(1, 13)
    )
    if duplicate:
        observations += '<Obs OBS_STATUS="A" OBS_VALUE="100" TIME_PERIOD="2024-01-31"/>'
    xml = f'<Root><Series SERIES_NAME="M2.M" FREQ="129" UNIT="Currency" UNIT_MULT="{unit}" ADJUSTED="{adjustment}">{observations}</Series></Root>'
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as z:
        z.writestr("H6_data.xml", xml)
    return target.getvalue()


def test_native_same_month_label_units_and_full_exact_overlap():
    raw = monthly_zip()
    rows = parse_native(raw, "M2SL", cutoff=date(2026, 1, 1))
    assert rows[0] == {"date": "2024-01-01", "value": 100}
    assert rows[-1]["date"] == "2025-12-01"
    assert verify_overlap(rows, rows)["observations"] == 24
    calls = []
    collector = NativeCollector(lambda url: calls.append(url) or raw)
    for _ in range(2):
        result, original, meta = collector.fetch("M2SL", start="2024-01-01", cutoff=date(2026, 1, 1), previous=rows)
        assert original == raw and result == rows
        assert meta["policy_source_id"] == "federal_reserve_board"
        assert meta["refresh_status"] == "verified_native_fallback"
    assert calls == [H6]


@pytest.mark.parametrize("kwargs", [{"adjustment": "NSA"}, {"unit": "1e+06"}, {"value": "NaN"}, {"value": "inf"}, {"duplicate": True}])
def test_native_rejects_identity_unit_nonfinite_and_duplicate_changes(kwargs):
    with pytest.raises(NativeSourceError):
        parse_native(monthly_zip(**kwargs), "M2SL", cutoff=date(2026, 1, 1))


def test_native_rejects_future_truncation_and_differing_vintage():
    raw = monthly_zip()
    with pytest.raises(NativeSourceError, match="future"):
        parse_native(raw, "M2SL", cutoff=date(2024, 1, 1))
    rows = parse_native(raw, "M2SL", cutoff=date(2026, 1, 1))
    with pytest.raises(NativeSourceError, match="coverage"):
        verify_overlap(rows[:-1], rows)
    with pytest.raises(NativeSourceError, match="differs"):
        verify_overlap([dict(x, value=101) for x in rows], rows)


def test_native_does_not_accept_unregistered_price_proxy():
    with pytest.raises(KeyError):
        parse_native(monthly_zip(), "NASDAQCOM", cutoff=date(2026, 1, 1))


def test_verified_retained_cache_keeps_original_clock_and_rejects_tampering(tmp_path, monkeypatch):
    from test_statistics_lab import _append_official_persistence_batch
    from ai_fc import statistics_lab as lab
    from ai_fc.fred_api import FredApiError
    from ai_fc.authoritative_statistics import read_raw_artifact_receipts, RawArtifactMissing
    _append_official_persistence_batch(tmp_path, raw_tag="fixture", fetched_at="2026-04-01T00:00:00+00:00")
    contracts = tmp_path / "data/contracts"
    contracts.mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[2]/"data/contracts/authoritative_statistics_sources.yaml", contracts)
    store = tmp_path / "data/statistics/official_store"
    receipt = next(r for r in read_raw_artifact_receipts(store) if r.source_id=="fred_market_signals" and "M2SL" in r.series_ids)
    prior = {"series_id":"M2SL", "policy_source_id":"fred_market_signals", "raw_sha256":receipt.raw_sha256,
             "raw_path":"data/statistics/official_store/"+receipt.artifact_path,
             "latest_observation":"2026-01-01", "available_at":receipt.fetched_at,
             "request_url":receipt.source_uri}
    monkeypatch.setattr(lab,"load_statistics_lab",lambda _: {"sources":[prior]})
    def unavailable(_):raise FredApiError("html; 3 attempts")
    def failed_native(_):raise OSError("fixture unavailable")
    rows, raws, meta = collect_current(tmp_path, {"M2SL":lab.FRED_SERIES["M2SL"]}, fetcher=unavailable, request=failed_native, cutoff=date(2026,4,2))
    assert raws=={} and rows["M2SL"]==[{"date":"2026-01-01","value":100}]
    assert meta["M2SL"]["available_at"]==receipt.fetched_at
    assert meta["M2SL"]["refresh_status"]=="verified_cache_waiting_source"
    def invalid_schema(_):raise FredApiError("invalid observations schema")
    with pytest.raises(FredApiError, match="schema"):
        collect_current(tmp_path, {"M2SL":lab.FRED_SERIES["M2SL"]}, fetcher=invalid_schema, request=failed_native, cutoff=date(2026,4,2))
    with pytest.raises(NativeSourceError, match="regressed"):
        collect_current(tmp_path, {"M2SL":lab.FRED_SERIES["M2SL"]}, fetcher=lambda _:([],b""), request=failed_native, cutoff=date(2026,4,2))
    (store/receipt.artifact_path).write_bytes(b"tampered fixture")
    with pytest.raises(RawArtifactMissing):
        collect_current(tmp_path, {"M2SL":lab.FRED_SERIES["M2SL"]}, fetcher=unavailable, request=failed_native, cutoff=date(2026,4,2))


def test_shared_native_and_z1_raw_declares_all_extracted_series(tmp_path, monkeypatch):
    import test_statistics_lab as fixtures
    from ai_fc import statistics_lab as lab
    from ai_fc.statistics_native import Z1
    from ai_fc.authoritative_statistics import read_raw_artifact_receipts
    original = lab._persist_authoritative_inputs
    native_ids = ["BOGZ1LM153064475Q", "BOGZ1LM893064105Q"]
    def shared(*args, **kwargs):
        for sid in native_ids:
            kwargs["raw_payloads"][sid] = kwargs["raw_payloads"][lab.Z1_PRIMARY_SERIES]
        kwargs["source_metadata"] = {sid: {"policy_source_id":"federal_reserve_board", "request_url":Z1, "media_type":"application/zip"} for sid in native_ids}
        return original(*args, **kwargs)
    monkeypatch.setattr(fixtures,"_persist_authoritative_inputs",shared)
    _candidates, appended = fixtures._append_official_persistence_batch(tmp_path, raw_tag="shared-zip-fixture", fetched_at="2026-04-01T00:00:00+00:00")
    native = [row for row in appended if row.series_id in native_ids]
    assert len(native)==2 and all(row.source_id=="federal_reserve_board" for row in native)
    receipts = [r for r in read_raw_artifact_receipts(tmp_path/"data/statistics/official_store") if r.raw_sha256==native[0].raw_sha256]
    assert receipts and all(set(native_ids)|set(lab.Z1_SERIES)<=set(r.series_ids) for r in receipts)
