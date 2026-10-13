"""Daily display forecast: same frozen inference, display-only, never scored.

사용자 결정 2026-10-07 — 화면은 매일, 채점은 주간. 네트워크 없이 고정 입력만 쓴다.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from ai_fc import config
from ai_fc import timeseries_v8_daily as daily
from ai_fc import timeseries_v8_display as display
from ai_fc.timeseries_v8 import pipeline
from ai_fc.timeseries_v8.contracts import (
    CONTRACT_RELATIVE,
    canonical_hash,
    frozen_coordinates,
    frozen_hash,
    load_contract_v8,
)

REPO = Path(config.ROOT)
NOW = datetime(2026, 10, 7, 5, 49, tzinfo=timezone.utc)   # KST 14:49 — FRED 는 아직 10-05

TREASURY_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
 <entry><content type="application/xml"><m:properties>
  <d:NEW_DATE>2026-10-05T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.84</d:BC_2YEAR><d:BC_10YEAR>5.31</d:BC_10YEAR>
 </m:properties></content></entry>
 <entry><content type="application/xml"><m:properties>
  <d:NEW_DATE>2026-10-06T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.79</d:BC_2YEAR><d:BC_10YEAR>5.27</d:BC_10YEAR>
 </m:properties></content></entry>
</feed>"""
TREASURY_CSV = (
    b'Date,"1 Mo","2 Yr","10 Yr"\r\n10/06/2026,4.06,4.79,5.27\r\n10/05/2026,4.05,4.84,5.31\r\n'
)
FRED_NASDAQ = b"observation_date,NASDAQCOM\n2026-10-05,27477.31\n2026-10-06,27599.89\n"


# ── fixtures ────────────────────────────────────────────────────────────────

def _observation(series: str, day: str, value: float, *, available_at: str) -> dict:
    seed = {"series": series, "day": day, "value": value}
    digest = canonical_hash(seed)
    return {
        "observation_id": f"market-observation-{digest[:24]}", "source_id": f"fixture_{series}",
        "series_id": series, "observation_time": day, "value": value,
        "unit": "index" if series in ("NASDAQCOM", "VIX", "DTWEXBGS") else "percentage_point",
        "available_at": available_at, "data_grade": "captured_forward",
        "vintage_start": available_at, "vintage_end": None, "raw_sha256": digest,
        "receipt_id": f"market-receipt-{digest[:24]}", "revision_seq": 1, "supersedes": None,
        "parser_version": "official-market-archive-v2.1",
    }


SESSIONS = ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05")
LEVELS = {
    "NASDAQCOM": (26700.0, 26800.0, 26871.6, 27190.86, 27477.31),
    "VIX": (16.2, 16.34, 16.39, 15.31, 15.52),
    "DGS2": (4.80, 4.81, 4.82, 4.83, 4.84),
    "DGS10": (5.25, 5.26, 5.27, 5.28, 5.31),
}
DOLLAR = {"2026-09-29": 121.0296, "2026-09-30": 120.9693, "2026-10-01": 121.7882, "2026-10-02": 121.3848}


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / CONTRACT_RELATIVE).parent.mkdir(parents=True)
    shutil.copyfile(REPO / CONTRACT_RELATIVE, root / CONTRACT_RELATIVE)
    rows = []
    for series, values in LEVELS.items():
        for day, value in zip(SESSIONS, values):
            rows.append(_observation(series, day, value, available_at="2026-10-06T08:09:42+00:00"))
    for day, value in DOLLAR.items():
        rows.append(_observation("DTWEXBGS", day, value, available_at="2026-10-06T08:09:42+00:00"))
    archive = root / "data/timeseries_v2/ledgers/market_observations.jsonl"
    archive.parent.mkdir(parents=True)
    archive.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    vix = root / daily.VIX_LATEST_RELATIVE
    vix.parent.mkdir(parents=True)
    vix.write_text(json.dumps({
        "observed_date": "2026-10-06", "source_url": "https://cdn.cboe.com/vix.csv",
        "latest_source": "cboe_delayed_quote", "latest_source_url": "https://cdn.cboe.com/_VIX.json",
        "trail": [{"d": "2026-10-05", "v": 15.52}, {"d": "2026-10-06", "v": 15.01}],
    }), encoding="utf-8")
    return root


