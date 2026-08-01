"""파일 → SQLite 멱등 동기화 + 드리프트 경보.

드리프트는 갱신이 아니라 '경보'다:
  E1 예측 파일 해시 변경     → 불변성 위반 (오류)
  E2 DB에만 있는 예측        → 파일 삭제됨 (오류)
  E3 원장 축소·과거 행 변조   → append-only 위반 (오류)
  W1 예측 있는 질문의 판정기준 변경 → 경고 (판정기준 불변 규칙)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time
from pathlib import Path

from .. import files as F
from ..integrity import RepositoryContext, repository_context
from ..models import sha256_file
from ..probability import ProbabilityRecord, ProbabilitySpace, ProbabilityUnit
from ..registry import load_registry


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # 기존 DB 마이그레이션 가드 (CREATE IF NOT EXISTS는 컬럼 추가를 못 하므로)
    for ddl in ("ALTER TABLE forecasts ADD COLUMN research_status TEXT",
                "ALTER TABLE research_status_override ADD COLUMN created_at TEXT",
                "ALTER TABLE forecasts ADD COLUMN shadow_extremized INTEGER",
                "ALTER TABLE forecasts ADD COLUMN ml_divergence_pp REAL",
                "ALTER TABLE forecasts ADD COLUMN divergence_class TEXT",
                "ALTER TABLE forecasts ADD COLUMN pipeline_tier TEXT",
                "ALTER TABLE cost_log ADD COLUMN provider TEXT NOT NULL DEFAULT 'anthropic'",
                "ALTER TABLE cost_log ADD COLUMN snapshot TEXT",
                "ALTER TABLE cost_log ADD COLUMN request_id TEXT",
                "ALTER TABLE cost_log ADD COLUMN cached_input_tokens INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE cost_log ADD COLUMN web_search_calls INTEGER NOT NULL DEFAULT 0"):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # 신규 DB(스키마에 포함) 또는 이미 추가됨 또는 테이블 미존재
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version,name,checksum,applied_at) "
        "VALUES (2,'quant-intelligence-additive-v2','schema.sql:v2',datetime('now'))"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class DriftReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [f"[오류] {e}" for e in self.errors] + [f"[경고] {w}" for w in self.warnings]
        return "\n".join(lines) if lines else "드리프트 없음"


def sync(conn: sqlite3.Connection, root: Path, rebuild: bool = False,
         force: bool = False, *, strict: bool = False) -> DriftReport:
    """파일 → DB. 멱등: 해시 동일 파일은 건너뜀. rebuild=True면 전체 재구축.

    AUDIT-260715 Q15: rebuild는 sync_meta(해시 기준선)를 지우므로, 지우기 **전에**
    현 파일과 기존 기준선을 대조한다. E1(예측 파일 변조)이 검출되면 force 없이는
    중단 — 침묵 재기준화로 불변성 위반이 세탁되는 것을 차단.
    """
    report = DriftReport()
    now = datetime.now().isoformat(timespec="seconds")
    context = repository_context(root)
    stored = _stored_repository_context(conn)
    if stored and (
        stored.repo_id != context.repo_id
        or stored.branch != context.branch
        or (stored.head and context.head and stored.head != context.head)
    ):
        rebuild = True
        force = True
        report.warnings.append(
            "W8 repository context changed; rebuilding the SQLite read index from source files"
        )

    if rebuild:
        pre = _precheck_forecast_hashes(conn, root)
        if pre and not force:
            report.errors.extend(pre)
            report.errors.append(
                "rebuild 중단: 위 불변성 위반이 재기준화로 세탁됩니다 — "
                "원인 규명 후 정말 재기준화하려면 --force")
            return report
        report.warnings.extend(f"[force 재기준화] {issue}" for issue in pre)
        staged = _memory_connection()
        staged_report = DriftReport()
        _sync_all(staged, root, staged_report, now)
        report.errors.extend(staged_report.errors)
        report.warnings.extend(staged_report.warnings)
        if report.errors:
            staged.close()
            return report
        _record_repository_context(staged, context, now)
        staged.commit()
        staged.backup(conn)
        staged.close()
        conn.commit()
        _write_hash_anchor(conn, root)
        return report

    conn.execute("SAVEPOINT ai_fc_sync")
    _sync_all(conn, root, report, now)
    if report.errors:
        if strict:
            conn.execute("ROLLBACK TO ai_fc_sync")
        conn.execute("RELEASE ai_fc_sync")
        if not strict:
            conn.commit()
            _write_hash_anchor(conn, root)
        return report
    _record_repository_context(conn, context, now)
    conn.execute("RELEASE ai_fc_sync")
    conn.commit()
    _write_hash_anchor(conn, root)
    return report


def _memory_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def check(root: Path) -> tuple[DriftReport, dict[str, int]]:
    """Validate all source inputs in an isolated database without touching the index."""
    conn = _memory_connection()
    report = DriftReport()
    _sync_all(conn, root, report, datetime.now().isoformat(timespec="seconds"))
    counts = {
        "questions": int(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]),
        "forecasts": int(conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]),
        "resolutions": int(conn.execute("SELECT COUNT(*) FROM resolutions").fetchone()[0]),
    }
    conn.close()
    return report, counts


def _sync_all(conn: sqlite3.Connection, root: Path, report: DriftReport, now: str) -> None:
    _sync_questions(conn, root, report)
    _sync_forecasts(conn, root, report, now)
    _sync_ledger(conn, root, report)
    _sync_benchmark(conn, root, report)
    _sync_ml_history(conn, root, report, now)
    _sync_status_overrides(conn, root, report)
    _sync_corrections(conn, root, report)
    _sync_source_registry(conn, root, report, now)
    _rebuild_probability_records(conn, report, now)
    _rebuild_resolution_events(conn, report)
    _rebuild_lineage_edges(conn, root, now)
    from ..model_registry import register_defaults
    register_defaults(conn, root)


def _rebuild_lineage_edges(conn: sqlite3.Connection, root: Path, now: str) -> None:
    """Rebuild deterministic read-index lineage; no source ledger is modified."""
    context = repository_context(root)
    conn.execute("DELETE FROM lineage_edge")
    edges = (
        ("lineage:forecast-read-model", "dataset", "forecasts/", "surface", "dashboard", "builds"),
        ("lineage:scenario-read-model", "dataset", "data/scenarios/archive", "surface", "scenario", "builds"),
        ("lineage:context-era", "dataset", "data/ml_history", "surface", "era_analog", "normalizes"),
        ("lineage:provider-shadow-arena", "ledger", "calibration/provider_shadow_ledger.csv", "surface", "arena", "benchmarks"),
    )
    conn.executemany(
        """INSERT INTO lineage_edge
           (edge_id,upstream_type,upstream_id,downstream_type,downstream_id,
            relation,commit_sha,created_at) VALUES (?,?,?,?,?,?,?,?)""",
        [(*edge, context.head or "working-tree", now) for edge in edges],
    )


def _stored_repository_context(conn: sqlite3.Connection) -> RepositoryContext | None:
    values = {row["key"]: row["value"] for row in conn.execute(
        "SELECT key, value FROM db_meta WHERE key IN "
        "('repo_id','branch','head','source_fingerprint')"
    )}
    if "repo_id" not in values:
        return None
    return RepositoryContext(
        repo_id=values["repo_id"],
        branch=values.get("branch", "detached-or-unversioned"),
        head=values.get("head", ""),
        source_fingerprint=values.get("source_fingerprint", ""),
    )


def _record_repository_context(
    conn: sqlite3.Connection, context: RepositoryContext, now: str
) -> None:
    for key, value in (
        ("schema_version", "2"),
        ("repo_id", context.repo_id),
        ("branch", context.branch),
        ("head", context.head),
        ("source_fingerprint", context.source_fingerprint),
    ):
        conn.execute(
            "INSERT INTO db_meta(key,value,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )


def _sync_corrections(conn: sqlite3.Connection, root: Path, report: DriftReport) -> None:
    import csv
    import hashlib

    path = root / "calibration" / "corrections.csv"
    if not path.exists():
        return
    raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data_lines = raw_lines[1:]
    known = {row["line_no"]: row["line_hash"] for row in conn.execute(
        "SELECT line_no,line_hash FROM correction_lines")}
    if known and len(data_lines) < len(known):
        report.errors.append(
            f"E9 correction ledger shrank: DB {len(known)} rows > file {len(data_lines)} rows"
        )
    for line_no, line in enumerate(data_lines, start=1):
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        if line_no in known and known[line_no] != digest:
            report.errors.append(f"E9 correction ledger row {line_no} was modified")
        conn.execute(
            "INSERT OR REPLACE INTO correction_lines(line_no,line_hash) VALUES (?,?)",
            (line_no, digest),
        )
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            required = ("correction_id", "target_table", "target_key", "field_name",
                        "status", "reason", "created_at")
            if any(not row.get(field) for field in required):
                report.errors.append(f"E9 invalid correction row: {row!r}")
                continue
            conn.execute(
                """INSERT OR IGNORE INTO correction_ledger
                   (correction_id,target_table,target_key,field_name,old_value,new_value,
                    status,reason,evidence_uri,created_at,approved_at,reviewer)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(row.get(field) or None for field in (
                    "correction_id", "target_table", "target_key", "field_name",
                    "old_value", "new_value", "status", "reason", "evidence_uri",
                    "created_at", "approved_at", "reviewer")),
            )


