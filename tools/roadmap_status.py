"""MTS 프로그램 로드맵 상태 — 원장·계약에서 **파생**해 인쇄한다 (설계도 §9).

    PYTHONUTF8=1 python tools/roadmap_status.py

규율(설계도 §9.4):
- 읽기 전용. 어떤 파일도 쓰지 않는다.
- 스케줄 금지. 세션 시작 시 사람이 1회 돌린다(`tools/ops_status.py` 패턴).
- 페일클로즈: 파일·필드 부재는 '알 수 없음'이 아니라 **미종료**로 보고한다.
- 상태를 손으로 적는 파일을 만들지 않는다 — 낡은 상태 파일은 잘못된 다음 행동을 부른다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
GUARD = ROOT / "data/timeseries_v13/vol/guard_mde_design.json"
LIVE = ROOT / "data/timeseries_v13/ledgers/vol_live.jsonl"
RESOLUTIONS = ROOT / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl"
HOLDOUT = ROOT / "data/timeseries_v13/ledgers/holdout_scorings.jsonl"
APPROVALS = ROOT / "data/timeseries_v13/ledgers/approvals.jsonl"
EXPERIMENTS = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"
LIMITS = ROOT / "docs/KNOWN_LIMITS.md"
LICENSES = ROOT / "docs/generated/licenses.generated.md"


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _contract() -> dict[str, Any]:
    if not CONTRACT.is_file():
        return {}
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8")) or {}


def _decisions(kind: str) -> bool:
    return any(row.get("decision_id") == kind for row in _rows(APPROVALS))


def _guard_ok() -> tuple[bool, list[str]]:
    contract = _contract()
    missing: list[str] = []
    if not GUARD.is_file():
        missing.append(f"{GUARD.relative_to(ROOT).as_posix()} 부재")
    guard = contract.get("degeneracy_guard") or {}
    rules = guard.get("rules") or {}
    if "min_episodes_per_half_per_class" not in rules:
        missing.append("계약 degeneracy_guard.rules.min_episodes_per_half_per_class 부재")
    if not guard.get("design_window_result"):
        missing.append("계약 degeneracy_guard.design_window_result 부재")
    if GUARD.is_file():
        payload = json.loads(GUARD.read_text(encoding="utf-8"))
        declared = sorted((guard.get("design_window_result") or {}).get("episode_failures") or [])
        measured = sorted((payload.get("summary") or {}).get("episode_guard_failures") or [])
        if declared != measured:
            missing.append("계약의 episode_failures 가 실측과 불일치")
    return (not missing), missing


def _live_forward_ok() -> tuple[bool, list[str]]:
    gate = (_contract().get("live_forward_gate") or {})
    missing: list[str] = []
    if gate.get("execution_path") == "absent_by_construction":
        missing.append("live_forward_gate.execution_path 가 아직 absent_by_construction")
    if not gate.get("verb"):
        missing.append("live_forward_gate.verb 미기재")
    cli = (ROOT / "src/ai_fc/cli.py")
    if cli.is_file() and "timeseries-v13-vol-resolve" not in cli.read_text(encoding="utf-8"):
        missing.append("CLI 에 timeseries-v13-vol-resolve 부재")
    return (not missing), missing


def _v8_stall() -> tuple[bool, list[str]]:
    """P1b: 정지가 문서화됐거나(등재) 이미 해소됐으면 종료."""
    documented = LIMITS.is_file() and "DTWEXBGS" in LIMITS.read_text(encoding="utf-8")
    report = (ROOT / "docs/review/V8_SHADOW_ORIGIN_STALL_20260909.md").is_file()
    if documented and report:
        return True, []
    return False, ["DTWEXBGS 정지가 KNOWN_LIMITS·진단 문서에 등재되지 않음"]


def _holdout_ok() -> tuple[bool, list[str]]:
    contract = _contract()
    status = ((contract.get("publication") or {}).get("holdout_status") or "not_consumed")
    missing: list[str] = []
    if not _rows(HOLDOUT):
        missing.append("holdout_scorings.jsonl 행 0 — 미소모")
    if status not in {"pass", "partial", "fail"}:
        missing.append(f"publication.holdout_status={status}")
    if not _decisions("V13-D3"):
        missing.append("approvals 에 V13-D3 승인 영수증 부재")
    return (not missing), missing


def _wiring_ok() -> tuple[bool, list[str]]:
    contract = _contract()
    missing: list[str] = []
    if not _decisions("V13-D6"):
        missing.append("approvals 에 V13-D6 승인 영수증 부재")
    if not (ROOT / "data/base_rates/volatility_v13_auto.md").is_file():
        missing.append("data/base_rates/volatility_v13_auto.md 부재")
    if (contract.get("publication") or {}).get("holdout_status") not in {"pass", "partial"}:
        missing.append("홀드아웃 PASS/부분PASS 전에는 배선 불가")
    return (not missing), missing


def _new_block_ok() -> tuple[bool, list[str]]:
    protocol = (_contract().get("development_protocol") or {})
    spent = int(protocol.get("evaluations_spent") or 0)
    if len(_rows(EXPERIMENTS)) >= 4 and spent >= 4:
        return True, []
    return False, [f"신규 피처블록 rung 미실행 (원장 {len(_rows(EXPERIMENTS))}행 · evaluations_spent {spent})"]


def _paid_data_ok() -> tuple[bool, list[str]]:
    if LICENSES.is_file():
        text = LICENSES.read_text(encoding="utf-8")
        head, _, tail = text.partition("Pending manual reviews")
        if "CBOE" in head or "Cboe" in head:
            return True, []
    return False, ["licenses.generated.md 의 확정 표에 CBOE 행 없음 (회신·적재 전)"]


def _forward_sample_ok() -> tuple[bool, list[str]]:
    gate = (_contract().get("live_forward_gate") or {})
    minimum = int(gate.get("minimum_matured_origins_per_cell") or 60)
    rows = _rows(RESOLUTIONS)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("cell"))] = counts.get(str(row.get("cell")), 0) + 1
    cells = ((_contract().get("gates") or {}).get("champion") or {}).get("cells") or {}
    if not cells:
        return False, ["champion 셀 미확정"]
    worst = min((counts.get(name, 0) for name in cells), default=0)
    if worst >= minimum:
        return True, []
    return False, [f"성숙 원점 최소 {worst}/{minimum} (해상 원장 {len(rows)}행)"]


def _sealed_ok() -> tuple[bool, list[str]]:
    return False, ["신규 버전 봉인 미착수 (C5 종속)"]


STAGES: list[tuple[str, str, Callable[[], tuple[bool, list[str]]], str, str]] = [
    ("P0", "판정 기계 건전성·에피소드 가드", _guard_ok, "없음",
     "PYTHONUTF8=1 python tools/v13_guard_mde.py"),
    ("P1", "라이브 전진 채점", _live_forward_ok, "없음",
     "cd src && python -m ai_fc timeseries-v13-vol-resolve"),
    ("P1b", "V8 섀도 정지 진단", _v8_stall, "없음", "docs/review/V8_SHADOW_ORIGIN_STALL_*.md 작성"),
    ("P2", "홀드아웃 1회 소모", _holdout_ok,
     "V13-D3 원문: 'V13-D3 홀드아웃 1회 소모 승인 finalist=<finalist_id>'",
     "cd src && python -m ai_fc timeseries-v13-vol-holdout --approval-receipt <id>"),
    ("P3", "EXIT base rate 배선", _wiring_ok, "V13-D6",
     "cd src && python -m ai_fc timeseries-v13-vol-base-rates"),
    ("P4", "봉인 아카이브 내 신규 피처블록", _new_block_ok, "없음(예산 내)",
     "신규 rung 사전등록 후 실행"),
    ("P5", "외부 정보집합(옵션·일중)", _paid_data_ok, "구매·발송(사용자)",
     "CBOE 회신 기록 → 적재 계약 신설"),
    ("P6", "라이브 전진 축적", _forward_sample_ok, "없음", "시간 — 매 거래일 resolve 누적"),
    ("P7", "신규 버전 봉인 + P3 게이트", _sealed_ok, "SEAL-1 + 소유자 사인오프", "C5 진전 대기"),
]


def main() -> int:
    print("MTS 로드맵 상태 — 원장·계약에서 파생 (설계도 §9). 읽기 전용.\n")
    contract = _contract()
    if not contract:
        print("V13 계약을 읽을 수 없다 — 저장소 루트에서 실행했는지 확인하라.")
        return 1
    results = [(sid, name, *check(), approval, command)
               for sid, name, check, approval, command in STAGES]
    print(f"{'단계':5s} {'상태':8s} 이름")
    current = None
    for sid, name, ok, _missing, _approval, _command in results:
        print(f"{sid:5s} {'완료' if ok else '미종료':8s} {name}")
        if not ok and current is None:
            current = (sid, name)
    print()
    blockers = [(sid, m) for sid, _n, ok, missing, _a, _c in results if not ok for m in missing]
    if current is None:
        print("현 단계 : 전 단계 종료 — 프로그램 완성 조건(C0~C4)을 §1.2 로 대조하라")
        return 0
    sid, name = current
    row = next(r for r in results if r[0] == sid)
    print(f"현 단계 : {sid} ({name})")
    print("차단 요인:")
    for stage_id, message in blockers[:8]:
        print(f"          [{stage_id}] {message}")
    print(f"다음 승인: {row[4]}")
    print(f"다음 명령: {row[5]}")
    print("\n자원 잔량:")
    protocol = contract.get("development_protocol") or {}
    print(f"          개발 예산 {protocol.get('evaluations_spent')}/{protocol.get('maximum_development_evaluations')}"
          f" · 홀드아웃 슬롯 {len({r.get('finalist_id') for r in _rows(HOLDOUT)})}/{protocol.get('holdout_maximum_finalists')}"
          f" · 라이브 원점 {len({r.get('as_of') for r in _rows(LIVE)})} · 해상 {len(_rows(RESOLUTIONS))}행")
    publication = contract.get("publication") or {}
    print(f"          표시 tier {publication.get('display_tier')} · 홀드아웃 {publication.get('holdout_status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
