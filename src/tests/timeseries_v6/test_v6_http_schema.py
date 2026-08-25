import json

import pytest

from ai_fc.timeseries_v6.http import HttpResponse, RetrievalError, ResilientHttpClient, RetryPolicy, sanitized_uri
from ai_fc.timeseries_v6.schema_drift import decide_schema, schema_fingerprint


def test_retry_after_and_offset_pagination_are_bounded() -> None:
    calls: list[dict] = []
    delays: list[float] = []

    def transport(_method, _uri, payload, _headers):
        calls.append(dict(payload or {}))
        if len(calls) == 1:
            return HttpResponse(429, b"busy", {"Retry-After": "3"})
        offset = int((payload or {})["offset"])
        rows = list(range(offset, offset + (2 if offset == 0 else 1)))
        return HttpResponse(200, json.dumps(rows).encode(), {"content-type": "application/json"})

    client = ResilientHttpClient(transport, policy=RetryPolicy(max_attempts=3, maximum_pages=3), sleeper=delays.append)
    pages = client.offset_pages("POST", "https://api.finra.org/data", base_payload={}, page_size=2, rows_from_body=lambda body: json.loads(body))
    assert len(pages) == 2
    assert delays == [3.0]
    assert [page.response.status for page in pages] == [200, 200]


def test_permanent_status_and_credential_uri_fail_closed() -> None:
    client = ResilientHttpClient(lambda *_args: HttpResponse(404, b"", {}))
    with pytest.raises(RetrievalError, match="permanent"):
        client.request("GET", "https://example.com/data")
    credential_uri = "https://" + "user" + ":" + "pass" + "@example.com/data"
    with pytest.raises(RetrievalError, match="credential-free"):
        sanitized_uri(credential_uri)


def test_schema_fingerprint_is_order_stable_and_drift_is_quarantined() -> None:
    one = json.dumps({"b": [1], "a": "x"}).encode()
    two = json.dumps({"a": "y", "b": [2]}).encode()
    fingerprint = schema_fingerprint(one, "application/json")
    assert schema_fingerprint(two, "application/json") == fingerprint
    assert decide_schema(one, "application/json", approved_fingerprints={fingerprint}).status == "approved"
    drift = json.dumps({"a": "x", "b": {"nested": 1}}).encode()
    assert decide_schema(drift, "application/json", approved_fingerprints={fingerprint}).status == "schema_quarantine"