def _sync_source_registry(
    conn: sqlite3.Connection, root: Path, report: DriftReport, now: str
) -> None:
    import yaml

    path = root / "data" / "source_registry.yaml"
    if not path.exists():
        return
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        report.errors.append(f"E10 source registry parse failed: {exc}")
        return
    conn.execute("DELETE FROM source_registry")
    required = (
        "id", "name", "provider", "tier", "cadence", "vintage_capability",
        "license_status", "contract",
    )
    for source in payload.get("sources", []):
        if any(source.get(field) in (None, "") for field in required):
            report.errors.append(f"E10 incomplete source registry entry: {source!r}")
            continue
        contract = root / str(source["contract"])
        if not contract.exists():
            report.errors.append(f"E10 missing data contract: {source['contract']}")
            continue
        conn.execute(
            """INSERT INTO source_registry
               (source_id,name,provider,source_tier,endpoint,cadence,freshness_sla_hours,
                vintage_capability,license_status,enabled,contract_path,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source["id"], source["name"], source["provider"], source["tier"],
             source.get("endpoint"), source["cadence"], source.get("freshness_sla_hours"),
             source["vintage_capability"], source["license_status"],
             1 if source.get("enabled", True) else 0, source["contract"], now),
        )


def _record_id(*parts: object) -> str:
    import hashlib

    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:32]


def _put_probability(
    conn: sqlite3.Connection,
    report: DriftReport,
    *,
    entity_type: str,
    entity_id: str,
    value: float | int | None,
    source_unit: ProbabilityUnit,
    probability_space: ProbabilitySpace,
    source_id: str,
    asof: str | None,
    now: str,
) -> None:
    if value is None:
        return
    try:
        record = ProbabilityRecord.from_raw(
            value,
            source_unit=source_unit,
            probability_space=probability_space,
            source_id=source_id,
            asof=asof,
        )
    except (TypeError, ValueError) as exc:
        report.warnings.append(
            f"Q1 quarantined probability {entity_type}/{entity_id}: {exc}"
        )
        return
    conn.execute(
        """INSERT INTO probability_record
           (record_id,entity_type,entity_id,probability,raw_value,source_unit,
            probability_space,source_id,asof,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (_record_id(entity_type, entity_id, probability_space.value, source_id),
         entity_type, entity_id, record.probability, record.raw_value,
         record.source_unit.value, record.probability_space.value,
         record.source_id, record.asof, now),
    )


def _rebuild_probability_records(
    conn: sqlite3.Connection, report: DriftReport, now: str
) -> None:
    conn.execute("DELETE FROM probability_record")
    for row in conn.execute("SELECT forecast_id,probability,forecast_ts FROM forecasts"):
        _put_probability(
            conn, report, entity_type="forecast", entity_id=row["forecast_id"],
            value=row["probability"], source_unit=ProbabilityUnit.PERCENT,
            probability_space=ProbabilitySpace.PHYSICAL_EVENT, source_id="forecast:file",
            asof=row["forecast_ts"], now=now)
    for row in conn.execute(
        "SELECT forecast_id,resolved_date,probability FROM resolutions"
    ):
        _put_probability(
            conn, report, entity_type="resolution", entity_id=f"{row['forecast_id']}@{row['resolved_date']}",
            value=row["probability"], source_unit=ProbabilityUnit.PERCENT,
            probability_space=ProbabilitySpace.PHYSICAL_EVENT, source_id="calibration:ledger",
            asof=row["resolved_date"], now=now)
    for row in conn.execute(
        "SELECT run_ts,question_id,model,kind,prob FROM ml_forecasts"
    ):
        space = (ProbabilitySpace.PATH_TOUCH if row["kind"] == "path_touch"
                 else ProbabilitySpace.PHYSICAL_EVENT)
        _put_probability(
            conn, report, entity_type="ml_forecast",
            entity_id=f"{row['run_ts']}|{row['question_id']}|{row['model']}|{row['kind']}",
            value=row["prob"], source_unit=ProbabilityUnit.FRACTION,
            probability_space=space, source_id=f"ml:{row['model']}",
            asof=row["run_ts"], now=now)
    for row in conn.execute(
        "SELECT run_ts,question_id,source,prob FROM market_implied"
    ):
        _put_probability(
            conn, report, entity_type="market_implied",
            entity_id=f"{row['run_ts']}|{row['question_id']}|{row['source']}",
            value=row["prob"], source_unit=ProbabilityUnit.FRACTION,
            probability_space=ProbabilitySpace.REFERENCE_ONLY,
            source_id=f"market:{row['source']}", asof=row["run_ts"], now=now)
    for row in conn.execute("SELECT * FROM benchmark_scores"):
        entity_id = f"{row['forecast_id']}@{row['resolved_date']}"
        for prefix in ("llm", "ml", "market"):
            _put_probability(
                conn, report, entity_type="benchmark", entity_id=f"{entity_id}|{prefix}",
                value=row[f"{prefix}_prob"], source_unit=ProbabilityUnit.FRACTION,
                probability_space=(ProbabilitySpace.REFERENCE_ONLY if prefix == "market"
                                   else ProbabilitySpace.PHYSICAL_EVENT),
                source_id=f"benchmark:{prefix}", asof=row["resolved_date"], now=now)


def _parse_event_time(value: str | None, fallback: date) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(value[:10]), time.min)
            except ValueError:
                pass
    return datetime.combine(fallback, time.min)


