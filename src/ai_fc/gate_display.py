"""P3 게이트 **표시층** — 게이트 산술은 여기서 한 글자도 바꾸지 않는다.

## 왜 이 모듈이 있는가

게이트 정본은 SQLite 뷰 `v_gate_status`(`db/schema.sql`)이고 그 산술은
`문항 수 = COUNT(DISTINCT question_id)` ∧ `Brier = AVG(brier)` — **문항 수는 문항 단위,
Brier 는 행 단위**라는 비대칭 위에 서 있다. 이 비대칭은 의도된 것이며 이 모듈은 그것을
바꾸지 않는다.

바꾸지 않는 대신 **드러낸다.** 같은 원장이 단위에 따라 다른 값을 낸다:

- 행 평균(게이트 정본): 0.15986
- 문항 등가중: 0.22079

전자는 문턱 0.18 아래이고 후자는 위다. 어느 쪽도 거짓이 아니며 **분모가 다를 뿐**이다.
표시층이 둘을 나란히 놓지 않으면 "통과"라는 인상만 남는다. 게다가 행 평균은 **쉬운 질문을
여러 회차 재예측**하면 낮아진다 — 게이트 문항 수에는 기여하지 않으면서 Brier 만 끌어내리는
표면이 열려 있다. 문항당 회차 분포를 함께 노출해 그 표면을 상시 감시한다.

## 이 모듈이 하지 않는 것

- 게이트 판정을 내리지 않는다. `gate_p3` 같은 불리언을 만들지 않는다.
- 원장·예측 파일을 쓰지 않는다. **읽기 전용**이다.
- 성적이 나쁜 행을 제외하지 않는다. primary 판정은 기존 오버라이드 규약을 그대로 읽을 뿐이다.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260910
CI_LEVEL = 0.90

#: 게이트 문턱 — **표시 목적으로만** 인용한다. 판정은 `v_gate_status` 가 한다.
GATE_BRIER_THRESHOLD = 0.18
GATE_QUESTION_THRESHOLD = 50


def _primary_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """원장에서 primary / 제외 행을 나눈다. 기존 규약(`c5_certificate.gate_status`)과 동일."""
    from .c5_certificate import read_forecasts, read_ledger, read_overrides

    rows = read_ledger(root)
    overrides = read_overrides(root)
    status = {f.forecast_id: f.research_status for f in read_forecasts(root)}
    primary, excluded = [], []
    for row in rows:
        fid = row.get("forecast_id", "")
        effective = overrides.get(fid, status.get(fid, "ok"))
        (excluded if effective == "failed" else primary).append(row)
    return primary, excluded


def _cluster_bootstrap_ci(rows: list[dict[str, Any]], *, replicates: int = BOOTSTRAP_REPLICATES,
                          seed: int = BOOTSTRAP_SEED, level: float = CI_LEVEL) -> list[float] | None:
    """**문항 클러스터** 부트스트랩으로 행 평균 Brier 의 CI 를 낸다.

    행을 독립으로 재표집하면 같은 질문의 여러 회차가 독립 표본인 것처럼 취급돼 CI 가 좁아진다.
    질문 단위로 통째로 재표집해야 회차 상관이 귀무 안에 보존된다.
    """
    if len(rows) < 2:
        return None
    by_question: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_question[row["question_id"]].append(float(row["brier"]))
    keys = sorted(by_question)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replicates):
        drawn: list[float] = []
        for _ in range(len(keys)):
            drawn.extend(by_question[keys[rng.randrange(len(keys))]])
        if drawn:
            means.append(sum(drawn) / len(drawn))
    if not means:
        return None
    means.sort()
    lo = (1 - level) / 2
    return [round(means[int(lo * len(means))], 6),
            round(means[min(len(means) - 1, int((1 - lo) * len(means)))], 6)]


def gate_display_facts(root: Path) -> dict[str, Any]:
    """표시층이 쓰는 이중 단위 사실표. 판정은 하지 않는다."""
    primary, excluded = _primary_rows(root)
    all_rows = primary + excluded

    briers_all = [float(r["brier"]) for r in all_rows]
    briers = [float(r["brier"]) for r in primary]
    probs = [float(r["probability"]) / 100 for r in primary]

    by_question: dict[str, list[float]] = defaultdict(list)
    for row in primary:
        by_question[row["question_id"]].append(float(row["brier"]))

    rows_mean = statistics.mean(briers) if briers else None
    per_question = (statistics.mean([statistics.mean(v) for v in by_question.values()])
                    if by_question else None)
    se = statistics.stdev(briers) / math.sqrt(len(briers)) if len(briers) > 1 else None
    margin_se = ((GATE_BRIER_THRESHOLD - rows_mean) / se) if (rows_mean is not None and se) else None
    rounds = {q: len(v) for q, v in sorted(by_question.items())}
    repeated = {q: n for q, n in rounds.items() if n > 1}

    return {
        "schema_version": 1,
        "gate_authority": "v_gate_status (db/schema.sql) — 행 평균이 정본. 이 모듈은 표시만 한다.",
        # 기존 이름은 삭제하지 않고 유지한다(계약: 이름 변경 가능, 삭제 금지).
        "brier_all_rows": round(statistics.mean(briers_all), 6) if briers_all else None,
        "brier_primary_rows": round(rows_mean, 6) if rows_mean is not None else None,
        "brier_per_question": round(per_question, 6) if per_question is not None else None,
        "se": round(se, 6) if se is not None else None,
        "ci90": _cluster_bootstrap_ci(primary),
        "ci90_method": f"문항 클러스터 부트스트랩 B={BOOTSTRAP_REPLICATES} seed={BOOTSTRAP_SEED}",
        "margin_se": round(margin_se, 4) if margin_se is not None else None,
        "sharpness_mean_p1mp": round(statistics.mean([p * (1 - p) for p in probs]), 6) if probs else None,
        "n_rows_all": len(all_rows),
        "n_rows_primary": len(primary),
        "n_excluded": len(excluded),
        "n_questions_primary": len(by_question),
        "rounds_per_question": rounds,
        "questions_with_multiple_rounds": repeated,
        "threshold_brier": GATE_BRIER_THRESHOLD,
        "threshold_questions": GATE_QUESTION_THRESHOLD,
        "unit_note": ("게이트 정본 = 행 평균. 문항 등가중은 **게이밍 감시용** 병기값이다 — "
                      "쉬운 질문을 여러 회차 재예측하면 행 평균은 내려가지만 문항 수는 늘지 않는다."),
        "status_wording": "미결",
    }


def gate_display_lines(facts: dict[str, Any]) -> list[str]:
    """대시보드·리포트가 그대로 쓸 수 있는 사람용 한 줄들. 판정 단어를 쓰지 않는다."""
    rows_mean = facts.get("brier_primary_rows")
    per_q = facts.get("brier_per_question")
    se = facts.get("se")
    ci = facts.get("ci90") or []
    margin = facts.get("margin_se")
    n_q = facts.get("n_questions_primary")
    lines = [
        f"게이트 정본(행 평균) {rows_mean:.5f}" if rows_mean is not None else "게이트 정본(행 평균) —",
        f"문항 등가중 {per_q:.5f}" if per_q is not None else "문항 등가중 —",
    ]
    if se is not None and margin is not None:
        lines.append(f"SE {se:.4f} · 문턱까지 {margin:.2f} SE")
    if len(ci) == 2:
        lines.append(f"CI90 [{ci[0]:.5f}, {ci[1]:.5f}] (문항 클러스터 부트스트랩)")
    lines.append(f"해소 문항 {n_q}/{facts.get('threshold_questions')} — **미결**")
    repeated = facts.get("questions_with_multiple_rounds") or {}
    if repeated:
        share = sum(repeated.values()) / max(1, facts.get("n_rows_primary") or 1)
        detail = " · ".join(f"{q} {n}회차" for q, n in sorted(repeated.items()))
        lines.append(f"복수 회차 문항 {len(repeated)}개 — primary 행의 {share:.0%} ({detail})")
    return lines
