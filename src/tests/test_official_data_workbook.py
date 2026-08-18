from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

from ai_fc.authoritative_statistics import (
    NormalizedObservation,
    append_normalized_observations,
    load_authoritative_source_policy,
    persist_raw_artifact,
)
from ai_fc.official_data_workbook import export_official_data_workbook


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_excel_audit_export_reconciles_to_canonical_ledgers(
    tmp_path: Path, monkeypatch,
) -> None:
    raw_body = b"M2SL,22000"
    raw_sha256 = hashlib.sha256(raw_body).hexdigest()
    _write_json(tmp_path / "data/statistics/dotcom_statistics_latest.json", {
        "generated_at": "2026-08-18T08:30:00+00:00",
        "as_of": "2026-08-17",
        "sources": [{
            "series_id": "M2SL", "title": "M2", "provider": "Federal Reserve",
            "unit": "billions_usd", "native_frequency": "monthly",
            "latest_observation": "2026-06-01", "row_count": 1,
            "authority_class": "authoritative_public_distributor",
            "policy_source_id": "fred_market_signals", "numeric_input_allowed": True,
            "raw_sha256": raw_sha256,
        }],
        "charts": [{
            "id": "m2", "title": "M2", "category": "liquidity", "unit": "level",
            "metric_source_ids": ["M2SL"], "research_context_source_ids": [],
            "scope_note": "*미국 기준", "conclusion": "공식 관측치입니다.",
        }],
    })
    store = tmp_path / "data/statistics/official_store"
    policy = load_authoritative_source_policy(
        Path(__file__).resolve().parents[2]
        / "data/contracts/authoritative_statistics_sources.yaml"
    )
    receipt = persist_raw_artifact(
        store,
        policy,
        source_id="fred_market_signals",
        payload=raw_body,
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL",
        fetched_at="2026-08-18T08:30:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["M2SL"],
    )
    observation = NormalizedObservation(
        source_id="fred_market_signals", series_id="M2SL",
        observation_date="2026-06-01", vintage_date="2026-08-18",
        revision_seq=0, available_at="2026-08-18T08:30:00+00:00",
        fetched_at="2026-08-18T08:30:00+00:00", raw_value="22000",
        value="22000", raw_unit="billions_usd", unit="billions_usd",
        semantic_type="currency", transformation_id="identity",
        parser_version="test-v1", raw_sha256=receipt.raw_sha256,
    )
    append_normalized_observations(store, policy, [observation])
    _write_json(
        tmp_path / "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json",
        {"status": "RESEARCH_CANDIDATE", "promotion_state": "NOT_OFFICIAL", "evidence_registry": []},
    )

    monkeypatch.setattr("ai_fc.statistics_lab.validate_statistics_lab", lambda _payload: None)
    path, counts = export_official_data_workbook(tmp_path)
    assert counts == {"sources": 1, "observations": 1, "receipts": 1, "charts": 1}
    assert path.is_file()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "xl/workbook.xml" in names
        assert len([name for name in names if name.startswith("xl/worksheets/sheet")]) == 8
        observations_xml = archive.read("xl/worksheets/sheet3.xml").decode("utf-8")
        assert "M2SL" in observations_xml
        assert "22000" in observations_xml
        gates_xml = archive.read("xl/worksheets/sheet8.xml").decode("utf-8")
        assert "RAW_BEFORE_DERIVE" in gates_xml
        assert "raw_errors=0; correction_errors=0; orphan_rows=0; series_mismatches=0" in gates_xml