def _fetcher(*, treasury: bytes = TREASURY_XML, fred: bytes | None = FRED_NASDAQ):
    def fetch(url: str) -> bytes:
        if "treasury.gov" in url:
            return treasury
        if "fred.stlouisfed.org" in url:
            if fred is None:
                raise OSError("fred unavailable")
            return fred
        raise AssertionError(f"unexpected url {url}")
    return fetch


def _no_quote() -> dict:
    raise OSError("no quote in tests")


# ── provisional publisher fills ─────────────────────────────────────────────

def test_treasury_xml_and_csv_carry_the_same_two_and_ten_year_values() -> None:
    from ai_fc.timeseries_v2.market_archive import parse_treasury_xml

    assert sorted(parse_treasury_xml(TREASURY_XML)) == sorted(daily.parse_treasury_csv(TREASURY_CSV))
    fills = daily.treasury_fills(["2026-10-06"], fetcher=_fetcher(), retrieved_at="t")
    assert {(row["series_id"], row["value"]) for row in fills} == {("DGS2", 4.79), ("DGS10", 5.27)}
    assert all(row["provisional"] is True and row["source"] == "us_treasury_daily_par_yield_curve"
               for row in fills)


def test_fills_stop_at_the_first_hole_instead_of_bridging_it() -> None:
    xml = TREASURY_XML.replace(b"2026-10-05", b"2026-09-01")
    fills = daily.treasury_fills(["2026-10-05", "2026-10-06"], fetcher=_fetcher(treasury=xml),
                                 retrieved_at="t")
    assert fills == [], "10-05 가 없으면 10-06 을 10-02 에 직접 잇지 않는다"


def test_vix_fill_uses_the_morning_projection_then_the_closed_cboe_quote(tmp_path: Path) -> None:
    root = _root(tmp_path)
    fills = daily.vix_fills(root, ["2026-10-06"], retrieved_at="t", now=NOW, quote_fetcher=_no_quote)
    assert fills[0]["value"] == 15.01 and fills[0]["source"] == "cboe_delayed_quote"
    (root / daily.VIX_LATEST_RELATIVE).unlink()
    closed = {"data": {"close": 15.01, "last_trade_time": "2026-10-06T16:15:01"}}
    from_quote = daily.vix_fills(root, ["2026-10-06"], retrieved_at="t", now=NOW,
                                 quote_fetcher=lambda: closed)
    assert from_quote[0]["value"] == 15.01
    intraday = {"data": {"close": 15.4, "last_trade_time": "2026-10-06T11:00:00"}}
    assert daily.vix_fills(root, ["2026-10-06"], retrieved_at="t", now=NOW,
                           quote_fetcher=lambda: intraday) == []


def test_nasdaq_fill_prefers_fred_then_the_closed_quote_files(tmp_path: Path) -> None:
    root = _root(tmp_path)
    fred = daily.nasdaq_fills(root, ["2026-10-06"], fetcher=_fetcher(), retrieved_at="t")
    assert fred[0]["value"] == 27599.89 and fred[0]["source"] == "fred_nasdaqcom"
    quote = root / daily.NASDAQ_LATEST_RELATIVE
    quote.parent.mkdir(parents=True)
    quote.write_text(json.dumps({"session_date": "2026-10-06", "close": 27599.79,
                                 "market_status": "Closed", "source_url": "https://api.nasdaq.com"}),
                     encoding="utf-8")
    fallback = daily.nasdaq_fills(root, ["2026-10-06"], fetcher=_fetcher(fred=None), retrieved_at="t")
    assert fallback[0]["value"] == 27599.79 and fallback[0]["source"] == "nasdaq_quote_api_comp"
    quote.write_text(json.dumps({"session_date": "2026-10-06", "close": 27650.0,
                                 "market_status": "Open"}), encoding="utf-8")
    assert daily.nasdaq_fills(root, ["2026-10-06"], fetcher=None, retrieved_at="t") == []


