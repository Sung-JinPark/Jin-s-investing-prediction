#!/usr/bin/env python
"""S4-2 문서 대사 — docs/design/v12_gate_design.md 를 산출 JSON·계약과 기계로 맞춘다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s4_2_doc_check.py

검사 (전부 PASS 여야 accept):
  D1 표 블록이 렌더러 출력과 바이트 일치 (수기 전사 0)
  D2 산문의 소수 리터럴이 전부 산출 JSON·계약·판정 JSON 의 값에서 유래
  D3 금지 서술 — '조건부 통과' 류가 부정문 밖에 없음
  D4 필수 절 존재 · accept 요건(설계서가 spec 4주제를 다룸)
  D5 게이트 문턱 인용이 계약값과 일치
  D6 게이트 무장 상태 서술이 계약(armed=false)과 일치
  D7 봉인·원장 해시 인용이 실측과 일치 + 불변 경로 git 청결
  D8 홀드아웃 무접촉 — 2015+ 산출 주장 0
  D9 한계·반대읽기 절이 [미검증] 표기를 동반
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/design/v12_gate_design.md"
TABLES = ROOT / "outputs/timeseries_v12/loop/_s4_2_tables.md"
GD = ROOT / "data/timeseries_v12/design/gate_design.json"
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v12.draft.yaml"
S3V = ROOT / "data/timeseries_v12/diagnostics/s3_verdict.json"
PREREG = ROOT / "data/timeseries_v12/prereg/hypotheses.json"

# 규약 상수·표기 관행 — 산출 JSON 에 값으로 존재하지 않아도 되는 리터럴.
WHITELIST = {
    "0.90",     # 배리어 K/S
    "0.05", "0.10",  # 명목 유의수준·T5 문턱
    "1.645",    # 진단 승수
    "0.001",    # V8 게이트 상수 인용 없음(보호용)
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_numbers(node: Any, out: list[float]) -> None:
    if isinstance(node, dict):
        for v in node.values():
            collect_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_numbers(v, out)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, str):
        for tok in re.findall(r"-?\d+\.\d+(?:[eE][-+]?\d+)?", node):
            try:
                out.append(float(tok))
            except ValueError:
                continue


def table_regions(doc_lines: list[str]) -> list[str]:
    """<!-- TABLES:* --> 마커 안쪽 줄만 모은다."""
    inside = False
    out: list[str] = []
    open_rx = re.compile(r"<!--\s*TABLES:(START|PART\d)\s*-->")
    close_rx = re.compile(r"<!--\s*TABLES:(PART\d_END|END)\s*-->")
    for line in doc_lines:
        if open_rx.search(line):
            inside = True
            continue
        if close_rx.search(line):
            inside = False
            continue
        if inside:
            out.append(line)
    return out


def main() -> int:
    doc = DOC.read_text(encoding="utf-8")
    doc_lines = doc.splitlines()
    rendered = TABLES.read_text(encoding="utf-8").splitlines()
    gd = json.loads(GD.read_text(encoding="utf-8"))
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    s3v = json.loads(S3V.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))

    checks: list[tuple[str, bool, str]] = []

    def chk(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, bool(ok), detail))

    # ---------------------------------------------------------------- D1 표 일치
    doc_tbl = [ln for ln in table_regions(doc_lines) if ln.strip()]
    ren_tbl = [ln for ln in rendered if ln.strip() and not ln.startswith("<!--")]
    chk("D1-a", doc_tbl == ren_tbl,
        f"문서 표 {len(doc_tbl)}줄 vs 렌더 {len(ren_tbl)}줄" +
        ("" if doc_tbl == ren_tbl else
         f" · 첫 불일치: {next((f'{i}: {a!r} != {b!r}' for i, (a, b) in enumerate(zip(doc_tbl, ren_tbl)) if a != b), 'length')}"))
    titles = [ln for ln in ren_tbl if ln.startswith("### 표 ")]
    chk("D1-b", len(titles) == 10, f"렌더 표 {len(titles)}개 (기대 10: A·A2·B·C·C2·D·E1·E2·E3·F)")
    chk("D1-c", all(t in doc for t in titles), "모든 표 제목이 문서에 존재")

    # ---------------------------------------------------------------- D2 산문 수치
    pool: list[float] = []
    for src in (gd, contract, s3v, prereg):
        collect_numbers(src, pool)
    prose_lines = []
    inside_tbl = set(id(x) for x in [])
    tbl_set = set(table_regions(doc_lines))
    for ln in doc_lines:
        if ln in tbl_set or ln.lstrip().startswith("|"):
            continue
        prose_lines.append(ln)
    # U+2212(−)·en dash 를 ASCII 하이픈으로 정규화해야 부호가 있는 리터럴을 제대로 읽는다.
    prose = "\n".join(prose_lines).replace("−", "-").replace("–", "-")
    tokens = re.findall(r"-?\d+\.\d{3,}(?:[eE][-+]?\d+)?", prose)
    unmatched: list[str] = []
    for tok in tokens:
        if tok in WHITELIST:
            continue
        val = float(tok)
        dp = len(tok.split(".")[1].split("e")[0].split("E")[0])
        if "e" in tok or "E" in tok:
            tol = abs(val) * 1e-2
        else:
            tol = 0.5 * 10 ** (-dp) + 1e-12
        if not any(abs(val - p) <= tol for p in pool):
            unmatched.append(tok)
    chk("D2-a", not unmatched, f"산문 소수 {len(tokens)}개 검사 · 미유래 {unmatched}")

    # 해시 리터럴은 실측과 일치해야 한다
    hash_tokens = re.findall(r"\b[0-9a-f]{64}\b", doc)
    known = {contract["predecessor_immutability"]["sealed_source_hash"],
             contract["predecessor_immutability"]["v8_ledger_hash"],
             contract["predecessor_immutability"]["v8_contract_sha256"]}
    chk("D2-b", all(h in known for h in hash_tokens),
        f"문서 해시 {len(hash_tokens)}개 전부 계약 핀과 일치")

    # ---------------------------------------------------------------- D3 금지 서술
    banned = ("조건부 통과", "잠정 통과", "잠정통과", "유예 통과")
    neg_markers = ("금지", "아니다", "없다", "않는다", "위반", "못한다", "말고")
    offenders = []
    for i, ln in enumerate(doc_lines, 1):
        for word in banned:
            if word in ln and not any(m in ln for m in neg_markers):
                offenders.append(f"{i}: {ln.strip()[:60]}")
    chk("D3-a", not offenders, f"금지 어휘 부정문 밖 사용 {offenders}")
    chk("D3-b", "게이트를 무장" not in doc and "무장한다" not in doc,
        "무장 선언 서술 없음")

    # ---------------------------------------------------------------- D4 절·주제
    required_sections = ["## 0.", "## 1. 게이트 산술", "## 2. MDE", "## 3. 예산",
                         "## 4. 파생층 배포 경계", "## 5.", "## 6.", "## 7."]
    missing = [s for s in required_sections if s not in doc]
    chk("D4-a", not missing, f"필수 절 누락 {missing}")
    spec_topics = {"게이트 산술": "## 1. 게이트 산술", "MDE": "## 2. MDE",
                   "예산": "## 3. 예산", "파생층 배포 경계": "## 4. 파생층 배포 경계"}
    chk("D4-b", all(v in doc for v in spec_topics.values()),
        f"spec 4주제 절 존재: {list(spec_topics)}")
    chk("D4-c", "S4-1 open_question 1" in doc and "S4-1 open_question 4" in doc,
        "S4-1 이 넘긴 두 미결 항목을 명시적으로 다룸")

    # ---------------------------------------------------------------- D5 문턱 인용
    th = contract["gates"]["G2_skill_vs_reflection"]["thresholds"]
    cited = []
    for h in ("h21", "h63"):
        for key in ("vs_reflection_bgk", "vs_reflection_2phi"):
            r = th[h][key]
            for field in ("required_candidate_brier_max",
                          "required_brier_skill_vs_climatology_min"):
                cited.append((f"{h}.{key}.{field}", f"{r[field]:.6f}" in doc))
    chk("D5-a", all(ok for _, ok in cited),
        f"계약 문턱 8개 인용 · 누락 {[k for k, ok in cited if not ok]}")
    recon = gd["A_gate_arithmetic"]["contract_reconciliation"]
    chk("D5-b", recon["all_within_tolerance"] and recon["values_compared"] == 20,
        f"산출측 계약 대사 {recon['values_compared']}값 · 최대잔차 "
        f"{recon['max_abs_residual']:.2e}")

    # ---------------------------------------------------------------- D6 무장 상태
    chk("D6-a", contract["gates"]["armed"] is False, "계약 armed=false")
    chk("D6-b", "armed=false" in doc or "`armed=false`" in doc,
        "문서가 armed=false 를 명시")
    chk("D6-c", contract["development_protocol"]["track_open"] is False
        and "트랙 개시" in doc, "트랙 미개시 상태 인지")
    chk("D6-d", int(contract["gates"]["evaluated_candidates"]) == 0,
        "평가된 후보 0 (문서가 후보를 만들지 않음)")

    # ---------------------------------------------------------------- D7 봉인
    seal = gd["seal_state"]
    chk("D7-a", seal["ledger_matches_baseline"] and seal["ledger_matches_contract_pin"]
        and seal["v8_ledger_hash"] == contract["predecessor_immutability"]["v8_ledger_hash"],
        f"원장 해시 = BOOT 기준선 = 계약 핀 ({seal['v8_ledger_hash'][:8]}…)")
    chk("D7-b", seal["sealed_matches_baseline"] and seal["sealed_matches_contract_pin"]
        and seal["sealed_source_hash"].startswith("e3ff2fdb")
        and seal["v8_contract_matches_pin"],
        f"봉인 해시 = BOOT 기준선 = 계약 핀 ({seal['sealed_source_hash'][:8]}…) + V8 계약 해시 일치")
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", "forecasts", "calibration", "src",
         "data/timeseries_v8", "data/timeseries_v2", "questions"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    chk("D7-c", proc.stdout.strip() == "",
        f"불변 경로 git 청결 · 출력={proc.stdout.strip()[:120]!r}")

    # ---------------------------------------------------------------- D8 홀드아웃
    years = re.findall(r"\b(20(?:1[5-9]|2[0-9]))\b", doc)
    bad_year_lines = []
    for i, ln in enumerate(doc_lines, 1):
        if re.search(r"\b20(1[5-9]|2[0-9])\b", ln):
            if not any(m in ln for m in ("미계산", "봉인", "보존", "홀드아웃", "미소모",
                                         "2026-09", "차단")):
                bad_year_lines.append(f"{i}: {ln.strip()[:70]}")
    chk("D8-a", not bad_year_lines, f"2015+ 언급이 전부 보존 문맥 · 예외 {bad_year_lines}")
    chk("D8-b", contract["stopping_points"]["holdout"]["current_state"].startswith("미소모"),
        "계약 홀드아웃 미소모 유지")
    chk("D8-c", not (ROOT / "data/timeseries_v12/holdout").exists(),
        "홀드아웃 산출물 디렉터리 부재")

    # ---------------------------------------------------------------- D9 한계
    chk("D9-a", doc.count("[미검증]") >= 4, f"[미검증] 표기 {doc.count('[미검증]')}개")
    chk("D9-b", "반대 읽기" in doc or "데블스" in doc, "반대증거 절 존재")
    chk("D9-c", "## 6. 한계" in doc, "한계 절 존재")
    limits = re.findall(r"^\d+\.\s", doc[doc.index("## 6. 한계"):], flags=re.M)
    chk("D9-d", len(limits) >= 8, f"한계 항목 {len(limits)}개")

    # ---------------------------------------------------------------- 출력
    failed = [c for c in checks if not c[1]]
    for cid, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {cid} — {detail}")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} PASS")
    if failed:
        print("실패: " + ", ".join(c[0] for c in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
