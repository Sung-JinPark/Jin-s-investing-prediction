"""동결 V8 재현 adapter — REPLAY_IDENTITY (T49, V8 트랙).

Tier-1 (저렴 — 전 행):
- 두 shadow 원장의 hash chain 검증 (동결 ``verify_chain`` 재사용).
- forecast_id 유도 재현: ``tsv8-shadow-<canonical_hash({model, config, origin})[:24]>``.
- 해소 행 전체 재계산: 저장된 quantile_grid + 저장된 actual 로 CRPS·coverage·direction 을
  bit 수준 재현(채점 경로 동일성), 그리고 actual 자체를 아카이브 종가로 독립 검증 —
  sum(log returns) 은 telescoping 으로 ``log(P_end/P_origin)`` 이므로 grid 와 무관하다.
- 행의 model_code_hash / contract_hash 를 현재 값과 대조 (환경·코드 드리프트 탐지).
- latest pointer 가 숫자를 실은 상태면 ``grid[int(q*levels)]`` 투영 재현.

Tier-2 (고가 — 1행 등록 실행): 행의 knowledge_cutoff 로 bundle 을 재구성하고
``walk_forward_dev_backtest_v8`` (순수 함수) 를 재실행해 200레벨 grid 를 대조한다.
전제 드리프트는 ``REPLAY_PRECONDITION_DRIFT``, 코드/환경 불일치는 ``ENVIRONMENT_MISMATCH``
로 보고하고 허용오차를 넓히지 않는다 (§19.2).

쓰기 없음 — 호출 금지 목록은 패키지 docstring 참조.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ...timeseries.backtest import sample_crps
from ...timeseries_v2.market_archive import read_market_observations

# 동결 모듈 상수·함수 — 무수정 import
from ...timeseries_v8.contracts import canonical_hash, frozen_hash, load_contract_v8, model_code_hash
from ...timeseries_v8.pipeline import (
    LATEST_RELATIVE,
    SEALED_LEDGER_RELATIVE,
    SHADOW_FORECAST_LEDGER,
    SHADOW_RESOLUTION_LEDGER,
    _read_chain,
    verify_chain,
)

ACTUAL_TOLERANCE = 1e-9  # 합산 vs telescoping 부동소수 차이 허용 — 모델 허용오차가 아니다
EXACT = 1e-12


def _series_closes(root: Path) -> tuple[dict[str, float], set[str]]:
    """(NASDAQCOM 종가 사전, DGS2 관측일 집합) — grid-skip 판정 재료."""
    closes: dict[str, float] = {}
    treasury_days: set[str] = set()
    for row in read_market_observations(root):
        if row.series_id == "NASDAQCOM":
            closes[str(row.observation_time)[:10]] = float(row.value)
        elif row.series_id == "DGS2":
            treasury_days.add(str(row.observation_time)[:10])
    return closes, treasury_days


def tier1_replay(root: Path) -> dict[str, Any]:
    contract = load_contract_v8(root)
    current_code_hash = model_code_hash(root)
    current_contract_hash = frozen_hash(contract)

    report: dict[str, Any] = {
        "chain_errors": (
            verify_chain(root, SHADOW_FORECAST_LEDGER)
            + verify_chain(root, SHADOW_RESOLUTION_LEDGER)
        ),
    }

    forecasts = _read_chain(root, SHADOW_FORECAST_LEDGER)
    forecast_results: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in forecasts:
        by_id[str(row["forecast_id"])] = row
        issues: list[str] = []
        derived = (
            "tsv8-shadow-"
            + canonical_hash(
                {"model": row["model_id"], "config": row["config"], "origin": row["origin"]}
            )[:24]
        )
        if derived != row["forecast_id"]:
            issues.append(f"forecast_id 유도 불일치: {derived}")
        if row.get("model_code_hash") != current_code_hash:
            issues.append("ENVIRONMENT_MISMATCH: model_code_hash 가 현재 코드와 다름")
        if row.get("contract_hash") != current_contract_hash:
            issues.append("ENVIRONMENT_MISMATCH: contract_hash 가 현재 계약과 다름")
        for horizon, payload in (row.get("horizons") or {}).items():
            grid = np.asarray(payload["quantile_grid"], dtype=float)
            if len(grid) != int(row["grid_levels_count"]):
                issues.append(f"h{horizon}: grid 길이 {len(grid)}")
            if (np.diff(grid) < 0).any():
                issues.append(f"h{horizon}: quantile grid 비단조")
            p_up = float(np.mean(grid > 0.0))
            if abs(p_up - float(payload["p_up"])) > EXACT:
                issues.append(f"h{horizon}: p_up {p_up} vs {payload['p_up']}")
        forecast_results.append({
            "forecast_id": row["forecast_id"],
            "origin": row["origin"],
            "status": "PASS" if not issues else "MISMATCH",
            **({"issues": issues} if issues else {}),
        })

    closes, treasury_days = _series_closes(root)
    nasdaq_days = sorted(closes)
    resolutions = _read_chain(root, SHADOW_RESOLUTION_LEDGER)
    resolution_results: list[dict[str, Any]] = []
    for row in resolutions:
        issues = []
        notes: list[str] = []
        forecast = by_id.get(str(row["forecast_id"]))
        if forecast is None:
            resolution_results.append({
                "resolution_id": row["resolution_id"], "status": "MISMATCH",
                "issues": ["원본 forecast 행 없음"],
            })
            continue
        horizon = str(int(row["horizon"]))
        payload = forecast["horizons"][horizon]
        grid = np.asarray(payload["quantile_grid"], dtype=float)
        baseline = np.asarray(payload["baseline_quantile_grid"], dtype=float)
        stored_actual = float(row["actual_log_return"])
        # (a) 채점 경로 재현 — 저장된 actual 로 bit 수준 대조
        if abs(float(sample_crps(grid, stored_actual)) - float(row["model_crps"])) > EXACT:
            issues.append("model_crps 재계산 불일치")
        if abs(float(sample_crps(baseline, stored_actual)) - float(row["baseline_crps"])) > EXACT:
            issues.append("baseline_crps 재계산 불일치")
        levels = int(forecast["grid_levels_count"])
        p10, p25, p50, p75, p90 = (float(grid[int(q * levels)]) for q in (0.10, 0.25, 0.50, 0.75, 0.90))
        if bool(p10 <= stored_actual <= p90) != bool(row["covered_p10_p90"]):
            issues.append("covered_p10_p90 불일치")
        if bool(p25 <= stored_actual <= p75) != bool(row["covered_p25_p75"]):
            issues.append("covered_p25_p75 불일치")
        if bool((p50 >= 0) == (stored_actual >= 0)) != bool(row["direction_correct"]):
            issues.append("direction_correct 불일치")
        if abs(float(payload["p_up"]) - float(row["p_up"])) > EXACT:
            issues.append("p_up 전사 불일치")
        # (b) actual 독립 검증 — telescoping: sum(r) = log(P_end / P_origin).
        # 단, bundle grid 는 국채 휴장(콜럼버스 데이 등)에 주식이 거래돼도 세션을
        # 떨어뜨린다 — 그 날의 수익은 h세션 누적 라벨에서 빠진다 (grid-종속 표적,
        # 감사 확인 사실). 탈락일 d 의 유입 수익 log(P_d/P_prev) 를 차감한 항등식으로
        # 정확 검증한다.
        origin_day = str(forecast["origin"])
        end_day = str(row["resolved_session"])
        origin_close = closes.get(origin_day)
        end_close = closes.get(end_day)
        if origin_close is None or end_close is None:
            issues.append("REPLAY_PRECONDITION_DRIFT: 아카이브에 원점/만기 종가 없음")
        else:
            telescoped = math.log(end_close / origin_close)
            between = [d for d in nasdaq_days if origin_day < d <= end_day]
            dropped = [d for d in between if d not in treasury_days and d != end_day]
            if len(between) == int(row["horizon"]) and not dropped:
                if abs(telescoped - stored_actual) > ACTUAL_TOLERANCE:
                    issues.append(
                        f"actual_log_return {stored_actual} vs 아카이브 telescoping {telescoped}"
                    )
            else:
                dropped_return = 0.0
                for day in dropped:
                    prev_index = nasdaq_days.index(day) - 1
                    dropped_return += math.log(closes[day] / closes[nasdaq_days[prev_index]])
                adjusted = telescoped - dropped_return
                if abs(adjusted - stored_actual) > ACTUAL_TOLERANCE:
                    issues.append(
                        "actual_log_return 불일치 (grid-skip 보정 후): "
                        f"{stored_actual} vs {adjusted} (탈락일 {dropped})"
                    )
                else:
                    notes.append(
                        f"GRID_SKIP: bundle grid 가 주식 거래일 {dropped} 를 제외 — "
                        "해당 일 수익이 라벨에서 빠짐 (동결 코드의 grid-종속 표적, 수정 아님)"
                    )
        resolution_results.append({
            "resolution_id": row["resolution_id"],
            "status": ("PASS" if not notes else "PASS_WITH_GRID_SKIP") if not issues else "MISMATCH",
            **({"issues": issues} if issues else {}),
            **({"notes": notes} if notes else {}),
        })

    # 봉인 원장 content_hash 재검 (1행)
    sealed_results: list[dict[str, Any]] = []
    sealed_path = root / SEALED_LEDGER_RELATIVE
    if sealed_path.is_file():
        for row in (json.loads(line) for line in sealed_path.read_text(encoding="utf-8").splitlines() if line.strip()):
            body = {k: v for k, v in row.items() if k != "content_hash"}
            ok = canonical_hash(body) == row.get("content_hash")
            sealed_results.append({
                "run_id": row.get("run_id"),
                "status": "PASS" if ok else "HASH_MISMATCH",
            })

    # latest pointer — 숫자를 실은 상태에서만 투영 재현 (hold 포인터는 상태만 기록)
    pointer_result: dict[str, Any] = {"status": "NOT_APPLICABLE"}
    pointer_path = root / LATEST_RELATIVE
    if pointer_path.is_file():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        body = {k: v for k, v in pointer.items() if k != "content_hash"}
        hash_ok = canonical_hash(body) == pointer.get("content_hash")
        horizons = pointer.get("horizons") or {}
        if not horizons:
            pointer_result = {
                "status": "HOLD_POINTER" if hash_ok else "HASH_MISMATCH",
                "pointer_status": pointer.get("status"),
            }
        else:
            issues = [] if hash_ok else ["pointer content_hash 불일치"]
            match = [f for f in forecasts if f.get("origin") == pointer.get("origin")]
            if not match:
                issues.append("pointer origin 의 forecast 행 없음")
            else:
                forecast = match[-1]
                levels = int(forecast["grid_levels_count"])
                for horizon, cells in horizons.items():
                    grid = np.asarray(
                        forecast["horizons"][str(horizon)]["quantile_grid"], dtype=float
                    )
                    for quantile_name, level in (
                        ("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90),
                    ):
                        if quantile_name in cells and abs(
                            float(cells[quantile_name]) - float(grid[int(level * levels)])
                        ) > EXACT:
                            issues.append(f"pointer h{horizon} {quantile_name} 투영 불일치")
                    if "probability_up" in cells and abs(
                        float(cells["probability_up"])
                        - float(forecast["horizons"][str(horizon)]["p_up"])
                    ) > EXACT:
                        issues.append(f"pointer h{horizon} probability_up 불일치")
            pointer_result = {
                "status": "PASS" if not issues else "MISMATCH",
                **({"issues": issues} if issues else {}),
            }

    report.update({
        "forecast_rows": len(forecast_results),
        "forecast_pass": sum(1 for r in forecast_results if r["status"] == "PASS"),
        "resolution_rows": len(resolution_results),
        "resolution_pass": sum(
            1 for r in resolution_results if r["status"] in ("PASS", "PASS_WITH_GRID_SKIP")
        ),
        "grid_skip_rows": sum(
            1 for r in resolution_results if r["status"] == "PASS_WITH_GRID_SKIP"
        ),
        "sealed": sealed_results,
        "pointer": pointer_result,
        "forecast_results": forecast_results,
        "resolution_results": resolution_results,
        "model_code_hash": current_code_hash,
        "contract_hash": current_contract_hash,
    })
    report["ok"] = (
        not report["chain_errors"]
        and report["forecast_pass"] == report["forecast_rows"]
        and report["resolution_pass"] == report["resolution_rows"]
        and all(r["status"] == "PASS" for r in sealed_results)
        and pointer_result["status"] in ("PASS", "HOLD_POINTER", "NOT_APPLICABLE")
    )
    return report


def tier2_replay_forecast(root: Path, forecast_id: str) -> dict[str, Any]:
    """1개 shadow forecast 행의 전체 모델 재계산 — 고가(전체 walk-forward 재생).

    등록된 1회 감독 실행 전용. 전제 드리프트/환경 불일치는 fail-closed 상태로 보고.
    """
    from ...timeseries_v2.contracts import require_dfm_runtime
    from ...timeseries_v8.backtest import walk_forward_dev_backtest_v8
    from ...timeseries_v8.pipeline import _sealed_bundle, build_config_from_grids

    contract = load_contract_v8(root)
    require_dfm_runtime()
    rows = _read_chain(root, SHADOW_FORECAST_LEDGER)
    target = next((row for row in rows if row["forecast_id"] == forecast_id), None)
    if target is None:
        return {"status": "NOT_FOUND", "forecast_id": forecast_id}
    if target.get("model_code_hash") != model_code_hash(root):
        return {"status": "ENVIRONMENT_MISMATCH", "forecast_id": forecast_id,
                "detail": "model_code_hash 가 현재 코드와 다름 — 허용오차 확장 금지 (§19.2)"}

    config = build_config_from_grids(
        contract, json.loads(json.dumps(contract["frozen_winner"]["config_overrides"]))
    )
    if config.as_manifest() != target["config"]:
        return {"status": "REPLAY_PRECONDITION_DRIFT", "forecast_id": forecast_id,
                "detail": "frozen config manifest 가 행과 다름"}
    bundle = _sealed_bundle(root, contract)
    dates = list(bundle.dates)
    origin = str(target["origin"])
    if origin not in dates:
        return {"status": "REPLAY_PRECONDITION_DRIFT", "forecast_id": forecast_id,
                "detail": "현재 bundle 에 원점 세션 없음"}
    end_index = dates.index(origin)
    scores, summary = walk_forward_dev_backtest_v8(
        dates=tuple(dates[: end_index + 1]),
        endog=bundle.endogenous[: end_index + 1],
        exog=bundle.exogenous[: end_index + 1],
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        config=config,
        outer_start=str(contract["evaluation"]["outer_start"]),
        outer_end=origin,
        path_count=int(contract["model"]["distribution"]["sealed_path_count"]),
        pit_min_matured=int(
            contract["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]
        ),
        collect_cramer_audit=False,
        emit_forecast=True,
    )
    forecast = summary.get("shadow_forecast") or {}
    if str(forecast.get("origin")) != origin:
        return {"status": "REPLAY_PRECONDITION_DRIFT", "forecast_id": forecast_id,
                "detail": f"재계산 원점 {forecast.get('origin')} != {origin}"}
    mismatches: list[str] = []
    for field in ("ensemble_weights", "block_length", "ewma_lambda"):
        if forecast.get(field) != target.get(field):
            mismatches.append(f"{field}: {forecast.get(field)} vs {target.get(field)}")
    if int(forecast.get("grid_levels_count", 0)) != int(target["grid_levels_count"]):
        mismatches.append("grid_levels_count")
    for horizon, payload in (target.get("horizons") or {}).items():
        recomputed = (forecast.get("horizons") or {}).get(str(horizon))
        if recomputed is None:
            mismatches.append(f"h{horizon}: 재계산 누락")
            continue
        for field in ("blend_weight", "recalibrated", "matured_pit_count", "p_up"):
            if recomputed.get(field) != payload.get(field):
                mismatches.append(f"h{horizon}.{field}")
        for grid_name in ("quantile_grid", "baseline_quantile_grid"):
            ours = np.asarray(recomputed[grid_name], dtype=float)
            theirs = np.asarray(payload[grid_name], dtype=float)
            if ours.shape != theirs.shape or not np.array_equal(ours, theirs):
                max_diff = (
                    float(np.max(np.abs(ours - theirs))) if ours.shape == theirs.shape else None
                )
                mismatches.append(f"h{horizon}.{grid_name} (max|Δ|={max_diff})")
    return {
        "status": "PASS" if not mismatches else "MISMATCH",
        "forecast_id": forecast_id,
        "origin": origin,
        "matured_origins_at_emit_recomputed": len({row.date for row in scores}),
        **({"mismatches": mismatches} if mismatches else {}),
    }