def test_collect_inputs_fills_only_missing_sessions_and_carries_the_dollar(tmp_path: Path) -> None:
    root = _root(tmp_path)
    contract = load_contract_v8(root)
    inputs = daily.collect_inputs(root, contract=contract, now=NOW, fetcher=_fetcher(),
                                  quote_fetcher=_no_quote)
    assert inputs["expected_session"] == "2026-10-06"
    filled = {(row["series_id"], row["observation_time"]) for row in inputs["fills"]}
    assert filled == {("NASDAQCOM", "2026-10-06"), ("VIX", "2026-10-06"),
                      ("DGS2", "2026-10-06"), ("DGS10", "2026-10-06")}
    carried = {row["observation_time"]: row for row in inputs["carried"]}
    assert set(carried) == {"2026-10-05", "2026-10-06"}
    assert all(row["carried_from"] == "2026-10-02" and row["provisional"] is False
               for row in carried.values())


# ── bundle overlay: in memory only, frozen transforms, no fabrication ───────

def test_overlay_extends_the_frozen_frame_without_writing_the_archive(tmp_path: Path) -> None:
    from ai_fc.timeseries_v2 import features

    root = _root(tmp_path)
    archive = root / "data/timeseries_v2/ledgers/market_observations.jsonl"
    before = archive.read_bytes()
    contract = load_contract_v8(root)
    cutoff = NOW.isoformat()
    base, _ = features.build_core_market_frame(root, knowledge_cutoff=cutoff)
    assert base.index[-1].date().isoformat() == "2026-10-02", "주간 원점과 같은 이유: 달러가 10-02 까지"
    inputs = daily.collect_inputs(root, contract=contract, now=NOW, fetcher=_fetcher(),
                                  quote_fetcher=_no_quote)
    with daily.market_overlay(daily._overlay_rows(inputs)):
        frame, _ = features.build_core_market_frame(root, knowledge_cutoff=cutoff)
    assert frame.index[-1].date().isoformat() == "2026-10-06"
    assert frame.loc["2026-10-06", "dollar_change"] == 0.0
    assert frame.loc["2026-10-06", "nasdaq_return"] == pytest.approx(np.log(27599.89 / 27477.31))
    assert frame.loc["2026-10-06", "dgs2_change_bps"] == pytest.approx(-5.0)
    # 패치는 컨텍스트 밖으로 새지 않고 아카이브 파일은 바이트 그대로다.
    after, _ = features.build_core_market_frame(root, knowledge_cutoff=cutoff)
    assert after.index[-1] == base.index[-1]
    assert archive.read_bytes() == before


def test_missing_publisher_series_falls_back_to_the_latest_complete_session(tmp_path: Path) -> None:
    from ai_fc.timeseries_v2 import features

    root = _root(tmp_path)
    (root / daily.VIX_LATEST_RELATIVE).unlink()   # VIX 10-06 원천 없음
    contract = load_contract_v8(root)
    inputs = daily.collect_inputs(root, contract=contract, now=NOW, fetcher=_fetcher(),
                                  quote_fetcher=_no_quote)
    assert not any(row["series_id"] == "VIX" for row in inputs["fills"])
    with daily.market_overlay(daily._overlay_rows(inputs)):
        frame, _ = features.build_core_market_frame(root, knowledge_cutoff=NOW.isoformat())
    assert frame.index[-1].date().isoformat() == "2026-10-05", "모든 필수 계열이 있는 마지막 세션"


# ── same inference call as the weekly shadow forecast ───────────────────────

class _Captured(Exception):
    pass


