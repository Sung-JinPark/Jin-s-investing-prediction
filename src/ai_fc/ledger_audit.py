"""Registered-ledger freshness, continuity and immutability audit."""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from .market_session import completed_market_cutoff
from .scenario import future_trading_days, load_calendar_contract, validate_scenario

REGISTRY = Path("data/contracts/ledger_registry.yaml")
MANIFEST = Path("docs/generated/ledger_manifest.json")
AUDIT_JSON = Path("docs/generated/ledger_audit.json")
AUDIT_MD = Path("docs/generated/ledger_audit.md")
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


class LedgerAuditError(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_registry(root: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load((root / REGISTRY).read_text(encoding="utf-8"))
    rows = raw.get("ledgers") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise LedgerAuditError("ledger registry must contain a non-empty ledgers list")
    required = {"id", "path", "kind", "cadence", "criticality", "schema_ref"}
    ids: set[str] = set()
    for row in rows:
        missing = required - set(row or {})
        if missing:
            raise LedgerAuditError(f"ledger registry entry missing {sorted(missing)}")
        if row["id"] in ids:
            raise LedgerAuditError(f"duplicate ledger id: {row['id']}")
        ids.add(row["id"])
    return rows


def _files(root: Path, row: dict[str, Any]) -> list[Path]:
    found = sorted(path for path in root.glob(row["path"]) if path.is_file())
    excludes = row.get("exclude") or []
    return [path for path in found if not any(
        fnmatch.fnmatch(path.relative_to(root).as_posix(), pattern) for pattern in excludes)]


def _dates(paths: list[Path], timestamp_field: str | None = None) -> list[date]:
    out: set[date] = set()
    for path in paths:
        match = DATE_RE.search(path.name)
        if match:
            try:
                out.add(date.fromisoformat(match.group(1)))
            except ValueError:
                pass
        if path.suffix.lower() == ".json":
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                # 등록된 timestamp_field는 하드코딩 키가 없을 때만 쓴다.
                # 덮어쓰면 asof(데이터 기준일) 대신 generated_at(생성 시각) 같은
                # 값을 읽어 신선도를 과대평가하게 된다.
                value = None
                if isinstance(raw, dict):
                    value = raw.get("asof")
                    if not value and timestamp_field:
                        value = raw.get(timestamp_field)
                if value:
                    out.add(date.fromisoformat(str(value)[:10]))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        elif path.suffix.lower() == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    raw = json.loads(line)
                    value = (raw.get("run_ts") or raw.get("asof")
                             or raw.get("timestamp")
                             or (raw.get(timestamp_field) if timestamp_field else None))
                    if value:
                        out.add(date.fromisoformat(str(value)[:10]))
                except (ValueError, json.JSONDecodeError, AttributeError):
                    pass
        elif path.suffix.lower() == ".csv" and timestamp_field:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for record in csv.DictReader(handle):
                    value = record.get(timestamp_field)
                    if value:
                        try:
                            out.add(date.fromisoformat(str(value)[:10]))
                        except ValueError:
                            pass
        elif path.suffix.lower() in {".sqlite", ".db"} and timestamp_field:
            parts = timestamp_field.split(".")
            if (len(parts) == 2
                    and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part)
                            for part in parts)):
                table, column = parts
                try:
                    uri = f"file:{path.resolve().as_posix()}?mode=ro"
                    with sqlite3.connect(uri, uri=True) as conn:
                        values = conn.execute(
                            f'SELECT DISTINCT "{column}" FROM "{table}" '
                            f'WHERE "{column}" IS NOT NULL').fetchall()
                    for (value,) in values:
                        try:
                            out.add(date.fromisoformat(str(value)[:10]))
                        except ValueError:
                            pass
                except sqlite3.Error:
                    pass
        elif path.suffix.lower() == ".ots":
            out.add(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date())
    return sorted(out)


def _last_market_day(root: Path, today: date) -> date:
    cutoff = completed_market_cutoff(today)
    calendar = load_calendar_contract(root)
    start = cutoff - timedelta(days=40)
    valid = [d for d in future_trading_days(start, 40, calendar) if d <= cutoff]
    return valid[-1] if valid else cutoff


def _trading_gaps(root: Path, days: list[date]) -> list[str]:
    if len(days) < 2:
        return []
    expected = future_trading_days(days[0], 370, load_calendar_contract(root))
    wanted = [d for d in expected if d <= days[-1]]
    actual = set(days)
    return [d.isoformat() for d in wanted if d not in actual]


