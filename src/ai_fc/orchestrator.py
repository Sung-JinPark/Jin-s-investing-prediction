"""질문 1개의 생애주기: 로드 → 프리플라이트 → 리서치 ∥ → 추론 → 불변 기록 → DB.

불변식:
- 모든 파일 쓰기는 파이프라인 성공 후 마지막에, 배타적-생성으로만.
- 실패 시 쓰기 0 (부분 증거는 스크래치패드에만 덤프).
- 파일 생성 후에만 DB 동기화 (DB가 유일한 보관처가 되는 일 없음).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import yaml

from . import config
from . import files as F
from .agents.base import run_research
from .aggregator import AggregateResult, SingleRun
from .db import ingest, queries
from .llm import PipelineBudget
from .models import EvidenceBrief, Question
from .registry import load_registry


class PreflightError(RuntimeError):
    pass


@contextmanager
def _lock(lockfile: Path):
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = open(lockfile, "x")
    except FileExistsError:
        raise PreflightError(
            f"다른 실행이 진행 중 (락파일 존재: {lockfile}) — 중단됐다면 파일 삭제 후 재시도"
        ) from None
    try:
        yield
    finally:
        fd.close()
        lockfile.unlink(missing_ok=True)


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo(config.TZ_NAME)).replace(tzinfo=None)


def run_forecast(conn: sqlite3.Connection, root: Path, question_id: str,
                 n_agents: int = 2, budget_usd: float = config.DEFAULT_PIPELINE_BUDGET,
                 dry_run: bool = False) -> str:
    questions = {q.question_id: q for q in load_registry(root / "questions" / "registry.yaml")}
    q = questions.get(question_id)

    # ── 프리플라이트 (쓰기·과금 전 전부 검증) ──
    if q is None:
        raise PreflightError(f"registry에 없는 질문: {question_id}")
    if q.status != "active":
        raise PreflightError(f"{question_id}는 active가 아님 (status={q.status})")
    if q.deadline_kind == "tbd":
        raise PreflightError(
            f"{question_id}의 deadline이 미확정(null) — 발표일을 확인해 registry에 "
            f"deadline을 기록한 뒤 재실행하세요 (판정기준 불변 원칙상 자동 기록하지 않음)")
    if q.deadline_kind == "fixed" and q.deadline and date.today() > q.deadline:
        raise PreflightError(f"{question_id}는 기한({q.deadline}) 경과 — resolve 대상")
    # WS1 등록 필터 (v2): 컷오프 이후 신규 질문은 판별가능성 근거 필수
    from .registry import factory_filter_violation
    violation = factory_filter_violation(q)
    if violation:
        raise PreflightError(f"등록필터 위반 — {violation}")

    now = _now_kst()
    today = now.date()
    window_end = today + timedelta(days=q.rolling_days) if q.deadline_kind == "rolling" else None
    monthly = queries.month_cost(conn, now.year, now.month)
    if monthly >= config.MONTHLY_BUDGET:
        raise PreflightError(f"월 예산 초과: ${monthly:.2f} >= ${config.MONTHLY_BUDGET:.2f}")

    budget = PipelineBudget(limit_usd=budget_usd)
    api_key = config.get_api_key()
    if not api_key:
        raise PreflightError(
            "API 키 없음 — ANTHROPIC_API_KEY 환경변수 또는 ~/.ai_fc/anthropic_key.dpapi 필요")
    client = anthropic.Anthropic(api_key=api_key)
    scratch = root / "db" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    with _lock(root / "db" / ".ai_fc.lock"):
        # ── 리서치 (병렬) ──
        try:
            briefs = run_research(client, q, n_agents, budget, today)
        except Exception:
            raise
        _dump_scratch(scratch, question_id, "briefs", "\n\n====\n\n".join(
            f"[{b.profile}]\n{b.text}" for b in briefs))

        # ── 정량 참조 다이제스트 (Outside view 보조 — 실패해도 파이프라인 무영향) ──
        try:
            from . import base_rates
            aux_context, aux_meta = base_rates.ml_digest_with_meta(root, conn, question_id)
        except Exception:  # noqa: BLE001
            aux_context, aux_meta = None, None

        # ── 스냅샷 게이트: 추론 전 NOT FOUND 검증은 추론 결과에서 수행 ──
        # ── 추론 (aggregator 경유 — K회 중앙값 배관, 기본 K=1=SingleRun) ──
        if config.REASONING_RUNS > 1:
            from .aggregator import KRunMedian
            aggregator = KRunMedian(config.REASONING_RUNS)
        else:
            aggregator = SingleRun()
        agg: AggregateResult = aggregator.estimate(
            client, q, briefs, root / "prompts", budget, today, window_end,
            aux_context=aux_context)

        # required_snapshots 확정 실패 시 기록 없이 중단
        filled = {s.name: s.value for s in agg.result.snapshots_filled}
        missing = [s for s in q.required_snapshots
                   if filled.get(s, "NOT FOUND").strip().upper() == "NOT FOUND"]
        if missing:
            raise PreflightError(
                f"필수 스냅샷 미확정: {missing} — 기록하지 않고 중단 (NOT FOUND ≠ 추측)")

        # ── WS6: 기록 시점 ML 괴리 산출 + ≥15%p면 사후 정당화 리뷰 (확률 확정 후 —
        # 앵커링 방지 유지: ML 값은 여기서 처음 노출되며 확률은 이미 불변) ──
        ml_ref = queries.latest_ml_refs(conn, config.ML_REF_MAX_AGE_DAYS).get(question_id)
        ml_divergence_pp = None
        div_note, div_class = None, None
        if ml_ref is not None and not ml_ref.low_confidence:
            ml_divergence_pp = round(abs(agg.probability - ml_ref.prob * 100), 1)
            if ml_divergence_pp >= config.ML_DIVERGENCE_PP:
                review = _divergence_review(client, q, agg, ml_ref, budget)
                div_note, div_class = review.note, review.divergence_class

        # ── 기록 렌더 + 검증 ──
        rnd = F.next_round(root / "forecasts", question_id)
        stem = f"{today.isoformat()}_{question_id}_r{rnd}"
        phase = "DRY" if dry_run else "P1"
        # 시장내재확률 — 있으면 기록 (edge 시그널 발행은 P3 게이트 봉인, 기록만)
        mi = queries.latest_market_implied(conn, question_id, config.MARKET_REF_MAX_AGE_DAYS)
        fm = _frontmatter(q, agg, stem, now, phase, budget, briefs, window_end, filled, mi,
                          aux_context=aux_context, aux_meta=aux_meta)
        fm["ml_divergence_pp"] = ml_divergence_pp
        fm["divergence_note"] = div_note
        fm["divergence_class"] = div_class
        # WS7: 출처 등급 분포 + 1차 비율 → research_status 세분 (대표 뷰 정의 무변경)
        from .quality import research_quality, refine_research_status
        rq = research_quality(briefs)
        fm["research_quality"] = rq
        fm["research_status"] = refine_research_status(fm["research_status"], rq)
        errors = F.validate_new_record(fm)
        if errors:
            raise RuntimeError(f"기록 검증 실패: {errors}")
        content = _render_md(fm, q, agg, briefs)
        evidence = _render_evidence(stem, briefs, aux_context, rq)

        # ── 쓰기 (여기가 유일한 쓰기 지점) ──
        if dry_run:
            (scratch / f"{stem}.md").write_text(content, encoding="utf-8")
            (scratch / f"{stem}_evidence.md").write_text(evidence, encoding="utf-8")
            return (f"[DRY] {question_id} r{rnd}: {agg.probability}% "
                    f"(CI {agg.ci80_lo}~{agg.ci80_hi}) 비용 ${budget.spent_usd:.2f} "
                    f"→ 스크래치패드에만 기록")

        target = _write_records(root, today.year, stem, content, evidence)

        for b in briefs:
            queries.log_cost(conn, question_id, f"research:{b.profile}",
                             config.RESEARCH_MODEL, b.input_tokens, b.output_tokens, b.cost_usd)
        reasoning_cost = budget.spent_usd - sum(b.cost_usd for b in briefs)
        queries.log_cost(conn, question_id, "reasoning", config.REASONING_MODEL,
                         0, 0, max(reasoning_cost, 0.0))
        ingest.sync(conn, root)

    return (f"{question_id} r{rnd}: {agg.probability}% (CI {agg.ci80_lo}~{agg.ci80_hi}) "
            f"비용 ${budget.spent_usd:.2f} → {target.relative_to(root)}\n"
            f"  ※ P1 참고 의견 — 자금 결정의 단독 근거 아님 (P3 게이트 전)")


def _divergence_review(client, q: Question, agg: AggregateResult, ml_ref,
                       budget) -> "object":
    """WS6 사후 리뷰 — 확률 확정 후 ML 참조 공개, 괴리 분류·정당화만 요청."""
    from .llm import structured_call
    from .schemas import DivergenceReview

    system = ("너의 예측 확률은 이미 확정되어 변경할 수 없다. 지금 처음 공개되는 "
              "오픈웨이트 ML 앙상블 참조 확률과의 괴리를 분류하고 한 문단으로 정당화하라. "
              "이것은 기록용 사후 설명이다 — 확률 수정 제안 금지, 괴리의 구조적 원인만.")
    user = (f"[질문] {q.question}\n"
            f"[확정된 LLM 확률] {agg.probability}%\n"
            f"[ML 앙상블 참조] {ml_ref.prob:.0%} (run {ml_ref.run_ts})\n"
            f"[참조 모델 특성] 무조건부 zero-shot(이벤트 캘린더 무지)·경로 보정값 기준\n"
            "괴리의 가장 그럴듯한 구조적 원인을 divergence_class로 분류하고 note에 정당화하라.")
    review, _usage = structured_call(client, system, user, budget, DivergenceReview)
    return review


def _write_records(root: Path, year: int, stem: str, content: str, evidence: str) -> Path:
    """불변 기록 쓰기 — 순서 고정: evidence 먼저, 본문 마지막 (WS5 원자성 교정).

    본문이 커밋 포인트: "본문 존재 = 기록 완결" 불변식. 중간 크래시 시 남는 것은
    고아 evidence뿐(무해한 방향)이며 sync가 E6 경고로 검출한다.
    """
    target = root / "forecasts" / str(year) / f"{stem}.md"
    F.write_forecast_exclusive(target.with_name(f"{stem}_evidence.md"), evidence)
    F.write_forecast_exclusive(target, content)
    return target


def _dump_scratch(scratch: Path, qid: str, kind: str, text: str) -> None:
    ts = _now_kst().strftime("%Y%m%d-%H%M%S")
    (scratch / f"{ts}_{qid}_{kind}.txt").write_text(text, encoding="utf-8")


def _frontmatter(q: Question, agg: AggregateResult, stem: str, now: datetime,
                 phase: str, budget: PipelineBudget, briefs: list[EvidenceBrief],
                 window_end: date | None, filled: dict[str, str],
                 market_implied: tuple[float, str] | None = None,
                 aux_context: str | None = None,
                 aux_meta: dict | None = None) -> dict:
    from .models import sha256_text
    return {
        "forecast_id": stem,
        "question_id": q.question_id,
        "question_snapshot": q.question,
        "timestamp": now.strftime("%Y-%m-%d %H:%M KST"),
        "phase": phase,
        "model": config.REASONING_MODEL,
        "prompt_version": config.PROMPT_VERSION,
        "probability": agg.probability,
        "ci80": [agg.ci80_lo, agg.ci80_hi],
        "window_end": window_end.isoformat() if window_end else None,
        "snapshots": filled or {},
        # 기록만 — edge '시그널 발행'은 P3 게이트(해소 50+, Brier<0.18) 통과 후 (CLAUDE.md)
        "market_implied": round(market_implied[0], 4) if market_implied else None,
        "edge": (round(agg.probability / 100 - market_implied[0], 4)
                 if market_implied else None),
        # AUDIT-260715 T-3: 리서치 품질 태그 (신규 예측부터). 채점 정책 반영은
        # 사용자 결정 8-2 대기 — 현행 채점 동작(전량)은 무변화.
        "research_status": _research_status(briefs),
        "sources_count": sum(b.sources_count for b in briefs),
        "method": f"p1-pipeline/{len(briefs)}agents",
        "cost_usd": round(budget.spent_usd, 4),
        "ensemble_runs": agg.runs,
        "divergence": agg.divergence,
        # 섀도 extremization (α=√3, AIA/N-R) — LLM 0.5-hedging 편향의 참고 교정치.
        # **표시 전용** — 공식 확률 아님. 실 보정은 해소 100+ ML 게이트 뒤 (ARCHITECTURE §2-⑤)
        "shadow_extremized": _extremize(agg.probability),
        # WS4 재현성 스냅샷: 주입된 다이제스트의 해시 + 입력 좌표 (원문은 evidence 첨부)
        "digest_hash": sha256_text(aux_context) if aux_context else None,
        "digest_inputs": aux_meta,
        # v3 WS-B: 파이프라인 티어 기록 — 추후 티어별 Brier 분해 (lite 열등 시 폐지 판정용)
        "pipeline_tier": getattr(q, "tier", "standard"),
    }


def _extremize(prob_pct: int) -> int:
    """log-odds extremization: σ(α·logit(p)), α=√3. 1~99 클램프."""
    import math

    p = min(max(prob_pct / 100.0, 0.01), 0.99)
    z = config.EXTREMIZE_ALPHA * math.log(p / (1 - p))
    return min(99, max(1, int(round(100 / (1 + math.exp(-z))))))


def _research_status(briefs: list[EvidenceBrief]) -> str:
    """ok = 전 에이전트 출처 확보 / degraded = 일부 전멸 / failed = 전부 전멸 (사건 #3 유형)."""
    zeros = sum(1 for b in briefs if b.sources_count == 0)
    if zeros == 0:
        return "ok"
    return "failed" if zeros == len(briefs) else "degraded"


def _render_md(fm: dict, q: Question, agg: AggregateResult,
               briefs: list[EvidenceBrief]) -> str:
    r = agg.result
    fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False,
                             default_flow_style=None, width=1000).strip()
    adjustments = "\n".join(
        f"| {a.evidence} | {'↑' if a.direction == 'up' else '↓'} | "
        f"{'+' if a.direction == 'up' else '−'}{a.delta_pp:g}%p |"
        for a in r.adjustments)
    base_rates = "\n".join(f"- {b}" for b in r.base_rates)
    premortem = "\n".join(f"{i}. {p}" for i, p in enumerate(r.premortem, 1))
    reasons = "\n".join(f"  {i}. {k}" for i, k in enumerate(r.key_reasons, 1))
    observables = "\n".join(f"  {i}. {o}" for i, o in enumerate(r.observables, 1))
    unverified = "\n".join(f"- {u}" for u in r.unverified_notes) or "- 없음"

    return f"""---
{fm_yaml}
---

## [0] 질문 검증
{r.question_check}

## [1] Outside View — base rate (anchor: {r.anchor_pct}%)
참조 클래스: {r.reference_class}

{base_rates}

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
{adjustments}

## [3] 분해 트리
{r.decomposition}

## [4] Premortem — 이 예측이 크게 틀렸다면
{premortem}

## [5] 최종 출력
- **최종 확률: {r.probability}%** (80% CI: {r.ci80_lo}~{r.ci80_hi}%)
- **핵심 근거**:
{reasons}
- **관찰 지표**:
{observables}

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
{unverified}

## 리서치 구성
{", ".join(f"{b.profile}(출처 {b.sources_count})" for b in briefs)} — 증거 부록: `{fm["forecast_id"]}_evidence.md`
"""


def _render_evidence(stem: str, briefs: list[EvidenceBrief],
                     aux_context: str | None = None,
                     rq: dict | None = None) -> str:
    parts = [f"# 증거 부록 — {stem}\n\n> 리서치 서브에이전트 보고서 원문. 불변 — 수정 금지.\n"]
    if rq:
        c = rq.get("sources", {})
        parts.append(
            f"\n> 출처 등급 분포 (WS7): T1 {c.get('t1', 0)} · T2 {c.get('t2', 0)} · "
            f"T3 {c.get('t3', 0)} · T4 {c.get('t4', 0)} · 미등재 {c.get('unknown', 0)} — "
            f"primary_ratio(T1+T2) **{rq.get('primary_ratio', 0.0):.0%}**\n")
    for b in briefs:
        parts.append(f"\n---\n\n## [{b.profile}] (출처 {b.sources_count}개, "
                     f"${b.cost_usd:.2f})\n\n{b.text}")
    if aux_context:
        parts.append("\n---\n\n## [주입된 정량 다이제스트 원문] (WS4 재현성 — "
                     "frontmatter digest_hash의 원문)\n\n" + aux_context)
    return "\n".join(parts)
