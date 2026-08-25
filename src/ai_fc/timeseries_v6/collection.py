"""Collection-attempt orchestration with exactly-one terminal outcome."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, TypeVar


TERMINAL_STATUSES = frozenset(
    {
        "success", "not_modified", "retryable_failure", "permanent_failure",
        "blocked_secret", "schema_quarantine", "cancelled",
    }
)


class AttemptRepository(Protocol):
    def create_collection_attempt(self, **kwargs: object) -> None: ...
    def finish_collection_attempt(self, **kwargs: object) -> None: ...


class RetryableCollectionError(RuntimeError):
    pass


class PermanentCollectionError(RuntimeError):
    pass


class BlockedSecretError(RuntimeError):
    pass


class SchemaQuarantineError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttemptResult:
    attempt_id: str
    terminal_status: str
    reason_code: str | None


T = TypeVar("T")


def request_fingerprint(method: str, redacted_url: str, body_sha256: str | None) -> str:
    payload = f"{method.upper()}\n{redacted_url}\n{body_sha256 or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_collection_attempt(
    repository: AttemptRepository,
    *,
    attempt_id: str,
    source_id: str,
    scheduled_for: datetime,
    retry_sequence: int,
    request_fingerprint_sha256: str,
    action: Callable[[str], str],
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> AttemptResult:
    """Run one attempt, ensuring it is recorded before any collector action.

    ``action`` must return either ``success`` after writing at least one receipt
    or ``not_modified`` after an HTTP 304. Exceptions are mapped to explicit
    terminal outcomes and are not silently retried here.
    """

    started_at = clock()
    repository.create_collection_attempt(
        attempt_id=attempt_id,
        source_id=source_id,
        scheduled_for=scheduled_for,
        retry_sequence=retry_sequence,
        started_at=started_at,
        request_fingerprint_sha256=request_fingerprint_sha256,
    )
    status: str
    reason: str | None = None
    try:
        status = action(attempt_id)
        if status not in {"success", "not_modified"}:
            raise PermanentCollectionError(f"collector returned invalid terminal status {status!r}")
    except BlockedSecretError as exc:
        status, reason = "blocked_secret", type(exc).__name__
    except SchemaQuarantineError as exc:
        status, reason = "schema_quarantine", type(exc).__name__
    except RetryableCollectionError as exc:
        status, reason = "retryable_failure", type(exc).__name__
    except PermanentCollectionError as exc:
        status, reason = "permanent_failure", type(exc).__name__
    repository.finish_collection_attempt(
        attempt_id=attempt_id,
        terminal_status=status,
        completed_at=clock(),
        reason_code=reason,
    )
    return AttemptResult(attempt_id=attempt_id, terminal_status=status, reason_code=reason)
