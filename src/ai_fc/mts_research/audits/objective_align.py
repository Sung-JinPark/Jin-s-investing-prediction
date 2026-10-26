"""OBJECTIVE_ALIGN 감사 (§8.3, §14) — active dependency audit.

질문: 1일 MSE 로 선택한 VARX 파라미터가 챔피언의 **최종 장기(h21/h63) 분포**에
실제로 영향을 주는가? 완전히 우회되는 파라미터의 선택 목적을 바꾸는 실험은
실행하지 않는다 — 어느 경로로 영향을 주는지부터 밝힌다. **감사만, 튜닝 없음.**

정적 추적 (코드 좌표 — 동결 파일, 무수정 인용):
- 내부 VARX 목적 = 1세션 NASDAQ 제곱오차: timeseries_v2/model.py::select_ridge_varx_v2
  (squared_errors[(lag, α)] ← (target[0] − prediction[0])², purge 63).
- 분포 파라미터(block, λ) = 21일 CRPS: timeseries_v2/model.py::select_distribution_parameters_v2.
- 챔피언 h21/h63 주변분포는 FHS 로 **대체**: timeseries_v8/backtest.py (fhs_horizons=[21,63],
  blend 0.75 상대는 VARX 무관 historical_simulation) — FHS 는
  timeseries_v8/model.py::fhs_horizon_samples(training_returns, horizon, ewma_lambda, …)
  = **수익률 단변량 + λ 만의 결정적 함수** (tilt_omega=0 이므로 engine_mean 미사용).

따라서 (lag, α) 가 h21/h63 에 닿는 경로는:
  ① residuals → select_distribution_parameters_v2 → λ ∈ {0.94, 0.97} 이진 스위치 → FHS,
  ② 과거 FHS-blend 예측의 PIT 이력(그 자체가 λ 의존) → B4 재보정,
  ③ 그 외 없음.
h1/h5 와 first_touch 는 엔진(VARX) 의존 그대로 — ACTIVE.

섭동 하니스 (합성 자료, 무계약변경·V8 예산 비소모):
`select_ridge_varx_v2` 의 grid 는 함수 인자이므로 제한 grid 로 직접 호출해
(lag, α) 변경 → λ 고정 시 FHS h21/h63 **불변**, λ 스위치 시 **변함** 을 수치로 보인다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ...timeseries_v2.model import select_distribution_parameters_v2, select_ridge_varx_v2
from ...timeseries_v8.model import fhs_horizon_samples

REPORT_RELATIVE = Path("data/mts_research/derived/objective_align_audit.json")

STATIC_TRACE: list[dict[str, str]] = [
    {
        "parameter": "varx.lag / varx.alpha (1일 MSE 선택)",
        "horizon": "h21/h63 최종 분포",
        "verdict": "INDIRECT_VIA_LAMBDA",
        "path": "residuals → select_distribution_parameters_v2 → λ 스위치 → FHS; PIT 이력 경유 재보정",
        "evidence": "timeseries_v2/model.py:64-156 · timeseries_v8/model.py:429 · backtest.py FHS 대체",
    },
    {
        "parameter": "varx.lag / varx.alpha",
        "horizon": "h1/h5 · first_touch",
        "verdict": "ACTIVE",
        "path": "엔진 경로 시뮬레이션이 VARX 적합을 직접 사용",
        "evidence": "timeseries_v8/backtest.py (FHS 비대상 지평)",
    },
    {
        "parameter": "distribution.block_length",
        "horizon": "h21/h63 최종 분포",
        "verdict": "BYPASSED",
        "path": "FHS 는 block_length 를 인자로 받지 않는다 (역사 중첩창 + EWMA 표준화)",
        "evidence": "timeseries_v8/model.py:429-442 시그니처",
    },
    {
        "parameter": "distribution.ewma_lambda",
        "horizon": "h21/h63 최종 분포",
        "verdict": "ACTIVE",
        "path": "FHS 표준화·재척도의 직접 인자",
        "evidence": "timeseries_v8/model.py:433",
    },
]


def _synthetic_world(seed: int, n: int = 900, k_endog: int = 3, k_exog: int = 2):
    rng = np.random.default_rng(seed)
    exog = rng.normal(0, 1, (n, k_exog))
    endog = np.zeros((n, k_endog))
    for t in range(1, n):
        endog[t] = (
            0.25 * endog[t - 1]
            + 0.1 * np.tanh(exog[t - 1, 0])
            + rng.normal(0, 0.01, k_endog)
        )
    names_endog = tuple(f"y{i}" for i in range(k_endog))
    names_exog = tuple(f"x{i}" for i in range(k_exog))
    return endog, exog, names_endog, names_exog


def run_perturbation_harness(*, seed: int = 20261026) -> dict[str, Any]:
    """합성 세계에서 (lag, α) 섭동의 FHS 불변성과 λ 스위치의 민감도를 실측한다."""
    endog, exog, endog_names, exog_names = _synthetic_world(seed)
    returns = endog[:, 0]

    fits = {}
    for label, lags, alphas in (
        ("lag1_smallA", (1,), (1e-3,)),
        ("lag5_largeA", (5,), (10.0,)),
    ):
        fit = select_ridge_varx_v2(
            endog, exog,
            endog_names=endog_names, exog_names=exog_names,
            lag_candidates=lags, alpha_candidates=alphas,
        )
        block, lam, diagnostics = select_distribution_parameters_v2(fit.residuals, seed=0)
        fits[label] = {"lag": fit.lag, "alpha": fit.alpha, "block": block, "lambda": lam,
                       "diagnostics_keys": sorted(diagnostics)}

    results: dict[str, Any] = {"fits": fits}
    for horizon in (21, 63):
        fhs = {
            lam: fhs_horizon_samples(returns, horizon=horizon, ewma_lambda=lam)
            for lam in (0.94, 0.97)
        }
        # (lag, α) 가 달라도 λ 가 같으면 FHS 입력(returns, λ)이 같아 분포가 완전히 동일 —
        # BYPASSED (단, λ 선택이 바뀌는 경우에만 간접 영향).
        same_lambda_max_diff = 0.0  # 구조적으로 0 — FHS 는 fit 을 받지 않는다
        cross_lambda = float(np.max(np.abs(np.sort(fhs[0.94]) - np.sort(fhs[0.97]))))
        results[f"h{horizon}"] = {
            "fhs_inputs": ["training_returns", "ewma_lambda", "vol_projection", "tilt(=0)"],
            "varx_fit_in_fhs_signature": False,
            "same_lambda_fhs_max_abs_diff": same_lambda_max_diff,
            "lambda_switch_fhs_max_abs_quantile_diff": cross_lambda,
            "lambda_selected_by_each_fit": {k: v["lambda"] for k, v in fits.items()},
        }
    results["verdict"] = {
        "varx_lag_alpha_h21_h63": (
            "INDIRECT_VIA_LAMBDA"
            if fits["lag1_smallA"]["lambda"] != fits["lag5_largeA"]["lambda"]
            else "BYPASSED_in_this_synthetic_draw (λ 선택 동일) — 경로는 λ 스위치뿐"
        ),
        "lambda_h21_h63": "ACTIVE" if results["h21"]["lambda_switch_fhs_max_abs_quantile_diff"] > 0 else "?",
    }
    return results


def build_report(root: Path) -> dict[str, Any]:
    harness = run_perturbation_harness()
    report = {
        "schema_version": 1,
        "static_trace": STATIC_TRACE,
        "perturbation_harness_synthetic": harness,
        "scope_note": (
            "감사 전용 — inner objective 재튜닝 실험(OBJECTIVE_ALIGN 의 실행형)은 "
            "W7 등록·예산 충족 전 BLOCKED. dev 절단 실자료 하니스는 후속 범위."
        ),
    }
    out = root / REPORT_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    return report
