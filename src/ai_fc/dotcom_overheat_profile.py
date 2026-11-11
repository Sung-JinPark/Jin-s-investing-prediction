"""닷컴 정점 대비 부문별 프로필 — 지수로 합치지 않고 지표별 닮음을 나란히 보인다(dotcom_overheat_profile_v1).

과열도 v6 는 단일 지수로는 자체 게이트를 넘지 못했다(v6.0·v6.1 탈락, DECISIONS 2026-11-11). 그러나 편입 시험(거짓 과열
없음 등)을 통과한 지표 다섯은 각자 뜻이 있다. 사용자 결정(2026-11-11 "프로필로 싣기")에 따라 그 지표들의 점수
(100 = 2000년 3월 정점 당시 상태, 0 = 평상)를 **합·평균·가중·종합 등급 없이** 표시한다. 대표값은 v5 그대로다.

기준값과 편입 결과는 v6.1 계약의 동결 블록에서 읽고, 그 지문을 프로필 계약에 적어 둔다 — 동결 블록이 바뀌면 닫힌다.
확률이 아니며 매매 신호가 아니다(reference_only).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import dotcom_overheat_v6 as v6

CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_profile_v1.yaml")
PROFILE_RELATIVE = Path("data/statistics/overheat/profile_latest.json")
CHANGE_SESSIONS = 20
HIGH_SESSIONS = 252
DAILY = {"daily", "daily_numerator"}


class OverheatProfileError(ValueError):
    pass


def admission_digest(source: dict[str, Any]) -> str:
    """편입된 지표와 그 기준값의 지문 — 프로필이 어떤 동결 결과 위에 서 있는지 묶는다."""
    frozen = source.get("frozen") or {}
    members = frozen.get("members") or {}
    admitted = sorted(sum(members.values(), []))
    body = {"contract": source.get("contract_id"), "members": {f: list(ids) for f, ids in sorted(members.items())},
            "anchors": {k: [frozen["anchors"][k]["zero"], frozen["anchors"][k]["peak"]] for k in admitted}}
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_contracts(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if profile.get("contract_id") != "dotcom_overheat_profile_v1":
        raise OverheatProfileError("profile contract id mismatch")
    source = v6.load_contract(root, v6.CONTRACT_RELATIVE)
    if source.get("contract_id") != profile.get("source_contract"):
        raise OverheatProfileError("profile contract points at another source contract")
    return profile, source


def _base(profile: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1, "dataset_id": "dotcom_overheat_profile", "contract_id": profile["contract_id"],
        "contract_version": profile["version"], "source_contract": profile["source_contract"],
        "probability_space": "reference_only", "model_use": False, "official_forecast_input": False,
        "trading_signal": False, "composite": None, "generated_at": now.isoformat(timespec="seconds"),
        "anchor_label": "2000년 3월 = 100 · 평상 = 0",
    }


def build_profile(root: Path, *, now: datetime | None = None, inp: v6.Inputs | None = None) -> dict[str, Any]:
    """오늘의 프로필. 합치지 않는다 — 지표마다 점수 하나."""
    now = now or datetime.now(timezone.utc)
    profile, source = load_contracts(root)
    base = _base(profile, now)
    frozen = source.get("frozen") or {}
    if not frozen.get("members") or admission_digest(source) != profile.get("source_admission_sha256"):
        return {**base, "status": "unavailable", "reason": "source admission differs from the profile contract"}
    inp = inp or v6.load_inputs(root)
    last = len(inp.sessions) - 1
    as_of = inp.sessions[last]
    base["as_of"] = as_of.isoformat()
    nasdaq_age = (now.astimezone(timezone.utc).date() - as_of).days
    if nasdaq_age > int(source["staleness_limits_days"]["daily"]):
        return {**base, "status": "hold", "reason": f"NASDAQ ledger is {nasdaq_age} days old"}
    drifted = set(v6.anchor_drift(inp, source))
    live, lagged = v6.Spec(source, lags=False), v6.Spec(source)
    families = []
    scored = 0
    for family, ids in frozen["members"].items():
        rows = []
        for key in ids:
            meta = v6._meta(source, key)
            anchor = {f: float(frozen["anchors"][key][f]) for f in ("zero", "peak")}
            row: dict[str, Any] = {"id": key, "label": meta["label"], "frequency": meta["frequency"]}
            item = None if key in drifted else v6.indicator_value(inp, key, last, live)
            if item is None:
                rows.append({**row, "status": "hold",
                             "reason": "anchor drift" if key in drifted else "no current observation"})
                continue
            value = v6.score(item["value"], anchor)
            row.update({"status": "ok", "score": int(round(value)), "score_raw": round(value, 1),
                        "beyond_peak": value >= 100, "below_normal": value < 0,
                        "period": item["period"], "age_days": item["age_days"], "basis": item["basis"]})
            if meta["frequency"] in DAILY:
                past = [(v6.score(prev["value"], anchor), inp.sessions[i].isoformat())
                        for i in range(max(0, last - HIGH_SESSIONS), last)
                        if (prev := v6.indicator_value(inp, key, i, lagged)) is not None]
                back = v6.indicator_value(inp, key, max(0, last - CHANGE_SESSIONS), lagged)
                row["change_4w"] = None if back is None else round(value - v6.score(back["value"], anchor), 1)
                high = max([*past, (value, as_of.isoformat())], key=lambda pair: pair[0])
                row["high_12m"] = {"value": int(round(high[0])), "date": high[1]}
            rows.append(row)
            scored += 1
        families.append({"id": family, "label": source["families"][family]["label"],
                         "status": "ok" if rows else "unmeasured", "indicators": rows})
    if not scored:
        return {**base, "status": "hold", "reason": "no indicator could be scored", "families": families}
    return {**base, "status": "ok", "families": families, "scored": scored, "nasdaq_age_days": nasdaq_age,
            "note": "합산 지수가 아니다. 확률이 아니며 사례 1개(2000년 3월) 기준의 닮음이다."}


def materialize(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """갱신 단계에서 프로필 산출물을 쓴다(파생 파일 — 매번 덮어쓴다, 원장이 아니다)."""
    payload = build_profile(root, now=now)
    path = root / PROFILE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload


def load_profile(root: Path, *, today: date | None = None) -> dict[str, Any]:
    """대시보드용 — 갱신 단계가 쓴 파일을 읽는다(빌드 때 원장을 훑지 않는다).

    파일을 그대로 믿지 않는다: 계약 지문이 다르거나 기준일이 일간 한도보다 오래됐으면 점수를 싣지 않는다.
    """
    closed = {"status": "unavailable", "probability_space": "reference_only", "composite": None}
    try:
        profile, source = load_contracts(root)
        payload = json.loads((root / PROFILE_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError):
        return {**closed, "reason": "profile not generated"}
    if admission_digest(source) != profile.get("source_admission_sha256") \
            or payload.get("contract_version") != profile.get("version"):
        return {**closed, "reason": "profile belongs to another contract state"}
    if payload.get("status") != "ok":
        return {**closed, "status": payload.get("status") or "unavailable", "reason": payload.get("reason"),
                "as_of": payload.get("as_of")}
    try:
        age = ((today or datetime.now(timezone.utc).date()) - date.fromisoformat(str(payload.get("as_of")))).days
    except ValueError:
        return {**closed, "reason": "profile has no as_of date"}
    if age > int(source["staleness_limits_days"]["daily"]):
        return {**closed, "status": "hold", "reason": f"profile is {age} days old", "as_of": payload.get("as_of")}
    return payload
