"""T07-2 — **사구간 감시.** 예측을 바꾸지 말고 질문을 바꾼다.

## 감시하는 것

계약 `dead_zone.band` = `[0.235, 0.765]`. 이 구간에 정직 확률이 떨어지는 질문은
**완전 캘리브레이션이어도** 기대 Brier 가 문턱 위다(`0.235 × 0.765 = 0.17978`).
`z < 0.7` 도 같은 말의 다른 표현이다 — `Φ(−0.7) = 0.242` 로 사구간 경계다.

## 왜 '경고'이고 '차단'이 아닌가 — 두 지점의 힘이 다르다

| 지점 | 조치 | 이유 |
|---|---|---|
| **등록 시점** | **차단** (`portfolio_prereg.evaluate_candidate`) | 여기서만 정직하게 개입할 수 있다 |
| **예측 시점** | **경고만** | 예측을 사구간 밖으로 미는 것은 **극단화**이고 8-8 이 금지한다 |

예측 시점 경고의 올바른 반응은 확률을 바꾸는 것이 아니라 **다음 질문을 다르게 설계하는 것**이다.
그래서 경고 문구가 "확률을 바꾸지 마라"를 먼저 말한다. 이 구별이 흐려지면 감시기가
극단화 유도 장치가 된다.

## 기등록 질문에는 소급하지 않는다

계약은 규칙의 소급 적용을 금지한다. 기등록 질문이 사구간에 있다는 사실은 **표시**하되
void·재분류·확률 조정으로 이어지지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BAND = (0.235, 0.765)
DEFAULT_Z_REJECT = 0.7

#: 예측 시점 경고에 반드시 붙는 문장. 없으면 감시기가 극단화 유도로 읽힌다.
NO_EXTREMIZATION = ("확률을 사구간 밖으로 밀지 마라 — 그것이 극단화이고 8-8 이 금지한다. "
                    "올바른 반응은 **다음 질문의 임계를 다시 두는 것**이다")


@dataclass(frozen=True)
class Warning_:
    question_id: str
    stage: str                 # registration | forecast
    kind: str                  # dead_zone | low_z | floor_over_cap
    value: float
    message: str
    blocking: bool


def _contract(root: Path) -> dict[str, Any]:
    import yaml

    path = root / "questions/portfolio_prereg_v1.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def band_and_thresholds(root: Path) -> tuple[tuple[float, float], float, float]:
    contract = _contract(root)
    dead = contract.get("dead_zone") or {}
    band = tuple(dead.get("band") or DEFAULT_BAND)
    cap = float(dead.get("per_question_expected_brier_cap") or 0.21)
    bands = ((contract.get("z_rule") or {}).get("bands") or {})
    reject = DEFAULT_Z_REJECT
    for token in str(bands.get("reject") or "").replace("<", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        if 0.0 < value < 2.0:
            reject = value
            break
    return (float(band[0]), float(band[1])), reject, cap


def check(root: Path, *, question_id: str, honest_probability: float | None,
          z: float | None, stage: str) -> list[Warning_]:
    """한 질문을 사구간·z·문항 상한에 비춘다.

    `stage="registration"` 이면 위반이 **차단**(blocking=True)이고,
    `stage="forecast"` 면 **경고만**이다 — 예측을 바꾸는 것은 극단화다.
    """
    (lo, hi), z_reject, cap = band_and_thresholds(root)
    blocking = stage == "registration"
    out: list[Warning_] = []

    if honest_probability is not None:
        p = float(honest_probability)
        if lo <= p <= hi:
            floor = p * (1.0 - p)
            msg = (f"정직 확률 {p:.3f} 이 사구간 [{lo}, {hi}] 안 — 완전 캘리브레이션이어도 "
                   f"기대 Brier {floor:.4f} 로 문턱 위다")
            out.append(Warning_(question_id, stage, "dead_zone", p,
                                msg if blocking else f"{msg}. {NO_EXTREMIZATION}", blocking))
        elif p * (1.0 - p) > cap:
            out.append(Warning_(question_id, stage, "floor_over_cap", p * (1.0 - p),
                                f"기대 Brier 바닥 {p * (1 - p):.4f} 가 문항 상한 {cap} 초과",
                                blocking))

    if z is not None and float(z) < z_reject:
        msg = f"z={float(z):.3f} < {z_reject} — 계약 z_rule.bands.reject"
        out.append(Warning_(question_id, stage, "low_z", float(z),
                            msg if blocking else f"{msg}. {NO_EXTREMIZATION}", blocking))
    return out


def scan_registry(root: Path) -> list[Warning_]:
    """기등록 질문 전체를 훑는다 — **표시 전용**이며 소급 조치로 이어지지 않는다."""
    from .c5_certificate import read_registry
    from .loss_decomp import honest_probability_of

    out: list[Warning_] = []
    for q in read_registry(root):
        if q.get("status") != "active":
            continue
        prereg = q.get("prereg") if isinstance(q.get("prereg"), dict) else {}
        honest, _ = honest_probability_of(q)
        z = prereg.get("z")
        out.extend(check(root, question_id=str(q.get("id")), honest_probability=honest,
                         z=float(z) if z is not None else None, stage="forecast"))
    return out


def scan_coverage(root: Path) -> dict[str, Any]:
    """감시가 **몇 문항을 실제로 보고 있는가.**

    정직 확률이 기록되지 않은 질문은 사구간 판정 자체가 불가능하다. 경고 0건을
    '사구간 문항이 없다'로 읽으면 안 되고, '볼 수 있는 것 중에 없다'로 읽어야 한다.
    """
    from .c5_certificate import read_registry
    from .loss_decomp import honest_probability_of

    active = [q for q in read_registry(root) if q.get("status") == "active"]
    covered = [q for q in active if honest_probability_of(q)[0] is not None]
    return {"active": len(active), "covered": len(covered),
            "uncovered": len(active) - len(covered)}


def watch_lines(warnings: list[Warning_], coverage: dict[str, Any] | None = None) -> list[str]:
    footer = ["기등록 질문에는 소급하지 않는다 — 표시일 뿐 void·재분류·확률 조정으로 가지 않는다"]
    if coverage:
        footer.insert(0, (f"감시 범위 {coverage['covered']}/{coverage['active']} 활성 문항 — "
                          f"정직 확률 미기록 {coverage['uncovered']}건은 판정 자체가 불가능하다. "
                          "경고 0건은 '사구간 문항이 없다'가 아니라 '볼 수 있는 것 중에 없다'다"))
    if not warnings:
        return ["사구간·z 경고 0건"] + footer
    by_kind: dict[str, int] = {}
    for w in warnings:
        by_kind[w.kind] = by_kind.get(w.kind, 0) + 1
    lines = ["사구간 감시 " + " · ".join(f"{k} {n}건" for k, n in sorted(by_kind.items()))]
    for w in warnings[:20]:
        lines.append(f"  {'차단' if w.blocking else '경고'} {w.question_id}: {w.message}")
    if len(warnings) > 20:
        lines.append(f"  … 외 {len(warnings) - 20}건")
    return lines + footer
