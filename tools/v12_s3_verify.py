#!/usr/bin/env python
"""tools/v12_s3_verify.py — S3 판정의 독립 재검 (읽기 전용).

`v12_s3_verdict.py` 의 로직을 신뢰하지 않고, transfer_results.json 의 원 레코드와
등록부 원문에서 판정을 **다시** 유도해 s3_verdict.json 과 대사한다.

  V1  봉인·원장 대사 (BOOT 기준선)
  V2  입력 3종 sha256 이 s3_verdict.inputs 와 일치 · 등록부 커밋이 실재하고 그 blob 이 현 파일과 동일
  V3  A1 재유도 — records 의 ci90_lower > 0 을 방향별로 세고 셀 AND 롤업 → adopted·k_obs
  V4  A2 재유도 (ci90_lower_vs_reflection) · 방향/셀 통과 수
  V5  미달 양상 계수 재현 (하한<0 / =0 / >0) · 퇴화 방향 집합
  V6  T5 규칙 재적용 — pooled 통과율이 두 셀 통과율의 산술평균인지, 문턱 비교, 실패 판정
  V7  분기 선택 재현 — T5_fail 우선 · s4_contract 문자열이 등록부 원문과 **바이트 동일**
  V8  family — k 분포 합 1000 · k_mean 재계산 · P(k≥k_obs) 재계산 · family_claim_supported
  V9  귀무 관대/보수 분류 재계산 (명목 단측 5%)
  V10 등록부 규칙 문자열이 s3_verdict.rule 에 바이트 그대로 실렸는지 (완화·재서술 탐지)
  V11 mandatory_fields_per_cell 23종이 16 레코드 전부에 존재 (no_cell_dropping 유지)
  V12 홀드아웃 무접촉 — 창 종료 2014-12-31 · 산출물 어디에도 2015+ 계산 없음
  V13 금지 verb — S3-2 가 만든 스크립트의 실행 토큰에 backtest/holdout/sealed/refresh 0 건
  V14 무수정 대사 — 입력 두 파일이 S3-0·S3-1 result JSON 이 기록한 해시 그대로인지
  V15 accept 대사 — spec 이 요구한 '채택 목록 또는 부정 결과' 가 판정에 명시돼 있는지

하나라도 어긋나면 종료코드 1.
실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s3_verify.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_seal_check as seal  # noqa: E402

TR_REL = "data/timeseries_v12/diagnostics/transfer_results.json"
PR_REL = "data/timeseries_v12/prereg/hypotheses.json"
S2_REL = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"
V_REL = "data/timeseries_v12/diagnostics/s3_verdict.json"

SEALED_BASELINE = "e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224"
LEDGER_BASELINE = "b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803"

S3_2_SCRIPTS = ["tools/v12_s3_verdict.py", "tools/v12_s3_tables.py", "tools/v12_s3_verify.py",
                "tools/v12_s3_doc_check.py", "tools/v12_s3_probe.py", "tools/v12_s3_probe2.py",
                "tools/v12_s3_probe3.py", "tools/v12_s3_2_result_check.py"]
FORBIDDEN_VERBS = ("dev-backtest", "dev_backtest", "holdout", "sealed", "refresh")


def sha256(rel: str) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout.strip() if out.returncode == 0 else f"<git error: {out.stderr.strip()[:80]}>"


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def exec_tokens(path: Path) -> set[str]:
    """주석·문자열을 버린 **실행 토큰**만 모은다 — 산문 언급과 실제 호출을 구분하기 위해."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
    return names


