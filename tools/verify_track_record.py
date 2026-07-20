#!/usr/bin/env python3
"""AI-FC track record 제3자 검증기 (v3.5 WS-T1).

외부인이 클론 직후 실행하는 1커맨드 무결성 검증 — **읽기 전용, 표준 라이브러리 + git CLI만**.
(피검증 시스템 코드를 import하지 않는다 — 검증기가 피검증 코드에 의존하면 순환.)

    python tools/verify_track_record.py

검증 항목:
  [1] 해시 앵커  — forecasts/ 예측 파일 SHA-256 재계산 ↔ forecasts/.hashes 대조
  [2] git 불변성 — (a) 예측·증거 파일의 수정/삭제 이벤트 0 (생성 후 무수정)
                   (b) calibration/*.csv가 이력상 항상 prefix-확장 (append-only)
  [3] 시점 불변식 — 파일별 등급 판정:
        A급(강한 증명): 공개 baseline 이후 커밋 — 커밋 시각 ≤ 질문 마감 (리모트 고정 시계)
        B급(약한 증명): baseline 커밋에 포함 — 내부 시점 정합만 (외부 시계 없음 — 자기증명)
  [4] Brier 재계산 — 원장·벤치마크의 점수를 (p − outcome)²로 독립 재계산 대조

종료코드: 0 = 전 항목 PASS, 1 = FAIL 존재 (CI 게이트 겸용).
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# AIFC_VERIFY_ROOT: 테스트가 조작 시뮬 픽스처 리포를 지정하는 용도 (기본 = 이 리포)
ROOT = Path(os.environ.get("AIFC_VERIFY_ROOT",
                           Path(__file__).resolve().parent.parent))
EXCLUDE_PARTS = ("retro",)          # 가변 회고 노트 — 불변 규약 비대상
ANCHOR = ROOT / "forecasts" / ".hashes"

GRADE_NOTE = """
등급 설명 (정직한 공증 구조):
  커밋 타임스탬프는 로컬 시계라 단독으로는 위조 가능하다. GitHub에 푸시된 이후의
  커밋 시점만 사실상 공증된다. 따라서 본 검증기는 증명을 2등급으로 구분한다:
  [B급 · 약한 증명] 공개 baseline 커밋에 포함된 기록 — 해시 일관성과 파일 내부
      시점 정합만 검증 (외부 시계 없음 — 자기증명임을 명시한다)
  [A급 · 강한 증명] baseline 이후 커밋된 기록 — 리모트 고정 이력의 커밋 시각이
      질문 마감보다 앞섬을 검증. 향후 표본은 전부 A급으로 쌓인다.
