"""Deterministic monthly research export from the registered source ledgers."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledger_audit import _files, _load_registry, _sha

PROBABILITY_KEY = re.compile(r"(^|_)(prob|probability|chance)(_|$)", re.I)


class ResearchPackError(ValueError):
    pass


def _commit_metadata(root: Path) -> tuple[str, str]:
    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True)
        return result.stdout.strip()
    return git("rev-parse", "HEAD"), git("show", "-s", "--format=%cI", "HEAD")


def _normal(
    value: Any, key: str = "", *, path: str = "",
    normalized_fields: list[str] | None = None,
    pending_fields: set[str] | None = None,
) -> Any:
    normalized_fields = normalized_fields if normalized_fields is not None else []
    pending_fields = pending_fields or set()
    if isinstance(value, dict):
        return {
            str(k): _normal(
                v, str(k), path=f"{path}.{k}" if path else str(k),
                normalized_fields=normalized_fields, pending_fields=pending_fields,
            ) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_normal(
            item, key, path=f"{path}[{index}]", normalized_fields=normalized_fields,
            pending_fields=pending_fields,
        ) for index, item in enumerate(value)]
    if key not in pending_fields and isinstance(value, (int, float)) and not isinstance(value, bool) and PROBABILITY_KEY.search(key):
        if 1 < float(value) <= 100:
            normalized_fields.append(path)
            return round(float(value) / 100.0, 8)
        return value
    if key not in pending_fields and isinstance(value, str) and PROBABILITY_KEY.search(key):
        try:
            numeric = float(value)
            if 1 < numeric <= 100:
                normalized_fields.append(path)
                return round(numeric / 100.0, 8)
            return numeric
        except ValueError:
            return value
    if isinstance(value, str) and (key.endswith("_at") or key in {"timestamp", "run_ts", "generated_at"}):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return value
    return value


def _pending_fields(root: Path, source: Path, payload: dict[str, Any]) -> set[str]:
    if source.relative_to(root).as_posix() != "calibration/benchmark_ledger.csv":
        return set()
    identity = f"{payload.get('forecast_id', '')}@{payload.get('resolved_date', '')}"
    path = root / "calibration" / "corrections.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("field_name")) for row in csv.DictReader(handle)
            if row.get("status") == "pending"
            and row.get("target_table") == "benchmark_scores"
            and identity and str(row.get("target_key") or "").endswith(identity)
        }


def _record(source: Path, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    pending = _pending_fields(root, source, payload)
    normalized: list[str] = []
    clean = _normal(payload, normalized_fields=normalized, pending_fields=pending)
    probability_space = clean.get("probability_space", "not_applicable")
    return {
        "source_file": source.relative_to(root).as_posix(),
        "source_sha256": _sha(source),
        "probability_space": probability_space,
        "derived_from": json.dumps([source.relative_to(root).as_posix()], ensure_ascii=False),
        "normalized_fields": json.dumps(sorted(set(normalized)), ensure_ascii=False),
        "unit_review_pending": bool(pending),
        "unit_review_pending_fields": json.dumps(sorted(pending), ensure_ascii=False),
        "payload_json": json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }


def _records(path: Path, root: Path, kind: str) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [_record(path, root, row) for row in csv.DictReader(handle)]
    if suffix == ".jsonl":
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                out.append(_record(path, root, raw if isinstance(raw, dict) else {"value": raw}))
        return out
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [_record(path, root, raw if isinstance(raw, dict) else {"value": raw})]
    if suffix in {".md", ".yaml", ".yml"}:
        return [_record(path, root, {"text": path.read_text(encoding="utf-8")})]
    return [_record(path, root, {"bytes": path.stat().st_size, "kind": kind})]


def _source_manifest(root: Path, registry: list[dict[str, Any]]) -> dict[str, str]:
    return dict(sorted(
        (path.relative_to(root).as_posix(), _sha(path))
        for row in registry if row["id"] != "research_pack"
        for path in _files(root, row)
    ))


def export_research_pack(root: Path, month: str | None = None) -> Path:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ResearchPackError("pyarrow is required; install the pit extra") from exc

    selected_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", selected_month):
        raise ResearchPackError("month must use YYYY-MM")
    registry = _load_registry(root)
    source_files = _source_manifest(root, registry)
    source_manifest_sha = hashlib.sha256(
        json.dumps(source_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    target = root / "exports" / f"research_pack_{selected_month}"
    existing = target / "manifest.json"
    if existing.exists():
        prior = json.loads(existing.read_text(encoding="utf-8"))
        if prior.get("source_manifest_sha256") == source_manifest_sha:
            return target
        revision = 2
        while (root / "exports" / f"research_pack_{selected_month}-r{revision}").exists():
            revision += 1
        target = root / "exports" / f"research_pack_{selected_month}-r{revision}"
        existing = target / "manifest.json"
    target.mkdir(parents=True, exist_ok=False)

    tables: list[dict[str, Any]] = []
    for row in registry:
        if row["id"] == "research_pack":
            continue
        records = [record for path in _files(root, row) for record in _records(path, root, row["kind"])]
        if not records:
            continue
        table = pa.Table.from_pylist(records)
        filename = f"{row['id']}.parquet"
        pq.write_table(table, target / filename, compression="zstd")
        tables.append({
            "ledger_id": row["id"], "file": filename, "rows": len(records),
            "sha256": _sha(target / filename), "probability_space_column": True,
            "derived_from_column": True,
        })

    commit, commit_time = _commit_metadata(root)
    manifest = {
        "schema_version": 1, "month": selected_month, "generated_from_commit": commit,
        "generated_at": commit_time, "source_manifest_sha256": source_manifest_sha,
        "source_files": source_files, "tables": tables,
        "normalization": {
            "probabilities": "fraction where a probability-like numeric field was in (1,100]",
            "excluded_probability_names": "generic weight fields are never treated as probabilities",
            "pending_units": "pending correction fields retain source values and are marked unit_review_pending",
            "timestamps": "timezone-bearing *_at/timestamp/run_ts/generated_at values normalized to UTC ISO-8601",
            "provenance": "every row contains source_file, source_sha256 and derived_from",
        },
    }
    (target / "DICTIONARY.md").write_text(
        "# Research pack data dictionary\n\n"
        "Each registered ledger is exported to its own Zstandard-compressed Parquet table. "
        "A normalized representation of each source row is retained as `payload_json`; `source_file` and "
        "`source_sha256` identify the immutable input. `probability_space` prevents physical-event, "
        "risk-neutral and scenario-conditional probabilities from being silently mixed. "
        "`derived_from` is a JSON array of source paths. Dates without a time remain civil dates; "
        "timestamps are converted to UTC ISO-8601. `normalized_fields` lists changed field paths; "
        "`unit_review_pending` keeps unresolved source units unchanged. Generic `weight` fields are not "
        "probabilities. Missing planned ledgers are intentionally absent.\n",
        encoding="utf-8",
    )
    existing.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    manifest["pack_bytes"] = size
    manifest["distribution"] = "github_release" if size > 50 * 1024 * 1024 else "repository"
    existing.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