def test_daily_inference_passes_the_weekly_argument_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    contract = load_contract_v8(root)
    bundle = SimpleNamespace(
        dates=("2026-10-01", "2026-10-02"), endogenous=np.zeros((2, 5)), exogenous=np.zeros((2, 3)),
        endogenous_names=("a",), exogenous_names=("b",),
    )
    calls: list[dict] = []

    def recorder(**kwargs):
        calls.append(kwargs)
        raise _Captured

    monkeypatch.setattr(pipeline, "walk_forward_dev_backtest_v8", recorder)
    monkeypatch.setattr(pipeline, "verify_v2_benchmark", lambda *a, **k: {})
    monkeypatch.setattr(pipeline, "require_dfm_runtime", lambda: None)
    monkeypatch.setattr(pipeline, "_sealed_gate_passed", lambda root: {"run_id": "tsv8-sealed-test"})
    monkeypatch.setattr(pipeline, "_sealed_bundle", lambda root, contract: bundle)
    with pytest.raises(_Captured):
        pipeline.shadow_forecast_timeseries_v8(root)
    with pytest.raises(_Captured):
        daily.frozen_inference(contract, daily.frozen_config(contract), bundle)
    weekly, daily_call = calls
    assert weekly.keys() == daily_call.keys()
    for key in weekly:
        if key == "config":
            assert weekly[key].as_manifest() == daily_call[key].as_manifest()
        else:
            assert weekly[key] is daily_call[key] or weekly[key] == daily_call[key], key


# ── ledger: append, idempotence, supersede, scoring exclusion ───────────────

def _fake_forecast(origin: str) -> dict:
    grid = list(np.linspace(-0.1, 0.12, 200))
    return {
        "origin": origin, "grid_levels_count": 200,
        "ensemble_weights": {"expanding": 0.5, "rolling": 0.5}, "block_length": 10,
        "ewma_lambda": 0.94,
        "horizons": {
            key: {"quantile_grid": grid, "baseline_quantile_grid": grid, "p_up": 0.6,
                  "blend_weight": 1.0, "recalibrated": True, "matured_pit_count": 900}
            for key in ("1", "5", "21", "63")
        },
    }


def _wire_heavy_parts(monkeypatch: pytest.MonkeyPatch, *, sealed: dict) -> list[str]:
    """Replace the 2007~ replay with a stub; keep the real overlay → frame path."""
    from ai_fc.timeseries_v2 import contracts as v2_contracts
    from ai_fc.timeseries_v2 import features

    origins: list[str] = []

    def bundle(root, contract):
        # 실제 _sealed_bundle 은 now() 를 컷오프로 쓴다 — 고정 시각 테스트에서는 먼 미래로 둔다.
        frame, _ = features.build_core_market_frame(root, knowledge_cutoff="2100-01-01T00:00:00+00:00")
        dates = tuple(item.date().isoformat() for item in frame.index)
        return SimpleNamespace(dates=dates, endogenous=frame.to_numpy(), exogenous=np.zeros((len(dates), 2)),
                               endogenous_names=tuple(frame.columns), exogenous_names=("g", "i"))

    def walk(**kwargs):
        origins.append(kwargs["outer_end"])
        return [SimpleNamespace(date="2019-01-04")], {"shadow_forecast": _fake_forecast(kwargs["dates"][-1])}

    monkeypatch.setattr(pipeline, "_sealed_bundle", bundle)
    monkeypatch.setattr(pipeline, "walk_forward_dev_backtest_v8", walk)
    monkeypatch.setattr(pipeline, "_sealed_gate_passed", lambda root: sealed)
    monkeypatch.setattr(daily, "verify_v2_benchmark", lambda *a, **k: {})
    monkeypatch.setattr(daily, "model_code_hash", lambda root: "d" * 64)
    monkeypatch.setattr(v2_contracts, "require_dfm_runtime", lambda: None)
    return origins


