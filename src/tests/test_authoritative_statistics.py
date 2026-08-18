from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ai_fc.authoritative_statistics import (
    AppendConflict,
    NormalizedObservation,
    RawArtifactMissing,
    SourcePolicyViolation,
    append_raw_receipt_correction,
    append_normalized_observations,
    load_authoritative_source_policy,
    persist_raw_artifact,
    read_raw_receipt_corrections,
    read_normalized_observations,
    validate_numeric_metric_lineage,
)


POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "contracts"
    / "authoritative_statistics_sources.yaml"
)


def _policy():
    return load_authoritative_source_policy(POLICY_PATH)


def _observation(
    *,
    raw_sha256: str,
    value: str = "100.25",
    raw_value: str = "100.25",
    revision_seq: int = 0,
    vintage_date: str = "2026-08-18",
    fetched_at: str = "2026-08-18T12:00:00+00:00",
    source_id: str = "fred_market_signals",
    transformation_id: str = "identity",
    transformation_formula: str | None = None,
    supersedes_observation_id: str | None = None,
) -> NormalizedObservation:
    return NormalizedObservation(
        source_id=source_id,
        series_id="NASDAQCOM",
        observation_date="2026-08-17",
        vintage_date=vintage_date,
        revision_seq=revision_seq,
        available_at="2026-08-17T22:30:00+00:00",
        fetched_at=fetched_at,
        raw_value=raw_value,
        value=value,
        raw_unit="index_points",
        unit="index_points",
        semantic_type="index",
        transformation_id=transformation_id,
        transformation_formula=transformation_formula,
        parser_version="fred-csv-v1",
        raw_sha256=raw_sha256,
        supersedes_observation_id=supersedes_observation_id,
    )


def test_policy_allows_authoritative_numeric_sources_and_denies_insight_sources() -> None:
    policy = _policy()
    rules = validate_numeric_metric_lineage(
        policy,
        metric_id="nasdaq_level",
        source_ids=["fred_market_signals"],
    )
    assert rules[0].owner == "Federal Reserve Bank of St. Louis"
    for source_id in ("reuters", "ritter_ipo_research", "yahoo_crosscheck", "macromicro"):
        with pytest.raises(SourcePolicyViolation, match="insight-only"):
            validate_numeric_metric_lineage(
                policy,
                metric_id="forbidden_numeric_metric",
                source_ids=[source_id],
            )
    with pytest.raises(SourcePolicyViolation, match="unregistered source"):
        validate_numeric_metric_lineage(
            policy,
            metric_id="unknown_numeric_metric",
            source_ids=["some_report_not_in_the_catalog"],
        )


def test_raw_bytes_are_persisted_before_normalized_rows(tmp_path: Path) -> None:
    policy = _policy()
    payload = b"DATE,NASDAQCOM\n2026-08-17,100.25\n"
    digest = hashlib.sha256(payload).hexdigest()
    observation = _observation(raw_sha256=digest)
    with pytest.raises(RawArtifactMissing, match="prior receipt"):
        append_normalized_observations(tmp_path, policy, [observation])

    receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=payload,
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    assert (tmp_path / receipt.artifact_path).read_bytes() == payload
    appended = append_normalized_observations(tmp_path, policy, [observation])
    assert appended == [observation]
    assert read_normalized_observations(tmp_path) == [observation]


def test_raw_receipt_rejects_a_source_id_bound_to_the_wrong_domain(tmp_path: Path) -> None:
    with pytest.raises(SourcePolicyViolation, match="not approved"):
        persist_raw_artifact(
            tmp_path,
            _policy(),
            source_id="fred_market_signals",
            payload=b"not actually from FRED",
            source_uri="https://example.com/fred-looking.csv",
            fetched_at="2026-08-18T12:00:00+00:00",
            http_status=200,
            media_type="text/csv",
            series_ids=["NASDAQCOM"],
        )