def _schema_errors(path: Path, schema_ref: str) -> list[str]:
    if schema_ref == "binary":
        return [] if path.stat().st_size else ["empty binary"]
    if schema_ref == "markdown":
        return [] if path.read_text(encoding="utf-8").strip() else ["empty markdown"]
    if schema_ref == "forecast_frontmatter":
        try:
            post = frontmatter.load(path)
            return [] if post.get("forecast_id") and post.get("question_id") else ["missing forecast_id/question_id"]
        except Exception as exc:  # parser supplies the useful class in output
            return [f"frontmatter: {type(exc).__name__}"]
    if schema_ref == "csv":
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                return [] if reader.fieldnames else ["missing CSV header"]
        except (OSError, csv.Error) as exc:
            return [f"csv: {type(exc).__name__}"]
    if schema_ref == "json_object":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [] if isinstance(raw, dict) else ["JSON root is not an object"]
        except (OSError, json.JSONDecodeError) as exc:
            return [f"json: {type(exc).__name__}"]
    if schema_ref == "dualdb_model_run":
        required = {"run_id", "model", "asof", "params_json", "output_json", "created_at"}
        try:
            uri = f"file:{path.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(model_run)")}
                count = int(conn.execute("SELECT COUNT(*) FROM model_run").fetchone()[0])
            missing = sorted(required - columns)
            if missing:
                return [f"model_run missing columns: {missing}"]
            return [] if count else ["model_run is empty"]
        except sqlite3.Error as exc:
            return [f"sqlite: {type(exc).__name__}"]
    if schema_ref in {"scenario_archive", "scenario_latest"}:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if int(raw.get("schema_version", 1)) >= 2:
                validate_scenario(raw)
            elif not raw.get("asof") or not raw.get("paths"):
                return ["legacy scenario missing asof/paths"]
            return []
        except Exception as exc:
            return [f"scenario: {type(exc).__name__}: {exc}"]
    if schema_ref in {"cross_asset_archive", "cross_asset_latest"}:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            required = {"asof", "forecast"}
            return [] if isinstance(raw, dict) and required <= set(raw) else ["cross-asset missing asof/scenarios"]
        except (OSError, json.JSONDecodeError) as exc:
            return [f"cross-asset: {type(exc).__name__}"]
    if schema_ref == "jsonl":
        errors = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                if not isinstance(json.loads(line), dict):
                    errors.append(f"line {line_no} is not an object")
            except json.JSONDecodeError:
                errors.append(f"line {line_no} invalid JSON")
        return errors[:10]
    return []


def _csv_health(paths: list[Path], timestamp_field: str | None) -> dict[str, Any]:
    duplicates = 0
    reversed_rows = 0
    row_count = 0
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        row_count += len(rows)
        keys = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
        duplicates += sum(n - 1 for n in Counter(keys).values() if n > 1)
        if timestamp_field:
            values = [row.get(timestamp_field, "") for row in rows]
            reversed_rows += sum(a > b for a, b in zip(values, values[1:]) if a and b)
    return {"rows": row_count, "duplicate_rows": duplicates, "reversed_timestamps": reversed_rows}