"""


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


class Report:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.infos: list[str] = []

    def fail(self, msg: str) -> None:
        self.fails.append(msg)
        print(f"  FAIL  {msg}")

    def ok(self, msg: str) -> None:
        print(f"  ok    {msg}")

    def info(self, msg: str) -> None:
        self.infos.append(msg)
        print(f"  info  {msg}")


# ── [1] 해시 앵커 ────────────────────────────────────────────────

def check_hash_anchor(rep: Report) -> list[str]:
    """앵커 대조. 반환: 앵커에 등재된 예측 파일 상대경로 목록."""
    print("[1] 해시 앵커 (forecasts/.hashes ↔ SHA-256 재계산)")
    if not ANCHOR.exists():
        rep.fail(".hashes 앵커 파일 없음")
        return []
    anchored: dict[str, str] = {}
    for line in ANCHOR.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        h, _, rel = line.partition("  ")
        anchored[rel.strip()] = h.strip()
    n_bad = 0
    for rel, expect in anchored.items():
        p = ROOT / rel
        if not p.exists():
            rep.fail(f"{rel}: 앵커에 있으나 파일 없음")
            n_bad += 1
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != expect:
            rep.fail(f"{rel}: 해시 불일치 (파일이 앵커 이후 변경됨)")
            n_bad += 1
    # 역방향: 앵커에 없는 예측 파일
    for p in sorted((ROOT / "forecasts").rglob("*_r*.md")):
        if any(part in EXCLUDE_PARTS for part in p.parts) or p.stem.endswith("_evidence"):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if not re.match(r"^\d{4}-\d{2}-\d{2}_.+_r\d+$", p.stem):
            continue
        if rel not in anchored:
            rep.fail(f"{rel}: 예측 파일이 앵커에 미등재")
            n_bad += 1
    if n_bad == 0:
        rep.ok(f"예측 파일 {len(anchored)}건 해시 전건 일치")
    return sorted(anchored)


# ── [2] git 불변성 ───────────────────────────────────────────────

def check_git_immutability(rep: Report) -> None:
    print("[2] git 불변성 (공개 이력 전체)")
    # (a) 예측·증거 md의 수정/삭제 이벤트
    out = _git("log", "--diff-filter=MD", "--name-only", "--format=", "--", "forecasts")
    touched = sorted({
        ln.strip() for ln in out.splitlines()
        if ln.strip().endswith(".md")
        and not any(part in EXCLUDE_PARTS for part in Path(ln.strip()).parts)
    })
    if touched:
        for t in touched:
            rep.fail(f"(a) {t}: 생성 후 수정/삭제 이력 존재")
    else:
        rep.ok("(a) 예측·증거 파일 수정/삭제 이벤트 0 — 생성 후 무수정")

    # (b) 원장 CSV의 prefix-확장 (append-only의 git 증명)
    for rel in ("calibration/ledger.csv", "calibration/benchmark_ledger.csv",
                "calibration/research_status_overrides.csv"):
        if not (ROOT / rel).exists():
            continue
        commits = _git("log", "--reverse", "--format=%H", "--", rel).split()
        prev_lines: list[str] | None = None
        bad = False
        for c in commits:
            try:
                content = _git("show", f"{c}:{rel}")
            except RuntimeError:
                continue
            lines = content.splitlines()
            if prev_lines is not None and lines[:len(prev_lines)] != prev_lines:
                rep.fail(f"(b) {rel}: 커밋 {c[:7]}에서 기존 행 수정/축소 — append-only 위반")
                bad = True
            prev_lines = lines
        # 작업 트리도 HEAD의 확장이어야 함
        if prev_lines is not None:
            wt = (ROOT / rel).read_text(encoding="utf-8").splitlines()
            if wt[:len(prev_lines)] != prev_lines:
                rep.fail(f"(b) {rel}: 작업 트리가 HEAD 대비 기존 행 변경")
                bad = True
        if not bad:
            n = len(commits)
            rep.ok(f"(b) {rel}: {n}개 버전 전부 prefix-확장 (이력 {n}커밋 기준"
                   + (" — 이력이 짧아 실효는 향후 커밋부터)" if n <= 1 else ")"))


# ── [3] 시점 불변식 + 등급 ───────────────────────────────────────

def _parse_frontmatter(path: Path) -> dict[str, str]:
    """의존성 없는 최소 frontmatter 파서 — 단순 'key: value' 행만."""
    fm: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return fm
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip("'\"")
    return fm


def _registry_deadlines() -> dict[str, str]:
    """registry.yaml에서 id→deadline — yaml 있으면 정식, 없으면 정규식 (의존성 0 경로)."""
    text = (ROOT / "questions" / "registry.yaml").read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return {str(q["id"]): str(q.get("deadline")) for q in data.get("questions", [])}
    except ImportError:
        out: dict[str, str] = {}
        cur = None
        for ln in text.splitlines():
            m = re.match(r"^- id:\s*(\S+)", ln)
            if m:
                cur = m.group(1)
                continue
            m = re.match(r"^\s{2}deadline:\s*(\S+)", ln)
            if m and cur:
                out[cur] = m.group(1).strip("'\"")
        return out


def _deadline_for(rel: str, deadlines: dict[str, str]) -> date | None:
    stem = Path(rel).stem
    m = re.match(r"^\d{4}-\d{2}-\d{2}_(?P<qid>.+)_r\d+$", stem)
    if not m:
        return None
    raw = deadlines.get(m.group("qid"), "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw or ""):
        return date.fromisoformat(raw)
    # rolling·미정 → frontmatter window_end
    fm = _parse_frontmatter(ROOT / rel)
    we = fm.get("window_end", "")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", we):
        return date.fromisoformat(we)
    return None


def check_timepoints(rep: Report, anchored: list[str]) -> tuple[int, int]:
    print("[3] 시점 불변식 + 증명 등급 (A=baseline 이후 커밋 / B=baseline 포함)")
    root_commit = _git("rev-list", "--max-parents=0", "HEAD").split()[0]
    deadlines = _registry_deadlines()
    n_a = n_b = 0
    for rel in anchored:
        first = _git("log", "--diff-filter=A", "--reverse",
                     "--format=%H|%cI", "--", rel).splitlines()
        if not first:
            rep.fail(f"{rel}: git 이력에 추가 커밋 없음 (미커밋 파일?)")
            continue
        commit_hash, commit_iso = first[0].split("|", 1)
        dl = _deadline_for(rel, deadlines)
        stem_date = date.fromisoformat(Path(rel).stem[:10])
        if commit_hash == root_commit:
            n_b += 1
            # B급: 내부 정합 — 파일명 날짜·frontmatter 시각 ≤ 마감 (자기증명)
            if dl is not None and stem_date > dl:
                rep.fail(f"{rel}: [B급] 파일명 날짜 {stem_date} > 마감 {dl} — 내부 정합 위반")
        else:
            n_a += 1
            ct = datetime.fromisoformat(commit_iso).astimezone(timezone.utc)
            if dl is not None:
                limit = datetime(dl.year, dl.month, dl.day, 23, 59, 59,
                                 tzinfo=timezone.utc) + timedelta(0)
                if ct > limit:
                    rep.fail(f"{rel}: [A급] 커밋 {ct.date()} (UTC) > 마감 {dl} — 시점 위반")
            else:
                rep.info(f"{rel}: [A급] 마감 미정 — 시점 검사 불가")
    rep.ok(f"등급 집계: A급 {n_a}건 (강한 증명) / B급 {n_b}건 (자기증명 — 외부 시계 없음)")
    return n_a, n_b


# ── [4] Brier 재계산 ─────────────────────────────────────────────

def _recheck_csv_brier(rep: Report, rel: str, cols: list[tuple[str, str, str]],
                       outcome_by_fid: dict[str, float] | None = None) -> None:
    p = ROOT / rel
    if not p.exists():
        return
    reader = csv.DictReader(io.StringIO(p.read_text(encoding="utf-8")))
    n = bad = 0
    for i, row in enumerate(reader, start=1):
        # outcome: 자체 열 우선, 없으면 원장 조인 (벤치마크 원장은 outcome 미보유 설계)
        raw_out = row.get("outcome")
        if raw_out in ("", None) and outcome_by_fid is not None:
            raw_out = outcome_by_fid.get(row.get("forecast_id", ""))
        try:
            outcome = float(raw_out)
        except (TypeError, ValueError):
            continue
        for pcol, bcol, scale in cols:
            praw, braw = row.get(pcol, ""), row.get(bcol, "")
            if praw in ("", None) or braw in ("", None):
                continue
            try:
                prob = float(praw) / (100.0 if scale == "pct" else 1.0)
            except (TypeError, ValueError):
                continue
            expect = round((prob - outcome) ** 2, 4)
            n += 1
            if abs(expect - float(braw)) > 1e-4:
                rep.fail(f"{rel} {i}행 {bcol}: 기록 {braw} ≠ 재계산 {expect}")
                bad += 1
    if bad == 0:
        rep.ok(f"{rel}: {n}개 점수 재계산 전건 일치")


def check_brier(rep: Report) -> None:
    print("[4] Brier 독립 재계산")
    _recheck_csv_brier(rep, "calibration/ledger.csv",
                       [("probability", "brier", "pct")])
    # 벤치마크 원장은 outcome 미보유 — 원장에서 forecast_id로 조인해 재계산
    outcome_by_fid: dict[str, float] = {}
    lp = ROOT / "calibration" / "ledger.csv"
    if lp.exists():
        for row in csv.DictReader(io.StringIO(lp.read_text(encoding="utf-8"))):
            try:
                outcome_by_fid[row["forecast_id"]] = float(row["outcome"])
            except (KeyError, ValueError):
                continue
    _recheck_csv_brier(rep, "calibration/benchmark_ledger.csv",
                       [("llm_prob", "llm_brier", "raw"),
                        ("ml_prob", "ml_brier", "raw"),
                        ("market_prob", "market_brier", "raw")],
                       outcome_by_fid=outcome_by_fid)


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 62)
    print("AI-FC track record 검증기 — 읽기 전용 · stdlib + git")
    print("=" * 62)
    rep = Report()
    anchored = check_hash_anchor(rep)
    check_git_immutability(rep)
    n_a, n_b = check_timepoints(rep, anchored)
    check_brier(rep)
    ots = ROOT / "forecasts" / ".hashes.ots"
    if ots.exists():
        rep.info(".hashes.ots 존재 — OpenTimestamps 비트코인 앵커 "
                 "(검증: `ots verify forecasts/.hashes.ots`)")
    print("-" * 62)
    verdict = "PASS" if not rep.fails else f"FAIL ({len(rep.fails)}건)"
    print(f"결과: [A급 {n_a} / B급 {n_b}] 해시·불변성·시점·Brier → {verdict}")
    print(GRADE_NOTE)
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
