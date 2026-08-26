"""Fail-closed data-quality and PIT qualification for frozen evidence packs."""

from __future__ import annotations

import io
import json
import argparse
import zipfile
from pathlib import Path
from typing import Any

from .integrity import safe_zip_inventory, sha256_file


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
    return {
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack")
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = qualify_evidence_pack(
        args.pack, nested_member=args.nested_member, expected_sha256=args.sha256,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by acceptance command
    raise SystemExit(main())