def _weighted_probability(rows: list[dict], resolved: date) -> float | None:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda row: (row["ts"], row["round"] or 0, row["forecast_id"]))
    resolution_end = datetime.combine(resolved, time.max)
    weights: list[float] = []
    for idx, row in enumerate(ordered):
        end = ordered[idx + 1]["ts"] if idx + 1 < len(ordered) else resolution_end
        weights.append(max(1.0, (end - row["ts"]).total_seconds()))
    total = sum(weights)
    return sum(row["probability"] * weight for row, weight in zip(ordered, weights)) / total


def _rebuild_resolution_events(conn: sqlite3.Connection, report: DriftReport) -> None:
    conn.execute("DELETE FROM score_observation")
    conn.execute("DELETE FROM resolution_event")
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in conn.execute(
        """SELECT r.*, f.round, f.forecast_ts,
                  COALESCE(o.status, f.research_status, 'ok') AS effective_status
           FROM resolutions r
           LEFT JOIN forecasts f ON f.forecast_id=r.forecast_id
           LEFT JOIN research_status_override o ON o.forecast_id=r.forecast_id
           ORDER BY r.question_id,r.resolved_date,f.round,r.forecast_id"""
    ):
        key = (row["question_id"], row["resolved_date"])
        resolved = date.fromisoformat(row["resolved_date"])
        grouped.setdefault(key, []).append({
            "forecast_id": row["forecast_id"],
            "round": row["round"],
            "ts": _parse_event_time(row["forecast_ts"] or row["forecast_date"], resolved),
            "probability": float(row["probability"]) / 100.0,
            "outcome": int(row["outcome"]),
            "domain": row["domain"],
            "eligible": row["effective_status"] != "failed",
        })

    for (question_id, resolved_text), rows in grouped.items():
        outcomes = {row["outcome"] for row in rows}
        if len(outcomes) != 1:
            report.errors.append(
                f"E8 inconsistent outcomes for {question_id}@{resolved_text}: {sorted(outcomes)}"
            )
            continue
        outcome = outcomes.pop()
        resolved = date.fromisoformat(resolved_text)
        ordered = sorted(rows, key=lambda row: (row["ts"], row["round"] or 0))
        representative = _weighted_probability(ordered, resolved)
        primary_rows = [row for row in ordered if row["eligible"]]
        primary_probability = _weighted_probability(primary_rows, resolved)
        event_id = _record_id("resolution_event", question_id, resolved_text)
        conn.execute(
            """INSERT INTO resolution_event
               (event_id,question_id,resolved_date,outcome,domain,forecast_count,
                first_probability,latest_probability,representative_probability,
                representative_brier,primary_forecast_count,primary_probability,primary_brier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, question_id, resolved_text, outcome, ordered[0]["domain"], len(ordered),
             ordered[0]["probability"], ordered[-1]["probability"], representative,
             (representative - outcome) ** 2 if representative is not None else None,
             len(primary_rows), primary_probability,
             (primary_probability - outcome) ** 2 if primary_probability is not None else None),
        )
        resolution_end = datetime.combine(resolved, time.max)
        for idx, row in enumerate(ordered):
            end = ordered[idx + 1]["ts"] if idx + 1 < len(ordered) else resolution_end
            weight = max(1.0, (end - row["ts"]).total_seconds())
            conn.execute(
                """INSERT INTO score_observation
                   (event_id,forecast_id,forecast_ts,round,probability,outcome,brier,
                    time_weight,eligible_primary) VALUES (?,?,?,?,?,?,?,?,?)""",
                (event_id, row["forecast_id"], row["ts"].isoformat(timespec="seconds"),
                 row["round"], row["probability"], outcome,
                 (row["probability"] - outcome) ** 2, weight, 1 if row["eligible"] else 0),
            )


def _sync_benchmark(conn: sqlite3.Connection, root: Path, report: DriftReport) -> None:
    """calibration/benchmark_ledger.csv → benchmark_scores (WS2, append-only 규율 E7)."""
    path = root / "calibration" / "benchmark_ledger.csv"
    rows = F.parse_benchmark_ledger(path)

    known = {r["line_no"]: r["line_hash"]
             for r in conn.execute("SELECT * FROM benchmark_lines")}
    if known and len(rows) < len(known):
        report.errors.append(
            f"E7 벤치마크 원장 축소: DB {len(known)}행 > 파일 {len(rows)}행 — append-only 위반")
    for row in rows:
        if row["line_no"] in known and known[row["line_no"]] != row["line_hash"]:
            report.errors.append(f"E7 벤치마크 원장 {row['line_no']}행 변조 — append-only 위반")
        conn.execute(
            """INSERT OR REPLACE INTO benchmark_scores (forecast_id, resolved_date,
                 question_id, llm_prob, llm_brier, ml_prob, ml_brier, market_prob,
                 market_brier, ml_asof, market_asof, notes, line_no)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["forecast_id"], row["resolved_date"], row["question_id"],
             row["llm_prob"], row["llm_brier"], row["ml_prob"], row["ml_brier"],
             row["market_prob"], row["market_brier"], row["ml_asof"] or None,
             row["market_asof"] or None, row["notes"], row["line_no"]))
        conn.execute(
            "INSERT OR REPLACE INTO benchmark_lines (line_no, line_hash) VALUES (?,?)",
            (row["line_no"], row["line_hash"]))


