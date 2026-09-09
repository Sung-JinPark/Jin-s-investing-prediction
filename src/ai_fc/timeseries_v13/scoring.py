"""V13 판정 기계 — tools/ 스크립트에 흩어져 있던 채점 함수의 라이브러리 승격.

홀드아웃 채점·라이브 전진 채점·차기 피처블록 트랙이 **같은 구현**을 쓰도록 한 곳에 모은다.
저장소에는 stationary bootstrap 구현이 이미 5중으로 중복되어 있다(v3/v5/v6/v11/v13) — 여기서
새 구현을 만들지 않고 rung-1(`tools/v13_vol_run.py`)이 실제로 쓴 규칙을 그대로 옮긴다.
계약 좌표(ℓ=13 · B=2000 · seed 20260907 · CI90)는 `contracts.py` 상수를 참조한다.

에피소드 가드(`episode_runs`)는 2026-09-09 실측에서 나온 것이다: 사건 수 가드(≥20)는 9/9 셀이
통과하지만, 연속 구간으로 세면 vix30 계열 후반창의 사건 91~151개가 전부 2011년 단일 국면이다.
사건 수가 아니라 **독립 국면 수**가 유효 표본이므로 두 기준을 함께 잰다.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contracts import BLOCK_LENGTH, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED

CI_INTERVAL = (5, 95)
MDE_Z = 1.645          # 계약 gate.mde: MDE = 1.645 · bootstrap_se


# ── 부트스트랩 ────────────────────────────────────────────────────────────────
def block_boot_ci(d: np.ndarray, seed: int = BOOTSTRAP_SEED, b: int = BOOTSTRAP_REPLICATES,
                  block: int = BLOCK_LENGTH) -> dict[str, float | list[float]]:
    """정지 블록(기하 길이·순환) 부트스트랩 — tools/v13_vol_run.block_boot_ci 와 같은 규칙.

    반환: mean · ci90[lo, hi] · se · mde(=1.645·se). d 는 쌍대 손실차(양수 = 후보 우세).
    """
    d = np.asarray(d, float)
    if d.size == 0:
        return {"mean": float("nan"), "ci90": [float("nan"), float("nan")],
                "se": float("nan"), "mde": float("nan"), "n": 0}
    rng = np.random.default_rng(seed)
    n = len(d)
    reps = np.empty(b)
    for i in range(b):
        idx: list[np.ndarray] = []
        total = 0
        while total < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(1.0 / block))
            idx.append((start + np.arange(length)) % n)
            total += length
        reps[i] = float(np.mean(d[np.concatenate(idx)[:n]]))
    lo, hi = np.percentile(reps, CI_INTERVAL)
    se = float(np.std(reps, ddof=1))
    return {"mean": float(np.mean(d)), "ci90": [float(lo), float(hi)],
            "se": se, "mde": MDE_Z * se, "n": n}


def paired_brier_ci(p_baseline: np.ndarray, p_candidate: np.ndarray, y: np.ndarray,
                    *, seed: int = BOOTSTRAP_SEED, b: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    """쌍대 Brier 손실차 d = BS_baseline − BS_candidate (양수 = 후보 우세) + CI90.

    `lower_gt_zero` = 후보가 기준선보다 **유의하게 낫다**(엄격 우월, G1 형).
    `upper_ge_zero` = 후보가 기준선보다 **유의하게 나쁘지는 않다**(비열화, G2 형).
    """
    y = np.asarray(y, float)
    bs_base = (np.asarray(p_baseline, float) - y) ** 2
    bs_cand = (np.asarray(p_candidate, float) - y) ** 2
    out = block_boot_ci(bs_base - bs_cand, seed=seed, b=b)
    out.update({
        "bs_baseline": float(bs_base.mean()) if bs_base.size else float("nan"),
        "bs_candidate": float(bs_cand.mean()) if bs_cand.size else float("nan"),
        "lower_gt_zero": bool(out["ci90"][0] > 0),
        "upper_ge_zero": bool(out["ci90"][1] >= 0),
    })
    return out


def brier_skill_score(p: np.ndarray, y: np.ndarray, base_rate: float) -> float:
    """기후(고정 기저율) 대비 Brier skill score."""
    y = np.asarray(y, float)
    bs_model = float((((np.asarray(p, float) - y) ** 2)).mean())
    bs_clim = float((((base_rate - y) ** 2)).mean())
    return 1.0 - bs_model / max(bs_clim, 1e-9)


# ── 건전 귀무 (y-block 순열) ─────────────────────────────────────────────────
def y_block_permutations(y: np.ndarray, *, draws: int, seed: int,
                         block: int = BLOCK_LENGTH) -> Iterable[np.ndarray]:
    """사건 라벨의 블록 순열 — p-순열은 누수라 계약이 금지(T-A 교훈)."""
    y = np.asarray(y, float)
    rng = np.random.default_rng(seed)
    n = len(y)
    starts = np.arange(0, n, block)
    for _ in range(draws):
        order = rng.permutation(len(starts))
        idx = np.concatenate([np.arange(starts[k], min(starts[k] + block, n)) for k in order])[:n]
        yield y[idx]


def y_block_null_pass_rate(y: np.ndarray, decide, *, draws: int, seed: int,
                           block: int = BLOCK_LENGTH) -> float:
    """`decide(y_permuted) -> bool` 이 라벨 순열에서 통과하는 비율. 계약 임계 0.10."""
    passes = sum(1 for perm in y_block_permutations(y, draws=draws, seed=seed, block=block)
                 if decide(perm))
    return passes / draws if draws else float("nan")


# ── 신뢰도 (Murphy 분해) ─────────────────────────────────────────────────────
def murphy_reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict[str, Any]:
    """uncertainty − resolution + reliability = Brier. tools/v13_vol_rung2.reliability 승계."""
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    if y.size == 0:
        return {"reliability": float("nan"), "resolution": float("nan"),
                "uncertainty": float("nan"), "brier_check": float("nan"), "curve": []}
    ybar = float(y.mean())
    unc = ybar * (1 - ybar)
    edges = np.linspace(0, 1, bins + 1)
    rel = res = 0.0
    curve = []
    n = len(y)
    for k in range(bins):
        upper = p <= 1.0 if k == bins - 1 else p < edges[k + 1]
        mask = (p >= edges[k]) & upper
        if not mask.any():
            continue
        pk = float(p[mask].mean()); ok = float(y[mask].mean()); nk = int(mask.sum())
        rel += nk / n * (pk - ok) ** 2
        res += nk / n * (ok - ybar) ** 2
        curve.append({"bin": k, "n": nk, "pred": round(pk, 4), "obs": round(ok, 4)})
    return {"reliability": float(rel), "resolution": float(res), "uncertainty": float(unc),
            "brier_check": float(unc - res + rel), "curve": curve}


# ── 다중비교 ─────────────────────────────────────────────────────────────────
def family_p_binomial(k_obs: int, n: int, p: float = 0.05) -> float:
    """family P(k >= k_obs) — 셀 독립 가정의 참고값. 셀 종속 caveat 를 항상 병기한다."""
    return float(sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(k_obs, n + 1)))


# ── 퇴화 / 에피소드 가드 ─────────────────────────────────────────────────────
def episode_runs(y: np.ndarray) -> dict[str, int]:
    """연속 구간(run) 수 — 유효 표본의 정직한 척도.

    라벨은 h영업일 전방창으로 만들어 이웃 원점이 강하게 겹친다. 사건 수 100개가 단일 국면
    하나일 수 있으므로 클래스별 **독립 국면 수**를 함께 잰다. NaN 은 구간을 끊지 않고 건너뛴다.
    """
    y = np.asarray(y, float)
    finite = np.isfinite(y)
    runs = {"event_runs": 0, "non_event_runs": 0}
    previous: float | None = None
    for value, ok in zip(y, finite):
        if not ok:
            continue
        if previous is None or value != previous:
            runs["event_runs" if value == 1.0 else "non_event_runs"] += 1
        previous = value
    return runs


def degeneracy_report(y: np.ndarray, *, min_events: int, min_episodes: int) -> dict[str, Any]:
    """한 창(반창 또는 홀드아웃 창)의 사건/비사건 수와 국면 수, 그리고 가드 판정."""
    y = np.asarray(y, float)
    finite = y[np.isfinite(y)]
    events = int((finite == 1.0).sum())
    non_events = int((finite == 0.0).sum())
    runs = episode_runs(y)
    counts_ok = min(events, non_events) >= min_events
    episodes_ok = min(runs["event_runs"], runs["non_event_runs"]) >= min_episodes
    return {
        "n": int(finite.size), "events": events, "non_events": non_events,
        "base_rate": float(finite.mean()) if finite.size else float("nan"),
        "event_runs": runs["event_runs"], "non_event_runs": runs["non_event_runs"],
        "min_count": min(events, non_events),
        "min_episodes": min(runs["event_runs"], runs["non_event_runs"]),
        "counts_ok": bool(counts_ok), "episodes_ok": bool(episodes_ok),
        "verdict": "ok" if (counts_ok and episodes_ok)
                   else ("episode_thin" if counts_ok else "untestable_by_construction"),
    }


def episode_spans(dates: np.ndarray, y: np.ndarray, value: float = 1.0) -> list[dict[str, Any]]:
    """해당 클래스의 연속 구간 목록 [{start, end, n}] — 판정서에 국면을 명시하기 위한 것."""
    spans: list[dict[str, Any]] = []
    start_idx: int | None = None
    for i, v in enumerate(y):
        hit = np.isfinite(v) and v == value
        if hit and start_idx is None:
            start_idx = i
        elif not hit and start_idx is not None:
            spans.append({"start": str(dates[start_idx]), "end": str(dates[i - 1]),
                          "n": i - start_idx})
            start_idx = None
    if start_idx is not None:
        spans.append({"start": str(dates[start_idx]), "end": str(dates[len(y) - 1]),
                      "n": len(y) - start_idx})
    return spans
