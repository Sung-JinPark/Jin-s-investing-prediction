"""P6 — V13-VOL 라이브 읽기 전용 진단 + T7 도달가능성 (2026-11-11 정합성 감사 D11 · V13E-1~7).

## 무엇을 재는가

1. **Cox 보정 기울기** — 홀드아웃 원장(`holdout_scorings.jsonl`)에 **이미 기록된** 10구간 신뢰도 곡선에
   이항 가중 로지스틱 logit(ō_b) = a + b·logit(p̄_b) 를 적합한다(가중 n_b). 홀드아웃 바이트를 새로 열지
   않는다. b<1 = 과신, a<0·b≈1 = 수준 이동. SE 는 원점 iid 가정이라 겹침 창에서 **과소**다.
2. **T7 도달가능성** — 셀당 60 원점 판정 전에 이미 확정된 손실차 d_i = (π − y_i)² − (p_i − y_i)² 의 합과,
   남은 원점이 낼 수 있는 최선·최악 d 로 60원점 평균 d 의 상·하한을 낸다. 미확정 미래 원점의 최선은
   max(π², (1−π)²) — 사건이면서 p→1 인 경로 (1−π)² 를 빼먹고 π² 만 쓰면 상한이 과소된다(V13E-2 원 주장
   +0.006 의 오류). 열린 원점은 이미 고정된 p 를 쓴다. 경로 CI 는 live_verdict 산술(ℓ13·B2000·seed
   20260907)을 그대로 import 해 쓰고 귀무 추출만 50회로 줄인다(경로가 여러 개라서).
3. **RV 기계확정 분해** — 기존 `rv_brier_decomposition` 의 층 분해·층 점수와 `rv_mechanics` 의 하한 플래그를
   재사용해, 라이브 성숙 코호트를 원점에서 기계적으로 확정된 양성과 나머지로 나눈다.
4. **상수 기준선** — 설계창(2007~2014)의 평온 VIX 밴드 [16,21) 경험빈도 c 를 상수 예보로 두고 라이브 손실을
   비교한다. 기후(GFC 로 부푼 설계창 무조건 빈도) 대비 통과가 보정을 뜻하지 않는다는 근거다.
5. **점프 지지** — 설계창 1일 VIX 로그 점프 최대와 그것을 넘는 라이브 사건(2026-11-05).

## 기대손실 부호 조건 (문서화)

한 원점의 기대 손실차는 E[d] = (π − p)(π + p − 2·π_true) 이다. p < π 이면
E[d] > 0 ⇔ π_true < (π + p)/2. 따라서 설계 기후 π 가 크면(GFC 포함 0.31/0.42) 평온 꼬리를 2~3배 과소예측해도
기대 손실차가 양수다 — "기후 대비 통과 ≠ 보정됨".

## 하지 않는 것

- 원장·계약·동결 계수·포인터에 아무것도 쓰지 않는다. 쓰기는 `--append` 때 derived JSON 1개와
  노출 영수증(`exposures.jsonl`, 같은 body 재실행은 no-op) 뿐이다.
- 판정·강등·T7 을 **적용하지 않는다**. 규칙·임계를 바꾸지 않는다. Cox 교정 예시 p 는 발행값이 아니다.
- 2015 이후 홀드아웃·봉인 구간으로 새 통계를 만들지 않는다(점프 순위도 설계창·라이브 안에서만).
- 서로 다른 probability_space 를 산술 결합하지 않는다 — 이 모듈은 V13 사건확률 공간만 읽는다.

산출물은 진단이며 캘리브레이션 표본·매매 신호가 아니다 (CLAUDE.md 5-5, display_only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ...timeseries_v2.market_archive import read_market_observations
from ...timeseries_v13 import contracts as C13
from ...timeseries_v13 import features as F13
from ...timeseries_v13 import scoring as S13
from ...timeseries_v13.live_scoreboard import claim_thresholds
from ...timeseries_v13.live_verdict import _evaluate_cell
from ...timeseries_v13.pipeline import HISTORY_START
from ...timeseries_v13.resolve import (RESOLUTION_LEDGER_RELATIVE, _read_rows, climatology_map,
                                       distinct_resolutions)
from ..sessions import future_sessions, session_offset
from .rv_brier_decomposition import (_nasdaq_returns, pb_probability_at, stratified_decomposition,
                                     stratum_scores)
from .rv_mechanics import EXPERIMENT_RELATIVE as RV_MECH_RELATIVE
from .rv_mechanics import mechanical_positive

DERIVED_RELATIVE = Path("data/mts_research/derived/v13_live_diagnostics.json")
RUN_ID = "v13-live-diagnostics-v1"
NOTICE = "참고 의견, 매매 신호 아님"
CELLS = ("vix25_h5", "vix25_h21", "rv_h5", "rv_h21")
VIX_CELLS = ("vix25_h5", "vix25_h21")
RV_CELLS = ("rv_h5", "rv_h21")
RELIABILITY_EDGES = (0.0, 0.1, 0.3, 0.65, 1.0)
T7_TARGET = 60
T7_PATH_NULL_DRAWS = 50          # 설계서 P6 — 경로 여러 개라 귀무 추출만 줄인다(live_verdict 는 120)
CALM_BAND = (16.0, 21.0)         # 감사(V13E-3)가 쓴 평온 밴드 — 결과 뒤 선택이므로 caveat 공시
WILSON_Z90 = 1.6448536269514722
P_RECOMPUTE_TOLERANCE = 5e-7
COX_MAX_ITER = 100
COX_TOL = 1e-12


class MtsV13DiagnosticsError(RuntimeError):
    """V13 진단 전제 위반 — fail-closed (조용한 클리핑·대체 없음)."""


# ---------------------------------------------------------------------------
# 순수 수학 — 합성 테스트 대상
# ---------------------------------------------------------------------------


def _logit(p: np.ndarray | float) -> np.ndarray:
    """엄격 logit — (0,1) 밖이면 클리핑하지 않고 실패한다."""
    arr = np.asarray(p, dtype=float)
    if not np.isfinite(arr).all() or (arr <= 0.0).any() or (arr >= 1.0).any():
        raise MtsV13DiagnosticsError("logit 입력은 (0,1) 안의 유한값이어야 한다")
    return np.log(arr / (1.0 - arr))


def _sigmoid(z: np.ndarray | float) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


def binned_cox(curve: Sequence[Mapping[str, Any]], drop_bin0: bool = False) -> dict[str, Any]:
    """구간 신뢰도 곡선의 Cox 절편·기울기 — 이항 가중 로지스틱(Newton, 정확 MLE).

    각 구간을 사건 n_b·ō_b, 비사건 n_b·(1−ō_b) 의 가중 관측으로 펼친다. x = logit(p̄_b).
    se_naive 는 원점 iid 가정의 역헤시안 — 겹침 라벨에서 과소(공시).
    """
    bins = [b for b in curve if not (drop_bin0 and int(b["bin"]) == 0)]
    if len(bins) < 2:
        raise MtsV13DiagnosticsError("Cox 적합에는 구간이 2개 이상 필요하다")
    n = np.array([float(b["n"]) for b in bins])
    obs = np.array([float(b["obs"]) for b in bins])
    pred = np.array([float(b["pred"]) for b in bins])
    if (n <= 0).any() or (obs < 0).any() or (obs > 1).any():
        raise MtsV13DiagnosticsError("구간 n>0, obs∈[0,1] 이어야 한다")
    x_bin = _logit(pred)
    x = np.concatenate([x_bin, x_bin])
    y = np.concatenate([np.ones_like(obs), np.zeros_like(obs)])
    w = np.concatenate([n * obs, n * (1.0 - obs)])
    design = np.column_stack([np.ones_like(x), x])
    beta = np.zeros(2)
    hessian = None
    for _ in range(COX_MAX_ITER):
        mu = _sigmoid(design @ beta)
        gradient = design.T @ (w * (mu - y))
        hessian = (design * (w * mu * (1.0 - mu))[:, None]).T @ design
        step = np.linalg.solve(hessian, gradient)
        beta = beta - step
        if float(np.abs(step).max()) < COX_TOL:
            break
    else:
        raise MtsV13DiagnosticsError("Cox 적합이 수렴하지 않았다")
    mu = _sigmoid(design @ beta)
    hessian = (design * (w * mu * (1.0 - mu))[:, None]).T @ design
    se = np.sqrt(np.diag(np.linalg.inv(hessian)))
    return {
        "a": round(float(beta[0]), 4), "b": round(float(beta[1]), 4),
        "se_naive": [round(float(se[0]), 4), round(float(se[1]), 4)],
        "n": int(n.sum()), "n_bins": len(bins), "drop_bin0": drop_bin0,
        "se_note": "원점 iid 가정 SE — 겹침 창이라 과소(공시). 구간 평균 근사.",
    }


def cox_example_probability(a: float, b: float, p: float) -> float:
    """Cox 교정 예시 p' = σ(a + b·logit p) — **발행값 아님**, 진단 예시."""
    return float(_sigmoid(a + b * float(_logit(p))))


