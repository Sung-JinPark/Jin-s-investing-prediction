#!/usr/bin/env python
"""tools/v12_s3_doc_check.py — S3 판정서의 수치를 산출물과 자동 대사 (읽기 전용).

  D1 판정서의 표 A~G 행이 `v12_s3_tables.py` 렌더 출력과 **바이트 일치**
  D2 §0·§1·§4~§6 산문의 수치가 s3_verdict.json · transfer_results.json · s2_entry_verdict.json 필드와 일치
  D3 판정 문장이 정확히 산출 JSON 의 decision 과 같고, 반대 판정(채택 ≥1)을 단정하지 않는지
  D4 금지 서술 — CI·귀무 없이 '유망/확인/우수/입증' 을 단정하는 문장이 없는지 (규율 4)
  D5 등록부 인용 대사 — 판정서가 인용한 분기 원문이 등록부 바이트 부분문자열인지 (완화·재서술 탐지)
  D6 재검 항목 수 대사 — 판정서가 적은 항목 수가 `v12_s3_verify.py` 재실행 결과와 같고 실패 0 인지
  D7 §9 산출물 표의 sha256 3종이 실제 파일과 일치
  D8 §9 봉인·원장 해시가 실측과 일치
  D9 홀드아웃 무접촉 — 판정서의 2015 언급이 '미계산' 문장뿐인지

하나라도 어긋나면 종료코드 1.
실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s3_doc_check.py
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_s3_tables as tbl      # noqa: E402
import v12_s3_verify as vfy      # noqa: E402
import v12_seal_check as sc      # noqa: E402

DOC = "docs/design/v12_s3_verdict.md"
V_REL = "data/timeseries_v12/diagnostics/s3_verdict.json"
TR_REL = "data/timeseries_v12/diagnostics/transfer_results.json"
PR_REL = "data/timeseries_v12/prereg/hypotheses.json"
S2_REL = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"


def sha256(rel: str) -> str:
    h = hashlib.sha256()
    with (ROOT / rel).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(text: str) -> str:
    """U+2212(−)·U+2013(–) 을 ASCII 로 낮춰 비교한다 — 산문과 표의 부호 표기가 섞여 있다."""
    return text.replace("−", "-").replace("–", "-")


def capture(fn) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


def main() -> int:
    doc = (ROOT / DOC).read_text(encoding="utf-8")
    ndoc = normalize(doc)
    v = json.loads((ROOT / V_REL).read_text(encoding="utf-8"))
    tr = json.loads((ROOT / TR_REL).read_text(encoding="utf-8"))
    pr = json.loads((ROOT / PR_REL).read_text(encoding="utf-8"))
    s2 = json.loads((ROOT / S2_REL).read_text(encoding="utf-8"))
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
        if not ok:
            fails.append(name)

    # ---------------------------------------------------------------- D1 표 행 바이트 일치
    rendered = capture(tbl.main).splitlines()
    rows = [ln for ln in rendered if ln.startswith("| ") and not ln.startswith("|---")]
    missing = [ln for ln in rows if ln not in doc]
    check("D1 표 행 일치", not missing,
          f"{len(rows) - len(missing)}/{len(rows)} 행 일치"
          + ("" if not missing else f" · 누락 {missing[:2]}"))

    # 표 밖의 렌더 요약 문장도 대사 (k_obs·퇴화 목록·MDE 요약·평균 k·관대/보수 집계)
    summaries = [ln for ln in rendered
                 if ln.strip() and not ln.startswith(("|", "#"))]
    smissing = [ln for ln in summaries if ln not in doc]
    check("D1-b 렌더 요약문 일치", not smissing,
          f"{len(summaries) - len(smissing)}/{len(summaries)} 문장 일치"
          + ("" if not smissing else f" · 누락 {smissing[:2]}"))

    # ---------------------------------------------------------------- D2 산문 수치
    verd, fa, mult = v["verdict"], v["failure_analysis"], v["multiplicity"]
    dirs = {(d["hypothesis_id"], d["horizon"], d["direction"]): d for d in v["directions"]}
    t3_h21 = dirs[("T3", 21, "early_to_late")]
    t3_h63 = dirs[("T3", 63, "early_to_late")]
    t1_h63_rev = dirs[("T1", 63, "late_to_early")]
    t1_h63_fwd = dirs[("T1", 63, "early_to_late")]
    upper = {(r["horizon"], r["direction"]): {"u": r["eval_upper_set_n"], "n_eval": r["n_eval"]}
             for r in tr["records"] if r["hypothesis_id"] == "T1"}

    needles: list[tuple[str, str]] = [
        ("채택 셀 수", f"0/8"),
        ("k_obs", f"k_obs = {verd['k_obs']}"),
        ("T5 pooled", f"{verd['T5_pass_rate_pooled']:.4f}"),
        ("T5 문턱", f"{verd['T5_threshold']:.2f}"),
        ("T5 백분율", f"{verd['T5_pass_rate_pooled']:.1%}"),
        ("미달 하한<0", f"하한 < 0 | {fa['by_failure_mode']['하한<0']} "),
        ("미달 하한=0", f"하한 = 0 | {fa['by_failure_mode']['하한=0']} "),
        ("MDE 방향수", f"{fa['inconclusive_by_mde_directions']}/16"),
        ("A2 방향수", f"{fa['a2_pass_directions']}/16"),
        ("k_mean", f"{mult['k_mean']}"),
        ("P(k≥kobs)", f"{mult['p_k_ge_kobs']:.4f}"),
        ("T3 h21 상한", f"{t3_h21['ci90_upper']:+.6f}"),
        ("T3 h63 상한", f"{t3_h63['ci90_upper']:+.6f}"),
        ("T1 h63 역방향 Δ", f"{t1_h63_rev['delta']:+.6f}"),
        ("T1 h63 부족분", f"{t1_h63_rev['shortfall_share_of_brier']:.2%}"),
        ("T1 h63 순방향 부족분", f"{t1_h63_fwd['shortfall_share_of_brier']:.2%}"),
        ("S2 h21 gap", f"{s2['rules']['horizons']['h21']['v8_top_gap']:+.4f}"),
        ("S2 h63 gap", f"{s2['rules']['horizons']['h63']['v8_top_gap']:+.4f}"),
        # 상단집합 크기 — 레코드의 eval_upper_set_n 이 정본. 판정서 §1 의 "208 중 14·9",
        # "209 중 156·151" 문장을 그대로 대사한다.
        ("상단집합 후반",
         f"{upper[(21, 'early_to_late')]['n_eval']} 중 {upper[(21, 'early_to_late')]['u']}·"
         f"{upper[(63, 'early_to_late')]['u']}"),
        ("상단집합 전반",
         f"{upper[(21, 'late_to_early')]['n_eval']} 중 {upper[(21, 'late_to_early')]['u']}·"
         f"{upper[(63, 'late_to_early')]['u']}"),
        ("분할 n", f"{tr['method']['split']['n']['early']} "),
        ("T4 위반", f"{tr['t4_full_sample']['h21']['monotonicity_violations']} 건"),
        ("등록부 커밋", tr["prereg"]["commit"][:8]),
    ]
    for label, needle in needles:
        check(f"D2 {label}", normalize(needle) in ndoc, f"'{needle}'")

    # ---------------------------------------------------------------- D3 판정 문장
    check("D3 판정", "**채택 목록: 없음 (0/8 셀). → 전이 불가 — 부정 결과 확정.**" in normalize(doc)
          and verd["decision_code"] == "NEGATIVE_RESULT",
          f"decision={verd['decision']}")
    # 반대 판정을 단정하지 않았는지 — 채택 셀이 0 인데 '채택 셀:' 뒤에 셀 이름이 오면 안 된다.
    bad = re.findall(r"채택 셀[:：]\s*(T[1-4]_h\d+)", doc)
    check("D3-b 반대 판정 미단정", not bad, f"채택 셀 명시 {bad or '없음'}")
    check("D3-c accept 표기", "채택 목록" in doc and "부정 결과" in doc, "accept 두 갈래 모두 표기")

    # ---------------------------------------------------------------- D4 금지 서술
    banned = []
    for line in doc.splitlines():
        if any(w in line for w in ("유망", "확인됐", "우수하다", "입증")):
            if not any(k in line for k in ("CI90", "귀무", "[미검증]", "금지", "p=")):
                banned.append(line.strip()[:80])
    check("D4 금지 서술", not banned, f"{len(banned)} 건" + (f" · {banned[:2]}" if banned else ""))

    # ---------------------------------------------------------------- D5 등록부 인용
    interp = pr["pre_committed_interpretation"]

    def flat(text: str) -> str:
        """인용 비교용 정규화 — 마크다운 인용부호(`> `)와 줄바꿈을 지운다.

        판정서는 등록부 원문을 blockquote 로 접어 싣기 때문에 줄머리 `> ` 가 원문 중간에
        섞여 들어간다. 그 표시만 걷어내고 **글자는 하나도 바꾸지 않는다** — 원문 완화·재서술은
        여전히 여기서 걸린다.
        """
        stripped = "\n".join(re.sub(r"^\s*>\s?", "", ln) for ln in normalize(text).splitlines())
        return re.sub(r"\s+", " ", stripped)

    flat_doc = flat(doc)
    for branch in ("T5_fail", "adopted_0"):
        quoted = interp[branch]
        check(f"D5 {branch} 원문", flat(quoted) in flat_doc, f"'{quoted[:30]}…'")
    check("D5-A1 규칙 원문", flat(pr["adoption"]["primary"]["rule"]) in flat_doc,
          "A1 원문 그대로 인용")
    check("D5-T5 규칙 원문", flat(tr["t5_negative_control"]["rule"]) in flat_doc,
          "T5 규칙 원문 그대로 인용")
    check("D5-T5 한계 원문", flat(tr["t5_negative_control"]["interpretation_limit"]) in flat_doc,
          "T5 해석 한계 원문 그대로 인용")

    # ---------------------------------------------------------------- D6 재검 항목 수
    out = io.StringIO()
    with redirect_stdout(out):
        rc = vfy.main()
    tail = out.getvalue().strip().splitlines()[-1]
    m = re.search(r"(\d+) 항목 · 실패 (\d+)", tail)
    n_items, n_fail = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)
    check("D6 재검 실행", rc == 0 and n_fail == 0, f"{tail}")
    check("D6-b 항목 수 표기", f"{n_items} 항목" in doc and f"재검 {n_items} 종" in doc,
          f"판정서가 {n_items} 항목·{n_items} 종으로 적었는지")

    # ---------------------------------------------------------------- D7 입력 sha256
    for rel in (TR_REL, PR_REL, S2_REL):
        digest = sha256(rel)
        check(f"D7 {rel.split('/')[-1][:14]}", digest in doc, f"{digest[:10]}…")

    # ---------------------------------------------------------------- D8 봉인
    check("D8-a 봉인 해시", sc.sealed_hash() in doc, f"{sc.sealed_hash()[:10]}…")
    check("D8-b 원장 해시", sc.ledger_hash() in doc, f"{sc.ledger_hash()[:10]}…")

    # ---------------------------------------------------------------- D9 홀드아웃
    lines_2015 = [ln.strip() for ln in doc.splitlines() if "2015" in ln]
    ok_2015 = all("미계산" in ln or "봉인창" in ln for ln in lines_2015)
    check("D9 홀드아웃", ok_2015, f"2015 언급 {len(lines_2015)} 줄 전부 '미계산/봉인창' 문맥")

    print("\nALL PASS" if not fails else f"\nFAILURES ({len(fails)}): " + ", ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