def _sync_status_overrides(conn: sqlite3.Connection, root: Path,
                           report: DriftReport) -> None:
    """calibration/research_status_overrides.csv → 메타 테이블 (8-2(c) + RE-AUDIT U-2).

    대표 Brier·게이트를 좌우하는 레버이므로 **원장급 규율**을 적용한다:
      E5 — append-only 위반 (행 축소·과거 행 변조, 행별 해시 대조)
      E4 — 시점 불변식 위반: override.created_at ≥ 해당 예측의 해소일
           (결과를 보고 나서 소급 제외하는 게이밍 차단)
    """
    import csv
    import hashlib

    path = root / "calibration" / "research_status_overrides.csv"
    if not path.exists():
        return

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    data_lines = lines[1:]  # 헤더 제외

    # E5: 행 해시 규율 (ledger_lines 패턴)
    known = {r["line_no"]: r["line_hash"]
             for r in conn.execute("SELECT * FROM override_lines")}
    if known and len(data_lines) < len(known):
        report.errors.append(
            f"E5 overrides 축소: DB {len(known)}행 > 파일 {len(data_lines)}행 — append-only 위반")
    for i, ln in enumerate(data_lines, start=1):
        h = hashlib.sha256(ln.encode("utf-8")).hexdigest()
        if i in known and known[i] != h:
            report.errors.append(f"E5 overrides {i}행 변조 — append-only 위반")
        conn.execute(
            "INSERT OR REPLACE INTO override_lines (line_no, line_hash) VALUES (?,?)",
            (i, h))

    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            created = r.get("created_at") or r.get("decided_at")
            if not created:
                report.errors.append(
                    f"E4 override {r.get('forecast_id')}: created_at 누락 — 시점 불변식 검사 불가")
                continue
            conn.execute(
                "INSERT OR REPLACE INTO research_status_override"
                " (forecast_id, status, reason, created_at) VALUES (?,?,?,?)",
                (r["forecast_id"], r["status"], r.get("reason"), created))

    # E4: 시점 불변식 — 해소일 이후 생성된 override는 게이밍 채널
    for row in conn.execute(
            """SELECT o.forecast_id, o.created_at, r.resolved_date
               FROM research_status_override o
               JOIN resolutions r ON r.forecast_id = o.forecast_id
               WHERE o.created_at >= r.resolved_date"""):
        report.errors.append(
            f"E4 override {row['forecast_id']}: 생성일 {row['created_at']} ≥ "
            f"해소일 {row['resolved_date']} — 결과 인지 후 소급 제외 금지")


