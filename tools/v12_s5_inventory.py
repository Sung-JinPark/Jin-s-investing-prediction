#!/usr/bin/env python
"""tools/v12_s5_inventory.py — S5-1 inventory 재생성 (envelope spec 'cd src && python -m ai_fc inventory').

왜 CLI 를 직접 부르지 않는가
---------------------------
루프 헌법 §1 은 파이썬 실행을 `tools/v12_run.py tools/v12_*.py` 경유로만 허용한다
(`python -m ai_fc …` 는 권한 목록 밖이라 거부된다). 그래서 이 스크립트가 CLI 하위명령
``inventory`` 가 **하는 일 그대로**를 라이브러리 호출로 재현한다:

    src/ai_fc/cli.py::cmd_inventory
        conn = ingest.connect(root/"db"/"index.db")
        _sync_or_exit(conn, root)          →  ingest.sync(conn, root, strict=True)
        write_inventory(root, conn)        →  docs/generated/{inventory,licenses}.generated.md
                                              + docs/generated/read_model_v2.schema.json

차이는 진입점뿐이고 호출 순서·인자·대상 파일이 같다. `ai_fc.config` 는 임포트하지 않는다
(키 파일 경로를 들고 있어 헌법 §6 '시크릿 미로드' 와 무관하게 만들기 위해서다) — root 는
파일 위치에서 직접 계산해 넘긴다.

안전 규약
---------
- 쓰기 대상은 docs/generated/ 3파일과 gitignore 된 db/index.db 뿐이다. 실행 전후로 불변
  경로(forecasts/·calibration/·src/·data/timeseries_v8·data/timeseries_v2·questions/)의
  git 워킹트리 변경 0 을 대사하고, 하나라도 더러워지면 비정상 종료한다.
- `--check` 는 아무것도 쓰지 않고 현재 생성물이 원천과 같은지만 본다.

산출: data/timeseries_v12/reports/inventory_result.json
실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_inventory.py [--check]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

OUT = ROOT / "data/timeseries_v12/reports/inventory_result.json"

GENERATED = [
    "docs/generated/inventory.generated.md",
    "docs/generated/licenses.generated.md",
    "docs/generated/read_model_v2.schema.json",
]

IMMUTABLE_PATHS = [
    "forecasts",
    "calibration",
    "src",
    "data/timeseries_v8",
    "data/timeseries_v2",
    "questions",
]


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout.strip()


def immutable_dirty() -> list[str]:
    status = git("status", "--porcelain", "--", *IMMUTABLE_PATHS)
    return [line for line in status.splitlines() if line.strip()]


def snapshot() -> dict[str, str | None]:
    return {rel: sha256_file(ROOT / rel) for rel in GENERATED}


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    dirty_before = immutable_dirty()
    if dirty_before:
        print("ABORT: 불변 경로가 실행 전부터 더럽다:\n" + "\n".join(dirty_before), file=sys.stderr)
        return 2

    from ai_fc.db import ingest  # noqa: E402
    from ai_fc.inventory import OUTPUT, collect, inventory_is_current, write_inventory  # noqa: E402

    before = snapshot()
    conn = ingest.connect(ROOT / "db" / "index.db")
    report = ingest.sync(conn, ROOT, strict=True)
    sync_ok = bool(report.ok)
    sync_summary = report.summary()

    payload: dict = {
        "schema": "v12.s5_inventory/1",
        "task_id": "S5-1",
        "generated_by": "tools/v12_s5_inventory.py",
        "equivalent_cli": "cd src && python -m ai_fc inventory",
        "why_not_cli": "루프 헌법 §1 — python -m ai_fc 는 권한 목록 밖. cmd_inventory 의 호출을 그대로 재현했다.",
        "output_target": OUTPUT.as_posix(),
        "sync": {
            "ok": sync_ok,
            "summary": sync_summary,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "db_path": "db/index.db (gitignore — 파생 인덱스)",
        },
    }

    if not sync_ok:
        payload["status"] = "차단"
        payload["reason"] = "ingest.sync 가 불변성 위반을 보고했다 — inventory 생성을 중단한다."
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    snap = collect(ROOT, conn)
    payload["snapshot"] = {
        "source_fingerprint": snap["fingerprint"],
        "questions": snap["questions"],
        "forecast_files": snap["forecast_files"],
        "evidence_files": snap["evidence_files"],
        "resolution_rows": snap["resolution_rows"],
        "benchmark_rows": snap["benchmark_rows"],
        "correction_rows": snap["correction_rows"],
        "contracts": snap["contracts"],
        "dualdb_eras": snap["dualdb_eras"],
        "tables": snap["tables"],
    }
    payload["was_current_before_run"] = bool(inventory_is_current(ROOT, conn))

    if check_only:
        payload["mode"] = "check"
        payload["files"] = {rel: {"sha256": before[rel]} for rel in GENERATED}
    else:
        payload["mode"] = "write"
        write_inventory(ROOT, conn)
        after = snapshot()
        payload["files"] = {
            rel: {
                "sha256_before": before[rel],
                "sha256_after": after[rel],
                "changed": before[rel] != after[rel],
                "created": before[rel] is None,
            }
            for rel in GENERATED
        }
        payload["files_changed"] = sorted(r for r in GENERATED if before[r] != after[r])
        payload["is_current_after_run"] = bool(inventory_is_current(ROOT, conn))

    conn.close()

    dirty_after = immutable_dirty()
    payload["immutable_paths"] = {
        "checked": IMMUTABLE_PATHS,
        "dirty_before": dirty_before,
        "dirty_after": dirty_after,
        "clean": not dirty_after,
    }
    payload["status"] = "완료" if not dirty_after else "차단"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not dirty_after else 1


if __name__ == "__main__":
    raise SystemExit(main())
