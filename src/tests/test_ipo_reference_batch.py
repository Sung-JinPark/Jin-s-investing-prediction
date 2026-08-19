from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_fc.ipo_reference_batch import (
    ACADEMIC_SOURCE_IDS,
    IPO_REFERENCE_PATH,
    refresh_ipo_reference_batch,
)


ROOT = Path(__file__).resolve().parents[2]


def _install_reference(tmp_path: Path) -> dict:
    payload = json.loads(
        (ROOT / IPO_REFERENCE_PATH).read_text(encoding="utf-8")
    )
    target = tmp_path / IPO_REFERENCE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def test_reference_batch_is_idempotent_and_locks_historical_rows(tmp_path: Path) -> None:
    payload = _install_reference(tmp_path)
    sources = {
        source["series_id"]: source for source in payload["sources"]
    }
    bodies = {
        sources[source_id]["source_url"]: f"payload-{source_id}".encode()
        for source_id in ACADEMIC_SOURCE_IDS
    }
    for source_id in ACADEMIC_SOURCE_IDS:
        sources[source_id]["raw_sha256"] = hashlib.sha256(
            bodies[sources[source_id]["source_url"]]
        ).hexdigest()
    reference_path = tmp_path / IPO_REFERENCE_PATH
    reference_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    before = reference_path.read_bytes()

    def fetcher(url: str):
        return bodies[url], 200, '"etag"', "Wed, 19 Aug 2026 00:00:00 GMT"

    _, first, appended = refresh_ipo_reference_batch(
        tmp_path,
        checked_at="2026-08-19T00:00:00+00:00",
        fetcher=fetcher,
    )
    _, second, second_appended = refresh_ipo_reference_batch(
        tmp_path,
        checked_at="2026-08-20T00:00:00+00:00",
        fetcher=fetcher,
    )
    assert first["status"] == second["status"] == "current"
    assert appended == len(ACADEMIC_SOURCE_IDS)
    assert second_appended == 0
    assert all(row["historical_rows_locked"] is True for row in first["sources"])
    assert reference_path.read_bytes() == before


def test_reference_batch_flags_changed_academic_source_for_review(tmp_path: Path) -> None:
    payload = _install_reference(tmp_path)
    sources = {
        source["series_id"]: source for source in payload["sources"]
    }
    bodies = {
        source_id: (
            b"changed-publication"
            if source_id == "RITTER_TECH_IPO_2025"
            else f"stable-{source_id}".encode()
        )
        for source_id in ACADEMIC_SOURCE_IDS
    }
    for source_id in ACADEMIC_SOURCE_IDS:
        if source_id != "RITTER_TECH_IPO_2025":
            sources[source_id]["raw_sha256"] = hashlib.sha256(
                bodies[source_id]
            ).hexdigest()
    (tmp_path / IPO_REFERENCE_PATH).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    def fetcher(url: str):
        source_id = next(
            source_id for source_id in ACADEMIC_SOURCE_IDS
            if sources[source_id]["source_url"] == url
        )
        return bodies[source_id], 200, None, None

    _, status, _ = refresh_ipo_reference_batch(
        tmp_path,
        checked_at="2026-08-19T00:00:00+00:00",
        fetcher=fetcher,
    )
    by_id = {row["source_id"]: row for row in status["sources"]}
    assert status["status"] == "review_required"
    assert by_id["RITTER_TECH_IPO_2025"]["status"] == "review_required"
    assert all(
        by_id[source_id]["status"] == "current"
        for source_id in ACADEMIC_SOURCE_IDS
        if source_id != "RITTER_TECH_IPO_2025"
    )
    assert status["allowed_update_scope"] == "current_era_rows_only_after_review"
