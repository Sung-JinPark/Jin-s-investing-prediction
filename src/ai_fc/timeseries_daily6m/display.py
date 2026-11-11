"""Fail-closed read projection for the independent six-month daily forecast."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from . import contracts as C
from . import features as F
from .pipeline import Daily6mPipelineError, hold_payload, load_run, read_chain, validate_run

# 전진 성적(표시 전용) 기준값 — 무정보 Brier 0.25 = p=0.5 고정 예측의 점수, 공칭 구간 80%.
NO_INFORMATION_BRIER = 0.25
NOMINAL_INTERVAL_COVERAGE = 0.8

# 표시 정직성 투영(P4, 2026-11-11) — 상수는 사전고정 파일에서만, 해시가 맞을 때만 읽는다.
# 이 파일(display.py)은 daily6m model_code_hash 대상이 아니다: 읽기 투영만 바꾸고 원장 가중·발행 숫자는 무변경.
DISPLAY_CONSTANTS_RELATIVE = Path("data/mts_research/contracts/daily6m_display_constants_v1.json")
PINNED_DISPLAY_CONSTANTS_HASH = "07c59548c8b82978c0cf5c626e7af97688514730f58f56c8e36d97a748ec0f59"
NOTICE = "참고 의견, 매매 신호 아님"
COVERAGE_LABEL = "원점 기준 누적 수준 p10~p90 (날짜별 pointwise)"
KAPPA_LABEL = "폭이 원점일 충격 미반영(1세션 지연)"
Z90 = 1.2815515655446004  # 표준정규 0.90 분위 — p10~p90 폭 = 2·Z90·σ
HONESTY_FIELDS = (
    "coverage_raw", "coverage_date_equal", "coverage_freshest_origin", "coverage_weekly_final",
    "effective_n_dates", "n_issuances", "n_active_weekly_lineages", "null_band",
    "null_band_sensitivity_freshest", "increment_coverage", "daily_z_rms_recent10", "post_shock_rows",
    "brier_date_equal", "brier_const_prefixed", "brier_in_sample_climatology", "skill_judgeable",
    "single_episode",
)


class Daily6mDisplayError(ValueError):
    """읽기 투영 입력이 정직성 지표를 계산할 수 없다 — 숫자를 지어내지 않고 닫는다."""


def load_display_constants(root: Path) -> tuple[dict[str, Any] | None, str]:
    """(상수, 상태). 상태: ok · constants_file_missing · constants_hash_mismatch."""
    path = root / DISPLAY_CONSTANTS_RELATIVE
    if not path.is_file():
        return None, "constants_file_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "constants_unreadable"
    if C.canonical_hash(payload) != PINNED_DISPLAY_CONSTANTS_HASH:
        return None, "constants_hash_mismatch"
    return payload, "ok"


def forward_record(rows: list[dict[str, Any]], *, runs: dict[str, dict[str, Any]] | None = None,
                   forecasts: list[dict[str, Any]] | None = None,
                   constants: dict[str, Any] | None = None) -> dict[str, Any]:
    """해소 원장 행을 전진 성적으로 요약한다 — 표시 전용 순수 함수, 채점·판정이 아니다.

    누적 Brier(무정보 0.25 병기)·80% 구간 적중 n/N·발행 수·해소일 수만 센다. 같은 발행의
    일별 행은 독립 표본이 아니므로 발행 수와 해소일 수를 함께 싣는다. 정정(supersedes)된
    해소 행은 최신 개정만 센다 — 원장 자체는 그대로다. 행이 없으면 숫자 대신 None(화면은
    '—')이고, predictive_validation 은 어떤 경우에도 not_established 로 유지한다.

    P4 정직성 필드(목표일 균등 커버리지·귀무 밴드 등)는 runs(run_summary 사본)·forecasts(발행
    원장 행)·constants(사전고정 상수)가 모두 있을 때만 채운다. 없으면 같은 키를 None 으로 두고
    honesty_status 에 이유를 적는다. 가중은 이 읽기 투영 안에서만 바뀌고 원장 가중은 그대로다.
    """
    superseded = {str(row.get("supersedes")) for row in rows if row.get("supersedes")}
    active = []
    for row in rows:
        if str(row.get("resolution_id")) in superseded:
            continue
        brier = row.get("brier")
        if isinstance(brier, bool) or not isinstance(brier, (int, float)) or not math.isfinite(float(brier)):
            continue
        active.append(row)
    count = len(active)
    dates = sorted({str(row.get("date")) for row in active if row.get("date")})
    issued = {str(row.get("forecast_id")) for row in active if row.get("forecast_id")}
    return {
        "schema_version": 1,
        "model_id": C.MODEL_ID,
        "ledger": C.RESOLUTION_LEDGER.as_posix(),
        "display_only": True,
        "probability_unit": "fraction",
        "resolved_rows": count,
        "forecasts": len(issued),
        "resolved_dates": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "mean_brier": round(sum(float(row["brier"]) for row in active) / count, 4) if count else None,
        "no_information_brier": NO_INFORMATION_BRIER,
        "covered_p10_p90_rows": sum(1 for row in active if row.get("inside_p10_p90") is True) if count else None,
        "nominal_interval_coverage": NOMINAL_INTERVAL_COVERAGE,
        "independent_rows": False,
        "predictive_validation": "not_established",
        "notice": NOTICE,
        "n": count,
        "n_dates": len(dates),
        "n_origins": len(issued),
        "label": COVERAGE_LABEL,
        **_honesty_or_null(active, runs, forecasts, constants),
    }


def _honesty_or_null(active: list[dict[str, Any]], runs: dict[str, dict[str, Any]] | None,
                     forecasts: list[dict[str, Any]] | None, constants: dict[str, Any] | None) -> dict[str, Any]:
    """정직성 필드 전부 또는 전부 None — 일부만 채운 표면은 만들지 않는다."""
    empty: dict[str, Any] = {key: None for key in HONESTY_FIELDS}
    if not active:
        return {**empty, "honesty_status": "no_resolved_rows"}
    if runs is None or forecasts is None:
        return {**empty, "honesty_status": "runs_unavailable"}
    if constants is None:
        return {**empty, "honesty_status": "constants_unavailable"}
    try:
        return {**honesty_projection(active, runs, forecasts, constants), "honesty_status": "ok"}
    except (Daily6mDisplayError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
        return {**empty, "honesty_status": "honesty_error: " + str(exc)}


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    """발행본에서 정직성 계산에 필요한 값만 뽑은 사본 — 9MB 발행본을 들고 다니지 않는다.

    수준 밴드는 원점 종가 대비 로그비 [p10, p50, p90], 일간 증분은 단순수익 분위수 5개다.
    sigma_origin = lead-1 일간 증분 (q90−q10)/(2·Z90).
    """
    anchor = float(run["anchor_index"])
    if not math.isfinite(anchor) or anchor <= 0:
        raise Daily6mDisplayError("run anchor index must be positive and finite")
    level, daily = [], []
    for record in run["records"]:
        band, step = record["band_index"], record["daily_return_quantiles"]
        level.append([math.log(float(band[key]) / anchor) for key in ("p10", "p50", "p90")])
        daily.append([float(step[key]) for key in C.QUANTILE_NAMES])
    width = daily[0][4] - daily[0][0]
    if not math.isfinite(width) or width <= 0:
        raise Daily6mDisplayError("lead-1 daily band width must be positive")
    return {
        "forecast_id": str(run["run_id"]), "anchor_date": str(run["anchor_date"]),
        "dates": [str(day) for day in run["dates"]], "level": level, "daily": daily,
        "sigma_origin": width / (2 * Z90),
    }


def _resolved_rows(active: list[dict[str, Any]], runs: dict[str, dict[str, Any]],
                   forecasts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """해소 행 ↔ 발행본 리드 결합. 발행본·날짜가 안 맞으면 닫는다(조용한 누락 없음)."""
    order = {str(row["forecast_id"]): index for index, row in enumerate(forecasts)}
    superseded = {str(row["supersedes"]) for row in forecasts if row.get("supersedes")}
    weeks = {str(row["forecast_id"]): str(row.get("iso_week") or "") for row in forecasts}
    joined = []
    for row in active:
        fid = str(row["forecast_id"])
        summary = runs.get(fid)
        if summary is None or fid not in order:
            raise Daily6mDisplayError("resolution has no loaded forecast run: " + fid)
        day = str(row["date"])
        if day not in summary["dates"]:
            raise Daily6mDisplayError("resolution date outside forecast calendar: " + fid + " " + day)
        inside, up = row.get("inside_p10_p90"), row.get("outcome_up")
        if not isinstance(inside, bool) or not isinstance(up, bool):
            raise Daily6mDisplayError("resolution coverage/outcome must be boolean")
        actual, previous = float(row["actual_index"]), float(row["actual_previous_index"])
        if not (math.isfinite(actual) and math.isfinite(previous) and actual > 0 and previous > 0):
            raise Daily6mDisplayError("resolution index must be positive and finite")
        lead = summary["dates"].index(day) + 1
        joined.append({
            "forecast_id": fid, "order": order[fid], "origin": summary["anchor_date"], "date": day,
            "lead": lead, "inside": inside, "up": up, "p_up": float(row["probability_up_from_previous"]),
            "daily_return": actual / previous - 1, "level": summary["level"][lead - 1],
            "daily": summary["daily"][lead - 1], "sigma_origin": summary["sigma_origin"],
            "weekly_final": fid not in superseded, "iso_week": weeks[fid],
        })
    return joined


def _by_date(joined: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in joined:
        groups.setdefault(row["date"], []).append(row)
    return dict(sorted(groups.items()))


def _date_equal(groups: dict[str, list[dict[str, Any]]], value) -> float:
    """C_de = (1/D)Σ_d (1/n_d)Σ_{i∈d} value(i)."""
    return sum(sum(value(row) for row in rows) / len(rows) for rows in groups.values()) / len(groups)


def _freshest(groups: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """목표일마다 가장 짧은 리드(가장 최근 원점) 행 — 동률이면 원장상 나중 발행."""
    return {day: min(rows, key=lambda row: (row["lead"], -row["order"])) for day, rows in groups.items()}


def _kn(rows: list[dict[str, Any]], key: str = "inside") -> dict[str, int]:
    return {"k": sum(1 for row in rows if row[key]), "n": len(rows)}


def _daily_z(row: dict[str, Any]) -> float:
    """z = (r − q50)/((q90−q10)/(2·Z90)) — 그 행 자신의 일간 증분 분위수(경로 무관)."""
    quantiles = row["daily"]
    return (row["daily_return"] - quantiles[2]) / ((quantiles[4] - quantiles[0]) / (2 * Z90))


def _increment_inside(row: dict[str, Any]) -> bool:
    return row["daily"][0] <= row["daily_return"] <= row["daily"][4]


def honesty_projection(active: list[dict[str, Any]], runs: dict[str, dict[str, Any]],
                       forecasts: list[dict[str, Any]], constants: dict[str, Any]) -> dict[str, Any]:
    """P4 정직성 필드 — 주 숫자는 목표일 균등 커버리지와 귀무 밴드, 원시 n/N 은 보조."""
    joined = _resolved_rows(active, runs, forecasts)
    groups = _by_date(joined)
    fresh = _freshest(groups)
    n_dates = len(groups)
    coverage_raw = _kn(joined)
    coverage_de = _date_equal(groups, lambda row: float(row["inside"]))
    band, sensitivity = _null_band(joined, groups, runs, constants["null_band"],
                                   observed_raw=coverage_raw["k"] / coverage_raw["n"], observed_de=coverage_de)
    return {
        "coverage_raw": coverage_raw,
        "coverage_date_equal": round(coverage_de, 4),
        "coverage_freshest_origin": _kn(list(fresh.values())),
        "coverage_weekly_final": _kn([row for row in joined if row["weekly_final"]]),
        "effective_n_dates": n_dates,
        "n_issuances": len({row["forecast_id"] for row in joined}),
        "n_active_weekly_lineages": len({row["iso_week"] for row in joined}),
        "null_band": band,
        "null_band_sensitivity_freshest": sensitivity,
        "increment_coverage": _increment_coverage(joined, groups, fresh),
        "daily_z_rms_recent10": _recent_z_rms(fresh, int(constants["recent_z_window_dates"])),
        "post_shock_rows": _post_shock(joined, float(constants["shock_mark_abs_daily_z"])),
        **_brier_fields(groups, constants["up_day_constant_baseline"]),
        "skill_judgeable": n_dates >= int(constants["skill_judgeable_min_dates"]),
        "skill_min_dates": int(constants["skill_judgeable_min_dates"]),
        "single_episode": n_dates <= int(constants["single_episode_max_dates"]),
        "scoring_excluded": True,
        "constants_id": constants["constants_id"],
    }


def _session_axis(joined: list[dict[str, Any]], runs: dict[str, dict[str, Any]]) -> list[str]:
    """발행본 자체 달력(XNAS future_sessions)의 합집합 — 아카이브 날짜를 달력으로 쓰지 않는다."""
    last = max(row["date"] for row in joined)
    used = {row["forecast_id"] for row in joined}
    axis = sorted({day for fid in used for day in runs[fid]["dates"] if day <= last})
    position = {day: index for index, day in enumerate(axis)}
    for fid in used:
        own = [day for day in runs[fid]["dates"] if day <= last]
        start = position[own[0]]
        if axis[start:start + len(own)] != own:
            raise Daily6mDisplayError("forecast calendars disagree on the shared session axis: " + fid)
    return axis


def _null_band(joined: list[dict[str, Any]], groups: dict[str, list[dict[str, Any]]],
               runs: dict[str, dict[str, Any]], spec: dict[str, Any], *,
               observed_raw: float, observed_de: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """model-true 근사 귀무: 공유 표준화 t4 증분 경로를 실제 (원점, 목표일) 쌍 구조에 대입한다.

    주(主): X_{o,d} = p50_{o,d} + σ_o·Σ_{t∈(o,d]} e_t, σ_o = 그 원점의 lead-1 σ.
    민감도: X_{o,d} = p50_{o,d} + Σ_t σ_fresh(t)·e_t, σ_fresh(t) = t 직전 최신 원점의 σ.
    e_t ~ t_df/√(df/(df−2)) (분산 1), 두 변형은 같은 난수를 공유한다. 같은 시드·입력이면 비트 동일.
    """
    import numpy as np

    df, seed, draws, chunk = int(spec["df"]), int(spec["seed"]), int(spec["draws"]), int(spec["chunk"])
    if df <= 2 or chunk <= 0 or draws % chunk:
        raise Daily6mDisplayError("null band spec must have df>2 and draws divisible by chunk")
    axis = _session_axis(joined, runs)
    position = {day: index for index, day in enumerate(axis)}
    start = np.array([position[row["date"]] - row["lead"] + 1 for row in joined])
    stop = np.array([position[row["date"]] + 1 for row in joined])
    if (start < 0).any():
        raise Daily6mDisplayError("row lead reaches before the shared session axis")
    low, mid, high = (np.array([row["level"][index] for row in joined]) for index in range(3))
    sigma = np.array([row["sigma_origin"] for row in joined])
    weight = np.array([1.0 / len(groups[row["date"]]) for row in joined]) / len(groups)
    origins = sorted({(row["origin"], row["order"], row["sigma_origin"]) for row in joined})
    fresh_sigma = np.array([[value for anchor, _, value in origins if anchor < day][-1] for day in axis])
    rng = np.random.default_rng(seed)
    scale = math.sqrt(df / (df - 2))
    main: tuple[list, list] = ([], [])
    fresh: tuple[list, list] = ([], [])
    for _ in range(draws // chunk):
        shocks = rng.standard_t(df, (chunk, len(axis))) / scale
        for path, (raws, des) in ((sigma * _window_sum(shocks, start, stop), main),
                                  (_window_sum(shocks * fresh_sigma, start, stop), fresh)):
            inside = ((mid + path) >= low) & ((mid + path) <= high)
            raws.append(inside.mean(axis=1))
            des.append(inside @ weight)
    base = {"method": spec["method"], "df": df, "seed": seed, "draws": draws, "approximate": True,
            "label": spec["label"], "statistic": "coverage_date_equal",
            "reference_p_raw_range": spec["reference_p_raw_range"]}
    return (_band_summary(main, observed_raw, observed_de, base),
            _band_summary(fresh, observed_raw, observed_de, {**base, "method": spec["sensitivity"]}))


def _window_sum(shocks, start, stop):
    """행별 Σ_{t∈[start, stop)} shocks[:, t] — 누적합 차분."""
    import numpy as np

    cumulative = np.concatenate([np.zeros((shocks.shape[0], 1)), np.cumsum(shocks, axis=1)], axis=1)
    return cumulative[:, stop] - cumulative[:, start]


def _band_summary(parts: tuple[list, list], observed_raw: float, observed_de: float,
                  base: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    raw, de = np.concatenate(parts[0]), np.concatenate(parts[1])
    tolerance = 1e-12
    return {
        **base,
        "p05": round(float(np.quantile(de, 0.05)), 4), "p95": round(float(np.quantile(de, 0.95)), 4),
        "raw_p05": round(float(np.quantile(raw, 0.05)), 4), "raw_p95": round(float(np.quantile(raw, 0.95)), 4),
        "null_mean_date_equal": round(float(de.mean()), 4),
        "p_raw_le_observed": round(float(np.mean(raw <= observed_raw + tolerance)), 4),
        "p_date_equal_le_observed": round(float(np.mean(de <= observed_de + tolerance)), 4),
    }


def _increment_coverage(joined: list[dict[str, Any]], groups: dict[str, list[dict[str, Any]]],
                        fresh: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """일간 증분 80% 적중 — 경로 의존이 없는 1스텝 폭 점검. PIT 는 분위수 6구간 빈도(최신 원점)."""
    bins = [0] * 6
    for row in fresh.values():
        bins[sum(1 for edge in row["daily"] if row["daily_return"] > edge)] += 1
    return {
        "rows": {"k": sum(1 for row in joined if _increment_inside(row)), "n": len(joined)},
        "date_equal": round(_date_equal(groups, lambda row: float(_increment_inside(row))), 4),
        "freshest_origin": {"k": sum(1 for row in fresh.values() if _increment_inside(row)), "n": len(fresh)},
        "freshest_pit_bins6": bins,
        "pit_bin_edges": list(C.QUANTILE_NAMES),
    }


def _recent_z_rms(fresh: dict[str, dict[str, Any]], window: int) -> dict[str, Any]:
    days = sorted(fresh)[-window:]
    values = [_daily_z(fresh[day]) for day in days]
    return {"value": round(math.sqrt(sum(value * value for value in values) / len(values)), 4),
            "n_dates": len(values), "first_date": days[0], "last_date": days[-1], "nominal": 1.0}


def _post_shock(joined: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """같은 원점에서 |일간 z|>임계인 첫날과 그 이후 행에 표식 — 제외하지 않고 제외 커버리지를 병기."""
    first = shock_onsets(joined, threshold)
    marked = shock_marked_keys(joined, first)
    rest = [row for row in joined if (row["forecast_id"], row["date"]) not in marked]
    return {
        "marked": len(marked), "n": len(joined), "threshold_abs_daily_z": threshold,
        "shock_dates": sorted(set(first.values())), "origins_marked": len(first),
        "coverage_excl": _kn(rest),
        "coverage_excl_date_equal": round(_date_equal(_by_date(rest), lambda row: float(row["inside"])), 4) if rest else None,
    }


def shock_onsets(joined: list[dict[str, Any]], threshold: float) -> dict[str, str]:
    """발행별 |일간 z|>임계 첫 목표일."""
    first: dict[str, str] = {}
    for row in sorted(joined, key=lambda item: item["date"]):
        if abs(_daily_z(row)) > threshold and row["forecast_id"] not in first:
            first[row["forecast_id"]] = row["date"]
    return first


def shock_marked_keys(joined: list[dict[str, Any]], first: dict[str, str]) -> set[tuple[str, str]]:
    """충격 첫날 포함 그 이후 같은 발행의 (forecast_id, date)."""
    return {(row["forecast_id"], row["date"]) for row in joined
            if row["forecast_id"] in first and row["date"] >= first[row["forecast_id"]]}


def _brier_fields(groups: dict[str, list[dict[str, Any]]], baseline: dict[str, Any]) -> dict[str, Any]:
    """Brier_de = (1/D)Σ_d mean_{i∈d}(p_i − y_d)². 상수 c 는 설계창(2007~2014) 상승일 빈도로 사전고정."""
    outcomes = {}
    for day, rows in groups.items():
        values = {row["up"] for row in rows}
        if len(values) != 1:
            raise Daily6mDisplayError("one target date carries conflicting up/down outcomes: " + day)
        outcomes[day] = float(values.pop())
    c = float(baseline["c"])
    frequency = sum(outcomes.values()) / len(outcomes)
    return {
        "brier_date_equal": round(_date_equal(groups, lambda row: (row["p_up"] - outcomes[row["date"]]) ** 2), 4),
        "brier_const_prefixed": {
            "c": round(c, 4), "value": round(sum((c - y) ** 2 for y in outcomes.values()) / len(outcomes), 4),
            "window": [baseline["window_start"], baseline["window_end"]], "n_sessions": baseline["n_sessions"]},
        "brier_in_sample_climatology": {
            "frequency": round(frequency, 4), "value": round(frequency * (1 - frequency), 4), "label": "in-sample"},
    }


def load_forward_record(root: Path) -> dict[str, Any]:
    """원장이 없거나 깨졌으면 행 0 으로 닫는다 — 빌드를 세우지 않고 숫자를 지어내지 않는다.

    정직성 필드용 발행본은 read_ledgered_run(원장 내용 identity 검사)으로만 읽는다. 발행본이 하나라도
    안 읽히면 정직성 필드 전부 None + honesty_status — 기본 요약은 그대로 낸다.
    """
    path = root / C.RESOLUTION_LEDGER
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ] if path.is_file() else []
    except (OSError, ValueError) as exc:
        record = forward_record([])
        record["ledger_error"] = str(exc)
        return record
    constants, constants_status = load_display_constants(root)
    runs, forecasts, run_error = _load_run_summaries(root, rows)
    record = forward_record(rows, runs=runs, forecasts=forecasts, constants=constants)
    if record["honesty_status"] == "runs_unavailable" and run_error:
        record["honesty_status"] = "runs_unavailable: " + run_error
    elif record["honesty_status"] == "constants_unavailable":
        record["honesty_status"] = "constants_unavailable: " + constants_status
    return record


def _load_run_summaries(root: Path, rows: list[dict[str, Any]]):
    """(runs, forecasts, error) — 해소 행이 참조하는 발행본만 identity 검사 후 요약한다."""
    if not rows:
        return None, None, None
    try:
        forecasts = read_chain(root, C.FORECAST_LEDGER)
        wanted = {str(row.get("forecast_id")) for row in rows}
        runs = {str(row["forecast_id"]): run_summary(read_ledgered_run(root, row))
                for row in forecasts if str(row["forecast_id"]) in wanted}
        return runs, forecasts, None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, Daily6mPipelineError, C.Daily6mContractError) as exc:
        return None, None, str(exc)


def read_ledgered_run(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    """발행 원장 행이 가리키는 발행본을 내용 identity 로만 확인해 읽는다(표시 전용 경로).

    load_run 은 거래소 달력 재구성·계약·코드 해시까지 검사해 발행본당 약 1.7초가 든다. 이미
    원장에 고정된 과거 발행본의 숫자를 읽기만 하는 정직성 투영은 run_id·원장 run_content_hash·
    재계산 content_hash 세 가지가 모두 맞을 때만 쓴다 — 하나라도 다르면 닫는다.
    """
    relative = Path(str(row["run_path"]))
    path = (root / relative).resolve()
    if not path.is_relative_to((root / C.STORE_RELATIVE / "runs").resolve()):
        raise Daily6mDisplayError("forecast run path outside research store")
    run = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in run.items() if key != "content_hash"}
    if (run.get("run_id") != row.get("forecast_id") or run.get("content_hash") != row.get("run_content_hash")
            or C.canonical_hash(body) != run.get("content_hash")):
        raise Daily6mDisplayError("forecast ledger/run content identity mismatch: " + str(row.get("forecast_id")))
    return run


_DISCLOSURE_ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError, RuntimeError,
                      Daily6mPipelineError, C.Daily6mContractError)


def run_disclosure(root: Path, run: dict[str, Any]) -> dict[str, Any]:
    """발행 1건의 설정 공시 — 선택 마진·직전 발행 대비 λ 전환·원점일 충격 폭 지연(κ).

    읽기 투영만 한다. 실패하면 해당 필드를 None/status 로 두고 투영 자체는 막지 않는다
    (표시 공시가 없다고 발행본을 HOLD 로 바꾸지 않는다 — 이유는 run_disclosure_status 에 남는다).
    """
    constants, status = load_display_constants(root)
    if constants is None:
        return {"selection_margin_pct": None, "selection_near_tie": None,
                "lambda_switch_vs_prev": {"status": status}, "origin_vol_lag_warning": {"status": status},
                "run_disclosure_status": status}
    problems = []
    try:
        selection = selection_margin(run, float(constants["selection_near_tie_pct"]))
    except _DISCLOSURE_ERRORS as exc:
        selection, problems = {"selection_margin_pct": None, "selection_near_tie": None}, problems + ["selection: " + str(exc)]
    try:
        kappa = origin_vol_lag(run, float(constants["kappa_warning_threshold"]))
    except _DISCLOSURE_ERRORS as exc:
        kappa, problems = {"status": "unavailable"}, problems + ["kappa: " + str(exc)]
    try:
        switch = lambda_switch_vs_prev(root, run)
    except _DISCLOSURE_ERRORS as exc:
        switch, problems = {"status": "unavailable"}, problems + ["lambda: " + str(exc)]
    return {**selection, "lambda_switch_vs_prev": switch, "origin_vol_lag_warning": kappa,
            "run_disclosure_status": "; ".join(problems) if problems else "ok"}


def selection_margin(run: dict[str, Any], near_tie_pct: float) -> dict[str, Any]:
    """분포 설정 선택 1·2위 점수 마진(%) = (s₂ − s₁)/s₁·100. 근소차 = 마진 < 사전고정 임계."""
    config = run["model_config"]
    scores = {str(key): float(value) for key, value in config["distribution_selection"].items()}
    if len(scores) < 2 or not all(math.isfinite(value) and value > 0 for value in scores.values()):
        raise Daily6mDisplayError("distribution selection needs two or more positive finite scores")
    ranked = sorted(scores.items(), key=lambda item: (item[1], item[0]))
    chosen = f"block_{config['block_length']}__ewma_{config['ewma_lambda']}"
    if chosen != ranked[0][0]:
        raise Daily6mDisplayError("published configuration is not the selection argmin: " + chosen)
    margin = (ranked[1][1] - ranked[0][1]) / ranked[0][1] * 100
    return {"selection_margin_pct": round(margin, 3), "selection_near_tie": margin < near_tie_pct,
            "selection_near_tie_threshold_pct": near_tie_pct, "selection_runner_up": ranked[1][0]}


def origin_vol_lag(run: dict[str, Any], threshold: float) -> dict[str, Any]:
    """κ = sqrt(λ + (1−λ)(r_T/σ1d)²) — 원점일 수익 r_T 를 넣었을 때의 EWMA σ 배율 근사.

    r_T 는 발행본 history 의 원점 직전 종가 대비 로그수익, σ1d 는 lead-1 (q90−q10)/(2·Z90).
    κ > 임계면 '폭이 원점일 충격 미반영(1세션 지연)' 경고. 봉인 커널은 건드리지 않는다.
    """
    history = run["history"]
    if history["dates"][-1] != run["anchor_date"] or float(history["index"][-1]) != float(run["anchor_index"]):
        raise Daily6mDisplayError("run history does not end at its anchor")
    previous, anchor = float(history["index"][-2]), float(run["anchor_index"])
    if not (previous > 0 and anchor > 0):
        raise Daily6mDisplayError("history index must be positive")
    step = run["records"][0]["daily_return_quantiles"]
    sigma = (float(step["p90"]) - float(step["p10"])) / (2 * Z90)
    lam = float(run["model_config"]["ewma_lambda"])
    if not (0 < lam < 1 and sigma > 0):
        raise Daily6mDisplayError("ewma lambda or lead-1 sigma outside (0,1)/(0,inf)")
    origin_return = math.log(anchor / previous)
    kappa = math.sqrt(lam + (1 - lam) * (origin_return / sigma) ** 2)
    triggered = kappa > threshold
    return {"kappa": round(kappa, 4), "triggered": triggered, "threshold": threshold, "lambda": lam,
            "origin_log_return": round(origin_return, 6), "sigma_1d": round(sigma, 6),
            "previous_session": history["dates"][-2], "label": KAPPA_LABEL if triggered else None,
            "status": "ok"}


def lambda_switch_vs_prev(root: Path, run: dict[str, Any]) -> dict[str, Any]:
    """발행 원장상 바로 앞 발행과 EWMA λ 비교 — 대체 발행 사이 설정 변화가 정보인지 선택 잡음인지 공시."""
    rows = read_chain(root, C.FORECAST_LEDGER)
    ids = [str(row["forecast_id"]) for row in rows]
    if run["run_id"] not in ids:
        raise Daily6mDisplayError("run is not in the forecast ledger")
    index = ids.index(run["run_id"])
    lam = float(run["model_config"]["ewma_lambda"])
    if index == 0:
        return {"previous_run_id": None, "previous_lambda": None, "lambda": lam, "switched": None,
                "status": "first_issuance"}
    previous = read_ledgered_run(root, rows[index - 1])
    before = float(previous["model_config"]["ewma_lambda"])
    return {"previous_run_id": ids[index - 1], "previous_anchor_date": previous["anchor_date"],
            "previous_lambda": before, "lambda": lam, "switched": before != lam, "status": "ok"}


def project_run(root: Path, run: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    validate_run(run)
    current = F.aware_time(now)
    frame = F.read_native_frame(root, as_of=current)
    freshness = F.source_freshness(frame, current)
    reasons = ["required source " + row["group"] + " " + row["status"] for row in freshness if row["status"] != "fresh"]
    age = F.origin_age(run["anchor_date"], current)
    if age >= 10:
        reasons.append("forecast origin age reaches 10 completed sessions")
    if reasons:
        stable_freshness = [{key: value for key, value in row.items() if key != "age_hours"} for row in freshness]
        held = hold_payload(reasons, as_of=run["as_of"], evidence={"source_freshness": stable_freshness, "origin_age_sessions": age})
        # Preserve issuance identity on HOLD so the UI does not describe this
        # original issue time as a new preflight check or an unpublished run.
        body = {key: value for key, value in held.items() if key != "content_hash"}
        body.update({"run_id": run["run_id"], "anchor_date": run["anchor_date"]})
        return {**body, "content_hash": C.canonical_hash(body)}
    actual = frame[(frame["series_id"] == "NASDAQCOM") & (frame["day"] > run["anchor_date"]) & frame["day"].isin(run["dates"])].sort_values("day")
    lineage = run.get("source_lineage") or {}
    body = {key: value for key, value in run.items() if key not in {"source_lineage", "joint_path_artifact", "content_hash"}}
    body["operational_source_freshness"] = [
        {key: value for key, value in row.items() if key != "age_hours"} for row in freshness]
    body.update({"content_hash": run["content_hash"], "source_lineage": {**{key: value for key, value in lineage.items() if key not in {"market_rows", "factor_rows", "initial_missing_daily_inputs"}}, "initial_missing_daily_inputs_count": len(lineage.get("initial_missing_daily_inputs") or [])}, "gate": {"pass": True, "reasons": [], "origin_age_sessions": age}, "realized": {"dates": actual["day"].tolist(), "index": [float(value) for value in actual["value"]]}})
    # 발행 설정 공시(P4) — 선택 근소차·λ 전환·원점일 충격 폭 지연. 표시 전용, 숫자는 무변경.
    body.update(run_disclosure(root, run))
    # Freshness ages are used for the gate but not reserialized: identical
    # source data and gate state produce the same sidecar identity.
    body["projection_hash"] = C.canonical_hash(body)
    return body


def load_projection(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    path = root / C.LATEST_RELATIVE
    if not path.is_file():
        return hold_payload(["independent daily6m forecast is not published"], status="absent")
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        if pointer.get("content_hash") != C.canonical_hash({key: value for key, value in pointer.items() if key != "content_hash"}):
            raise Daily6mPipelineError("latest pointer content hash mismatch")
        if pointer.get("numbers_visible") is not True:
            if pointer.get("records") or pointer.get("dates") or pointer.get("sample_paths"):
                raise Daily6mPipelineError("HOLD pointer contains numerical forecast arrays")
            # A stored operational source HOLD must be reevaluated at read time:
            # it is not a new forecast and cannot select a superseded issue.
            reasons = pointer.get("gate", {}).get("reasons") or []
            if (pointer.get("run_id") and reasons
                    and all(str(reason).startswith("required source ") for reason in reasons)):
                from .pipeline import _active, read_chain
                active = _active(read_chain(root, C.FORECAST_LEDGER))
                if active and active[-1]["forecast_id"] == pointer["run_id"]:
                    return project_run(root, load_run(root, active[-1]), now=now)
            return pointer
        row = {"forecast_id": pointer["run_id"], "run_path": pointer["run_path"], "run_content_hash": pointer["run_content_hash"]}
        return project_run(root, load_run(root, row), now=now)
    except (OSError, ValueError, KeyError, RuntimeError, TypeError, ImportError, Daily6mPipelineError, C.Daily6mContractError) as exc:
        return hold_payload(["daily6m artifact unavailable: " + str(exc)])
