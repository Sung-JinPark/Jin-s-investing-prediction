"""Bounded, resumable HTTP retrieval without credentials in receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class RetrievalError(RuntimeError):
    pass


SECRET_QUERY_NAMES = {"api_key", "apikey", "key", "token", "access_token", "password", "secret"}


def sanitized_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise RetrievalError("source URI must be credential-free HTTPS")
    query = [(key, "REDACTED" if key.lower() in SECRET_QUERY_NAMES else value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def request_fingerprint(method: str, uri: str, payload: Mapping[str, Any] | None) -> str:
    material = {"method": method.upper(), "uri": sanitized_uri(uri), "payload": payload or {}}
    raw = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    maximum_pages: int = 1000
    maximum_response_bytes: int = 100_000_000
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)


@dataclass(frozen=True)
class PageResult:
    page_number: int
    request_fingerprint_sha256: str
    sanitized_uri: str
    response: HttpResponse


Transport = Callable[[str, str, Mapping[str, Any] | None, Mapping[str, str]], HttpResponse]


class ResilientHttpClient:
    def __init__(self, transport: Transport, *, policy: RetryPolicy = RetryPolicy(), sleeper: Callable[[float], None] | None = None) -> None:
        self.transport = transport
        self.policy = policy
        self.sleeper = sleeper or (lambda _seconds: None)

    def request(self, method: str, uri: str, *, payload: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> HttpResponse:
        safe = sanitized_uri(uri)
        public_headers = {key: value for key, value in (headers or {}).items() if key.lower() not in {"authorization", "x-api-key", "cookie"}}
        last_status: int | None = None
        for index in range(self.policy.max_attempts):
            response = self.transport(method.upper(), uri, payload, headers or {})
            last_status = response.status
            if len(response.body) > self.policy.maximum_response_bytes:
                raise RetrievalError("response exceeds configured byte limit")
            if response.status < 400:
                return HttpResponse(response.status, response.body, {key.lower(): value for key, value in response.headers.items()})
            if response.status not in {408, 429, 500, 502, 503, 504}:
                raise RetrievalError(f"permanent HTTP status {response.status} for {safe}")
            if index + 1 < self.policy.max_attempts:
                retry = response.headers.get("Retry-After") or response.headers.get("retry-after")
                delay = float(retry) if retry and retry.replace(".", "", 1).isdigit() else self.policy.backoff_seconds[min(index, len(self.policy.backoff_seconds) - 1)]
                self.sleeper(delay)
        raise RetrievalError(f"retry budget exhausted with status {last_status} for {safe}")

    def offset_pages(
        self,
        method: str,
        uri: str,
        *,
        base_payload: Mapping[str, Any],
        page_size: int,
        rows_from_body: Callable[[bytes], list[Any]],
        start_offset: int = 0,
        headers: Mapping[str, str] | None = None,
    ) -> list[PageResult]:
        if page_size <= 0 or start_offset < 0:
            raise RetrievalError("invalid pagination coordinates")
        pages: list[PageResult] = []
        offset = start_offset
        for page_number in range(self.policy.maximum_pages):
            payload = {**base_payload, "limit": page_size, "offset": offset}
            response = self.request(method, uri, payload=payload, headers=headers)
            pages.append(PageResult(page_number, request_fingerprint(method, uri, payload), sanitized_uri(uri), response))
            rows = rows_from_body(response.body)
            if len(rows) < page_size:
                return pages
            offset += page_size
        raise RetrievalError("pagination exceeded maximum_pages without a terminal page")
