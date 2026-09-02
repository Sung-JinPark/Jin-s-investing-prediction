"""V9-owned market lane: CBOE VXN daily closes with locator-only receipts.

Approved by V9-D6 (2026-09-02): the CBOE usage-scope extension is authorised
with raw payloads NOT committed — receipts carry a private locator and the
payload hash only (the V5 CBOE precedent), honouring the 12-1/12-5 terms
posture.  The sealed V2 store is never written (`v2_store_write: prohibited`);
this lane keeps its own append-only ledgers under ``data/timeseries_v9/``.

Pure helpers from the sealed V2 module (CSV parser, the 16:15-ET availability
convention) are imported read-only; nothing in the sealed hash set changes.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_fc.timeseries_v2.market_archive import (  # pure functions, read-only reuse
    _market_available_at,
    parse_cboe_vix_csv,
)
from .contracts import LEDGER_RELATIVE, TimeSeriesV9ContractError, canonical_hash

VXN_SOURCE_ID = "cboe_vxn_archive"
VXN_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv"
MARKET_RECEIPTS_RELATIVE = LEDGER_RELATIVE / "market_receipts.jsonl"
MARKET_FACTS_RELATIVE = LEDGER_RELATIVE / "market_observations.jsonl"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ai-fc-research"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise TimeSeriesV9ContractError(f"VXN source returned HTTP {response.status}")
        return response.read()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")


def collect_vxn(
    root: Path, *, fetcher: Callable[[str], bytes] | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Append new VXN closes idempotently; raw stays uncommitted by design."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = (fetcher or _fetch)(VXN_URL)
    digest = hashlib.sha256(payload).hexdigest()
    rows = parse_cboe_vix_csv(payload)
    if not rows:
        raise TimeSeriesV9ContractError("VXN payload parsed to zero observations")
    receipt = {
        "receipt_id": f"v9-market-{canonical_hash({'source': VXN_SOURCE_ID, 'sha': digest})[:24]}",
        "source_id": VXN_SOURCE_ID,
        "source_uri": VXN_URL,
        "retrieved_at": retrieved,
        "raw_sha256": digest,
        # 12-1/12-5 posture: the payload itself is never committed.
        "raw_path": f"private://timeseries-v9/{VXN_SOURCE_ID}/{digest}",
        "redistribution": "private_locator_only",
        "row_count": len(rows),
    }
    existing = {
        (row["series_id"], row["observation_time"]): row
        for row in _read_jsonl(root / MARKET_FACTS_RELATIVE)
    }
    pending: list[dict[str, Any]] = []
    unchanged = 0
    for day, value in sorted(rows):
        key = ("VXN", day)
        prior = existing.get(key)
        if prior is not None:
            if float(prior["value"]) != float(value):
                raise TimeSeriesV9ContractError(
                    f"VXN close changed for {day}: settled index values must not move"
                )
            unchanged += 1
            continue
        pending.append({
            "series_id": "VXN",
            "observation_time": day,
            "value": float(value),
            "unit": "index",
            "available_at": _market_available_at(day),
            "data_grade": "reconstructed_market_archive",
            "receipt_id": receipt["receipt_id"],
        })
    if pending:
        _append_jsonl(root / MARKET_RECEIPTS_RELATIVE, [receipt])
        _append_jsonl(root / MARKET_FACTS_RELATIVE, pending)
    return {"appended": len(pending), "unchanged": unchanged,
            "receipt_id": receipt["receipt_id"] if pending else None,
            "raw_sha256": digest, "observation_span": [rows[0][0], rows[-1][0]]}


def read_vxn(root: Path) -> list[tuple[str, str, float]]:
    """(observation_time, available_at, value) for the collected VXN closes."""
    facts = _read_jsonl(root / MARKET_FACTS_RELATIVE)
    out = [
        (str(row["observation_time"]), str(row["available_at"]), float(row["value"]))
        for row in facts if row.get("series_id") == "VXN"
    ]
    out.sort()
    return out
