from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


IPO_REFERENCE_PATH = Path("data/statistics/ipo/ipo_comparison_v1.json")
STATUS_PATH = Path("data/statistics/ipo/reference_batch_status.json")
RECEIPT_DIRECTORY = Path("data/statistics/ipo/reference_batch_receipts")
USER_AGENT = "JinsInvestingIPOReferenceBatch/1.0 (+public research dashboard)"
ACADEMIC_SOURCE_IDS = (
    "RITTER_TECH_IPO_2025",
    "RITTER_INTERNET_IPO_2025",
    "RITTER_IPO_SALES_2025",
    "RITTER_IPO_UNDERPRICING_2025",
)


class IPOReferenceBatchError(RuntimeError):
    pass


def _fetch(url: str) -> tuple[bytes, int, str | None, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return (
            response.read(),
            int(response.status),
            response.headers.get("ETag"),
            response.headers.get("Last-Modified"),
        )


def refresh_ipo_reference_batch(
    root: Path,
    *,
    checked_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, int, str | None, str | None]] = _fetch,
) -> tuple[Path, dict[str, object], int]:
    """Check refreshable academic IPO sources without rewriting cited history.

    Content changes create a review-required receipt.  They never mutate the
    historical dot-com rows or silently promote unreviewed current values.
    Reviewed changes are applied to the current-era rows in
    ``ipo_comparison_v1.json`` and picked up by the weekly statistics build.
    """

    checked = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_path = root / IPO_REFERENCE_PATH
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IPOReferenceBatchError("IPO reference source cannot be read") from exc
    sources = {
        str(source.get("series_id")): source for source in payload.get("sources") or []
    }
    missing = [source_id for source_id in ACADEMIC_SOURCE_IDS if source_id not in sources]
    if missing:
        raise IPOReferenceBatchError(
            f"IPO academic source registry incomplete: {', '.join(missing)}"
        )

    receipt_directory = root / RECEIPT_DIRECTORY
    receipt_directory.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, object]] = []
    new_receipts = 0
    for source_id in ACADEMIC_SOURCE_IDS:
        source = sources[source_id]
        source_url = str(source.get("source_url", ""))
        reviewed_sha = str(source.get("raw_sha256", ""))
        try:
            body, http_status, etag, last_modified = fetcher(source_url)
            observed_sha = hashlib.sha256(body).hexdigest()
            status = "current" if observed_sha == reviewed_sha else "review_required"
            error = None
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            body = b""
            http_status = 0
            etag = None
            last_modified = None
            observed_sha = None
            status = "fetch_failed"
            error = type(exc).__name__
        receipt = {
            "schema_version": 1,
            "source_id": source_id,
            "checked_at": checked,
            "source_url": source_url,
            "http_status": http_status,
            "observed_sha256": observed_sha,
            "reviewed_sha256": reviewed_sha,
            "content_bytes": len(body),
            "etag": etag,
            "last_modified": last_modified,
            "status": status,
            "error": error,
            "historical_rows_locked": True,
            "allowed_update_scope": "current_era_rows_only_after_review",
        }
        receipt_key = observed_sha or hashlib.sha256(
            f"{source_id}|{checked}|{error}".encode("utf-8")
        ).hexdigest()
        receipt_path = receipt_directory / f"{source_id.lower()}_{receipt_key[:16]}.json"
        if not receipt_path.exists():
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            new_receipts += 1
        observations.append({
            **receipt,
            "receipt_path": receipt_path.relative_to(root).as_posix(),
        })

    status_payload: dict[str, object] = {
        "schema_version": 1,
        "dataset_id": "ipo_reference_current_era_batch_v1",
        "checked_at": checked,
        "status": (
            "review_required"
            if any(row["status"] == "review_required" for row in observations)
            else "degraded"
            if any(row["status"] == "fetch_failed" for row in observations)
            else "current"
        ),
        "cadence": "weekly",
        "historical_rows_locked": True,
        "allowed_update_scope": "current_era_rows_only_after_review",
        "forecast_extension": False,
        "sources": observations,
    }
    status_path = root / STATUS_PATH
    status_path.write_text(
        json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return status_path, status_payload, new_receipts
