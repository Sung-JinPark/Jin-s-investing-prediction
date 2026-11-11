"""V15-VOL 설계창(2007-2014) 전용 적합 — 동결 도구와 테스트 오라클만 호출한다.

라이브 모듈(shadow·resolve·verdict·arms)은 이 모듈을 import 하지 않는다(ML 게이트 고정 — 라이브 해소 표본으로
재추정하는 경로가 코드에 없다). 2014-12-31 을 넘는 행이 들어오면 raise (홀드아웃·봉인 바이트 차단, 설계서 §5-13).

- R1: 반창 교차전이 OOF(V13 rung-3 `_dir_preds` 와 같은 적합기) + embargo h(분할 직전 h 원점 purge) 위의
      방향 층화 Platt(공통 기울기·방향 절편 2개, 무정규 Newton). a0 = 두 절편 단순 평균, b0 = 공통 기울기.
- R2: 평온(VIX_t<20) 1일 로그변화의 ln(25/20) 이상 꼬리 · n_calm.
- R3: 상태(운영 문턱)별 설계창 라벨 빈도.
결정론 수치모델 적합(CLAUDE.md 원칙 5 명문화 예외) — base rate 참조이며 하이퍼파라미터 caveat 를 아티팩트에 싣는다.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..timeseries_v13 import contracts as V13C
from ..timeseries_v13 import features as F
from ..timeseries_v13 import scoring as S
from . import contracts as C

DESIGN = ("2007-01-01", "2014-12-31")
SPLIT = "2011-01-01"
TAIL_FLOOR = math.log(25.0 / 20.0)
MDE_BOOT_B = 2000
MDE_WINDOW = 60
MDE_BLOCK = 13           # V13 scoring.block_boot_ci 의 ℓ — 명세 §3.7 스크래치와 같은 좌표(참조 전용)
MDE_STRIDE = 120
ELIGIBILITY_START_STRIDE = 20

HYPERPARAMETER_CAVEATS = [
    "설계창 2007-2014 와 분할 2011-01-01 은 V13 계약 좌표 승계 — GFC 국면을 포함한 창 선택이 이후 지식을 간접 내포할 수 있다",
    "R3 국면 문턱 VIX 20 은 V14 M5 운영값, θ 0.1694 는 V13 설계창 중앙값(in-sample) — 통계로 새로 고르지 않았으나 θ 의 기원은 표본 내",
    "R2 꼬리 하한 ln(25/20)·Jeffreys ½ 평활·h5 2셀 한정은 결과 전 구조 사유 — 장지평 점프 효과는 측정하지 않는다",
    "R1 embargo h·방향 절편 단순 평균·공통 기울기는 설계창 열람(Simpson 인공물) 뒤 정했다 — 라이브 결과는 보지 않았다",
    "R1 b0>1 은 동결 PB l2(1e-3) 축소 해제 성분을 포함한다(ridge_slope_ratio 공시) — 홀드아웃 Cox 기울기와 반대 방향 셀이 있다",
    "R3 ½·½ 가중은 고정 상수 — 학습 결합 아님. 산출은 base rate 참조이지 캘리브레이션 표본이 아니다",
]


class DesignWindowError(C.TimeSeriesV15VolError):
    """설계창 밖 바이트가 적합 경로에 들어왔다."""


def _assert_design_dates(dates: Any) -> None:
    values = [str(d) for d in dates]
    if values and (values[-1] > DESIGN[1] or max(values) > DESIGN[1]):
        raise DesignWindowError(f"design panel reaches past {DESIGN[1]} ({max(values)}) — refit on post-2014 data is prohibited")
    if values and min(values) < DESIGN[0]:
        raise DesignWindowError(f"design panel starts before {DESIGN[0]}")


def design_panel(root: Path, *, knowledge_cutoff: str | None = None) -> dict[str, np.ndarray]:
    """V13 build_panel 을 설계창으로 절단 — 반환 날짜가 2014-12-31 을 넘으면 raise (이중 확인)."""
    from ..timeseries_v2.market_archive import read_market_observations

    observations = read_market_observations(root, knowledge_cutoff=knowledge_cutoff) if knowledge_cutoff \
        else read_market_observations(root)
    panel = F.build_panel(observations, start=DESIGN[0], end=DESIGN[1])
    _assert_design_dates(panel["dates"])
    if not len(panel["dates"]):
        raise DesignWindowError("design panel is empty")
    return panel


def _inputs_sha256(panel: dict[str, np.ndarray]) -> str:
    payload = {"dates": [str(d) for d in panel["dates"]], "vix": [float(v) for v in panel["vix"]],
               "ndx": [float(v) for v in panel["ndx"]]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _logit_arr(p: np.ndarray) -> np.ndarray:
    q = np.clip(np.asarray(p, float), *C.PROB_CLIP)
    return np.log(q / (1 - q))


def _cell_xy(cell_spec: dict[str, Any], panel: dict[str, np.ndarray], frozen_v13: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(x 피처 — 동결 PB 입력과 같은 값, y 라벨, calm 마스크)."""
    vix, rv = panel["vix"], panel["rv21"]
    h = int(cell_spec["h"])
    if cell_spec["target"] == "vix_touch":
        y = F.labels_vix(vix, cell_spec["K"], h)
        x = np.asarray(vix, float)
        calm = x < C.CALM_VIX_BELOW
    else:
        y = F.labels_rv(rv, C.THETA_RV, h)
        x = F.fill_rv_nan(rv, frozen_v13["rv_nan_fill_median"])
        calm = x <= C.THETA_RV
    return x, y, calm