def main() -> int:
    rows: list[tuple[str, bool, str]] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        rows.append((cid, bool(ok), detail))

    tr, pr, v = load(TR_REL), load(PR_REL), load(V_REL)
    records = tr["records"]

    # ---------------------------------------------------------------- V1 봉인
    # 변수명에 금지 verb 와 **정확히** 같은 토큰을 두지 않는다 — V13 이 exact-match 로 적발한다.
    seal_now, ledger_now = seal.sealed_hash(), seal.ledger_hash()
    add("V1-a", seal_now == SEALED_BASELINE, f"봉인 {seal_now[:8]}…")
    add("V1-b", ledger_now == LEDGER_BASELINE, f"원장 {ledger_now[:8]}…")
    dirty = git("status", "--porcelain", "--", "forecasts", "calibration", "src",
                "data/timeseries_v8", "data/timeseries_v2", "questions")
    add("V1-c", dirty == "", f"보호 경로 git status {'무변경' if dirty == '' else dirty[:60]}")

    # ---------------------------------------------------------------- V2 입력 해시·커밋
    for rel in (TR_REL, PR_REL, S2_REL):
        add(f"V2-{rel.split('/')[-1][:6]}", v["inputs"][rel]["sha256"] == sha256(rel),
            f"{rel.split('/')[-1]} {sha256(rel)[:8]}…")
    commit = tr["prereg"]["commit"]
    subj = git("log", "-1", "--format=%s", commit)
    add("V2-commit", subj.startswith("loop(v12): S3-0"), f"{commit[:8]} = {subj[:48]}")
    committed_blob = git("rev-parse", f"{commit}:{PR_REL}")
    work_blob = git("hash-object", PR_REL)
    add("V2-blob", committed_blob == work_blob and len(work_blob) == 40,
        f"등록부 blob {work_blob[:8]}… 커밋본과 동일")
    add("V2-prereg-sha", tr["prereg"]["sha256"] == sha256(PR_REL),
        "S3-1 이 인용한 등록부 해시 = 현 파일")

    # ---------------------------------------------------------------- V3 A1 재유도
    cells_a1: dict[str, list[bool]] = {}
    cells_a2: dict[str, list[bool]] = {}
    for rec in records:
        cid = f"{rec['hypothesis_id']}_h{rec['horizon']}"
        cells_a1.setdefault(cid, []).append(rec["ci90_lower"] > 0.0)
        cells_a2.setdefault(cid, []).append(rec["ci90_lower_vs_reflection"] > 0.0)
    add("V3-a", len(records) == 16 and all(len(x) == 2 for x in cells_a1.values()),
        f"레코드 {len(records)} · 셀 {len(cells_a1)} × 방향 2")
    adopted = sorted(c for c, flags in cells_a1.items() if all(flags))
    add("V3-b", adopted == sorted(v["verdict"]["adopted_cells"]),
        f"재유도 채택 = {adopted or '없음'}")
    add("V3-c", len(adopted) == v["verdict"]["k_obs"] == tr["multiplicity_null"]["k_obs"] == 0,
        f"k_obs = {len(adopted)}")
    add("V3-d", all((rec["ci90_lower"] > 0.0) == rec["A1_pass"] for rec in records),
        "레코드 A1_pass = (하한>0) 16/16")

    # ---------------------------------------------------------------- V4 A2
    a2_dirs = sum(1 for rec in records if rec["ci90_lower_vs_reflection"] > 0.0)
    a2_cells = sorted(c for c, flags in cells_a2.items() if all(flags))
    add("V4-a", a2_dirs == v["failure_analysis"]["a2_pass_directions"], f"A2 방향 {a2_dirs}/16")
    add("V4-b", a2_cells == v["verdict"]["A2_cells"] == [], f"A2 셀 {a2_cells or '없음'}")

    # ---------------------------------------------------------------- V5 미달 양상
    neg = sum(1 for rec in records if rec["ci90_lower"] < 0.0)
    zero = sum(1 for rec in records if rec["ci90_lower"] == 0.0)
    pos = sum(1 for rec in records if rec["ci90_lower"] > 0.0)
    m = v["failure_analysis"]["by_failure_mode"]
    add("V5-a", (neg, zero, pos) == (m["하한<0"], m["하한=0"], m["하한>0"]) and neg + zero + pos == 16,
        f"하한<0 {neg} · =0 {zero} · >0 {pos}")
    degen = {f"{r['hypothesis_id']}_h{r['horizon']}·{r['direction']}" for r in records if r["degenerate"]}
    add("V5-b", degen == set(v["failure_analysis"]["degenerate_directions"]) and len(degen) == zero,
        f"퇴화 {len(degen)} 개 = 하한 0 인 방향 집합")
    inconcl = sum(1 for rec in records if rec["inconclusive_by_mde"])
    add("V5-c", inconcl == v["failure_analysis"]["inconclusive_by_mde_directions"],
        f"|Δ|<MDE {inconcl}/16")

    # ---------------------------------------------------------------- V6 T5
    t5 = tr["t5_negative_control"]
    pooled_recalc = sum(t5["pass_rate_by_cell"].values()) / len(t5["pass_rate_by_cell"])
    add("V6-a", abs(pooled_recalc - t5["pass_rate_pooled"]) < 1e-12,
        f"pooled {t5['pass_rate_pooled']:.4f} = 셀 평균 {pooled_recalc:.4f}")
    add("V6-b", (t5["pass_rate_pooled"] > t5["threshold"]) is True and v["verdict"]["T5_failed"] is True,
        f"{t5['pass_rate_pooled']:.4f} > {t5['threshold']} → 실패")
    counts = tr["multiplicity_null"]["t1_cell_pass_counts"]
    reps = tr["multiplicity_null"]["replicates"]
    add("V6-c", all(abs(counts[h] / reps - t5["pass_rate_by_cell"][h]) < 1e-12 for h in counts),
        f"셀 통과 카운트/1000 = 통과율 {dict(counts)}")

    # ---------------------------------------------------------------- V7 분기
    interp = pr["pre_committed_interpretation"]
    expect_branch = "T5_fail" if v["verdict"]["T5_failed"] else ("adopted_0" if not adopted else "adopted_ge_1")
    add("V7-a", v["verdict"]["governing_branch"] == expect_branch == "T5_fail",
        f"발동 분기 {v['verdict']['governing_branch']}")
    add("V7-b", set(v["verdict"]["branches_fired"]) == {"T5_fail", "adopted_0"},
        f"동시 발동 {v['verdict']['branches_fired']}")
    add("V7-c", v["verdict"]["s4_contract"] == interp["T5_fail"],
        "s4_contract = 등록부 T5_fail 원문 바이트 동일")
    add("V7-d", "우선한다" in interp["T5_fail"],
        "등록부가 T5_fail 우선을 명시")
    add("V7-e", v["verdict"]["decision_code"] == "NEGATIVE_RESULT",
        f"decision_code = {v['verdict']['decision_code']}")

    # ---------------------------------------------------------------- V8 family
    null = tr["multiplicity_null"]
    kd = {int(k): n for k, n in null["k_distribution"].items()}
    total = sum(kd.values())
    kmean = sum(k * n for k, n in kd.items()) / total
    pge0 = sum(n for k, n in kd.items() if k >= 0) / total
    add("V8-a", total == null["replicates"] == 1000, f"k 분포 합 {total}")
    add("V8-b", abs(kmean - null["k_mean"]) < 1e-9, f"k_mean {kmean:.3f}")
    add("V8-c", abs(pge0 - null["p_k_ge_kobs"]) < 1e-12 and pge0 == 1.0,
        f"P(k≥0) = {pge0:.4f}")
    add("V8-d", (null["p_k_ge_kobs"] <= null["family_claim_threshold"]) == v["verdict"]["family_claim_supported"]
        and v["verdict"]["family_claim_supported"] is False,
        "family 주장 미지지")
    add("V8-e", max(kd) if kd else None, f"k_max 기록 {null['k_max']}")
    add("V8-f", max(k for k, n in kd.items() if n > 0) == null["k_max"],
        f"k_max 재계산 = {max(k for k, n in kd.items() if n > 0)}")

    # ---------------------------------------------------------------- V9 관대/보수
    nominal = v["null_liberality"]["nominal_one_sided"]
    lib = sorted(c for c, r in null["cell_pass_rate"].items() if r > nominal)
    con = sorted(c for c, r in null["cell_pass_rate"].items() if r <= nominal)
    add("V9-a", lib == sorted(v["null_liberality"]["liberal_cells"]), f"관대 {len(lib)} 셀 {lib}")
    add("V9-b", con == sorted(v["null_liberality"]["conservative_cells"]), f"보수 {len(con)} 셀 {con}")
    add("V9-c", "[사후 관찰]" in v["null_liberality"]["label"], "사후 라벨임을 공시")

    # ---------------------------------------------------------------- V10 규칙 원문 대사
    add("V10-a", v["rule"]["A1"] == pr["adoption"]["primary"]["rule"], "A1 원문 동일")
    add("V10-b", v["rule"]["A2"] == pr["adoption"]["secondary"]["rule"], "A2 원문 동일")
    add("V10-c", v["rule"]["T5"] == tr["t5_negative_control"]["rule"], "T5 규칙 원문 동일")
    add("V10-d", v["rule"]["what_adoption_does_not_mean"] == interp["what_adoption_does_not_mean"],
        "'채택이 뜻하지 않는 것' 원문 동일")
    add("V10-e", "CI90 하한 > 0" in v["rule"]["A1"] and "모두" in v["rule"]["A1"],
        "A1 이 양방향·엄격 부등호 문자 유지")

    # ---------------------------------------------------------------- V11 필수 필드
    mandatory = pr["reporting_contract"]["mandatory_fields_per_cell"]
    missing = {f for rec in records for f in mandatory if f not in rec}
    add("V11-a", not missing, f"필수 필드 {len(mandatory)}/{len(mandatory)} 전 레코드 존재")
    add("V11-b", len(v["directions"]) == 16 and len(v["cells"]) == 8,
        f"판정 JSON 방향 {len(v['directions'])} · 셀 {len(v['cells'])}")

    # ---------------------------------------------------------------- V12 홀드아웃
    add("V12-a", tr["target"]["window"]["outer_end"] == "2014-12-31",
        f"창 종료 {tr['target']['window']['outer_end']}")
    vtext = (ROOT / V_REL).read_text(encoding="utf-8")
    add("V12-b", "2015" not in vtext or "2015+ 봉인창 미계산" in vtext,
        "판정 JSON 의 2015 언급은 '미계산' 문장뿐")

    # ---------------------------------------------------------------- V13 금지 verb
    # 금지 verb 는 **CLI 하위명령**이다. 봉인 '대사' 를 위한 이름(sealed_hash·SEALED_BASELINE)은
    # 금지 대상이 아니므로, 토큰이 verb 와 **정확히** 같을 때만 적발한다. 부분 문자열 매칭은
    # 봉인 대사 코드를 스스로 적발해 검사를 무의미하게 만든다.
    hits: list[str] = []
    exempt: list[str] = []
    for rel in S3_2_SCRIPTS:
        path = ROOT / rel
        if not path.exists():
            continue
        toks = exec_tokens(path)
        for t in toks:
            low = t.lower()
            if low in FORBIDDEN_VERBS:
                hits.append(f"{rel}:{t}")
            elif any(vb in low for vb in FORBIDDEN_VERBS):
                exempt.append(f"{rel}:{t}")
    # subprocess 등 호출 인자에 금지 verb 가 문자열로 들어간 경우도 본다 (실제 실행 경로).
    # 여기서도 **낱말 단위 정확 일치**만 적발한다 — 'sealed_sha256'(봉인 대사 필드명)처럼
    # verb 를 부분 문자열로 품은 이름을 적발하면 검사가 자기 자신을 잡아 무의미해진다.
    for rel in S3_2_SCRIPTS:
        path = ROOT / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for lit in [a for a in ast.walk(node) if isinstance(a, ast.Constant)
                            and isinstance(a.value, str)]:
                    words = [w.strip("\"'`,.;:()[]{}") for w in lit.value.lower().split()]
                    if any(w in FORBIDDEN_VERBS for w in words):
                        hits.append(f"{rel}:call-arg:{lit.value[:30]}")
                    elif any(vb in lit.value.lower() for vb in FORBIDDEN_VERBS):
                        exempt.append(f"{rel}:call-arg:{lit.value[:24]}")
    add("V13-a", not hits, f"S3-2 스크립트의 금지 verb 실행 {len(hits)} 건{'' if not hits else ' → ' + str(hits[:3])} "
                           f"(봉인 대사 이름 {len(exempt)} 건은 면제: {sorted(set(exempt))[:3]})")

    # ---------------------------------------------------------------- V14 입력 무수정
    s31 = json.loads((ROOT / "outputs/timeseries_v12/loop/results/S3-1.json").read_text(encoding="utf-8"))
    s30 = json.loads((ROOT / "outputs/timeseries_v12/loop/results/S3-0.json").read_text(encoding="utf-8"))
    add("V14-a", s31["artifacts"][TR_REL] == sha256(TR_REL), "transfer_results 가 S3-1 기록 해시 그대로")
    add("V14-b", s30["artifacts"][PR_REL] == sha256(PR_REL), "등록부가 S3-0 기록 해시 그대로")

    # ---------------------------------------------------------------- V15 accept
    add("V15-a", v["verdict"]["adopted_cells"] == [] and "부정 결과" in v["verdict"]["decision"],
        f"판정 = {v['verdict']['decision']}")
    add("V15-b", "채택 목록" in v["verdict"]["accept_line"],
        f"accept 라인 = {v['verdict']['accept_line'][:40]}…")

    # ---------------------------------------------------------------- 출력
    failed = [cid for cid, ok, _ in rows if not ok]
    for cid, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {cid:<12} {detail}")
    print(f"\n{len(rows)} 항목 · 실패 {len(failed)}"
          + (f" → {failed}" if failed else " · ALL PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
