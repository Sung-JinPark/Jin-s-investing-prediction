"""Raw-first, append-only ALFRED ledger for multivariate forecasting."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import urllib.parse
import urllib.error
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from ai_fc.facts import ObservationFact
from ai_fc.official_sources import (
    RequestSpec,
    alfred_request,
    alfred_vintage_dates_request,
    fetch,
)

from .contracts import FACTS_RELATIVE, LEDGER_RELATIVE, RAW_RELATIVE, canonical_hash, load_contract


RECEIPTS_NAME = "raw_receipts.jsonl"
OBSERVATIONS_NAME = "observations.jsonl"
OBSERVATION_MANIFEST_NAME = "observation_chunks.jsonl"
OBSERVATION_CHUNKS_DIRECTORY = "observation_chunks"
PARQUET_NAME = "observations.parquet"
ALFRED_JSON_VINTAGE_LIMIT = 2_000
ALFRED_VINTAGE_BATCH_SIZE = 250
ALFRED_MINIMUM_SPLIT_BATCH_SIZE = 1


class AlfredFetchError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class RawTimeSeriesReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    receipt_id: str
    source_id: str
    series_id: str
    retrieved_at: str
    available_at: str
    raw_sha256: str = Field(min_length=64, max_length=64)
    raw_path: str
    request_fingerprint: str = Field(min_length=64, max_length=64)
    http_status: int
    byte_count: int


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append_unique(path: Path, row: dict[str, Any], *, id_field: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {str(item[id_field]): item for item in _jsonl(path)}
    key = str(row[id_field])
    if key in existing:
        if existing[key] != row:
            raise RuntimeError(f"append-only conflict for {id_field}={key}")
        return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return True


def _public_request_fingerprint(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    public = [(key, "REDACTED" if key.lower() == "api_key" else value) for key, value in query]
    clean = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(public), ""))
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _release_timestamp(day: str, release_time: str = "23:59:59") -> str:
    # ALFRED exposes vintage dates, not intraday publication timestamps. Using
    # end-of-day New York time prevents same-date values from entering early.
    local = datetime.fromisoformat(f"{day}T{release_time}").replace(tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc).isoformat()


def persist_response(
    root: Path, *, series_id: str, status: int, payload: bytes, retrieved_at: str,
    request_url: str,
) -> RawTimeSeriesReceipt:
    digest = hashlib.sha256(payload).hexdigest()
    raw_path = root / RAW_RELATIVE / "alfred" / f"{digest}.json.gz"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.exists():
        temporary = raw_path.with_suffix(".tmp")
        with temporary.open("wb") as raw_handle:
            with gzip.GzipFile(
                filename="", fileobj=raw_handle, mode="wb", compresslevel=9, mtime=0,
            ) as handle:
                handle.write(payload)
        os.replace(temporary, raw_path)
    available_at = retrieved_at
    receipt_body = {
        "schema_version": 1,
        "source_id": "alfred",
        "series_id": series_id,
        "retrieved_at": retrieved_at,
        "available_at": available_at,
        "raw_sha256": digest,
        "raw_path": raw_path.relative_to(root).as_posix(),
        "request_fingerprint": _public_request_fingerprint(request_url),
        "http_status": int(status),
        "byte_count": len(payload),
    }
    receipt = RawTimeSeriesReceipt(
        receipt_id=canonical_hash(receipt_body), **receipt_body,
    )
    _append_unique(
        root / LEDGER_RELATIVE / RECEIPTS_NAME,
        receipt.model_dump(mode="json"), id_field="receipt_id",
    )
    return receipt


def normalize_alfred(
    payload: bytes, *, series_id: str, retrieved_at: str,
) -> list[ObservationFact]:
    decoded = json.loads(payload)
    source_hash = hashlib.sha256(payload).hexdigest()
    facts: list[ObservationFact] = []
    for row in decoded.get("observations", []):
        if decoded.get("output_type") == 3:
            prefix = f"{series_id}_"
            for column, raw_value in row.items():
                if column == "date" or not column.startswith(prefix):
                    continue
                suffix = column[len(prefix):]
                if len(suffix) != 8 or not suffix.isdigit() or raw_value in (None, "."):
                    continue
                vintage_day = datetime.strptime(suffix, "%Y%m%d").date().isoformat()
                start = _release_timestamp(vintage_day)
                facts.append(ObservationFact(
                    source_id="alfred",
                    series_id=series_id,
                    observation_time=str(row["date"]),
                    value=float(raw_value),
                    available_at=start,
                    vintage_start=start,
                    vintage_end=None,
                    retrieved_at=retrieved_at,
                    source_revision_id=f"{series_id}:{vintage_day}",
                    source_hash=source_hash,
                    parser_version="multivariate-alfred-v2-wide",
                    timezone="America/New_York",
                    calendar_id="US_FED",
                ))
            continue
        if row.get("value") in (None, "."):
            continue
        start = _release_timestamp(str(row["realtime_start"]))
        raw_end = row.get("realtime_end")
        end = None if raw_end in (None, "9999-12-31") else _release_timestamp(str(raw_end))
        if end is not None and datetime.fromisoformat(end) <= datetime.fromisoformat(start):
            # ALFRED real-time end dates are inclusive. A one-day vintage may
            # therefore carry identical start/end dates; our fact interval is
            # exclusive at the right boundary, so retain a positive interval.
            end = (datetime.fromisoformat(start) + timedelta(seconds=1)).isoformat()
        facts.append(ObservationFact(
            source_id="alfred",
            series_id=series_id,
            observation_time=str(row["date"]),
            value=float(row["value"]),
            available_at=start,
            vintage_start=start,
            vintage_end=end,
            retrieved_at=retrieved_at,
            source_revision_id=f"{series_id}:{row['realtime_start']}",
            source_hash=source_hash,
            parser_version="multivariate-alfred-v1",
            timezone="America/New_York",
            calendar_id="US_FED",
        ))
    return facts


def _close_vintage_intervals(
    root: Path, facts: Iterable[ObservationFact],
) -> list[ObservationFact]:
    """Close only touched observation histories at the next known vintage."""
    incoming = list(facts)
    if not incoming:
        return []
    touched = {
        (fact.source_id, fact.series_id, fact.observation_time)
        for fact in incoming
    }
    combined: dict[tuple[str, str, str, str], ObservationFact] = {
        fact.key: fact for fact in read_facts(root)
        if (fact.source_id, fact.series_id, fact.observation_time) in touched
    }
    for fact in incoming:
        combined[fact.key] = fact

    grouped: dict[tuple[str, str, str], list[ObservationFact]] = {}
    for fact in combined.values():
        group_key = (fact.source_id, fact.series_id, fact.observation_time)
        grouped.setdefault(group_key, []).append(fact)

    closed: list[ObservationFact] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda fact: fact.vintage_start)
        for index, fact in enumerate(ordered):
            next_start = ordered[index + 1].vintage_start if index + 1 < len(ordered) else None
            closed.append(fact.model_copy(update={"vintage_end": next_start}))
    return sorted(closed, key=lambda fact: fact.key)


def rebuild_facts_from_raw(root: Path) -> dict[str, int]:
    """Idempotently rebuild normalized PIT facts from preserved raw receipts."""
    facts: list[ObservationFact] = []
    observation_receipts = 0
    for receipt in _jsonl(root / LEDGER_RELATIVE / RECEIPTS_NAME):
        raw_path = root / str(receipt["raw_path"])
        if not raw_path.is_file():
            raise RuntimeError(f"missing ALFRED raw artifact: {raw_path.relative_to(root)}")
        payload = gzip.decompress(raw_path.read_bytes())
        digest = hashlib.sha256(payload).hexdigest()
        if digest != receipt["raw_sha256"]:
            raise RuntimeError(f"ALFRED raw hash mismatch: {raw_path.relative_to(root)}")
        decoded = json.loads(payload)
        if "observations" not in decoded:
            continue
        observation_receipts += 1
        facts.extend(normalize_alfred(
            payload,
            series_id=str(receipt["series_id"]),
            retrieved_at=str(receipt["retrieved_at"]),
        ))
    result = append_facts(root, _close_vintage_intervals(root, facts))
    return {**result, "observation_receipts": observation_receipts}


def append_facts(root: Path, facts: Iterable[ObservationFact]) -> dict[str, int]:
    manifest_path = root / LEDGER_RELATIVE / OBSERVATION_MANIFEST_NAME
    existing_rows = read_fact_rows(root)
    existing_ids = {str(row["observation_id"]): row for row in existing_rows}
    existing: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in existing_rows:
        key = (row["source_id"], row["series_id"], row["observation_time"], row["vintage_start"])
        prior = existing.get(key)
        if prior is None or int(row["revision_seq"]) > int(prior["revision_seq"]):
            existing[key] = row
    appended = 0
    corrected = 0
    pending_rows: list[dict[str, Any]] = []
    for fact in facts:
        row = fact.model_dump(mode="json")
        key = fact.key
        prior = existing.get(key)
        if prior is not None:
            semantic_prior = {key: prior.get(key) for key in ("value", "value_status", "vintage_end")}
            semantic_new = {key: row.get(key) for key in ("value", "value_status", "vintage_end")}
            if semantic_prior == semantic_new:
                continue
            revision_seq = int(prior["revision_seq"]) + 1
            supersedes = str(prior["observation_id"])
            corrected += 1
        else:
            revision_seq = 0
            supersedes = None
        ledger_seed = {
            **row,
            "revision_seq": revision_seq,
            "supersedes_observation_id": supersedes,
        }
        observation_id = canonical_hash(ledger_seed)
        ledger_row = {"observation_id": observation_id, **ledger_seed}
        prior_id_row = existing_ids.get(observation_id)
        if prior_id_row is not None and prior_id_row != ledger_row:
            raise RuntimeError(f"append-only conflict for observation_id={observation_id}")
        if prior_id_row is None:
            pending_rows.append(ledger_row)
            existing_ids[observation_id] = ledger_row
        existing[key] = ledger_row
        appended += 1
    if pending_rows:
        rows_by_series_decade: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in pending_rows:
            observation_year = str(row["observation_time"])[:4]
            observation_decade = f"{observation_year[:3]}0s"
            partition = (str(row["series_id"]), observation_decade)
            rows_by_series_decade.setdefault(partition, []).append(row)
        for (series_id, observation_decade), series_rows in sorted(rows_by_series_decade.items()):
            body = "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for row in series_rows
            ).encode("utf-8")
            content_sha256 = hashlib.sha256(body).hexdigest()
            chunk_path = (
                root / FACTS_RELATIVE / OBSERVATION_CHUNKS_DIRECTORY
                / f"{content_sha256}.jsonl.gz"
            )
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            if not chunk_path.exists():
                temporary = chunk_path.with_suffix(".tmp")
                with temporary.open("wb") as raw_handle:
                    with gzip.GzipFile(
                        filename="", fileobj=raw_handle, mode="wb", compresslevel=9, mtime=0,
                    ) as handle:
                        handle.write(body)
                os.replace(temporary, chunk_path)
            manifest_body = {
                "schema_version": 1,
                "chunk_id": content_sha256,
                "series_id": series_id,
                "observation_decade": observation_decade,
                "content_sha256": content_sha256,
                "chunk_path": chunk_path.relative_to(root).as_posix(),
                "row_count": len(series_rows),
                "created_at": max(str(row["retrieved_at"]) for row in series_rows),
                "first_observation_id": str(series_rows[0]["observation_id"]),
                "last_observation_id": str(series_rows[-1]["observation_id"]),
            }
            _append_unique(
                manifest_path, manifest_body, id_field="chunk_id",
            )
    if appended:
        build_parquet_training_view(root)
    return {
        "existing": len(existing_rows),
        "appended": appended,
        "corrected": corrected,
        "total": len(existing_rows) + appended,
    }


def read_fact_rows(root: Path) -> list[dict[str, Any]]:
    """Read legacy rows plus immutable content-addressed JSONL gzip chunks."""
    rows = _jsonl(root / LEDGER_RELATIVE / OBSERVATIONS_NAME)
    chunk_root = (root / FACTS_RELATIVE / OBSERVATION_CHUNKS_DIRECTORY).resolve()
    for manifest in _jsonl(root / LEDGER_RELATIVE / OBSERVATION_MANIFEST_NAME):
        chunk_path = (root / str(manifest["chunk_path"])).resolve()
        if not chunk_path.is_relative_to(chunk_root):
            raise RuntimeError(f"observation chunk escaped registered root: {manifest['chunk_path']}")
        if not chunk_path.is_file():
            raise RuntimeError(f"missing observation chunk: {manifest['chunk_path']}")
        body = gzip.decompress(chunk_path.read_bytes())
        digest = hashlib.sha256(body).hexdigest()
        if digest != manifest["content_sha256"] or digest != manifest["chunk_id"]:
            raise RuntimeError(f"observation chunk hash mismatch: {manifest['chunk_path']}")
        chunk_rows = [json.loads(line) for line in body.decode("utf-8").splitlines() if line]
        if len(chunk_rows) != int(manifest["row_count"]):
            raise RuntimeError(f"observation chunk row-count mismatch: {manifest['chunk_path']}")
        rows.extend(chunk_rows)
    return rows


def read_facts(root: Path) -> list[ObservationFact]:
    latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in read_fact_rows(root):
        key = (row["source_id"], row["series_id"], row["observation_time"], row["vintage_start"])
        prior = latest.get(key)
        if prior is None or int(row["revision_seq"]) > int(prior["revision_seq"]):
            if prior is not None and row.get("supersedes_observation_id") != prior.get("observation_id"):
                raise RuntimeError(f"branched observation correction: {key}")
            latest[key] = row
    ignored = {"observation_id", "revision_seq", "supersedes_observation_id"}
    return [
        ObservationFact.model_validate({key: value for key, value in row.items() if key not in ignored})
        for row in sorted(latest.values(), key=lambda item: (
            item["series_id"], item["observation_time"], item["vintage_start"],
        ))
    ]


def build_parquet_training_view(root: Path) -> Path:
    """Rebuild the disposable Parquet read model from the append-only JSONL ledger."""
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("install ai-fc[pit] for the Parquet training view") from exc
    rows = [fact.model_dump(mode="json") for fact in read_facts(root)]
    target = root / FACTS_RELATIVE / PARQUET_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.parquet")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, target)
    return target


def registered_series(
    contract: dict[str, Any], *, include_optional: bool = True,
    include_historical_bridge: bool = True,
) -> list[str]:
    sources = contract["sources"]
    groups = ["daily_required", "growth_required", "inflation_required"]
    if include_optional:
        groups.append("financial_optional")
    if include_historical_bridge:
        groups.append("historical_bridge")
    return sorted({series for group in groups for series in sources[group]})


def _fetch_alfred(
    spec: RequestSpec, *, series_id: str, endpoint: str, max_attempts: int = 4,
    timeout_seconds: int = 300,
) -> tuple[int, bytes]:
    """Fetch without ever surfacing a credential-bearing URL."""
    if max_attempts < 1 or timeout_seconds < 1:
        raise ValueError("ALFRED attempts and timeout must be positive")
    for attempt in range(max_attempts):
        try:
            return fetch(spec, timeout=timeout_seconds)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            message = f"HTTP {exc.code}"
            try:
                decoded = json.loads(body)
                message = str(
                    decoded.get("error_message")
                    or decoded.get("message")
                    or message
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            retryable = exc.code in {429, 500, 502, 503, 504}
            if retryable and attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            raise AlfredFetchError(
                f"ALFRED {series_id} {endpoint} returned HTTP {exc.code}: {message}",
                retryable=retryable,
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            raise AlfredFetchError(
                f"ALFRED {series_id} {endpoint} network timeout or failure",
                retryable=True,
            ) from exc
    raise AlfredFetchError(
        f"ALFRED {series_id} {endpoint} retry exhaustion",
        retryable=True,
    )


def _observation_responses(
    *, series_id: str, api_key: str, vintage_dates: list[str],
) -> list[tuple[RequestSpec, int, bytes]]:
    """Adaptively split only server-size failures; never hide contract errors."""
    spec = alfred_request(
        series_id,
        api_key=api_key,
        realtime_start=vintage_dates[0],
        realtime_end=vintage_dates[-1],
        output_type=3,
    )
    # A multi-vintage response can be expensive enough to time out even when
    # the requested window is already small. Split immediately so one slow
    # range cannot consume four full timeout windows; retry only the atomic
    # single-vintage request, which cannot be divided without changing PIT
    # semantics.
    attempts = 4 if len(vintage_dates) == ALFRED_MINIMUM_SPLIT_BATCH_SIZE else 1
    timeout_seconds = 60
    try:
        status, payload = _fetch_alfred(
            spec,
            series_id=series_id,
            endpoint="observations",
            max_attempts=attempts,
            timeout_seconds=timeout_seconds,
        )
        return [(spec, status, payload)]
    except AlfredFetchError as exc:
        splittable_status = exc.status is None or exc.status in {500, 502, 503, 504}
        if (
            not exc.retryable
            or not splittable_status
            or len(vintage_dates) <= ALFRED_MINIMUM_SPLIT_BATCH_SIZE
        ):
            raise
        midpoint = len(vintage_dates) // 2
        return [
            *_observation_responses(
                series_id=series_id,
                api_key=api_key,
                vintage_dates=vintage_dates[:midpoint],
            ),
            *_observation_responses(
                series_id=series_id,
                api_key=api_key,
                vintage_dates=vintage_dates[midpoint:],
            ),
        ]


def _vintage_date_batches(
    root: Path, *, series_id: str, api_key: str, retrieved_at: str,
    realtime_start: str, realtime_end: str,
) -> tuple[list[list[str]], list[RawTimeSeriesReceipt]]:
    dates: list[str] = []
    receipts: list[RawTimeSeriesReceipt] = []
    offset = 0
    while True:
        spec = alfred_vintage_dates_request(
            series_id,
            api_key=api_key,
            realtime_start=realtime_start,
            realtime_end=realtime_end,
            offset=offset,
        )
        status, payload = _fetch_alfred(
            spec, series_id=series_id, endpoint="vintage_dates",
        )
        receipts.append(persist_response(
            root,
            series_id=series_id,
            status=status,
            payload=payload,
            retrieved_at=retrieved_at,
            request_url=spec.url,
        ))
        decoded = json.loads(payload)
        page = [str(value) for value in decoded.get("vintage_dates", [])]
        dates.extend(page)
        count = int(decoded.get("count", len(page)))
        offset += len(page)
        if not page or offset >= count:
            break
    unique_dates = sorted(set(dates))
    batches = [
        unique_dates[index:index + ALFRED_VINTAGE_BATCH_SIZE]
        for index in range(0, len(unique_dates), ALFRED_VINTAGE_BATCH_SIZE)
    ]
    if any(len(batch) > ALFRED_JSON_VINTAGE_LIMIT for batch in batches):
        raise RuntimeError(f"ALFRED {series_id} vintage batch exceeds API contract")
    return batches, receipts


def collect_alfred(
    root: Path, *, api_key: str, series_ids: list[str] | None = None,
    retrieved_at: str | None = None, realtime_start: str = "1776-07-04",
    realtime_end: str = "9999-12-31", allow_partial_retryable: bool = False,
) -> dict[str, Any]:
    contract = load_contract(root)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    requested = series_ids or registered_series(contract)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pending_facts: list[ObservationFact] = []
    effective_start = realtime_start
    if realtime_start == "1776-07-04":
        effective_start = str(contract["model"]["windows"]["expanding_start"])
    for series_id in requested:
        try:
            batches, receipts = _vintage_date_batches(
                root,
                series_id=series_id,
                api_key=api_key,
                retrieved_at=retrieved,
                realtime_start=effective_start,
                realtime_end=realtime_end,
            )
        except AlfredFetchError as exc:
            if not allow_partial_retryable or not exc.retryable:
                raise
            failures.append({
                "series_id": series_id,
                "status": exc.status,
                "retryable": True,
                "reason": str(exc),
            })
            continue
        normalized_count = 0
        for batch in batches:
            for spec, status, payload in _observation_responses(
                series_id=series_id,
                api_key=api_key,
                vintage_dates=batch,
            ):
                receipts.append(persist_response(
                    root,
                    series_id=series_id,
                    status=status,
                    payload=payload,
                    retrieved_at=retrieved,
                    request_url=spec.url,
                ))
                facts = normalize_alfred(
                    payload, series_id=series_id, retrieved_at=retrieved,
                )
                normalized_count += len(facts)
                pending_facts.extend(facts)
        results.append({
            "series_id": series_id,
            "vintage_count": sum(len(batch) for batch in batches),
            "batch_count": len(batches),
            "receipt_ids": [receipt.receipt_id for receipt in receipts],
            "raw_sha256s": [receipt.raw_sha256 for receipt in receipts],
            "normalized_facts": normalized_count,
        })
    fact_result = append_facts(root, _close_vintage_intervals(root, pending_facts))
    return {
        "retrieved_at": retrieved,
        "realtime_window": {"start": effective_start, "end": realtime_end},
        "facts": fact_result,
        "series": results,
        "failures": failures,
    }


def incremental_realtime_window(root: Path, *, retrieved_at: str, overlap_days: int = 7) -> tuple[str, str]:
    receipts = _jsonl(root / LEDGER_RELATIVE / RECEIPTS_NAME)
    current = datetime.fromisoformat(retrieved_at).astimezone(timezone.utc)
    if not receipts:
        return "1776-07-04", "9999-12-31"
    prior = max(datetime.fromisoformat(row["retrieved_at"]) for row in receipts)
    start = min(prior.astimezone(timezone.utc), current) - timedelta(days=overlap_days)
    return start.date().isoformat(), current.date().isoformat()
