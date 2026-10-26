"""T03 — V13-VOL 검증 셀의 **기후 기저율 표시 배선** (V13-D6 경로).

## 지금 이 모듈이 아무것도 표시하지 않는 이유

배선 자격은 네 조건의 **논리곱**이다.

1. 홀드아웃 통과 — 계약 `publication.holdout_pass_cells`
2. 설계창 국면 가드 통과 — 계약 `publication.wiring_eligible_cells`
   (`vix25_h21` 은 홀드아웃을 통과했지만 설계창 late 국면이 4개뿐이라 여기서 걸린다)
3. **라이브 판정불가(제한) 라벨이 없음** — `live_scoreboard.projection` 의 `claim_blocked`
   (계약 `live_claim_restriction` scope 4항: "배선 자격 — claim_blocked 셀은 자격 없음".
   사건 < 20 또는 국면 < 5 인 셀은 pass·BSS·배선 승격을 **주장할 수 없다**. 라벨은
   집계 시점의 누적값으로 매번 다시 계산되므로 표본이 자라면 저절로 떨어진다.)
4. **대응하는 등록 질문이 존재** — `CELL_QUESTION_MAP`

2026-09-11 현재 (1)∧(2) 를 통과하는 셀은 `rv_h5`·`rv_h21` 두 개이고, 둘 다 실현변동성
`P(RV21 > 0.1694)` 을 묻는데 레지스트리에 대응 질문이 **없다**. 등록된 `vix-25-90d` 는
90달력일 ≈ 63영업일이라 `vix25_h63` 에 대응하는데 그 셀은 홀드아웃에서 **실패**했다.
2026-10-22 현재 (3) 은 아홉 셀 전부에 걸려 있다(성숙 원점 h5 26 · h21 12 · h63 0 — 사건·국면
임계 미달). 그래서 (1)∧(2) 를 통과한 두 셀도 지금은 자격이 없다.

그래서 배선 대상은 **0건**이고 이 모듈은 빈 목록을 낸다. 코드를 미리 두는 이유는,
나중에 자격 셀이나 대응 질문이 생겼을 때 **설계를 다시 하지 않고** 지도만 채우면
켜지게 하기 위해서다. 조건을 만족하지 못하면 아무것도 표시하지 않는다(페일클로즈).
스코어보드를 읽거나 해석하지 못하면 라벨을 모르는 것이므로 **모든 셀을 차단**한다 —
"라벨이 안 보이니 자격 있음" 으로 기우는 쪽이 긍정 주장 누출이다.

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

#: 판정불가(제한) 차단 사유 접두사 — 스코어보드 자체 사유(`events<20` 등)와 구별되는 이 모듈의 사유.
CLAIM_REASON_SCOREBOARD_UNREADABLE = "scoreboard_unreadable"   # 스코어보드를 읽거나 해석하지 못함 → 전 셀 차단
CLAIM_REASON_SCOREBOARD_MISSING_CELL = "scoreboard_missing_cell"  # 스코어보드에 그 셀 항목이 없음 → 라벨 불명 → 차단


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


def contract_eligible_cells(root: Path) -> tuple[str, ...]:
    """(1) 홀드아웃 통과 ∧ (2) 설계창 국면 가드 통과 인 셀 — **계약만** 본 자격. 라이브 라벨은 아직 안 뺐다.

    두 목록의 **교집합**인 이유: `vix25_h21` 은 홀드아웃을 통과했지만 설계창 late 국면이
    4개뿐이라 `wiring_eligible_cells` 에서 빠져 있다. 통과만 보면 그 셀이 새어 들어온다.
    """
    passed, wiring = _eligibility_lists(root)
    return tuple(sorted(passed & wiring))


def _claim_blocked_cells(root: Path) -> tuple[dict[str, list[str]], set[str], str | None]:
    """라이브 스코어보드의 판정불가(제한) 라벨을 읽는다.

    반환 `(blocked, seen, error)`: blocked = `claim_blocked` 셀 → 스코어보드 사유 목록,
    seen = 스코어보드에 항목이 있는 셀 전부, error = 읽거나 해석하지 못했을 때의 사유(그 외 None).
    error 가 있으면 blocked·seen 은 비어 있고 호출자는 **전 셀을 차단**해야 한다 — 라벨 불명은
    '자격 있음' 이 아니다. 항목에 `claim_blocked` 불리언이 없는 것도 해석 실패로 친다(조용히 통과 금지).
    """
    try:
        from .timeseries_v13 import live_scoreboard

        board = live_scoreboard.projection(root)
        entries = board.get("cells") if isinstance(board, dict) else None
        if not isinstance(entries, list):
            raise VolWiringError("스코어보드 projection 에 cells 목록이 없다")
        blocked: dict[str, list[str]] = {}
        seen: set[str] = set()
        for entry in entries:
            name = entry.get("cell") if isinstance(entry, dict) else None
            flag = entry.get("claim_blocked") if isinstance(entry, dict) else None
            if not name or not isinstance(flag, bool):
                raise VolWiringError(f"스코어보드 셀 항목에 cell/claim_blocked 가 없다: {entry!r}")
            seen.add(str(name))
            if flag:
                reasons = [str(r) for r in (entry.get("claim_block_reasons") or [])]
                blocked[str(name)] = reasons or ["claim_blocked"]
        return blocked, seen, None
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 페일클로즈. 사유는 상태표에 그대로 싣는다.
        return {}, set(), f"{type(exc).__name__}: {exc}"


def eligibility(root: Path) -> dict[str, Any]:
    """자격 산출과 **왜 빠졌는지**를 함께 돌려준다.

    - `contract_eligible_cells`: (1)∧(2) — 계약만 본 자격
    - `eligible_cells`: (1)∧(2)∧(3) — 거기서 라이브 판정불가(제한) 셀을 뺀 것
    - `blocked_by_claim_restriction`: 계약 자격은 있으나 (3) 에서 빠진 셀(정렬). 홀드아웃·국면 가드에서
      이미 떨어진 셀은 여기 싣지 않는다 — 그 셀이 없는 이유는 라벨이 아니다.
    - `claim_block_reasons`: 위 셀 → 사유 목록(스코어보드 사유 그대로, 또는 이 모듈의 `scoreboard_*` 사유)
    - `scoreboard_error`: 스코어보드를 읽지 못했을 때의 사유. 이때 자격 셀은 **없다**.
    """
    contract_cells = contract_eligible_cells(root)
    blocked, seen, error = _claim_blocked_cells(root)
    reasons: dict[str, list[str]] = {}
    for cell in contract_cells:
        if error is not None:
            reasons[cell] = [f"{CLAIM_REASON_SCOREBOARD_UNREADABLE}: {error}"]
        elif cell in blocked:
            reasons[cell] = list(blocked[cell])
        elif cell not in seen:
            reasons[cell] = [CLAIM_REASON_SCOREBOARD_MISSING_CELL]
    return {
        "contract_eligible_cells": list(contract_cells),
        "eligible_cells": [cell for cell in contract_cells if cell not in reasons],
        "blocked_by_claim_restriction": sorted(reasons),
        "claim_block_reasons": reasons,
        "scoreboard_error": error,
    }


def eligible_cells(root: Path) -> tuple[str, ...]:
    """(1) 홀드아웃 통과 ∧ (2) 설계창 국면 가드 통과 ∧ (3) 라이브 판정불가(제한) 라벨 없음 인 셀.

    (1)∧(2) 는 계약에서, (3) 은 `live_scoreboard.projection` 에서 읽는다. 스코어보드를 못 읽으면
    빈 튜플이다(페일클로즈) — 사유는 `eligibility(root)["scoreboard_error"]` 에 있다.
    """
    return tuple(eligibility(root)["eligible_cells"])


def wiring_targets(root: Path, *, cell_question_map: dict[str, str] | None = None
                   ) -> list[WiringTarget]:
    """자격 셀 중 **대응 질문이 있는 것**만 배선한다. 조건 미달이면 빈 목록."""
    mapping = CELL_QUESTION_MAP if cell_question_map is None else cell_question_map
    if not mapping:
        return []
    return _targets_from(root, mapping, eligibility(root))


def _targets_from(root: Path, mapping: dict[str, str], info: dict[str, Any]) -> list[WiringTarget]:
    eligible = set(info["eligible_cells"])
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
            claim = info["claim_block_reasons"].get(cell)
            detail = f" — 판정불가(제한): {', '.join(claim)}" if claim else ""
            raise VolWiringError(
                f"셀 {cell} 은 배선 자격이 없다{detail} — 자격 셀: {', '.join(sorted(eligible)) or '(없음)'}")
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
    info = eligibility(root)
    eligible = info["eligible_cells"]
    targets = _targets_from(root, CELL_QUESTION_MAP, info) if CELL_QUESTION_MAP else []
    if info["scoreboard_error"] is not None:
        reason = ("라이브 스코어보드를 읽지 못해 판정불가(제한) 라벨을 알 수 없다 — "
                  f"전 셀 차단, 배선 0건(페일클로즈): {info['scoreboard_error']}")
    elif not info["contract_eligible_cells"]:
        reason = "자격 셀 자체가 없다 — 배선 0건(페일클로즈)"
    elif not eligible:
        reason = ("계약 자격 셀은 있으나 라이브 판정불가(제한) 라벨로 전부 차단 — 배선 0건(페일클로즈): "
                  + "; ".join(f"{cell} {', '.join(info['claim_block_reasons'][cell])}"
                              for cell in info["blocked_by_claim_restriction"]))
    elif not CELL_QUESTION_MAP:
        reason = "자격 셀은 있으나 대응 등록 질문이 없다 — 배선 0건(페일클로즈)"
    else:
        reason = "배선 활성"
    return {
        "eligible_cells": list(eligible),
        "contract_eligible_cells": info["contract_eligible_cells"],
        "blocked_by_claim_restriction": info["blocked_by_claim_restriction"],
        "claim_block_reasons": info["claim_block_reasons"],
        "scoreboard_error": info["scoreboard_error"],
        "mapped_cells": sorted(CELL_QUESTION_MAP),
        "targets": len(targets),
        "fail_closed": not targets,
        "reason": reason,
        "forbidden_fields_never_exported": list(FORBIDDEN_CELL_FIELDS),
    }