def reliability_by_bin(rows: Sequence[Mapping[str, Any]],
                       edges: Sequence[float] = RELIABILITY_EDGES) -> list[dict[str, Any]]:
    """원점 순 행을 p 구간으로 나눠 Σp·사건·사건 run 수를 센다 (마지막 구간은 1.0 포함)."""
    if list(edges) != sorted(edges) or edges[0] != 0.0 or edges[-1] != 1.0:
        raise MtsV13DiagnosticsError("구간 경계는 0 에서 1 까지 오름차순")
    ordered = sorted(rows, key=lambda r: str(r["origin"]))
    p = np.array([float(r["probability"]) for r in ordered])
    y = np.array([float(r["label"]) for r in ordered])
    out: list[dict[str, Any]] = []
    for k, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        upper = p <= hi if k == len(edges) - 2 else p < hi
        mask = (p >= lo) & upper
        n = int(mask.sum())
        runs = S13.episode_runs(y[mask]) if n else {"event_runs": 0, "non_event_runs": 0}
        out.append({
            "p_range": [lo, hi], "n": n,
            "sum_p": round(float(p[mask].sum()), 4),
            "events": int(y[mask].sum()),
            "event_runs": int(runs["event_runs"]),
            "mean_p": round(float(p[mask].mean()), 4) if n else None,
            "obs_rate": round(float(y[mask].mean()), 4) if n else None,
        })
    return out


def loss_difference(pi: float, p: float, y: float) -> float:
    """d = (π − y)² − (p − y)² — 양수 = 모형이 기후보다 낫다."""
    return (pi - y) ** 2 - (p - y) ** 2


