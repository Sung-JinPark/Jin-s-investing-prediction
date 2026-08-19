"""Official-source request builders and point-in-time normalizers.

Network execution is explicit and raw-first.  No request is scheduled automatically,
and credentials/user-agent identity must be supplied by the caller.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .data_contracts import payload_sha256
from .facts import ObservationFact


@dataclass(frozen=True)
class RequestSpec:
    source_id: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None


def _url(base: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return f"{base}?{urllib.parse.urlencode(clean)}"


def alfred_request(
    series_id: str, *, api_key: str, realtime_start: str = "1776-07-04",
    realtime_end: str = "9999-12-31", output_type: int = 2,
) -> RequestSpec:
    if output_type not in {1, 2, 3, 4}:
        raise ValueError("ALFRED output_type must be one of 1, 2, 3, 4")
    return RequestSpec(
        source_id="alfred",
        method="GET",
        url=_url("https://api.stlouisfed.org/fred/series/observations", {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "output_type": output_type,
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
        }),
    )


def alfred_vintage_dates_request(
    series_id: str, *, api_key: str, realtime_start: str = "1776-07-04",
    realtime_end: str = "9999-12-31", limit: int = 10_000, offset: int = 0,
) -> RequestSpec:
    """Build a bounded vintage-date inventory request for PIT batching."""
    if not 1 <= limit <= 10_000 or offset < 0:
        raise ValueError("ALFRED vintage date pagination is invalid")
    return RequestSpec(
        source_id="alfred",
        method="GET",
        url=_url("https://api.stlouisfed.org/fred/series/vintagedates", {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
            "limit": limit,
            "offset": offset,
        }),
    )


def bls_request(
    series_ids: list[str], *, start_year: int, end_year: int,
    registration_key: str | None = None,
) -> RequestSpec:
    body = json.dumps({
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        **({"registrationkey": registration_key} if registration_key else {}),
    }).encode("utf-8")
    return RequestSpec(
        source_id="bls", method="POST",
        url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
        headers={"Content-Type": "application/json"}, body=body)


def bea_request(dataset: str, *, user_id: str, **parameters: str) -> RequestSpec:
    return RequestSpec(
        source_id="bea", method="GET",
        url=_url("https://apps.bea.gov/api/data/", {
            "UserID": user_id, "method": "GetData", "datasetname": dataset,
            "ResultFormat": "JSON", **parameters,
        }))


def treasury_request(path: str, **parameters: str) -> RequestSpec:
    safe_path = path.strip("/")
    return RequestSpec(
        source_id="treasury_fiscaldata", method="GET",
        url=_url(
            f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service/{safe_path}",
            parameters,
        ))


def nyfed_request(path: str, **parameters: str) -> RequestSpec:
    safe_path = path.strip("/")
    return RequestSpec(
        source_id="nyfed_markets", method="GET",
        url=_url(f"https://markets.newyorkfed.org/api/{safe_path}", parameters))


def edgar_companyfacts_request(cik: str, *, user_agent: str) -> RequestSpec:
    if "@" not in user_agent:
        raise ValueError("SEC requests require an identifying user-agent with contact email")
    padded = cik.removeprefix("CIK").zfill(10)
    return RequestSpec(
        source_id="sec_edgar", method="GET",
        url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json",
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})


def fetch(spec: RequestSpec, *, timeout: int = 60) -> tuple[int, bytes]:
    request = urllib.request.Request(
        spec.url, data=spec.body, headers=spec.headers, method=spec.method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read()


def alfred_facts(
    payload: bytes, *, series_id: str, retrieved_at: str,
    release_time: str = "08:30:00",
) -> list[ObservationFact]:
    """Normalize all ALFRED revisions; date-only realtime fields use release-time ET."""
    decoded = json.loads(payload)
    source_hash = payload_sha256(payload)
    facts: list[ObservationFact] = []
    for row in decoded.get("observations", []):
        if row.get("value") in (None, "."):
            continue
        start = f"{row['realtime_start']}T{release_time}"
        raw_end = row.get("realtime_end")
        end = None if raw_end in (None, "9999-12-31") else f"{raw_end}T{release_time}"
        facts.append(ObservationFact(
            source_id="alfred", series_id=series_id,
            observation_time=row["date"], value=float(row["value"]),
            available_at=start, vintage_start=start, vintage_end=end,
            retrieved_at=retrieved_at, source_revision_id=row["realtime_start"],
            source_hash=source_hash, parser_version="alfred-v1",
            timezone="America/New_York", calendar_id="US_FED",
        ))
    return facts


def edgar_fact(
    *, cik: str, accession_number: str, accepted_at: str, observation_time: str,
    series_id: str, value: float, payload: bytes, retrieved_at: str,
) -> ObservationFact:
    """Create a filing fact whose knowledge time is EDGAR acceptance, not period end."""
    available = datetime.fromisoformat(accepted_at.replace("Z", "+00:00")).isoformat()
    return ObservationFact(
        source_id="sec_edgar", series_id=f"CIK{cik.zfill(10)}:{series_id}",
        observation_time=observation_time, value=value,
        available_at=available, vintage_start=available, vintage_end=None,
        retrieved_at=retrieved_at, source_revision_id=accession_number,
        source_hash=payload_sha256(payload), parser_version="edgar-v1",
        timezone="America/New_York", calendar_id="US_SEC",
    )