def test_raw_receipt_and_observation_append_are_idempotent(tmp_path: Path) -> None:
    policy = _policy()
    payload = b"DATE,NASDAQCOM\n2026-08-17,100.25\n"
    kwargs = dict(
        source_id="fred_market_signals",
        payload=payload,
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    first_receipt = persist_raw_artifact(tmp_path, policy, **kwargs)
    second_receipt = persist_raw_artifact(tmp_path, policy, **kwargs)
    assert first_receipt == second_receipt
    observation = _observation(raw_sha256=first_receipt.raw_sha256)
    assert append_normalized_observations(tmp_path, policy, [observation]) == [observation]
    assert append_normalized_observations(tmp_path, policy, [observation]) == []
    assert len((tmp_path / "ledgers" / "raw_receipts.jsonl").read_text().splitlines()) == 1
    assert len(
        (tmp_path / "ledgers" / "normalized_observations.jsonl").read_text().splitlines()
    ) == 1


def test_receipt_metadata_correction_is_append_only_and_preserves_raw_hash(
    tmp_path: Path,
) -> None:
    policy = _policy()
    payload = b"official workbook bytes"
    old = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="sec_edgar",
        payload=payload,
        source_uri="https://www.sec.gov/data-research/statistics-data-visualizations/initial-public-offerings-ipos",
        fetched_at="2026-08-18T08:00:00+00:00",
        http_status=200,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        series_ids=["SEC_IPO_QUARTERLY.total_count"],
    )
    replacement = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="sec_edgar",
        payload=payload,
        source_uri="https://www.sec.gov/files/dera/data/sec-stats-ipos-2026.xlsx",
        fetched_at="2026-08-18T09:00:00+00:00",
        http_status=200,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        series_ids=["SEC_IPO_QUARTERLY.total_count"],
    )
    correction = append_raw_receipt_correction(
        tmp_path,
        supersedes_receipt_id=old.receipt_id,
        replacement_receipt_id=replacement.receipt_id,
        reason="replace landing-page URI with exact SEC workbook URI",
        corrected_at="2026-08-18T09:00:00+00:00",
    )
    assert correction.supersedes_receipt_id == old.receipt_id
    assert read_raw_receipt_corrections(tmp_path) == [correction]
    assert append_raw_receipt_correction(
        tmp_path,
        supersedes_receipt_id=old.receipt_id,
        replacement_receipt_id=replacement.receipt_id,
        reason="replace landing-page URI with exact SEC workbook URI",
        corrected_at="2026-08-18T09:00:00+00:00",
    ) == correction


def test_same_revision_can_be_reobserved_from_a_later_raw_fetch(tmp_path: Path) -> None:
    policy = _policy()
    first_receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=b"DATE,NASDAQCOM\n2026-08-17,100.25\n",
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    later_receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=b"DATE,NASDAQCOM\n2026-08-17,100.25\n2026-08-18,101.00\n",
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-19T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    first = _observation(raw_sha256=first_receipt.raw_sha256)
    later = _observation(
        raw_sha256=later_receipt.raw_sha256,
        fetched_at="2026-08-19T12:00:00+00:00",
    )
    append_normalized_observations(tmp_path, policy, [first])
    assert append_normalized_observations(tmp_path, policy, [later]) == [later]
    assert len(read_normalized_observations(tmp_path)) == 2


def test_research_bytes_may_be_retained_but_cannot_enter_numeric_ledger(tmp_path: Path) -> None:
    policy = _policy()
    receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="reuters",
        payload=b"report context only",
        source_uri="https://www.reuters.com/example",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/html",
        series_ids=["NASDAQCOM"],
    )
    with pytest.raises(SourcePolicyViolation, match="insight-only"):
        append_normalized_observations(
            tmp_path,
            policy,
            [_observation(raw_sha256=receipt.raw_sha256, source_id="reuters")],
        )


def test_batch_validation_finishes_before_any_observation_is_appended(tmp_path: Path) -> None:
    policy = _policy()
    official_receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=b"DATE,NASDAQCOM\n2026-08-17,100.25\n",
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    insight_receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="reuters",
        payload=b"report context only",
        source_uri="https://www.reuters.com/example",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/html",
        series_ids=["NASDAQCOM"],
    )
    with pytest.raises(SourcePolicyViolation, match="insight-only"):
        append_normalized_observations(
            tmp_path,
            policy,
            [
                _observation(raw_sha256=official_receipt.raw_sha256),
                _observation(raw_sha256=insight_receipt.raw_sha256, source_id="reuters"),
            ],
        )
    assert not (tmp_path / "ledgers" / "normalized_observations.jsonl").exists()


