#!/usr/bin/env python
"""tools/v12_s3_2_result_check.py — S3-2 result JSON 의 자기주장 대사 (읽기 전용).

result JSON 은 사람이 쓴다. 그래서 그 안의 주장을 파일·git·산출 JSON·검증기 출력과 하나씩 맞춘다.

  R1  파싱·필수 키·task_id
  R2  artifacts 의 sha256 이 실제 파일과 일치 (7종)
  R3  인용한 커밋이 실재하고 산출물을 담고 있는지 · 커밋 이후 산출물 무수정
  R4  accept 주장 — 판정서 존재 · 채택 목록이 빈 목록 · '부정 결과' 확정 문장이 판정서에 있는지
  R5  봉인·원장 해시가 BOOT 기준선과 일치
  R6  headline 수치가 s3_verdict.json 필드와 일치 (k_obs·분기·계약 출처 등)
  R7  failure_modes 수치가 판정 JSON 과 일치
  R8  검증기 두 개를 다시 돌려 실패 0 이고, result 가 인용한 항목 수와 같은지
  R9  key_findings·verification 산문의 수치가 판정 JSON 과 일치 (전사 오류 탐지)
  R10 not_done 주장 — S4 계약 미작성·홀드아웃 미계산·src 무변경이 실제로 성립하는지

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s3_2_result_check.py
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_s3_doc_check as dchk   # noqa: E402
import v12_s3_verify as vfy       # noqa: E402
import v12_seal_check as sc       # noqa: E402

RESULT = ROOT / "outputs/timeseries_v12/loop/results/S3-2.json"
DOC = ROOT / "docs/design/v12_s3_verdict.md"
V_REL = "data/timeseries_v12/diagnostics/s3_verdict.json"
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

    def add(cid: str, ok: bool, detail: str) -> None:
        rows.append((cid, bool(ok), detail))

    res = json.loads(RESULT.read_text(encoding="utf-8"))
    v = json.loads((ROOT / V_REL).read_text(encoding="utf-8"))
    doc = DOC.read_text(encoding="utf-8")
    verd, fa = v["verdict"], v["failure_analysis"]

    # ---------------------------------------------------------------- R1
    need = ["task_id", "title", "status", "stage", "artifacts", "accept_check", "headline",
            "seal_reconciliation", "verification", "key_findings", "open_questions",
            "not_done", "next_task"]
    add("R1-a", all(k in res for k in need), f"필수 키 누락 {[k for k in need if k not in res] or '없음'}")
    add("R1-b", res.get("task_id") == "S3-2" and res.get("stage") == "S3",
        f"task_id={res.get('task_id')!r} stage={res.get('stage')!r}")
    add("R1-c", res.get("status") == "완료", f"status={res.get('status')!r}")

    # ---------------------------------------------------------------- R2
    bad = []
    for rel, expect in res["artifacts"].items():
        path = ROOT / rel
        got = sha256(path) if path.exists() else "<없음>"
        if got != expect:
            bad.append(f"{rel}: {got[:10]}≠{expect[:10]}")
    add("R2", not bad, f"artifacts {len(res['artifacts'])}종 sha256 일치"
                       + ("" if not bad else f" · 불일치 {bad}"))

    # ---------------------------------------------------------------- R3
    commit = res["commit"].split()[0]
    subj = git("log", "-1", "--format=%s", commit)
    add("R3-a", subj.startswith("loop(v12): S3-2"), f"{commit} = {subj[:46]}")
    tracked = git("show", "--stat", "--format=", commit)
    add("R3-b", "docs/design/v12_s3_verdict.md" in tracked and "s3_verdict.json" in tracked,
        "커밋이 판정서·판정 JSON 을 담음")
    for rel in ("docs/design/v12_s3_verdict.md", V_REL):
        add(f"R3-c {rel.split('/')[-1][:12]}",
            git("rev-parse", f"{commit}:{rel}") == git("hash-object", rel),
            "커밋본 blob = 작업본 (커밋 이후 무수정)")

    # ---------------------------------------------------------------- R4
    acc = res["accept_check"]
    add("R4-a", DOC.exists() and acc["artifact_path"] == "docs/design/v12_s3_verdict.md",
        "spec 이 지목한 판정서 존재")
    add("R4-b", acc["adopted_cells_list"] == [] == verd["adopted_cells"]
        and acc["adopted_count"] == verd["adopted_count"] == 0,
        f"채택 목록 = 빈 목록 (adopted_count={acc['adopted_count']})")
    add("R4-c", acc["verdict_line"].replace("−", "-") in doc.replace("−", "-"),
        "판정 문장이 판정서에 실재")
    add("R4-d", acc["delivered"] == "부정 결과" and verd["decision_code"] == "NEGATIVE_RESULT",
        f"accept 두 갈래 중 '{acc['delivered']}' 로 확정")

    # ---------------------------------------------------------------- R5
    seal_now, ledger_now = sc.sealed_hash(), sc.ledger_hash()
    sr = res["seal_reconciliation"]
    add("R5-a", seal_now == sr["sealed_sha256"] == SEAL_BASELINE, f"봉인 {seal_now[:8]}…")
    add("R5-b", ledger_now == sr["ledger_sha256"] == LEDGER_BASELINE, f"원장 {ledger_now[:8]}…")
    protected = git("status", "--porcelain", "--", "forecasts", "calibration", "src",
                    "data/timeseries_v8", "data/timeseries_v2", "questions")
    add("R5-c", protected == "", f"보호 경로 {'무변경' if protected == '' else protected[:50]}")

    # ---------------------------------------------------------------- R6
    hl = res["headline"]
    add("R6-a", hl["adopted_cells"] == verd["adopted_count"] == 0, f"채택 {hl['adopted_cells']}")
    add("R6-b", hl["k_obs"] == verd["k_obs"] == 0, f"k_obs {hl['k_obs']}")
    add("R6-c", hl["governing_branch"] == verd["governing_branch"] == "T5_fail",
        f"지배 분기 {hl['governing_branch']}")
    add("R6-d", sorted(hl["branches_fired"]) == sorted(verd["branches_fired"]),
        f"동시 발동 {hl['branches_fired']}")
    add("R6-e", hl["s4_contract_source"].startswith(verd["s4_contract_source"]),
        f"계약 출처 {verd['s4_contract_source']}")
    add("R6-f", hl["directions_with_lower_gt_0"] == fa["by_failure_mode"]["하한>0"] == 0,
        "하한>0 방향 0")
    add("R6-g", hl["decision"] == verd["decision"] and hl["two_paths_converge"] == verd["converges"],
        f"decision={hl['decision']}")

    # ---------------------------------------------------------------- R7
    fm = res["failure_modes"]
    add("R7-a", (fm["lower_lt_0"], fm["lower_eq_0"], fm["lower_gt_0"])
        == (fa["by_failure_mode"]["하한<0"], fa["by_failure_mode"]["하한=0"],
            fa["by_failure_mode"]["하한>0"]),
        f"{fm['lower_lt_0']}/{fm['lower_eq_0']}/{fm['lower_gt_0']}")
    add("R7-b", fm["inconclusive_by_mde_directions"] == fa["inconclusive_by_mde_directions"]
        and fm["inconclusive_by_mde_cells"] == fa["inconclusive_by_mde_cells"],
        f"|Δ|<MDE {fm['inconclusive_by_mde_directions']}/16")
    add("R7-c", fm["a2_pass_directions"] == fa["a2_pass_directions"]
        and fm["a2_pass_cells"] == fa["a2_pass_cells"], f"A2 {fm['a2_pass_directions']}/16")
    add("R7-d", len(fm["degenerate_directions"]) == fa["by_failure_mode"]["하한=0"],
        f"퇴화 {len(fm['degenerate_directions'])} 방향")

    # ---------------------------------------------------------------- R8
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_v = vfy.main()
    tail = buf.getvalue().strip().splitlines()[-1]
    m = re.search(r"(\d+) 항목 · 실패 (\d+)", tail)
    n_items, n_fail = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)
    add("R8-a", rc_v == 0 and n_fail == 0, f"v12_s3_verify {tail}")
    add("R8-b", res["verification"]["total"] == f"{n_items}항목 전부 PASS",
        f"result 가 적은 항목 수 = {n_items}")
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        rc_d = dchk.main()
    add("R8-c", rc_d == 0 and "ALL PASS" in buf2.getvalue(), "v12_s3_doc_check ALL PASS")

    # ---------------------------------------------------------------- R9 산문 수치
    blob = json.dumps(res, ensure_ascii=False)
    dirs = {(d["hypothesis_id"], d["horizon"], d["direction"]): d for d in v["directions"]}
    needles = [
        ("T3 h21 상한", f"{dirs[('T3', 21, 'early_to_late')]['ci90_upper']:+.6f}"),
        ("T3 h63 상한", f"{dirs[('T3', 63, 'early_to_late')]['ci90_upper']:+.6f}"),
        ("가장 가까운 방향", f"{dirs[('T1', 63, 'early_to_late')]['shortfall_share_of_brier']:.2%}"),
        ("가장 먼 방향", f"{dirs[('T1', 63, 'late_to_early')]['shortfall_share_of_brier']:.2%}"),
        ("k_mean", str(v["multiplicity"]["k_mean"])),
        ("T1_h21 귀무", f"{v['null_liberality']['cell_pass_rate']['T1_h21']:.3f}"),
        ("T4_h63 귀무", f"{v['null_liberality']['cell_pass_rate']['T4_h63']:.3f}"),
        ("전→후 Δ h21", f"{dirs[('T1', 21, 'early_to_late')]['delta']:+.6f}"),
        ("전→후 Δ h63", f"{dirs[('T1', 63, 'early_to_late')]['delta']:+.6f}"),
    ]
    for label, needle in needles:
        add(f"R9 {label}", needle.replace("−", "-") in blob.replace("−", "-"), f"'{needle}'")
    add("R9 관대셀수", f"관대한 셀 {len(v['null_liberality']['liberal_cells'])} 개" in blob
        or f"관대 {len(v['null_liberality']['liberal_cells'])} 셀" in blob
        or f"셀 {len(v['null_liberality']['liberal_cells'])} 개" in blob,
        f"관대 {len(v['null_liberality']['liberal_cells'])} 셀 표기")

    # ---------------------------------------------------------------- R10
    add("R10-a", not (ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml").exists(),
        "S4 계약 draft 미작성 주장 성립")
    lines_2015 = [ln for ln in doc.splitlines() if "2015" in ln]
    add("R10-b", all("미계산" in ln or "봉인창" in ln for ln in lines_2015),
        f"판정서의 2015 언급 {len(lines_2015)} 줄 전부 미계산 문맥")
    add("R10-c", git("status", "--porcelain", "--", "src") == "", "src/ 무변경 주장 성립")
    add("R10-d", res["next_task"] == "S4-1", f"next_task={res['next_task']!r}")

    # ---------------------------------------------------------------- 출력
    failed = [cid for cid, ok, _ in rows if not ok]
    for cid, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {cid:<18} {detail}")
    print(f"\n{len(rows)} 항목 · 실패 {len(failed)}" + (f" → {failed}" if failed else " · ALL PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
