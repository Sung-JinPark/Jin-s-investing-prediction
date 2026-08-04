from __future__ import annotations

import json
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
