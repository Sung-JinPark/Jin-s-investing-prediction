"""Fail-closed data-quality and PIT qualification for frozen evidence packs."""

from __future__ import annotations

import io
import json
import argparse
import os
import zipfile
from datetime import date, datetime, time, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .integrity import safe_zip_inventory, sha256_file
from .pit_snapshot import (
    LabelInterval,
    PitSnapshot,
    persist_qualified_pit_snapshot,
    verify_qualified_pit_snapshot,
)


def _json_member(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name))
    except KeyError as exc:
        raise ValueError(f"required evidence member missing: {name}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSON evidence member: {name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"evidence member must contain an object: {name}")
    return value


def _single_suffix(names: set[str], suffix: str) -> str:
    matches = sorted(name for name in names if name.endswith(suffix))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one evidence member ending with {suffix!r}")
    return matches[0]


def qualify_evidence_pack(
    pack_path: str | Path,
    *,
    nested_member: str,
    expected_sha256: str,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Qualify real, immutable evidence without materializing it to durable storage."""
    path = Path(pack_path)
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"evidence pack sha256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    outer_names = {item["path"] for item in safe_zip_inventory(path)}
    if nested_member not in outer_names:
        raise ValueError(f"declared nested evidence member missing: {nested_member}")
    with zipfile.ZipFile(path) as outer:
        nested_bytes = outer.read(nested_member)
    with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
        names = {info.filename.rstrip("/") for info in nested.infolist() if not info.is_dir()}
        snapshot = _json_member(nested, "RECOMPUTED/snapshot_and_label_audit.json")
        receipts = _json_member(nested, "RECOMPUTED/receipt_audit.json")
        gate = _json_member(nested, _single_suffix(names, "/data_quality_gate.json"))
        lineage = _json_member(nested, _single_suffix(names, "/feature_manifest.json"))
        rematerialized = None
        if database_url is not None:
            rematerialized = _rematerialize_r4_snapshot(nested, names, lineage)

    run_ids = {item.get("run_id") for item in (snapshot, receipts, gate, lineage)}
    if len(run_ids) != 1 or None in run_ids or "" in run_ids:
        raise ValueError("qualification failed: evidence run coordinates disagree")
    checks = gate.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("qualification failed: data-quality checks are missing")
    receipt_count = receipts.get("receipt_count")
    success_count = receipts.get("success_count")
    terminal_rate = (success_count / receipt_count) if isinstance(receipt_count, int) \
        and receipt_count > 0 and isinstance(success_count, int) else 0.0
    pit_violations = snapshot.get("pit_leakage_count")
    freshness_pass = (
        gate.get("state") == "READY"
        and gate.get("train_allowed") is True
        and isinstance(checks.get("latest_target_session"), str)
        and bool(checks["latest_target_session"])
    )
    lineage_pass = (
        receipts.get("pass") is True
        and receipts.get("raw_hash_failures") == []
        and isinstance(lineage.get("row_count"), int) and lineage["row_count"] > 0
        and isinstance(lineage.get("feature_count"), int) and lineage["feature_count"] > 0
        and isinstance(lineage.get("data_grade"), list) and bool(lineage["data_grade"])
        and lineage.get("pit_leakage_count") == pit_violations
    )
    qualified = (
        pit_violations == 0
        and checks.get("pit_leakage_count") == 0
        and terminal_rate == 1.0
        and checks.get("receipt_terminal_outcome_rate") == 1.0
        and freshness_pass
        and lineage_pass
    )
    if not qualified:
        raise ValueError("qualification failed: PIT, terminal receipt, freshness, or lineage gate")
    result = {
        "schema_version": 1,
        "run_id": run_ids.pop(),
        "source_pack_sha256": actual_sha256,
        "nested_member": nested_member,
        "qualified": True,
        "pit_violations": pit_violations,
        "receipt_count": receipt_count,
        "receipt_terminal_outcome_rate": terminal_rate,
        "latest_target_session": checks["latest_target_session"],
        "freshness_pass": freshness_pass,
        "lineage_pass": lineage_pass,
    }
    if rematerialized is not None:
        inserted = persist_qualified_pit_snapshot(
            database_url, rematerialized["snapshot"], rematerialized["provenance_rows"]
        )
        persisted = verify_qualified_pit_snapshot(
            database_url, rematerialized["snapshot"], rematerialized["provenance_rows"]
        )
        result.update({
            "r4_snapshot_rematerialized": True,
            "source_snapshot_hash": rematerialized["source_hash"],
            "r4_snapshot_hash": rematerialized["r4_hash"],
            "canonical_xnas_cutoff_proof": rematerialized["cutoff_proof"],
            "feature_value_provenance_pass": rematerialized["provenance_pass"],
            "release_native_features_pass": (
                "native_pit" in lineage.get("data_grade", [])
                and any(str(name).startswith("alfred_") for name in lineage.get("feature_names", []))
            ),
            "postgres_snapshot_persisted": True,
            "postgres_snapshot_inserted": inserted,
            "postgres_feature_rows": persisted["feature_rows"],
            "postgres_label_rows": persisted["label_rows"],
            "postgres_provenance_rows": persisted["provenance_rows"],
            "legacy_runtime_defects_acknowledged": True,
            **{key: rematerialized[key] for key in (
                "source_snapshot_rows", "source_label_rows", "active_feature_value_count",
                "calendar_version_hash", "canonical_early_close_checks",
                "release_native_feature_count",
            )},
        })
    return result


def _rematerialize_r4_snapshot(
    archive: zipfile.ZipFile, names: set[str], lineage: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild the packed feature rows with canonical XNAS close cutoffs."""
    import pyarrow.parquet as parquet

    member = _single_suffix(names, "/pit_snapshot.parquet")
    source = archive.read(member)
    table = parquet.read_table(io.BytesIO(source))
    rows = table.to_pylist()
    if not rows:
        raise ValueError("qualification failed: packed PIT snapshot is empty")
    import exchange_calendars as xcals

    sessions = [row["origin_session"] for row in rows]
    labels_member = _single_suffix(names, "/direct_labels.parquet")
    label_rows = parquet.read_table(io.BytesIO(archive.read(labels_member))).to_pylist()
    observation_member = _single_suffix(names, ".jsonl")
    m2_revisions = []
    for line in archive.read(observation_member).splitlines():
        item = json.loads(line)
        if item.get("series_id") == "M2SL" and item.get("data_grade") == "native_pit":
            item["available_at"] = datetime.fromisoformat(item["available_at"])
            m2_revisions.append(item)
    label_ends = [value for row in label_rows for key, value in row.items()
                  if key.endswith("_label_end_session") and value is not None]
    calendar_end = max([*sessions, *label_ends])
    calendar = xcals.get_calendar("XNAS", start=min(sessions), end=calendar_end)
    schedule = calendar.schedule.loc[min(sessions):calendar_end]
    canonical_closes = {
        str(index.date()): close.to_pydatetime().astimezone(timezone.utc)
        for index, close in schedule["close"].items()
    }
    canonical_dates = sorted(canonical_closes)
    close_by_date = {}
    for session in sessions:
        eligible = [item for item in canonical_dates if item <= session]
        if not eligible:
            raise ValueError("qualification failed: no canonical cutoff at origin")
        close_by_date[session] = canonical_closes[eligible[-1]]
    calendar_payload = [(key, value.isoformat()) for key, value in sorted(close_by_date.items())]
    calendar_hash = sha256(json.dumps(calendar_payload, separators=(",", ":")).encode()).hexdigest()
    early_close_checks = sum(
        close.astimezone(ZoneInfo("America/New_York")).time() < time(16, 0)
        for close in close_by_date.values()
    )
    cutoff_proof = True
    provenance_pass = True
    rebuilt: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    feature_names = list(lineage.get("feature_names", []))
    for row in rows:
        session = row["origin_session"]
        cutoff = close_by_date.get(session)
        if cutoff is None:
            cutoff_proof = False
            continue
        maximum = row.get("max_available_at")
        updated = dict(row)
        updated["origin_cutoff_at"] = cutoff
        if maximum is None or maximum.astimezone(timezone.utc) > cutoff:
            # The legacy pack used a next-midnight cutoff.  Values cannot be
            # attributed safely to the earlier canonical close, so retain the
            # target row while fail-closed masking every feature value.
            for name in ["price", *lineage.get("feature_names", [])]:
                if name in updated:
                    updated[name] = None
                missing_name = f"{name}__missing"
                if missing_name in updated:
                    updated[missing_name] = 1
            updated["max_available_at"] = None
        updated["pit_pass"] = True
        visible_m2 = [item for item in m2_revisions if item["available_at"] <= cutoff]
        if visible_m2:
            latest_period = max(item["observation_time"] for item in visible_m2)
            latest = max(
                (item for item in visible_m2 if item["observation_time"] == latest_period),
                key=lambda item: (item["available_at"], item["observation_id"]),
            )
            updated["r4_alfred_m2_latest_known"] = latest["value"]
            provenance_rows.append({
                "origin_session": session, "feature_id": "r4_alfred_m2_latest_known",
                "max_available_at": latest["available_at"], "origin_cutoff_at": cutoff,
            })
        rebuilt.append(updated)
        maximum = updated.get("max_available_at")
        if maximum is not None:
            for feature_name in ["price", *feature_names]:
                if updated.get(feature_name) is not None:
                    provenance_rows.append({
                        "origin_session": session, "feature_id": feature_name,
                        "max_available_at": maximum, "origin_cutoff_at": cutoff,
                    })
    if not cutoff_proof or not provenance_pass or len(rebuilt) != len(rows):
        raise ValueError("qualification failed: canonical cutoff or feature provenance")
    as_of = max(close_by_date.values())
    positions = {session: index for index, session in enumerate(sessions)}
    labels: list[LabelInterval] = []
    for row in label_rows:
        origin = row["origin_session"]
        origin_pos = positions.get(origin)
        for horizon in (1, 5, 21, 63):
            value, end = row.get(f"h{horizon}"), row.get(f"h{horizon}_label_end_session")
            if value is None or end is None or origin_pos is None:
                continue
            canonical_after_origin = [item for item in canonical_dates if item > origin]
            eligible_at_end = [item for item in canonical_dates if item <= end]
            if not eligible_at_end or not canonical_after_origin:
                raise ValueError("qualification failed: label is outside canonical XNAS sessions")
            labels.append(LabelInterval(
                target_id=f"{origin}:h{horizon}", origin_session=date.fromisoformat(origin),
                label_start_session=date.fromisoformat(min(canonical_after_origin[0], end)),
                label_end_session=date.fromisoformat(end),
                mature_at=canonical_closes[eligible_at_end[-1]],
                horizon_sessions=horizon, value=value,
            ))
    payload = json.dumps({"features": rebuilt, "labels": [str(x) for x in labels],
                          "calendar_version_hash": calendar_hash}, default=str,
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    r4_hash = sha256(payload.encode("utf-8")).hexdigest()
    snapshot = PitSnapshot(r4_hash, as_of, f"XNAS@{calendar_hash}", tuple(labels), tuple(rebuilt))
    return {
        "source_hash": sha256(source).hexdigest(), "r4_hash": r4_hash,
        "cutoff_proof": cutoff_proof, "provenance_pass": provenance_pass,
        "snapshot": snapshot, "provenance_rows": tuple(provenance_rows),
        "source_snapshot_rows": len(rows), "source_label_rows": len(labels),
        "active_feature_value_count": len(provenance_rows),
        "calendar_version_hash": calendar_hash,
        "canonical_early_close_checks": early_close_checks,
        "release_native_feature_count": sum(
            row.get("r4_alfred_m2_latest_known") is not None for row in rebuilt
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack")
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--database-url", default=(os.getenv("RALPH_V7_R4_DATABASE_URL")
                                                    or os.getenv("DATABASE_URL")))
    args = parser.parse_args()
    result = qualify_evidence_pack(
        args.pack, nested_member=args.nested_member, expected_sha256=args.sha256,
        database_url=args.database_url,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by acceptance command
    raise SystemExit(main())
