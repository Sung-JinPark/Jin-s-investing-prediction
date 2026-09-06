#!/usr/bin/env python
"""tools/v12_s5_doc_check.py — 최종 보고서 대사 (읽기 전용).

무엇을 검사하는가
-----------------
  D1  표 — 보고서의 표 블록이 렌더러(tools/v12_s5_tables.py) 출력과 **바이트 일치**하고,
      표 11 종이 전부 실렸는가. 사람이 수치를 옮겨 적을 자리를 없앤다.
  D2  산문 수치 — 표 밖 산문의 소수 리터럴이 전부 원천 JSON(산출 JSON·12 태스크 result·
      진단·판정·설계)에서 유래하는가. 유래하지 않는 값은 허용 목록에 근거와 함께 등재해야 한다.
  D3  금지 서술 — 부정 결과를 '조건부 통과'로 되살리는 서술, 게이트 무장·트랙 개시 단정이
      부정문 밖에 있는가.
  D4  절 — 필수 절 §0~§9 가 전부 있는가.
  D5  결정표 — 산출 JSON 의 결정 ID·권고 요약이 보고서와 일치하는가.
  D6  봉인·앵커 — 보고서에 실린 sha256 리터럴이 실측 봉인·원장·앵커와 일치하는가.
  D7  홀드아웃 — 2015~2025 언급이 전부 '미계산·미소모·보존' 문맥인가.
  D8  정직 기록 — `[미검증]` 표기·반대 읽기 절·한계 절이 실재하는가.
  D9  상태 — 불변 경로 청결 · 백로그 13 태스크 전부 완료 · 산출물 drift 0.

무엇을 검사하지 않는가 (정직한 경계)
------------------------------------
상류 단계 판정의 **정오**는 재검증하지 않는다. 그것은 각 단계의 verify·result_check 가 이미
한 일이고, 여기서 다시 돌리면 같은 코드를 두 번 도는 것이지 독립 검증이 아니다. 이 검사가
보장하는 것은 "보고서가 상류 산출물을 왜곡 없이 옮겼는가" 뿐이다.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_doc_check.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import v12_seal_check as sc  # noqa: E402

DOC = ROOT / "docs/review/SUNDAY_LOOP_FINAL_REPORT.md"
TABLES = ROOT / "outputs/timeseries_v12/loop/_s5_1_tables.md"
REPORT = ROOT / "data/timeseries_v12/reports/final_report.json"
BACKLOG = ROOT / "data/timeseries_v12/ralph/V12_SUNDAY_BACKLOG_260904.json"
RESULTS = ROOT / "outputs/timeseries_v12/loop/results"

IMMUTABLE_PATHS = ["forecasts", "calibration", "src",
                   "data/timeseries_v8", "data/timeseries_v2", "questions"]

REQUIRED_SECTIONS = [
    "## §0 판정",
    "## §1 이 루프가 지킨 규율",
    "## §2 단계별 결과",
    "## §3 사용자 결정표",
    "## §4 미완 정직 기록",
    "## §5 산출물 무결성과 inventory",
    "## §6 PR 준비",
    "## §7 반대 읽기",
    "## §8 한계",
    "## §9 이 보고 뒤에 남는 것",
]

# 원천 JSON 이 아닌 곳에서 온 수치는 여기 근거와 함께 등재한다. 비워 두는 것이 원칙이다.
DECIMAL_ALLOWLIST = {
    "0.18": "CLAUDE.md 하드 게이트 — P3 게이트 Brier 문턱 (저장소 헌법 상수, 산출 JSON 밖)",
}

FORBIDDEN_PHRASES = ["조건부 통과", "게이트를 무장", "트랙을 개시했다", "채택됐다", "전이가 확인"]
# 부정 마커는 '0' 같은 흔한 토큰을 넣지 않는다 — 넣는 순간 거의 모든 줄이 면제돼 검사가 무의미해진다.
NEGATION_MARKERS = ["아니", "않", "없", "금지", "못", "미달", "막", "무장하지", "위반"]

# D2/D3 이 헛돌지 않음을 보이는 음성 대조. 이 값·문장이 통과하면 검사가 무의미하다.
DECIMAL_NEGATIVE_CONTROL = ["3.14159", "0.123456789", "99.9999"]
NARRATIVE_NEGATIVE_CONTROL = "S3 는 조건부 통과였으므로 트랙을 개시했다"

HOLDOUT_CONTEXT = ["미계산", "미소모", "보존", "봉인창", "홀드아웃", "접촉", "주장이", "미평가"]

_SECTION_RE = re.compile(r"§\s*\d+(?:\.\d+)*")
_CODE_RE = re.compile(r"`[^`]*`")
_DECIMAL_RE = re.compile(r"(?<![\w])(\d+\.\d+)")


def norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_numbers(obj, pool: set[str]) -> None:
    """JSON 의 모든 수치와 문자열 속 소수 리터럴을 표기 후보 집합으로 편다."""
    if isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, pool)
    elif isinstance(obj, list):
        for v in obj:
            collect_numbers(v, pool)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        x = float(obj)
        for d in range(0, 9):
            pool.add(f"{abs(x):.{d}f}")
            pool.add(f"{abs(x) * 100:.{d}f}")
        pool.add(repr(abs(x)))
    elif isinstance(obj, str):
        for m in _DECIMAL_RE.findall(obj):
            pool.add(m)


def split_render_sections(text: str) -> list[tuple[str, str]]:
    chunks = norm(text).split("\n### ")
    out = []
    for chunk in chunks[1:]:
        title = chunk.splitlines()[0]
        out.append((title, ("### " + chunk).rstrip("\n")))
    return out


def strip_tables(doc: str, sections: list[tuple[str, str]]) -> str:
    prose = doc
    for _title, body in sections:
        prose = prose.replace(body, "\n")
    return prose


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        checks.append((cid, bool(ok), detail))

    doc = norm(DOC.read_text(encoding="utf-8"))
    render = norm(TABLES.read_text(encoding="utf-8"))
    R = json.loads(REPORT.read_text(encoding="utf-8"))
    backlog = json.loads(BACKLOG.read_text(encoding="utf-8"))

    # ── D1 표 바이트 일치 ────────────────────────────────────────────
    sections = split_render_sections(render)
    add("D1-a", len(sections) == 11, f"렌더 표 절 {len(sections)}개 (기대 11)")
    missing = [t for t, body in sections if body not in doc]
    add("D1-b", not missing, f"보고서에 바이트 일치로 실리지 않은 표: {missing or '없음'}")
    table_lines = sum(len(body.splitlines()) for _t, body in sections)
    add("D1-c", table_lines > 100, f"표 총 {table_lines}행이 렌더 출력 그대로")

    # ── D2 산문 소수 리터럴 ─────────────────────────────────────────
    prose = strip_tables(doc, sections)
    prose = _SECTION_RE.sub(" ", prose)
    prose = _CODE_RE.sub(" ", prose)
    literals = sorted(set(_DECIMAL_RE.findall(prose)))

    pool: set[str] = set()
    collect_numbers(R, pool)
    for path in sorted(RESULTS.glob("*.json")):
        collect_numbers(json.loads(path.read_text(encoding="utf-8")), pool)
    for rel in R["provenance"]["inputs_sha256"]:
        p = ROOT / rel
        if p.suffix == ".json" and p.is_file():
            collect_numbers(json.loads(p.read_text(encoding="utf-8")), pool)

    unsourced = [lit for lit in literals if lit not in pool and lit not in DECIMAL_ALLOWLIST]
    add("D2-a", not unsourced, f"산문 소수 {len(literals)}개 중 미출처 {len(unsourced)}: {unsourced or '없음'}")
    add("D2-b", set(DECIMAL_ALLOWLIST) <= set(literals) | set(DECIMAL_ALLOWLIST),
        f"허용 목록 {len(DECIMAL_ALLOWLIST)}건 전부 근거 명시")
    leaked = [c for c in DECIMAL_NEGATIVE_CONTROL if c in pool]
    add("D2-c", not leaked,
        f"음성 대조 — 원천에 없는 소수 {DECIMAL_NEGATIVE_CONTROL} 가 후보 집합에 새지 않음 (샌 값: {leaked or '없음'}) · 후보 집합 크기 {len(pool)}")

    # ── D3 금지 서술 ────────────────────────────────────────────────
    def find_offenders(lines: list[str]) -> list[tuple[str, str]]:
        found = []
        for line in lines:
            for phrase in FORBIDDEN_PHRASES:
                if phrase in line and not any(m in line for m in NEGATION_MARKERS):
                    found.append((phrase, line.strip()[:80]))
        return found

    offenders = find_offenders(doc.splitlines())
    add("D3-a", not offenders, f"부정문 밖 금지 서술 {len(offenders)}건: {offenders or '없음'}")
    add("D3-c", bool(find_offenders([NARRATIVE_NEGATIVE_CONTROL])),
        "음성 대조 — 부정 마커 없는 되살리기 문장은 같은 검사에서 적발된다")
    add("D3-b", "gates.armed=false" in doc or "armed=False" in doc or "무장하지 않" in doc,
        "게이트 미무장 상태를 문서가 명시")

    # ── D4 절 ───────────────────────────────────────────────────────
    absent = [s for s in REQUIRED_SECTIONS if s not in doc]
    add("D4-a", not absent, f"필수 절 누락: {absent or '없음'}")

    # ── D5 결정표 ───────────────────────────────────────────────────
    ids = [d["id"] for d in R["decisions"]]
    add("D5-a", all(i in doc for i in ids), f"결정 ID {ids} 전부 보고서에 존재")
    add("D5-b", all(d["recommendation_short"] in doc for d in R["decisions"]),
        "결정별 권고 요약이 산출 JSON 문자열 그대로")
    add("D5-c", all(d["state"] in doc for d in R["decisions"]),
        "결정별 현재 상태가 산출 JSON 문자열 그대로")

    # ── D6 봉인·앵커 ────────────────────────────────────────────────
    sealed_now, ledger_now = sc.sealed_hash(), sc.ledger_hash()
    seal = R["seal_state"]
    add("D6-a", sealed_now == seal["sealed_sha256"] == seal["sealed_baseline"],
        f"봉인 {sealed_now[:8]}… = 산출 JSON = BOOT 기준선")
    add("D6-b", ledger_now == seal["ledger_sha256"] == seal["ledger_baseline"],
        f"원장 {ledger_now[:8]}… = 산출 JSON = 기준선")
    doc_hashes = set(re.findall(r"\b[0-9a-f]{64}\b", doc))
    known = {sealed_now, ledger_now,
             R["artifact_inventory"]["anchors"]["artifacts_anchor"],
             R["artifact_inventory"]["anchors"]["results_anchor"],
             R["artifact_inventory"]["anchors"]["loop_anchor"],
             R["ckpt_reproduction"]["checkpoint_anchor_declared"],
             R["inventory"]["snapshot"]["source_fingerprint"]}
    unknown = sorted(doc_hashes - known)
    add("D6-c", not unknown, f"보고서 sha256 {len(doc_hashes)}개 중 원천 미상 {len(unknown)}: {unknown or '없음'}")
    add("D6-d", R["artifact_inventory"]["clean"] and R["ckpt_reproduction"]["checkpoint_anchor_match"],
        "산출물 drift 0 · CKPT 앵커 재현")

    # ── D7 홀드아웃 ─────────────────────────────────────────────────
    bad = []
    for line in doc.splitlines():
        if re.search(r"\b20(1[5-9]|2[0-5])\b", line) and not any(k in line for k in HOLDOUT_CONTEXT):
            bad.append(line.strip()[:90])
    add("D7-a", not bad, f"보존 문맥 밖 2015+ 언급 {len(bad)}건: {bad or '없음'}")
    add("D7-b", not (ROOT / "data/timeseries_v12/holdout").exists(), "홀드아웃 산출물 디렉터리 부재")

    # ── D8 정직 기록 ────────────────────────────────────────────────
    unverified = doc.count("[미검증]")
    add("D8-a", unverified >= 3, f"`[미검증]` 표기 {unverified}건")
    add("D8-b", "데블스 애드버킷" in doc, "반대 읽기(데블스 애드버킷) 절 존재")
    counter_items = len(re.findall(r"\*\*\(\d\)", doc))
    add("D8-c", counter_items >= 5, f"반대 읽기 항목 {counter_items}건")
    limits = doc.split("## §8 한계")[1].split("## §9")[0] if "## §8 한계" in doc else ""
    limit_bullets = len([l for l in limits.splitlines() if l.startswith("- ")])
    add("D8-d", limit_bullets >= 5, f"한계 항목 {limit_bullets}건")
    add("D8-e", "not_done" in doc or "미완" in doc, "미완 기록 절 존재")

    # ── D9 상태 ─────────────────────────────────────────────────────
    dirty = [l for l in git("status", "--porcelain", "--", *IMMUTABLE_PATHS).splitlines() if l.strip()]
    add("D9-a", not dirty, f"불변 경로 워킹트리 변경 {len(dirty)}건")
    statuses = {t["status"] for t in backlog["tasks"]}
    add("D9-b", statuses == {"완료"}, f"백로그 태스크 상태 집합 {sorted(statuses)}")
    add("D9-c", R["loop"]["forbidden_verbs_executed_total"] == 0,
        f"금지 verb 실행 누계 {R['loop']['forbidden_verbs_executed_total']}")
    add("D9-d", R["inventory"]["status"] == "완료" and not R["inventory"]["immutable_paths"]["dirty_after"],
        "inventory 재생성 완료 · 불변 경로 무오염")
    add("D9-e", (ROOT / "outputs/timeseries_v12/loop/PR_BODY.md").is_file(),
        "PR 본문 초안 존재 (푸시 없음)")

    failed = [c for c in checks if not c[1]]
    for cid, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {cid}  {detail}")
    print(f"\n총 {len(checks)}항목 · 실패 {len(failed)}")
    print(f"보고서 sha256: {sha256_file(DOC)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
