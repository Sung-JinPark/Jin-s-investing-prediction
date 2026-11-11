"""V8 라이브 성적 감시기 L1~L4 (설계서 P3 — D8, V8-LOC-01~06).

V8 운영 게이트(operational_gate)는 h63 해소 원점 26개가 쌓여야 열린다(약 2027-05). 그 전까지 라이브
성적에 임계 경보가 없다(D8). 여기서는 사전고정 임계(`coherence_monitor_thresholds_v1.json`, 해시 고정)로
**공시 라벨만** 붙인다. 게이트·승격·숨김·재예측과는 연결하지 않는다.

## 무엇을 재는가

- basis 두 가지를 병기하고 섞지 않는다: (a) 원장 grid 라벨(**1차**, 봉인 점수와 같은 규약),
  (b) P1 XNAS 진단 라벨(`v8_xnas_labels` 공개 함수 import — 원장 해소 쌍 `matched_ledger_rows` 와
  목표 종가가 확정된 모든 쌍 `all_closed_targets` 두 코호트).
- 대표 지표는 h5·h21(h63 은 성숙하면 자동 포함). h1 은 12/12 발행 시점에 이미 실현돼(post_dated)
  "pseudo-OOS(사전 기록 아님)" 블록에서만 보고하고 경보를 내지 않는다(정보 플래그 near_tail 만).
- 지평별 마지막 k 원점(k = 12/11/8, h63 8):
  - L1 S_h = 1 − ΣCRPS_m/ΣCRPS_HS (CRPS = 저장소 `sample_crps`, 저장 grid 그대로)
  - L2 z̄, z_i = (y_i − q50_i)/((q90_i − q10_i)/2.5631)
  - L3 PIT 평균·분산, PIT = (#{q<y} + 0.5·#{q=y})/L
  - L4 p_up 평균 − 실현 상승빈도 + 포아송-이항 정확 꼬리(DP 합성곱)
  각각에 봉인 2019+ 롤링 백분위(창 크기 = 라이브 n)와 블록 부트스트랩 CI 를 붙인다.
- 민감도: 충격 창 제외(창 안 일간 |z|>4 — 원점 행의 ewma_lambda 로 만든 XNAS 사전 변동성 기준),
  2026-10-09 원점 제외, CRPS 위치/형태 분해 Δ_loc = Σ(CRPS_m − CRPS_loc)/ΣCRPS_b, Δ_shape = 나머지.
- 연구 쌍둥이(채점·판정 제외, scoring_excluded):
  ① 위치 중립: grid − q50 + q50_HS (원장만으로 결정론).
  ② h21/h63 B4 전: V2 C1 번들 NASDAQ 수익 + 원장 ewma_lambda → 0.75·FHS + 0.25·HS(B4 미적용).
     HS 표본은 봉인 규칙(원점 시드+1, 지평 순서 1·5·21·63)으로 비트 재현한다. 검증 = HS 기준선
     MAE ≤ 0.0025 와 재구성 B4 맵을 다시 적용한 grid 가 원장 grid 를 ±0.004 안에서 재현. 하나라도
     실패하면 status=unreconstructable 이고 숫자를 싣지 않는다. h1/h5 B4 전 재구성(tier2 replay)은 범위 밖.

## 표본 경계(point-in-time)

- 섀도 예측 행은 origin ≤ as_of AND knowledge_cutoff ≤ now 만 쓴다(발행 전 예측은 존재하지 않는 예측).
- 해소 원장(shadow_resolutions)에는 기록 시각 필드가 **없다**. 그래서 as_of 를 고정해도 원장이 자라면
  표본이 바뀔 수 있다 — 목표 세션 ≤ as_of 인데 늦게 해소되는 쌍(예: 2026-11-06 h1, 2026-10-09 h21)이
  나중에 resolved_session ≤ as_of 로 들어온다. 재현이 필요한 호출(테스트 오라클·감사 재연)은
  `resolution_ids` 허용 목록으로 해소 행을 명시 고정한다. 이 경계는 원장 grid basis 와 XNAS
  `matched_ledger_rows`(원장 해소 쌍) 둘 다에 같이 걸린다. `all_closed_targets` 는 해소 원장과 무관하다
  (목표 ≤ as_of + 시장 아카이브 knowledge_cutoff = now 로 고정).

## 하지 않는 것

- 봉인 코드(V8·V2 커널)는 import 만 한다. 원장 grid 행을 정정하지 않는다. 두 label_basis 를 한 평균에
  섞지 않는다. 서로 다른 probability_space 를 산술 결합하지 않는다(V8 로그수익 공간만 읽는다).
- 경보로 재예측·재학습·게이트 숨김을 트리거하지 않는다. 판단은 사람이 한다.
- 장중 값·네트워크를 쓰지 않는다. 아카이브 날짜를 달력으로 쓰지 않는다(달력 = XNAS).

산출물은 참고 의견이며 매매 신호가 아니다(display_only · scoring_excluded).
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..timeseries_v8.contracts import canonical_hash
from .artifacts import LEDGERS_RELATIVE, MtsArtifactError, append_event, read_chain, writer_lock
from .monitor_thresholds import NOTICE, PINNED_THRESHOLD_HASH, load_pinned_thresholds
from .v8_xnas_labels import (
    CALENDAR_LOOKAHEAD_DAYS,
    CALENDAR_START,
    GRID_BASIS,
    LABEL_BASIS,
    PROBABILITY_SPACE,
    V8_FORECAST_LEDGER,
    V8_RESOLUTION_LEDGER,
    NasdaqArchive,
    XnasCalendar,
    build_diagnostics,
    pit_mid,
)

LEDGER_RELATIVE = LEDGERS_RELATIVE / "v8_live_monitor.jsonl"
DERIVED_RELATIVE = Path("data/mts_research/derived/v8_live_monitor.json")
SEALED_LEDGER = Path("data/timeseries_v8/ledgers/sealed_evaluations.jsonl")
BASELINE_IDENTITY = Path("docs/research/mts_upgrade/baseline_identity.json")

SCHEMA_VERSION = 1
MONITOR_VERSION = "v1"
HORIZONS = (1, 5, 21, 63)
WINDOW_K = {1: 12, 5: 11, 21: 8, 63: 8}
Z_DIVISOR = 2.5631  # (q90 − q10) / 2.5631 = 정규 σ 근사 (2·1.28155)
SEALED_FROM = "2019-01-01"
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_SEED = 20261111
SEALED_Q05_DRAWS = 2000
SEALED_Q05_BLOCK = 26  # 봉인 주간 원점 26주 블록 — 임계 JSON 의 q05 CI 와 같은 규약
CI_LEVEL = 0.90
SHOCK_ABS_Z = 4.0
EXCLUDED_ORIGIN_SENSITIVITY = "2026-10-09"
NEAR_TAIL_PERCENTILE = 0.10
COMPOSITE_HORIZONS = (1, 5, 21)
# 봉인 규약 L=200 grid 의 원장 인덱스 — covered_p10_p90·direction_correct 와 같은 grid[int(q·L)]
Q10, Q50, Q90 = 0.10, 0.50, 0.90

# B4 전 쌍둥이 재현 검증 허용치(설계서 P3)
TWIN_HS_MAE_MAX = 0.0025
TWIN_GRID_MAX_ABS = 0.004
TWIN_HORIZONS = (21, 63)

LABEL_NORMAL = "정상 범위(검정력 낮음)"
LABEL_BREACH = "경계 이탈"
POST_DATED_LABEL = "pseudo-OOS(사전 기록 아님)"


class V8LiveMonitorError(MtsArtifactError):
    """V8 라이브 감시 전제 위반 — fail-closed."""


# ---------------------------------------------------------------------------
# 행 — 한 basis 의 한 (원점, 지평) 채점 재료
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredRow:
    origin: str
    h: int
    y: float
    target: str
    window: tuple[date, ...]  # (원점, 목표] XNAS 세션 — 충격 창 판정용
    grid: np.ndarray = field(repr=False)
    baseline: np.ndarray = field(repr=False)
    p_up: float
    ewma_lambda: float
    post_dated: bool
    crps_model: float
    crps_baseline: float
    pit: float
    z: float
    crps_location_neutral: float


def _grid_quantile(grid: np.ndarray, level: float) -> float:
    return float(grid[int(level * grid.size)])


def location_neutral_twin(grid: np.ndarray, hs_grid: np.ndarray) -> np.ndarray:
    """① 위치 중립 쌍둥이: 모델 형태는 두고 중앙값만 HS 기준선 중앙값으로 옮긴다."""
    grid = np.asarray(grid, dtype=float)
    hs_grid = np.asarray(hs_grid, dtype=float)
    return grid - _grid_quantile(grid, Q50) + _grid_quantile(hs_grid, Q50)


def _score_row(forecast: Mapping[str, Any], h: int, y: float, target: str,
               window: Sequence[date], post_dated: bool) -> ScoredRow:
    from ..timeseries.backtest import sample_crps

    block = forecast["horizons"][str(h)]
    grid = np.asarray(block["quantile_grid"], dtype=float)
    baseline = np.asarray(block["baseline_quantile_grid"], dtype=float)
    if grid.size != int(forecast["grid_levels_count"]) or baseline.size != grid.size:
        raise V8LiveMonitorError(f"grid 길이 불일치: {forecast['forecast_id']} h{h}")
    width = _grid_quantile(grid, Q90) - _grid_quantile(grid, Q10)
    if not width > 0:
        raise V8LiveMonitorError(f"80% 폭이 양수가 아니다: {forecast['origin']} h{h}")
    return ScoredRow(
        origin=forecast["origin"], h=h, y=float(y), target=target, window=tuple(window),
        grid=grid, baseline=baseline, p_up=float(block["p_up"]),
        ewma_lambda=float(forecast["ewma_lambda"]), post_dated=bool(post_dated),
        crps_model=float(sample_crps(grid, y)), crps_baseline=float(sample_crps(baseline, y)),
        pit=pit_mid(grid, y), z=(float(y) - _grid_quantile(grid, Q50)) / (width / Z_DIVISOR),
        crps_location_neutral=float(sample_crps(location_neutral_twin(grid, baseline), y)),
    )


# ---------------------------------------------------------------------------
# 설계서 시그니처 — 순수 함수
# ---------------------------------------------------------------------------


def _last_k(rows: Sequence[ScoredRow], h: int, k: int) -> list[ScoredRow]:
    ordered = sorted((r for r in rows if r.h == h), key=lambda r: r.origin)
    return ordered[-k:] if k > 0 else []


def _block_length(h: int, n: int) -> int:
    """주간 원점의 h세션 창 겹침 ≈ ceil(h/5) 원점. 표본의 절반을 넘지 않게 자른다."""
    return int(max(1, min(math.ceil(h / 5), n // 2)))


def _resample_indices(n: int, block: int, draws: int, seed: int) -> np.ndarray:
    """(draws, n) 재표본 인덱스. block=1 이면 iid, 아니면 원형 이동 블록."""
    rng = np.random.default_rng(seed)
    if block <= 1:
        return rng.integers(0, n, size=(draws, n))
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n, size=(draws, blocks))
    index = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return index.reshape(draws, blocks * block)[:, :n]


def _interval(values: np.ndarray) -> list[float] | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    tail = (1.0 - CI_LEVEL) / 2.0
    return [float(np.quantile(finite, tail)), float(np.quantile(finite, 1.0 - tail))]


def _skill_draws(model: np.ndarray, baseline: np.ndarray, index: np.ndarray) -> np.ndarray:
    return 1.0 - model[index].sum(axis=1) / baseline[index].sum(axis=1)


def rolling_skill(rows: Sequence[Mapping[str, Any] | ScoredRow], h: int, k: int) -> dict:
    """L1 — 지평 h 의 마지막 k 원점 skill 과 iid·블록 부트스트랩 90% CI."""
    picked = _last_k([_as_scored(r) for r in rows], h, k)
    if not picked:
        return {"skill": None, "n": 0, "n_origins": 0, "origins": [], "ci90_iid": None,
                "ci90_block": None, "block_length": None, "window_k": k}
    model = np.array([r.crps_model for r in picked])
    baseline = np.array([r.crps_baseline for r in picked])
    n = len(picked)
    block = _block_length(h, n)
    return {
        "skill": float(1.0 - model.sum() / baseline.sum()),
        "n": n,
        "n_origins": len({r.origin for r in picked}),
        "origins": [r.origin for r in picked],
        "ci90_iid": _interval(_skill_draws(model, baseline, _resample_indices(n, 1, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED))),
        "ci90_block": _interval(_skill_draws(model, baseline,
                                             _resample_indices(n, block, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED))),
        "block_length": block,
        "window_k": k,
    }


def location_z(rows: Sequence[Mapping[str, Any] | ScoredRow]) -> float:
    """L2 — z̄ = mean (y − q50)/((q90 − q10)/2.5631)."""
    scored = [_as_scored(r) for r in rows]
    if not scored:
        raise V8LiveMonitorError("z̄ 를 낼 행이 없다")
    return float(np.mean([r.z for r in scored]))


def poisson_binomial_cdf(ps: Sequence[float], k: int) -> float:
    """P(K ≤ k), K = Σ Bernoulli(p_i) 독립 — 정확 DP 합성곱."""
    probabilities = np.asarray(ps, dtype=float)
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise V8LiveMonitorError("포아송-이항 확률은 [0,1] 이어야 한다")
    if k < 0:
        return 0.0
    distribution = np.zeros(len(probabilities) + 1)
    distribution[0] = 1.0
    for p in probabilities:
        distribution[1:] = distribution[1:] * (1.0 - p) + distribution[:-1] * p
        distribution[0] *= 1.0 - p
    return float(min(1.0, distribution[: k + 1].sum()))


@lru_cache(maxsize=4)
def _sealed_scores(root_key: str) -> dict[int, list[dict[str, Any]]]:
    path = Path(root_key) / SEALED_LEDGER
    if not path.is_file():
        raise V8LiveMonitorError(f"봉인 평가 원장 없음: {SEALED_LEDGER.as_posix()}")
    first = path.read_text(encoding="utf-8").splitlines()[0]
    scores = json.loads(first)["scores"]
    by_h: dict[int, list[dict[str, Any]]] = {}
    for row in scores:
        if row["date"] >= SEALED_FROM:
            by_h.setdefault(int(row["horizon"]), []).append(row)
    return {h: sorted(rows, key=lambda r: r["date"]) for h, rows in by_h.items()}


def _sealed_series(root: Path, h: int, metric: str) -> np.ndarray:
    """봉인 2019+ 원점별 통계 재료. pup_gap 은 p_up 이 원장에 없어 정규 근사(proxy)."""
    from scipy.stats import norm

    rows = _sealed_scores(str(root.resolve())).get(h, [])
    if not rows:
        return np.empty((0, 2))
    if metric == "skill":
        return np.array([[r["model_crps"], r["baseline_crps"]["historical_simulation"]] for r in rows])
    sd = np.array([(r["p90"] - r["p10"]) / Z_DIVISOR for r in rows])
    y = np.array([r["actual_log_return"] for r in rows])
    median = np.array([r["median"] for r in rows])
    if metric == "z":
        return ((y - median) / sd)[:, None]
    if metric == "pup_gap":
        return (norm.cdf(median / sd) - (y > 0).astype(float))[:, None]
    raise V8LiveMonitorError(f"알 수 없는 봉인 지표: {metric}")


def _rolling_windows(series: np.ndarray, window: int, metric: str) -> np.ndarray:
    if len(series) < window or window <= 0:
        return np.empty(0)
    kernel = np.ones(window)
    if metric == "skill":
        model = np.convolve(series[:, 0], kernel, "valid")
        baseline = np.convolve(series[:, 1], kernel, "valid")
        return 1.0 - model / baseline
    return np.convolve(series[:, 0], kernel / window, "valid")


def sealed_percentile(live_value: float, h: int, window: int, root: Path, *, metric: str = "skill") -> dict:
    """봉인 2019+ 연속 window 원점 창 분포에서 live_value 의 백분위 P(창 ≤ live) 와 q05·q50·q95.

    q05 의 블록 부트스트랩 90% CI(26주 블록, 2000회)를 함께 낸다 — 임계 JSON 의 q05 CI 와 같은 규약.
    """
    series = _sealed_series(root, h, metric)
    windows = _rolling_windows(series, window, metric)
    if windows.size == 0 or live_value is None:
        return {"percentile": None, "n_windows": int(windows.size), "window": window, "metric": metric}
    total = len(series)
    index = _resample_indices(total, SEALED_Q05_BLOCK, SEALED_Q05_DRAWS, BOOTSTRAP_SEED)
    q05_draws = np.array([np.quantile(_rolling_windows(series[idx], window, metric), 0.05) for idx in index])
    return {
        "percentile": float(np.mean(windows <= live_value)),
        "q05_q50_q95": [float(x) for x in np.quantile(windows, [0.05, 0.50, 0.95])],
        "q05_ci90_block": _interval(q05_draws),
        "n_windows": int(windows.size),
        "n_sealed_origins": total,
        "window": window,
        "metric": metric,
        "proxy": metric == "pup_gap",
        "source": f"{SEALED_LEDGER.as_posix()} scores, {SEALED_FROM}+ 연속 창",
    }


def _sealed_composite_windows(root: Path, windows: Mapping[int, int]) -> np.ndarray:
    """3지평 평균 skill 의 봉인 창 분포 — 같은 시작 원점에 정렬(임계 JSON mean_1_5_21 규약)."""
    per_h = {h: _rolling_windows(_sealed_series(root, h, "skill"), windows[h], "skill") for h in windows}
    length = min(len(v) for v in per_h.values())
    if length == 0:
        return np.empty(0)
    return np.mean([per_h[h][:length] for h in windows], axis=0)


# ---------------------------------------------------------------------------
# ② B4 전 쌍둥이 — V2 C1 번들 NASDAQ 수익 + 원장 ewma_lambda, 봉인 HS 시드 재현
# ---------------------------------------------------------------------------


@dataclass
class B4TwinContext:
    """번들·람다·성숙 PIT 이력 — 한 번 만들어 모든 원점에 쓴다."""

    dates: list[str]
    index: dict[str, int]
    returns: np.ndarray
    path_count: int
    pit_min_matured: int
    pit_maturity: int
    pit_history: dict[int, list[tuple[int, float]]]
    unknown_lambda_origins: list[str]
    lambda_fallback_rule: str
    history_end: str | None


def _contract_parameters(root: Path) -> tuple[int, int, str]:
    from ..timeseries_v8.contracts import load_contract_v8

    contract = load_contract_v8(root)
    return (int(contract["model"]["distribution"]["sealed_path_count"]),
            int(contract["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]),
            str(contract["evaluation"]["outer_start"]))


def _known_lambdas(root: Path, forecasts: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """봉인 평가 원장의 원점별 ewma_lambda(λ 필드만) + 섀도 원장 λ."""
    path = root / SEALED_LEDGER
    known: dict[str, float] = {}
    if path.is_file():
        for row in json.loads(path.read_text(encoding="utf-8").splitlines()[0])["scores"]:
            known[row["date"]] = float(row["ewma_lambda"])
    for forecast in forecasts:
        known.setdefault(forecast["origin"], float(forecast["ewma_lambda"]))
    return known


def _hs_and_fhs(returns: np.ndarray, *, origin: str, forecast: Mapping[str, Any], ewma_lambda: float,
                path_count: int, horizons: Sequence[int]) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """봉인 규칙 그대로: rng = default_rng(seed+1), 지평 1·5·21·63 순서로 기준선 표본을 뽑는다."""
    from ..timeseries.model import deterministic_seed
    from ..timeseries_v2.backtest import _baseline_samples_v2
    from ..timeseries_v8.model import HORIZONS as V8_HORIZONS
    from ..timeseries_v8.model import fhs_horizon_samples

    config = forecast["config"]
    if float(config["fhs_tilt_omega"]) != 0.0:
        raise V8LiveMonitorError("FHS tilt ω>0 은 엔진 평균이 필요해 재구성 범위 밖")
    seed = deterministic_seed(forecast["model_id"], int(forecast["model_version"]), origin)
    rng = np.random.default_rng(seed + 1)
    out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for h in V8_HORIZONS:
        historical = _baseline_samples_v2(returns, horizon=h, count=path_count, rng=rng)["historical_simulation"]
        if h in horizons:
            fhs = fhs_horizon_samples(
                returns, horizon=h, ewma_lambda=ewma_lambda,
                vol_projection=config["fhs_vol_projection"],
                unconditional_window_sessions=int(config["unconditional_window_sessions"]),
                mu_hat_window_sessions=config["mu_hat_window_sessions"],
                tilt_omega=0.0, tilt_cap_sigma=float(config["fhs_tilt_cap_sigma"]),
            )
            out[h] = (fhs, historical)
        if h >= max(horizons):
            break
    return out


def build_b4_twin_context(root: Path, forecasts: Sequence[Mapping[str, Any]], *, now: datetime) -> B4TwinContext:
    """V2 C1 번들(import 전용)과 2007+ 주간 원점의 B4 전 PIT 이력을 만든다.

    성숙 PIT 는 봉인 walk-forward 와 같이 혼합(0.75·FHS + 0.25·HS) CDF 의 실현값 위치다. λ 가 원장에
    없는 원점(봉인 끝 2026-05-14 ~ 첫 섀도 원점 사이)은 직전 알려진 λ 를 이월하고 목록으로 공시한다.
    """
    from ..timeseries.ledger import read_facts
    from ..timeseries_v2.backtest import _weekly_forecast_origins
    from ..timeseries_v2.contracts import load_contract_v2
    from ..timeseries_v2.features import assemble_candidate_bundle
    from ..timeseries_v8.backtest import PIT_MATURITY_SESSIONS
    from ..timeseries_v8.model import mixture_cdf_at

    path_count, pit_min_matured, outer_start = _contract_parameters(root)
    bundle = assemble_candidate_bundle(
        root, contract=load_contract_v2(root), macro_facts=read_facts(root),
        candidate_id="C1", knowledge_cutoff=now.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )
    dates = list(bundle.dates)
    if not dates:
        raise V8LiveMonitorError("V2 C1 번들이 비어 있다")
    returns = np.asarray(bundle.endogenous[:, 0], dtype=float)
    index = {day: i for i, day in enumerate(dates)}
    shadow_positions = [index[f["origin"]] for f in forecasts if f["origin"] in index]
    if not shadow_positions:
        raise V8LiveMonitorError("섀도 원점이 번들에 없다")
    history_limit = max(shadow_positions) - PIT_MATURITY_SESSIONS
    known = _known_lambdas(root, forecasts)
    reference = forecasts[0]
    weight = float(reference["config"]["blend_weight_by_horizon"]["21"])
    history: dict[int, list[tuple[int, float]]] = {h: [] for h in TWIN_HORIZONS}
    unknown: list[str] = []
    carried = None
    for as_of_index, forecast_start in _weekly_forecast_origins(tuple(dates), outer_start=outer_start, horizon=63):
        if as_of_index > history_limit:
            break
        day = dates[as_of_index]
        lam = known.get(day)
        if lam is None:
            if carried is None:
                raise V8LiveMonitorError(f"λ 이월 출발점이 없다: {day}")
            lam = carried
            unknown.append(day)
        carried = lam
        training = returns[:forecast_start]
        samples = _hs_and_fhs(training, origin=day, forecast=reference, ewma_lambda=lam,
                              path_count=path_count, horizons=TWIN_HORIZONS)
        for h in TWIN_HORIZONS:
            if forecast_start + h > len(returns):
                continue
            actual = float(np.sum(returns[forecast_start: forecast_start + h]))
            fhs, historical = samples[h]
            history[h].append((as_of_index, mixture_cdf_at(fhs, historical, weight=weight, value=actual)))
    return B4TwinContext(
        dates=dates, index=index, returns=returns, path_count=path_count,
        pit_min_matured=pit_min_matured, pit_maturity=PIT_MATURITY_SESSIONS, pit_history=history,
        unknown_lambda_origins=unknown,
        lambda_fallback_rule="봉인 평가 원장·섀도 원장에 λ 가 없는 주간 원점은 직전 알려진 λ 이월",
        history_end=dates[history_limit] if 0 <= history_limit < len(dates) else None,
    )


def _twin_grids(row: Mapping[str, Any], context: B4TwinContext) -> dict[int, dict[str, Any]]:
    """한 섀도 원점의 h21/h63 B4 전 grid·재구성 B4 후 grid·검증 수치."""
    from ..timeseries_v8.model import mixture_quantile_function, recalibration_levels

    origin = row["origin"]
    if origin not in context.index:
        raise V8LiveMonitorError(f"원점이 번들에 없다: {origin}")
    position = context.index[origin]
    levels_count = int(row["grid_levels_count"])
    levels = (np.arange(levels_count) + 0.5) / levels_count
    samples = _hs_and_fhs(context.returns[: position + 1], origin=origin, forecast=row,
                          ewma_lambda=float(row["ewma_lambda"]), path_count=context.path_count,
                          horizons=TWIN_HORIZONS)
    out: dict[int, dict[str, Any]] = {}
    for h in TWIN_HORIZONS:
        block = row["horizons"][str(h)]
        weight = float(row["config"]["blend_weight_by_horizon"][str(h)])
        fhs, historical = samples[h]
        pre = np.maximum.accumulate(mixture_quantile_function(fhs, historical, weight=weight, levels=levels))
        matured = np.array([p for i, p in context.pit_history[h] if i + context.pit_maturity <= position])
        ledger = np.asarray(block["quantile_grid"], dtype=float)
        hs_mae = float(np.mean(np.abs(np.quantile(historical, levels) - np.asarray(block["baseline_quantile_grid"]))))
        post = None
        if matured.size >= context.pit_min_matured and bool(block.get("recalibrated")):
            remapped = recalibration_levels(
                matured, target_levels=levels, shrinkage=float(row["config"]["pit_recalibration_shrinkage"]))
            post = np.maximum.accumulate(mixture_quantile_function(fhs, historical, weight=weight, levels=remapped))
        out[h] = {
            "pre": pre,
            "post_recon": post,
            "hs_mae": hs_mae,
            "grid_max_abs": None if post is None else float(np.max(np.abs(post - ledger))),
            "matured_pits": int(matured.size),
            "matured_pit_count_ledger": block.get("matured_pit_count"),
        }
    return out


def b4_pre_twin_h21_h63(row: dict, root: Path, *, context: B4TwinContext | None = None,
                        now: datetime | None = None) -> dict[int, np.ndarray] | None:
    """② h21/h63 B4 전 grid. 재현 검증(HS MAE ≤ 0.0025, 원장 grid ±0.004) 실패면 None."""
    try:
        context = context or build_b4_twin_context(root, [row], now=now or datetime.now(timezone.utc))
        grids = _twin_grids(row, context)
    except (V8LiveMonitorError, KeyError, ValueError):
        return None
    for item in grids.values():
        if (item["hs_mae"] > TWIN_HS_MAE_MAX or item["grid_max_abs"] is None
                or item["grid_max_abs"] > TWIN_GRID_MAX_ABS):
            return None
    return {h: item["pre"] for h, item in grids.items()}


# ---------------------------------------------------------------------------
# 저장소 문맥 — 원장 grid 행·XNAS 진단 행
# ---------------------------------------------------------------------------


def _read_jsonl(root: Path, relative: Path) -> list[dict[str, Any]]:
    path = root / relative
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class _Context:
    root: Path
    now: datetime
    as_of: date
    forecasts: list[dict[str, Any]]
    resolutions: list[dict[str, Any]]
    xnas_rows: list[dict[str, Any]]
    cal: XnasCalendar
    archive: NasdaqArchive
    sample_bound: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved_keys(self) -> set[tuple[str, int]]:
        """표본에 든 원장 해소 쌍 (forecast_id, h) — XNAS matched 코호트도 이 집합으로 묶는다."""
        return {(r["forecast_id"], int(r["horizon"])) for r in self.resolutions}


def _bounded_resolutions(rows: Sequence[Mapping[str, Any]], as_of: date,
                         resolution_ids: frozenset[str] | None) -> list[dict[str, Any]]:
    """resolved_session ≤ as_of, 허용 목록이 있으면 그 id 만. 목록에 있는데 원장에 없으면 fail-closed."""
    picked = [dict(r) for r in rows if date.fromisoformat(r["resolved_session"]) <= as_of]
    if resolution_ids is None:
        return picked
    missing = sorted(resolution_ids - {r["resolution_id"] for r in picked})
    if missing:
        raise V8LiveMonitorError(f"허용 목록 해소 행 {len(missing)}건이 원장(≤ as_of)에 없다: {missing[:3]}")
    return [r for r in picked if r["resolution_id"] in resolution_ids]


def _load_context(root: Path, *, now: datetime, as_of: date | None,
                  resolution_ids: frozenset[str] | None = None) -> _Context:
    from ..timeseries_v2.market_archive import read_market_observations

    if now.tzinfo is None:
        raise V8LiveMonitorError("now 는 timezone-aware 여야 한다")
    xnas_all, summary = build_diagnostics(root, now=now, as_of=as_of)
    resolved_as_of = date.fromisoformat(summary["as_of_session"])
    observations = read_market_observations(
        root, knowledge_cutoff=now.astimezone(timezone.utc).isoformat(timespec="seconds"))
    archive = NasdaqArchive.from_observations(observations, as_of=resolved_as_of)
    cal = XnasCalendar.build(CALENDAR_START, resolved_as_of + timedelta(days=CALENDAR_LOOKAHEAD_DAYS))
    forecasts = [f for f in _read_jsonl(root, V8_FORECAST_LEDGER)
                 if date.fromisoformat(f["origin"]) <= resolved_as_of
                 and datetime.fromisoformat(f["knowledge_cutoff"]) <= now]
    if not forecasts:
        raise V8LiveMonitorError("V8 섀도 예측 원장이 비어 있다(as_of·now 경계 안)")
    known = {f["forecast_id"] for f in forecasts}
    resolutions = _bounded_resolutions(_read_jsonl(root, V8_RESOLUTION_LEDGER), resolved_as_of, resolution_ids)
    orphans = [r["resolution_id"] for r in resolutions if r["forecast_id"] not in known]
    if orphans:
        raise V8LiveMonitorError(f"해소 행의 예측이 now 경계 밖이거나 없다: {orphans[:3]}")
    xnas_rows = [r for r in xnas_all if r["forecast_id"] in known]
    bound = {
        "forecasts": "origin ≤ as_of AND knowledge_cutoff ≤ now",
        "resolutions": ("resolved_session ≤ as_of" if resolution_ids is None
                        else "resolved_session ≤ as_of AND resolution_id ∈ 허용 목록(고정 표본)"),
        "resolution_allowlist_n": None if resolution_ids is None else len(resolution_ids),
        "xnas_rows_excluded_after_now": len(xnas_all) - len(xnas_rows),
        "note": "해소 원장에 기록 시각이 없어 as_of 만으로는 표본이 고정되지 않는다 — 늦게 해소된 쌍이 들어올 수 있음",
    }
    return _Context(root, now, resolved_as_of, forecasts, resolutions, xnas_rows, cal, archive, bound)


def _post_dated(forecast: Mapping[str, Any], target: date, cal: XnasCalendar) -> bool:
    return datetime.fromisoformat(forecast["knowledge_cutoff"]) > cal.close_utc(target)


def _grid_rows(context: _Context) -> list[ScoredRow]:
    by_id = {f["forecast_id"]: f for f in context.forecasts}
    rows = []
    for resolution in context.resolutions:
        forecast = by_id.get(resolution["forecast_id"])
        if forecast is None:
            raise V8LiveMonitorError(f"고아 해소 행: {resolution['resolution_id']}")
        h = int(resolution["horizon"])
        origin = date.fromisoformat(forecast["origin"])
        target = date.fromisoformat(resolution["resolved_session"])
        xnas_target = context.cal.offset(origin, h)
        rows.append(_score_row(forecast, h, float(resolution["actual_log_return"]), target.isoformat(),
                               context.cal.between(origin, target), _post_dated(forecast, xnas_target, context.cal)))
    return rows


def _xnas_rows(context: _Context, *, matched_only: bool) -> list[ScoredRow]:
    by_id = {f["forecast_id"]: f for f in context.forecasts}
    rows = []
    resolved = context.resolved_keys
    for diagnostic in context.xnas_rows:
        # matched = 표본에 든 원장 해소 쌍만(같은 해소 경계). stage 만 보면 허용 목록 밖 해소가 섞인다.
        if matched_only and (diagnostic["stage"] != "reconciled"
                             or (diagnostic["forecast_id"], int(diagnostic["h"])) not in resolved):
            continue
        forecast = by_id[diagnostic["forecast_id"]]
        origin = date.fromisoformat(forecast["origin"])
        target = date.fromisoformat(diagnostic["xnas_target_session"])
        rows.append(_score_row(forecast, int(diagnostic["h"]), float(diagnostic["y_xnas"]), target.isoformat(),
                               context.cal.between(origin, target), bool(diagnostic["target_closed_at_emit"])))
    return rows


def _as_scored(row: Mapping[str, Any] | ScoredRow) -> ScoredRow:
    if isinstance(row, ScoredRow):
        return row
    # 테스트·외부 호출용 최소 매핑: crps_model·crps_baseline·origin·h(+ z)
    return ScoredRow(
        origin=str(row["origin"]), h=int(row["h"]), y=float(row.get("y", 0.0)), target=str(row.get("target", "")),
        window=(), grid=np.empty(0), baseline=np.empty(0), p_up=float(row.get("p_up", 0.5)),
        ewma_lambda=float(row.get("ewma_lambda", 0.97)), post_dated=bool(row.get("post_dated", False)),
        crps_model=float(row["crps_model"]), crps_baseline=float(row["crps_baseline"]),
        pit=float(row.get("pit", 0.5)), z=float(row.get("z", 0.0)),
        crps_location_neutral=float(row.get("crps_location_neutral", row["crps_model"])),
    )


# ---------------------------------------------------------------------------
# 충격 창 — 원점 행 λ 의 XNAS 사전 변동성 기준 일간 |z|
# ---------------------------------------------------------------------------


def _xnas_daily_returns(context: _Context) -> tuple[list[date], np.ndarray]:
    days, values = [], []
    sessions = [d for d in context.cal.sessions if d <= context.as_of and d in context.archive.closes]
    for previous, current in zip(sessions, sessions[1:]):
        if context.cal.previous(current) != previous:
            continue  # 아카이브 결측 세션 사이 수익은 만들지 않는다
        days.append(current)
        values.append(math.log(context.archive.close(current) / context.archive.close(previous)))
    return days, np.asarray(values, dtype=float)


def _prior_ewma_variance(returns: np.ndarray, lam: float) -> np.ndarray:
    """σ²_{t|t−1}: v_0 = r_0², v_t = λ v_{t−1} + (1−λ) r_{t−1}² (V8 재귀와 같은 사전 정보 정의)."""
    variance = np.empty_like(returns)
    variance[0] = max(float(returns[0]) ** 2, 1e-16)
    for t in range(1, len(returns)):
        variance[t] = lam * variance[t - 1] + (1.0 - lam) * returns[t - 1] ** 2
    return variance


def _shock_days(context: _Context, lambdas: set[float]) -> dict[float, dict[date, float]]:
    days, returns = _xnas_daily_returns(context)
    out: dict[float, dict[date, float]] = {}
    for lam in sorted(lambdas):
        z = returns / np.sqrt(_prior_ewma_variance(returns, lam))
        out[lam] = {day: float(value) for day, value in zip(days, z) if abs(value) > SHOCK_ABS_Z}
    return out


def _row_shocks(row: ScoredRow, shocks: Mapping[float, Mapping[date, float]]) -> list[str]:
    table = shocks.get(row.ewma_lambda, {})
    return [day.isoformat() for day in row.window if day in table]


# ---------------------------------------------------------------------------
# 지평 블록·경보 라벨
# ---------------------------------------------------------------------------


def _skill(rows: Sequence[ScoredRow]) -> float | None:
    if not rows:
        return None
    return float(1.0 - sum(r.crps_model for r in rows) / sum(r.crps_baseline for r in rows))


def _mean_ci(values: np.ndarray, h: int) -> dict[str, Any]:
    n = len(values)
    block = _block_length(h, n)
    iid = values[_resample_indices(n, 1, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED)].mean(axis=1)
    blocked = values[_resample_indices(n, block, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED)].mean(axis=1)
    return {"ci90_iid": _interval(iid), "ci90_block": _interval(blocked), "block_length": block}


def _poisson_binomial_block(rows: Sequence[ScoredRow]) -> dict[str, Any]:
    p = [r.p_up for r in rows]
    ups = int(sum(r.y > 0 for r in rows))
    lower = poisson_binomial_cdf(p, ups)
    upper = 1.0 - poisson_binomial_cdf(p, ups - 1)
    return {
        "k_up": ups, "expected_up": float(sum(p)),
        "p_le_observed": lower, "p_ge_observed": upper,
        "two_sided_min_tail": float(min(lower, upper)),
        "method": "exact_dp_convolution", "independence_assumed": True,
        "note": "겹치는 창(h21·h63)은 독립 가정이 낙관적 — 꼬리확률 과소 가능",
    }


def _decomposition(rows: Sequence[ScoredRow]) -> dict[str, Any]:
    base = sum(r.crps_baseline for r in rows)
    model = sum(r.crps_model for r in rows)
    neutral = sum(r.crps_location_neutral for r in rows)
    return {
        "loss_vs_hs": model / base - 1.0,
        "delta_loc": (model - neutral) / base,
        "delta_shape": neutral / base - 1.0,
        "skill_location_neutral_twin": 1.0 - neutral / base,
        "identity": "loss_vs_hs = delta_loc + delta_shape = −skill",
        "location_neutral": "grid − q50 + q50_HS",
    }


def _horizon_block(rows: Sequence[ScoredRow], h: int, root: Path, thresholds: Mapping[str, Any],
                   shocks: Mapping[float, Mapping[date, float]], *, post_dated_horizon: bool) -> dict[str, Any] | None:
    k = WINDOW_K[h]
    picked = _last_k(rows, h, k)
    if not picked:
        return None
    live = thresholds["v8_live"]
    minimum = int(live["minimum_origins"])
    key = str(h)
    n = len(picked)
    l1 = rolling_skill(picked, h, k)
    l1["threshold_q05"] = live["L1_skill_q05"].get(key)
    # 사전고정 q05 는 창 k 로 정의됐다. 라이브 n < k 면 n 창 값을 k 창 임계와 견주는 셈이라 병기한다.
    l1["threshold_window_k"] = k
    l1["threshold_window_matches_n"] = n == k
    l1["sealed"] = sealed_percentile(l1["skill"], h, n, root, metric="skill")
    z = np.array([r.z for r in picked])
    l2 = {"z_mean": float(z.mean()), **_mean_ci(z, h), "threshold_zq05": live["L2_location_z_q05"].get(key),
          "sealed": sealed_percentile(float(z.mean()), h, n, root, metric="z")}
    pit = np.array([r.pit for r in picked])
    band = live["L3_pit_mean_band"]
    l3 = {"pit_mean": float(pit.mean()), "pit_var": float(pit.var(ddof=0)), "uniform_var": 1.0 / 12.0,
          **_mean_ci(pit, h), "band": band, "outside_band": not (band[0] <= float(pit.mean()) <= band[1]),
          "status": "information_only"}
    p_up = np.array([r.p_up for r in picked])
    up = np.array([1.0 if r.y > 0 else 0.0 for r in picked])
    gap = float(p_up.mean() - up.mean())
    l4 = {"p_up_mean": float(p_up.mean()), "freq_up": float(up.mean()), "gap": gap,
          **_mean_ci(p_up - up, h), "poisson_binomial": _poisson_binomial_block(picked),
          "sealed": sealed_percentile(gap, h, n, root, metric="pup_gap")}
    row_shocks = {(r.origin, r.h): _row_shocks(r, shocks) for r in picked}
    shock_days = sorted({d for days in row_shocks.values() for d in days})
    ex_shock = [r for r in picked if not row_shocks[(r.origin, r.h)]]
    ex_origin = [r for r in picked if r.origin != EXCLUDED_ORIGIN_SENSITIVITY]
    breaches = []
    if l1["threshold_q05"] is not None and l1["skill"] < l1["threshold_q05"]:
        breaches.append("L1_skill_below_q05")
    if l2["threshold_zq05"] is not None and l2["z_mean"] < l2["threshold_zq05"]:
        breaches.append("L2_z_below_q05")
    pinned = l1["threshold_q05"] is not None and l2["threshold_zq05"] is not None
    if n < minimum:
        state = "insufficient"
    elif post_dated_horizon:
        percentile = l1["sealed"].get("percentile")
        state = "near_tail" if (breaches or (percentile is not None and percentile <= NEAR_TAIL_PERCENTILE)) else "normal"
    elif not pinned:
        state = "no_pinned_threshold"
    else:
        state = "breach" if breaches else "normal"
    return {
        "h": h,
        "n": n,
        "n_origins": len({r.origin for r in picked}),
        "n_dates": len({r.target for r in picked}),
        "window_k": k,
        "origins": [r.origin for r in picked],
        "post_dated_rows": sum(r.post_dated for r in picked),
        "L1": l1, "L2": l2, "L3": l3, "L4": l4,
        "decomposition": _decomposition(picked),
        "sensitivity": {
            "ex_shock_window": {"rule": f"창 안 일간 |z|>{SHOCK_ABS_Z:g} (원점 λ 의 XNAS 사전 EWMA)",
                                "n": len(ex_shock), "skill": _skill(ex_shock),
                                "excluded": [r.origin for r in picked if row_shocks[(r.origin, r.h)]]},
            "ex_origin_2026_10_09": {"n": len(ex_origin), "skill": _skill(ex_origin)},
        },
        "shock_days": shock_days,
        "single_episode": len(shock_days) == 1,
        "single_episode_scope": "창 안 |z|>4 충격일 수 — 1 이면 꼬리가 한 에피소드에 종속",
        "minimum_origins": minimum,
        "sufficiency": "ok" if n >= minimum else "insufficient",
        "state": state,
        "breaches": breaches if not post_dated_horizon else [],
        "information_flags": (["near_tail"] if post_dated_horizon and state == "near_tail" else []),
    }


def _label(state: str, single_episode: bool) -> str:
    if state == "breach":
        return f"{LABEL_BREACH}({'단일 에피소드' if single_episode else '복수 에피소드'})"
    if state == "normal":
        return LABEL_NORMAL
    return {"insufficient": "표본 부족(insufficient)", "no_pinned_threshold": "사전고정 임계 없음",
            "near_tail": "꼬리 근접(정보 — 사전 기록 아님)"}.get(state, state)


def _alarm_label(breached: Sequence[Mapping[str, Any]], states: Mapping[str, str]) -> str:
    """대표 지평 상태 → 한 줄 라벨. 이탈 > 정상 > 표본 부족 > 임계 없음 순."""
    if breached:
        return str(breached[0]["label"])
    if any(s == "normal" for s in states.values()):
        return LABEL_NORMAL
    if not states or any(s == "insufficient" for s in states.values()):
        return _label("insufficient", False)
    return _label("no_pinned_threshold", False)


def _basis_block(rows: Sequence[ScoredRow], root: Path, thresholds: Mapping[str, Any],
                 shocks: Mapping[float, Mapping[date, float]], representative: Sequence[int],
                 post_dated: Sequence[int], *, cohort: str, label: str) -> dict[str, Any]:
    out: dict[str, Any] = {"cohort": cohort, "label": label, "representative": {}, "post_dated": {}}
    for h in HORIZONS:
        is_post = h in post_dated
        block = _horizon_block(rows, h, root, thresholds, shocks, post_dated_horizon=is_post)
        if block is None:
            continue
        block["label"] = _label(block["state"], block["single_episode"])
        (out["post_dated"] if is_post else out["representative"])[f"h{h}"] = block
    out["composite_mean_1_5_21"] = _composite(rows, root, thresholds)
    return out


def _composite(rows: Sequence[ScoredRow], root: Path, thresholds: Mapping[str, Any]) -> dict[str, Any] | None:
    picked = {h: _last_k(rows, h, WINDOW_K[h]) for h in COMPOSITE_HORIZONS}
    if any(not v for v in picked.values()):
        return None
    skills = [_skill(picked[h]) for h in COMPOSITE_HORIZONS]
    value = float(np.mean(skills))
    windows = _sealed_composite_windows(root, {h: len(picked[h]) for h in COMPOSITE_HORIZONS})
    threshold = thresholds["v8_live"]["L1_skill_q05"].get("mean_1_5_21")
    return {
        "skill_mean": value,
        "n_by_h": {f"h{h}": len(picked[h]) for h in COMPOSITE_HORIZONS},
        "window_k_by_h": {f"h{h}": WINDOW_K[h] for h in COMPOSITE_HORIZONS},
        "threshold_q05": threshold,
        "below_q05_information_only": None if threshold is None else value < threshold,
        "sealed_percentile": float(np.mean(windows <= value)) if windows.size else None,
        "sealed_n_windows": int(windows.size),
        "representative": False,
        "note": "post_dated h1 을 포함하므로 정보용 — 경보에 쓰지 않는다. 같은 basis 안의 단순 평균",
    }


# ---------------------------------------------------------------------------
# 쌍둥이 요약
# ---------------------------------------------------------------------------


def _twin_report(context: _Context, bases: Mapping[str, Sequence[ScoredRow]],
                 twin_context: B4TwinContext | None, twin_error: str | None) -> dict[str, Any]:
    from ..timeseries.backtest import sample_crps

    report: dict[str, Any] = {
        "scoring_excluded": True, "display_only": True,
        "caveat": "연구 쌍둥이 — 채점·판정·승격 근거 아님(사전등록 전). ΔB4 부호는 결과 방향에 기계적으로 종속",
        "verification": {"hs_mae_max": TWIN_HS_MAE_MAX, "grid_max_abs_max": TWIN_GRID_MAX_ABS},
    }
    if twin_context is None:
        report.update({"status": "unreconstructable", "reason": twin_error})
        return report
    per_origin: dict[str, dict[int, dict[str, Any]]] = {}
    try:
        for forecast in context.forecasts:
            per_origin[forecast["origin"]] = _twin_grids(forecast, twin_context)
    except (V8LiveMonitorError, KeyError, ValueError) as exc:  # 번들 밖 원점 등 — 숫자 없이 닫는다
        report.update({"status": "unreconstructable", "reason": f"{type(exc).__name__}: {exc}"})
        return report
    checks = [(o, h, g) for o, grids in per_origin.items() for h, g in grids.items()]
    failures = [
        {"origin": o, "h": h, "hs_mae": g["hs_mae"], "grid_max_abs": g["grid_max_abs"]}
        for o, h, g in checks
        if g["hs_mae"] > TWIN_HS_MAE_MAX or g["grid_max_abs"] is None or g["grid_max_abs"] > TWIN_GRID_MAX_ABS
    ]
    report["verification"].update({
        "n_checked": len(checks),
        "hs_mae_observed_max": max(g["hs_mae"] for _, _, g in checks),
        "grid_max_abs_observed_max": (None if any(g["grid_max_abs"] is None for _, _, g in checks)
                                      else max(g["grid_max_abs"] for _, _, g in checks)),
        "failures": failures,
        "unknown_lambda_origins": twin_context.unknown_lambda_origins,
        "lambda_fallback_rule": twin_context.lambda_fallback_rule,
        "pit_history_end": twin_context.history_end,
        "lambda_source": "봉인 평가 원장 scores.ewma_lambda 필드(점수는 읽지 않음) + 섀도 원장",
    })
    if failures:
        report["status"] = "unreconstructable"
        report["reason"] = "재현 검증 실패 — 숫자를 싣지 않는다"
        return report
    report["status"] = "reconstructed"
    by_h: dict[str, Any] = {}
    for h in TWIN_HORIZONS:
        origins = sorted(per_origin)
        pre = [per_origin[o][h]["pre"] for o in origins]
        ledger = [np.asarray(next(f for f in context.forecasts if f["origin"] == o)["horizons"][str(h)]["quantile_grid"])
                  for o in origins]
        entry: dict[str, Any] = {
            "n_origins": len(origins),
            "p_up_pre_mean": float(np.mean([np.mean(g > 0) for g in pre])),
            "p_up_ledger_mean": float(np.mean([np.mean(g > 0) for g in ledger])),
            "width80_ratio_ledger_over_pre_mean": float(np.mean(
                [(_grid_quantile(b, Q90) - _grid_quantile(b, Q10)) / (_grid_quantile(a, Q90) - _grid_quantile(a, Q10))
                 for a, b in zip(pre, ledger)])),
            "per_origin": [
                {"origin": o, "p_up_pre": float(np.mean(per_origin[o][h]["pre"] > 0)),
                 "p_up_ledger": float(np.mean(l > 0)), "median_pre": _grid_quantile(per_origin[o][h]["pre"], Q50),
                 "median_ledger": _grid_quantile(l, Q50), "hs_mae": per_origin[o][h]["hs_mae"],
                 "grid_max_abs": per_origin[o][h]["grid_max_abs"]}
                for o, l in zip(origins, ledger)
            ],
            "scored": {},
        }
        for basis, rows in bases.items():
            picked = _last_k(rows, h, WINDOW_K[h])
            if not picked:
                continue
            base = sum(r.crps_baseline for r in picked)
            crps_pre = sum(sample_crps(per_origin[r.origin][h]["pre"], r.y) for r in picked)
            crps_post = sum(sample_crps(per_origin[r.origin][h]["post_recon"], r.y) for r in picked)
            crps_ledger = sum(r.crps_model for r in picked)
            entry["scored"][basis] = {
                "n": len(picked), "origins": [r.origin for r in picked],
                "skill_pre_b4": 1.0 - crps_pre / base,
                "skill_post_recon": 1.0 - crps_post / base,
                "skill_ledger_grid": 1.0 - crps_ledger / base,
                "delta_b4": (crps_ledger - crps_pre) / base,
                "delta_b4_note": "양수 = B4 가 CRPS 를 키움. 부호는 결과 방향(하락이면 악화)에 기계적으로 종속",
            }
        by_h[f"h{h}"] = entry
    report["b4_pre"] = by_h
    return report


def _location_neutral_report(bases: Mapping[str, Sequence[ScoredRow]]) -> dict[str, Any]:
    out: dict[str, Any] = {"rule": "grid − q50 + q50_HS (원장만으로 결정론)", "scoring_excluded": True}
    for basis, rows in bases.items():
        out[basis] = {}
        for h in HORIZONS:
            picked = _last_k(rows, h, WINDOW_K[h])
            if picked:
                out[basis][f"h{h}"] = {"n": len(picked), **_decomposition(picked)}
    return out


# ---------------------------------------------------------------------------
# 감시 본체
# ---------------------------------------------------------------------------


def _null_report(status: str, threshold_status: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "status": status, "threshold_status": threshold_status,
        "notice": NOTICE, "display_only": True, "scoring_excluded": True, "network_fetch_enabled": False,
        "n": None, "n_origins": None, "n_dates": None, "single_episode": None,
        "bases": None, "alarm": None, "twins": None,
        "detail": "임계 해시 불일치·부재 — 모든 지표 null (사전고정 문서 참조)",
    }


def _disclosures(root: Path, context: _Context, thresholds: Mapping[str, Any]) -> dict[str, Any]:
    sealed_hash = None
    path = root / SEALED_LEDGER
    if path.is_file():
        sealed_hash = json.loads(path.read_text(encoding="utf-8").splitlines()[0]).get("model_code_hash")
    live_hashes = sorted({f["model_code_hash"] for f in context.forecasts})
    identity = None
    if (root / BASELINE_IDENTITY).is_file():
        payload = json.loads((root / BASELINE_IDENTITY).read_text(encoding="utf-8"))
        identity = {"v8_tier1_identity": payload.get("verdict", {}).get("v8_tier1_identity"),
                    "v8_tier2_status": (payload.get("v8_tier2") or {}).get("status"),
                    "v8_tier2_mismatches": (payload.get("v8_tier2") or {}).get("mismatches")}
    return {
        "model_code_hash": {"live": [h[:8] for h in live_hashes], "sealed": (sealed_hash or "")[:8] or None,
                            "same_model_basis": "identity replay PASS (baseline_identity.json)",
                            "identity_replay": identity},
        "in_sample": "2007~2018 은 개발창(in-sample) — 봉인 백분위는 2019+ 창만",
        "mde": {"skill_n12": thresholds["v8_live"].get("mde_skill_n12"),
                "note": "검정력 낮음 — '이탈 없음'은 '변화 없음'의 증거가 아니다"},
        "b4_twin_history": ("쌍둥이 λ 는 봉인 평가 원장 ewma_lambda 필드(2007~)·PIT 이력은 2007~ 재계산"
                            "(2015~2018 수익 포함) — 라이브 모델이 스스로 계산하는 B4 맵과 같은 입력이며 새 홀드아웃 개봉 아님"),
        "sample_bound": context.sample_bound,
        "b4_sign": "ΔB4 부호는 결과 방향(하락이면 악화)에 기계적으로 종속 — 단기 부호로 B4 를 판정하지 않는다",
        "operational_gate": "operational_gate 와 무관 — 공시 라벨 전용, 게이트·승격·숨김·재예측 미연결",
        "post_dated": "h1 은 발행 시점에 목표가 이미 실현 — pseudo-OOS(사전 기록 아님)",
        "label_basis_mixing": "prohibited",
        "probability_space": PROBABILITY_SPACE,
    }


def run_monitor(root: Path, *, thresholds: dict | None, threshold_status: str = "ok",
                now: datetime | None = None, as_of: date | None = None,
                with_twins: bool = True, resolution_ids: Sequence[str] | None = None) -> dict:
    """감시 보고서. 임계가 없거나 해시 불일치면 모든 지표 null + status.

    resolution_ids: 해소 행 허용 목록(고정 표본 재연용). None 이면 resolved_session ≤ as_of 전부.
    """
    if thresholds is None:
        return _null_report(threshold_status, threshold_status)
    now = now or datetime.now(timezone.utc)
    context = _load_context(root, now=now, as_of=as_of,
                            resolution_ids=None if resolution_ids is None else frozenset(resolution_ids))
    live = thresholds["v8_live"]
    post_dated = [int(h) for h in live["post_dated_horizons"]]
    representative = [int(h) for h in live["representative_horizons"]]
    bases = {
        GRID_BASIS: _grid_rows(context),
        f"{LABEL_BASIS}.matched_ledger_rows": _xnas_rows(context, matched_only=True),
        f"{LABEL_BASIS}.all_closed_targets": _xnas_rows(context, matched_only=False),
    }
    shocks = _shock_days(context, {r.ewma_lambda for rows in bases.values() for r in rows})
    labels = {
        GRID_BASIS: ("resolved_ledger_rows", "원장 grid 라벨(1차·공식 basis)"),
        f"{LABEL_BASIS}.matched_ledger_rows": ("resolved_ledger_rows", "XNAS 진단 — 원장 해소 쌍"),
        f"{LABEL_BASIS}.all_closed_targets": ("reconciled+provisional", "XNAS 진단 — 목표 종가 확정 쌍 전부"),
    }
    blocks = {name: _basis_block(rows, root, thresholds, shocks, representative, post_dated,
                                 cohort=labels[name][0], label=labels[name][1])
              for name, rows in bases.items()}
    primary = blocks[GRID_BASIS]["representative"]
    breached = [{"h": b["h"], "breaches": b["breaches"], "label": b["label"]}
                for b in primary.values() if b["state"] == "breach"]
    states = {key: b["state"] for key, b in primary.items()}
    alarm_label = _alarm_label(breached, states)
    twin_context, twin_error = None, None
    if with_twins:
        try:
            twin_context = build_b4_twin_context(root, context.forecasts, now=now)
        except Exception as exc:  # noqa: BLE001 — 재구성 실패는 unreconstructable 로 닫는다
            twin_error = f"{type(exc).__name__}: {exc}"
    else:
        twin_error = "with_twins=False"
    all_rows = [r for rows in bases.values() for r in rows]
    all_shocks = sorted({d for r in all_rows for d in _row_shocks(r, shocks)})
    resolved_origins = sorted({r["origin"] for r in context.resolutions})
    return {
        "schema_version": SCHEMA_VERSION,
        "verb": "v8-live-monitor",
        "status": "ok",
        "threshold_status": threshold_status,
        "threshold_set_id": thresholds.get("threshold_set_id"),
        "threshold_hash": PINNED_THRESHOLD_HASH,
        "notice": NOTICE,
        "display_only": True,
        "scoring_excluded": True,
        "network_fetch_enabled": False,
        "as_of_session": context.as_of.isoformat(),
        "last_resolved_origin": resolved_origins[-1] if resolved_origins else None,
        "monitor_id": f"v8lm-{resolved_origins[-1] if resolved_origins else 'none'}-{MONITOR_VERSION}",
        "n": len(bases[GRID_BASIS]),
        "n_origins": len({r.origin for r in bases[GRID_BASIS]}),
        "n_dates": len({r.target for r in bases[GRID_BASIS]}),
        "n_note": "n·n_origins·n_dates 는 1차 basis(원장 grid) 해소 행 기준",
        "single_episode": len(all_shocks) == 1,
        "shock_days": all_shocks,
        "label_bases": [GRID_BASIS, LABEL_BASIS],
        "label_basis_mixing": "prohibited",
        "probability_space": PROBABILITY_SPACE,
        "representative_horizons": [h for h in representative if h not in post_dated],
        "post_dated_horizons": post_dated,
        "post_dated_label": POST_DATED_LABEL,
        "window_k": {f"h{h}": k for h, k in WINDOW_K.items()},
        "alarm": {"basis": GRID_BASIS, "label": alarm_label, "breaches": breached, "states": states,
                  "effect_scope": "공시 라벨 전용 — 자동 재예측·재학습·게이트 숨김 없음"},
        "bases": blocks,
        "twins": {
            "location_neutral": _location_neutral_report(bases),
            "b4_pre_h21_h63": _twin_report(context, bases, twin_context, twin_error),
            "h1_h5_b4_pre": "범위 밖 — tier2 replay 필요",
        },
        "disclosures": _disclosures(root, context, thresholds),
    }


# ---------------------------------------------------------------------------
# 원장 행·derived·CLI
# ---------------------------------------------------------------------------


def _compact_block(block: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "n": block["n"], "state": block["state"], "label": block["label"],
        "skill": block["L1"]["skill"], "skill_sealed_percentile": block["L1"]["sealed"].get("percentile"),
        "z_mean": block["L2"]["z_mean"], "pit_mean": block["L3"]["pit_mean"], "pup_gap": block["L4"]["gap"],
        "pb_two_sided_min_tail": block["L4"]["poisson_binomial"]["two_sided_min_tail"],
        "single_episode": block["single_episode"],
    }


def ledger_row(report: Mapping[str, Any]) -> dict[str, Any]:
    """주 1행(identity v8lm-{last_resolved_origin}-v1) — 시각을 넣지 않아 같은 입력이면 같은 바이트."""
    bases = {}
    for name, block in (report.get("bases") or {}).items():
        bases[name] = {
            group: {key: _compact_block(b) for key, b in block[group].items()}
            for group in ("representative", "post_dated")
        }
    twin = (report.get("twins") or {}).get("b4_pre_h21_h63") or {}
    twin_summary = {"status": twin.get("status")}
    if twin.get("status") == "reconstructed":
        twin_summary["h21"] = {basis: {k: v for k, v in item.items() if k in ("n", "skill_pre_b4", "skill_post_recon",
                                                                             "skill_ledger_grid", "delta_b4")}
                               for basis, item in twin["b4_pre"]["h21"]["scored"].items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "monitor_id": report["monitor_id"],
        "as_of_session": report["as_of_session"],
        "last_resolved_origin": report["last_resolved_origin"],
        "status": report["status"],
        "threshold_status": report["threshold_status"],
        "threshold_hash": report["threshold_hash"],
        "notice": NOTICE,
        "display_only": True,
        "scoring_excluded": True,
        "n": report["n"], "n_origins": report["n_origins"], "n_dates": report["n_dates"],
        "single_episode": report["single_episode"],
        "alarm": report["alarm"],
        "bases": bases,
        "b4_pre_twin": twin_summary,
        "label_basis_mixing": "prohibited",
        "probability_space": PROBABILITY_SPACE,
    }


def append_monitor(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """멱등 append. 같은 identity 가 있으면 쓰지 않는다(본문이 달라도 — 주 1행, 첫 기록 고정)."""
    with writer_lock(root):
        existing = read_chain(root, LEDGER_RELATIVE)
        for previous in existing:
            if previous.get("monitor_id") == row["monitor_id"]:
                body = {k: v for k, v in previous.items() if k not in ("previous_hash", "content_hash")}
                return {"appended": 0, "identity": row["monitor_id"],
                        "status": "identical" if body == dict(row) else "identity_exists_body_differs",
                        "rows": len(existing)}
        append_event(root, LEDGER_RELATIVE, dict(row))
        return {"appended": 1, "identity": row["monitor_id"], "status": "appended", "rows": len(existing) + 1}


def write_derived(root: Path, report: Mapping[str, Any]) -> Path:
    """결정론 재생성(tmp+os.replace). data/mts_research/derived/ 아래만."""
    path = root / DERIVED_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=_json) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)
    return path


def _json(value: Any) -> Any:
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"직렬화 불가: {type(value).__name__}")


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise V8LiveMonitorError("--now 는 timezone 을 포함해야 한다")
    return parsed.astimezone(timezone.utc)


def _plain(report: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(report, ensure_ascii=False, allow_nan=False, default=_json))


def run_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict]:
    """dry-run(기본): 보고서 출력. --append: 원장 1행(멱등) + derived 재생성."""
    thresholds, threshold_status = load_pinned_thresholds(root)
    try:
        now = _parse_now(getattr(args, "now", None))
        as_of_raw = getattr(args, "as_of", None)
        report = _plain(run_monitor(root, thresholds=thresholds, threshold_status=threshold_status, now=now,
                                    as_of=date.fromisoformat(as_of_raw) if as_of_raw else None))
    except (MtsArtifactError, ValueError, KeyError) as exc:
        return 4, {"status": "PREREQUISITE_MISSING", "detail": str(exc), "notice": NOTICE,
                   "display_only": True, "scoring_excluded": True}
    payload: dict[str, Any] = {"verb": "v8-live-monitor", "mode": "dry_run", "report": report,
                               "notice": NOTICE, "display_only": True, "scoring_excluded": True}
    if thresholds is None:
        return 2, payload  # 해시 불일치·부재 — 지표 null, 원장에 쓰지 않는다
    if not getattr(args, "append", False):
        return 0, payload
    row = ledger_row(report)
    payload["mode"] = "append"
    payload["ledger"] = {"path": LEDGER_RELATIVE.as_posix(), **append_monitor(root, row)}
    payload["derived_path"] = write_derived(root, report).relative_to(root).as_posix()
    return 0, payload
