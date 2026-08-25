from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_fc.timeseries_v6.bulk import BulkIngestionError, ObservationBatchRow, validate_observation_batch


NOW = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)


def _row(**changes: object) -> ObservationBatchRow:
    values: dict[str, object] = {
        "observation_key_id": "key-1",
        "observation_version_id": "version-1",
        "receipt_id": "receipt-1",
        "source_id": "fred_alfred",
        "series_id": "NASDAQCOM",
        "observation_time": NOW,
        "unit": "index_points",
        "semantic_type": "close",
        "revision_seq": 0,
        "value_numeric": 100.0,
        "value_text": None,
        "available_at": NOW,
        "vintage_start": None,
        "vintage_end": None,
        "raw_object_sha256": "a" * 64,
        "supersedes_observation_version_id": None,
    }
    values.update(changes)
    return ObservationBatchRow(**values)  # type: ignore[arg-type]


def test_clean_batch_is_frozen_and_future_rows_fail() -> None:
    assert validate_observation_batch([_row()], knowledge_cutoff=NOW)[0].series_id == "NASDAQCOM"
    with pytest.raises(BulkIngestionError, match="future-available"):
        validate_observation_batch([_row(available_at=NOW + timedelta(seconds=1))], knowledge_cutoff=NOW)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"value_numeric": None}, "exactly one"),
        ({"value_numeric": float("nan")}, "finite"),
        ({"revision_seq": 1}, "supersedes"),
        ({"revision_seq": 0, "supersedes_observation_version_id": "old"}, "supersedes"),
        ({"relation": "derived"}, "relation"),
    ],
)
def test_invalid_rows_fail_before_write(changes: dict[str, object], message: str) -> None:
    with pytest.raises(BulkIngestionError, match=message):
        validate_observation_batch([_row(**changes)], knowledge_cutoff=NOW)


def test_batch_rejects_duplicate_identity() -> None:
    with pytest.raises(BulkIngestionError, match="duplicate"):
        validate_observation_batch([_row(), _row()], knowledge_cutoff=NOW)
