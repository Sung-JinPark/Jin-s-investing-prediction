"""V15-VOL 판정 산술 (명세 U5 §8.5) — 접두·Holm·부호반전 귀무·잠정 라벨·쓰기 0. tmp_path 합성 원장."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v13 import scoring as S
from ai_fc.timeseries_v15_vol import arms as A
from ai_fc.timeseries_v15_vol import contracts as C
from ai_fc.timeseries_v15_vol import verdict as V
from ai_fc.timeseries_v15_vol.resolve import _xnas_session_offset, _xnas_sessions
from v15_vol_fixtures import V13_LIVE, V15_RES, V15_SHADOW, arm, file_hashes, make_root, protected_hashes, write_jsonl

START = date(2020, 1, 2)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(C.ARMING_ENV, raising=False)
    before = protected_hashes()
    yield
    assert protected_hashes() == before


def _sessions(n: int, start: date = START) -> list[str]:
    days = [d for d in _xnas_sessions(start.year - 1, start.year + 4) if d >= start]
    return [d.isoformat() for d in days[:n]]


def _run_labels(n: int, run: int = 6, phase: int = 0) -> list[float]:
    return [float(((i + phase) // run) % 2) for i in range(n)]


def _synthetic(root: Path, *, cells: dict[str, dict], n: int, settle_extra: int = 25,
               states: dict[tuple[str, int], str] | None = None,
               derived_at: dict[int, str] | None = None) -> list[str]:
    """cells: {cell: {'y': [...], 'pb': [...], 'r1': [...], 'r2': [...]?, 'r3': [...]}} — 원점 순서대로 합성."""
    origins = _sessions(n + settle_extra)
    shadow, resolutions = [], []
    states = states or {}
    for i in range(n):
        run_id = f"v15vol-{origins[i]}-syn"
        row_cells = {}
        for cell, data in cells.items():
            cols = {"calm": True, "p_pb": data["pb"][i], "p_r1": data["r1"][i], "p_r3": data["r3"][i],
                    "clim": 0.3, "cond": 0.3}
            if "r2" in data:
                cols["p_r2"] = data["r2"][i]
            row_cells[cell] = cols
            state = states.get((cell, i), "scored")
            if state == "pending":
                continue
            probs = {"pb": cols["p_pb"], "r1": cols["p_r1"], "r3": cols["p_r3"], "clim": 0.3, "cond": 0.3}
            if "p_r2" in cols:
                probs["r2"] = cols["p_r2"]
            y = data["y"][i]
            scored = state == "scored"
            resolutions.append({
                "resolution_id": f"{run_id}-{cell}", "run_id": run_id, "cell": cell, "origin": origins[i],
                "label": y, "scored": scored, "hold_reason": None if scored else "xnas_session_mismatch",
                "probabilities": probs,
                "brier": {k: A.brier(p, y) for k, p in probs.items()} if scored else None,
                "log_score": {k: A.log_score(p, y) for k, p in probs.items()} if scored else None,
            })
        stamp = (derived_at or {}).get(i, f"{origins[i]}T23:00:00+00:00")       # 기본: 원점 당일 파생(정시)
        shadow.append({"run_id": run_id, "as_of": origins[i], "derived_at": stamp, "cells": row_cells})
    write_jsonl(root / V15_SHADOW, shadow)
    write_jsonl(root / V15_RES, resolutions)
    write_jsonl(root / V13_LIVE, [{"as_of": origins[-1], "run_id": "v13-syn", "coefficients_sha256": "x"}])
    return origins


def _root(tmp_path: Path) -> Path:
    root = make_root(tmp_path, v13_ledgers=False)
    arm(root)
    return root


def _cell_data(n: int, *, strong: bool = False, seed: int = 0, r2: bool = True, run: int = 6) -> dict:
    rng = np.random.default_rng(seed)
    y = _run_labels(n, run=run)
    pb = [float(np.clip(0.5 + rng.normal(0, 0.15), 0.05, 0.95)) for _ in range(n)]
    r1 = [0.97 if v == 1.0 else 0.03 for v in y] if strong else list(pb)
    data = {"y": y, "pb": pb, "r1": r1, "r3": list(pb)}
    if r2:
        data["r2"] = list(pb)
    return data


def _moderate_cell(n: int, *, run: int = 20, mu: float = 0.02, sd: float = 0.08, seed: int = 2) -> dict:
    """PB = 0.5 고정, 팔의 Brier 를 0.25 − d_i 로 맞춘 합성(d_i = μ + 잡음) — 블록 상관이 약한 우세."""
    rng = np.random.default_rng(seed)
    y = _run_labels(n, run=run)
    d = np.clip(mu + rng.normal(0, sd, n), -0.2, 0.2)
    gap = np.sqrt(0.25 - d)
    arm_p = [float(1 - g) if v == 1.0 else float(g) for v, g in zip(y, gap)]
    pb = [0.5] * n
    return {"y": y, "pb": pb, "r1": arm_p, "r2": list(pb), "r3": list(pb)}


def _pair(result: dict, arm_name: str, cell: str) -> dict:
    return next(p for p in result["pairs"] if p["arm"] == arm_name and p["cell"] == cell)


def test_small_sample_all_insufficient(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _synthetic(root, cells={"vix25_h5": _cell_data(40)}, n=40)
    result = V.shadow_verdict(root, rv_mechanics=False, draws=10)
    assert all(p["status"] == "insufficient" and p["p"] == 1.0 for p in result["pairs"])
    assert not any(h["reject"] for h in result["holm"])
    assert result["read_only"] is True and result["writes"] == 0 and result["family_size"] == 20


def test_prefix_is_deterministic_under_appends(tmp_path: Path) -> None:
    root = _root(tmp_path)
    data = _cell_data(200, strong=True)
    short = {k: v[:120] for k, v in data.items()}
    _synthetic(root, cells={"vix25_h5": short}, n=120)
    first = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    _synthetic(root, cells={"vix25_h5": data}, n=200)
    second = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    a, b = _pair(first, "R1_platt", "vix25_h5"), _pair(second, "R1_platt", "vix25_h5")
    assert a["eligible"] and b["eligible"]
    assert first["cells"]["vix25_h5"]["prefix"] == second["cells"]["vix25_h5"]["prefix"]
    assert a["d_brier"] == b["d_brier"] and a["n"] == b["n"] == 65


def test_pending_blocks_but_held_does_not(tmp_path: Path) -> None:
    root = _root(tmp_path)
    data = _cell_data(120, strong=True)
    _synthetic(root, cells={"vix25_h5": data}, n=120, states={("vix25_h5", 10): "pending"})
    result = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    assert result["cells"]["vix25_h5"]["prefix"]["eligible"] is False
    assert result["cells"]["vix25_h5"]["prefix"]["reason"] == "pending_in_prefix"
    _synthetic(root, cells={"vix25_h5": data}, n=120, states={("vix25_h5", 10): "held"})
    result = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    prefix = result["cells"]["vix25_h5"]["prefix"]
    assert prefix["eligible"] is True and prefix["n"] == 65
    assert result["cells"]["vix25_h5"]["held_by_reason"] == {"xnas_session_mismatch": 1}


def test_settle_limit_blocks_recent_prefix(tmp_path: Path) -> None:
    root = _root(tmp_path)
    data = _cell_data(70, strong=True)
    origins = _synthetic(root, cells={"vix25_h5": data}, n=70, settle_extra=0)
    result = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    assert result["cells"]["vix25_h5"]["prefix"]["eligible"] is False      # 마지막 원점이 V13 최신 as_of − 20 세션보다 뒤
    later = _xnas_session_offset(date.fromisoformat(origins[-1]), 25).isoformat()
    write_jsonl(root / V13_LIVE, [{"as_of": later, "run_id": "v13-syn", "coefficients_sha256": "x"}])
    result = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    assert result["cells"]["vix25_h5"]["prefix"]["eligible"] is True


def test_strong_superiority_passes_with_holm(tmp_path: Path) -> None:
    root = _root(tmp_path)
    # 국면이 긴(run 20) 합성 — 첫 적격 접두가 n=181(K=13). 블록 상관이 강한 우세(일정한 d)는 부호반전 귀무가
    # 0.10 을 넘겨 void 가 된다(계약 공시 — 내부 부트스트랩 CI 의 반보수성) — 그래서 잡음 섞인 중간 우세로 pass 경로를 확인한다.
    _synthetic(root, cells={"vix25_h5": _moderate_cell(260)}, n=260)
    result = V.shadow_verdict(root, rv_mechanics=False)
    pair = _pair(result, "R1_platt", "vix25_h5")
    assert pair["n"] == 181
    assert pair["p"] == pytest.approx(1 / (C.BOOTSTRAP_REPLICATES + 1))
    assert pair["p"] <= C.ALPHA / C.FAMILY_SIZE and pair["holm_reject"] is True
    assert pair["sign_flip_null_pass_rate"] <= C.NULL_PASS_RATE_MAX
    assert pair["single_episode_guard"]["pass"] and pair["log_non_inferior"]
    assert pair["status"] == "pass_shadow_superiority"
    same = _pair(result, "R3_regime_mix", "vix25_h5")          # R3 = PB → d = 0
    assert same["holm_reject"] is False and same["status"] == "not_rejected_provisional"
    assert result["family_complete"] is False


def test_block_constant_superiority_is_void(tmp_path: Path) -> None:
    """d 가 블록마다 거의 일정한 강한 우세 → 부호반전 귀무 통과율 > 0.10 → void_negative_control (확정, Holm 무관)."""
    root = _root(tmp_path)
    _synthetic(root, cells={"vix25_h5": _cell_data(260, strong=True, run=20)}, n=260)
    pair = _pair(V.shadow_verdict(root, rv_mechanics=False), "R1_platt", "vix25_h5")
    assert pair["holm_reject"] is True and pair["sign_flip_null_pass_rate"] > C.NULL_PASS_RATE_MAX
    assert pair["status"] == "void_negative_control" and pair["conditions_other_than_holm"] is False


def test_sign_flip_null_is_sharpness_independent() -> None:
    rng = np.random.default_rng(20261111)
    n = 150
    y = np.array(_run_labels(n, run=5), float)
    pb = np.clip(0.3 + rng.normal(0, 0.05, n), 0.01, 0.99)
    duller = 0.5 * pb + 0.5 * 0.3
    logit = np.log(pb / (1 - pb))
    sharper = 1 / (1 + np.exp(-1.5 * logit))
    rates = {}
    yblock = {}
    for name, arm_p in (("duller", duller), ("sharper", sharper)):
        d = (pb - y) ** 2 - (arm_p - y) ** 2
        d = d - d.mean()                     # 기대 손실차 ≈ 0 (귀무 아래)
        rates[name] = V.sign_flip_null_pass_rate(d, 13, cell_index=0, arm_index=0)
        again = V.sign_flip_null_pass_rate(d, 13, cell_index=0, arm_index=0)
        assert rates[name] == again          # 결정론
        yblock[name] = S.y_block_null_pass_rate(
            y, lambda yy, a=arm_p: S.block_boot_ci((pb - yy) ** 2 - (a - yy) ** 2, b=200)["ci90"][0] > 0,
            draws=20, seed=1)                # 기록만 — 비교 단언 없음(대조용)
    assert all(0.0 <= r <= 0.2 for r in rates.values()), rates
    assert abs(rates["duller"] - rates["sharper"]) <= 0.2, (rates, yblock)


def test_zero_events_is_insufficient(tmp_path: Path) -> None:
    root = _root(tmp_path)
    data = _cell_data(150)
    data["y"] = [0.0] * 150
    _synthetic(root, cells={"vix25_h5": data}, n=150)
    result = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    assert all(_pair(result, a, "vix25_h5")["status"] == "insufficient"
               for a in ("R1_platt", "R2_calm_jump", "R3_regime_mix"))


def test_crn_indices_shared_within_cell(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _synthetic(root, cells={"vix25_h5": _cell_data(130, strong=True)}, n=130)
    captured: dict[str, np.ndarray] = {}
    result = V.shadow_verdict(root, rv_mechanics=False, draws=3, index_hook=lambda c, idx: captured.setdefault(c, idx))
    assert set(captured) == {"vix25_h5"}
    idx = captured["vix25_h5"]
    rows = [r for r in __import__("v15_vol_fixtures").read_jsonl(root / V15_RES)][:65]
    for arm_name, col in (("R1_platt", "r1"), ("R2_calm_jump", "r2"), ("R3_regime_mix", "r3")):
        d = np.array([r["brier"]["pb"] - r["brier"][col] for r in rows])
        assert V.boot_summary(d, idx) == _pair(result, arm_name, "vix25_h5")["d_brier"]
    same = np.random.default_rng([C.BOOTSTRAP_SEED, 0])
    assert np.array_equal(V.stationary_indices(same, 65, 13, C.BOOTSTRAP_REPLICATES), idx)


def test_holm_monotone_and_rank_shift() -> None:
    m = 20
    base = [1.0] * m
    base[0] = 0.001
    assert V.holm(base)[0] is True
    lower = list(base)
    lower[5] = 0.001
    assert V.holm(lower)[0] is True                       # 다른 p 가 내려가도 기존 기각 유지
    alone = [1.0] * m
    alone[3] = 0.0026                                     # 0.0026 > 0.05/20 = 0.0025
    assert V.holm(alone)[3] is False
    shifted = list(alone)
    shifted[7] = 0.0001                                   # 순위 2 문턱 0.05/19 ≈ 0.002632
    assert V.holm(shifted)[3] is True and V.holm(shifted)[7] is True
    ties = [0.001, 0.001] + [1.0] * 18
    assert V.holm(ties)[:2] == [True, True]


def test_provisional_vs_fail_by_family_completeness(tmp_path: Path) -> None:
    root = _root(tmp_path)
    n = 330
    flat = _cell_data(n)                               # 팔 = PB → d = 0 → 비기각
    _synthetic(root, cells={"vix25_h5": flat}, n=n)
    partial = V.shadow_verdict(root, rv_mechanics=False, draws=3)
    assert partial["family_complete"] is False
    assert _pair(partial, "R1_platt", "vix25_h5")["status"] == "not_rejected_provisional"
    cells = {c: (_cell_data(n) if c in C.R2_CELLS else {k: v for k, v in _cell_data(n).items() if k != "r2"})
             for c in C.CELL_ORDER}
    _synthetic(root, cells=cells, n=n)
    full = V.shadow_verdict(root, rv_mechanics=False, draws=3)
    assert full["family_complete"] is True
    assert _pair(full, "R1_platt", "vix25_h5")["status"] == "fail"
    assert all(p["eligible"] for p in full["pairs"])
    assert full["cells"]["vix25_h63"]["prefix"]["n"] >= 315


def test_verdict_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _synthetic(root, cells={"vix25_h5": _cell_data(130, strong=True)}, n=130)
    tracked = (V15_SHADOW, V15_RES, V13_LIVE, "data/timeseries_v15_vol/ledgers/arming.jsonl",
               "data/contracts/multivariate_timeseries_v15_vol.yaml")
    before = file_hashes(root, tracked)
    files_before = sorted(p.as_posix() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    V.shadow_verdict(root, rv_mechanics=False, draws=3)
    assert file_hashes(root, tracked) == before
    assert sorted(p.as_posix() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts) == files_before


def test_block_length_and_eligibility_thresholds() -> None:
    assert C.block_length(5) == 13 and C.block_length(21) == 21 and C.block_length(63) == 63

    def origins(n: int) -> list[dict]:
        y = _run_labels(n, run=3)
        days = _sessions(n)
        return [{"origin": days[i], "state": "scored", "resolution": {"label": y[i]}} for i in range(n)]

    far = "2099-12-31"
    assert V.first_eligible_prefix(origins(104), 21, far)["eligible"] is False
    assert V.first_eligible_prefix(origins(105), 21, far)["n"] == 105
    assert V.first_eligible_prefix(origins(64), 5, far)["eligible"] is False
    assert V.first_eligible_prefix(origins(65), 5, far)["n"] == 65
    ids, k = V.block_ids(70, 13)
    assert k == 5 and int((ids == 4).sum()) == 18


def test_single_episode_guard_requires_two_blocks() -> None:
    assert V.single_episode_guard(np.ones(20), 13)["pass"] is False      # K=1
    d = np.concatenate([np.full(13, 0.5), np.full(13, 0.1), np.full(13, -0.05)])
    guard = V.single_episode_guard(d, 13)
    assert guard["K"] == 3 and guard["pass"] is True
    assert math.isclose(guard["mean_without_best_block"], 0.025)


def test_rv_mechanics_clone_matches_research_layer() -> None:
    """닫힌형 복제(verdict.mechanical_positive) == 연구 계층 rv_mechanics (1e-12) — 설계창 수익만 읽는다."""
    from ai_fc.mts_research.audits.rv_mechanics import mechanical_positive as research
    from ai_fc.timeseries_v13 import features as F
    from ai_fc.timeseries_v2.market_archive import read_market_observations
    from v15_vol_fixtures import ROOT

    panel = F.build_panel(read_market_observations(ROOT, knowledge_cutoff="2026-11-11T09:03:44+00:00"),
                          start="2007-01-01", end="2014-12-31")
    returns = np.concatenate([[np.nan], np.diff(np.log(panel["ndx"]))])
    checked = mech = 0
    for t in range(40, len(returns) - 70, 37):
        for h in (5, 21, 63):
            ours = V.mechanical_positive(returns, t, h, C.THETA_RV)
            theirs = research(returns, t, h, C.THETA_RV)
            assert abs(ours["max_floor"] - theirs["max_floor"]) <= 1e-12
            assert ours["argmax_k"] == theirs["argmax_k"]
            assert ours["mechanically_determined"] == theirs["mechanically_determined"]
            checked += 1
            mech += int(ours["mechanically_determined"])
    assert checked > 100 and mech > 0


# ── 리뷰 수정(w1-u5 fix) ────────────────────────────────────────────────────────
def test_late_derived_rule_boundary() -> None:
    """N3: derived_at UTC 날짜 ≥ 원점 + 20 XNAS 세션이면 접두 제외. 해석 불가도 제외(보수)."""
    origin = date(2026, 3, 2)
    settle = _xnas_session_offset(origin, C.PREFIX_SETTLE_SESSIONS)
    before = _xnas_session_offset(origin, C.PREFIX_SETTLE_SESSIONS - 1)
    row = {"as_of": origin.isoformat()}
    assert V._late_derived({**row, "derived_at": f"{origin.isoformat()}T23:00:00+00:00"}) is False
    assert V._late_derived({**row, "derived_at": f"{before.isoformat()}T23:59:59+00:00"}) is False
    assert V._late_derived({**row, "derived_at": f"{settle.isoformat()}T00:00:00+00:00"}) is True
    assert V._late_derived({**row, "derived_at": f"{origin.isoformat()}T23:00:00"}) is True     # naive
    assert V._late_derived(row) is True


def test_late_backfilled_origin_does_not_change_fixed_prefix(tmp_path: Path) -> None:
    """N3: 접두가 확정된 뒤 V13 late_capture 백필로 오래된 원점의 V15 행이 늦게 생겨도 확증 통계는 그대로다."""
    root = _root(tmp_path)
    data = _cell_data(130, strong=True)
    origins = _synthetic(root, cells={"vix25_h5": data}, n=130)
    first = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    assert first["cells"]["vix25_h5"]["late_derived_excluded_from_prefix"] == 0
    # 접두 안 원점 10 이 '나중에야' 파생된 상황 — 같은 원장에 그 행이 늦은 derived_at 으로 들어온 것과 같다.
    late_stamp = f"{_xnas_session_offset(date.fromisoformat(origins[-1]), 1).isoformat()}T11:25:00+00:00"
    flipped = {k: list(v) for k, v in data.items()}
    flipped["y"][10] = 1.0 - flipped["y"][10]
    _synthetic(root, cells={"vix25_h5": flipped}, n=130, derived_at={10: late_stamp})
    second = V.shadow_verdict(root, rv_mechanics=False, draws=5)
    assert second["cells"]["vix25_h5"]["late_derived_excluded_from_prefix"] == 1
    a, b = _pair(first, "R1_platt", "vix25_h5"), _pair(second, "R1_platt", "vix25_h5")
    assert a["eligible"] and b["eligible"]
    # 원점 10 을 원래부터 없던 것으로 친 접두와 같다(결정론 — 늦은 행은 접두 밖).
    base = [{"origin": origins[i], "state": "scored", "resolution": {"label": data["y"][i]}, "late_derived": False}
            for i in range(130) if i != 10]
    expected = V.first_eligible_prefix(base, 5, "2099-12-31")
    assert b["n"] == expected["n"] and second["cells"]["vix25_h5"]["prefix"]["end_origin"] == expected["end_origin"]


def test_render_table_shows_draws_and_other_conditions(tmp_path: Path) -> None:
    """N5: 표 머리에 draws·계약값 여부, 열에 holm·other(Holm 외 4조건)."""
    root = _root(tmp_path)
    _synthetic(root, cells={"vix25_h5": _cell_data(130, strong=True)}, n=130)
    result = V.shadow_verdict(root, rv_mechanics=False, draws=3)
    table = V.render_table(result)
    assert "draws 3" in table and "계약값 아님" in table
    header = next(line for line in table.splitlines() if line.startswith("arm"))
    assert "holm" in header and "other" in header
    row = next(line for line in table.splitlines() if line.startswith("R1_platt") and "vix25_h5" in line)
    pair = _pair(result, "R1_platt", "vix25_h5")
    assert row.split()[-3:-1] == [str(pair["holm_reject"])[0], str(pair["conditions_other_than_holm"])[0]]
    assert "참고 의견" in table
