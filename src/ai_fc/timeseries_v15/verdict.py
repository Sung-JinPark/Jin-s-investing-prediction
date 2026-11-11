"""V15 동결 판정 규칙 — `frozen_verdict_code_hash` 대상(이 파일 한 개).

r1 판정 규칙 + r2 개정(A5 비열등 가족 분리·m=12 고정·가족별 기계 컷 T*·마감 컷·정렬·블록 연결 순서).
- 쌍: (팔 X, 지평 h, 원점 o) 마다 X 행과 A0 행이 모두 컷 이내 해소, excluded 없음, seed 같음(CRN),
  두 해소 행의 calendar_hash 가 예측 행과 같음(다르면 calendar_drift 제외).
- 재표본: default_rng([20261111, h]), B=5000, 시작점 U{0..n−ℓ} 에서 b=ceil(n/ℓ)개, 블록 내부 원점 순서
  유지·뽑힌 순서대로 연결·앞 n 개(Künsch). 같은 (h, n) 의 모든 비교는 같은 색인 행렬을 쓴다.
- 우월성(A1~A4 × {5,21,63}, Holm m=12 고정): CI90 상한 < 0, Holm 후 p < α, 에피소드 과반·최유리 블록 제거.
- 비열등(A5 × {5,21,63}, Holm m=3): Δ_rel = Σd/Σc, CI90 상한 < +0.01, p_NI < α.
- T*_F: 해소 원장을 resolved_at 순으로 볼 때 F 의 모든 (팔,지평)이 data 조건을 처음 동시에 충족한
  해소 행의 resolved_at. 마감 컷 2028-06-30T23:59:59Z. 판정 JSON = f(원장, 계약, 이 파일).
판정은 승격이 아니다(126세션 + 소유자 승인). 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .arms import NONINFERIORITY_FAMILY, SUPERIORITY_FAMILY, VERDICT_HORIZONS

REPLICATES = 5000
BOOTSTRAP_SEED = 20261111
BLOCK_LENGTH = {5: 2, 21: 5, 63: 13}
MIN_ORIGINS = {5: 26, 21: 26, 63: 39}
DISTINCT_FLOOR = 1000
NI_MARGIN = 0.01
ALPHA = 0.05
CI_QUANTILES = (0.05, 0.95)
DEADLINE_CUT_UTC = "2028-06-30T23:59:59Z"
FAMILIES = {"superiority": SUPERIORITY_FAMILY, "noninferiority": NONINFERIORITY_FAMILY}
NOTICE = "참고 의견, 매매 신호 아님 — 판정은 승격이 아니다(126세션 + 소유자 승인)"


def parse_utc(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        raise ValueError(f"시각에 시간대가 없다: {value!r}")
    return stamp.astimezone(timezone.utc)


def iso_utc(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── 조합 산술·data 조건 ───────────────────────────────────────────────────────


def blocks_drawn(n: int, h: int) -> int:
    return math.ceil(n / BLOCK_LENGTH[h])


def distinct_resamples(n: int, h: int) -> int:
    ell = BLOCK_LENGTH[h]
    if n < ell:
        return 0
    b = blocks_drawn(n, h)
    return math.comb(n - ell + b, b)


def data_condition(n: int, h: int) -> str | None:
    """None = 충족. 아니면 미달 사유."""
    if n < MIN_ORIGINS[h]:
        return "minimum_origins"
    if n // BLOCK_LENGTH[h] < 3:
        return "episodes_k_below_3"
    if distinct_resamples(n, h) < DISTINCT_FLOOR:
        return "distinct_resample_floor"
    return None


def required_n(h: int) -> int:
    n = 1
    while data_condition(n, h) is not None:
        n += 1
    return n


# ── 재표본·통계 (판정·MDE 공용 — 구현이 하나라 불일치가 생길 수 없다) ─────────


def bootstrap_indices(n: int, h: int, *, replicates: int = REPLICATES) -> np.ndarray:
    ell = BLOCK_LENGTH[h]
    if n < ell:
        raise ValueError(f"n={n} < ℓ={ell}")
    b = blocks_drawn(n, h)
    rng = np.random.default_rng([BOOTSTRAP_SEED, h])
    starts = rng.integers(0, n - ell + 1, size=(replicates, b))
    index = starts[:, :, None] + np.arange(ell)[None, None, :]
    return index.reshape(replicates, b * ell)[:, :n]


def _bootstrap_means(values: np.ndarray, index: np.ndarray) -> np.ndarray:
    """values: (n,) 또는 (r, n) — 재표본 평균 (B,) 또는 (r, B)."""
    return np.take(np.asarray(values, dtype=float), index, axis=-1).mean(axis=-1)


def _ratio_resamples(d: np.ndarray, c: np.ndarray, index: np.ndarray) -> np.ndarray:
    return (np.take(np.asarray(d, dtype=float), index, axis=-1).sum(axis=-1)
            / np.take(np.asarray(c, dtype=float), index, axis=-1).sum(axis=-1))


def _pvalue(statistics: np.ndarray, threshold: float = 0.0) -> float:
    """p = (1 + #{stat_b ≥ threshold}) / (B + 1) — 동점은 ≥ 로 센다(보수)."""
    values = np.asarray(statistics, dtype=float)
    return float((1 + int(np.sum(values >= threshold))) / (values.shape[-1] + 1))


def _ci(statistics: np.ndarray) -> tuple[float, float]:
    low, high = np.quantile(np.asarray(statistics, dtype=float), CI_QUANTILES, method="linear")
    return float(low), float(high)


def _episode_stats(d: np.ndarray, h: int) -> dict[str, Any]:
    """첫 원점부터 길이 ℓ 의 겹치지 않는 블록 K 개. 꼬리는 에피소드 수에서만 뺀다."""
    values = np.asarray(d, dtype=float)
    ell = BLOCK_LENGTH[h]
    n = len(values)
    k = n // ell
    required = max(3, k // 2 + 1)
    if k == 0:
        return {"blocks": 0, "required": required, "negative_blocks": 0, "block_means": [],
                "best_block": None, "mean_without_best_block": None, "tail_origins": n, "ok": False}
    block_means = values[: k * ell].reshape(k, ell).mean(axis=1)
    negative = int(np.sum(block_means < 0.0))
    best = int(np.argmin(block_means))
    mask = np.ones(n, dtype=bool)
    mask[best * ell:(best + 1) * ell] = False
    without_best = float(np.mean(values[mask])) if mask.any() else math.nan
    return {
        "blocks": k, "required": required, "negative_blocks": negative,
        "block_means": [float(v) for v in block_means], "best_block": best,
        "mean_without_best_block": without_best, "tail_origins": n - k * ell,
        "ok": bool(negative >= required and without_best < 0.0),
    }


def holm(pvalues: Mapping[Any, float], alpha: float = ALPHA) -> dict[Any, bool]:
    """Holm 단계하강 — m 은 입력 크기 고정(insufficient 는 p=1 로 넣는다)."""
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], str(item[0])))
    m = len(ordered)
    rejected = {key: False for key in pvalues}
    for rank, (key, value) in enumerate(ordered):
        if value < alpha / (m - rank):
            rejected[key] = True
        else:
            break
    return rejected


