from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_fc.timeseries_v6.collection import (
    BlockedSecretError,
    PermanentCollectionError,
    RetryableCollectionError,
    SchemaQuarantineError,
    request_fingerprint,
    run_collection_attempt,
)


class MemoryAttemptRepository:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def create_collection_attempt(self, **kwargs: object) -> None:
        self.events.append(("created", kwargs))

    def finish_collection_attempt(self, **kwargs: object) -> None:
        self.events.append(("finished", kwargs))


def _clock() -> datetime:
    return datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (BlockedSecretError("missing"), "blocked_secret"),
        (SchemaQuarantineError("drift"), "schema_quarantine"),
        (RetryableCollectionError("429"), "retryable_failure"),
        (PermanentCollectionError("404"), "permanent_failure"),
    ],
)
def test_failure_is_recorded_after_attempt_exists(exception: Exception, expected: str) -> None:
    repository = MemoryAttemptRepository()

    def action(attempt_id: str) -> str:
        assert repository.events[0][0] == "created"
        raise exception

    result = run_collection_attempt(
        repository,
        attempt_id="attempt-1",
        source_id="fred_alfred",
        scheduled_for=_clock(),
        retry_sequence=0,
        request_fingerprint_sha256="a" * 64,
        action=action,
        clock=_clock,
    )
    assert result.terminal_status == expected
    assert [event for event, _ in repository.events] == ["created", "finished"]
    assert repository.events[-1][1]["terminal_status"] == expected


@pytest.mark.parametrize("status", ["success", "not_modified"])
def test_success_and_304_reach_one_terminal_status(status: str) -> None:
    repository = MemoryAttemptRepository()
    result = run_collection_attempt(
        repository,
        attempt_id="attempt-ok", source_id="fred_alfred", scheduled_for=_clock(),
        retry_sequence=0, request_fingerprint_sha256="b" * 64,
        action=lambda _: status, clock=_clock,
    )
    assert result.terminal_status == status
    assert sum(event == "finished" for event, _ in repository.events) == 1


def test_invalid_return_becomes_permanent_failure_and_fingerprint_is_redacted() -> None:
    repository = MemoryAttemptRepository()
    result = run_collection_attempt(
        repository,
        attempt_id="attempt-invalid", source_id="x", scheduled_for=_clock(),
        retry_sequence=0, request_fingerprint_sha256="c" * 64,
        action=lambda _: "maybe", clock=_clock,
    )
    assert result.terminal_status == "permanent_failure"
    assert request_fingerprint("GET", "https://example.test/data?api_key=[REDACTED]", None) == request_fingerprint(
        "GET", "https://example.test/data?api_key=[REDACTED]", None
    )
    assert len(request_fingerprint("GET", "https://example.test", None)) == 64
