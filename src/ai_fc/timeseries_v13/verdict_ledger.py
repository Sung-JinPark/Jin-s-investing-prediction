"""V13-D15 라이브 판정 적용 원장 리더 — **stdlib + yaml 전용** (표시·배선·due·스코어보드 공용).

원장: data/timeseries_v13/ledgers/live_verdict_applications.jsonl (append-only, key=application_id).
쓰는 곳은 사람이 대화형 세션에서 돌리는 `timeseries-v13-vol-apply-verdict` 하나뿐이다(verdict_apply.py).
이 모듈은 읽기만 한다. pages 빌드 규약(timeseries_v13_vol_display.py 와 같다 — numpy·pandas 금지)을 지킨다.

반환 스키마는 고정이다(r2, 리뷰 B2):
- 파일 부재 → status ok · 빈 원장. 첫 체크포인트(성숙 60 — rv_h5 ≈ 2026-12-10) 전의 정상 상태다.
- 손상(JSON·필수 키·kind·checkpoint int·outcome 집합·cell 이름·중복 id·content_hash) → status unreadable · rows/demoted 비움. 표시는 hold, 배선은 전 셀 차단.
- 리더는 예외를 밖으로 던지지 않는다.
참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import CELL_ORDER, CONTRACT_RELATIVE, canonical_hash

APPLICATIONS_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/live_verdict_applications.jsonl")
ROW_KINDS = ("checkpoint_verdict", "t7_termination")
REQUIRED_KEYS = ("schema_version", "application_id", "kind", "content_hash")
CHECKPOINT_KEYS = ("cell", "checkpoint", "outcome")
DEMOTION_OUTCOME = "demotion_applied"
# 적용 verb 가 쓸 수 있는 outcome 전부(verdict_apply.OUTCOME_BY_STATUS ∪ AFTER_DEMOTION). 오타 outcome 이 강등을
# 조용히 빠뜨리는 fail-open 을 막으려고 리더가 집합 밖 값을 unreadable 로 본다(리뷰 비차단 4).
KNOWN_OUTCOMES = ("demotion_applied", "no_demotion", "verdict_void", "recorded_after_demotion")
DEFAULT_FIRST = 60
DEFAULT_STEP = 20


def checkpoint_schedule(n: int, *, first: int = DEFAULT_FIRST, step: int = DEFAULT_STEP) -> list[int]:
    """성숙 n 에서 도달한 체크포인트 전부(60, 80, …). n < first 이면 빈 목록 — 조기 적용 경로 없음."""
    n = int(n)
    if step <= 0 or first <= 0:
        raise ValueError("checkpoint first/step must be positive")
    return list(range(first, n + 1, step)) if n >= first else []


def reached_checkpoint(n: int, *, first: int = DEFAULT_FIRST, step: int = DEFAULT_STEP) -> int | None:
    schedule = checkpoint_schedule(n, first=first, step=step)
    return schedule[-1] if schedule else None


def checkpoint_sample(file_order_rows: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """file_order_rows = 셀의 distinct 해상 행, 해상 원장에 (cell, origin) 이 **처음 기록된 순서**.

    앞 k 개를 고른 뒤 블록 부트스트랩을 위해 origin 오름차순으로 재정렬해 돌려준다. append-only 원장의
    앞 k 개는 이후 어떤 append 로도 바뀌지 않는다 — 늦게 돌려도 같은 표본(실행 시점 재량 0).
    """
    if len(file_order_rows) < k:
        raise ValueError("checkpoint not reached")
    return sorted(file_order_rows[:k], key=lambda r: str(r["origin"]))


def _empty(status: str, *, exists: bool, error: str | None) -> dict[str, Any]:
    return {"status": status, "path": APPLICATIONS_LEDGER_RELATIVE.as_posix(), "exists": exists,
            "rows": [], "by_id": {}, "demoted": [], "t7": None, "error": error}


def read_applications(root: Path) -> dict[str, Any]:
    """적용 원장 판독 — 예외를 던지지 않는다. 영수증·재계산 검사는 verify(numpy)가 한다."""
    try:
        path = Path(root) / APPLICATIONS_LEDGER_RELATIVE
        if not path.is_file():
            return _empty("ok", exists=False, error=None)
        rows: list[dict[str, Any]] = []
        by_id: dict[str, dict[str, Any]] = {}
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {number}: row is not an object")
            missing = [key for key in REQUIRED_KEYS if key not in row]
            kind = row.get("kind")
            if kind not in ROW_KINDS:
                raise ValueError(f"line {number}: unknown kind {kind!r}")
            if kind == "checkpoint_verdict":
                missing += [key for key in CHECKPOINT_KEYS if key not in row]
            if missing:
                raise ValueError(f"line {number}: missing keys {missing}")
            if kind == "checkpoint_verdict":
                # 해시가 맞아도 타입이 틀린 행은 표시(int 변환)·배선을 깨거나 강등을 빠뜨린다 → unreadable(fail-closed).
                checkpoint = row["checkpoint"]
                if isinstance(checkpoint, bool) or not isinstance(checkpoint, int) or checkpoint <= 0:
                    raise ValueError(f"line {number}: checkpoint must be a positive int, got {checkpoint!r}")
                if row["outcome"] not in KNOWN_OUTCOMES:
                    raise ValueError(f"line {number}: unknown outcome {row['outcome']!r}")
                if row["cell"] not in CELL_ORDER:
                    raise ValueError(f"line {number}: unknown cell {row['cell']!r}")
            body = {key: value for key, value in row.items() if key != "content_hash"}
            if canonical_hash(body) != row.get("content_hash"):
                raise ValueError(f"line {number}: content_hash mismatch ({row.get('application_id')})")
            identity = str(row["application_id"])
            if identity in by_id:
                raise ValueError(f"line {number}: duplicate application_id {identity}")
            by_id[identity] = row
            rows.append(row)
        demoted = {str(r["cell"]) for r in rows
                   if r.get("kind") == "checkpoint_verdict" and r.get("outcome") == DEMOTION_OUTCOME}
        t7 = next((r for r in rows if r.get("kind") == "t7_termination"), None)
        return {"status": "ok", "path": APPLICATIONS_LEDGER_RELATIVE.as_posix(), "exists": True,
                "rows": rows, "by_id": by_id,
                "demoted": [c for c in CELL_ORDER if c in demoted] + sorted(demoted - set(CELL_ORDER)),
                "t7": t7, "error": None}
    except Exception as exc:  # noqa: BLE001 — 리더는 던지지 않는다(표시·배선이 fail-closed 로 읽는다)
        return _empty("unreadable", exists=True, error=f"{type(exc).__name__}: {exc}")


def unreadable_from_exception(exc: BaseException) -> dict[str, Any]:
    """호출부가 리더 호출 자체에서 예외를 만났을 때 쓰는 unreadable dict (None 금지 — 리뷰 B2)."""
    return _empty("unreadable", exists=True, error=f"{type(exc).__name__}: {exc}")


def cell_application_summary(applications: dict[str, Any] | None, cell: str) -> dict[str, Any] | None:
    """셀의 가장 최근(파일 순) checkpoint 행 요약. 원장 판독 실패·행 없음이면 None."""
    if not applications or applications.get("status") != "ok":
        return None
    latest = None
    for row in applications.get("rows") or []:
        if row.get("kind") == "checkpoint_verdict" and str(row.get("cell")) == cell:
            latest = row
    if latest is None:
        return None
    return {"application_id": latest.get("application_id"), "checkpoint": int(latest["checkpoint"]),
            "outcome": latest.get("outcome"), "effect": latest.get("effect"),
            "status": ((latest.get("verdict") or {}).get("status"))}


def pending_checkpoints(matured: dict[str, int], applications: dict[str, Any], scope: list[str] | tuple[str, ...], *,
                        first: int = DEFAULT_FIRST, step: int = DEFAULT_STEP) -> list[dict[str, Any]]:
    """도달했지만 적용 행이 없는 가장 작은 체크포인트 — [{cell, matured, checkpoint}].

    원장 판독 실패면 빈 목록이 아니라 `[{"cell": "*", "error": "verdict_applications_unreadable"}]` 한 항목.
    """
    if not applications or applications.get("status") != "ok":
        detail = (applications or {}).get("error")
        return [{"cell": "*", "error": "verdict_applications_unreadable" + (f": {detail}" if detail else "")}]
    by_id = applications.get("by_id") or {}
    out: list[dict[str, Any]] = []
    for cell in [c for c in CELL_ORDER if c in set(scope)]:
        n = int(matured.get(cell, 0) or 0)
        for k in checkpoint_schedule(n, first=first, step=step):
            if f"v13-apply:{cell}:k{k}" not in by_id:
                out.append({"cell": cell, "matured": n, "checkpoint": k})
                break
    return out


def pending_from_root(root: Path) -> list[dict[str, Any]]:
    """`ai_fc due` 용 — 계약 → 성숙 수(distinct) → 적용 원장 → 도래 체크포인트(+영수증 id)."""
    import yaml

    path = Path(root) / CONTRACT_RELATIVE
    if not path.is_file():
        return []
    contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = contract.get("live_verdict_application")
    if not isinstance(block, dict):
        return []
    checkpoints = block.get("checkpoints") or {}
    first = int(checkpoints.get("first") or DEFAULT_FIRST)
    step = int(checkpoints.get("step") or DEFAULT_STEP)
    scope = [str(c) for c in ((contract.get("publication") or {}).get("holdout_pass_cells") or [])]
    from .resolve import matured_counts   # 지연 import — numpy 계층

    matured = matured_counts(Path(root))
    applications = read_applications(Path(root))
    receipt = str(block.get("approval_receipt") or "")
    return [{**item, "receipt": receipt} for item in
            pending_checkpoints(matured, applications, scope, first=first, step=step)]
