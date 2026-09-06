#!/usr/bin/env python
"""tools/v12_s3_0_result_check.py — S3-0 result JSON 의 자기주장 대사 (읽기 전용).

result JSON 은 사람이 쓴다. 그래서 그 안의 주장을 파일·git·검증기 출력과 하나씩 맞춰 본다.

  R1 파싱·필수 키
  R2 artifacts 의 sha256 이 실제 파일과 일치
  R3 인용한 커밋 해시가 실제로 존재하고, 그 커밋이 등록부를 담고 있는지
  R4 accept 주장(커밋 해시 로그 존재)이 실제로 성립하는지
  R5 봉인·원장 해시가 BOOT 기준선과 일치
  R6 등록부 검증기를 다시 돌려 실패 0 이고, result 가 인용한 항목 수와 같은지
  R7 '결과 미계산' 주장 — transfer_results.json 이 아직 없어야 한다

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s3_0_result_check.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "outputs/timeseries_v12/loop/results/S3-0.json"
PREREG = ROOT / "data/timeseries_v12/prereg/hypotheses.json"
LOG = ROOT / "data/timeseries_v12/prereg/prereg_commit_log.json"
SEALED_BASELINE = "e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224"
LEDGER_BASELINE = "b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout.strip() if out.returncode == 0 else f"<git error: {out.stderr.strip()[:80]}>"


def main() -> int:
    rows: list[tuple[str, bool, str]] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        rows.append((cid, bool(ok), detail))

    res = json.loads(RESULT.read_text(encoding="utf-8"))
    need = ["task_id", "title", "status", "stage", "artifacts", "accept_check",
            "seal_reconciliation", "key_findings", "open_questions", "not_done", "next_task"]
    add("R1", all(k in res for k in need), f"필수 키 누락 {[k for k in need if k not in res] or '없음'}")
    add("R1-b", res.get("task_id") == "S3-0", f"task_id={res.get('task_id')!r}")

    for rel, expect in res["artifacts"].items():
        path = ROOT / rel
        got = sha256(path) if path.exists() else "<없음>"
        add("R2", got == expect, f"{rel} {got[:16]}… = 기재 {str(expect)[:16]}…")

    log = json.loads(LOG.read_text(encoding="utf-8"))
    prereg_commit = log["prereg_commit"]["commit"]
    add("R3-a", res["accept_check"]["prereg_commit"] == prereg_commit,
        f"result 의 커밋 {res['accept_check']['prereg_commit'][:12]}… = 로그의 {prereg_commit[:12]}…")
    subject = git("log", "-1", "--format=%s", prereg_commit)
    add("R3-b", subject.startswith("loop(v12): S3-0"),
        f"커밋 {prereg_commit[:12]}… 존재 · subject={subject[:44]}")
    blob = git("rev-parse", f"{prereg_commit}:data/timeseries_v12/prereg/hypotheses.json")
    add("R3-c", blob == log["registered_artifacts"]["data/timeseries_v12/prereg/hypotheses.json"]["git_blob_sha1"],
        f"그 커밋의 등록부 blob {blob[:12]}… = 로그 기재값")
    # 등록부가 커밋 이후 손대지 않았는지 — 작업본 blob 이 커밋본과 같아야 한다
    now_blob = git("hash-object", str(PREREG))
    add("R3-d", now_blob == blob, f"작업본 blob {now_blob[:12]}… = 커밋본 {blob[:12]}… (등록부 무수정)")

    add("R4-a", LOG.exists(), f"커밋 해시 로그 존재: {LOG.relative_to(ROOT).as_posix()}")
    add("R4-b", res["accept_check"]["artifact_named_in_spec_exists"] is True and PREREG.exists(),
        "spec 이 지목한 hypotheses.json 존재")

    seal = json.loads(subprocess.run(
        [sys.executable, str(ROOT / "tools/v12_seal_check.py")], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8").stdout)
    add("R5-a", seal["sealed"] == SEALED_BASELINE == res["seal_reconciliation"]["sealed_sha256"],
        f"봉인 {seal['sealed'][:16]}… = BOOT 기준선 = result 기재값")
    add("R5-b", seal["ledger"] == LEDGER_BASELINE == res["seal_reconciliation"]["ledger_sha256"],
        f"원장 {seal['ledger'][:16]}… = 기준선 = result 기재값")

    chk = subprocess.run([sys.executable, str(ROOT / "tools/v12_prereg_check.py")], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in chk.stdout.splitlines() if ln.startswith("검사 ")]
    total = int(tail[0].split("검사 ")[1].split("항목")[0]) if tail else -1
    failed = int(tail[0].split("실패 ")[1]) if tail else -1
    add("R6-a", chk.returncode == 0 and failed == 0, f"등록부 검증기 재실행 — 실패 {failed}")
    add("R6-b", total == res["accept_check"]["prereg_check_items"],
        f"항목 수 {total} = result 기재 {res['accept_check']['prereg_check_items']}")

    tr = ROOT / "data/timeseries_v12/diagnostics/transfer_results.json"
    add("R7", not tr.exists(), f"transfer_results.json 부재 {not tr.exists()} — S3-1 소관, 결과 미계산")

    for cid, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'} {cid:6s} {detail}")
    bad = sum(0 if ok else 1 for _, ok, _ in rows)
    print(f"\n검사 {len(rows)}항목 · 실패 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
