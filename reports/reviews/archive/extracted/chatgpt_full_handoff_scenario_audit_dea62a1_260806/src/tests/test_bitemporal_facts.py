from __future__ import annotations

import pytest

from ai_fc.facts import ObservationFact, ParquetFactStore, as_of_rows, assert_no_leakage


def _fact(value: float, start: str, end: str | None) -> ObservationFact:
    return ObservationFact(
        source_id="alfred", series_id="GDP", observation_time="2025-01-01",
        value=value, available_at=start, vintage_start=start, vintage_end=end,
        retrieved_at="2026-01-01T00:00:00", source_hash="a" * 64,
        parser_version="test-v1", timezone="America/New_York", calendar_id="US_FED",
    )


def test_asof_selects_the_revision_known_at_that_time() -> None:
    facts = [
        _fact(100.0, "2025-04-30T08:30:00", "2025-05-29T08:30:00"),
        _fact(101.0, "2025-05-29T08:30:00", "2025-06-26T08:30:00"),
        _fact(102.0, "2025-06-26T08:30:00", None),
    ]
    assert as_of_rows(facts, series_id="GDP", as_of="2025-05-15T12:00:00")[0].value == 100.0
    assert as_of_rows(facts, series_id="GDP", as_of="2025-06-01T12:00:00")[0].value == 101.0
    assert as_of_rows(facts, series_id="GDP", as_of="2025-07-01T12:00:00")[0].value == 102.0


def test_pre_release_value_is_unavailable_and_sentinel_fails() -> None:
    fact = _fact(100.0, "2025-04-30T08:30:00", None)
    assert as_of_rows([fact], series_id="GDP", as_of="2025-04-30T08:29:59") == []
    with pytest.raises(AssertionError, match="leakage"):
        assert_no_leakage([fact], as_of="2025-04-30T08:29:59")


def test_parquet_duckdb_store_matches_python_asof(tmp_path) -> None:
    facts = [
        _fact(100.0, "2025-04-30T08:30:00", "2025-05-29T08:30:00"),
        _fact(101.0, "2025-05-29T08:30:00", None),
    ]
    store = ParquetFactStore(tmp_path)
    paths = store.append(facts)
    assert paths and all(path.exists() for path in paths)
    rows = store.as_of(series_id="GDP", as_of="2025-05-15T12:00:00")
    assert len(rows) == 1 and rows[0]["value"] == 100.0
