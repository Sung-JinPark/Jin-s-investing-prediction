"""registry.yaml 로드·검증, cadence 정규화, due 계산.

due 계산은 (레지스트리, 최근 예측 시각) → DueItem 목록의 순수 함수라서
놓친 날이 있어도 다음 실행에서 자동 복구된다.

schedule 세그먼트 스키마 (additive — 기존 cadence 자유 텍스트는 유지):
  {per_week: N} | {per_day: N} | {once: true}
  + 선택 조건: {from: "D-30"} (기한 D-30 이내) | {from_date: "YYYY-MM-DD"}
목록에서 조건을 충족하는 '마지막' 세그먼트가 활성. schedule 부재 = manual.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import ML_DIVERGENCE_PP, STALE_DAYS
from .models import DueItem, Question, sha256_text

ROLLING_RE = re.compile(r"^rolling-(\d+)d$")


def load_registry(path: Path) -> list[Question]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = []
    for q in data.get("questions", []):
        deadline_raw = q.get("deadline")
        deadline_kind, deadline, rolling_days = _classify_deadline(deadline_raw)
        src_hash = sha256_text(
            f"{q.get('question', '')}|{q.get('resolution', '')}|{q.get('resolution_source', '')}"
        )
        questions.append(Question(
            question_id=str(q["id"]),
            title=str(q.get("title", "")),
            question=str(q.get("question", "")).strip(),
            deadline_kind=deadline_kind,
            deadline=deadline,
            rolling_days=rolling_days,
            resolution=str(q.get("resolution", "")).strip(),
            resolution_source=str(q.get("resolution_source", "")),
            domain=str(q.get("domain", "")),
            cadence_raw=str(q.get("cadence", "")),
            schedule=q.get("schedule") or [],
            action_link=str(q.get("action_link", "")),
            status=str(q.get("status", "active")),
            created=q.get("created") if isinstance(q.get("created"), date) else None,
            notes=str(q.get("notes", "")),
            required_snapshots=q.get("required_snapshots") or [],
            src_hash=src_hash,
            drivers=q.get("drivers") or [],
            tier=(str(q.get("tier")) if q.get("tier") in ("standard", "lite")
                  else "standard"),  # 관대한 리더 — 미지정/오타는 standard
        ))
    ids = [q.question_id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("registry에 중복 question_id 존재")
    return questions


def _classify_deadline(raw: Any) -> tuple[str, Optional[date], Optional[int]]:
    if raw is None:
        return "tbd", None, None
    if isinstance(raw, datetime):
        return "fixed", raw.date(), None
    if isinstance(raw, date):
        return "fixed", raw, None
    m = ROLLING_RE.match(str(raw).strip())
    if m:
        return "rolling", None, int(m.group(1))
    # 문자열 날짜 (yaml이 date로 안 읽은 경우)
    dm = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(raw).strip())
    if dm:
        return "fixed", date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3))), None
    raise ValueError(f"해석 불가 deadline: {raw!r}")


# ── 스케줄 → 재예측 간격 ─────────────────────────────────────────

def _segment_active(seg: dict[str, Any], q: Question, today: date) -> bool:
    if "from" in seg:
        m = re.match(r"^D-(\d+)$", str(seg["from"]))
        if not m or q.deadline_kind != "fixed" or q.deadline is None:
            return False
        return (q.deadline - today).days <= int(m.group(1))
    if "from_date" in seg:
        fd = seg["from_date"]
        fd = fd if isinstance(fd, date) else date.fromisoformat(str(fd))
        return today >= fd
    return True  # 무조건 세그먼트


def active_segment(q: Question, today: date) -> Optional[dict[str, Any]]:
    """조건을 충족하는 마지막 세그먼트 (활성). 없으면 None."""
    active = None
    for seg in q.schedule:
        if _segment_active(seg, q, today):
            active = seg
    return active


def segment_activation_date(seg: dict[str, Any], q: Question) -> Optional[date]:
    """조건부 세그먼트가 활성화된 날짜. 무조건 세그먼트는 None."""
    if "from" in seg:
        m = re.match(r"^D-(\d+)$", str(seg["from"]))
        if m and q.deadline_kind == "fixed" and q.deadline:
            return q.deadline - timedelta(days=int(m.group(1)))
        return None
    if "from_date" in seg:
        fd = seg["from_date"]
        return fd if isinstance(fd, date) else date.fromisoformat(str(fd))
    return None


def active_interval_days(q: Question, today: date) -> Optional[float]:
    """활성 세그먼트의 재예측 간격(일). once/manual이면 None."""
    active = active_segment(q, today)
    if active is None:
        return None
    if active.get("once"):
        return None
    if "per_day" in active:
        return 1.0 / float(active["per_day"])
    if "per_week" in active:
        return 7.0 / float(active["per_week"])
    return None


# ── WS1 질문 팩토리 등록 필터 (v2 라운드, questions/FACTORY_GUIDE.md) ──

FACTORY_FILTER_CUTOFF = date(2026, 7, 21)   # 이후 created 질문만 적용 (grandfather)
FACTORY_MARKER = "등록필터:"


def factory_filter_violation(q: Question) -> Optional[str]:
    """등록 필터 위반 메시지. 통과·비대상(grandfather)이면 None.

    필터 (FACTORY_GUIDE.md): (a) base rate/시장내재가 [35,65] 밖, 또는
    (b) 정보 우위 논거 명시 — 어느 쪽이든 notes에 '등록필터:' 마커로 근거를 남겨야 한다.
    코인플립성 질문(기해소 spx-up/soxx-up 유형)이 Brier를 0.25에 고정해 게이트를
    오염시키는 것을 차단하는 규약. 수치 검증은 사람 몫 — 코드는 근거 기재만 강제.
    """
    if q.created is None or q.created < FACTORY_FILTER_CUTOFF:
        return None
    if q.status != "active":
        return None
    if FACTORY_MARKER not in (q.notes or ""):
        return (f"{q.question_id}: created {q.created} ≥ {FACTORY_FILTER_CUTOFF} 인데 "
                f"notes에 '{FACTORY_MARKER}' 근거 없음 — FACTORY_GUIDE.md 필터 (a)/(b) "
                "충족 근거를 기재 후 재실행")
    return None


# ── due 계산 (순수 함수) ─────────────────────────────────────────

def compute_due(
    questions: list[Question],
    latest_forecast: dict[str, Optional[datetime]],  # qid → 마지막 예측 시각 (없으면 None/부재)
    open_windows: dict[str, list[tuple[str, date]]],  # qid → [(forecast_id, window_end)] 미해소 rolling 인스턴스
    resolved_forecast_ids: set[str],
    now: datetime,
    latest_probs: Optional[dict[str, int]] = None,   # qid → 최신 LLM 확률 (divergence용)
    ml_refs: Optional[dict[str, Any]] = None,        # qid → queries.MlRef (divergence용)
    divergence_classes: Optional[dict[str, str]] = None,  # qid → 직전 회차 class (WS6 표시)
) -> list[DueItem]:
    due: list[DueItem] = []
    today = now.date()

    for q in questions:
        if q.status != "active":
            continue
        last = latest_forecast.get(q.question_id)

        # 1) 해소 due — fixed 기한 경과
        if q.deadline_kind == "fixed" and q.deadline and today > q.deadline:
            due.append(DueItem(q.question_id, "resolve",
                               f"기한 {q.deadline} 경과 — 판정 필요"))
            continue  # 기한 지난 질문은 재예측 대상 아님

        # 2) 해소 due — rolling 윈도우 종료
        for fid, wend in open_windows.get(q.question_id, []):
            if fid not in resolved_forecast_ids and today > wend:
                due.append(DueItem(q.question_id, "resolve",
                                   f"rolling 윈도우 {wend} 종료 — {fid} 채점 필요"))

        # 3) 재예측 due
        if q.is_manual:
            due.append(DueItem(q.question_id, "manual-review",
                               f"schedule 미정 (cadence: {q.cadence_raw!r})", last))
        else:
            interval = active_interval_days(q, today)
            if interval is None:
                # once 세그먼트: 무조건 once = 첫 예측 1회 / 조건부 once({from: D-3, once})
                # = 세그먼트 활성화 이후 1회 (WS1 단기 질문의 "r1 + D-3 재예측" cadence)
                seg = active_segment(q, today)
                if seg is not None and seg.get("once"):
                    act = segment_activation_date(seg, q)
                    if last is None:
                        due.append(DueItem(q.question_id, "forecast",
                                           "1회성 — 첫 예측 미실행", last))
                    elif act is not None and last.date() < act:
                        due.append(DueItem(
                            q.question_id, "forecast",
                            f"세그먼트({seg.get('from') or seg.get('from_date')}) 활성 "
                            f"({act}) 후 예측 미실행", last))
            elif last is None:
                due.append(DueItem(q.question_id, "forecast", "첫 예측 미실행", last))
            elif (now - last) > timedelta(days=interval):
                overdue = (now - last).days
                due.append(DueItem(q.question_id, "forecast",
                                   f"마지막 예측 {overdue}일 전 (간격 {interval:.1f}일)", last))

        # 4) 스테일 경보 (재예측 due와 별개의 안전망)
        if last is not None and (now - last) > timedelta(days=STALE_DAYS) and not q.is_manual:
            due.append(DueItem(q.question_id, "stale",
                               f"{(now - last).days}일 무예측 — cadence 해석 점검 필요", last))

        # 5) divergence — LLM 확률 vs ML앙상블 참조 확률의 괴리 (표시만 — 자동 실행 없음)
        if latest_probs and ml_refs:
            p = latest_probs.get(q.question_id)
            ref = ml_refs.get(q.question_id)
            if p is not None and ref is not None and not ref.low_confidence:
                gap = abs(p / 100.0 - ref.prob)
                if gap >= ML_DIVERGENCE_PP / 100.0:
                    cls = (divergence_classes or {}).get(q.question_id)
                    cls_txt = f" · 직전 분류: {cls}" if cls else ""
                    due.append(DueItem(
                        q.question_id, "divergence",
                        f"LLM {p}% vs ML앙상블 {ref.prob:.0%} — 괴리 {gap * 100:.0f}%p "
                        f"≥ {ML_DIVERGENCE_PP}%p (재예측 후보 — 자동 실행 안 함){cls_txt}",
                        last))

    return due


# ── 한국어 cadence → schedule 제안 (보조 마이그레이션) ─────────────

def propose_schedule(cadence: str) -> Optional[list[dict[str, Any]]]:
    """알려진 한국어 패턴에서 schedule 제안. 해석 불가 시 None (추측 금지)."""
    c = cadence.strip()
    if not c:
        return None
    if "1회성" in c:
        return [{"once": True}]

    segments: list[dict[str, Any]] = []

    m = re.search(r"D-(\d+)부터\s*주\s*(\d+)회", c)
    if m:
        base = [{"per_week": 1}]
        return base + [{"from": f"D-{m.group(1)}", "per_week": int(m.group(2))}]

    m = re.search(r"주\s*(\d+)회\s*[,，]\s*D-(\d+)부터\s*일\s*(\d+)회", c)
    if m:
        return [{"per_week": int(m.group(1))},
                {"from": f"D-{m.group(2)}", "per_day": int(m.group(3))}]

    m = re.search(r"P0에서는\s*주\s*(\d+)회", c)  # "일 1회 (P0에서는 주 2회로 완화)"
    if m:
        return [{"per_week": int(m.group(1))}]

    m = re.search(r"\((\d{1,2})/(\d{1,2})\)\s*후\s*주\s*(\d+)회", c)  # "FQ4 발표(9/29) 후 주 1회"
    if m:
        return [{"from_date": f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                 "per_week": int(m.group(3))}]

    m = re.search(r"발표\s*전\s*1~2회", c)
    if m:
        return [{"per_week": 1}]

    m = re.search(r"D-\d+\s*이내\s*[—-]+\s*주\s*(\d+)회", c)
    if m:
        return [{"per_week": int(m.group(1))}]

    m = re.search(r"주\s*(\d+)회", c)  # "주 1회", "주 1회 + 뉴스 트리거" 등 — 마지막 폴백
    if m:
        return [{"per_week": int(m.group(1))}]

    return None