def best_worst_open(pi: float, p: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """p 가 고정된 미성숙 원점의 ((최선 d, y), (최악 d, y))."""
    options = [(loss_difference(pi, p, y), y) for y in (0.0, 1.0)]
    return max(options), min(options)


def best_worst_future(pi: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """p 도 라벨도 미정인 미래 원점의 ((최선 d, p, y), (최악 d, p, y)).

    최선 = max(π², (1−π)²): 비사건·p→0 이면 π², 사건·p→1 이면 (1−π)².
    최악 = min(π², (1−π)²) − 1: 반대 방향으로 p 가 완전히 틀린 경우.
    """
    nonevent_best, event_best = (pi ** 2, 0.0, 0.0), ((1 - pi) ** 2, 1.0, 1.0)
    best = max(nonevent_best, event_best)
    nonevent_worst, event_worst = (pi ** 2 - 1.0, 1.0, 0.0), ((1 - pi) ** 2 - 1.0, 0.0, 1.0)
    worst = min(nonevent_worst, event_worst)
    return best, worst


def expected_loss_sign_threshold(pi: float, p: float) -> dict[str, Any]:
    """E[d] = (π − p)(π + p − 2π_true). p<π 이면 E[d]>0 ⇔ π_true < (π+p)/2."""
    return {
        "formula": "E[d] = (pi - p)(pi + p - 2*pi_true)",
        "pi": round(pi, 6), "p": round(p, 6),
        "pi_true_threshold": round((pi + p) / 2.0, 6),
        "direction": "pi_true < threshold 이면 E[d]>0" if p < pi else "pi_true > threshold 이면 E[d]>0",
    }


def const_baseline_loss(rows: Sequence[Mapping[str, Any]], c: float) -> dict[str, Any]:
    """상수 예보 c 대 모형 — Brier·로그손실. c 는 설계창(2007~2014)에서만 산출한 값이어야 한다."""
    if not 0.0 < c < 1.0:
        raise MtsV13DiagnosticsError("상수 c 는 (0,1) 안이어야 한다")
    p = np.array([float(r["probability"]) for r in rows])
    y = np.array([float(r["label"]) for r in rows])
    if p.size == 0:
        raise MtsV13DiagnosticsError("상수 기준선 비교 행이 없다")
    _logit(p)  # (0,1) 검사 — 로그손실이 무한대가 되는 입력은 클리핑하지 않고 실패
    brier_model = float(np.mean((p - y) ** 2))
    brier_const = float(np.mean((c - y) ** 2))
    log_model = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    log_const = float(-np.mean(y * np.log(c) + (1 - y) * np.log(1 - c)))
    return {
        "c": round(c, 6), "n": int(p.size), "events": int(y.sum()),
        "brier_model": round(brier_model, 6), "brier_const": round(brier_const, 6),
        "bss_vs_const": round(1.0 - brier_model / brier_const, 4),
        "logloss_model": round(log_model, 4), "logloss_const": round(log_const, 4),
    }


def wilson_interval(k: int, n: int, z: float = WILSON_Z90) -> list[float] | None:
    if n <= 0:
        return None
    phat = k / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denominator
    return [round(max(centre - half, 0.0), 4), round(min(centre + half, 1.0), 4)]


# ---------------------------------------------------------------------------
# 저장소 입력 — 한 번 읽어 공유한다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticsContext:
    root: Path
    as_of: str
    contract: dict[str, Any]
    frozen: dict[str, Any]
    pinned_sha: str
    climatology: dict[str, float]
    live_rows: list[dict[str, Any]]                 # as_of 이하 distinct 원점, 원점 순
    resolutions: dict[str, list[dict[str, Any]]]    # 셀별 distinct, resolved_session ≤ as_of, 원점 순
    observations: list[Any]
    panel: dict[str, np.ndarray]                    # VIX∩NASDAQCOM, [HISTORY_START, as_of]


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_hashes(root: Path) -> dict[str, str | None]:
    """읽는 원장·계수·계약의 sha256 — 테스트가 실행 전후 불변을 assert 한다."""
    relatives = [
        C13.CONTRACT_RELATIVE, C13.COEFFICIENTS_RELATIVE, C13.LIVE_LEDGER_RELATIVE,
        RESOLUTION_LEDGER_RELATIVE, C13.HOLDOUT_LEDGER_RELATIVE,
        RV_MECH_RELATIVE / "prereg.json",
    ]
    return {str(rel).replace("\\", "/"): _sha256(root / rel) for rel in relatives}


def _distinct_live_rows(rows: list[dict[str, Any]], pinned_sha: str) -> list[dict[str, Any]]:
    """원점(as_of)당 한 행 — 핀 sha 행 우선, 다음 knowledge_cutoff 최신 (resolve.distinct_resolutions 규칙)."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("as_of"))
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        row_pinned = row.get("coefficients_sha256") == pinned_sha
        cur_pinned = current.get("coefficients_sha256") == pinned_sha
        if row_pinned and not cur_pinned:
            best[key] = row
        elif row_pinned == cur_pinned and str(row.get("knowledge_cutoff") or "") > str(current.get("knowledge_cutoff") or ""):
            best[key] = row
    return [best[k] for k in sorted(best)]


def load_context(root: Path, as_of: str | None = None) -> DiagnosticsContext:
    contract = C13.load_contract_v13(root)
    pin = contract.get("frozen_coefficients") or {}
    frozen = C13.load_frozen_coefficients(
        root,
        expected_sha256=pin.get("sha256"),
        expected_content_hash=pin.get("content_hash"),
        expected_finalist_id=pin.get("finalist_id"),
    )
    pinned_sha = str(pin["sha256"])
    observations = list(read_market_observations(root))
    full = F13.build_panel(observations, start=HISTORY_START)
    if not len(full["dates"]):
        raise MtsV13DiagnosticsError("VIX∩NASDAQCOM 패널이 비었다")
    last = str(full["dates"][-1])
    as_of = as_of or last
    if as_of not in {str(d) for d in full["dates"]}:
        raise MtsV13DiagnosticsError(f"as_of {as_of} 는 VIX∩NASDAQCOM 관측 세션이 아니다 (마지막 {last})")
    panel = F13.build_panel(observations, start=HISTORY_START, end=as_of)

    live = _distinct_live_rows(_read_rows(root / C13.LIVE_LEDGER_RELATIVE), pinned_sha)
    live = [r for r in live if str(r["as_of"]) <= as_of]
    if not live:
        raise MtsV13DiagnosticsError("as_of 이하 라이브 원점이 없다")
    resolved = distinct_resolutions(_read_rows(root / RESOLUTION_LEDGER_RELATIVE), pinned_sha=pinned_sha)
    by_cell: dict[str, list[dict[str, Any]]] = {name: [] for name in CELLS}
    for row in resolved:
        if row.get("cell") in by_cell and str(row.get("resolved_session")) <= as_of:
            by_cell[str(row["cell"])].append(row)
    for name in by_cell:
        by_cell[name].sort(key=lambda r: str(r["origin"]))
    return DiagnosticsContext(
        root=root, as_of=as_of, contract=contract, frozen=frozen, pinned_sha=pinned_sha,
        climatology=climatology_map(contract, frozen), live_rows=live, resolutions=by_cell,
        observations=observations, panel=panel,
    )


def _cell_spec(cell: str) -> dict[str, Any]:
    for spec in C13.cell_specs():
        if spec["name"] == cell:
            return spec
    raise MtsV13DiagnosticsError(f"알 수 없는 셀: {cell}")


def _single_episode(rows: Sequence[Mapping[str, Any]]) -> bool:
    labels = [float(r["label"]) for r in sorted(rows, key=lambda r: str(r["origin"]))]
    return S13.episode_runs(np.array(labels))["event_runs"] <= 1


# ---------------------------------------------------------------------------
# 진단 단위
# ---------------------------------------------------------------------------


def _partial_label(spec: dict[str, Any], panel: Mapping[str, np.ndarray], i: int) -> tuple[float | None, bool]:
    """원점 i 의 라벨이 as_of 까지 관측으로 확정됐는지 — (라벨 또는 None, 성숙 여부).

    창 안에서 이미 임계를 넘었으면 성숙 전이어도 사건 확정, 성숙했는데 안 넘었으면 비사건 확정.
    """
    last = len(panel["dates"]) - 1
    h = int(spec["h"])
    end = min(i + h, last)
    matured = i + h <= last
    if spec["target"] == "vix_touch":
        window = panel["vix"][i + 1:end + 1]
        hit = bool((window >= spec["K"]).any())
    else:
        window = panel["rv21"][i + 1:end + 1]
        finite = window[np.isfinite(window)]
        hit = bool((finite > spec["theta"]).any())
    if hit:
        return 1.0, matured
    if matured:
        return 0.0, True
    return None, False


def _path_rows(entries: list[tuple[str, float, float]], pi: float) -> list[dict[str, Any]]:
    return [{"origin": o, "probability": p, "label": y, "climatology_base_rate": pi} for o, p, y in entries]


def _path_verdict(entries: list[tuple[str, float, float]], pi: float, contract: dict[str, Any],
                  n_target: int) -> dict[str, Any]:
    """live_verdict 의 셀 산술을 그대로 호출한다 (ℓ13·B2000·seed 20260907·귀무 50)."""
    rules = ((contract.get("degeneracy_guard") or {}).get("rules") or {})
    result = _evaluate_cell(
        _path_rows(entries, pi), minimum=n_target,
        min_events=int(rules.get("min_events_per_half_per_class") or 20),
        min_episodes=int(rules.get("min_episodes_per_half_per_class") or 5),
        draws=T7_PATH_NULL_DRAWS,
    )
    ci = result.get("paired_loss_vs_climatology") or {}
    return {
        "mean_d": round(float(ci.get("mean", float("nan"))), 6) if ci else None,
        "ci90": [round(float(v), 4) for v in ci.get("ci90", [])] if ci else None,
        "null_pass_rate": result.get("negative_control_pass_rate"),
        "status": result.get("status"),
        "events": result.get("events"),
    }


def t7_reachability(cell: str, root: Path, *, n_target: int = T7_TARGET,
                    context: DiagnosticsContext | None = None) -> dict[str, Any]:
    """60원점 판정 전 확정분·상하한·경로 CI. 산술이며 적용이 아니다."""
    ctx = context or load_context(root)
    spec = _cell_spec(cell)
    pi = float(ctx.climatology[cell])
    index = {str(d): i for i, d in enumerate(ctx.panel["dates"])}
    ledger_labels = {str(r["origin"]): float(r["label"]) for r in ctx.resolutions.get(cell, [])}
    origins = ctx.live_rows[:n_target]

    determined: list[tuple[str, float, float]] = []
    open_: list[tuple[str, float]] = []
    for row in origins:
        origin = str(row["as_of"])
        if origin not in index:
            raise MtsV13DiagnosticsError(f"라이브 원점 {origin} 이 패널에 없다")
        p = float(row["cells"][cell]["p"])
        label, matured = _partial_label(spec, ctx.panel, index[origin])
        if matured and origin in ledger_labels and ledger_labels[origin] != label:
            raise MtsV13DiagnosticsError(f"{cell} {origin}: 재계산 라벨이 해상 원장과 다르다")
        if label is None:
            open_.append((origin, p))
        else:
            determined.append((origin, p, label))

    n_future = n_target - len(origins)
    future_dates = ([d.isoformat() for d in future_sessions(date.fromisoformat(ctx.as_of), n_future)]
                    if n_future > 0 else [])
    target_origin = future_dates[-1] if future_dates else str(origins[n_target - 1]["as_of"])
    verdict_session = session_offset(date.fromisoformat(target_origin), int(spec["h"])).isoformat()

    d_det = [loss_difference(pi, p, y) for _, p, y in determined]
    open_best = [best_worst_open(pi, p)[0] for _, p in open_]
    open_worst = [best_worst_open(pi, p)[1] for _, p in open_]
    future_best, future_worst = best_worst_future(pi)
    sum_det = float(sum(d_det))
    upper = (sum_det + sum(d for d, _ in open_best) + n_future * future_best[0]) / n_target
    lower = (sum_det + sum(d for d, _ in open_worst) + n_future * future_worst[0]) / n_target
    # 대조용 — 미확정 원점 전부를 '비사건·p→0'(π²)으로만 둔 잘못된 상한(V13E-2 원 주장 +0.006)
    contrast = (sum_det + (len(open_) + n_future) * pi ** 2) / n_target

    best_entries = (list(determined)
                    + [(o, p, y) for (o, p), (_, y) in zip(open_, open_best)]
                    + [(d, future_best[1], future_best[2]) for d in future_dates])
    worst_entries = (list(determined)
                     + [(o, p, y) for (o, p), (_, y) in zip(open_, open_worst)]
                     + [(d, future_worst[1], future_worst[2]) for d in future_dates])
    paths = {
        "best_case": _path_verdict(sorted(best_entries), pi, ctx.contract, n_target),
        "worst_case": _path_verdict(sorted(worst_entries), pi, ctx.contract, n_target),
    }
    last_p = float(origins[-1]["cells"][cell]["p"])
    for label_name, y in (("persistence_event", 1.0), ("persistence_nonevent", 0.0)):
        entries = (list(determined) + [(o, p, y) for o, p in open_]
                   + [(d, last_p, y) for d in future_dates])
        paths[label_name] = _path_verdict(sorted(entries), pi, ctx.contract, n_target)
        paths[label_name]["assumption"] = f"열린·미래 원점 y={int(y)}, 미래 p=마지막 기록 p {last_p}"

    events_det = int(sum(y for _, _, y in determined))
    return {
        "cell": cell, "climatology_pi": round(pi, 6), "n_target": n_target,
        "recorded_origins": len(origins), "determined_n": len(determined),
        "determined_events": events_det,
        "determined_matured_n": sum(1 for o, _, _ in determined if o in ledger_labels),
        "sum_d_determined": round(sum_det, 4),
        "open_origins": [{"origin": o, "p": p, "best_d": round(b[0], 4), "best_y": b[1]}
                         for (o, p), b in zip(open_, open_best)],
        "future_origins": n_future,
        "future_best_d": round(future_best[0], 6), "future_worst_d": round(future_worst[0], 6),
        "target_origin_session": target_origin,
        "target_verdict_session": verdict_session,
        "d_upper": round(upper, 6), "d_lower": round(lower, 6),
        "contrast_nonevent_only_upper": round(contrast, 6),
        "contrast_note": "사건·p→1 경로((1−π)²)를 빼고 π² 만 쓴 상한 — V13E-2 원 주장의 오류, 판단에 쓰지 않는다",
        "paths": paths,
        "demotion_at_best_path": paths["best_case"]["status"] == "demotion_candidate",
        "demotion_at_worst_path": paths["worst_case"]["status"] == "demotion_candidate",
        "single_episode": _single_episode(
            [{"origin": o, "label": y} for o, _, y in determined]) if determined else True,
        "note": "경로 극단 2개 + 지속 가정 2개의 산술 — CI 하한의 경로 단조성은 가정이다. 판정 적용 아님.",
    }


def rv_mechanics_split(cell: str, root: Path, *, context: DiagnosticsContext | None = None) -> dict[str, Any]:
    """라이브 성숙 코호트의 기계확정/비기계 분해 — rv_brier_decomposition 함수 재사용."""
    if cell not in RV_CELLS:
        raise MtsV13DiagnosticsError(f"RV 셀이 아니다: {cell}")
    ctx = context or load_context(root)
    rows = ctx.resolutions.get(cell, [])
    if not rows:
        return {"cell": cell, "n": 0, "status": "NO_MATURED_ORIGINS"}
    prereg = json.loads((ctx.root / RV_MECH_RELATIVE / "prereg.json").read_text(encoding="utf-8"))
    theta = float(prereg["theta"])
    dates, returns = _nasdaq_returns(ctx.root)
    date_index = {d: i for i, d in enumerate(dates)}
    h = int(_cell_spec(cell)["h"])
    y = np.array([float(r["label"]) for r in rows])
    p = np.array([float(r["probability"]) for r in rows])
    pc = np.array([float(r["climatology_base_rate"]) for r in rows])
    flags = [mechanical_positive(returns, date_index[str(r["origin"])], h, theta) for r in rows]
    m = np.array([bool(f["mechanically_determined"]) for f in flags])
    delta = (pc - y) ** 2 - (p - y) ** 2
    nonmech_events = ~m & (y == 1.0)
    nonmech_nonevents = ~m & (y == 0.0)
    return {
        "cell": cell, "n": int(y.size), "events": int(y.sum()), "theta": theta,
        "mechanical_positives": int((m & (y == 1.0)).sum()),
        "decomposition": stratified_decomposition(delta, m),
        "mechanical": stratum_scores(p, pc, y, m),
        "nonmechanical": stratum_scores(p, pc, y, ~m),
        "all": stratum_scores(p, pc, y, np.ones_like(m)),
        "nonmechanical_event_split": {
            "events_n": int(nonmech_events.sum()),
            "events_sse_model": round(float(((p - y) ** 2)[nonmech_events].sum()), 4),
            "events_sse_climatology": round(float(((pc - y) ** 2)[nonmech_events].sum()), 4),
            "nonevents_n": int(nonmech_nonevents.sum()),
            "nonevents_sse_model": round(float(((p - y) ** 2)[nonmech_nonevents].sum()), 4),
            "nonevents_sse_climatology": round(float(((pc - y) ** 2)[nonmech_nonevents].sum()), 4),
        },
        "nonmechanical_event_floors": [
            {"origin": str(r["origin"]), "max_floor": round(float(f["max_floor"]), 4)}
            for r, f, flag in zip(rows, flags, nonmech_events) if flag
        ],
        "single_episode": _single_episode(rows),
        "note": "소표본 기술 분해 — 판정 아님. 기계확정 플래그는 원점 정보(감사 NASDAQCOM 그리드)만 쓴다.",
    }


def design_calm_band_constant(cell: str, root: Path, *,
                              context: DiagnosticsContext | None = None) -> dict[str, Any]:
    """설계창(2007~2014) VIX∈[16,21) 원점의 사건 빈도 — 설계창 밖 바이트로 라벨을 만들지 않는다."""
    if cell not in VIX_CELLS:
        raise MtsV13DiagnosticsError(f"평온 밴드 상수는 VIX 셀만: {cell}")
    ctx = context or load_context(root)
    spec = _cell_spec(cell)
    design = F13.build_panel(ctx.observations, start=C13.DESIGN_WINDOW[0], end=C13.DESIGN_WINDOW[1])
    labels = F13.labels_vix(design["vix"], spec["K"], spec["h"])
    mask = np.isfinite(labels) & (design["vix"] >= CALM_BAND[0]) & (design["vix"] < CALM_BAND[1])
    n = int(mask.sum())
    k = int(labels[mask].sum())
    if n == 0 or k == 0 or k == n:
        raise MtsV13DiagnosticsError(f"{cell}: 설계창 평온 밴드 빈도가 퇴화했다 (n={n}, k={k})")
    return {
        "cell": cell, "band": list(CALM_BAND), "window": list(C13.DESIGN_WINDOW),
        "n": n, "events": k, "c": round(k / n, 4), "wilson90": wilson_interval(k, n),
        "caveat": "밴드 [16,21) 은 라이브 결과 뒤 감사가 고른 좌표 — 사전등록 상수가 아니며 skill 주장 근거 아님",
    }


def jump_support_fact(root: Path, *, context: DiagnosticsContext | None = None) -> dict[str, Any]:
    """설계창 1일 VIX 로그 점프 최대와 그것을 넘는 라이브 사건 (2015~ 홀드아웃·봉인 구간 미사용)."""
    ctx = context or load_context(root)
    design = F13.build_panel(ctx.observations, start=C13.DESIGN_WINDOW[0], end=C13.DESIGN_WINDOW[1])
    design_jumps = np.diff(np.log(design["vix"]))
    k_max = int(np.argmax(design_jumps))
    design_max = float(design_jumps[k_max])
    first_live = str(ctx.live_rows[0]["as_of"])
    dates = [str(d) for d in ctx.panel["dates"]]
    start = dates.index(first_live)
    vix = ctx.panel["vix"][start:]
    live_dates = dates[start:]
    live_jumps = np.diff(np.log(vix))
    exceed = [
        {"session": live_dates[j + 1], "from": float(vix[j]), "to": float(vix[j + 1]),
         "log_jump": round(float(live_jumps[j]), 4),
         "design_days_at_or_above": int((design_jumps >= live_jumps[j]).sum())}
        for j in np.flatnonzero(live_jumps > design_max)
    ]
    pre_jump: list[dict[str, Any]] = []
    live_by_origin = {str(r["as_of"]): r for r in ctx.live_rows}
    for event in exceed:
        prior = live_dates[live_dates.index(event["session"]) - 1]
        row = live_by_origin.get(prior)
        if row is None:
            continue
        cell = row["cells"]["vix25_h5"]
        v = float(row["inputs"]["vix_close"])
        lo = math.floor(v)
        labels = F13.labels_vix(design["vix"], 25, 5)
        mask = np.isfinite(labels) & (design["vix"] >= lo) & (design["vix"] < lo + 1)
        n, k = int(mask.sum()), int(labels[mask].sum())
        pre_jump.append({
            "origin": prior, "vix_close": v, "p_vix25_h5": float(cell["p"]),
            "band80": cell.get("band80"),
            "design_frequency_same_vix_bin": {"bin": [lo, lo + 1], "n": n, "events": k,
                                              "wilson90_iid": wilson_interval(k, n)},
            "note": "band80 은 계수 불확실성만 반영(KNOWN_LIMITS 35) — Wilson 은 원점 iid 가정",
        })
    return {
        "design_window": list(C13.DESIGN_WINDOW),
        "design_days": int(design_jumps.size),
        "design_max_log_jump": round(design_max, 4),
        "design_max_session": str(design["dates"][k_max + 1]),
        "live_window": [first_live, ctx.as_of],
        "live_exceedances": exceed,
        "pre_jump_origins": pre_jump,
        "scope_note": "2015~2026-09 구간 순위는 홀드아웃·봉인 바이트 신규 열람이라 계산하지 않는다",
        "single_episode": len(exceed) <= 1,
    }


def recompute_live_probabilities(context: DiagnosticsContext) -> dict[str, Any]:
    """기록 p 대 동결 계수 재계산 |Δ| — 생산 수식 동형(pb_probability_at)."""
    index = {str(d): i for i, d in enumerate(context.panel["dates"])}
    worst = 0.0
    checked = 0
    for row in context.live_rows:
        if row.get("coefficients_sha256") != context.pinned_sha:
            continue
        for cell in CELLS:
            p = pb_probability_at(context.frozen, context.panel, index[str(row["as_of"])], cell)
            worst = max(worst, abs(p - float(row["cells"][cell]["p"])))
            checked += 1
    return {"checked": checked, "max_abs_delta": worst,
            "tolerance": P_RECOMPUTE_TOLERANCE, "ok": worst <= P_RECOMPUTE_TOLERANCE}


def _holdout_curves(context: DiagnosticsContext) -> tuple[dict[str, Any], str]:
    rows = [r for r in _read_rows(context.root / C13.HOLDOUT_LEDGER_RELATIVE)
            if r.get("coefficients_sha256") == context.pinned_sha]
    if not rows:
        raise MtsV13DiagnosticsError("핀 계수의 홀드아웃 채점 행이 없다")
    row = rows[-1]
    return {cell: row["cells"][cell]["reliability"]["curve"] for cell in CELLS}, str(row["content_hash"])


def _live_cell_summary(context: DiagnosticsContext, cell: str) -> dict[str, Any]:
    """live_verdict 의 셀 산술(_evaluate_cell)을 as_of 이하 행에 그대로 적용 — 표본 부족이면 기술통계만."""
    rows = context.resolutions.get(cell, [])
    gate = context.contract.get("live_forward_gate") or {}
    rules = ((context.contract.get("degeneracy_guard") or {}).get("rules") or {})
    result = _evaluate_cell(
        rows, minimum=int(gate.get("minimum_matured_origins_per_cell") or T7_TARGET),
        min_events=int(rules.get("min_events_per_half_per_class") or 20),
        min_episodes=int(rules.get("min_episodes_per_half_per_class") or 5),
        draws=T7_PATH_NULL_DRAWS,
    )
    keep = ("matured", "events", "brier_model", "brier_climatology", "bss", "status",
            "expected_events_model", "first_origin", "last_origin")
    out = {k: result.get(k) for k in keep}
    if rows:
        labels = np.array([float(r["label"]) for r in rows])
        out["event_runs"] = int(S13.episode_runs(labels)["event_runs"])
    out["single_episode"] = _single_episode(rows) if rows else True
    return out


def build_report(root: Path, *, as_of: str | None = None) -> dict[str, Any]:
    ctx = load_context(root, as_of)
    curves, holdout_hash = _holdout_curves(ctx)
    claim = claim_thresholds(ctx.contract)
    scope = [str(c) for c in ((ctx.contract.get("publication") or {}).get("holdout_pass_cells") or [])]

    cells: dict[str, Any] = {}
    for cell in CELLS:
        rows = ctx.resolutions.get(cell, [])
        pi = float(ctx.climatology[cell])
        cox = binned_cox(curves[cell])
        cox_drop = binned_cox(curves[cell], drop_bin0=True)
        last_p = float(ctx.live_rows[-1]["cells"][cell]["p"])
        median_p = float(np.median([float(r["probability"]) for r in rows])) if rows else last_p
        entry: dict[str, Any] = {
            "n": len(rows),
            "live": _live_cell_summary(ctx, cell),
            "reliability_live": reliability_by_bin(rows) if rows else [],
            "holdout_cox": {
                "all_bins": cox, "drop_bin0": cox_drop, "low_bin": curves[cell][0],
                "source": "holdout_scorings.jsonl 기록 곡선(2015~2018) — 홀드아웃 바이트 신규 열람 없음",
                "example_probability_not_published": {
                    "p_as_of": last_p,
                    "p_cox": round(cox_example_probability(cox["a"], cox["b"], last_p), 6),
                    "label": "발행값 아님 — 진단 예시. 교정은 새 사전등록 계약에서만",
                },
            },
            "live_cox": {"status": "not_fit_single_episode",
                         "note": "사건 run 1 — 라이브 적합은 추론 의미 없음"},
            "expected_loss_sign": expected_loss_sign_threshold(pi, median_p),
            "in_t7_scope": cell in scope,
            "t7": t7_reachability(cell, root, context=ctx),
        }
        if cell in VIX_CELLS and rows:
            constant = design_calm_band_constant(cell, root, context=ctx)
            ybar = float(np.mean([float(r["label"]) for r in rows]))
            entry["const_baselines"] = {
                "design_calm_band": {**constant, "loss": const_baseline_loss(rows, constant["c"])},
                "design_climatology": const_baseline_loss(rows, pi),
                "hindsight_live_rate": {
                    **(const_baseline_loss(rows, ybar) if 0.0 < ybar < 1.0 else {"status": "degenerate"}),
                    "label": "사후(hindsight) 상수 — 대조 전용, skill 주장 금지",
                },
            }
        if cell in RV_CELLS:
            entry["rv_mechanics_split"] = rv_mechanics_split(cell, root, context=ctx)
        cells[cell] = entry

    t7_cells = {c: cells[c]["t7"] for c in scope if c in cells}
    determined = sorted(c for c, t in t7_cells.items() if t["demotion_at_best_path"])
    reachable = sorted(c for c, t in t7_cells.items() if t["demotion_at_worst_path"])
    any_single = any(cells[c]["live"]["single_episode"] for c in CELLS)
    return {
        "schema": "mts_v13_live_diagnostics_v1",
        "display_only": True, "scoring_excluded": True, "notice": NOTICE,
        "probability_space": C13.PROBABILITY_SPACE,
        "as_of": ctx.as_of,
        "n": len(ctx.live_rows), "n_origins": len(ctx.live_rows),
        "single_episode": any_single,
        "claim_restriction": claim,
        "writes_to_ledgers": 0,
        "inputs_sha256": input_hashes(root),
        "holdout_row_content_hash": holdout_hash,
        "p_recompute": recompute_live_probabilities(ctx),
        "jump_support": jump_support_fact(root, context=ctx),
        "cells": cells,
        "t7_summary": {
            "scope_cells": scope,
            "demotion_in_all_paths": determined,
            "demotion_reachable": reachable,
            "t7_trigger_determined": len(determined) >= 2,
            "t7_trigger_reachable": len(reachable) >= 2,
            "note": "T7 = 범위 3셀 60 도달 뒤 2셀 이상 강등. 이 요약은 산술이며 적용(강등·종결)은 사용자 결정",
        },
        "governance": [
            "원장·계약·동결 계수 무수정, 판정 적용 없음",
            "Cox 교정 예시는 발행값 아님 — 학습형 보정은 해소 100+ 게이트 뒤 새 계약에서만",
            "기후 대비 통과 ≠ 보정됨 (expected_loss_sign)",
            "모든 사건 양성이 단일 에피소드(2026-11-05)면 single_episode=true — 추론 근거 아님",
        ],
    }


# ---------------------------------------------------------------------------
# CLI (공유 배선: cli.RESEARCH_TOOLS["v13-diagnostics"])
# ---------------------------------------------------------------------------


def _render(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _write_derived(root: Path, payload: Mapping[str, Any]) -> bool:
    """재생성본 쓰기 — 바이트가 같으면 쓰지 않는다(멱등). tmp+os.replace 원자 쓰기."""
    path = root / DERIVED_RELATIVE
    rendered = _render(payload)
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)
    return True


def _exposure(root: Path, *, append: bool) -> dict[str, Any]:
    """노출 영수증 절차(read_scope_guard, purpose=audit) — dry-run 은 검사만, --append 때 기록."""
    from .. import artifacts
    from ..contracts import DRAFT_CONTRACT_RELATIVE, load_research_contract, read_scope_guard

    contract, _ = load_research_contract(root / DRAFT_CONTRACT_RELATIVE, root)
    before = len(artifacts.read_chain(root, artifacts.EXPOSURE_LEDGER))
    check = read_scope_guard(
        root, contract,
        requested_series={"NASDAQCOM", "VIX"},
        requested_window=(HISTORY_START, None),
        purpose="audit",
        run_id=RUN_ID,
        record_exposure=artifacts.record_exposure if append else None,
    )
    after = len(artifacts.read_chain(root, artifacts.EXPOSURE_LEDGER))
    return {"allowed": check.allowed, "windows_hit": list(check.windows_hit),
            "recorded": append, "appended": after - before}


def run_cli(root: Path, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """dry-run(기본): 보고서 JSON 만 출력. --append: derived JSON 재생성 + 노출 영수증(멱등)."""
    append = bool(getattr(args, "append", False))
    try:
        exposure = _exposure(root, append=append)
        report = build_report(root, as_of=getattr(args, "as_of", None))
    except (MtsV13DiagnosticsError, C13.TimeSeriesV13VolError) as exc:
        return 4, {"status": "PREREQUISITE_FAILED", "detail": str(exc), "notice": NOTICE,
                   "display_only": True}
    written = _write_derived(root, report) if append else False
    summary = {
        "status": "OK", "mode": "append" if append else "dry_run",
        "output": str(DERIVED_RELATIVE).replace("\\", "/"),
        "derived_written": written, "exposure": exposure,
        "ledger_appends": exposure["appended"],
    }
    return 0, {**summary, "report": report}