def _append_archive(root: Path, rows: list[dict]) -> None:
    archive = root / "data/timeseries_v2/ledgers/market_observations.jsonl"
    with archive.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_daily_rows_append_supersede_and_never_touch_weekly_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    origins = _wire_heavy_parts(monkeypatch, sealed={"run_id": "tsv8-sealed-test"})
    first = daily.daily_forecast_timeseries_v8(root, now=NOW, fetcher=_fetcher(), quote_fetcher=_no_quote)
    assert first["appended"] is True and first["origin"] == "2026-10-06"
    assert first["input_state"] == "provisional"
    assert first["provisional_series"] == ["DGS10", "DGS2", "NASDAQCOM", "VIX"]
    again = daily.daily_forecast_timeseries_v8(root, now=NOW, fetcher=_fetcher(), quote_fetcher=_no_quote)
    assert "already recorded" in again["skipped"] and origins == ["2026-10-06"], "재실행은 추론도 안 돈다"
    # FRED/H.15 가 10-06 을 확정 → 같은 원점의 confirmed 행이 supersedes 로 앞 행을 가리킨다.
    confirmed_at = "2026-10-07T20:00:00+00:00"
    _append_archive(root, [
        _observation("NASDAQCOM", "2026-10-06", 27599.89, available_at=confirmed_at),
        _observation("VIX", "2026-10-06", 15.01, available_at=confirmed_at),
        _observation("DGS2", "2026-10-06", 4.79, available_at=confirmed_at),
        _observation("DGS10", "2026-10-06", 5.27, available_at=confirmed_at),
    ])
    later = datetime(2026, 10, 7, 20, 30, tzinfo=timezone.utc)
    second = daily.daily_forecast_timeseries_v8(root, now=later, fetcher=None)
    assert second["input_state"] == "confirmed" and second["supersedes"] == first["display_id"]
    rows = daily.read_daily_rows(root)
    assert len(rows) == 2 and rows[1]["anchor"]["provisional"] is False
    assert rows[0]["provisional_inputs"][0]["provisional"] is True
    assert daily.latest_effective(rows)["display_id"] == second["display_id"]
    assert all(row["scoring_excluded"] is True and row["display_only"] is True for row in rows)
    assert daily.verify_daily_display(root)["ok"] is True
    # 주간 원장은 생기지도 않았고, 해소·전진 성적은 일일 행을 보지 않는다.
    assert not (root / pipeline.SHADOW_FORECAST_LEDGER).exists()
    assert not (root / pipeline.SHADOW_RESOLUTION_LEDGER).exists()
    assert pipeline.shadow_resolve_timeseries_v8(root, bundle=SimpleNamespace(dates=()))["resolved"] == 0
    assert display._forward_resolutions(root) == []
    # 확정 행 뒤에 잠정 상태가 다시 와도 대체하지 않는다.
    third = daily.daily_forecast_timeseries_v8(root, now=later, fetcher=None)
    assert "skipped" in third


def test_verify_flags_a_supersede_across_origins_and_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    _wire_heavy_parts(monkeypatch, sealed={"run_id": "tsv8-sealed-test"})
    daily.daily_forecast_timeseries_v8(root, now=NOW, fetcher=_fetcher(), quote_fetcher=_no_quote)
    ledger = root / daily.DAILY_LEDGER_RELATIVE
    ledger.write_text(ledger.read_text(encoding="utf-8").replace('"p_up":0.6', '"p_up":0.7'),
                      encoding="utf-8")
    result = daily.verify_daily_display(root)
    assert result["ok"] is False and any("hash" in error for error in result["errors"])


def test_existing_weekly_ledger_is_byte_identical_after_a_daily_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    for relative in (pipeline.SHADOW_FORECAST_LEDGER, pipeline.SHADOW_RESOLUTION_LEDGER):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, root / relative)
    before = {relative: (root / relative).read_bytes()
              for relative in (pipeline.SHADOW_FORECAST_LEDGER, pipeline.SHADOW_RESOLUTION_LEDGER)}
    _wire_heavy_parts(monkeypatch, sealed={"run_id": "tsv8-sealed-test"})
    daily.daily_forecast_timeseries_v8(root, now=NOW, fetcher=_fetcher(), quote_fetcher=_no_quote)
    for relative, body in before.items():
        assert (root / relative).read_bytes() == body
    assert daily.verify_daily_display(root)["ok"] is True


