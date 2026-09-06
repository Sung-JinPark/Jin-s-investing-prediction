#!/usr/bin/env python
"""tools/v12_prereg_tables.py — 사전등록 JSON 을 사람이 읽는 표로 렌더 (수기 전사 없음).

S2-3 에서 수기 전사 오기가 2건 나왔다. 그래서 S3-0 의 요약표는 손으로 쓰지 않고 등록부에서
직접 렌더한다. 이 스크립트는 hypotheses.json 을 읽어 outputs/timeseries_v12/loop/_s3_0_tables.md
로 쓴다. 등록부를 고치지 않으며, 등록부에 없는 수치를 만들지 않는다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_prereg_tables.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "data/timeseries_v12/prereg/hypotheses.json"
OUT = ROOT / "outputs/timeseries_v12/loop/_s3_0_tables.md"


def esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    raw = PREREG.read_bytes()
    reg = json.loads(raw.decode("utf-8"))
    digest = hashlib.sha256(raw).hexdigest()
    L: list[str] = []

    L.append("# S3-0 사전등록 요약 (자동 렌더 — 수기 전사 없음)")
    L.append("")
    L.append(f"원본: `data/timeseries_v12/prereg/hypotheses.json` · sha256 `{digest}`")
    L.append(f"등록 시각(epoch): {reg['registered_epoch']} — {esc(reg['registered_kst'])}")
    L.append(f"결과 열람 여부: **results_seen = {reg['results_seen']}**")
    L.append("")

    L.append("## 표 A — 가설")
    L.append("")
    L.append("| ID | 이름 | 채택대상 | 설계도 원문 식 | 자유도 | 설계도 원문 기대 |")
    L.append("|---|---|---|---|---|---|")
    for h in reg["hypotheses"]:
        L.append("| {} | {} | {} | `{}` | {} | {} |".format(
            h["id"], esc(h["name"]), "O" if h["adoption_eligible"] else "— (음성대조)",
            esc(h["design_literal"]), len(h.get("free_parameters", {})),
            esc(h.get("prior_expectation_design", ""))))
    L.append("")
    L.append("설계도 §2 표의 식·기대는 `tools/v12_prereg_check.py` C2 가 바이트 부분문자열로 대사한다.")
    L.append("")

    L.append("## 표 B — 검정 프로토콜 (전부 결과 보기 전 고정)")
    L.append("")
    ep, un, ad, mu = (reg["estimation_protocol"], reg["uncertainty"],
                      reg["adoption"], reg["multiplicity"])
    boot = un["bootstrap"]
    rows = [
        ("표적 y", reg["target"]["y"]),
        ("예측 p", reg["target"]["p"]),
        ("지평", f"{reg['target']['horizons']} (h1·h5 제외 — {reg['target']['horizons_excluded']['reason']})"),
        ("원점", f"{reg['target']['n_origins']}개 · {reg['target']['window'][0]}~{reg['target']['window'][1]}"),
        ("분할", f"{reg['split']['boundary']} — 전반 {reg['split']['early']['n_expected']} / 후반 {reg['split']['late']['n_expected']}"),
        ("방향", " · ".join(f"{d['label']}({d['fit_on']}→{d['evaluate_on']})" for d in ep["directions"])),
        ("적합", ep["fit_objective"]),
        ("격자", f"{ep['grid']['support']} step {ep['grid']['step']} → {ep['grid']['points']}점 · {ep['grid']['tie_break']}"),
        ("검정통계량", ep["test_statistic"]),
        ("CI", f"{boot['type']} ℓ={boot['block_length']} B={boot['replicates']} seed={boot['seed']} · {boot['interval']}"),
        ("1차 채택", ad["primary"]["rule"]),
        ("2차 기준", ad["secondary"]["rule"]),
        ("귀무", f"{mu['null']['definition']} · {mu['null']['replicates']}회"),
        ("다중검정", f"family {mu['family_size']}셀 · {mu['report']} · 주장 문턱 {mu['family_claim_threshold']}"),
        ("홀드아웃", reg["holdout"]["policy"]),
    ]
    L.append("| 항목 | 사전 고정값 |")
    L.append("|---|---|")
    for k, v in rows:
        L.append(f"| {k} | {esc(v)} |")
    L.append("")

    L.append("## 표 C — 보고 의무 (셀마다 전부 채워야 마감)")
    L.append("")
    fields = reg["reporting_contract"]["mandatory_fields_per_cell"]
    L.append(f"산출 경로 `{reg['reporting_contract']['output_path']}` · 필드 {len(fields)}개")
    L.append("")
    L.append("```")
    for i in range(0, len(fields), 4):
        L.append("  " + ", ".join(fields[i:i + 4]))
    L.append("```")
    L.append("")
    L.append(f"- {esc(reg['reporting_contract']['no_cell_dropping'])}")
    L.append(f"- {esc(un['mde_obligation']['rule'])}")
    L.append(f"- {esc(un['concentration_obligation']['rule'])}")
    L.append("")

    L.append("## 표 D — 금지 조항")
    L.append("")
    L.append("| 조항 | 내용 |")
    L.append("|---|---|")
    pro = reg["prohibitions"]
    L.append(f"| 사후 가설 | {esc(pro['no_post_hoc_hypotheses'])} |")
    for i, item in enumerate(pro["no_knob_swapping"], 1):
        L.append(f"| 손잡이 교체 {i} | {esc(item)} |")
    for key in ("K-split-contrast", "K-gate-arith"):
        L.append(f"| {key} | {esc(pro[key]['rule'])} |")
    L.append(f"| 봉인 | {esc(pro['no_seal_touch'])} |")
    L.append(f"| 홀드아웃 | {esc(pro['no_holdout'])} |")
    L.append("")

    L.append("## 표 E — 결과를 보기 전에 정한 해석")
    L.append("")
    L.append("| 경우 | 사전 확정 귀결 |")
    L.append("|---|---|")
    for k, v in reg["pre_committed_interpretation"].items():
        L.append(f"| {k} | {esc(v)} |")
    L.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({len(L)} lines)")
    print(f"prereg sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
