#!/usr/bin/env python
"""tools/v12_s5_result_check.py — S5-1 result JSON 자기주장 대사 (읽기 전용).

이 파일이 검사하는 대상은 `outputs/timeseries_v12/loop/results/S5-1.json` 이 **적은 모든 주장**이다.
result JSON 은 사람이 쓰는 마지막 문서라 전사 오류가 들어갈 유일한 자리다. 그래서 그 값을
파일·git·재실행 출력과 맞춘다.

  R1  산출물 해시 10종 + 재생성물 해시가 실측과 일치하고, 전부 커밋에 실렸는가.
  R2  봉인·원장이 실측 = 선언 = BOOT 기준선인가. 불변 경로 청결.
  R3  headline 수치가 final_report.json 과 일치하는가 (24종).
  R4  accept 주장 — 보고서 실재·커밋 blob 동일·spec 5항목 매핑 존재.
  R5  inventory 주장 — inventory_result.json 과 값 일치, 갱신 파일 1건, 생성물 3종 중 2종 무변경.
  R6  PR 무접촉 — 이 브랜치에 push 흔적이 없고 PR 초안만 있는가.
  R7  커밋 후 루프 범위 재계수 (보고서 표 K 의 렌더 시점 값과 구분해 기록).
  R8  doc_check 재실행 — 29항목 실패 0, 그룹별 항목 수 역검증.
  R9  not_done·open_questions 주장 — 수집 건수가 final_report 와 일치.
  R10 금지 verb — S5 스크립트의 실행 토큰·호출 인자에 CLI 하위명령 0건.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_result_check.py
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import runpy
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_seal_check as sc  # noqa: E402

RESULT = ROOT / "outputs/timeseries_v12/loop/results/S5-1.json"
REPORT = ROOT / "data/timeseries_v12/reports/final_report.json"
INVENTORY = ROOT / "data/timeseries_v12/reports/inventory_result.json"
DOC = ROOT / "docs/review/SUNDAY_LOOP_FINAL_REPORT.md"

IMMUTABLE_PATHS = ["forecasts", "calibration", "src",
                   "data/timeseries_v8", "data/timeseries_v2", "questions"]

# 루프 헌법 §1 이 금지한 verb — dev-backtest·holdout·sealed·refresh·push.
# (`sync`·`inventory` 는 금지 목록에 없다. envelope 가 inventory 를 지시했고 그 내부가 sync 를 부른다.)
FORBIDDEN_VERBS = ["dev-backtest", "holdout", "sealed", "refresh", "push"]

# 텍스트 매칭은 두 방향으로 헛돈다.
#   과탐: `Path.resolve()`·`ingest.sync()`·경로 문자열 "…/holdout" 을 스스로 적발한다
#         (S3-2 가 기록한 실패 양상).
#   자기적발: 검사기 자신의 주석·대조 문자열에 'git push' 가 들어 있어 스스로를 잡는다.
# 그래서 **AST 의 호출 노드만** 본다 — 실제로 실행되는 형태만 남기고 주석·설명 문자열·
# 대조 상수는 구조적으로 제외된다.
_INVOKE_RE = re.compile(r"(?:-m\s+ai_fc|ai-fc)\s+([A-Za-z][A-Za-z0-9_-]*)")

# 검사가 헛돌지 않음을 보이는 음성 대조 — 아래 소스는 실제 실행 형태 2종을 담는다.
VERB_NEGATIVE_CONTROL_SRC = (
    'subprocess.run(["python", "-m", "ai_fc", "dev-backtest", "--x"])\n'
    'git("push", "origin", "HEAD")\n'
)
# 반대 방향 대조 — 실행이 아닌 것들. 하나라도 잡히면 과탐이다.
VERB_FALSE_POSITIVE_CONTROL_SRC = (
    'ROOT = Path(__file__).resolve().parents[1]\n'
    'report = ingest.sync(conn, root, strict=True)\n'
    'p = ROOT / "data/timeseries_v12/holdout"\n'
    'note = "이 루프는 dev-backtest 를 실행하지 않는다"\n'
)


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


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, bool(ok), detail))

    S = json.loads(RESULT.read_text(encoding="utf-8"))
    R = json.loads(REPORT.read_text(encoding="utf-8"))
    INV = json.loads(INVENTORY.read_text(encoding="utf-8"))

    # ── R1 산출물 해시 ──────────────────────────────────────────────
    commit = S["commit_sha"]
    committed_files = set(git("show", "--pretty=", "--name-only", commit).splitlines())
    for rel, declared in S["artifacts"].items():
        actual = sha256_file(ROOT / rel)
        add(f"R1-{Path(rel).name}", actual == declared,
            f"{rel} 선언={declared[:12]}… 실측={(actual or '없음')[:12]}…")
    add("R1-count", len(S["artifacts"]) == 10, f"산출물 선언 {len(S['artifacts'])}종")
    add("R1-committed", all(rel in committed_files for rel in S["artifacts"]),
        f"산출물 10종 전부 커밋 {commit[:8]} 에 포함")
    regen = S["regenerated_not_authored"]
    rel_regen = "docs/generated/inventory.generated.md"
    add("R1-regen", sha256_file(ROOT / rel_regen) == regen[rel_regen] and rel_regen in committed_files,
        "재생성물 해시 일치 + 같은 커밋에 포함")
    add("R1-clean", not [l for l in git("status", "--porcelain", "--",
                                        *S["artifacts"], rel_regen).splitlines() if l.strip()],
        "선언 산출물의 워킹트리 미커밋 변경 0")

    # ── R2 봉인 ─────────────────────────────────────────────────────
    sealed, ledger = sc.sealed_hash(), sc.ledger_hash()
    sr = S["seal_reconciliation"]
    base = (ROOT / "outputs/timeseries_v12/loop/sealed_baseline.hash").read_text().strip()
    lbase = (ROOT / "outputs/timeseries_v12/loop/ledger_baseline.hash").read_text().strip()
    add("R2-a", sealed == sr["sealed_sha256"] == base, f"봉인 {sealed[:12]}… = 선언 = 기준선")
    add("R2-b", ledger == sr["ledger_sha256"] == lbase, f"원장 {ledger[:12]}… = 선언 = 기준선")
    dirty = [l for l in git("status", "--porcelain", "--", *IMMUTABLE_PATHS).splitlines() if l.strip()]
    add("R2-c", not dirty, f"불변 경로 변경 {len(dirty)}건")

    # ── R3 headline ─────────────────────────────────────────────────
    H = S["headline"]
    ai = R["artifact_inventory"]
    expect = {
        "loop_tasks": R["loop"]["tasks_total"],
        "tasks_completed": R["loop"]["status_counts"]["완료"],
        "tasks_partial": R["loop"]["status_counts"]["부분완료"],
        "tasks_blocked": R["loop"]["status_counts"]["차단"],
        "forbidden_verbs_executed_total": R["loop"]["forbidden_verbs_executed_total"],
        "backtests_run": R["loop"]["backtests_run"],
        "holdout_touched": R["loop"]["holdout_touched"],
        "upstream_artifacts_rehashed": ai["declared_artifacts"],
        "result_json_count": ai["result_json_count"],
        "files_rehashed_total": ai["files_total"],
        "drift": len(ai["drifted"]),
        "missing": len(ai["missing"]),
        "loop_anchor": ai["anchors"]["loop_anchor"],
        "artifacts_anchor": ai["anchors"]["artifacts_anchor"],
        "results_anchor": ai["anchors"]["results_anchor"],
        "ckpt_anchor_reproduced": R["ckpt_reproduction"]["checkpoint_anchor_match"],
        "decisions_tabled": [d["id"] for d in R["decisions"]],
        "not_done_collected": R["incomplete"]["not_done_total"],
        "not_done_excluding_followup": R["incomplete"]["not_done_total"] - R["incomplete"]["followup"]["total"],
        "open_questions_collected": R["incomplete"]["open_questions_total"],
        "open_questions_distinct": R["incomplete"]["open_questions_distinct"],
        "unverified_flagged_in_open_questions": R["incomplete"]["unverified_flagged"],
        "gates_armed": R["stage_findings"]["S4"]["gates_armed"],
        "candidates_created": R["stage_findings"]["S4"]["evaluated_candidates"],
    }
    for key, want in expect.items():
        add(f"R3-{key}", H[key] == want, f"{key}: 선언 {H[key]!r} vs 원천 {want!r}")
    add("R3-inputs", S["inputs"]["upstream_artifacts_rehashed"] == ai["declared_artifacts"]
        and S["inputs"]["upstream_drift"] == len(ai["drifted"])
        and S["inputs"]["upstream_missing"] == len(ai["missing"]),
        "inputs 절의 재해시·drift·missing 이 산출 JSON 과 일치")
    add("R3-run", S["inputs"]["run_sha256"] == R["provenance"]["run_sha256"], "V8 run 해시 일치")

    # ── R4 accept ───────────────────────────────────────────────────
    add("R4-a", DOC.is_file() and S["accept_check"]["artifact_path"] == "docs/review/SUNDAY_LOOP_FINAL_REPORT.md",
        "spec 지정 경로에 보고서 실재")
    blob = git("rev-parse", f"{commit}:docs/review/SUNDAY_LOOP_FINAL_REPORT.md")
    worktree_blob = git("hash-object", "docs/review/SUNDAY_LOOP_FINAL_REPORT.md")
    add("R4-b", blob and blob == worktree_blob, f"커밋본 blob {blob[:8]}… = 작업본 (커밋 후 무수정)")
    add("R4-c", len(S["accept_check"]["spec_items_delivered"]) == 5, "spec 5항목 매핑 존재")
    add("R4-d", S["status"] == "완료" and S["headline"]["tasks_completed"] == 13,
        "상태 완료 · 13/13")

    # ── R5 inventory ────────────────────────────────────────────────
    ir = S["inventory_result"]
    add("R5-a", ir["sync_ok"] == INV["sync"]["ok"] and ir["sync_errors"] == len(INV["sync"]["errors"])
        and ir["sync_warnings"] == len(INV["sync"]["warnings"]), "sync 상태·경고 수 일치")
    add("R5-b", ir["files_changed"] == INV["files_changed"] and len(INV["files_changed"]) == 1,
        f"갱신 파일 {INV['files_changed']}")
    add("R5-c", ir["was_current_before_run"] == INV["was_current_before_run"]
        and ir["is_current_after_run"] == INV["is_current_after_run"], "실행 전/후 최신 여부 일치")
    add("R5-d", not INV["files"]["docs/generated/licenses.generated.md"]["changed"]
        and not INV["files"]["docs/generated/read_model_v2.schema.json"]["changed"]
        and ir["license_manifest_changed"] is False and ir["read_model_schema_changed"] is False,
        "라이선스 매니페스트·read-model 스키마 무변경")
    add("R5-e", ir["immutable_paths_dirty_after"] == len(INV["immutable_paths"]["dirty_after"]) == 0,
        "inventory 실행이 불변 경로를 건드리지 않음")
    add("R5-f", INV["snapshot"]["contracts"] == 54 and "53 → 54" in ir["change_content"],
        f"계약 수 {INV['snapshot']['contracts']} — 서술과 일치")
    add("R5-g", INV["snapshot"]["source_fingerprint"] in R["inventory"]["snapshot"]["source_fingerprint"],
        "fingerprint 가 최종 보고 산출 JSON 과 동일")

    # ── R6 PR 무접촉 ────────────────────────────────────────────────
    pr = S["pr_preparation"]
    add("R6-a", (ROOT / pr["pr_body_draft"]).is_file(), "PR 본문 초안 실재")
    add("R6-b", pr["pushed"] is False and pr["pr_opened"] is False and pr["remote_contacted"] is False,
        "push·PR 생성·원격 접촉 전부 False 로 선언")
    upstream = git("rev-parse", "--abbrev-ref", "HEAD@{upstream}")
    ahead = git("rev-list", "--count", f"{upstream}..HEAD") if upstream else ""
    add("R6-c", (not upstream) or (ahead.isdigit() and int(ahead) > 0),
        f"원격 추적 {upstream or '없음'} · 미푸시 커밋 {ahead or 'n/a'} (푸시했다면 0 이어야 한다)")
    add("R6-d", pr["branch"] == git("branch", "--show-current"), "브랜치 이름 일치")

    # ── R7 커밋 후 루프 범위 재계수 ─────────────────────────────────
    rng = R["pr"]["loop_range"]
    now_commits = len([l for l in git("log", "--format=%h", rng).splitlines() if l])
    now_files = len([l for l in git("diff", "--name-only", rng.replace("..", "...")).splitlines() if l])
    add("R7-a", now_commits >= pr["loop_commits_at_report_render"],
        f"커밋 후 루프 커밋 {now_commits} ≥ 렌더 시점 {pr['loop_commits_at_report_render']}")
    add("R7-b", now_files >= pr["loop_files_changed_at_report_render"],
        f"커밋 후 루프 파일 {now_files} ≥ 렌더 시점 {pr['loop_files_changed_at_report_render']}")
    add("R7-c", any("표 K" in s and "렌더 시점" in s for s in S["known_staleness"]),
        "렌더 시점 값과의 차이를 known_staleness 가 공시")

    # ── R8 doc_check 재실행 ─────────────────────────────────────────
    buf = io.StringIO()
    argv = sys.argv[:]
    try:
        sys.argv = ["tools/v12_s5_doc_check.py"]
        with redirect_stdout(buf):
            try:
                runpy.run_path(str(ROOT / "tools/v12_s5_doc_check.py"), run_name="__main__")
            except SystemExit as exc:
                rc = exc.code or 0
    finally:
        sys.argv = argv
    out = buf.getvalue()
    n_pass = out.count("PASS  ")
    n_fail = out.count("FAIL  ")
    add("R8-a", rc == 0 and n_fail == 0, f"doc_check 재실행 실패 {n_fail}건")
    add("R8-b", n_pass == S["headline"]["doc_check_items"] == S["headline"]["doc_check_pass"] == 29,
        f"항목 수 {n_pass} = 선언 {S['headline']['doc_check_items']}")
    groups = {g: len(re.findall(rf"  {g}-", out)) for g in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]}
    declared = {g: int(re.search(r"(\d+)항목", S["verification"][g]).group(1)) for g in groups}
    add("R8-c", groups == declared, f"그룹별 항목 수 재계수 {groups} vs 선언 {declared}")

    # ── R9 미완 주장 ────────────────────────────────────────────────
    add("R9-a", S["headline"]["not_done_collected"] == R["incomplete"]["not_done_total"],
        "not_done 수집 건수 일치")
    add("R9-b", len(S["not_done"]) >= 8 and len(S["open_questions"]) >= 5,
        f"이 태스크의 not_done {len(S['not_done'])}건 · open_questions {len(S['open_questions'])}건")
    add("R9-c", sum(1 for q in S["open_questions"] if "[미검증]" in q or "[미확정]" in q or "[미해소]" in q
                    or "[부분 미검증]" in q) >= 4,
        "미결 표기가 붙은 open_question 4건 이상")

    # ── R10 금지 verb ───────────────────────────────────────────────
    def _str_args(call: ast.Call) -> list[str]:
        out: list[str] = []
        for node in call.args:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append(node.value)
            elif isinstance(node, (ast.List, ast.Tuple)):
                out += [e.value for e in node.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return out

    def scan_verbs(source: str, label: str) -> list[str]:
        found: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            args = _str_args(node)
            if not args:
                continue
            # (a) 인자 목록에 ai_fc 와 금지 verb 가 함께 실린 실행
            if "ai_fc" in args or "ai-fc" in args:
                for verb in args:
                    if verb in FORBIDDEN_VERBS:
                        found.append(f"{label}:{node.lineno} ai_fc {verb}")
            # (b) 한 문자열 안에 실행 형태가 통째로 실린 경우
            for arg in args:
                for verb in _INVOKE_RE.findall(arg):
                    if verb in FORBIDDEN_VERBS:
                        found.append(f"{label}:{node.lineno} '{arg[:40]}'")
            # (c) git push
            if args and args[0] == "push":
                found.append(f"{label}:{node.lineno} git push")
            if "git" in args and "push" in args:
                found.append(f"{label}:{node.lineno} git push (인자 목록)")
        return found

    hits: list[str] = []
    scanned = 0
    for path in sorted(ROOT.glob("tools/v12_s5_*.py")):
        scanned += 1
        hits += scan_verbs(path.read_text(encoding="utf-8"), path.name)
    add("R10-a", not hits, f"S5 스크립트 {scanned}개의 호출 노드에 금지 verb {len(hits)}건: {hits[:3] or '없음'}")
    add("R10-b", S["forbidden_verbs_executed"] == [], "금지 verb 실행 목록 비어 있음")
    add("R10-c", len(scan_verbs(VERB_NEGATIVE_CONTROL_SRC, "control")) == 2,
        "음성 대조 — 실제 실행 형태 2종은 같은 검사에서 적발된다")
    fp = scan_verbs(VERB_FALSE_POSITIVE_CONTROL_SRC, "control")
    add("R10-d", not fp,
        f"과탐 대조 — resolve()·sync()·경로 문자열·산문 언급은 적발되지 않는다 (적발 {len(fp)})")

    failed = [c for c in checks if not c[1]]
    for cid, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {cid}  {detail}")
    print(f"\n금지 verb 정본: {FORBIDDEN_VERBS} — AST 호출 노드만 검사(주석·설명 문자열 제외)")
    print(f"총 {len(checks)}항목 · 실패 {len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