# ── pointer and display ─────────────────────────────────────────────────────

def _sealed_ledger(root: Path) -> None:
    path = root / pipeline.SEALED_LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "run_id": "tsv8-sealed-test",
        "summary": {"gate_pass": True, "origin_count": 1011, "horizons": {
            "21": {"crps_improvement_vs_best": 0.04, "coverage_p10_p90": 0.81},
            "63": {"crps_improvement_vs_best": 0.03, "coverage_p10_p90": 0.80}}},
    }) + "\n", encoding="utf-8")


def test_pointer_measures_freshness_on_the_inputs_the_row_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    _sealed_ledger(root)
    _wire_heavy_parts(monkeypatch, sealed={"run_id": "tsv8-sealed-test"})
    daily.daily_forecast_timeseries_v8(root, now=NOW, fetcher=_fetcher(), quote_fetcher=_no_quote)
    monkeypatch.undo()
    pointer = daily.publish_daily_display_latest(root, now=NOW)
    display.validate_latest(pointer)
    assert pointer["publication"]["customer_numbers_visible"] is True, pointer["gate"]["reasons"]
    assert pointer["as_of"] == "2026-10-06" and pointer["daily"]["input_state"] == "provisional"
    groups = {row["group"]: row for row in pointer["operational"]["freshness"]}
    assert groups["VIX"]["observation_time"] == "2026-10-06" and groups["VIX"]["provisional"] is True
    assert groups["DTWEXBGS_or_DTWEXB"]["observation_time"] == "2026-10-02"
    # 사흘 뒤까지 갱신이 멈추면 같은 포인터 로직이 신선도 보류로 닫는다.
    stale = daily.publish_daily_display_latest(root, now=datetime(2026, 10, 10, 6, tzinfo=timezone.utc))
    assert stale["publication"]["customer_numbers_visible"] is False and "horizons" not in stale


def test_display_prefers_the_daily_pointer_and_labels_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    _sealed_ledger(root)
    _wire_heavy_parts(monkeypatch, sealed={"run_id": "tsv8-sealed-test"})
    daily.daily_forecast_timeseries_v8(root, now=NOW, fetcher=_fetcher(), quote_fetcher=_no_quote)
    monkeypatch.undo()
    pointer = daily.publish_daily_display_latest(root, now=NOW)
    weekly = json.loads(json.dumps(pointer))
    weekly.pop("daily")
    weekly.pop("content_hash")
    weekly["as_of"] = "2026-10-02"
    weekly["content_hash"] = canonical_hash(weekly)
    (root / display.LATEST_RELATIVE).write_text(json.dumps(weekly), encoding="utf-8")
    projection = display.load_projection(root)
    assert projection is not None
    assert projection["as_of"] == "2026-10-06" and projection["cadence"] == "daily"
    assert projection["weekly_as_of"] == "2026-10-02"
    assert projection["input_state"] == "provisional"
    assert projection["anchor"] == {"series_id": "NASDAQCOM", "value": 27599.89, "provisional": True}
    assert projection["history"]["dates"][-2:] == ["2026-10-05", "2026-10-06"]
    assert projection["origin_age_sessions"] == 0, "원점 나이는 일일 원점에서 잰다"
    # 일일 포인터가 주간보다 낡으면 주간 표면으로 돌아간다(주간 경로는 그대로).
    stale_daily = json.loads((root / display.DAILY_LATEST_RELATIVE).read_text(encoding="utf-8"))
    stale_daily.pop("content_hash")
    stale_daily["as_of"] = "2026-09-25"
    stale_daily["content_hash"] = canonical_hash(stale_daily)
    (root / display.DAILY_LATEST_RELATIVE).write_text(json.dumps(stale_daily), encoding="utf-8")
    monkeypatch.setattr(display, "_anchor_and_history", lambda root, origin, cutoff: (
        27190.86, {"dates": ["2026-10-02"], "index": [27190.86]}))
    fallback = display.load_projection(root)
    assert fallback["as_of"] == "2026-10-02" and fallback["cadence"] == "weekly"


