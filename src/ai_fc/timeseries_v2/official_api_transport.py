"""FRED official-API transport for the V2 market archive (DECISIONS 12-6).

The sealed V2 collector (``market_archive.py``) still names ``fredgraph.csv``
for NASDAQCOM/DTWEXB/DTWEXBGS, but that file sits inside the sealed
``model_code_hash`` dependency list and may not be edited — verify fails
closed on any byte change.  This module therefore lives NEXT TO the sealed
code (new files are outside the explicit hash list) and

1. drives the sealed collector with a fetcher that **refuses fredgraph URLs
   with HTTP 451** (the scrape is a FRED terms-of-use violation, and it was
   observed serving observations ~10 days behind the API — starving the V8
   operational freshness gate), while every non-FRED source passes through
   untouched, and
2. appends the same three series through the official API with **honest
   receipts**: their own source ids and the keyless public URL.  The key only
   ever rides the transport inside ``ai_fc.fred_api``.

Revisions stay point-in-time honest: rows land as ``captured_forward`` with
``available_at`` equal to the retrieval time, and a value that differs from a
prior fredgraph capture becomes a superseding revision, never an overwrite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..fred_api import FredApiError, observations_csv, observations_public_url
from ..scenario_v5.contracts import compare_protected_hashes, protected_hashes
from .market_archive import (
    _append_observations,
    _fetch,
    _market_available_at,
    collect_official_market_archives,
    export_market_parquet,
    parse_fred_graph_csv,
    persist_market_raw,
    verify_market_lineage,
)
from .pipeline import TimeSeriesV2PipelineError

FRED_API_SERIES: dict[str, dict[str, str]] = {
    "NASDAQCOM": {
        "source_id": "fred_api_nasdaqcom_archive",
        "observation_start": "1995-01-01",
    },
    "DTWEXB": {
        "source_id": "fred_api_h10_broad_archive",
        "observation_start": "1995-01-01",
    },
    "DTWEXBGS": {
        "source_id": "fred_api_h10_broad_goods_services_archive",
        "observation_start": "2006-01-01",
    },
}


def refuse_fredgraph_fetch(url: str) -> tuple[int, bytes, str]:
    """Sealed-spec fetcher shim: legal refusal for the scrape, passthrough else."""
    if "fred.stlouisfed.org/graph/fredgraph.csv" in url:
        # 451 Unavailable For Legal Reasons — the refusal is recorded in the
        # collection report's failures list instead of silently vanishing.
        return 451, b"fredgraph scraping is prohibited (DECISIONS 12-6)", "text/plain"
    return _fetch(url)


def append_fred_official_api(
    root: Path, *, retrieved_at: str | None = None, fetch_text=None,
) -> dict[str, Any]:
    """Append the FRED-hosted market series through the official API."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    report: dict[str, Any] = {"retrieved_at": retrieved, "series": {}, "failures": []}
    for series_id, spec in FRED_API_SERIES.items():
        try:
            csv_text = observations_csv(
                series_id, observation_start=spec["observation_start"],
                fetch_text=fetch_text,
            )
            payload = csv_text.encode("utf-8")
            receipt = persist_market_raw(
                root, source_id=spec["source_id"],
                source_uri=observations_public_url(
                    series_id, observation_start=spec["observation_start"],
                ),
                payload=payload, retrieved_at=retrieved,
                http_status=200, content_type="text/csv",
            )
            report["series"][series_id] = _append_observations(
                root, source_id=spec["source_id"], series_id=series_id,
                unit="index", values=parse_fred_graph_csv(payload, series_id=series_id),
                receipt=receipt, available_at=_market_available_at,
                data_grade="captured_forward",
            )
        except (OSError, ValueError, FredApiError) as exc:
            report["failures"].append({"series": series_id, "reason": str(exc)})
    report["ok"] = not report["failures"]
    return report


def refresh_timeseries_v2_official(root: Path) -> dict[str, Any]:
    """Terms-compliant forward refresh: sealed collector minus the scrape, plus the API.

    Mirrors the sealed ``refresh_timeseries_v2`` guard sequence (protected
    hashes, lineage, parquet) while injecting the refusal fetcher and the
    official-API append.  The sealed module is imported, never modified.
    """
    before = protected_hashes(root)
    market = collect_official_market_archives(
        root, fetcher=refuse_fredgraph_fetch, collection_mode="forward_refresh",
    )
    fred = append_fred_official_api(root)
    if not fred["ok"]:
        raise TimeSeriesV2PipelineError(
            f"FRED official API append failed: {fred['failures'][:3]}"
        )
    lineage = verify_market_lineage(root)
    if not lineage["ok"]:
        raise TimeSeriesV2PipelineError(f"V2 market lineage failed: {lineage['errors'][:3]}")
    comparison = compare_protected_hashes(before, protected_hashes(root))
    if not comparison["ok"]:
        raise TimeSeriesV2PipelineError(f"protected path changed during V2 refresh: {comparison}")
    return {
        "market": market, "fred_official_api": fred, "lineage": lineage,
        "protected": comparison, "parquet": export_market_parquet(root),
    }