def audit_ledgers(root: Path, *, write: bool = True, now: datetime | None = None) -> dict[str, Any]:
    stamp = now or datetime.now(timezone.utc)
    today = stamp.date()
    registered = _load_registry(root)
    previous = {}
    manifest_path = root / MANIFEST
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", {})
    all_hashes: dict[str, str] = dict(previous)
    results: list[dict[str, Any]] = []
    last_market = _last_market_day(root, today)

    for row in registered:
        paths = _files(root, row)
        days = _dates(paths, row.get("timestamp_field"))
        immutable_changes: list[str] = []
        schema_errors: list[str] = []
        for path in paths:
            rel = path.relative_to(root).as_posix()
            digest = _sha(path)
            immutable_kind = row["kind"] in {"archive_dir", "immutable_files"}
            if row.get("expected_state") == "frozen":
                immutable_kind = True
            if immutable_kind and rel in previous and previous[rel] != digest:
                immutable_changes.append(rel)
            else:
                all_hashes[rel] = digest
            for error in _schema_errors(path, row["schema_ref"]):
                schema_errors.append(f"{rel}: {error}")
        gaps = _trading_gaps(root, days) if row["cadence"] == "trading_daily" and row["kind"] == "archive_dir" else []
        csv_health = _csv_health(paths, row.get("timestamp_field")) if row["kind"] == "append_csv" else {"rows": None, "duplicate_rows": 0, "reversed_timestamps": 0}
        latest = days[-1] if days else None
        expected = row.get("expected_state")
        stale = False
        if latest and expected != "frozen":
            if row["cadence"] == "trading_daily":
                stale = latest < last_market
            elif row["cadence"] == "weekly":
                stale = (today - latest).days > 10
            elif row["cadence"] == "biweekly":
                # 14일 주기 + 한 번 놓쳐도 되는 여유. weekly의 10일과 같은 비율.
                stale = (today - latest).days > 17
            elif row["cadence"] == "monthly":
                stale = (today - latest).days > 40
        elif (row["cadence"] not in {"event", "manual"}
              and expected not in {"planned", "frozen"}
              and not row.get("allow_empty_accumulating")):
            stale = True
        violations = immutable_changes + schema_errors
        if csv_health["duplicate_rows"]:
            violations.append(f"{csv_health['duplicate_rows']} duplicate CSV row(s)")
        if csv_health["reversed_timestamps"]:
            violations.append(f"{csv_health['reversed_timestamps']} reversed CSV timestamp(s)")
        if violations:
            status = "violation"
        elif expected == "planned" and (not paths or csv_health["rows"] == 0):
            status = "planned"
        elif paths and expected == "frozen":
            status = "frozen"
        elif not paths:
            status = "inactive"
        elif stale or gaps:
            status = "stalled"
        else:
            status = "accumulating"
        results.append({
            "id": row["id"], "path": row["path"], "kind": row["kind"],
            "cadence": row["cadence"], "criticality": row["criticality"],
            "status": status, "file_count": len(paths), "row_count": csv_health["rows"],
            "latest_date": latest.isoformat() if latest else None,
            "missing_trading_days": gaps, "immutable_changes": immutable_changes,
            "schema_errors": schema_errors, "duplicate_rows": csv_health["duplicate_rows"],
            "reversed_timestamps": csv_health["reversed_timestamps"],
            "growth_last_30d": [
                {"date": day.isoformat(), "count": index + 1}
                for index, day in enumerate(days) if day >= today - timedelta(days=30)
            ],
        })

    counts = Counter(item["status"] for item in results)
    report = {
        "schema_version": 1,
        "generated_at": stamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "market_cutoff": last_market.isoformat(),
        "summary": {key: counts.get(key, 0) for key in ("accumulating", "stalled", "inactive", "violation", "planned", "frozen")},
        "ledgers": results,
    }
    if write:
        (root / AUDIT_JSON).parent.mkdir(parents=True, exist_ok=True)
        (root / AUDIT_JSON).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest = {"schema_version": 1, "baseline_at": report["generated_at"], "files": dict(sorted(all_hashes.items()))}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (root / AUDIT_MD).write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Ledger accumulation audit", "",
        f"- Generated: `{report['generated_at']}`",
        f"- Latest completed NYSE day: `{report['market_cutoff']}`",
        f"- Result: accumulating {summary['accumulating']} · frozen {summary['frozen']} · stalled {summary['stalled']} · inactive {summary['inactive']} · violation {summary['violation']} · planned {summary['planned']}", "",
        "| Ledger | Cadence | Files / rows | Latest | Status | Finding |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in report["ledgers"]:
        findings = []
        if item["missing_trading_days"]:
            findings.append("missing trading days: " + ", ".join(item["missing_trading_days"]))
        if item["immutable_changes"]:
            findings.append("immutable file changed")
        if item["schema_errors"]:
            findings.append(f"schema errors: {len(item['schema_errors'])}")
        if item["duplicate_rows"]:
            findings.append(f"duplicate rows: {item['duplicate_rows']}")
        count = str(item["file_count"])
        if item["row_count"] is not None:
            count += f" / {item['row_count']}"
        lines.append(f"| `{item['id']}` | {item['cadence']} | {count} | {item['latest_date'] or '—'} | **{item['status']}** | {'; '.join(findings) or '—'} |")
    lines += ["", "## Interpretation", "", "`frozen` is a deliberately retired ledger whose bytes remain immutable. `stalled` is an operational warning, not an immutable-record violation. `planned` means the layer is registered before first ingestion. Existing file hash changes and schema failures are `violation` and fail the check gate.", ""]
    return "\n".join(lines)


def has_violations(report: dict[str, Any]) -> bool:
    return report["summary"]["violation"] > 0
