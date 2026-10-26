"""§13 공동 block 재표집과 §13.5.1 검정 계약.

- LossPanel 은 **원래 origin-calendar grid** 전체를 보존한다. eligible 날짜만 압축해
  인접 행을 시간 블록처럼 재표집하지 않는다 (§13.1, T41).
- replicate 당 **단일 인덱스 벡터**를 모든 모델·지평·셀 슬라이스와 eligibility mask 에
  공동 적용한다 (T42).
- 검정: centered paired stationary bootstrap — observed = mean(d)+δ,
  null_b = mean(d[idx_b]) − mean(d), p_raw = (1+#{null_b <= observed})/(B+1) 좌측꼬리.
  이는 bootstrap 근사에 대한 Monte Carlo 추정이며 유한표본 보장이 아니다 (§13.5.1).
- Holm: 검정불능 비교는 p_for_adjustment=1 로 family 에 남긴다 — family 축소 금지 (T44).
- 퇴화 replicate(유효 paired 관측 0)는 사전 고정 정책으로 집계하고 다시 뽑지 않는다 (T43).
- 블록 생성은 기하 길이 circular — `timeseries_v13.scoring.block_boot_ci` 와 같은 규약
  (저장소에 이미 5벌 중복이지만, 공동 grid+mask 재표집은 기존 어느 구현도 지원하지
  않아 신규 작성한다; 패리티는 합성 테스트로 고정).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np

from ..timeseries_v8.contracts import canonical_hash

MISSING_REASONS = ("OK", "NOT_ELIGIBLE", "UNRESOLVED", "CANDIDATE_FAILURE", "HOLD", "NOT_ISSUED")


class MtsResamplingError(RuntimeError):
    """재표집·검정 계약 위반 — fail-closed."""


@dataclass(frozen=True)
class LossPanel:
    """원점 손실 벡터 패널 (§13.1).

    losses[o, m, c] — NaN 은 결측이며 missing_reason 이 사유를 가진다.
    eligibility[o, c] — 계약 eligibility (사전 결정, 후보 성패와 무관).
    """

    origin_grid: tuple[str, ...]
    models: tuple[str, ...]
    cells: tuple[str, ...]
    losses: np.ndarray
    eligibility: np.ndarray
    missing_reason: np.ndarray  # int 인덱스 → MISSING_REASONS
    cohort_hash: str = field(default="")

    def __post_init__(self) -> None:
        n, m, c = len(self.origin_grid), len(self.models), len(self.cells)
        if self.losses.shape != (n, m, c):
            raise MtsResamplingError(f"losses shape {self.losses.shape} != {(n, m, c)}")
        if self.eligibility.shape != (n, c):
            raise MtsResamplingError("eligibility shape 불일치")
        if self.missing_reason.shape != (n, m, c):
            raise MtsResamplingError("missing_reason shape 불일치")
        if list(self.origin_grid) != sorted(set(self.origin_grid)):
            raise MtsResamplingError("origin_grid 는 중복 없는 오름차순 — 원 달력 보존 (T41)")
        # 결측이면 사유가 OK 가 아니어야 하고, 값이 있으면 OK 여야 한다
        missing = ~np.isfinite(self.losses)
        reason_ok = self.missing_reason == 0
        if bool((missing & reason_ok).any()):
            raise MtsResamplingError("NaN 손실에 OK 사유 — 결측 사유 누락")
        if bool((~missing & ~reason_ok).any()):
            raise MtsResamplingError("유효 손실에 결측 사유")
        object.__setattr__(self, "cohort_hash", self._hash())

    def _hash(self) -> str:
        return canonical_hash({
            "origin_grid": list(self.origin_grid),
            "models": list(self.models),
            "cells": list(self.cells),
            "losses_shape": list(self.losses.shape),
        })

    def model_index(self, model: str) -> int:
        return self.models.index(model)

    def cell_index(self, cell: str) -> int:
        return self.cells.index(cell)


def stationary_block_indices(
    n: int, *, mean_block: float, rng: np.random.Generator
) -> np.ndarray:
    """기하 길이 circular block 인덱스 1벌 — v13 scoring.block_boot_ci 와 같은 규약."""
    if n < 1:
        raise MtsResamplingError("n >= 1")
    if mean_block < 1:
        raise MtsResamplingError("mean_block >= 1")
    p = 1.0 / float(mean_block)
    out = np.empty(n, dtype=np.int64)
    filled = 0
    while filled < n:
        start = int(rng.integers(0, n))
        length = int(rng.geometric(p))
        take = min(length, n - filled)
        out[filled : filled + take] = (start + np.arange(take)) % n
        filled += take
    return out


@dataclass(frozen=True)
class ReplicateSet:
    """공동 재표집 결과 — 모든 슬라이스가 같은 인덱스를 공유했다는 증거 포함."""

    indices: np.ndarray  # (B, n_origin)
    seed: int
    mean_block: float
    panel_hash: str


def joint_block_resample(
    panel: LossPanel, *, mean_block: float, replications: int, seed: int
) -> ReplicateSet:
    """replicate 당 단일 인덱스 벡터 — 전 모델·셀·mask 공동 적용 (T41·T42)."""
    if replications < 1:
        raise MtsResamplingError("replications >= 1")
    rng = np.random.default_rng(seed)
    n = len(panel.origin_grid)
    indices = np.stack([
        stationary_block_indices(n, mean_block=mean_block, rng=rng)
        for _ in range(replications)
    ])
    return ReplicateSet(indices=indices, seed=seed, mean_block=mean_block,
                        panel_hash=panel.cohort_hash)


DegeneratePolicy = Literal["count_and_exclude", "fail"]


@dataclass(frozen=True)
class PairedAggregate:
    mean_difference: float | None
    n_paired: int
    status: Literal["OK", "NO_PAIRED_OBSERVATIONS"]


def eligible_paired_mean(
    panel: LossPanel, *, candidate: str, baseline: str, cell: str,
    index_vector: np.ndarray | None = None,
) -> PairedAggregate:
    """같은 원점·같은 셀에서 둘 다 유효한 paired 손실차 평균.

    후보 실패 원점을 삭제한 '성공 교집합' 이 아니라, eligibility 는 mask 가 정하고
    후보/기준 어느 쪽이든 결측이면 그 원점은 paired 불능으로 **센다** (§13.1).
    """
    ci = panel.model_index(candidate)
    bi = panel.model_index(baseline)
    cj = panel.cell_index(cell)
    losses = panel.losses
    mask = panel.eligibility[:, cj].astype(bool)
    if index_vector is not None:
        losses = losses[index_vector]
        mask = mask[index_vector]
    candidate_loss = losses[:, ci, cj]
    baseline_loss = losses[:, bi, cj]
    paired = mask & np.isfinite(candidate_loss) & np.isfinite(baseline_loss)
    n = int(paired.sum())
    if n == 0:
        return PairedAggregate(mean_difference=None, n_paired=0,
                               status="NO_PAIRED_OBSERVATIONS")
    d = candidate_loss[paired] - baseline_loss[paired]
    return PairedAggregate(mean_difference=float(d.mean()), n_paired=n, status="OK")


@dataclass(frozen=True)
class InferenceResult:
    comparison_id: str
    candidate: str
    baseline: str
    cell: str
    observed_mean_difference: float | None
    delta: float
    p_raw: float | None
    n_paired: int
    replications: int
    degenerate_replicates: int
    status: Literal["OK", "UNTESTABLE", "EVIDENCE_INSUFFICIENT"]
    reason: str | None = None


def centered_paired_bootstrap_test(
    panel: LossPanel,
    replicates: ReplicateSet,
    *,
    candidate: str,
    baseline: str,
    cell: str,
    delta: float = 0.0,
    degenerate_policy: DegeneratePolicy = "count_and_exclude",
    min_paired: int = 1,
) -> InferenceResult:
    """§13.5.1 — H0: E[d] >= -δ vs H1: E[d] < -δ (낮을수록 좋은 손실).

    δ 는 해당 손실의 **단위**다 — 상대 skill 임계를 그대로 대입하지 않는다.
    """
    if delta < 0:
        raise MtsResamplingError("δ >= 0 (손실 단위의 최소 실질 개선)")
    if replicates.panel_hash != panel.cohort_hash:
        raise MtsResamplingError("replicate 가 다른 panel 에서 생성됨 — 공동 인덱스 위반")
    comparison_id = f"{candidate}|{baseline}|{cell}"
    observed = eligible_paired_mean(panel, candidate=candidate, baseline=baseline, cell=cell)
    if observed.status != "OK" or observed.n_paired < min_paired:
        return InferenceResult(
            comparison_id=comparison_id, candidate=candidate, baseline=baseline, cell=cell,
            observed_mean_difference=observed.mean_difference, delta=delta, p_raw=None,
            n_paired=observed.n_paired, replications=len(replicates.indices),
            degenerate_replicates=0, status="UNTESTABLE",
            reason="유효 paired 관측 부족",
        )
    observed_stat = observed.mean_difference + delta
    null_stats: list[float] = []
    degenerate = 0
    for index_vector in replicates.indices:
        replicate = eligible_paired_mean(
            panel, candidate=candidate, baseline=baseline, cell=cell, index_vector=index_vector
        )
        if replicate.status != "OK":
            degenerate += 1
            if degenerate_policy == "fail":
                raise MtsResamplingError("퇴화 replicate — 정책상 실패")
            continue  # 사전 고정 정책: 집계 제외·카운트 (다시 뽑지 않는다, T43)
        null_stats.append(replicate.mean_difference - observed.mean_difference)
    effective_b = len(null_stats)
    if effective_b == 0:
        return InferenceResult(
            comparison_id=comparison_id, candidate=candidate, baseline=baseline, cell=cell,
            observed_mean_difference=observed.mean_difference, delta=delta, p_raw=None,
            n_paired=observed.n_paired, replications=len(replicates.indices),
            degenerate_replicates=degenerate, status="EVIDENCE_INSUFFICIENT",
            reason="모든 replicate 퇴화",
        )
    count = sum(1 for stat in null_stats if stat <= observed_stat)
    p_raw = (1 + count) / (effective_b + 1)
    return InferenceResult(
        comparison_id=comparison_id, candidate=candidate, baseline=baseline, cell=cell,
        observed_mean_difference=observed.mean_difference, delta=delta, p_raw=float(p_raw),
        n_paired=observed.n_paired, replications=len(replicates.indices),
        degenerate_replicates=degenerate, status="OK",
    )


@dataclass(frozen=True)
class FamilyResult:
    family_id: str
    alpha: float
    results: tuple[InferenceResult, ...]
    adjusted_p: tuple[float | None, ...]
    rejected: tuple[bool, ...]
    family_size: int


def holm_adjust(
    results: Sequence[InferenceResult], *, family_id: str, alpha: float = 0.05
) -> FamilyResult:
    """Holm step-down — 검정불능 비교는 p_for_adjustment=1 로 family 에 남는다 (T44).

    NaN 자동 제거로 family 크기를 줄이지 않는다. Holm 의 보호는 입력 p 의 유효성에
    의존하며 bootstrap 근사를 exact test 로 바꾸지 않는다 (§13.5.1-5).
    """
    if not 0.0 < alpha < 1.0:
        raise MtsResamplingError("alpha (0,1)")
    m = len(results)
    if m == 0:
        raise MtsResamplingError("빈 family")
    p_for_adjustment = [
        r.p_raw if (r.status == "OK" and r.p_raw is not None) else 1.0 for r in results
    ]
    order = sorted(range(m), key=lambda i: p_for_adjustment[i])
    adjusted = [None] * m
    running_max = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (m - rank) * p_for_adjustment[index])
        running_max = max(running_max, value)
        adjusted[index] = running_max
    rejected = []
    # step-down 중단 규칙: 정렬 순서에서 처음 비기각이 나오면 이후 전부 비기각
    stopped = False
    rejected_by_index = {}
    for rank, index in enumerate(order):
        if stopped or p_for_adjustment[index] > alpha / (m - rank):
            stopped = True
            rejected_by_index[index] = False
        else:
            rejected_by_index[index] = True
    rejected = [rejected_by_index[i] for i in range(m)]
    return FamilyResult(
        family_id=family_id,
        alpha=alpha,
        results=tuple(results),
        adjusted_p=tuple(adjusted),
        rejected=tuple(rejected),
        family_size=m,
    )


def skill_ratio(candidate_total: float, baseline_total: float) -> dict[str, object]:
    """Skill = 1 − ΣL_C/ΣL_B — 분모 불안정 시 NOT_IDENTIFIABLE (§3.2, T43)."""
    if not math.isfinite(baseline_total) or baseline_total <= 0.0:
        return {"skill": None, "status": "NOT_IDENTIFIABLE",
                "candidate_total": candidate_total, "baseline_total": baseline_total}
    return {"skill": 1.0 - candidate_total / baseline_total, "status": "OK",
            "candidate_total": candidate_total, "baseline_total": baseline_total}
