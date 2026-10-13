"""Audit a trendline release without changing any durable source database.

SQLite and WAL/SHM files are copied to a disposable directory before inspection.
Official observations and receipts are validated using existing strict models.
This audit reports legacy defects without repairing or silently normalizing them.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc import authoritative_statistics as authority
from ai_fc.ledger_audit import audit_ledgers


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_sqlite(path: Path) -> dict:
    originals = [p for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")) if p.exists()]
    before = {str(p): sha(p) for p in originals}
    with tempfile.TemporaryDirectory(prefix="trendlines-db-audit-") as directory:
        copied = Path(directory) / path.name
        for p in originals:
            shutil.copyfile(p, Path(directory) / p.name)
        with closing(sqlite3.connect(f"file:{copied.as_posix()}?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check")]
            foreign_keys = list(conn.execute("PRAGMA foreign_key_check"))
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            price = {}
            if "price_daily" in tables:
                # Exact violations are retained; small floating differences are classified.
                price_rows = list(conn.execute("SELECT series,date,open,high,low,close,source FROM price_daily"))
                invalid = [r for r in price_rows if all(v is not None for v in r[2:6]) and
                           not (r[4] <= min(r[2], r[5]) <= max(r[2], r[5]) <= r[3])]
                material = [r for r in invalid if max(r[4] - min(r[2], r[5]), max(r[2], r[5]) - r[3]) >= .01]
                price = {"rows": len(price_rows), "ohlc_exact_violations": len(invalid),
                         "ohlc_material_violations": material[:20],
                         "mixed_source_rows": sum("+" in str(r[6]) for r in price_rows)}
    after = {str(p): sha(p) for p in originals}
    if after != before:
        raise RuntimeError(f"source database changed during copy audit: {path}")
    return {"path": str(path), "integrity": integrity, "foreign_key_violations": len(foreign_keys),
            "source_bytes_unchanged": True, "tables": len(tables), "prices": price,
            "ok": integrity == ["ok"] and not foreign_keys}


def audit_official(root: Path) -> dict:
    store = root / "data/statistics/official_store"
    policy = authority.load_authoritative_source_policy(root / "data/contracts/authoritative_statistics_sources.yaml")
    receipts = authority.read_raw_artifact_receipts(store)
    receipt_index = {}
    seen_ids = set()
    validated_raw = set()
    for receipt in receipts:
        if receipt.receipt_id in seen_ids:
            raise ValueError("duplicate official receipt ID")
        seen_ids.add(receipt.receipt_id)
        rule = policy.rule_for(receipt.source_id)
        authority._assert_safe_source_uri(receipt.source_uri)
        authority._assert_source_domain(rule, receipt.source_uri)
        if not 200 <= receipt.http_status < 300:
            raise ValueError("unsuccessful official receipt")
        raw_key = (receipt.artifact_path, receipt.raw_sha256, receipt.byte_count)
        if raw_key not in validated_raw:
            authority._verify_receipt_artifact(store, receipt)
            validated_raw.add(raw_key)
        key = (receipt.source_id, receipt.raw_sha256, receipt.fetched_at)
        if key in receipt_index:
            raise ValueError("duplicate official receipt binding")
        receipt_index[key] = receipt
    observations = authority.read_normalized_observations(store)
    lineage = defaultdict(list)
    observed_ids = set()
    coverage = {}
    for obs in observations:
        if obs.observation_id in observed_ids:
            raise ValueError("duplicate normalized observation ID")
        observed_ids.add(obs.observation_id)
        policy.require_numeric_source(obs.source_id)
        receipt = receipt_index.get((obs.source_id, obs.raw_sha256, obs.fetched_at))
        if receipt is None or obs.series_id not in receipt.series_ids:
            raise ValueError("normalized observation has no matching source receipt")
        lineage[(obs.source_id, obs.series_id, obs.observation_date)].append(obs)
        if obs.series_id in ("NASDAQCOM", "SP500", "CBBTCUSD", "NASDAQSOX", "DJIA"):
            old = coverage.get(obs.series_id)
            if old is None or old["last_observation"] < obs.observation_date:
                coverage[obs.series_id] = {"last_observation": obs.observation_date, "unit": obs.unit,
                                           "source_id": obs.source_id, "ohlc_available": False}
    for revisions in lineage.values():
        revisions.sort(key=lambda row: row.revision_seq)
        if [row.revision_seq for row in revisions] != list(range(len(revisions))):
            raise ValueError("official revision sequence has a gap")
        prior = None
        for row in revisions:
            if row.supersedes_observation_id != prior:
                raise ValueError("official supersedes relationship is not linear")
            prior = row.observation_id
    return {"ok": True, "receipts": len(receipts), "unique_raw_artifacts": len(validated_raw),
            "observations": len(observations), "lineages": len(lineage), "market_coverage": coverage}


def run(root: Path, database_root: Path, baseline: str) -> dict:
    result = {"schema_version": 1, "baseline": baseline, "failures": [], "databases": []}
    for relative in ("db/index.db", "dualdb/db/dualdb.sqlite"):
        path = database_root / relative
        if path.exists():
            try:
                result["databases"].append(audit_sqlite(path))
            except (OSError, sqlite3.Error, RuntimeError) as exc:
                result["failures"].append({"category": "environment", "target": relative, "reason": str(exc)})
        else:
            result["databases"].append({"path": relative, "status": "absent_in_checkout"})
    try:
        result["official_store"] = audit_official(root)
    except (OSError, ValueError) as exc:
        result["failures"].append({"category": "data", "target": "official_store", "reason": str(exc)})
    ledgers = audit_ledgers(root, write=False)
    result["registered_ledgers"] = {"status_counts": dict(Counter(r["status"] for r in ledgers["ledgers"])),
                                     "findings": [r for r in ledgers["ledgers"] if r["status"] == "violation"]}
    protected = ["forecasts", "calibration", "questions", "data/scenarios", "data/cross_asset",
                 "data/statistics/official_store", "data/timeseries_v2", "data/timeseries_v5", "data/timeseries_v8"]
    diff = subprocess.run(["git", "diff", "--name-only", baseline, "--", *protected], cwd=root,
                          capture_output=True, text=True, check=True).stdout.splitlines()
    result["protected_changed_paths"] = diff
    if diff:
        result["failures"].append({"category": "code", "target": "protected_history", "reason": diff})
    result["ok"] = not result["failures"] and not result["registered_ledgers"]["findings"]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--database-root", type=Path, default=ROOT)
    parser.add_argument("--baseline", default="origin/main")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.root, args.database_root, args.baseline)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "official_store", "protected_changed_paths", "failures") if k in report}, ensure_ascii=True))
    raise SystemExit(0 if report["ok"] else 1)
