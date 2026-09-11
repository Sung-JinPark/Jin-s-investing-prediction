"""T06 — 중간검토와 **부정 결과 선언 절차**.

## 왜 결과 전에 코드로 박아두는가

부정 선언은 늦게 정할수록 안 하게 된다. 20문항에서 성적이 나쁘면 "표본이 얇다"고 하고,
30문항에서 나쁘면 "이번 분기가 특이했다"고 하고, 49문항에서 나쁘면 "한 건만 더"라고 한다.
계약 `stopping_rules` 가 문턱과 조건을 **결과 보기 전에** 고정한 이유이고, 이 모듈은
그 조건을 사람이 다시 해석할 여지 없이 계산한다.

## 무엇을 계산하는가

- **중간검토** (계약 `interim_review_at_questions`, 현재 20·30): 도달하면 리포트를 낸다.
  행 평균 · 문항 등가중 · 문항 클러스터 부트스트랩 CI90 · 도메인 분해 · 예약 손실 시나리오.
- **부정 선언** (계약 `negative_declaration`): 문항 30 에서 **클러스터 CI90 하한 > 0.20**
  이면 `NEGATIVE_RESULT_DECLARED`. 트랙 종결 판정서를 쓰고 자금 결정 경로는 영구 차단을 유지한다.

## 이 모듈이 하지 않는 것

- 게이트 판정을 대신하지 않는다. 정본은 `v_gate_status` 다.
- "통과"를 쓰지 않는다. 계약 `status_wording.forbidden_words` 에 등재돼 있다.
- 원장을 쓰지 않는다. 상태 파일도 만들지 않는다 — 낡은 상태 파일은 잘못된 다음 행동을 부른다.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_RELATIVE = Path("questions/portfolio_prereg_v1.yaml")

#: 계약이 없거나 필드가 비면 쓰는 페일클로즈 기본값 — 통과 쪽으로 기울지 않는다.
FALLBACK_REVIEW_AT = (20, 30)
FALLBACK_NEGATIVE_AT = 30
FALLBACK_NEGATIVE_CI_LOWER = 0.20

NEGATIVE_STATE = "NEGATIVE_RESULT_DECLARED"
UNDECIDED_STATE = "미결"


@dataclass(frozen=True)
class ReviewVerdict:
    n_questions: int
    milestones_reached: tuple[int, ...]
    review_due: bool
    negative_declared: bool
    reason: str


def _contract(root: Path) -> dict[str, Any]:
    import yaml

    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def stopping_parameters(root: Path) -> dict[str, Any]:
    rules = (_contract(root).get("stopping_rules") or {})
    negative = rules.get("negative_declaration") or {}
    condition = str(negative.get("condition") or "")
    # 조건 문자열에서 문턱을 읽되, 못 읽으면 페일클로즈 기본값을 쓴다.
    threshold = FALLBACK_NEGATIVE_CI_LOWER
    for token in condition.replace(">", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        if 0.0 < value < 1.0:
            threshold = value
            break
    return {
        "review_at": tuple(rules.get("interim_review_at_questions") or FALLBACK_REVIEW_AT),
        "negative_at": int(negative.get("at_questions") or FALLBACK_NEGATIVE_AT),
        "negative_ci_lower_above": threshold,
        "negative_action": str(negative.get("action") or ""),
        "never": list(rules.get("never") or []),
        "status_wording": str(
            ((_contract(root).get("status_wording") or {}).get("current")) or UNDECIDED_STATE),
    }


def interim_review(root: Path) -> dict[str, Any]:
    """중간검토 리포트의 사실표. 판정 단어를 쓰지 않는다."""
    from .gate_display import gate_display_facts
    from .loss_decomp import counterfactual_row_mean, decompose_ledger, summarize

    facts = gate_display_facts(root)
    params = stopping_parameters(root)
    n_q = int(facts.get("n_questions_primary") or 0)

    reached = tuple(m for m in params["review_at"] if n_q >= m)
    ci = facts.get("ci90") or []
    ci_lower = ci[0] if len(ci) == 2 else None

    negative = (n_q >= params["negative_at"]
                and ci_lower is not None
                and ci_lower > params["negative_ci_lower_above"])

    domains = _domain_split(root)
    decomposition = summarize(decompose_ledger(root))
    # 예약 손실 — 같은 전제로 생산된 NFP 2건이 둘 다 NO 인 경우.
    reserved = counterfactual_row_mean(root, [(0.66, 0), (0.66, 0)])

    return {
        "n_questions_primary": n_q,
        "n_rows_primary": facts.get("n_rows_primary"),
        "brier_primary_rows": facts.get("brier_primary_rows"),
        "brier_per_question": facts.get("brier_per_question"),
        "se": facts.get("se"),
        "ci90": ci,
        "ci90_lower": ci_lower,
        "margin_se": facts.get("margin_se"),
        "threshold_brier": facts.get("threshold_brier"),
        "threshold_questions": facts.get("threshold_questions"),
        "milestones": params["review_at"],
        "milestones_reached": reached,
        "review_due": bool(reached),
        "negative_at": params["negative_at"],
        "negative_ci_lower_above": params["negative_ci_lower_above"],
        "negative_declared": negative,
        "state": NEGATIVE_STATE if negative else params["status_wording"],
        "domain_split": domains,
        "loss_decomposition": decomposition,
        "reserved_loss_scenario": reserved,
        "never": params["never"],
    }


def _domain_split(root: Path) -> list[dict[str, Any]]:
    from .c5_certificate import read_forecasts, read_ledger, read_overrides

    overrides = read_overrides(root)
    status = {f.forecast_id: f.research_status for f in read_forecasts(root)}
    by_domain: dict[str, list[float]] = defaultdict(list)
    questions: dict[str, set[str]] = defaultdict(set)
    for row in read_ledger(root):
        fid = row.get("forecast_id", "")
        if overrides.get(fid, status.get(fid, "ok")) == "failed":
            continue
        domain = str(row.get("domain") or "(미상)")
        by_domain[domain].append(float(row["brier"]))
        questions[domain].add(str(row.get("question_id") or ""))
    return [{"domain": d, "n_rows": len(v), "n_questions": len(questions[d]),
             "brier": round(statistics.mean(v), 6)}
            for d, v in sorted(by_domain.items(), key=lambda kv: -len(kv[1]))]


def verdict(root: Path) -> ReviewVerdict:
    review = interim_review(root)
    n_q = review["n_questions_primary"]
    if review["negative_declared"]:
        reason = (f"문항 {n_q} ≥ {review['negative_at']} 이고 클러스터 CI90 하한 "
                  f"{review['ci90_lower']:.5f} > {review['negative_ci_lower_above']} — "
                  "계약 negative_declaration 발동")
    elif review["review_due"]:
        reason = (f"중간검토 문턱 {', '.join(str(m) for m in review['milestones_reached'])} 도달 — "
                  "리포트 생성 대상")
    else:
        nxt = next((m for m in review["milestones"] if m > n_q), None)
        reason = (f"문항 {n_q} — 다음 중간검토 문턱 {nxt}" if nxt
                  else f"문항 {n_q} — 남은 중간검토 문턱 없음")
    return ReviewVerdict(n_questions=n_q,
                         milestones_reached=tuple(review["milestones_reached"]),
                         review_due=review["review_due"],
                         negative_declared=review["negative_declared"],
                         reason=reason)


def render_markdown(review: dict[str, Any], *, today: str) -> str:
    """중간검토 리포트 / 부정 선언 판정서 본문. 결과를 보고 쓰는 유일한 문서다."""
    negative = review["negative_declared"]
    title = ("P3 게이트 — **부정 결과 선언**" if negative else "P3 게이트 중간검토")

    def num(key: str, spec: str = ".5f") -> str:
        v = review.get(key)
        return format(v, spec) if isinstance(v, (int, float)) else "—"

    ci = review.get("ci90") or []
    ci_txt = f"[{ci[0]:.5f}, {ci[1]:.5f}]" if len(ci) == 2 else "—"

    lines = [
        f"# {title} ({today})",
        "",
        f"> 상태: **{review['state']}** · 해소 문항 {review['n_questions_primary']}"
        f"/{review['threshold_questions']} · primary 행 {review['n_rows_primary']}",
        "",
        "## 1. 두 단위",
        "",
        "| 단위 | 값 |",
        "|---|---|",
        f"| 행 평균 (게이트 정본) | {num('brier_primary_rows')} |",
        f"| 문항 등가중 | {num('brier_per_question')} |",
        f"| SE | {num('se', '.4f')} |",
        f"| 문턱까지 | {num('margin_se', '.2f')} SE |",
        f"| 클러스터 CI90 | {ci_txt} |",
        "",
        "## 2. 도메인 분해",
        "",
        "| 도메인 | 행 | 문항 | Brier |",
        "|---|---|---|---|",
    ]
    for row in review["domain_split"]:
        lines.append(f"| {row['domain']} | {row['n_rows']} | {row['n_questions']} | "
                     f"{row['brier']:.5f} |")

    decomp = review["loss_decomposition"]
    lines += ["", "## 3. 손실 3분해", ""]
    if decomp.get("mean_floor") is not None:
        lines += [
            f"평균 Brier {decomp['mean_brier_decomposed']:.5f} = 기대 바닥 "
            f"{decomp['mean_floor']:.5f} + 뽑기 {decomp['mean_draw']:+.5f} + "
            f"앵커 초과 {decomp['mean_anchor_excess']:+.5f}",
            "",
            "기대 바닥은 질문 선택의 값이라 등록에서만 고칠 수 있고, 뽑기는 기댓값 0 이며, "
            "앵커 초과만 예측 절차로 고칠 수 있는 축이다.",
        ]
    else:
        lines.append(f"분해 가능 {decomp['n_decomposed']}/{decomp['n_rows']}행 — "
                     "등록 시점 정직 확률이 기록된 문항이 아직 해소되지 않았다.")

    reserved = review["reserved_loss_scenario"]
    lines += [
        "",
        "## 4. 예약 손실 시나리오",
        "",
        f"같은 날 같은 전제로 생산된 NFP 2건(각 66%)이 둘 다 NO 이면 "
        f"행 평균 {reserved['before_mean']:.5f} → **{reserved['after_mean']:.5f}** "
        f"({reserved['before_rows']}행 → {reserved['after_rows']}행, 문턱 {reserved['threshold']}).",
        "",
        "## 5. 계약이 금지한 것",
        "",
    ]
    lines += [f"- `{item}`" for item in review["never"]]

    if negative:
        lines += [
            "",
            "## 6. 부정 결과 선언 — 발동 조건 충족",
            "",
            f"문항 {review['n_questions_primary']} ≥ {review['negative_at']} 이고 "
            f"클러스터 CI90 하한 {num('ci90_lower')} > {review['negative_ci_lower_above']}.",
            "",
            "**원인 분해는 §3 의 세 조각으로 시작한다.** 기대 바닥이 지배적이면 질문 선택의 실패이고, "
            "앵커 초과가 지배적이면 예측 절차의 실패다. 둘의 비중이 재도전 설계를 정한다.",
            "",
            "**재도전 조건**: 새 포트폴리오 계약(v2)을 결과를 보기 전에 커밋한다. 기존 등록분에 "
            "소급하지 않으며, 이 표본을 다시 쓰지 않는다. 자금 결정 경로는 영구 차단을 유지한다.",
            "",
            f"**계약이 정한 조치**: {review.get('negative_action') or '(계약 미기재)'}",
        ]
    else:
        lines += [
            "",
            "## 6. 부정 선언 조건 — 미충족",
            "",
            f"발동 조건은 문항 {review['negative_at']} 이상 ∧ 클러스터 CI90 하한 > "
            f"{review['negative_ci_lower_above']} 다. 현재 문항 {review['n_questions_primary']} · "
            f"CI90 하한 {num('ci90_lower')}.",
            "",
            "조건 미충족은 **통과가 아니다.** 게이트 상태 표현은 계약이 고정한 문구를 쓴다.",
        ]
    return "\n".join(lines) + "\n"
