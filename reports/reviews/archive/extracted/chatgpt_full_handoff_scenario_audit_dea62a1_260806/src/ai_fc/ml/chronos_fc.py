"""Chronos-Bolt zero-shot 시계열 분위수 예측 (추론 전용).

- 모델: amazon/chronos-bolt-small (Apache-2.0, ~48M) — 최초 실행 시 HF에서 다운로드(~190MB),
  이후 로컬 캐시. CPU 추론 수 초.
- 역할: GBM(정규분포 가정, fat-tail 미포착)의 비모수 보완재. 사전학습 분포가
  실제 시장 시계열의 두꺼운 꼬리를 반영한다.
- 한계(정직 고지): zero-shot 모델은 이벤트 캘린더(FOMC·실적·선거)를 모른다 —
  출력은 '무조건부 분포'이며 시나리오 분석의 참조선일 뿐 예측 보증이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MODEL_ID = "amazon/chronos-bolt-small"
T5_MODEL_ID = "amazon/chronos-t5-small"  # 샘플 경로 생성용 (~200MB) — 경로 터치 확률 정공법
C2_MODEL_ID = "amazon/chronos-2"         # 공변량 지원 (~480MB), Apache-2.0
_pipeline = None     # 모듈 캐시 (Bolt)
_t5_pipeline = None  # 모듈 캐시 (T5)
_c2_pipeline = None  # 모듈 캐시 (Chronos-2)


@dataclass
class QuantileForecast:
    symbol: str
    context_len: int
    horizon: int          # 주 단위 스텝 수
    quantiles: dict[str, list[float]]   # {"q10": [...], "q25": ..., "q50": ..., "q75": ..., "q90": ...}
    last_value: float

    def terminal(self, q: str) -> float:
        return self.quantiles[q][-1]

    def terminal_pct(self, q: str) -> float:
        return self.terminal(q) / self.last_value - 1.0

    def prob_above(self, threshold: float) -> float:
        """예측 종점에서 임계값 상회 확률 — 분위수 5점의 선형 보간 근사.

        Chronos-Bolt 학습 분위수 범위가 [0.1, 0.9]라 q10/q90 밖은 보간 불가 —
        0.93/0.07로 캡 (분포 꼬리 단정 금지, 근사 상·하한).
        """
        qs = [0.10, 0.25, 0.50, 0.75, 0.90]
        vals = [self.terminal(f"q{int(q * 100):02d}") for q in qs]
        if threshold <= vals[0]:
            return 0.93  # 분위수 밖 — 근사 상한
        if threshold >= vals[-1]:
            return 0.07
        for i in range(len(vals) - 1):
            if vals[i] <= threshold <= vals[i + 1]:
                if vals[i + 1] == vals[i]:
                    return 1 - qs[i]
                frac = (threshold - vals[i]) / (vals[i + 1] - vals[i])
                cdf = qs[i] + frac * (qs[i + 1] - qs[i])
                return 1.0 - cdf
        return 0.5


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        import torch
        from chronos import BaseChronosPipeline

        _pipeline = BaseChronosPipeline.from_pretrained(
            MODEL_ID, device_map="cpu", torch_dtype=torch.float32)
    return _pipeline


def _load_t5_pipeline():
    global _t5_pipeline
    if _t5_pipeline is None:
        import torch
        from chronos import BaseChronosPipeline

        _t5_pipeline = BaseChronosPipeline.from_pretrained(
            T5_MODEL_ID, device_map="cpu", torch_dtype=torch.float32)
    return _t5_pipeline


def sample_paths(closes: list[float], horizon: int, num_samples: int = 256,
                 seed: int = 42) -> "np.ndarray":
    """Chronos-T5 샘플 경로 (num_samples, horizon) 절대가격 — 배리어 확률용.

    CPU 자기회귀 생성이라 수십 초~수 분. 경로 질문이 있는 시리즈에만 호출할 것.
    터치 확률 계산은 quant.mc.barrier_prob 재사용 (모델 불문 순수 함수).
    """
    import torch

    pipe = _load_t5_pipeline()
    torch.manual_seed(seed)  # 실행 간 재현성
    context = torch.tensor(closes, dtype=torch.float32)
    out = pipe.predict(context, prediction_length=horizon, num_samples=num_samples)
    return out[0].numpy()  # (num_samples, horizon)


LEVELS = [0.1, 0.25, 0.5, 0.75, 0.9]  # Bolt 학습 범위 [0.1~0.9] 내 — 범위 밖은 조용히 잘림


def _to_qf(symbol: str, closes: list[float], horizon: int, arr: "np.ndarray"
           ) -> QuantileForecast:
    if arr.ndim == 3:  # (n_targets, horizon, n_q) — 1타깃이면 축약
        arr = arr[0]
    return QuantileForecast(
        symbol=symbol,
        context_len=len(closes),
        horizon=horizon,
        quantiles={f"q{int(l * 100):02d}": [float(v) for v in arr[:, k]]
                   for k, l in enumerate(LEVELS)},
        last_value=float(closes[-1]),
    )


def forecast_quantiles(symbol: str, closes: list[float], horizon: int = 25
                       ) -> QuantileForecast:
    """Bolt: 주간 종가 시계열 → horizon주 분위수 예측 (q10/25/50/75/90)."""
    import torch

    pipe = _load_pipeline()
    context = torch.tensor(closes, dtype=torch.float32)
    q, _ = pipe.predict_quantiles(
        context, prediction_length=horizon, quantile_levels=LEVELS)  # chronos 2.x: inputs 위치 인자
    return _to_qf(symbol, closes, horizon, q[0].numpy())


def _load_c2_pipeline():
    global _c2_pipeline
    if _c2_pipeline is None:
        import torch
        from chronos import BaseChronosPipeline

        _c2_pipeline = BaseChronosPipeline.from_pretrained(
            C2_MODEL_ID, device_map="cpu", torch_dtype=torch.float32)
    return _c2_pipeline


def _align_covariates(target_len: int, covs: dict[str, list[float]]) -> dict[str, "np.ndarray"]:
    """공변량을 타깃 길이에 뒤끝 정렬 — 길면 앞을 자르고, 짧으면 첫 값으로 앞을 채움."""
    out: dict[str, np.ndarray] = {}
    for k, v in covs.items():
        a = np.asarray(v, dtype=np.float32)
        if len(a) >= target_len:
            a = a[-target_len:]
        else:
            a = np.concatenate([np.full(target_len - len(a), a[0], dtype=np.float32), a])
        out[k] = a
    return out


def forecast_quantiles_c2(symbol: str, closes: list[float], horizon: int,
                          past_covariates: dict[str, list[float]] | None = None
                          ) -> QuantileForecast:
    """Chronos-2: 과거 공변량(past-only) 조건부 분위수 예측.

    미래 공변량은 쓰지 않는다 — 미래 VIX·금리를 아는 척하지 않는 정직 고지.
    """
    pipe = _load_c2_pipeline()
    target = np.asarray(closes, dtype=np.float32)
    if past_covariates:
        inputs = [{"target": target,
                   "past_covariates": _align_covariates(len(closes), past_covariates)}]
    else:
        inputs = [target]
    q, _ = pipe.predict_quantiles(
        inputs, prediction_length=horizon, quantile_levels=LEVELS)
    return _to_qf(symbol, closes, horizon, q[0].numpy())


def combine_median(fcs: list[QuantileForecast]) -> QuantileForecast:
    """분위수 레벨·스텝별 중앙값 결합 — 고정 규칙 (학습 아님, ML 게이트 내)."""
    if not fcs:
        raise ValueError("빈 목록")
    if len(fcs) == 1:
        return fcs[0]
    base = fcs[0]
    quantiles = {
        key: [float(np.median([fc.quantiles[key][i] for fc in fcs]))
              for i in range(base.horizon)]
        for key in base.quantiles
    }
    return QuantileForecast(
        symbol=base.symbol, context_len=base.context_len,
        horizon=base.horizon, quantiles=quantiles, last_value=base.last_value)


def disagreement(probs: dict[str, float]) -> float:
    """모델별 매핑 확률의 최대 쌍별 괴리 (= max − min). 1개 이하면 0."""
    vals = list(probs.values())
    return (max(vals) - min(vals)) if len(vals) > 1 else 0.0


def bridge_touch_prob(paths: "np.ndarray", threshold: float, direction: str,
                      step_range: tuple[int, int] | None = None,
                      sigma_w: float | None = None) -> float:
    """브라운 브리지 보정 터치 확률 (WS3 — T-11 상환, 결정론 수식·학습 없음).

    주간 관측 경로가 놓치는 주중 터치를 log-공간 브리지로 보정한다.
    미터치 인접 관측쌍 (x0, x1), 하향 배리어 b에 대해 (상향은 부호 대칭):
        p_bridge = exp(−2·max(0,x0−b)·max(0,x1−b) / σ_w²)
    경로 터치확률 = 1 − Π(1−p_i). 이미 터치한 경로는 1.
    σ_w는 경로 자체의 주간 log 증분 표준편차(ddof=0)로 추정 — 근사임을
    KNOWN_LIMITS에 명기. sigma_w 인자로 명시 지정 가능 (테스트·감사용).

    성질: 보정 ≥ raw (barrier_prob) — 항상. 브리지 항은 확률 질량을 더할 뿐이다.
    """
    if step_range is not None:
        s0 = max(0, step_range[0])
        s1 = min(paths.shape[1] - 1, step_range[1])
        if s0 > s1:
            return 0.0
        window = paths[:, s0:s1 + 1]
    else:
        window = paths
    x = np.log(window)
    b = float(np.log(threshold))
    if direction == "below":
        d = x - b          # 배리어까지의 (log) 거리 — 양수 = 미터치
    else:
        d = b - x
    touched = (d <= 0).any(axis=1)

    if window.shape[1] < 2:
        return float(touched.mean())

    if sigma_w is not None:
        sig2 = np.full(len(window), float(sigma_w) ** 2)
    else:
        incr = np.diff(x, axis=1)
        sig = incr.std(axis=1, ddof=0)          # 경로 내 추정 (근사 — 정직 고지)
        sig2 = np.maximum(sig, 1e-9) ** 2

    d0 = np.maximum(d[:, :-1], 0.0)
    d1 = np.maximum(d[:, 1:], 0.0)
    p_pair = np.exp(-2.0 * d0 * d1 / sig2[:, None])
    # 이미 터치한 쌍(d≤0 포함)은 p_pair=1이 되지만 touched 마스크가 우선한다
    p_path = 1.0 - np.prod(1.0 - np.clip(p_pair, 0.0, 1.0), axis=1)
    return float(np.where(touched, 1.0, p_path).mean())
