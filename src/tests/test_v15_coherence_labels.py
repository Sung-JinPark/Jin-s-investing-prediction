"""V15 xnas_v1 라벨 — 진단 원장 함수와의 동일성·미성숙·개정 정정 행 (spec_U3 §8 L1~L3).

실아카이브는 as_of 고정으로 1회만 읽는다. 쓰기는 tmp 사본만. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_fc.timeseries_v15.labels import NasdaqArchive, XnasCalendar, xnas_label
from v15_coherence_fixtures import ROOT, REAL_CUTOFF, Obs, make_root, nasdaq_observations, set_track_open


@pytest.fixture(scope="module")
def real_observations():
    from ai_fc.timeseries_v2.market_archive import read_market_observations

    return read_market_observations(ROOT, knowledge_cutoff=REAL_CUTOFF)


def test_l1_matches_research_diagnostic_labels_at_v8_origins(real_observations) -> None:
    from ai_fc.mts_research import v8_xnas_labels as research

    as_of = date(2026, 11, 10)
    rows = [json.loads(line) for line in
            (ROOT / "data/timeseries_v8/ledgers/shadow_forecasts.jsonl").read_text(encoding="utf-8").splitlines() if line]
    origins = sorted({date.fromisoformat(row["origin"]) for row in rows})
    assert len(origins) >= 12
    research_cal = research.XnasCalendar.build(date(1995, 1, 1), date(2027, 6, 30))
    research_archive = research.NasdaqArchive.from_observations(real_observations, as_of=as_of)
    cal = XnasCalendar.build(date(1995, 1, 1), date(2027, 6, 30))
    archive = NasdaqArchive.from_observations(real_observations, as_of=as_of)
    compared = 0
    for origin in origins:
        for h in (1, 5, 21, 63):
            target = research.xnas_target_session(origin, h, research_cal)
            labelled = xnas_label(origin, h, cal, archive)
            if target > as_of or target not in research_archive.closes:
                assert labelled is None
                continue
            assert labelled is not None and labelled[0] == target
            assert abs(labelled[1] - research._log_return(research_archive, origin, target)) <= 1e-15
            assert archive.input_hash([origin, target]) == research_archive.input_hash([origin, target])
            compared += 1
    assert compared >= 29  # V8 원장 해소 29행 규모 이상의 원점·지평


def test_l2_immature_target_is_none() -> None:
    observations = nasdaq_observations("2026-10-01", "2026-11-06")
    cal = XnasCalendar.build(date(2026, 1, 2), date(2027, 3, 31))
    archive = NasdaqArchive.from_observations(observations, as_of=date(2026, 11, 6))
    assert xnas_label(date(2026, 10, 30), 5, cal, archive) is not None
    assert xnas_label(date(2026, 11, 6), 1, cal, archive) is None


def test_l3_archive_revision_appends_supersedes_row(tmp_path: Path) -> None:
    from ai_fc.timeseries_v15.pipeline import collect_staged, read_ledger, resolve_v15
    from ai_fc.timeseries_v15.contracts import RESOLUTION_LEDGER
    from v15_coherence_fixtures import stage_payload, v8_row, write_stage, write_v8_rows

    root = make_root(tmp_path, track_open=True)
    reference = v8_row("2026-10-02", "2026-10-06T03:10:00+00:00")
    write_v8_rows(root, [reference])
    staging = tmp_path / "staging"
    for arm in ("A0", "A1", "A2", "A3", "A4"):
        write_stage(staging, arm, stage_payload(root, arm, reference))
    collect_staged(root, staging=staging, expected_arms=["A0", "A1", "A2", "A3", "A4"],
                   v8_forecast_id=reference["forecast_id"], now=datetime(2026, 10, 7, tzinfo=timezone.utc))
    first = nasdaq_observations("2026-09-01", "2026-10-09")
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    result = resolve_v15(root, now=now, observations=first)
    assert result["resolved"] == 5 * 2  # h1·h5 성숙
    revised = [row if row.observation_time != "2026-10-09" else
               Obs(row.series_id, row.observation_time, row.value * 1.01, observation_id="rev", revision_seq=2,
                   supersedes=row.observation_id) for row in first]
    again = resolve_v15(root, now=datetime(2026, 10, 11, 12, tzinfo=timezone.utc), observations=revised)
    assert again["corrections"] == 5  # h5 목표(10-09)만 바뀐다
    rows = read_ledger(root, RESOLUTION_LEDGER)
    corrections = [row for row in rows if row["supersedes"]]
    assert len(corrections) == 5 and all(row["horizon"] == 5 for row in corrections)
    assert all(row["resolution_id"].endswith("-xnas_v1-r2") for row in corrections)
    unchanged = resolve_v15(root, now=datetime(2026, 10, 12, 12, tzinfo=timezone.utc), observations=revised)
    assert unchanged["resolved"] == 0
