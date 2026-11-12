"""닷컴 대비 과열도 v8 — 판단 가중 평균 (dotcom_overheat_index_v8).

소유자 지시(2026-11-12)로 만든 **선언형** 값이다: 지표마다 중요도 점수(A 닷컴 경로 + B 과거 표본 근거 + C 정점 때 실제
방향)를 매기고, 같은 것을 재는 지표는 한 묶음으로 평균해 한 번만 세고, 그 점수를 가중으로 써서 오늘 값을 평균한다.

- 가중치는 판단값이다. 검증된 값이 아니다(v6.0·v6.1·v7 의 검증 기록은 그대로 남는다).
- 새로 재는 것은 없다. 값은 v5(카드 14개 지표)와 프로필(상승 속도 2종)이 이미 낸 것을 읽는다.
- 확률이 아니고 매매 신호가 아니다(reference_only). LLM 은 계산에 들어가지 않는다 — 패널 점수는 계약에 숫자로 동결돼 있다.
- 계약의 frozen 이 규칙에서 다시 유도한 값과 다르면 닫힌다(손으로 고친 가중으로 계산하지 않는다).
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from . import dotcom_overheat_v7 as v7

CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_index_v8.yaml")
RULE_KEYS = ("contract_id", "version", "readings", "points", "groups", "missing", "variants", "indicators", "panel")
VARIANTS = ("declared", "equal_groups", "equal_indicators")
CLOSED_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError,
                 yaml.YAMLError, json.JSONDecodeError)
STATISTICS_RELATIVE = Path("data/statistics/dotcom_statistics_latest.json")
V5_CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_index_v5.yaml")


class OverheatV8Error(ValueError):
    """계약이 규칙대로 채워지지 않았다."""


def load_contract(root: Path) -> dict[str, Any]:
    contract = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or contract.get("contract_id") != "dotcom_overheat_index_v8":
        raise OverheatV8Error("not the v8 contract")
    return contract


def _closed(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, "dataset_id": "dotcom_overheat_weighted",
            "contract_id": "dotcom_overheat_index_v8", "weights_basis": "declared_judgment",
            "probability_space": "reference_only", "model_use": False, "official_forecast_input": False,
            "trading_signal": False, "overheat_pct": None, **extra}


def _number(value: Any) -> float | None:
    """유한한 숫자만 값으로 친다 — bool·문자열·NaN·무한대·변환 불가 정수는 '값 없음'이다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _half_up(value: float) -> int:
    """화면 정수 — 58.5 는 59 다(파이썬 round 의 짝수 반올림을 쓰지 않는다)."""
    return int(math.floor(value + 0.5))


def rules_digest(contract: dict[str, Any]) -> str:
    body = {key: contract.get(key) for key in RULE_KEYS}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def evidence_by_candidate(v7_contract: dict[str, Any]) -> dict[str, str]:
    """v7 이 기록한 판정 — 다시 재지 않고 읽기만 한다."""
    return {row["id"]: row["evidence"] for row in v7.ranking_for_display(v7_contract)}


