"""Idempotent collector primitives with explicit terminal outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Mapping, Protocol


@dataclass(frozen=True)
class Request:
    source_id: str
    url: str
    fetched_at: datetime
    headers: Mapping[str, str] = field(default_factory=dict)
    page_token: str | None = None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str]
    next_page_token: str | None = None


@dataclass(frozen=True)
class CollectionResult:
    source_id: str
    object_hashes: tuple[str, ...]
    schema_fingerprints: tuple[str, ...]
    outcome: str
    attempts: int
    etag: str | None
    last_modified: str | None


class Transport(Protocol):
    def __call__(self, request: Request) -> Response: ...


class ObjectStore(Protocol):
    def put_if_absent(self, key: str, body: bytes) -> bool: ...


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def schema_fingerprint(body: bytes) -> str:
    value = json.loads(body)
    if isinstance(value, dict):
        shape = {key: type(item).__name__ for key, item in sorted(value.items())}
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        shape = {key: type(item).__name__ for key, item in sorted(value[0].items())}
    else:
        shape = {"root": type(value).__name__}
    return content_hash(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode())


def collect(
    initial: Request,
    transport: Transport,
    store: ObjectStore,
    *,
    max_attempts: int = 3,
    known_schema: str | None = None,
    backoff: Callable[[int], None] = lambda _: None,
) -> CollectionResult:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    request = initial
    object_hashes: list[str] = []
    fingerprints: list[str] = []
    attempts = 0
    etag = None; last_modified = None
    while True:
        response = None
        for retry in range(max_attempts):
            attempts += 1
            try:
                response = transport(request)
            except (TimeoutError, ConnectionError):
                if retry + 1 == max_attempts:
                    return CollectionResult(initial.source_id, tuple(object_hashes), tuple(fingerprints), "parser_failure", attempts, etag, last_modified)
                backoff(retry + 1)
                continue
            if response.status in {429, 500, 502, 503, 504}:
                if retry + 1 == max_attempts:
                    return CollectionResult(initial.source_id, tuple(object_hashes), tuple(fingerprints), "parser_failure", attempts, etag, last_modified)
                backoff(retry + 1)
                continue
            break
        assert response is not None
        if response.status == 304:
            return CollectionResult(initial.source_id, tuple(object_hashes), tuple(fingerprints), "unchanged", attempts, etag, last_modified)
        if response.status != 200:
            return CollectionResult(initial.source_id, tuple(object_hashes), tuple(fingerprints), "license_blocked" if response.status in {401, 403} else "parser_failure", attempts, etag, last_modified)
        etag = response.headers.get("etag", etag)
        last_modified = response.headers.get("last-modified", last_modified)
        fingerprint = schema_fingerprint(response.body)
        fingerprints.append(fingerprint)
        if known_schema is not None and fingerprint != known_schema:
            return CollectionResult(initial.source_id, tuple(object_hashes), tuple(fingerprints), "quarantined", attempts, etag, last_modified)
        digest = content_hash(response.body)
        created = store.put_if_absent(f"sha256/{digest[:2]}/{digest}", response.body)
        object_hashes.append(digest)
        if response.next_page_token is None:
            outcome = "parsed_new" if created else "unchanged"
            return CollectionResult(initial.source_id, tuple(object_hashes), tuple(fingerprints), outcome, attempts, etag, last_modified)
        request = Request(request.source_id, request.url, request.fetched_at, request.headers, response.next_page_token)
