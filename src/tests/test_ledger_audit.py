from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from ai_fc.ledger_audit import audit_ledgers, has_violations
from ai_fc.research_pack import export_research_pack


CALENDAR = """version: 1
calendar: NYSE
rules: []
one_off_closures: []
"""


def _root(tmp_path: Path, registry: str) -> Path:
    (tmp_path / "data/contracts").mkdir(parents=True)
    (tmp_path / "docs/generated").mkdir(parents=True)
    (tmp_path / "data/contracts/nyse_holidays.yaml").write_text(CALENDAR, encoding="utf-8")
    (tmp_path / "data/contracts/ledger_registry.yaml").write_text(registry, encoding="utf-8")
    return tmp_path


def test_audit_baselines_then_detects_immutable_change(tmp_path: Path) -> None:
    root = _root(tmp_path, """version: 1
ledgers:
  - id: events
    path: data/events/*.json
    kind: archive_dir
    cadence: event
    criticality: high
    schema_ref: json_object
""")
    (root / "data/events").mkdir()
    source = root / "data/events/2026-08-03.json"
    source.write_text('{"asof":"2026-08-03"}\n', encoding="utf-8")
    first = audit_ledgers(root, write=True)
    assert not has_violations(first)
    source.write_text('{"asof":"2026-08-03","changed":true}\n', encoding="utf-8")
    second = audit_ledgers(root, write=False)
    assert has_violations(second)
    assert second["ledgers"][0]["immutable_changes"] == ["data/events/2026-08-03.json"]


def test_frozen_append_ledger_is_not_marked_stale(tmp_path: Path) -> None:
    root = _root(tmp_path, """version: 1
ledgers:
  - id: legacy
    path: data/legacy.csv
    kind: append_csv
    cadence: trading_daily
    criticality: medium
    schema_ref: csv
    timestamp_field: asof
    expected_state: frozen
""")
    (root / "data/legacy.csv").write_text("asof,value\n2020-01-02,1\n", encoding="utf-8")
    report = audit_ledgers(root, write=False)
    assert report["ledgers"][0]["status"] == "frozen"
    assert report["summary"]["frozen"] == 1


def test_registered_empty_writer_can_report_accumulating_zero_rows(tmp_path: Path) -> None:
    root = _root(tmp_path, """version: 1
ledgers:
  - id: calibration
    path: data/calibration.csv
    kind: append_csv
    cadence: trading_daily
    criticality: medium
    schema_ref: csv
    timestamp_field: asof
    allow_empty_accumulating: true
""")
    (root / "data/calibration.csv").write_text("asof,value\n", encoding="utf-8")
    report = audit_ledgers(root, write=False)
    assert report["ledgers"][0]["status"] == "accumulating"
    assert report["ledgers"][0]["row_count"] == 0


def test_dualdb_model_run_weekly_cadence_detects_stalled_sqlite(tmp_path: Path) -> None:
    root = _root(tmp_path, """version: 1
ledgers:
  - id: dualdb_model_runs
    path: dualdb/db/dualdb.sqlite
    kind: singleton
    cadence: weekly
    criticality: high
    schema_ref: dualdb_model_run
    timestamp_field: model_run.asof
""")
    database = root / "dualdb/db/dualdb.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE model_run (run_id INTEGER PRIMARY KEY, model TEXT, "
            "asof TEXT, params_json TEXT, output_json TEXT, created_at TEXT)")
        conn.execute(
            "INSERT INTO model_run VALUES (1,'knn_analog','2026-07-17','{}','{}',"
            "'2026-07-17T00:00:00')")
    report = audit_ledgers(
        root, write=False,
        now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )
    row = report["ledgers"][0]
    assert row["latest_date"] == "2026-07-17"
    assert row["status"] == "stalled"
    assert row["schema_errors"] == []


