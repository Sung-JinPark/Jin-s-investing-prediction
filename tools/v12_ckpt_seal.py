#!/usr/bin/env python
"""tools/v12_ckpt_seal.py — CKPT 월요일 체크포인트 봉인 (읽기 전용 + 봉인 파일 2개 기록).

무엇을 하는가 (설계도 §1 표 "00:00 월요일 체크포인트" = 중간 봉인: S1~S3 산출물 해시·상태 기록):

  C1  V8/V2 봉인 해시·v8 원장 해시를 BOOT 기준선과 재대사 (tools/v12_seal_check 재사용).
  C2  S1~S3 result JSON 9종이 선언한 산출물 63개의 sha256 을 **재계산**해 선언값과 대사 —
      단계 종료 후 산출물이 바뀌었는지(사후 수정) 잡는 것이 이 단계의 존재 이유다.
  C3  result JSON 9종 자체의 sha256 과 상태(완료/부분완료/차단)를 기록.
  C4  git: 63개 산출물 + 9개 result JSON 이 전부 추적 상태이고 워킹트리가 깨끗한지(미커밋 0).
  C5  불변 경로(forecasts/·calibration/·src/·data/timeseries_v8·data/timeseries_v2·questions/)
      워킹트리 무변경 대사.
  C6  체크포인트 앵커 해시: 위 파일들의 ``<sha256> *<relpath>`` 라인을 정렬해 재해시 —
      sunday_opus_loop.sh 의 sealed_hash() 와 **같은 규약**(바이너리 모드 ' *' 구분자).

무엇을 기록하는가:
  outputs/timeseries_v12/loop/checkpoint_monday.json  ← 정본(커밋). 아래 state.json 은 감독
      스크립트가 종료 시 {'ended','iters'} 로 **덮어쓴다**(sunday_opus_loop.sh:75). 그래서
      봉인 정본은 이 파일이고, state.json 에는 같은 앵커를 심되 덮어쓰기 사실을 명기한다.
  outputs/timeseries_v12/loop/state.json             ← 기존 ended/iters 보존 + checkpoint 블록.

출력은 시각(now)을 담지 않는다 — 재실행하면 바이트 동일해야 자기주장 대사가 가능하기 때문.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_ckpt_seal.py [--check]
      --check 는 파일을 쓰지 않고 대사만 한다.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_seal_check as sc  # noqa: E402

LOOP = ROOT / "outputs/timeseries_v12/loop"
RESULTS = LOOP / "results"
CKPT_FILE = LOOP / "checkpoint_monday.json"
STATE_FILE = LOOP / "state.json"
BACKLOG = ROOT / "data/timeseries_v12/ralph/V12_SUNDAY_BACKLOG_260904.json"

STAGE_ORDER = ["S1-1", "S1-2", "S1-3", "S2-1", "S2-2", "S2-3", "S3-0", "S3-1", "S3-2"]

# 불변 경로 — 루프 헌법 §2 (V8/V2 봉인·원장·forecasts·calibration 무수정)
IMMUTABLE_PATHS = [
    "forecasts",
    "calibration",
    "src",
    "data/timeseries_v8",
    "data/timeseries_v2",
    "questions",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> tuple[int, str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.returncode, out.stdout.strip()


def anchor_hash(pairs: list[tuple[str, str]]) -> str:
    """``<sha256> *<relpath>`` 라인 정렬 후 재해시 — sealed_hash() 와 동일 규약."""
    lines = sorted(f"{h} *{rel}\n" for rel, h in pairs)
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def build() -> dict:
    rows: list[dict] = []
    stages: dict[str, dict] = {}
    result_files: list[tuple[str, str]] = []

    for tid in STAGE_ORDER:
        rp = RESULTS / f"{tid}.json"
        d = json.loads(rp.read_text(encoding="utf-8"))
        rrel = rp.relative_to(ROOT).as_posix()
        rhash = sha256_file(rp)
        result_files.append((rrel, rhash))
        arts = d.get("artifacts", {})
        st = {
            "task_id": d.get("task_id"),
            "title": d.get("title"),
            "status": d.get("status"),
            "result_json": rrel,
            "result_json_sha256": rhash,
            "artifact_count": len(arts),
            "artifacts_matching_declared": 0,
            "artifacts_missing": [],
            "artifacts_drifted": [],
        }
        for rel, declared in arts.items():
            path = ROOT / rel
            if not path.is_file():
                st["artifacts_missing"].append(rel)
                rows.append({"task": tid, "path": rel, "declared": declared,
                             "actual": None, "match": False, "state": "MISSING"})
                continue
            actual = sha256_file(path)
            ok = actual == declared
            st["artifacts_matching_declared"] += int(ok)
            if not ok:
                st["artifacts_drifted"].append(rel)
            rows.append({"task": tid, "path": rel, "declared": declared,
                         "actual": actual, "match": ok,
                         "state": "OK" if ok else "DRIFT"})
        stages[tid] = st

    art_pairs = [(r["path"], r["actual"]) for r in rows if r["actual"]]
    all_pairs = art_pairs + result_files

    # C4 — git 추적·청결 대사 (산출물 + result JSON)
    paths = sorted({p for p, _ in all_pairs})
    rc_tracked, tracked_out = git("ls-files", "--", *paths)
    tracked = set(tracked_out.splitlines())
    untracked = sorted(p for p in paths if p not in tracked)
    rc_status, status_out = git("status", "--porcelain", "--untracked-files=all", "--", *paths)
    dirty = sorted(line[3:].strip().strip('"') for line in status_out.splitlines() if line)

    # C5 — 불변 경로 워킹트리 무변경
    rc_imm, imm_out = git("status", "--porcelain", "--untracked-files=all", "--", *IMMUTABLE_PATHS)
    immutable_dirty = sorted(line[3:].strip().strip('"') for line in imm_out.splitlines() if line)

    _, head = git("rev-parse", "HEAD")
    _, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    _, head_subject = git("log", "-1", "--format=%s")

    # C1 — 봉인 재대사
    sealed = sc.sealed_hash()
    ledger = sc.ledger_hash()
    sealed_base = (LOOP / "sealed_baseline.hash").read_text().strip()
    ledger_base = (LOOP / "ledger_baseline.hash").read_text().strip()

    backlog = json.loads(BACKLOG.read_text(encoding="utf-8"))
    window = backlog["window"]
    done_ids = [t["id"] for t in backlog["tasks"] if t["status"] in ("완료", "부분완료")]
    pending = [t["id"] for t in backlog["tasks"] if t["status"] == "대기"]

    ck = {
        "schema": "v12_monday_checkpoint_v1",
        "task_id": "CKPT",
        "title": "월요일 체크포인트 봉인",
        "branch": branch,
        "head_commit": head,
        "head_subject": head_subject,
        "window": window,
        "seal_reconciliation": {
            "sealed_sha256": sealed,
            "sealed_baseline": sealed_base,
            "sealed_match": sealed == sealed_base,
            "sealed_prefix_ok": sealed.startswith("e3ff2fdb"),
            "ledger_sha256": ledger,
            "ledger_baseline": ledger_base,
            "ledger_match": ledger == ledger_base,
            "source": "tools/v12_seal_check.py (sunday_opus_loop.sh sealed_hash() 규약 재현)",
        },
        "immutable_paths_checked": IMMUTABLE_PATHS,
        "immutable_paths_dirty": immutable_dirty,
        "stages": stages,
        "artifact_totals": {
            "declared": len(rows),
            "present": len(art_pairs),
            "missing": sum(1 for r in rows if r["state"] == "MISSING"),
            "drifted": sum(1 for r in rows if r["state"] == "DRIFT"),
            "result_json_count": len(result_files),
        },
        "git_reconciliation": {
            "files_checked": len(paths),
            "untracked": untracked,
            "dirty_or_uncommitted": dirty,
            "clean": not untracked and not dirty,
        },
        "anchors": {
            "convention": "sha256 over sorted '<sha256> *<relpath>' lines (sealed_hash() 규약)",
            "artifacts_anchor": anchor_hash(art_pairs),
            "results_anchor": anchor_hash(result_files),
            "checkpoint_anchor": anchor_hash(all_pairs),
        },
        "backlog_state": {
            "path": BACKLOG.relative_to(ROOT).as_posix(),
            "done": done_ids,
            "pending": pending,
            "s3_outcome": "채택 0/8 — 전이 불가 부정 결과 확정 (S3-2)",
            "next_stage": "S4-1 (부정 결과 계약)",
        },
        "files": rows,
        "result_files": [{"path": p, "sha256": h} for p, h in result_files],
        "notes": [
            "이 파일이 체크포인트 봉인 정본이다. state.json 은 감독 스크립트가 종료 시 "
            "{'ended','iters'} 로 덮어쓰므로(sunday_opus_loop.sh:75) 같은 앵커를 심되 정본이 아니다.",
            "감독 스크립트의 00:00 KST 자동 체크포인트(monday_ckpt.sha256)는 epoch "
            f"{window['monday_ckpt_epoch']} 이후 별도로 기록된다 — 본 태스크는 그와 독립인 태스크 봉인이다.",
            "백테스트·홀드아웃·refresh·push 0회. 이 스크립트는 읽기 + 봉인 파일 2개 쓰기만 한다.",
        ],
    }
    ck["ok"] = bool(
        ck["seal_reconciliation"]["sealed_match"]
        and ck["seal_reconciliation"]["ledger_match"]
        and ck["seal_reconciliation"]["sealed_prefix_ok"]
        and ck["artifact_totals"]["missing"] == 0
        and ck["artifact_totals"]["drifted"] == 0
        and not immutable_dirty
    )
    return ck


def state_block(ck: dict) -> dict:
    prev = {}
    if STATE_FILE.is_file():
        try:
            prev = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    prev.pop("checkpoint", None)
    return {
        **prev,
        "checkpoint": {
            "task_id": "CKPT",
            "sealed": ck["ok"],
            "canonical_record": CKPT_FILE.relative_to(ROOT).as_posix(),
            "checkpoint_anchor": ck["anchors"]["checkpoint_anchor"],
            "artifacts_anchor": ck["anchors"]["artifacts_anchor"],
            "results_anchor": ck["anchors"]["results_anchor"],
            "sealed_sha256": ck["seal_reconciliation"]["sealed_sha256"],
            "ledger_sha256": ck["seal_reconciliation"]["ledger_sha256"],
            "head_commit": ck["head_commit"],
            "stages_sealed": STAGE_ORDER,
            "artifacts_sealed": ck["artifact_totals"]["present"],
            "next_stage": ck["backlog_state"]["next_stage"],
            "warning": "감독 스크립트가 종료 시 이 파일을 {'ended','iters'} 로 덮어쓴다 — "
                       "봉인 정본은 canonical_record 경로다.",
        },
    }


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    ck = build()
    if not check_only:
        CKPT_FILE.write_text(json.dumps(ck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        STATE_FILE.write_text(json.dumps(state_block(ck), ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

    sr = ck["seal_reconciliation"]
    at = ck["artifact_totals"]
    print(f"sealed  {sr['sealed_sha256'][:16]}… match={sr['sealed_match']} prefix_ok={sr['sealed_prefix_ok']}")
    print(f"ledger  {sr['ledger_sha256'][:16]}… match={sr['ledger_match']}")
    print(f"artifacts declared={at['declared']} present={at['present']} missing={at['missing']} drifted={at['drifted']}")
    print(f"result JSON {at['result_json_count']}종")
    print(f"git clean={ck['git_reconciliation']['clean']} untracked={len(ck['git_reconciliation']['untracked'])} dirty={len(ck['git_reconciliation']['dirty_or_uncommitted'])}")
    if ck["git_reconciliation"]["untracked"]:
        for p in ck["git_reconciliation"]["untracked"]:
            print(f"  UNTRACKED {p}")
    if ck["git_reconciliation"]["dirty_or_uncommitted"]:
        for p in ck["git_reconciliation"]["dirty_or_uncommitted"]:
            print(f"  DIRTY {p}")
    print(f"immutable dirty={len(ck['immutable_paths_dirty'])}")
    for p in ck["immutable_paths_dirty"]:
        print(f"  IMMUTABLE-DIRTY {p}")
    for r in ck["files"]:
        if r["state"] != "OK":
            print(f"  {r['state']} {r['task']} {r['path']}")
    a = ck["anchors"]
    print(f"anchor artifacts={a['artifacts_anchor']}")
    print(f"anchor results  ={a['results_anchor']}")
    print(f"anchor CHECKPOINT={a['checkpoint_anchor']}")
    print(f"OK={ck['ok']} written={'no (--check)' if check_only else 'yes'}")
    return 0 if ck["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
