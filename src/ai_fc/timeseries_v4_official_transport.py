"""FRED official-API transport for the V4 source store (DECISIONS 12-6).

The sealed V4 collector still names ``fredgraph.csv`` for NASDAQ100, and everything under
``ai_fc/timeseries_v4`` is bound by its run's ``model_code_hash``, so it may not be edited. That
endpoint is a terms-of-use violation and it times out from runners: the weekly refresh failed on
every scheduled run from 2026-08-29, which also held V5's reconstructed features at 2026-08-14.

Same shape as ``timeseries_v2.official_api_transport``: drive the sealed collector with a fetcher
that refuses the scrape with HTTP 451, then append the series through the official API under its
own source id and the keyless public URL. The key only rides the transport in ``ai_fc.fred_api``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .fred_api import FredApiError, observations_csv, observations_public_url
from .timeseries_v4.source_store import (
    V4SourceError,
    _all_observations,
    append_observations,
    collect_v4_sources,
    parse_fred_graph,
    persist_raw,
    verify_v4_source_store,
)

SEALED_SOURCE_ID = "fred_nasdaq100"
API_SOURCE_ID = "fred_api_nasdaq100"
SERIES_ID = "NASDAQ100"
OBSERVATION_START = "1995-01-01"
FETCHER = Callable[[str], tuple[int, bytes, str]]


def refuse_fredgraph(fetch: FETCHER) -> FETCHER:
    """Legal refusal for the scrape; every other source passes through untouched."""

    def fetcher(url: str) -> tuple[int, bytes, str]:
        if "fred.stlouisfed.org/graph/fredgraph.csv" in url:
            return 451, b"fredgraph scraping is prohibited (DECISIONS 12-6)", "text/plain"
        return fetch(url)

    return fetcher


def collect_v4_official(
    root: Path,
    *,
    fetcher: FETCHER,
    volume_start_year: int = 2009,
    retrieved_at: str | None = None,
    fetch_text=None,
) -> dict[str, Any]:
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = collect_v4_sources(
        root, retrieved_at=retrieved, fetcher=refuse_fredgraph(fetcher), volume_start_year=volume_start_year,
    )
    # Only the refusal we asked for is expected; any other failure of that source stays visible.
    result["failures"] = [
        row for row in result["failures"]
        if not (row.get("source_id") == SEALED_SOURCE_ID and "HTTP 451" in str(row.get("reason")))
    ]
    try:
        payload = observations_csv(SERIES_ID, observation_start=OBSERVATION_START, fetch_text=fetch_text).encode("utf-8")
        receipt = persist_raw(
            root, source_id=API_SOURCE_ID,
            source_uri=observations_public_url(SERIES_ID, observation_start=OBSERVATION_START),
            payload=payload, retrieved_at=retrieved, http_status=200, content_type="text/csv",
            redistribution="private_locator_only",
        )
        parsed = parse_fred_graph(payload, series_id=SERIES_ID)
        if not parsed:
            raise V4SourceError("parser produced zero observations")
        result["sources"][API_SOURCE_ID] = append_observations(
            root, parsed, receipt, observation_cache=_all_observations(root),
        )
    except (OSError, ValueError, FredApiError, V4SourceError) as exc:
        result["failures"].append({"source_id": API_SOURCE_ID, "reason": str(exc)})
    result["ok"] = not result["failures"]
    result["lineage"] = verify_v4_source_store(root)
    return result