def _precheck_forecast_hashes(conn: sqlite3.Connection, root: Path) -> list[str]:
    """rebuild 전 기존 sync_meta 대비 예측 파일 해시 대조 — 불일치 목록 반환."""
    issues: list[str] = []
    try:
        rows = list(conn.execute(
            "SELECT file, sha256 FROM sync_meta WHERE file LIKE 'forecasts/%'"))
    except Exception:  # noqa: BLE001 — 테이블 미존재(완전 신규 DB)
        return issues
    for r in rows:
        path = root / r["file"]
        if not path.exists():
            issues.append(f"E2 {r['file']}: 파일 없음 (rebuild 전 검출)")
        elif sha256_file(path) != r["sha256"]:
            issues.append(f"E1 {r['file']}: 해시 불일치 (rebuild 전 검출)")
    return issues


def _write_hash_anchor(conn: sqlite3.Connection, root: Path) -> None:
    """git 추적 해시 앵커(forecasts/.hashes) 갱신 — DB 재구축과 무관한 독립 기준선.

    DB(파생·재생성 가능)만이 기준선이면 rebuild가 기준선 자체를 지울 수 있다.
    이 파일은 git이 추적하므로 변조 시 diff로 드러난다 (AUDIT-260715 T-5).
    """
    rows = list(conn.execute(
        "SELECT file, sha256 FROM sync_meta WHERE file LIKE 'forecasts/%' ORDER BY file"))
    if not rows:
        return
    anchor = root / "forecasts" / ".hashes"
    # newline="\n" 고정: Windows 기본 텍스트 모드의 CRLF가 .gitattributes -text 하에서
    # 순수 EOL diff churn을 만드는 것을 차단 (내용 해시는 불변 — 2026-07-20 검증)
    with open(anchor, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(f"{r['sha256']}  {r['file']}" for r in rows) + "\n")


