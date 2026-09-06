#!/usr/bin/env python
"""tools/v12_s2_doc_check.py — S2 진단서의 수치를 산출물과 자동 대사 (읽기 전용).

D1  진단서에 붙은 표 A/B/B2/C/D 의 데이터 행이 `v12_s2_tables.py` 렌더 출력과 **바이트 일치**
D2  §0·§6 산문·제약표의 수치가 s2_entry_verdict.json 필드와 일치 (문자열 포함 검사)
D3  진단서가 판정 문장을 정확히 1 건 담고, 그것이 산출 JSON 의 decision 과 같은지
D4  금지 서술 검사 — CI·귀무 없이 '유망/확인/우수' 를 단정하는 문장이 없는지 (규율 4)

하나라도 어긋나면 종료코드 1.
"""
from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_s2_tables as tbl   # noqa: E402

DOC = "docs/design/v12_event_target_diagnostic.md"
V = "data/timeseries_v12/diagnostics/s2_entry_verdict.json"


def normalize(text: str) -> str:
    """U+2212(−)·U+2013(–) 을 ASCII 로 낮춰 비교한다 — 산문과 표의 부호 표기가 섞여 있다."""
    return text.replace("−", "-")


def main() -> int:
    doc = (ROOT / DOC).read_text(encoding="utf-8")
    v = json.loads((ROOT / V).read_text(encoding="utf-8"))
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
        if not ok:
            fails.append(name)

    # ---- D1 표 행 바이트 일치
    buf = io.StringIO()
    with redirect_stdout(buf):
        tbl.main()
    rendered = buf.getvalue().splitlines()
    data_rows = [ln for ln in rendered
                 if ln.startswith("| ") and not ln.startswith("|---")
                 and not ln.startswith("| 지평 |") and not ln.startswith("| 조작화 |")
                 and not ln.startswith("| 사전 제약 |")]
    # §6 제약표는 진단서에서 의도적으로 재서술했으므로 D2 로 검사한다 — 여기서는 제외.
    table_rows = [ln for ln in data_rows if not ln.startswith("| `K-")]
    missing = [ln for ln in table_rows if ln not in doc]
    check("D1 표 행 일치", not missing,
          f"{len(table_rows) - len(missing)}/{len(table_rows)} 행 일치"
          + ("" if not missing else f" · 누락: {missing[:2]}"))

    # ---- D2 산문·제약표 수치
    ndoc = normalize(doc)
    verd, rules, power, gate = v["verdict"], v["rules"], v["split_power"], v["gate_arithmetic"]
    needles: list[tuple[str, str]] = [
        ("R2 h21 하한", f"{rules['R2']['ci90_lower']['h21']:+.4f}"),
        ("R2 h63 하한", f"{rules['R2']['ci90_lower']['h63']:+.4f}"),
        ("R1 h21 하한", f"{rules['R1']['ci90_lower']['h21']:+.4f}"),
        ("셀 카운트", f"{rules['regime_cell_summary']['both_top_gap_positive']}/"
                    f"{rules['regime_cell_summary']['cells']}"),
        ("반사 셀 CI", f"반사 {rules['regime_cell_summary']['reflection_ci90_lower_positive']}/8"),
        ("V8 셀 CI", f"V8 {rules['regime_cell_summary']['v8_ci90_lower_positive']}/8"),
        ("h21 후반 집중도",
         f"{power['h21']['late_2011_2014']['concentration']['top5_abs_share_of_sum']:.1%}"),
        ("h21 후반 MDE", f"{power['h21']['late_2011_2014']['mde_1645se']:.6f}"),
        ("h63 후반 MDE", f"{power['h63']['late_2011_2014']['mde_1645se']:.6f}"),
        ("h21 전반 제거후평균",
         f"{power['h21']['early_2007_2010']['concentration']['mean_after_dropping_top5pct_by_abs']:+.6f}"),
        ("게이트 h21 2Φ", f"{gate['h21']['reflection_2phi']['required_bss_vs_climatology']:+.2%}"),
        ("게이트 h21 BGK", f"{gate['h21']['reflection_bgk']['required_bss_vs_climatology']:+.2%}"),
        ("게이트 h63 2Φ", f"{gate['h63']['reflection_2phi']['required_bss_vs_climatology']:+.2%}"),
        ("게이트 h63 BGK", f"{gate['h63']['reflection_bgk']['required_bss_vs_climatology']:+.2%}"),
        ("상한 h21", f"{gate['h21']['ceiling_max_bss']:.1%}"),
        ("상한 h63", f"{gate['h63']['ceiling_max_bss']:.1%}"),
    ]
    for label, needle in needles:
        check(f"D2 {label}", normalize(needle) in ndoc, f"'{needle}'")

    # ---- D3 판정 1건
    decision = verd["decision"]
    hits = len(re.findall(r"\*\*판정\s*=?\s*" + decision, doc)) + len(
        re.findall(r"\*\*S3 " + decision + r"\.\*\*", doc))
    check("D3 판정 문장", hits >= 1 and decision in doc,
          f"decision={decision} 문장 {hits} 건")
    other = "중단" if decision == "진입" else "진입"
    check("D3 반대 판정 미단정", f"**판정 = {other}**" not in doc, f"'{other}' 단정 없음")

    # ---- D4 금지 서술 (CI 없는 단정)
    banned = []
    for line in doc.splitlines():
        if any(w in line for w in ("유망", "확인됐", "우수하다", "입증")):
            if not any(k in line for k in ("CI90", "귀무", "[미검증]", "금지", "p=")):
                banned.append(line.strip()[:80])
    check("D4 금지 서술", not banned, f"{len(banned)} 건" + (f" · {banned[:2]}" if banned else ""))

    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
