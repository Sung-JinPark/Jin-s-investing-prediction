#!/usr/bin/env python
"""tools/v12_ckpt_tables.py — CKPT 봉인표 렌더 (읽기 전용).

checkpoint_monday.json 만 읽어 outputs/timeseries_v12/loop/_ckpt_tables.md 로 표를 쓴다.
사람이 수치를 옮겨 적지 않게 하는 것이 목적 — 산문 전사 오류 차단.

실행: .venv/Scripts/python.exe tools/v12_run.py tools/v12_ckpt_tables.py [--stdout]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CKPT = ROOT / "outputs/timeseries_v12/loop/checkpoint_monday.json"
OUT = ROOT / "outputs/timeseries_v12/loop/_ckpt_tables.md"


def render(ck: dict) -> str:
    L: list[str] = []
    sr = ck["seal_reconciliation"]
    at = ck["artifact_totals"]
    a = ck["anchors"]
    L.append("# CKPT — 월요일 체크포인트 봉인표")
    L.append("")
    L.append(f"브랜치 `{ck['branch']}` · HEAD `{ck['head_commit'][:8]}` ({ck['head_subject']})")
    L.append("")
    L.append("## 1. 봉인 재대사 (V8/V2 + v8 원장)")
    L.append("")
    L.append("| 대상 | 재계산 sha256 | BOOT 기준선 | 일치 |")
    L.append("|---|---|---|---|")
    L.append(f"| V8 전체 .py + V2 봉인 8종 | `{sr['sealed_sha256']}` | `{sr['sealed_baseline']}` | {'✅' if sr['sealed_match'] else '❌'} |")
    L.append(f"| data/timeseries_v8/ledgers/*.jsonl | `{sr['ledger_sha256']}` | `{sr['ledger_baseline']}` | {'✅' if sr['ledger_match'] else '❌'} |")
    L.append("")
    L.append(f"접두사 `e3ff2fdb` 확인: {'✅' if sr['sealed_prefix_ok'] else '❌'} · 규약: {sr['source']}")
    L.append("")
    L.append("## 2. 단계별 산출물 대사 (선언 sha256 vs 재계산)")
    L.append("")
    L.append("| 태스크 | 제목 | 상태 | 산출물 | 선언과 일치 | 유실 | 변조(drift) | result JSON sha256 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for tid, st in ck["stages"].items():
        L.append(
            f"| {tid} | {st['title']} | {st['status']} | {st['artifact_count']} | "
            f"{st['artifacts_matching_declared']} | {len(st['artifacts_missing'])} | "
            f"{len(st['artifacts_drifted'])} | `{st['result_json_sha256'][:16]}…` |"
        )
    L.append(
        f"| **합계** | S1~S3 9태스크 | 전부 완료 | **{at['declared']}** | "
        f"**{at['declared'] - at['missing'] - at['drifted']}** | **{at['missing']}** | **{at['drifted']}** | "
        f"result JSON {at['result_json_count']}종 |"
    )
    L.append("")
    L.append("## 3. 앵커 해시 (`<sha256> *<relpath>` 정렬 후 재해시 — sealed_hash() 규약)")
    L.append("")
    L.append("| 앵커 | 범위 | sha256 |")
    L.append("|---|---|---|")
    L.append(f"| artifacts | 산출물 {at['present']}개 | `{a['artifacts_anchor']}` |")
    L.append(f"| results | result JSON {at['result_json_count']}종 | `{a['results_anchor']}` |")
    L.append(f"| **CHECKPOINT** | 위 둘의 합집합 {at['present'] + at['result_json_count']}개 | `{a['checkpoint_anchor']}` |")
    L.append("")
    L.append("## 4. 무변경 대사")
    L.append("")
    g = ck["git_reconciliation"]
    L.append("| 항목 | 결과 |")
    L.append("|---|---|")
    L.append(f"| 봉인 산출물 git 추적·커밋 완료 ({g['files_checked']}개 경로) | {'✅ 미추적 0 · 미커밋 0' if g['clean'] else '❌ ' + str(len(g['untracked'])) + ' 미추적 / ' + str(len(g['dirty_or_uncommitted'])) + ' 미커밋'} |")
    L.append(f"| 불변 경로 워킹트리 ({' · '.join(ck['immutable_paths_checked'])}) | {'✅ 변경 0' if not ck['immutable_paths_dirty'] else '❌ ' + str(len(ck['immutable_paths_dirty'])) + '건 변경'} |")
    L.append("")
    L.append("## 5. 백로그 상태")
    L.append("")
    b = ck["backlog_state"]
    L.append(f"- 완료: {', '.join(b['done'])}")
    L.append(f"- 대기: {', '.join(b['pending'])}")
    L.append(f"- S3 결과: {b['s3_outcome']}")
    L.append(f"- 다음 단계: {b['next_stage']}")
    L.append("")
    L.append("## 6. 봉인 판정")
    L.append("")
    L.append(f"**봉인 성립 = {ck['ok']}** — 봉인 해시 2종 일치 · 산출물 유실 0 · drift 0 · 불변 경로 무변경.")
    L.append("")
    for n in ck["notes"]:
        L.append(f"- {n}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ck = json.loads(CKPT.read_text(encoding="utf-8"))
    text = render(ck)
    if "--stdout" in sys.argv[1:]:
        print(text)
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT).as_posix()} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