# ── questions ────────────────────────────────────────────────────

def _sync_questions(conn: sqlite3.Connection, root: Path, report: DriftReport) -> None:
    registry_path = root / "questions" / "registry.yaml"
    questions = load_registry(registry_path)

    from ..registry import factory_filter_violation

    for q in questions:
        # WS1 등록 필터 — sync는 경고만 (강제 차단은 forecast 프리플라이트)
        violation = factory_filter_violation(q)
        if violation:
            report.warnings.append(f"W2 등록필터: {violation}")
        old = conn.execute(
            "SELECT src_hash FROM questions WHERE question_id = ?", (q.question_id,)
        ).fetchone()
        if old and old["src_hash"] != q.src_hash:
            n_forecasts = conn.execute(
                "SELECT COUNT(*) AS n FROM forecasts WHERE question_id = ?", (q.question_id,)
            ).fetchone()["n"]
            if n_forecasts > 0:
                report.warnings.append(
                    f"W1 {q.question_id}: 예측 {n_forecasts}건 존재하는 질문의 "
                    f"질문/판정기준 텍스트가 변경됨 — 판정기준 불변 규칙 확인 필요"
                )
        conn.execute(
            """INSERT INTO questions (question_id, title, question, deadline_kind, deadline,
                 rolling_days, resolution, resolution_source, domain, cadence_raw,
                 schedule_json, action_link, status, created, notes,
                 required_snapshots_json, src_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(question_id) DO UPDATE SET
                 title=excluded.title, question=excluded.question,
                 deadline_kind=excluded.deadline_kind, deadline=excluded.deadline,
                 rolling_days=excluded.rolling_days, resolution=excluded.resolution,
                 resolution_source=excluded.resolution_source, domain=excluded.domain,
                 cadence_raw=excluded.cadence_raw, schedule_json=excluded.schedule_json,
                 action_link=excluded.action_link, status=excluded.status,
                 created=excluded.created, notes=excluded.notes,
                 required_snapshots_json=excluded.required_snapshots_json,
                 src_hash=excluded.src_hash""",
            (q.question_id, q.title, q.question, q.deadline_kind,
             q.deadline.isoformat() if q.deadline else None,
             q.rolling_days, q.resolution, q.resolution_source, q.domain,
             q.cadence_raw, json.dumps(q.schedule, ensure_ascii=False),
             q.action_link, q.status,
             q.created.isoformat() if q.created else None,
             q.notes, json.dumps(q.required_snapshots, ensure_ascii=False), q.src_hash),
        )


