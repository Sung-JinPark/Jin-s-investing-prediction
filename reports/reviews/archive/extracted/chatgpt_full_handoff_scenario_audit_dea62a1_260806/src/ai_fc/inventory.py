"""Deterministic repository/data inventory generated from source and rebuilt indexes."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import yaml

from . import files as F
from .integrity import source_fingerprint
from .registry import load_registry

OUTPUT = Path("docs") / "generated" / "inventory.generated.md"
LICENSE_OUTPUT = Path("docs") / "generated" / "licenses.generated.md"


def _csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _table_count(conn: sqlite3.Connection | None, table: str) -> int | None:
    if conn is None:
        return None
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        return None


def collect(root: Path, conn: sqlite3.Connection | None = None) -> dict:
    forecasts = list(F.iter_forecast_files(root / "forecasts"))
    evidence = list((root / "forecasts").rglob("*_evidence.md"))
    registry = load_registry(root / "questions" / "registry.yaml")
    config_path = root / "dualdb" / "config.yaml"
    dual_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    seed_dir = root / "dualdb" / "data" / "seeds"
    seed_counts = {
        path.stem: _csv_rows(path) for path in sorted(seed_dir.glob("*.csv"))
    } if seed_dir.exists() else {}
    tables = (
        "questions", "forecasts", "resolutions", "benchmark_scores",
        "resolution_event", "score_observation", "probability_record",
        "source_registry", "model_registry",
    )
    return {
        "fingerprint": source_fingerprint(root),
        "questions": len(registry),
        "forecast_files": len(forecasts),
        "evidence_files": len(evidence),
        "resolution_rows": _csv_rows(root / "calibration" / "ledger.csv"),
        "benchmark_rows": _csv_rows(root / "calibration" / "benchmark_ledger.csv"),
        "correction_rows": _csv_rows(root / "calibration" / "corrections.csv"),
        "contracts": len(list((root / "data" / "contracts").glob("*.yaml"))),
        "dualdb_eras": len((dual_config.get("anchors") or {})),
        "dualdb_seed_counts": seed_counts,
        "tables": {table: _table_count(conn, table) for table in tables},
    }


def render(snapshot: dict) -> str:
    lines = [
        "# Generated data inventory",
        "",
        "> 이 문서는 정적 수기 현황표가 아닙니다. `ai-fc inventory`가 원천 파일과 재구축된",
        "> 읽기 인덱스에서 결정론적으로 생성합니다. 숫자를 직접 수정하지 마세요.",
        "",
        f"- Source fingerprint: `{snapshot['fingerprint']}`",
        f"- Registered questions: {snapshot['questions']}",
        f"- Forecast bodies: {snapshot['forecast_files']}",
        f"- Evidence files: {snapshot['evidence_files']}",
        f"- Resolution rows / unique events: {snapshot['resolution_rows']} / "
        f"{snapshot['tables'].get('resolution_event') if snapshot['tables'].get('resolution_event') is not None else 'index not supplied'}",
        f"- Benchmark rows: {snapshot['benchmark_rows']}",
        f"- Pending/approved correction rows: {snapshot['correction_rows']}",
        f"- Source contracts: {snapshot['contracts']}",
        f"- DualDB configured eras: {snapshot['dualdb_eras']}",
        "",
        "## SQLite read index",
        "",
        "| Table | Rows |",
        "|---|---:|",
    ]
    for table, count in snapshot["tables"].items():
        lines.append(f"| `{table}` | {count if count is not None else 'not supplied'} |")
    lines.extend(["", "## DualDB source seeds", "", "| Seed | Rows |", "|---|---:|"])
    for name, count in snapshot["dualdb_seed_counts"].items():
        lines.append(f"| `{name}.csv` | {count} |")
    lines.extend([
        "",
        "## Interpretation",
        "",
        "SQLite와 DualDB의 데이터베이스 파일은 파생 산출물입니다. 위 원천 수치와 다르면",
        "데이터를 DB 쪽에 맞추지 말고 clean rebuild를 수행해야 합니다. 반복 예측 회차는",
        "행 단위 점수와 실제 결과(event) 단위 점수를 별도로 표시합니다.",
        "",
    ])
    return "\n".join(lines)


def write_inventory(root: Path, conn: sqlite3.Connection | None = None) -> Path:
    target = root / OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(collect(root, conn)), encoding="utf-8", newline="\n")
    write_license_manifest(root)
    from .read_model_contract import write_schema
    write_schema(root)
    return target


def inventory_is_current(root: Path, conn: sqlite3.Connection | None = None) -> bool:
    target = root / OUTPUT
    license_target = root / LICENSE_OUTPUT
    from .read_model_contract import schema
    import json
    schema_target = root / "docs" / "generated" / "read_model_v2.schema.json"
    return (
        target.exists()
        and target.read_text(encoding="utf-8") == render(collect(root, conn))
        and license_target.exists()
        and license_target.read_text(encoding="utf-8") == render_license_manifest(root)
        and schema_target.exists()
        and schema_target.read_text(encoding="utf-8")
        == json.dumps(schema(), ensure_ascii=False, indent=2) + "\n"
    )


def render_license_manifest(root: Path) -> str:
    path = root / "data" / "source_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    sources = payload.get("sources") or []
    lines = [
        "# Generated source license manifest",
        "",
        "> `ai-fc inventory`가 source registry에서 생성합니다. GitHub Pages 표시는 원시",
        "> 데이터 재배포 허가를 뜻하지 않습니다. `review_required` 원천은 파생 통계만 사용합니다.",
        "",
        "- 확인일: 2026-08-01",
        "",
        "| Source | Provider | Terms / endpoint | Status | Pages policy |",
        "|---|---|---|---|---|",
    ]
    for source in sources:
        status = source.get("license_status", "review_required")
        policy = (
            "파생 통계 표시 가능; 원시 재배포 금지"
            if status != "approved"
            else "계약 범위 내 파생 통계 표시"
        )
        lines.append(
            f"| `{source.get('id','')}` | {source.get('provider','')} | "
            f"[{source.get('endpoint','')}]({source.get('endpoint','')}) | `{status}` | {policy} |"
        )
    lines.extend([
        "",
        "## Pending manual reviews",
        "",
        "- CBOE, Nasdaq Data Link, Google News RSS는 registry 편입 전 재배포 약관을 별도로 확인한다.",
        "- Yahoo cross-check는 비활성 상태를 유지하며 공식 해소 근거 또는 원시 재배포에 쓰지 않는다.",
        "",
    ])
    return "\n".join(lines)


def write_license_manifest(root: Path) -> Path:
    target = root / LICENSE_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_license_manifest(root), encoding="utf-8", newline="\n")
    return target