def test_daily_hold_pointer_keeps_metadata_without_numbers(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _sealed_ledger(root)
    pointer = daily.publish_daily_display_latest(root, now=NOW)   # 일일 행 없음 → HOLD
    assert pointer["publication"]["customer_numbers_visible"] is False
    assert pointer["as_of"] is None
    original = (root / display.DAILY_LATEST_RELATIVE).read_bytes()
    projection = display.load_projection(root)
    assert projection["model_id"] == pointer["model_id"]
    assert projection["as_of"] is None and projection["cadence"] == "daily"
    assert projection["knowledge_cutoff"] == pointer["knowledge_cutoff"]
    assert projection["gate"]["reasons"] == pointer["gate"]["reasons"]
    assert projection["numbers_visible"] is False
    assert projection["horizons"] == {} and projection["path"] == {}
    assert "anchor" not in projection and "history" not in projection
    assert (root / display.DAILY_LATEST_RELATIVE).read_bytes() == original


# ── contract and workflow ───────────────────────────────────────────────────

def test_daily_display_policy_lives_outside_the_frozen_coordinates() -> None:
    contract = load_contract_v8(REPO)
    policy = contract["daily_display_policy"]
    assert "daily_display_policy" not in frozen_coordinates(contract)
    assert policy["scoring"] == "excluded"
    assert policy["decision"]["date"] == "2026-10-07"
    assert policy["ledger"] == daily.DAILY_LEDGER_RELATIVE.as_posix()
    assert policy["pointer"] == daily.DAILY_LATEST_RELATIVE.as_posix()
    assert contract["evaluation"]["origin_frequency"] == "weekly_last_completed_session"
    assert frozen_hash(contract) == (
        "7c56ee4eaa5697823c71c504e524354a70d643d20b555de69120f11ac55f785b"
    ), "봉인·섀도 원장이 고정한 contract_hash 가 바뀌면 안 된다"


def test_daily_module_stays_outside_the_hashed_model_package() -> None:
    from ai_fc.timeseries_v8.contracts import model_code_hash

    assert not (REPO / "src/ai_fc/timeseries_v8/daily.py").exists()
    weekly_hashes = {
        json.loads(line)["model_code_hash"]
        for line in (REPO / pipeline.SHADOW_FORECAST_LEDGER).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert model_code_hash(REPO) in weekly_hashes, "주간 원장의 모델 코드 정체성이 그대로여야 한다"


def test_daily_workflow_triggers_lock_and_registration() -> None:
    directory = REPO / ".github" / "workflows"
    text = (directory / "timeseries-v8-daily.yml").read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    on = document.get(True) or document.get("on")
    assert on["workflow_run"]["workflows"] == ["market-mood-refresh", "timeseries-v2-refresh"]
    assert "workflow_dispatch" in on and len(on["schedule"]) == 2
    assert document["name"] == "timeseries-v8-daily"
    commit = document["jobs"]["commit"]
    assert commit["concurrency"] == {"group": "investing-data-writer", "cancel-in-progress": False}
    assert "concurrency" not in document["jobs"]["forecast"], "긴 계산 잡은 공용 쓰기 잠금을 쥐지 않는다"
    assert "workflow_run.conclusion == 'success'" in document["jobs"]["forecast"]["if"]
    assert "workflow_run.head_branch == 'main'" in document["jobs"]["forecast"]["if"]
    assert "python -m ai_fc timeseries-v8-daily" in text
    assert "unexpected daily paths" in text and "git pull --rebase origin main" in text
    assert "shadow_forecasts" not in text, "일일 워크플로는 주간 원장을 쓰지 않는다"
    alert = yaml.safe_load((directory / "ops-failure-alert.yml").read_text(encoding="utf-8"))
    assert "timeseries-v8-daily" in (alert.get(True) or alert.get("on"))["workflow_run"]["workflows"]
    for name in ("pages.yml", "verify.yml"):
        assert '"timeseries-v8-daily"' in (directory / name).read_text(encoding="utf-8")