def test_normalization_and_probability_units_must_be_explicit() -> None:
    digest = "a" * 64
    with pytest.raises(ValueError, match="identity"):
        _observation(raw_sha256=digest, raw_value="100.25", value="100.3")
    with pytest.raises(ValueError, match="transformation_formula"):
        _observation(raw_sha256=digest, transformation_id="scale")
    with pytest.raises(ValueError, match="unit='fraction'"):
        NormalizedObservation(
            source_id="fred_market_signals",
            series_id="PROBABILITY_EXAMPLE",
            observation_date="2026-08-17",
            vintage_date="2026-08-18",
            revision_seq=0,
            available_at="2026-08-18T08:00:00+00:00",
            fetched_at="2026-08-18T12:00:00+00:00",
            raw_value="73",
            value="73",
            raw_unit="percent",
            unit="percent",
            semantic_type="probability",
            transformation_id="identity",
            parser_version="test-v1",
            raw_sha256=digest,
        )


def test_revisions_must_be_sequential_and_explicitly_supersede(tmp_path: Path) -> None:
    policy = _policy()
    first_payload = b"DATE,NASDAQCOM\n2026-08-17,100.25\n"
    second_payload = b"DATE,NASDAQCOM\n2026-08-17,101.00\n"
    first_receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=first_payload,
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    second_receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=second_payload,
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-19T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    first = _observation(raw_sha256=first_receipt.raw_sha256)
    append_normalized_observations(tmp_path, policy, [first])
    invalid_revision = _observation(
        raw_sha256=second_receipt.raw_sha256,
        value="101.00",
        raw_value="101.00",
        revision_seq=1,
        vintage_date="2026-08-19",
        fetched_at="2026-08-19T12:00:00+00:00",
    )
    with pytest.raises(AppendConflict, match="supersede"):
        append_normalized_observations(tmp_path, policy, [invalid_revision])
    revision = invalid_revision.model_copy(
        update={"supersedes_observation_id": first.observation_id}
    )
    assert append_normalized_observations(tmp_path, policy, [revision]) == [revision]
    assert read_normalized_observations(
        tmp_path, as_of="2026-08-18T23:59:59+00:00"
    ) == [first]


def test_tampered_raw_artifact_is_rejected(tmp_path: Path) -> None:
    policy = _policy()
    receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=b"DATE,NASDAQCOM\n2026-08-17,100.25\n",
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=200,
        media_type="text/csv",
        series_ids=["NASDAQCOM"],
    )
    (tmp_path / receipt.artifact_path).write_bytes(b"tampered")
    with pytest.raises(RawArtifactMissing, match="byte count changed|hash changed"):
        append_normalized_observations(
            tmp_path, policy, [_observation(raw_sha256=receipt.raw_sha256)]
        )


def test_unsuccessful_fetch_is_retained_but_not_eligible_for_numeric_use(tmp_path: Path) -> None:
    policy = _policy()
    receipt = persist_raw_artifact(
        tmp_path,
        policy,
        source_id="fred_market_signals",
        payload=b"upstream unavailable",
        source_uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM",
        fetched_at="2026-08-18T12:00:00+00:00",
        http_status=503,
        media_type="text/plain",
        series_ids=["NASDAQCOM"],
    )
    with pytest.raises(RawArtifactMissing, match="HTTP status 503"):
        append_normalized_observations(
            tmp_path, policy, [_observation(raw_sha256=receipt.raw_sha256)]
        )


def test_secret_query_parameters_are_not_written_to_receipts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="secret query parameters"):
        persist_raw_artifact(
            tmp_path,
            _policy(),
            source_id="alfred",
            payload=b"{}",
            source_uri="https://api.stlouisfed.org/fred/series?api_key=secret",
            fetched_at="2026-08-18T12:00:00+00:00",
            http_status=200,
            media_type="application/json",
            series_ids=["GDP"],
        )


def test_published_statistics_match_the_machine_readable_lineage_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (root / "data/statistics/dotcom_statistics_latest.json").read_text(encoding="utf-8")
    )
    lineage = yaml.safe_load(
        (root / "data/contracts/website_data_lineage_v1.yaml").read_text(encoding="utf-8")
    )
    declared = lineage["statistics"]["consumers"]
    actual = {chart["id"]: chart["source_ids"] for chart in payload["charts"]}
    assert declared == actual
    policy = _policy()
    policy_source_by_series = {
        source["series_id"]: source["policy_source_id"] for source in payload["sources"]
    }
    for chart_id, series_ids in actual.items():
        validate_numeric_metric_lineage(
            policy,
            metric_id=chart_id,
            source_ids=list(dict.fromkeys(policy_source_by_series[item] for item in series_ids)),
        )
