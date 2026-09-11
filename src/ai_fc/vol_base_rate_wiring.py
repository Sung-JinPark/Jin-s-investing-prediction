"""T03 — V13-VOL 검증 셀의 **기후 기저율 표시 배선** (V13-D6 경로).

## 지금 이 모듈이 아무것도 표시하지 않는 이유

배선 자격은 세 조건의 **논리곱**이다.

1. 홀드아웃 통과 — 계약 `publication.holdout_pass_cells`
2. 설계창 국면 가드 통과 — 계약 `publication.wiring_eligible_cells`
   (`vix25_h21` 은 홀드아웃을 통과했지만 설계창 late 국면이 4개뿐이라 여기서 걸린다)
3. **대응하는 등록 질문이 존재** — `CELL_QUESTION_MAP`

2026-09-11 현재 (1)∧(2) 를 통과하는 셀은 `rv_h5`·`rv_h21` 두 개이고, 둘 다 실현변동성
`P(RV21 > 0.1694)` 을 묻는데 레지스트리에 대응 질문이 **없다**. 등록된 `vix-25-90d` 는
90달력일 ≈ 63영업일이라 `vix25_h63` 에 대응하는데 그 셀은 홀드아웃에서 **실패**했다.

그래서 배선 대상은 **0건**이고 이 모듈은 빈 목록을 낸다. 코드를 미리 두는 이유는,
나중에 자격 셀이나 대응 질문이 생겼을 때 **설계를 다시 하지 않고** 지도만 채우면
켜지게 하기 위해서다. 조건을 만족하지 못하면 아무것도 표시하지 않는다(페일클로즈).

## 무엇을 내보내고 무엇을 내보내지 않는가

내보내는 것은 **원재료**뿐이다 — 기후 기저율(`clim_base_rate`) · 임계(`theta`/`K`) ·
지평(`h`) · 현 입력 수준. 모델의 셀 확률 `p`·`p_raw`·`band80` 은 **내보내지 않는다.**

앵커링 금지가 이유다. 질문별 매핑 확률을 LLM digest 에 주입하면 rN 이 트랙 확률의
재진술이 되고, 그 순간 원장은 LLM 캘리브레이션 표본이 아니라 트랙의 그림자가 된다.
기후 기저율은 트랙의 견해가 아니라 **역사 빈도**라서 outside view 재료로 정당하다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v13_vol.yaml")
LATEST_RELATIVE = Path("data/timeseries_v13/vol/vol_latest.json")

#: 셀 → 대응 등록 질문. **비어 있는 것이 현 상태다.**
#: 채울 때는 (a) 셀의 사건 정의와 질문의 판정기준이 같은 사건인지, (b) 지평이 일치하는지를
#: 사람이 확인하고 그 근거를 DECISIONS 에 남긴다. 근사 대응은 배선하지 않는다.
CELL_QUESTION_MAP: dict[str, str] = {}

#: 모델의 견해에 해당하는 필드 — 표시층으로 절대 넘기지 않는다.
FORBIDDEN_CELL_FIELDS = ("p", "p_raw", "band80", "se_raw", "derived_layer")


class VolWiringError(ValueError):
    """자격 미달 셀 배선 시도."""


@dataclass(frozen=True)
class WiringTarget:
    cell: str
    question_id: str
    climatological_base_rate: float
    threshold: float
    horizon_business_days: int
    target: str
    as_of: str

    def display_lines(self) -> list[str]:
        """카드에 나갈 줄. 모델 확률을 말하지 않는다."""
        return [
            f"참고 base rate(기후) {self.climatological_base_rate:.1%} — "
            f"{self.target} 임계 {self.threshold} · {self.horizon_business_days}영업일 · as_of {self.as_of}",
            "역사 빈도이며 모델 예측이 아니다. 공식 확률은 LLM rN 이다.",
        ]


def _contract(root: Path) -> dict[str, Any]:
    import yaml

    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        raise VolWiringError(f"V13-VOL 계약이 없다: {CONTRACT_RELATIVE}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


#: 자격 키가 실린 계약 섹션 후보 — 계약이 재구성돼도 조용히 빈 목록이 되지 않게 둘 다 본다.
_ELIGIBILITY_SECTIONS = ("publication", "development_protocol")


def _eligibility_lists(root: Path) -> tuple[set[str], set[str]]:
    contract = _contract(root)
    passed: set[str] = set()
    wiring: set[str] = set()
    for name in _ELIGIBILITY_SECTIONS:
        node = contract.get(name) or {}
        if not isinstance(node, dict):
            continue
        passed |= set(node.get("holdout_pass_cells") or [])
        wiring |= set(node.get("wiring_eligible_cells") or [])
    if not passed or not wiring:
        raise VolWiringError(
            "계약에서 홀드아웃 통과 셀 또는 배선 자격 셀 목록을 찾지 못했다 — "
            f"찾아본 섹션: {', '.join(_ELIGIBILITY_SECTIONS)}. "
            "자격을 못 읽으면 배선하지 않는다(페일클로즈)")
    return passed, wiring


def eligible_cells(root: Path) -> tuple[str, ...]:
    """(1) 홀드아웃 통과 ∧ (2) 설계창 국면 가드 통과 인 셀. 계약에서 읽는다.

    두 목록의 **교집합**인 이유: `vix25_h21` 은 홀드아웃을 통과했지만 설계창 late 국면이
    4개뿐이라 `wiring_eligible_cells` 에서 빠져 있다. 통과만 보면 그 셀이 새어 들어온다.
    """
    passed, wiring = _eligibility_lists(root)
    return tuple(sorted(passed & wiring))


def wiring_targets(root: Path, *, cell_question_map: dict[str, str] | None = None
                   ) -> list[WiringTarget]:
    """자격 셀 중 **대응 질문이 있는 것**만 배선한다. 조건 미달이면 빈 목록."""
    mapping = CELL_QUESTION_MAP if cell_question_map is None else cell_question_map
    if not mapping:
        return []

    eligible = set(eligible_cells(root))
    latest_path = root / LATEST_RELATIVE
    if not latest_path.is_file():
        return []
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    cells = latest.get("cells") or {}
    as_of = str(latest.get("as_of") or "")

    known_questions = _registered_question_ids(root)
    out: list[WiringTarget] = []
    for cell, question_id in sorted(mapping.items()):
        if cell not in eligible:
            raise VolWiringError(
                f"셀 {cell} 은 배선 자격이 없다 — 자격 셀: {', '.join(sorted(eligible)) or '(없음)'}")
        if question_id not in known_questions:
            raise VolWiringError(f"셀 {cell} 이 가리키는 질문 {question_id} 이 레지스트리에 없다")
        node = cells.get(cell)
        if not node:
            continue
        base = node.get("clim_base_rate")
        if base is None:
            continue
        out.append(WiringTarget(
            cell=cell, question_id=question_id,
            climatological_base_rate=float(base),
            threshold=float(node.get("theta") if node.get("theta") is not None else node.get("K", 0.0)),
            horizon_business_days=int(node.get("h") or 0),
            target=str(node.get("target") or ""), as_of=as_of))
    return out


def _registered_question_ids(root: Path) -> set[str]:
    import yaml

    path = root / "questions/registry.yaml"
    if not path.is_file():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(q.get("id")) for q in (data.get("questions") or [])}


def wiring_status(root: Path) -> dict[str, Any]:
    """왜 지금 0건인지를 그대로 인쇄할 수 있는 상태표."""
    eligible = eligible_cells(root)
    targets = wiring_targets(root)
    return {
        "eligible_cells": list(eligible),
        "mapped_cells": sorted(CELL_QUESTION_MAP),
        "targets": len(targets),
        "fail_closed": not targets,
        "reason": ("자격 셀은 있으나 대응 등록 질문이 없다 — 배선 0건(페일클로즈)"
                   if eligible and not CELL_QUESTION_MAP else
                   "자격 셀 자체가 없다 — 배선 0건(페일클로즈)" if not eligible else
                   "배선 활성"),
        "forbidden_fields_never_exported": list(FORBIDDEN_CELL_FIELDS),
    }