def superiority_statistics(d: Sequence[float], h: int) -> dict[str, Any]:
    values = np.asarray(d, dtype=float)
    index = bootstrap_indices(len(values), h)
    means = _bootstrap_means(values, index)
    low, high = _ci(means)
    return {"n": len(values), "mean_d": float(np.mean(values)), "ci90": [low, high],
            "p": _pvalue(means, 0.0), "episodes": _episode_stats(values, h)}


def noninferiority_statistics(d: Sequence[float], c: Sequence[float], h: int) -> dict[str, Any]:
    dv = np.asarray(d, dtype=float)
    cv = np.asarray(c, dtype=float)
    index = bootstrap_indices(len(dv), h)
    ratios = _ratio_resamples(dv, cv, index)
    low, high = _ci(ratios)
    return {"n": len(dv), "delta_rel": float(np.sum(dv) / np.sum(cv)), "ci90": [low, high],
            "p_ni": _pvalue(ratios, NI_MARGIN)}


# ── 원장 → 쌍 ────────────────────────────────────────────────────────────────


def _resolution_index(resolutions: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in resolutions:
        if row.get("label_basis") != "xnas_v1":
            continue
        grouped.setdefault((str(row["forecast_id"]), int(row["horizon"])), []).append(dict(row))
    for rows in grouped.values():
        rows.sort(key=lambda item: (parse_utc(item["resolved_at"]), str(item["resolution_id"])))
    return grouped


def _value_at(rows: list[dict[str, Any]], cut: datetime) -> dict[str, Any] | None:
    """컷 이내 마지막 정정값(같은 키의 supersedes 행 포함)."""
    eligible = [row for row in rows if parse_utc(row["resolved_at"]) <= cut]
    return eligible[-1] if eligible else None


def build_candidate_pairs(
    shadow: Sequence[Mapping[str, Any]],
    issuance: Sequence[Mapping[str, Any]],
    resolutions: Sequence[Mapping[str, Any]],
    *,
    first_origin_not_before: str | None = None,
) -> dict[tuple[str, int], dict[str, Any]]:
    """(팔, 지평) → {pairs: [...], excluded: {사유: 수}}. pair = (origin, ready_at, X·A0 해소 행 목록)."""
    resolved = _resolution_index(resolutions)
    a0_by_v8: dict[str, dict[str, Any]] = {}
    a0_by_week: dict[str, dict[str, Any]] = {}
    for row in shadow:
        if row.get("arm") == "A0":
            a0_by_v8.setdefault(str(row.get("v8_forecast_id")), dict(row))
            a0_by_week.setdefault(str(row.get("iso_week")), dict(row))
    out: dict[tuple[str, int], dict[str, Any]] = {
        (arm, h): {"pairs": [], "excluded": []} for arm, h in SUPERIORITY_FAMILY + NONINFERIORITY_FAMILY
    }

    def exclude(arm: str, reason: str, issued_at: Any) -> None:
        stamp = parse_utc(issued_at) if issued_at else parse_utc(DEADLINE_CUT_UTC)
        for h in VERDICT_HORIZONS:
            out[(arm, h)]["excluded"].append((reason, stamp))

    candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for row in shadow:
        if row.get("arm") in ("A1", "A2", "A3", "A4"):
            candidates.append((dict(row), a0_by_v8.get(str(row.get("v8_forecast_id")))))
    for row in issuance:
        if row.get("arm") == "A5":
            candidates.append((dict(row), a0_by_week.get(str(row.get("iso_week")))))
    for arm_row, a0_row in candidates:
        arm = str(arm_row["arm"])
        origin = str(arm_row["origin"])
        if first_origin_not_before and origin < str(first_origin_not_before):
            exclude(arm, "before_first_origin", arm_row.get("issued_at"))
            continue
        if a0_row is None:
            exclude(arm, "a0_missing", arm_row.get("issued_at"))
            continue
        if arm == "A5" and str(a0_row["origin"]) != origin:
            exclude(arm, "origin_mismatch", arm_row.get("issued_at"))
            continue
        if arm_row.get("excluded_reasons") or a0_row.get("excluded_reasons"):
            reasons = list(arm_row.get("excluded_reasons") or []) + list(a0_row.get("excluded_reasons") or [])
            exclude(arm, str(sorted(set(reasons))[0]), arm_row.get("issued_at"))
            continue
        crn_ok = int(arm_row["seed"]) == int(a0_row["seed"])
        for h in VERDICT_HORIZONS:
            x_rows = resolved.get((str(arm_row["forecast_id"]), h), [])
            a_rows = resolved.get((str(a0_row["forecast_id"]), h), [])
            if not x_rows or not a_rows:
                continue
            out[(arm, h)]["pairs"].append({
                "origin": origin,
                "ready_at": max(parse_utc(x_rows[0]["resolved_at"]), parse_utc(a_rows[0]["resolved_at"])),
                "crn_ok": crn_ok,
                "x_rows": x_rows, "a0_rows": a_rows,
                "x_calendar_hash": arm_row.get("calendar_hash"),
                "a0_calendar_hash": a0_row.get("calendar_hash"),
            })
    return out


def _pairs_at_cut(candidate: dict[str, Any], cut: datetime) -> dict[str, Any]:
    d: list[tuple[str, float, float]] = []
    crn_violations = 0
    calendar_drift = 0
    for pair in candidate["pairs"]:
        if pair["ready_at"] > cut:
            continue
        x_value = _value_at(pair["x_rows"], cut)
        a_value = _value_at(pair["a0_rows"], cut)
        if x_value is None or a_value is None:
            continue
        if (x_value.get("calendar_hash") != pair["x_calendar_hash"]
                or a_value.get("calendar_hash") != pair["a0_calendar_hash"]):
            calendar_drift += 1
            continue
        if not pair["crn_ok"]:
            crn_violations += 1
            continue
        crps_x = float(x_value["crps_model"])
        crps_a0 = float(a_value["crps_model"])
        d.append((pair["origin"], crps_x - crps_a0, crps_a0))
    d.sort(key=lambda item: item[0])  # 원점 날짜 오름차순 — 원장 추출 순서 무관
    return {"origins": [o for o, _, _ in d], "d": [v for _, v, _ in d], "c": [c for _, _, c in d],
            "crn_violations": crn_violations, "calendar_drift": calendar_drift}


def _excluded_at_cut(candidate: dict[str, Any], cut: datetime) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason, stamp in candidate["excluded"]:
        if stamp <= cut:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _event_times(candidate: dict[str, Any], deadline: datetime) -> set[datetime]:
    """쌍 수가 바뀔 수 있는 시각 — 쌍 성립(ready_at)과 모든 해소·정정 행의 resolved_at(마감 이내)."""
    times = {pair["ready_at"] for pair in candidate["pairs"] if pair["ready_at"] <= deadline}
    for pair in candidate["pairs"]:
        for row in list(pair["x_rows"]) + list(pair["a0_rows"]):
            stamp = parse_utc(row["resolved_at"])
            if stamp <= deadline:
                times.add(stamp)
    return times


def _member_ready_at(candidate: dict[str, Any], h: int, stamp: datetime) -> bool:
    return len(_pairs_at_cut(candidate, stamp)["d"]) >= required_n(h)


def member_ready_time(candidate: dict[str, Any], h: int, deadline: datetime) -> datetime | None:
    """그 (팔,지평)이 data 조건을 처음 충족하는 해소 시각(마감 이내) — 보고용·T* 의 하한."""
    for stamp in sorted(_event_times(candidate, deadline)):
        if _member_ready_at(candidate, h, stamp):
            return stamp
    return None


def family_cut(
    candidates: Mapping[tuple[str, int], dict[str, Any]], family: str,
) -> tuple[datetime | None, dict[str, str | None]]:
    """T*_F = F 의 모든 (팔,지평)이 data 조건을 **처음 동시에** 충족하는 시각.

    구성원별 최초 도달 시각의 max 는 하한일 뿐이다 — 달력 정정(calendar_drift) 행이 쌍을 빼면 먼저 도달한 구성원이
    다시 미달할 수 있어, 하한 이후의 사건 시각을 오름차순으로 훑어 전원 충족을 다시 확인한다.
    """
    deadline = parse_utc(DEADLINE_CUT_UTC)
    members = FAMILIES[family]
    member_times = {
        f"{arm}:h{h}": member_ready_time(candidates[(arm, h)], h, deadline)
        for arm, h in members
    }
    times = list(member_times.values())
    t_star = None
    if times and all(stamp is not None for stamp in times):
        lower = max(times)
        events: set[datetime] = set()
        for arm, h in members:
            events |= _event_times(candidates[(arm, h)], deadline)
        for stamp in sorted(stamp for stamp in events if stamp >= lower):
            if all(_member_ready_at(candidates[(arm, h)], h, stamp) for arm, h in members):
                t_star = stamp
                break
    return t_star, {key: (None if stamp is None else iso_utc(stamp)) for key, stamp in member_times.items()}


# ── 판정 ─────────────────────────────────────────────────────────────────────


def _ledger_head_at_cut(rows: Sequence[Mapping[str, Any]], field: str, cut: datetime) -> str | None:
    eligible = [row for row in rows if row.get(field) and parse_utc(row[field]) <= cut]
    return str(eligible[-1].get("content_hash")) if eligible else None


def family_verdict(
    *,
    family: str,
    shadow: Sequence[Mapping[str, Any]],
    issuance: Sequence[Mapping[str, Any]],
    resolutions: Sequence[Mapping[str, Any]],
    first_origin_not_before: str | None = None,
    now: datetime | None = None,
    verdict_code_hash: str | None = None,
    rule_hash: str | None = None,
) -> dict[str, Any]:
    """판정 JSON — (원장, 계약, verdict_code_hash)만의 함수. now 는 컷 확정 여부 판단에만 쓴다."""
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    members = FAMILIES[family]
    candidates = build_candidate_pairs(shadow, issuance, resolutions,
                                       first_origin_not_before=first_origin_not_before)
    deadline = parse_utc(DEADLINE_CUT_UTC)
    t_star, member_times = family_cut(candidates, family)
    if t_star is not None:
        cut, cut_kind = t_star, "t_star"
    elif now is not None and now.astimezone(timezone.utc) > deadline:
        cut, cut_kind = deadline, "deadline"
    else:
        cut, cut_kind = None, "pending"
    base = {
        "schema_version": 1, "family": family, "family_size": len(members),
        "t_star": None if t_star is None else iso_utc(t_star),
        "member_ready_at": member_times, "deadline_cut_utc": DEADLINE_CUT_UTC,
        "cut_kind": cut_kind, "verdict_code_hash": verdict_code_hash, "rule_hash": rule_hash,
        "label_basis": "xnas_v1", "notice": NOTICE,
    }
    if cut is None:
        counts = {}
        for arm, h in members:
            stats = _pairs_at_cut(candidates[(arm, h)], deadline)
            counts[f"{arm}:h{h}"] = {"pairs": len(stats["d"]), "required": required_n(h),
                                     "reached": member_times[f"{arm}:h{h}"] is not None}
        return {**base, "status": "pending", "cut_utc": None, "counts": counts,
                "labels": {f"{arm}:h{h}": "insufficient" for arm, h in members}}
    results: dict[str, dict[str, Any]] = {}
    pvalues: dict[str, float] = {}
    for arm, h in members:
        key = f"{arm}:h{h}"
        at_cut = _pairs_at_cut(candidates[(arm, h)], cut)
        n = len(at_cut["d"])
        entry: dict[str, Any] = {
            "arm": arm, "horizon": h, "n": n, "required": required_n(h),
            "crn_violations": at_cut["crn_violations"], "calendar_drift": at_cut["calendar_drift"],
            "excluded": _excluded_at_cut(candidates[(arm, h)], cut),
            "first_origin": at_cut["origins"][0] if n else None,
            "last_origin": at_cut["origins"][-1] if n else None,
        }
        reason = data_condition(n, h)
        if reason is None and at_cut["crn_violations"]:
            reason = "crn_violation"
        if reason is not None:
            entry.update({"label": "insufficient", "reason": f"data:{reason}"})
            pvalues[key] = 1.0
        elif family == "superiority":
            stats = superiority_statistics(at_cut["d"], h)
            entry.update(stats)
            pvalues[key] = stats["p"]
        else:
            stats = noninferiority_statistics(at_cut["d"], at_cut["c"], h)
            entry.update(stats)
            pvalues[key] = stats["p_ni"]
        results[key] = entry
    rejected = holm(pvalues)
    for key, entry in results.items():
        entry["holm_rejected"] = bool(rejected[key])
        entry["p_holm_input"] = pvalues[key]
        if entry.get("label") == "insufficient":
            continue
        upper = entry["ci90"][1]
        threshold = 0.0 if family == "superiority" else NI_MARGIN
        if upper >= threshold or not rejected[key]:
            entry.update({"label": "fail", "reason": "ci_or_holm"})
        elif family == "superiority" and not entry["episodes"]["ok"]:
            entry.update({"label": "insufficient", "reason": "single_episode"})
        else:
            entry.update({"label": "pass", "reason": None})
    return {
        **base, "status": "decided", "cut_utc": iso_utc(cut),
        "members": results,
        "pairs_used": {key: entry["n"] for key, entry in results.items()},
        "labels": {key: entry["label"] for key, entry in results.items()},
        "ledger_heads_at_cut": {
            "shadow_forecasts": _ledger_head_at_cut(shadow, "issued_at", cut),
            "issuance_forecasts": _ledger_head_at_cut(issuance, "issued_at", cut),
            "shadow_resolutions": _ledger_head_at_cut(resolutions, "resolved_at", cut),
        },
    }


def counts_only(
    *,
    shadow: Sequence[Mapping[str, Any]],
    issuance: Sequence[Mapping[str, Any]],
    resolutions: Sequence[Mapping[str, Any]],
    first_origin_not_before: str | None = None,
) -> dict[str, Any]:
    """status·중간 출력용 — 건수·도달 여부·T* 만(d̄·CI 없음)."""
    candidates = build_candidate_pairs(shadow, issuance, resolutions,
                                       first_origin_not_before=first_origin_not_before)
    deadline = parse_utc(DEADLINE_CUT_UTC)
    payload: dict[str, Any] = {}
    for family, members in FAMILIES.items():
        t_star, member_times = family_cut(candidates, family)
        payload[family] = {
            "t_star": None if t_star is None else iso_utc(t_star),
            "members": {
                f"{arm}:h{h}": {
                    "pairs": len(_pairs_at_cut(candidates[(arm, h)], deadline)["d"]),
                    "required": required_n(h),
                    "reached": member_times[f"{arm}:h{h}"] is not None,
                }
                for arm, h in members
            },
        }
    return payload


def verdict_file_hash(root: Path) -> str:
    from .contracts import verdict_code_hash

    return verdict_code_hash(root)
