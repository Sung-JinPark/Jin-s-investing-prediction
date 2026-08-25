import json
from pathlib import Path

from ai_fc.timeseries_v6.public_archive import PublicSeriesSpec
from ai_fc.timeseries_v6.source_coverage import build_source_coverage


def _registry(path: Path) -> None:
    path.write_text(
        """schema_version: 1
registry_id: test
sources:
  - {source_id: source_a, provider: A, authority_class: official, adapter_status: implemented, data_grade: reconstructed_official_archive, cadence: daily, availability_policy_version: v1, redistribution: repository_raw_allowed, source_uri_template: 'https://example.com/a'}
  - {source_id: source_b, provider: B, authority_class: licensed, adapter_status: forward_capture, data_grade: captured_forward, cadence: event, availability_policy_version: v1, redistribution: private_raw_derived_public, source_uri_template: 'captured-forward://b'}
""",
        encoding="utf-8",
    )


def test_source_coverage_separates_catalogue_from_active_materialization(tmp_path: Path) -> None:
    registry = tmp_path / "sources.yaml"
    manifest = tmp_path / "manifest.json"
    _registry(registry)
    manifest.write_text(json.dumps({"receipts": [{"source_id": "source_a", "series_id": "SERIES_A"}]}), encoding="utf-8")
    spec = PublicSeriesSpec("source_a", "SERIES_A", "https://example.com/a", "value", "daily", "index_points", 1)
    report = build_source_coverage(registry, manifest, [spec])
    assert report["model_required_pass"] is True
    assert report["registry_source_count"] == 2
    assert report["materialized_source_count"] == 1
    assert report["full_registry_materialization_is_not_claimed"] is True
    assert {row["source_id"]: row["runtime_status"] for row in report["sources"]} == {
        "source_a": "materialized",
        "source_b": "forward_capture_pending",
    }


def test_source_coverage_fails_closed_for_required_missing_series(tmp_path: Path) -> None:
    registry = tmp_path / "sources.yaml"
    manifest = tmp_path / "manifest.json"
    _registry(registry)
    manifest.write_text(json.dumps({"receipts": []}), encoding="utf-8")
    spec = PublicSeriesSpec("source_a", "SERIES_A", "https://example.com/a", "value", "daily", "index_points", 1)
    report = build_source_coverage(registry, manifest, [spec])
    assert report["model_required_pass"] is False
    assert report["missing_required_series"] == ["source_a:SERIES_A"]
