"""Official-source collectors owned by the R4 namespace."""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from .integrity import canonical_json, sha256_bytes, sha256_file

NASDAQCOM_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM"


def _last_completed_xnas_session(now: datetime) -> str:
    calendar = xcals.get_calendar("XNAS")
    timestamp = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    today = timestamp.normalize().tz_localize(None)
    sessions = calendar.sessions_in_range(today - pd.Timedelta(days=14), today)
    completed: list[pd.Timestamp] = []
    for session in sessions:
        close = calendar.session_close(session)
        if close <= timestamp:
            completed.append(session)
    if not completed:
        raise RuntimeError("no completed XNAS session in lookback")
    return completed[-1].date().isoformat()


def collect_nasdaqcom(output_root: Path, *, now: datetime | None = None,
                      payload: bytes | None = None) -> dict[str, Any]:
    retrieved_at = now or datetime.now(timezone.utc)
    if payload is None:
        request = urllib.request.Request(NASDAQCOM_URL, headers={"User-Agent": "ai-investing-r4/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    raw_hash = sha256_bytes(payload)
    raw_dir = output_root / "raw/nasdaqcom"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{raw_hash}.csv"
    if not raw_path.exists():
        raw_path.write_bytes(payload)
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    observations: list[dict[str, Any]] = []
    for row in reader:
        date_value = row.get("observation_date") or row.get("DATE")
        value = row.get("NASDAQCOM")
        if not date_value or value in (None, "", "."):
            continue
        observations.append({"series_id": "NASDAQCOM", "date": date_value,
                             "value": float(value), "source": "FRED",
                             "available_at": retrieved_at.isoformat(),
                             "raw_sha256": raw_hash})
    if not observations:
        raise ValueError("FRED NASDAQCOM payload has no observations")
    latest = observations[-1]
    target_session = _last_completed_xnas_session(retrieved_at)
    calendar = xcals.get_calendar("XNAS")
    sessions = calendar.sessions_in_range(pd.Timestamp(latest["date"]), pd.Timestamp(target_session))
    missing_sessions = max(0, len(sessions) - 1)
    materialized = output_root / "market/nasdaqcom_observations.jsonl"
    materialized.parent.mkdir(parents=True, exist_ok=True)
    existing: set[tuple[str, float, str]] = set()
    if materialized.exists():
        for line in materialized.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            existing.add((item["date"], item["value"], item["raw_sha256"]))
    new_rows = [item for item in observations
                if (item["date"], item["value"], item["raw_sha256"]) not in existing]
    if new_rows:
        with materialized.open("a", encoding="utf-8", newline="\n") as handle:
            for item in new_rows:
                handle.write(canonical_json(item).decode("utf-8") + "\n")
    receipt = {
        "schema_version": 1, "source": "FRED", "series_id": "NASDAQCOM",
        "request_url": NASDAQCOM_URL, "retrieved_at": retrieved_at.isoformat(),
        "raw_path": str(raw_path), "raw_sha256": raw_hash, "raw_bytes": len(payload),
        "observation_count": len(observations), "new_rows": len(new_rows),
        "latest_observation": latest, "target_completed_xnas_session": target_session,
        "missing_completed_sessions": missing_sessions,
        "freshness_pass": missing_sessions <= 1,
    }
    receipt_dir = output_root / "receipts/nasdaqcom"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{raw_hash}.json"
    if not receipt_path.exists():
        receipt_path.write_bytes(canonical_json(receipt) + b"\n")
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = sha256_file(receipt_path)
    return receipt