def _early_mask(panel: dict[str, np.ndarray]) -> np.ndarray:
    return np.array([str(d) for d in panel["dates"]]) < SPLIT


def pb_oof_cross_transfer(x: np.ndarray, y: np.ndarray, early: np.ndarray, *, embargo: int) -> tuple[np.ndarray, np.ndarray]:
    """반창 교차전이 OOF + purge(분할 직전 embargo 개 원점 — 라벨이 반대 창을 본다).

    방향 0(e2l): fit = early∧finite∧¬purge, eval = late∧finite.  방향 1(l2e): fit = late∧finite, eval = early∧finite∧¬purge.
    반환 (oof, direction_flag ∈ {0, 1, −1}). embargo=0 이면 rung-3 `_dir_preds` 와 같은 값.
    """
    x = np.asarray(x, float).reshape(-1, 1)
    y = np.asarray(y, float)
    early = np.asarray(early, bool)
    late = ~early
    finite = np.isfinite(y)
    split_idx = int(np.argmax(late)) if late.any() else len(y)
    purge = np.zeros(len(y), bool)
    if embargo > 0:
        purge[max(0, split_idx - int(embargo)):split_idx] = True
    e = early & finite & ~purge
    l = late & finite
    oof = np.full(len(y), np.nan)
    flag = np.full(len(y), -1, dtype=int)
    for k, (fit_m, eval_m) in enumerate(((e, l), (l, e))):
        beta, mu, sd = F.logit_fit(x[fit_m], y[fit_m])
        oof[eval_m] = F.logit_predict(beta, mu, sd, x[eval_m])
        flag[eval_m] = k
    return oof, flag