# ── forecasts ────────────────────────────────────────────────────

def _sync_forecasts(conn: sqlite3.Connection, root: Path, report: DriftReport, now: str) -> None:
    forecasts_dir = root / "forecasts"
    seen_files: set[str] = set()

    for path in F.iter_forecast_files(forecasts_dir):
        rel = path.relative_to(root).as_posix()
        seen_files.add(rel)
        current_hash = sha256_file(path)

        meta = conn.execute("SELECT sha256 FROM sync_meta WHERE file = ?", (rel,)).fetchone()
        if meta:
            if meta["sha256"] != current_hash:
                report.errors.append(f"E1 {rel}: 예측 파일이 변경됨 — 불변성 위반")
            continue  # 기존 파일은 재파싱 불필요 (멱등)

        try:
            rec = F.parse_forecast_file(path)
        except Exception as exc:  # noqa: BLE001 — 파일 하나가 전체 sync를 막지 않게
            report.errors.append(f"파싱 실패 {rel}: {exc}")
            continue

        conn.execute(
            """INSERT OR REPLACE INTO forecasts (forecast_id, question_id, round, forecast_ts,
                 probability, ci80_lo, ci80_hi, window_end, snapshots_json, market_implied,
                 edge, model, prompt_version, phase, method, sources_count, path,
                 file_sha256, ingested_at, research_status,
                 shadow_extremized, ml_divergence_pp, divergence_class, pipeline_tier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.forecast_id, rec.question_id, rec.round,
             rec.forecast_ts.isoformat(timespec="seconds") if rec.forecast_ts else None,
             rec.probability, rec.ci80_lo, rec.ci80_hi,
             rec.window_end.isoformat() if rec.window_end else None,
             json.dumps(rec.snapshots, ensure_ascii=False, default=str),
             rec.market_implied, rec.edge, rec.model, rec.prompt_version,
             rec.phase, rec.method, rec.sources_count, rel, rec.file_sha256, now,
             rec.research_status,
             rec.shadow_extremized, rec.ml_divergence_pp, rec.divergence_class,
             rec.pipeline_tier),
        )
        conn.execute(
            "INSERT OR REPLACE INTO sync_meta (file, sha256, mtime, ingested_at) VALUES (?,?,?,?)",
            (rel, current_hash, path.stat().st_mtime, now),
        )

    # E2: DB에는 있는데 파일이 사라진 예측
    for row in conn.execute("SELECT forecast_id, path FROM forecasts"):
        if row["path"] not in seen_files:
            report.errors.append(f"E2 {row['forecast_id']}: DB에 있으나 파일 없음 ({row['path']})")

    # E6 (WS5): 본문 없는 evidence = 쓰기 중단 잔재 — 경고만 (자동 삭제 금지)
    for p in sorted(forecasts_dir.rglob("*_evidence.md")):
        main = p.with_name(p.name.replace("_evidence.md", ".md"))
        if not main.exists():
            report.warnings.append(
                f"E6 고아 evidence: {p.relative_to(root).as_posix()} — 본문 없음 "
                "(쓰기 중단 잔재 가능 — 수동 삭제 또는 보존 결정, 자동 삭제 안 함)")


# ── ml history (append-only JSONL → 3테이블) ─────────────────────

def _sync_ml_history(conn: sqlite3.Connection, root: Path, report: DriftReport, now: str) -> None:
    """data/ml_history/*.jsonl → ml_forecasts·ml_sentiment·market_implied.

    append-only 파일이라 해시 변경은 정상 (E1 아님). 변경 시 파일 전체를
    INSERT OR REPLACE로 재적재 — PK 멱등이라 안전.
    """
    from ..ml.history import history_dir, iter_history

    d = history_dir(root)
    if not d.exists():
        return

    changed = False
    for path in sorted(d.glob("*.jsonl")):
        rel = path.relative_to(root).as_posix()
        current_hash = sha256_file(path)
        meta = conn.execute("SELECT sha256 FROM sync_meta WHERE file = ?", (rel,)).fetchone()
        if meta and meta["sha256"] == current_hash:
            continue
        changed = True
        conn.execute(
            "INSERT OR REPLACE INTO sync_meta (file, sha256, mtime, ingested_at) VALUES (?,?,?,?)",
            (rel, current_hash, path.stat().st_mtime, now))

    if not changed:
        return

    for run in iter_history(root):
        ts = run.get("run_ts")
        for r in run.get("forecasts", []):
            conn.execute(
                """INSERT OR REPLACE INTO ml_forecasts
                   (run_ts, question_id, model, kind, prob, threshold, horizon_weeks, detail_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ts, r["question_id"], r["model"], r["kind"], r["prob"],
                 r.get("threshold"), r.get("horizon_weeks"),
                 json.dumps(r.get("detail", {}), ensure_ascii=False)))
        for s in run.get("sentiment", []):
            conn.execute(
                "INSERT OR REPLACE INTO ml_sentiment (run_ts, feed, n_headlines, score)"
                " VALUES (?,?,?,?)",
                (ts, s["feed"], s.get("n_headlines"), s.get("score")))
        for m in run.get("market", []):
            conn.execute(
                """INSERT OR REPLACE INTO market_implied
                   (run_ts, question_id, source, prob, detail_json)
                   VALUES (?,?,?,?,?)""",
                (ts, m["question_id"], m["source"], m["prob"],
                 json.dumps(m.get("detail", {}), ensure_ascii=False)))


# ── ledger ───────────────────────────────────────────────────────

def _sync_ledger(conn: sqlite3.Connection, root: Path, report: DriftReport) -> None:
    ledger_path = root / "calibration" / "ledger.csv"
    rows = F.parse_ledger(ledger_path)

    known = {r["line_no"]: r["line_hash"] for r in conn.execute("SELECT * FROM ledger_lines")}
    if known and len(rows) < len(known):
        report.errors.append(
            f"E3 원장 축소: DB {len(known)}행 > 파일 {len(rows)}행 — append-only 위반")
    for row in rows:
        if row.line_no in known and known[row.line_no] != row.line_hash:
            report.errors.append(f"E3 원장 {row.line_no}행 변조 — append-only 위반")

    for row in rows:
        conn.execute(
            """INSERT OR REPLACE INTO resolutions (forecast_id, resolved_date, question_id,
                 forecast_date, probability, outcome, brier, domain, notes, ledger_line)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row.forecast_id, row.resolved_date, row.question_id, row.forecast_date,
             row.probability, row.outcome, row.brier, row.domain, row.notes, row.line_no),
        )
        conn.execute(
            "INSERT OR REPLACE INTO ledger_lines (line_no, line_hash) VALUES (?, ?)",
            (row.line_no, row.line_hash),
        )
