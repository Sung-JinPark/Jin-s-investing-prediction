#!/usr/bin/env python
"""tools/v12_ckpt_result_check.py — CKPT result JSON 의 자기주장 대사 (읽기 전용).

result JSON 은 사람이 쓴다. 그래서 그 안의 주장을 파일·git·봉인 JSON·재실행 출력과 하나씩 맞춘다.

  R1  파싱·필수 키·task_id·status
  R2  artifacts 의 sha256 이 실제 파일과 일치
  R3  인용 커밋이 실재하고 산출물을 담고 있으며, 커밋 이후 산출물 무수정
  R4  accept 주장 — state.json 의 checkpoint 블록·checkpoint_monday.json 존재와 ok=true
  R5  봉인·원장 해시가 BOOT 기준선과 일치 (재계산)
  R6  headline 수치가 checkpoint_monday.json 필드와 일치 (63·9·72·앵커 3종)
  R7  봉인 재실행(--check) 이 같은 앵커를 내는지 = 멱등성. 표 md 가 렌더 출력과 바이트 일치
  R8  not_done 주장 — S4 산출물 미작성·감독 00:00 체크포인트 미발동·state.json gitignore 사실

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_ckpt_result_check.py
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_ckpt_seal as seal      # noqa: E402
import v12_ckpt_tables as tbl     # noqa: E402
import v12_seal_check as sc       # noqa: E402

RESULT = ROOT / "outputs/timeseries_v12/loop/results/CKPT.json"
CKPT = ROOT / "outputs/timeseries_v12/loop/checkpoint_monday.json"
STATE = ROOT / "outputs/timeseries_v12/loop/state.json"
TABLES = ROOT / "outputs/timeseries_v12/loop/_ckpt_tables.md"
SEAL_BASELINE = "e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224"
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

    def ck(tag: str, ok: bool, note: str = "") -> None:
        rows.append((tag, bool(ok), note))

    # R1 ------------------------------------------------------------------
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    ck("R1 파싱", True, RESULT.name)
    for key in ("task_id", "title", "status", "commit", "commit_sha",
                "artifacts_in_seal_commit", "artifacts_follow_up_commit", "artifacts", "accept_check",
                "headline", "seal_reconciliation", "read_only", "forbidden_verbs_executed",
                "not_done", "open_questions", "next_task"):
        ck(f"R1 키 {key}", key in d)
    ck("R1 task_id=CKPT", d.get("task_id") == "CKPT", str(d.get("task_id")))
    ck("R1 status 완료", d.get("status") == "완료", str(d.get("status")))
    ck("R1 금지 verb 0", d.get("forbidden_verbs_executed") == [], str(d.get("forbidden_verbs_executed")))

    # R2 ------------------------------------------------------------------
    for rel, declared in d["artifacts"].items():
        p = ROOT / rel
        ck(f"R2 {rel}", p.is_file() and sha256(p) == declared,
           "" if p.is_file() else "파일 없음")

    # R3 ------------------------------------------------------------------
    commit = str(d["commit_sha"])
    subject = git("log", "-1", "--format=%s", commit)
    ck("R3 커밋 실재", not subject.startswith("<git error"), f"{commit[:8]} {subject[:48]}")
    files_in_commit = set(git("show", "--name-only", "--format=", commit).splitlines())
    ck("R3 봉인 커밋 파일 목록 일치",
       set(d["artifacts_in_seal_commit"]) <= files_in_commit,
       f"{len(d['artifacts_in_seal_commit'])}개 주장")
    for rel in d["artifacts_in_seal_commit"]:
        blob = git("rev-parse", f"{commit}:{rel}")
        cur = git("hash-object", str(ROOT / rel))
        ck(f"R3 커밋 후 무수정 {rel}", blob == cur, f"{blob[:8]} vs {cur[:8]}")
    # 후속 커밋 대상(이 result JSON·자기검사 스크립트)은 아직 미커밋일 수 있다 — 존재·해시만(R2).
    others = [r for r in d["artifacts"]
              if r not in d["artifacts_in_seal_commit"]
              and r != "outputs/timeseries_v12/loop/state.json"]
    ck("R3 후속 커밋 대상 목록 일치", sorted(others) == sorted(d["artifacts_follow_up_commit"]),
       f"{others}")

    # R4 ------------------------------------------------------------------
    ckpt = json.loads(CKPT.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8"))
    ck("R4 checkpoint_monday.json ok", ckpt.get("ok") is True)
    ck("R4 state.json checkpoint 블록", "checkpoint" in state)
    cb = state.get("checkpoint", {})
    ck("R4 state anchor == ckpt anchor",
       cb.get("checkpoint_anchor") == ckpt["anchors"]["checkpoint_anchor"])
    ck("R4 state sealed=true", cb.get("sealed") is True)
    ck("R4 state 정본 포인터", cb.get("canonical_record") == CKPT.relative_to(ROOT).as_posix())
    ck("R4 state ended/iters 보존", "ended" in state and "iters" in state)
    ck("R4 accept 주장 일치",
       d["accept_check"].get("state_json_sealed") is True
       and d["accept_check"].get("canonical_record") == CKPT.relative_to(ROOT).as_posix())

    # R5 ------------------------------------------------------------------
    sealed_now, ledger_now = sc.sealed_hash(), sc.ledger_hash()
    ck("R5 봉인 해시 == BOOT", sealed_now == SEAL_BASELINE, sealed_now[:16])
    ck("R5 원장 해시 == BOOT", ledger_now == LEDGER_BASELINE, ledger_now[:16])
    sr = d["seal_reconciliation"]
    ck("R5 result 인용 봉인 해시", sr.get("sealed_sha256") == sealed_now)
    ck("R5 result 인용 원장 해시", sr.get("ledger_sha256") == ledger_now)

    # R6 ------------------------------------------------------------------
    h = d["headline"]
    at = ckpt["artifact_totals"]
    a = ckpt["anchors"]
    ck("R6 artifacts_sealed", h.get("artifacts_sealed") == at["present"] == 63, str(at["present"]))
    ck("R6 result_json_sealed", h.get("result_json_sealed") == at["result_json_count"] == 9)
    ck("R6 files_sealed 합", h.get("files_sealed") == at["present"] + at["result_json_count"] == 72)
    ck("R6 drift 0", h.get("drifted") == at["drifted"] == 0)
    ck("R6 missing 0", h.get("missing") == at["missing"] == 0)
    ck("R6 checkpoint_anchor", h.get("checkpoint_anchor") == a["checkpoint_anchor"])
    ck("R6 artifacts_anchor", h.get("artifacts_anchor") == a["artifacts_anchor"])
    ck("R6 results_anchor", h.get("results_anchor") == a["results_anchor"])
    ck("R6 단계 9개", list(ckpt["stages"]) == seal.STAGE_ORDER == h.get("stages_sealed"))
    ck("R6 전 단계 완료", all(s["status"] == "완료" for s in ckpt["stages"].values()))
    ck("R6 HEAD 커밋 기록", ckpt["head_commit"] == git("rev-parse", ckpt["head_commit"]))

    # R7 ------------------------------------------------------------------
    rebuilt = seal.build()
    ck("R7 재실행 앵커 동일",
       rebuilt["anchors"] == a and rebuilt["artifact_totals"]["drifted"] == 0,
       "멱등")
    ck("R7 재실행 ok", rebuilt["ok"] is True)
    ck("R7 불변 경로 무변경", rebuilt["immutable_paths_dirty"] == [],
       str(rebuilt["immutable_paths_dirty"])[:60])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rendered = tbl.render(ckpt)
    ck("R7 표 md 바이트 일치",
       TABLES.read_text(encoding="utf-8") == rendered,
       f"{len(rendered)} chars")

    # R8 ------------------------------------------------------------------
    nd = " ".join(d["not_done"]) if isinstance(d["not_done"], list) else str(d["not_done"])
    ck("R8 S4 계약 미작성",
       not (ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml").exists()
       and "S4" in nd)
    ck("R8 감독 00:00 체크포인트 미발동",
       not (ROOT / "outputs/timeseries_v12/loop/monday_ckpt.sha256").exists()
       and "monday_ckpt" in nd)
    ck("R8 state.json gitignore 사실",
       "!!" in git("status", "--porcelain", "--ignored", "--", STATE.relative_to(ROOT).as_posix())
       and "gitignore" in nd)
    ck("R8 백로그 대기 3건",
       ckpt["backlog_state"]["pending"] == ["S4-1", "S4-2", "S5-1"])

    fails = [r for r in rows if not r[1]]
    for tag, ok, note in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {tag}" + (f"  — {note}" if note else ""))
    print(f"\n{len(rows) - len(fails)}/{len(rows)} PASS, {len(fails)} FAIL")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
