"""FRED/ALFRED vintage parser; network transport is injected elsewhere."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_vintages(series_id: str, observations: list[dict[str, str]], *, ingested_at: datetime) -> list[dict[str, object]]:
    rows = []
    for item in observations:
        if item.get("value") in {None, "."}:
            continue
        available = datetime.fromisoformat(item["realtime_start"]).replace(tzinfo=timezone.utc)
        rows.append({
            "series_id": series_id, "observation_time": item["date"],
            "available_at": available, "ingested_at": ingested_at,
            "value": float(item["value"]), "data_grade": "native_pit",
            "vintage_start": item["realtime_start"], "vintage_end": item["realtime_end"],
        })
    return sorted(rows, key=lambda row: (row["observation_time"], row["available_at"]))