def test_research_pack_normalizes_probability_and_provenance(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _root(tmp_path, """version: 1
ledgers:
  - id: sample
    path: data/sample.csv
    kind: append_csv
    cadence: event
    criticality: medium
    schema_ref: csv
""")
    (root / "data/sample.csv").write_text(
        "question_id,probability,weight,probability_space\nq1,75,75,physical_event\n", encoding="utf-8")
    monkeypatch.setattr(
        "ai_fc.research_pack._commit_metadata",
        lambda _root: ("a" * 40, "2026-08-04T00:00:00+00:00"),
    )
    pack = export_research_pack(root, "2026-08")
    rows = pq.read_table(pack / "sample.parquet").to_pylist()
    payload = json.loads(rows[0]["payload_json"])
    assert payload["probability"] == 0.75
    assert payload["weight"] == "75"
    assert json.loads(rows[0]["normalized_fields"]) == ["probability"]
    assert rows[0]["probability_space"] == "physical_event"
    assert json.loads(rows[0]["derived_from"]) == ["data/sample.csv"]
    assert export_research_pack(root, "2026-08") == pack


def test_research_pack_preserves_pending_probability_unit(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path, """version: 1
ledgers:
  - id: benchmark
    path: calibration/benchmark_ledger.csv
    kind: append_csv
    cadence: event
    criticality: medium
    schema_ref: csv
""")
    (root / "calibration").mkdir()
    (root / "calibration/benchmark_ledger.csv").write_text(
        "forecast_id,resolved_date,market_prob,probability_space\nf1,2026-07-31,22,physical_event\n",
        encoding="utf-8")
    (root / "calibration/corrections.csv").write_text(
        "target_table,target_key,field_name,status\nbenchmark_scores,f1@2026-07-31,market_prob,pending\n",
        encoding="utf-8")
    monkeypatch.setattr(
        "ai_fc.research_pack._commit_metadata",
        lambda _root: ("b" * 40, "2026-08-04T00:00:00+00:00"),
    )
    rows = pq.read_table(export_research_pack(root, "2026-08") / "benchmark.parquet").to_pylist()
    assert json.loads(rows[0]["payload_json"])["market_prob"] == "22"
    assert rows[0]["unit_review_pending"] is True
    assert json.loads(rows[0]["unit_review_pending_fields"]) == ["market_prob"]


def test_registered_timestamp_field_is_a_fallback_for_json_and_jsonl(tmp_path) -> None:
    """json/jsonl 원장도 등록된 timestamp_field로 날짜를 찾되, 기존 키를 덮지 않는다.

    이 fallback이 없으면 asof/run_ts/timestamp 중 어느 것도 쓰지 않는 원장이
    latest_date=None으로 잡혀 한 번도 채워진 적 없는 것처럼 보고된다
    (ipo_reference_batch_*, timeseries_shadow_forecasts에서 실제 발생).
    반대로 덮어쓰기로 만들면 asof(데이터 기준일) 대신 generated_at(생성 시각)을
    읽어 신선도를 과대평가하므로, 하드코딩 키가 있으면 그쪽이 우선이어야 한다.
    """
    from datetime import date
    from ai_fc.ledger_audit import _dates

    # json: asof가 없으면 등록 필드로 대체
    only_field = tmp_path / "status.json"
    only_field.write_text('{"checked_at": "2026-08-19T05:23:09+00:00"}', encoding="utf-8")
    assert _dates([only_field], "checked_at") == [date(2026, 8, 19)]
    assert _dates([only_field], None) == []

    # json: asof가 있으면 등록 필드보다 우선 (신선도 과대평가 방지)
    both = tmp_path / "cohort.json"
    both.write_text(
        '{"asof": "2026-07-30", "generated_at": "2026-08-04T09:15:53+00:00"}',
        encoding="utf-8",
    )
    assert _dates([both], "generated_at") == [date(2026, 7, 30)]

    # jsonl: run_ts/asof/timestamp가 모두 없을 때만 등록 필드 사용
    lines = tmp_path / "forecasts.jsonl"
    lines.write_text(
        '{"as_of": "2026-08-28", "forecast_id": "f1"}' + chr(10), encoding="utf-8"
    )
    assert _dates([lines], "as_of") == [date(2026, 8, 28)]
    assert _dates([lines], None) == []


def test_biweekly_cadence_allows_a_fortnight_before_calling_a_ledger_stalled(
    tmp_path: Path,
) -> None:
    """격주 원장은 14일 주기 + 한 번 놓칠 여유(17일)까지 accumulating이다.

    biweekly 분기가 없으면 어떤 분기에도 걸리지 않아 staleness가 영원히 False가
    되고, 격주 작성기가 죽어도 stalled로 잡히지 않는다.
    """
    registry = """version: 1
ledgers:
  - id: ipo_edgar_candidates
    path: data/statistics/ipo/edgar_candidates.json
    kind: mutable_snapshot
    cadence: biweekly
    criticality: medium
    schema_ref: json_object
    timestamp_field: checked_at
"""

    def audit(checked_at: str, now: str) -> tuple[dict, dict]:
        root = _root(tmp_path / checked_at[:10], registry)
        target = root / "data/statistics/ipo/edgar_candidates.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"checked_at": checked_at, "candidates": []}), encoding="utf-8")
        report = audit_ledgers(
            root, write=False, now=datetime.fromisoformat(now).replace(tzinfo=timezone.utc))
        return report["ledgers"][0], report

    fresh, _ = audit("2026-08-31T00:00:00+00:00", "2026-09-14T00:00:00")
    assert fresh["status"] == "accumulating", "14일째는 아직 신선하다"
    assert fresh["cadence"] == "biweekly"
    assert fresh["latest_date"] == "2026-08-31"

    edge, _ = audit("2026-08-01T00:00:00+00:00", "2026-08-18T00:00:00")
    assert edge["status"] == "accumulating", "17일까지는 한 번 놓친 것으로 본다"

    stalled, report = audit("2026-07-01T00:00:00+00:00", "2026-07-19T00:00:00")
    assert stalled["status"] == "stalled", "18일이면 격주 작성기가 멈춘 것"
    assert not has_violations(report), "정체는 불변성 위반이 아니다"