def newton_logit(X: np.ndarray, y: np.ndarray, init: Any) -> tuple[np.ndarray, bool, int]:
    """무정규 Newton 로지스틱(최대 100회, |step|∞<1e-12 정지). 비수렴 또는 |coef|∞>50 이면 converged=False."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    coef = np.array(init, float)
    n = len(y)
    converged = False
    iters = 0
    with np.errstate(over="ignore", invalid="ignore"):
        for iters in range(1, 101):
            z = np.clip(X @ coef, -700, 700)
            p = np.clip(1 / (1 + np.exp(-z)), 1e-12, 1 - 1e-12)
            g = X.T @ (p - y) / n
            H = (X * (p * (1 - p))[:, None]).T @ X / n + 1e-12 * np.eye(X.shape[1])
            try:
                step = np.linalg.solve(H, g)
            except np.linalg.LinAlgError:
                break
            coef = coef - step
            if not np.all(np.isfinite(coef)):
                break
            if float(np.abs(step).max()) < 1e-12:
                converged = True
                break
    if not np.all(np.isfinite(coef)) or float(np.abs(coef).max()) > 50:
        converged = False
    return coef, converged, iters


def _naive_se(X: np.ndarray, coef: np.ndarray) -> list[float]:
    X = np.asarray(X, float)
    z = np.clip(X @ coef, -700, 700)
    p = np.clip(1 / (1 + np.exp(-z)), 1e-12, 1 - 1e-12)
    info = (X * (p * (1 - p))[:, None]).T @ X
    try:
        cov = np.linalg.inv(info)
    except np.linalg.LinAlgError:
        return [float("nan")] * X.shape[1]
    return [float(math.sqrt(max(v, 0.0))) for v in np.diag(cov)]


def platt_fit(p: np.ndarray, y: np.ndarray) -> tuple[float, float, list[float], bool]:
    """방향별 단독 Platt(공시용) — (a, b, se_naive, converged)."""
    z = _logit_arr(p)
    X = np.column_stack([np.ones(len(z)), z])
    coef, converged, _ = newton_logit(X, y, (0.0, 1.0))
    return float(coef[0]), float(coef[1]), _naive_se(X, coef), bool(converged)


def ridge_slope_ratio(cell_spec: dict[str, Any], panel: dict[str, np.ndarray], frozen_v13: dict[str, Any]) -> float:
    """무정규(l2=0)/정규(l2=1e-3) PB 기울기비 — 설계창 표본 내 Platt 기울기와 같다(축소 해제 공시)."""
    x, y, _ = _cell_xy(cell_spec, panel, frozen_v13)
    m = np.isfinite(y)
    X = x.reshape(-1, 1)
    b_l2, _, _ = F.logit_fit(X[m], y[m])
    b_0, _, _ = F.logit_fit(X[m], y[m], l2=0.0)
    return float(b_0[1] / b_l2[1])


def fit_r1(cell_spec: dict[str, Any], panel: dict[str, np.ndarray], frozen_v13: dict[str, Any]) -> dict[str, Any]:
    h = int(cell_spec["h"])
    x, y, _ = _cell_xy(cell_spec, panel, frozen_v13)
    oof, flag = pb_oof_cross_transfer(x, y, _early_mask(panel), embargo=h)
    mm = np.isfinite(oof)
    z = _logit_arr(oof[mm])
    yy = y[mm]
    f = flag[mm]
    X = np.column_stack([(f == 0).astype(float), (f == 1).astype(float), z])
    coef, converged, _ = newton_logit(X, yy, (0.0, 0.0, 1.0))
    if not converged:
        raise C.TimeSeriesV15VolError(f"stratified Platt did not converge for {cell_spec['name']} — refusing to freeze")
    by_direction: dict[str, Any] = {}
    for k, name in ((0, "e2l"), (1, "l2e")):
        sel = flag == k
        a, b, _, ok = platt_fit(oof[sel], y[sel])
        by_direction[name] = {
            "a": a if ok else "non_convergent", "b": b if ok else "non_convergent",
            "n": int(sel.sum()), "events": int(np.nansum(y[sel])), "converged": bool(ok),
        }
    return {
        "a0": float((coef[0] + coef[1]) / 2.0), "b0": float(coef[2]),
        "a_e2l": float(coef[0]), "a_l2e": float(coef[1]),
        "n_oof": int(mm.sum()), "embargo": h, "purged": h,
        "se_naive": _naive_se(X, coef), "converged": bool(converged),
        "ridge_slope_ratio": ridge_slope_ratio(cell_spec, panel, frozen_v13),
        "by_direction": by_direction,
    }


def calm_jump_tail(panel: dict[str, np.ndarray]) -> dict[str, Any]:
    vix = np.asarray(panel["vix"], float)
    dates = [str(d) for d in panel["dates"]]
    lj = np.diff(np.log(vix))
    calm = vix[:-1] < C.CALM_VIX_BELOW
    jumps = lj[calm]
    tail = sorted(float(j) for j in jumps[jumps >= TAIL_FLOOR])
    after = [d for d, c in zip(dates[1:], calm) if c]
    arg = int(np.argmax(jumps))
    return {"n_calm": int(calm.sum()), "jump_tail": tail, "max_calm_jump": float(jumps[arg]),
            "max_calm_jump_date": after[arg]}


def state_base_rates(cell_spec: dict[str, Any], panel: dict[str, np.ndarray], frozen_v13: dict[str, Any]) -> dict[str, Any]:
    _, y, calm = _cell_xy(cell_spec, panel, frozen_v13)
    m = np.isfinite(y)
    return {"calm": float(y[m & calm].mean()), "stress": float(y[m & ~calm].mean()),
            "n_calm": int((m & calm).sum()), "n_stress": int((m & ~calm).sum())}


def load_parent_frozen(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """V13 계약 핀으로 동결 계수 3자 대조 — (frozen, pin)."""
    contract = V13C.load_contract_v13(root)
    pin = contract.get("frozen_coefficients") or {}
    frozen = V13C.load_frozen_coefficients(root, expected_sha256=pin.get("sha256"),
                                           expected_content_hash=pin.get("content_hash"),
                                           expected_finalist_id=pin.get("finalist_id"))
    return frozen, pin


def build_constants(root: Path, *, knowledge_cutoff: str | None = None) -> dict[str, Any]:
    """동결 상수 본문(provenance·content_hash 제외 — 결정론). 동결 도구가 provenance 를 붙이고 해시한다."""
    frozen, pin = load_parent_frozen(root)
    panel = design_panel(root, knowledge_cutoff=knowledge_cutoff)
    specs = V13C.cell_specs()
    r1_cells = {spec["name"]: fit_r1(spec, panel, frozen) for spec in specs}
    r3_cells = {spec["name"]: state_base_rates(spec, panel, frozen) for spec in specs}
    jump = calm_jump_tail(panel)
    dates = [str(d) for d in panel["dates"]]
    return {
        "schema_version": 1,
        "model_id": C.MODEL_ID,
        "model_version": C.MODEL_VERSION,
        "design_window": list(DESIGN),
        "split": SPLIT,
        "parent_v13": {"coefficients_sha256": pin.get("sha256"), "content_hash": pin.get("content_hash"),
                       "finalist_id": pin.get("finalist_id")},
        "panel": {"n": len(dates), "first": dates[0], "last": dates[-1], "inputs_sha256": _inputs_sha256(panel)},
        "R1": {"estimator": "direction_stratified_platt", "embargo": "h", "intercept_rule": "simple_mean",
               "formula": "p1 = clip(sigmoid(a0 + b0*logit(clip(p_PB))))", "cells": r1_cells},
        "R2": {"calm_rule": "vix_close_t < 20.0", "n_calm": jump["n_calm"], "jump_tail": jump["jump_tail"],
               "tail_floor": TAIL_FLOOR, "max_calm_jump": jump["max_calm_jump"],
               "max_calm_jump_date": jump["max_calm_jump_date"], "smoothing": "jeffreys_half", "horizon": 5,
               "cells": list(C.R2_CELLS)},
        "R3": {"state_rule": {"vix": "vix_close_t < 20.0 -> calm", "rv": "rv21_ann_t <= 0.1694 -> calm"},
               "weights": [0.5, 0.5], "cells": r3_cells},
        "hyperparameter_caveats": list(HYPERPARAMETER_CAVEATS),
    }


# ── MDE·도달 시점 참조 (채택 근거 아님) ──────────────────────────────────────────
def _arm_series(cell_spec: dict[str, Any], panel: dict[str, np.ndarray], frozen: dict[str, Any],
                constants: dict[str, Any]) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    name = cell_spec["name"]
    x, y, calm = _cell_xy(cell_spec, panel, frozen)
    cell = frozen["cells"][name]
    p = F.logit_predict(np.asarray(cell["beta"], float), np.asarray(cell["mu"], float),
                        np.asarray(cell["sd"], float), x.reshape(-1, 1))
    r1 = constants["R1"]["cells"][name]
    arms = {"R1": np.clip(1 / (1 + np.exp(-(r1["a0"] + r1["b0"] * _logit_arr(p)))), *C.PROB_CLIP)}
    if name in C.R2_CELLS:
        tail = np.asarray(constants["R2"]["jump_tail"], float)
        n_calm = int(constants["R2"]["n_calm"])
        need = np.log(float(cell_spec["K"]) / x)
        k = len(tail) - np.searchsorted(tail, need, side="left")
        lam1 = (k + 0.5) / (n_calm + 1)
        lam5 = np.where(calm, 1 - (1 - lam1) ** int(constants["R2"]["horizon"]), 0.0)
        arms["R2"] = 1 - (1 - p) * (1 - lam5)
    rates = constants["R3"]["cells"][name]
    arms["R3"] = 0.5 * p + 0.5 * np.where(calm, rates["calm"], rates["stress"])
    return p, arms, y


def origins_to_eligibility(y: np.ndarray, h: int) -> dict[str, Any]:
    """임의 시작점(20원점 간격)에서 r2 적격(n≥max(60,5ℓ_h) ∧ 사건·비사건 ≥20 ∧ 에피소드 5/5)에 닿는 원점 수."""
    ys = np.asarray(y, float)
    ys = ys[np.isfinite(ys)]
    need_n = max(C.MIN_ORIGINS, C.MIN_BLOCKS * C.block_length(h))
    needs: list[float] = []
    for start in range(0, len(ys) - C.MIN_ORIGINS, ELIGIBILITY_START_STRIDE):
        ev_runs = ne_runs = events = 0
        prev = None
        hit = None
        for j in range(start, len(ys)):
            value = ys[j]
            if prev is None or value != prev:
                if value == 1.0:
                    ev_runs += 1
                else:
                    ne_runs += 1
            prev = value
            events += int(value == 1.0)
            n = j - start + 1
            if (ev_runs >= C.MIN_EPISODES_EACH and ne_runs >= C.MIN_EPISODES_EACH and n >= need_n
                    and events >= C.MIN_EVENTS_EACH and n - events >= C.MIN_EVENTS_EACH):
                hit = n
                break
        needs.append(float(hit) if hit is not None else float("nan"))
    arr = np.asarray(needs, float)
    finite = np.isfinite(arr)
    return {
        "starts": int(len(arr)), "start_stride": ELIGIBILITY_START_STRIDE, "min_n_rule": need_n,
        "median": float(np.nanmedian(arr)) if finite.any() else None,
        "q90": float(np.nanquantile(arr, 0.9)) if finite.any() else None,
        "never_frac": float(np.mean(~finite)) if len(arr) else None,
    }


def mde_reference(root: Path, constants: dict[str, Any], *, knowledge_cutoff: str | None = None,
                  b: int = MDE_BOOT_B) -> dict[str, Any]:
    """설계창 쌍대 Brier 차 d = BS_PB − BS_arm 의 60원점 창 블록 부트스트랩 se 중앙값 → MDE60 = 1.645·se.

    **채택 근거가 아니다**(설계서 §5-12). PB·c·R1 상수가 모두 같은 설계창에 적합된 표본 내 값이라
    '설계창 평균 d' 의 부호는 참고로만 보고 판정에 쓰지 않는다.
    """
    frozen, _ = load_parent_frozen(root)
    panel = design_panel(root, knowledge_cutoff=knowledge_cutoff)
    cells: dict[str, Any] = {}
    for idx, spec in enumerate(V13C.cell_specs()):
        p, arms, y = _arm_series(spec, panel, frozen, constants)
        m = np.isfinite(y)
        yy = y[m]
        res: dict[str, Any] = {"n": int(m.sum()), "block_length_verdict": C.block_length(spec["h"])}
        for a_idx, (arm, pa) in enumerate(arms.items()):
            d = (p[m] - yy) ** 2 - (pa[m] - yy) ** 2
            ses = [S.block_boot_ci(d[i:i + MDE_WINDOW], seed=[C.BOOTSTRAP_SEED, idx, a_idx, i], b=b,
                                   block=MDE_BLOCK)["se"]
                   for i in range(0, len(d) - MDE_WINDOW + 1, MDE_STRIDE)]
            wins = [float(d[i:i + MDE_WINDOW].mean()) for i in range(0, len(d) - MDE_WINDOW + 1, MDE_WINDOW)]
            se_med = float(np.median(ses))
            res[arm] = {"design_mean_d_insample": float(d.mean()), "se60_median": se_med,
                        "mde60_median": S.MDE_Z * se_med, "windows_se": len(ses),
                        "win60_mean_q05_q50_q95": [float(q) for q in np.quantile(wins, [0.05, 0.5, 0.95])],
                        "frac_win60_d_pos": float(np.mean(np.asarray(wins) > 0))}
        res["origins_to_eligibility"] = origins_to_eligibility(yy, spec["h"])
        cells[spec["name"]] = res
    return {
        "schema_version": 1, "model_id": C.MODEL_ID, "kind": "design_reference_mde",
        "adoption_basis": False,
        "interpretation": ("채택 근거 아님(§5-12). 설계창 평균 d 는 PB·c·R1 상수가 같은 창에 적합된 표본 내 값 — "
                           "R1 의 양수 d 는 l2 축소 해제의 표본 내 이득, R3 의 음수 d 는 PB 의 표본 내 적합 우위. 라이브 예상치로 읽지 않는다."),
        "design_window": list(DESIGN), "bootstrap": {"replicates": b, "seed": C.BOOTSTRAP_SEED,
                                                      "seed_rule": "[20261111, cell_index, arm_index, window_start]",
                                                      "block": MDE_BLOCK, "window": MDE_WINDOW, "stride": MDE_STRIDE},
        "eligibility_rule": "n>=max(60,5*max(13,h)) & events>=20 & non_events>=20 & event_runs>=5 & non_event_runs>=5",
        "constants_content_hash": constants.get("content_hash"),
        "cells": cells,
    }
