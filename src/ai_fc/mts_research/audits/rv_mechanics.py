"""RV_MECHANICS 감사 (§4.5, §14) — RV21 스킬의 '이미 아는 창' 기여 분해.

**감사 가설**: h<21 에서 미래 RV21 에는 원점에 이미 알려진 수익이 남아 있다 —
V13 의 큰 BSS 를 전부 미래 충격 예측으로 해석하면 안 된다.

구성:
1. ``rv_floor`` — 원점 정보만으로 결정되는 rv21[t+k] 의 **하한** (닫힌형).
   하한이 θ 를 넘는 원점의 양성 라벨은 원점에서 기계적으로 확정된 것이다.
2. window-mechanics probability baseline — 등록된 단순 수익 생성기로 미래 경로를
   만들고 **실제 추정식**을 굴려 기간 내 최대 rv21 > θ 인 경로 비율을 확률로 삼는다.
   기대값만 대입해 임계 indicator 를 적용한 값은 ``not_a_probability`` 로만 산출한다 (T21).
3. 모든 실자료 계산 전에 prereg 스탠자(생성기·seed·원점 표본)를
   data/mts_research/experiments/ 에 기록한다 — 결과를 보고 쓰거나 빼는 경로 없음.

산출물은 진단이며 캘리브레이션 표본·매매 신호가 아니다 (CLAUDE.md 5-5 예외 범위).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ...timeseries_v8.contracts import canonical_hash
from ..records import require_utc
from ..targets import RV_ANNUALIZATION, RV_WINDOW, decompose_rv21

EXPERIMENT_RELATIVE = Path("data/mts_research/experiments/rv_mechanics")

GeneratorId = Literal["iid_resample_2520", "ewma_rescaled_resample"]


class MtsRvAuditError(RuntimeError):
    pass


def rv_floor(known_sum: float, known_sumsq: float, n_known: int, k: int) -> float:
    """미래 k 개 수익을 임의로 둘 때 rv21[t+k] 의 최솟값 (연율화).

    변수: F1=Σf, F2=Σf² (F2 >= F1²/k — 모든 미래 수익이 같을 때 등호).
    분산 ∝ S2 + F2 − (S1+F1)²/21 를 F2=F1²/k 에서 F1 로 최소화:
    F1* = S1·k/(21−k)  (k<21).  k>=21 이면 알려진 부분이 없어 하한 0.
    """
    if k >= RV_WINDOW or n_known == 0:
        return 0.0
    if n_known + k != RV_WINDOW:
        raise MtsRvAuditError("분해 좌표 불일치")
    f1_star = known_sum * k / (RV_WINDOW - k)
    f2_star = f1_star * f1_star / k
    total = known_sum + f1_star
    variance = (known_sumsq + f2_star - total * total / RV_WINDOW) / (RV_WINDOW - 1)
    return math.sqrt(max(variance, 0.0) * RV_ANNUALIZATION)


def mechanical_positive(returns: np.ndarray, t: int, h: int, theta: float) -> dict[str, Any]:
    """원점 t 에서 h 지평 내 rv 사건이 **기계적으로 확정**됐는지 (k<21 만 가능)."""
    best_k, best_floor = None, 0.0
    for k in range(1, min(h, RV_WINDOW - 1) + 1):
        decomposition = decompose_rv21(returns, t, k)
        floor = rv_floor(
            decomposition.known_sum, decomposition.known_sumsq, decomposition.n_known, k
        )
        if floor > best_floor:
            best_floor, best_k = floor, k
    return {
        "max_floor": best_floor,
        "argmax_k": best_k,
        "mechanically_determined": bool(best_floor > theta),
    }


def _rolling_rv_matrix(known_tail: np.ndarray, futures: np.ndarray) -> np.ndarray:
    """(paths, h) — 각 경로의 미래 세션별 rv21 (실제 추정식: ddof=1, 평균 제거).

    known_tail: 원점까지의 마지막 20개 수익. futures: (paths, h).
    """
    paths, h = futures.shape
    full = np.concatenate(
        [np.repeat(known_tail[None, :], paths, axis=0), futures], axis=1
    )  # (paths, 20+h)
    # 창 k: full[:, k-1 : k+20] 의 21개 — cumsum 으로 벡터화
    x = full
    cumulative = np.concatenate([np.zeros((paths, 1)), np.cumsum(x, axis=1)], axis=1)
    cumulative_sq = np.concatenate([np.zeros((paths, 1)), np.cumsum(x * x, axis=1)], axis=1)
    out = np.empty((paths, h))
    for k in range(1, h + 1):
        start = k - 1
        end = start + RV_WINDOW
        window_sum = cumulative[:, end] - cumulative[:, start]
        window_sumsq = cumulative_sq[:, end] - cumulative_sq[:, start]
        variance = (window_sumsq - window_sum * window_sum / RV_WINDOW) / (RV_WINDOW - 1)
        out[:, k - 1] = np.sqrt(np.maximum(variance, 0.0) * RV_ANNUALIZATION)
    return out


def window_mechanics_probability(
    returns: np.ndarray,
    t: int,
    h: int,
    theta: float,
    *,
    generator: GeneratorId,
    n_paths: int,
    seed: int,
    lookback: int = 2520,
    ewma_lambda: float = 0.94,
) -> dict[str, Any]:
    """등록된 단순 생성기 + 실제 rolling 추정식 + 기간 내 max 연산의 사건확률 (§4.5-2).

    별도 산출: 기대 제곱수익만 대입한 기대값 변종 — ``not_a_probability`` 라벨 (T21).
    """
    returns = np.asarray(returns, dtype=float)
    if t < RV_WINDOW or t + 1 < lookback * 0:  # t 는 최소 20개 수익 필요
        raise MtsRvAuditError("원점 앞 이력이 부족하다")
    known_tail = returns[t - (RV_WINDOW - 1) + 1 : t + 1]  # 마지막 20개
    if len(known_tail) != RV_WINDOW - 1 or not np.isfinite(known_tail).all():
        raise MtsRvAuditError("known tail 에 NaN")
    history = returns[max(1, t + 1 - lookback) : t + 1]
    history = history[np.isfinite(history)]
    if history.size < 250:
        raise MtsRvAuditError("생성기 이력이 부족하다")
    rng = np.random.default_rng(seed)
    draws = rng.choice(history, size=(n_paths, h), replace=True)
    if generator == "ewma_rescaled_resample":
        # EWMA 분산으로 재척도: 과거 표본을 현재 변동성 수준으로 스케일
        squared = history**2
        ewma_var = squared[0]
        for value in squared[1:]:
            ewma_var = ewma_lambda * ewma_var + (1 - ewma_lambda) * value
        historical_sd = float(history.std(ddof=1))
        scale = math.sqrt(ewma_var) / historical_sd if historical_sd > 0 else 1.0
        draws = draws * scale
    elif generator != "iid_resample_2520":
        raise MtsRvAuditError(f"등록되지 않은 생성기: {generator}")
    rv_paths = _rolling_rv_matrix(known_tail, draws)
    probability = float((rv_paths.max(axis=1) > theta).mean())

    # 기대값 변종 — 확률이 아니다 (T21): E[f²] 대입 후 indicator
    expected_sq = float((draws**2).mean())
    pseudo_future = np.full((1, h), math.sqrt(expected_sq))
    rv_expected = _rolling_rv_matrix(known_tail, pseudo_future)
    expectation_indicator = bool(rv_expected.max() > theta)

    return {
        "probability": probability,
        "generator": generator,
        "n_paths": n_paths,
        "seed": seed,
        "expectation_variant": {
            "kind": "expectation_threshold_indicator",
            "value": expectation_indicator,
            "label": "not_a_probability",
        },
    }


def preregister_and_run_diagnostic(
    root: Path,
    *,
    prices_by_date: dict[str, float],
    theta: float,
    design_window: tuple[str, str],
    now: datetime,
    horizons: tuple[int, ...] = (5, 21, 63),
    origin_stride: int = 21,
    n_paths: int = 400,
    base_seed: int = 20261026,
) -> dict[str, Any]:
    """prereg 스탠자 기록 → 설계창 진단 실행 → 결과 저장 (결과 후 변경 없음).

    - 원점 표본: 설계창 안에서 stride 간격 (등록 좌표 — 성적 보고 선택이 아님).
    - PB 대비 '증분' 주장은 하지 않는다 — known-window 기여의 **크기 진단**이다.
    """
    require_utc(now, field="now")
    dates = sorted(prices_by_date)
    prices = np.array([prices_by_date[d] for d in dates], dtype=float)
    returns = np.concatenate([[np.nan], np.diff(np.log(prices))])

    lo, hi = design_window
    eligible = [
        i for i, d in enumerate(dates)
        if lo <= d <= hi and i >= RV_WINDOW and i + max(horizons) < len(dates)
        and np.isfinite(returns[max(1, i - 2520) : i + 1]).all()
    ]
    origins = eligible[::origin_stride]

    prereg = {
        "experiment_id": "RV_MECHANICS_v1",
        "registered_at": now.isoformat(),
        "theta": theta,
        "design_window": list(design_window),
        "horizons": list(horizons),
        "origin_stride": origin_stride,
        "n_origins": len(origins),
        "generators": ["iid_resample_2520", "ewma_rescaled_resample"],
        "n_paths": n_paths,
        "base_seed": base_seed,
        "estimator": "rolling_std_ddof1 * sqrt(252) — 실제 V13 정의",
        "claims_excluded": [
            "PB 대비 증분 주장 없음 — known-window 기여 크기 진단",
            "기대값 변종은 not_a_probability (T21)",
            "캘리브레이션 표본 아님 — base rate 참조 진단 (CLAUDE.md 5-5)",
        ],
    }
    prereg["content_hash"] = canonical_hash(prereg)
    experiment_dir = root / EXPERIMENT_RELATIVE
    experiment_dir.mkdir(parents=True, exist_ok=True)
    prereg_path = experiment_dir / "prereg.json"
    if prereg_path.is_file():
        existing = json.loads(prereg_path.read_text(encoding="utf-8"))
        frozen_keys = {k: v for k, v in existing.items() if k not in ("registered_at", "content_hash", "n_origins")}
        incoming = {k: v for k, v in prereg.items() if k not in ("registered_at", "content_hash", "n_origins")}
        if frozen_keys != incoming:
            raise MtsRvAuditError("prereg 가 이미 존재하고 좌표가 다르다 — 결과 후 변경 금지")
    else:
        prereg_path.write_text(
            json.dumps(prereg, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    per_origin: list[dict[str, Any]] = []
    for count, i in enumerate(origins):
        row: dict[str, Any] = {"origin": dates[i], "rv_now": None}
        seg = returns[i - RV_WINDOW + 1 : i + 1]
        if np.isfinite(seg).all():
            row["rv_now"] = float(np.std(seg, ddof=1) * math.sqrt(RV_ANNUALIZATION))
        for h in horizons:
            mech = mechanical_positive(returns, i, h, theta)
            # 실현 라벨 (within-horizon, 실제 추정식) — 진단 대조용
            future = []
            for k in range(1, h + 1):
                decomposition = decompose_rv21(returns, i, k) if k < RV_WINDOW else None
                if decomposition is not None:
                    future.append(decomposition.recombine_ann())
                else:
                    window = returns[i + k - RV_WINDOW + 1 : i + k + 1]
                    future.append(float(np.std(window, ddof=1) * math.sqrt(RV_ANNUALIZATION)))
            realized = bool(max(future) > theta)
            wm = {
                generator: window_mechanics_probability(
                    returns, i, h, theta,
                    generator=generator, n_paths=n_paths,
                    seed=base_seed + 1000 * count + h,
                )["probability"]
                for generator in ("iid_resample_2520", "ewma_rescaled_resample")
            }
            row[f"h{h}"] = {
                "label": realized,
                "mechanically_determined": mech["mechanically_determined"],
                "max_floor": round(mech["max_floor"], 6),
                "wm_probability": {k: round(v, 4) for k, v in wm.items()},
            }
        per_origin.append(row)

    summary: dict[str, Any] = {"prereg_content_hash": prereg["content_hash"], "n_origins": len(per_origin)}
    for h in horizons:
        rows_h = [row[f"h{h}"] for row in per_origin]
        positives = [r for r in rows_h if r["label"]]
        summary[f"h{h}"] = {
            "positives": len(positives),
            "positives_mechanically_determined": sum(
                1 for r in positives if r["mechanically_determined"]
            ),
            "mean_wm_probability_iid": round(
                float(np.mean([r["wm_probability"]["iid_resample_2520"] for r in rows_h])), 4
            ),
            "mean_wm_probability_ewma": round(
                float(np.mean([r["wm_probability"]["ewma_rescaled_resample"] for r in rows_h])), 4
            ),
            "base_rate": round(len(positives) / len(rows_h), 4) if rows_h else None,
        }
    results = {"summary": summary, "per_origin": per_origin}
    (experiment_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return results