def derive_points(contract: dict[str, Any], v7_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """지표별 A·B·C 와 합계. A = 패널 중앙값(소유자 지정이 있으면 그 값), B·C = 기록된 숫자에서 기계적으로."""
    rule = contract["points"]
    medians = (contract.get("panel") or {}).get("median") or {}
    override = rule["A"].get("owner_override") or {}
    evidence = evidence_by_candidate(v7_contract)
    b_map, cut = rule["B"]["map"], rule["C"]["thresholds"]
    out: dict[str, dict[str, Any]] = {}
    for spec in contract["indicators"]:
        key = spec["id"]
        if key not in medians:
            raise OverheatV8Error(f"panel median missing: {key}")
        a = float(override[key]) if key in override else float(medians[key])
        if not rule["A"]["range"][0] <= a <= rule["A"]["range"][1]:
            raise OverheatV8Error(f"A out of range: {key}")
        label = evidence.get(spec["v7_id"], "unscored")
        if label not in b_map:
            raise OverheatV8Error(f"unknown evidence label: {label}")
        end = float(spec["dotcom_end_position"])
        c = 2.0 if end >= cut["two"] else 1.0 if end >= cut["one"] else 0.0
        out[key] = {"A": a, "B": float(b_map[label]), "C": c, "points": a + float(b_map[label]) + c,
                    "evidence": label, "a_source": "owner" if key in override else "panel"}
    return out


def weights(points: dict[str, float], groups: dict[str, str], live: list[str], variant: str = "declared") -> dict[str, float]:
    """살아 있는 지표의 가중(합 1). 묶음은 한 번만 센다 — 묶음 점수는 구성 지표 점수의 평균."""
    if variant not in VARIANTS:
        raise OverheatV8Error(f"unknown variant: {variant}")
    if not live:
        return {}
    if variant == "equal_indicators":
        return {key: 1.0 / len(live) for key in live}
    members: dict[str, list[str]] = {}
    for key in live:
        members.setdefault(groups[key], []).append(key)
    score = {g: (1.0 if variant == "equal_groups" else statistics.fmean(points[k] for k in ids))
             for g, ids in members.items()}
    total = sum(score.values())
    if total <= 0:
        raise OverheatV8Error("no positive group points")
    return {key: score[g] / total / len(ids) for g, ids in members.items() for key in ids}


def derive_frozen(contract: dict[str, Any], v7_contract: dict[str, Any]) -> dict[str, Any]:
    """규칙에서 유도한 동결 블록 — 계약의 frozen 은 이것과 같아야 한다."""
    rows = derive_points(contract, v7_contract)
    groups = {spec["id"]: spec["group"] for spec in contract["indicators"]}
    order = [spec["id"] for spec in contract["indicators"]]
    share = weights({k: v["points"] for k, v in rows.items()}, groups, order)
    group_points: dict[str, float] = {}
    for name in dict.fromkeys(groups.values()):
        group_points[name] = round(statistics.fmean(rows[k]["points"] for k in order if groups[k] == name), 4)
    return {
        "rules_sha256": rules_digest(contract),
        "v7_rules_sha256": v7.rules_digest(v7_contract),
        "indicators": {k: {**rows[k], "weight": round(share[k], 6)} for k in order},
        "group_points": group_points,
        "group_weights": {name: round(sum(share[k] for k in order if groups[k] == name), 6) for name in group_points},
    }


def frozen_problem(contract: dict[str, Any], v7_contract: dict[str, Any]) -> str | None:
    frozen = contract.get("frozen") or {}
    if not frozen or not (contract.get("panel") or {}).get("median"):
        return "contract not frozen"
    try:
        expected = derive_frozen(contract, v7_contract)
    except (OverheatV8Error, KeyError, TypeError, ValueError) as exc:
        return f"rules do not derive: {exc}"
    if frozen != expected:
        return "frozen block differs from what the rules derive"
    return None


def _profile_speed(profile: dict[str, Any]) -> dict[str, float]:
    if not isinstance(profile, dict) or profile.get("status") != "ok":
        return {}
    out: dict[str, float] = {}
    for family in profile.get("families") or []:
        for row in family.get("indicators") or []:
            value = _number(row.get("score_raw"))
            if row.get("status") == "ok" and value is not None:
                out[str(row.get("id"))] = value
    return out


def end_position_drift(root: Path) -> list[str]:
    """계약의 dotcom_end_position(정점 방향 C 의 근거)이 지금 통계 원장으로 다시 읽은 값과 같은 칸에 있는가.

    닷컴 구간은 과거지만 분기 자료는 개정된다. 개정이 33·67 문턱을 넘기면 C 점수의 근거가 사라진 것이므로 감시가 알린다
    (자동으로 고치지 않는다 — 계약 새 판이 필요하다). 카드 14개만 본다: 속도 2종은 개정되지 않는 NASDAQ 종가에서 나온다.
    """
    from .dotcom_overheat import dotcom_range_position

    contract = load_contract(root)
    v5 = yaml.safe_load((root / V5_CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    payload = json.loads((root / STATISTICS_RELATIVE).read_text(encoding="utf-8"))
    charts = {chart.get("id"): chart for chart in payload.get("charts") or []}
    specs = {spec["id"]: spec for spec in v5.get("indicators") or []}
    cut = contract["points"]["C"]["thresholds"]
    bucket = lambda value: 2 if value >= cut["two"] else 1 if value >= cut["one"] else 0  # noqa: E731
    problems = []
    for item in contract["indicators"]:
        if item["source"] != "v5":
            continue
        spec = specs.get(item["id"]) or {}
        chart = charts.get(spec.get("chart")) or {}
        series = next((s for s in chart.get("series") or []
                       if s.get("label") == spec.get("dotcom_series") and not s.get("provisional")), None)
        points = [p["value"] for p in (series or {}).get("points") or [] if _number(p.get("value")) is not None]
        now = dotcom_range_position(float(points[-1]), [float(v) for v in points], spec.get("direction")) if points else None
        if now is None:
            problems.append(f"{item['id']}: 닷컴 계열을 다시 읽지 못함")
        elif bucket(now) != bucket(float(item["dotcom_end_position"])):
            problems.append(f"{item['id']}: 계약 {item['dotcom_end_position']} → 지금 {now:.1f} (점수 칸이 바뀜)")
    return problems


def compute(root: Path, *, v5: dict[str, Any] | None = None, profile: dict[str, Any] | None = None,
            today: date | None = None) -> dict[str, Any]:
    """오늘의 판단 가중 평균. 어떤 경우에도 예외를 올리지 않는다 — 닫히면 화면은 이전 산식(v5)만 보인다."""
    try:
        contract = load_contract(root)
        v7_contract = v7.load_contract(root)
        problem = frozen_problem(contract, v7_contract)
        if problem:
            return _closed("unavailable", problem)
        if v5 is None:
            from .dotcom_overheat import compute_index
            v5 = compute_index(root)
        if profile is None:
            from .dotcom_overheat_profile import load_profile
            profile = load_profile(root, today=today)
        if not isinstance(v5, dict) or v5.get("status") != "ok":
            return _closed("hold", "v5 readings unavailable")
        return _evaluate(contract, v5, profile)
    except CLOSED_ERRORS as exc:
        return _closed("unavailable", f"{type(exc).__name__}: {exc}"[:200])


def _evaluate(contract: dict[str, Any], v5: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    frozen = contract["frozen"]
    low, high = (float(x) for x in contract["readings"]["clamp"])
    card = {str(row.get("id")): row for row in v5.get("indicators") or []}
    speed = _profile_speed(profile)
    groups = {spec["id"]: spec["group"] for spec in contract["indicators"]}
    points = {key: float(row["points"]) for key, row in frozen["indicators"].items()}
    readings: dict[str, float] = {}
    for spec in contract["indicators"]:
        key = spec["id"]
        value = _number(speed.get(key) if spec["source"] == "profile" else (card.get(key) or {}).get("pct"))
        if value is not None:
            readings[key] = value
    live = [spec["id"] for spec in contract["indicators"] if spec["id"] in readings]
    missing = [spec["id"] for spec in contract["indicators"] if spec["id"] not in readings]
    live_weight = sum(float(frozen["indicators"][key]["weight"]) for key in live)
    speed_live = any(spec["source"] == "profile" and spec["id"] in readings for spec in contract["indicators"])
    base = {
        "dataset_id": "dotcom_overheat_weighted", "contract_id": contract["contract_id"],
        "contract_version": contract["version"], "probability_space": "reference_only", "model_use": False,
        "official_forecast_input": False, "trading_signal": False, "weights_basis": "declared_judgment",
        # 속도 값의 기준일과 나이 한도 — 화면이 프로필과 같은 나이 판정을 건다(낡으면 화면도 이전 산식으로 내려간다).
        # v8 이 실제로 읽은 속도 지표가 있을 때만 싣는다(프로필의 다른 부문 행은 v8 의 입력이 아니다).
        "speed_as_of": profile.get("as_of") if speed_live else None,
        "speed_max_age_days": _number(profile.get("max_age_days")) if speed_live else None,
        "previous_formula": {"contract_id": v5.get("contract_id"), "overheat_pct": v5.get("overheat_pct")},
        "live_weight": round(live_weight, 4), "missing": missing,
    }
    if live_weight < float(contract["missing"]["hold_below_live_weight"]):
        return {**base, "status": "hold", "overheat_pct": None,
                "reason": f"live weight {live_weight:.2f} below the contract minimum"}
    # 매일 움직이는 묶음이 통째로 없으면 재배분하지 않고 닫는다. 재배분하면 시장이 그대로인데 숫자가 58 → 66 으로 뛰고,
    # 화면 시점의 나이 판정(낡으면 이전 산식)과 빌드 시점의 결과가 서로 달라진다 — 두 경로가 같은 곳(v5)에 닿게 한다.
    absent = [name for name in contract["missing"].get("required_groups") or []
              if not any(groups[key] == name for key in live)]
    if absent:
        return {**base, "status": "hold", "overheat_pct": None,
                "reason": f"required group has no reading: {', '.join(absent)}"}
    clamped = {key: min(high, max(low, readings[key])) for key in live}
    cut = {key: "high" if readings[key] > high else "low" if readings[key] < low else None for key in live}
    values: dict[str, float] = {}
    shares: dict[str, dict[str, float]] = {}
    for variant in VARIANTS:
        shares[variant] = weights(points, groups, live, variant)
        values[variant] = sum(shares[variant][key] * clamped[key] for key in live)
    share = shares["declared"]
    order = sorted(VARIANTS, key=lambda name: values[name])
    labels = contract["groups"]["labels"]
    group_rows = []
    for name in dict.fromkeys(groups.values()):
        ids = [key for key in live if groups[key] == name]
        if not ids:
            continue
        weight = sum(share[key] for key in ids)
        sides = {cut[key] for key in ids} - {None}
        group_rows.append({
            "id": name, "label": labels.get(name, name), "members": ids,
            "clamped": "both" if len(sides) == 2 else next(iter(sides), None),
            "points": round(statistics.fmean(points[key] for key in ids), 1), "weight_pct": round(100 * weight, 1),
            "reading": round(statistics.fmean(clamped[key] for key in ids), 1),
            "contribution": round(sum(share[key] * clamped[key] for key in ids), 1),
        })
    indicator_rows = []
    for spec in contract["indicators"]:
        key = spec["id"]
        row = frozen["indicators"][key]
        item = {"id": key, "label": spec["label"], "group": spec["group"],
                "group_label": labels.get(spec["group"], spec["group"]), "source": spec["source"],
                "A": row["A"], "B": row["B"], "C": row["C"], "points": row["points"], "evidence": row["evidence"],
                "a_source": row["a_source"], "status": "ok" if key in readings else "missing"}
        if key in readings:
            item.update({"reading": round(readings[key], 1), "clamped": cut[key],
                         "weight_pct": round(100 * share[key], 1),
                         "contribution": round(share[key] * clamped[key], 1)})
        indicator_rows.append(item)
    value = values["declared"]
    return {
        **base, "status": "ok", "overheat_pct": _half_up(value), "value_raw": round(value, 1),
        "range": {"low": _half_up(values[order[0]]), "high": _half_up(values[order[-1]]),
                  "low_raw": round(values[order[0]], 1), "high_raw": round(values[order[-1]], 1),
                  "low_variant": order[0], "high_variant": order[-1]},
        "variants": {name: round(values[name], 1) for name in VARIANTS},
        "clamp": [low, high], "clamped_high_count": sum(1 for key in live if cut[key] == "high"),
        "clamped_low_count": sum(1 for key in live if cut[key] == "low"),
        "beyond_peak_count": sum(1 for key in live if readings[key] > 100.0),
        "included": len(live), "groups": sorted(group_rows, key=lambda r: -r["contribution"]),
        "indicators": indicator_rows,
        "note": "판단 가중 평균이다. 가중치는 판단값이며 검증된 값이 아니다. 확률이 아니다.",
    }
