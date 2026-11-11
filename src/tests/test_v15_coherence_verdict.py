"""V15 판정·MDE 통계(합성) — spec_U3 §8 V1~V19.

합성 원장만 쓴다(실원장 무관). 판정 JSON 이 (원장, 계약, 판정 코드)만의 함수인지, 가족별 기계 컷 T*·마감 컷·
Holm m 고정·정렬·블록 연결 순서·정정 행 규칙을 고정한다. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v8.contracts import canonical_hash
from ai_fc.timeseries_v15 import verdict as v
from ai_fc.timeseries_v15.mde import critical_effects, ni_pass_flags, summarize_mde
from v15_coherence_fixtures import make_root

START = date(2026, 11, 13)


def _stamp(day: date, hours: int = 3) -> str:
    return datetime(day.year, day.month, day.day, hours, 10, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def build_ledgers(n: int, effects: dict, *, a5_n: int | None = None, a5_lag_weeks: int = 0, c_base: float = 0.02):
    """effects[arm] = f(i, h) → d. 반환 (shadow, issuance, resolutions)."""
    shadow, issuance, resolutions = [], [], []
    for i in range(n):
        origin = START + timedelta(days=7 * i)
        week = f"{origin.isocalendar().year}-W{origin.isocalendar().week:02d}"
        issued = _stamp(origin + timedelta(days=4))
        for arm in ("A0", "A1", "A2", "A3", "A4"):
            shadow.append({"forecast_id": f"{arm}-{i}", "arm": arm, "origin": origin.isoformat(), "iso_week": week,
                           "v8_forecast_id": f"v8-{i}", "seed": 1000 + i, "excluded_reasons": [],
                           "calendar_hash": "cal", "issued_at": issued, "content_hash": f"s-{arm}-{i}"})
        if a5_n is None or i < a5_n:
            issuance.append({"forecast_id": f"A5-{i}", "arm": "A5", "origin": origin.isoformat(), "iso_week": week,
                             "v8_forecast_id": None, "seed": 1000 + i, "excluded_reasons": [],
                             "calendar_hash": "cal", "issued_at": _stamp(origin + timedelta(days=3)),
                             "content_hash": f"i-{i}"})
        c = c_base * (1.0 + 0.3 * math.sin(i))
        for arm in ("A0", "A1", "A2", "A3", "A4", "A5"):
            if arm == "A5" and a5_n is not None and i >= a5_n:
                continue
            for h in (5, 21, 63):
                lag = a5_lag_weeks * 7 if arm == "A5" else 0
                resolved = origin + timedelta(days=math.ceil(h * 7 / 5) + 4 + lag)
                d = 0.0 if arm == "A0" else effects.get(arm, lambda i, h: 0.0)(i, h)
                row = {"resolution_id": f"{arm}-{i}-h{h}-xnas_v1", "forecast_id": f"{arm}-{i}", "horizon": h,
                       "label_basis": "xnas_v1", "crps_model": c + d, "resolved_at": _stamp(resolved),
                       "calendar_hash": "cal", "supersedes": None}
                row["content_hash"] = canonical_hash(row)
                resolutions.append(row)
    resolutions.sort(key=lambda row: (row["resolved_at"], row["resolution_id"]))
    return shadow, issuance, resolutions


def strong(i, h):
    return -0.05 * 0.02 * (1.0 + 0.3 * math.sin(i)) - 1e-5 * (1 + (i % 3))


def zero_mean(i, h):
    return 1e-4 * (1 if i % 2 else -1)


def run(family, ledgers, now=None):
    shadow, issuance, resolutions = ledgers
    return v.family_verdict(family=family, shadow=shadow, issuance=issuance, resolutions=resolutions,
                            now=now, verdict_code_hash="h", rule_hash="r")


def test_v1_strong_effect_passes() -> None:
    result = run("superiority", build_ledgers(39, {"A1": strong}))
    assert result["status"] == "decided" and result["cut_kind"] == "t_star"
    assert result["labels"]["A1:h5"] == "pass" and result["labels"]["A1:h63"] == "pass"
    assert result["members"]["A1:h63"]["n"] == 39


def test_v2_zero_effect_fails() -> None:
    result = run("superiority", build_ledgers(39, {"A1": zero_mean, "A2": zero_mean}))
    assert result["labels"]["A1:h5"] == "fail" and result["labels"]["A2:h63"] == "fail"
    assert result["labels"]["A3:h21"] == "fail"  # d≡0 → d̄*=0 은 ≥0 → p=1


def test_v3_below_minimum_is_insufficient_at_deadline() -> None:
    now = datetime(2028, 7, 1, tzinfo=timezone.utc)
    result = run("superiority", build_ledgers(30, {"A1": strong}), now=now)
    assert result["cut_kind"] == "deadline"
    assert result["labels"]["A1:h63"] == "insufficient"
    assert result["members"]["A1:h63"]["reason"] == "data:minimum_origins"
    assert result["labels"]["A1:h5"] == "pass"


def test_v4_distinct_resample_floor_arithmetic() -> None:
    assert v.distinct_resamples(26, 63) == math.comb(15, 2) == 105 < v.DISTINCT_FLOOR
    assert v.distinct_resamples(39, 63) == math.comb(29, 3) == 3654
    assert v.data_condition(26, 63) is not None and v.data_condition(39, 63) is None
    assert v.required_n(5) == 26 and v.required_n(21) == 26 and v.required_n(63) == 39


def test_v5_ties_count_as_not_better() -> None:
    assert v._pvalue(np.zeros(5000)) == 1.0
    values = np.array([0.0, -1.0, -1.0, -1.0])
    assert v._pvalue(values) == (1 + 1) / 5


def test_v6_holm_step_down() -> None:
    rejected = v.holm({"a": 0.001, "b": 0.012, "c": 0.02, "d": 0.04})
    assert rejected == {"a": True, "b": True, "c": True, "d": True}
    rejected = v.holm({"a": 0.001, "b": 0.03, "c": 0.02, "d": 0.04})
    assert rejected == {"a": True, "b": False, "c": False, "d": False}


def test_v7_concentrated_effect_is_single_episode_insufficient() -> None:
    def concentrated(i, h):
        return -0.004 if i < 10 else 1e-7  # h5: 13블록 중 5블록만 음수

    result = run("superiority", build_ledgers(39, {"A1": concentrated}))
    member = result["members"]["A1:h5"]
    assert member["ci90"][1] < 0 and member["holm_rejected"] is True
    assert member["label"] == "insufficient" and member["reason"] == "single_episode"
    # 최유리 블록 제거 규칙: 블록 과반 음수여도 최유리 블록을 빼면 d̄ ≥ 0 이면 미충족
    d = np.array([-1.0, -1.0] + [-0.001] * 2 * 6 + [0.3] * 2 * 6)
    stats = v._episode_stats(d, 5)
    assert stats["negative_blocks"] == 7 and stats["required"] == 7
    assert stats["mean_without_best_block"] >= 0 and stats["ok"] is False


def test_v8_noninferiority_power_and_margin_boundary() -> None:
    rng = np.random.default_rng(8)
    c = 0.02 + 0.002 * rng.standard_normal(40)
    d = 0.0005 * rng.standard_normal(40)
    d -= d.mean()
    flags = ni_pass_flags(d[None, :], c[None, :], 21, alpha=0.05 / 3)
    stats = v.noninferiority_statistics(d, c, 21)
    assert bool(flags[0]) == (stats["ci90"][1] < 0.01 and stats["p_ni"] < 0.05 / 3)
    near = d + 0.009 * c
    over = d + 0.011 * c
    assert v.noninferiority_statistics(near, c, 21)["delta_rel"] == pytest.approx(0.009, abs=1e-12)
    assert v.noninferiority_statistics(over, c, 21)["ci90"][1] >= 0.01


def test_v9_critical_effect_matches_direct_recomputation() -> None:
    rng = np.random.default_rng(9)
    trials = 0.0005 * rng.standard_normal((30, 26))
    alpha = 0.05 / 12
    critical = critical_effects(trials, 5, alpha=alpha)
    for delta in (0.0, 0.0002, 0.0004, 0.0008, 0.002):
        for row, edge in zip(trials, critical):
            if abs(edge - delta) < 1e-9:
                continue
            shifted = row - delta
            stats = v.superiority_statistics(shifted, 5)
            direct = stats["ci90"][1] < 0 and stats["p"] < alpha and stats["episodes"]["ok"]
            assert direct == (delta > edge), (delta, edge)


def _replay(arm: str, rng, *, shift: float, n: int = 120) -> dict:
    rows = []
    for i in range(n):
        day = date(2007, 1, 5) + timedelta(days=7 * i)
        week = f"{day.isocalendar().year}-W{day.isocalendar().week:02d}"
        for h in (1, 5, 21, 63):
            base = 0.02 * (1 + 0.2 * math.sin(i / 3)) * math.sqrt(h / 5)
            noise = 0.0 if arm == "A0" else 0.0003 * rng.standard_normal()
            rows.append({"date": day.isoformat(), "iso_week": week, "horizon": h, "seed": i,
                         "crps_verdict": base + noise + shift, "y_verdict": 0.0})
    return {"arm": arm, "rows": rows, "input_rows_differing_from_a0": {"A3": 40, "A4": 1}.get(arm)}


def test_v11_representativeness_flag_and_no_effect_estimates() -> None:
    rng = np.random.default_rng(11)
    replays = {arm: _replay(arm, rng, shift=0.0) for arm in ("A0", "A1", "A2", "A3", "A4", "A5")}
    summary = summarize_mde(replays, trials=20)
    for h in ("5", "21", "63"):
        a4 = summary["per_arm"]["A4"][h]
        assert a4["status"] == "not_computable" and a4["mde_rel_at_nmin"] is None
        assert "design_non_representative" in a4["flags"]
        assert a4["proxy_reference"] == summary["values_by_horizon"][h]
        assert summary["values_by_horizon"][h] == max(summary["per_arm"][arm][h]["mde_rel_at_nmin"]
                                                      for arm in ("A1", "A2", "A3"))
        assert "power_at_true_zero" in summary["per_arm"]["A5"][h]
    text = json.dumps(summary)
    assert "design_delta_rel" not in summary and "power_at_design_estimate" not in summary
    assert '"design_delta_rel":' not in text and '"power_at_design_estimate":' not in text


def test_v10_determinism() -> None:
    ledgers = build_ledgers(39, {"A1": strong, "A2": zero_mean})
    first = json.dumps(run("superiority", ledgers), sort_keys=True)
    second = json.dumps(run("superiority", ledgers), sort_keys=True)
    assert first == second


def test_v13_execution_time_invariance() -> None:
    full = build_ledgers(52, {"A1": strong})
    t_star = v.parse_utc(run("superiority", full)["t_star"])
    # T* 시점에 실제로 있던 원장 = 각 행의 기록 시각 ≤ T* 인 접두(append-only 이므로 파일 순서 보존)
    prefix = ([row for row in full[0] if v.parse_utc(row["issued_at"]) <= t_star],
              [row for row in full[1] if v.parse_utc(row["issued_at"]) <= t_star],
              [row for row in full[2] if v.parse_utc(row["resolved_at"]) <= t_star])
    assert len(prefix[2]) < len(full[2]) and len(prefix[0]) < len(full[0])
    at_cut = run("superiority", prefix)
    assert at_cut["t_star"] == v.iso_utc(t_star)
    assert json.dumps(at_cut, sort_keys=True) == json.dumps(run("superiority", full), sort_keys=True)


def test_v14_families_are_independent() -> None:
    full = build_ledgers(45, {"A1": strong})
    slow = build_ledgers(45, {"A1": strong}, a5_n=20, a5_lag_weeks=3)
    assert run("superiority", full)["t_star"] == run("superiority", slow)["t_star"]
    pending = run("noninferiority", slow)
    assert pending["status"] == "pending" and pending["t_star"] is None
    assert pending["counts"]["A5:h5"]["pairs"] < 26


def test_v15_deadline_cut_ignores_later_rows() -> None:
    shadow, issuance, resolutions = build_ledgers(45, {"A1": strong}, a5_n=30)
    deadline = v.parse_utc(v.DEADLINE_CUT_UTC)
    shifted = []
    for row in resolutions:
        if row["forecast_id"].startswith("A5-") and int(row["forecast_id"].split("-")[1]) >= 20:
            row = {**row, "resolved_at": "2028-07-02T00:00:00Z"}
        shifted.append(row)
    result = v.family_verdict(family="noninferiority", shadow=shadow, issuance=issuance, resolutions=shifted,
                              now=datetime(2028, 7, 3, tzinfo=timezone.utc))
    assert result["cut_kind"] == "deadline" and v.parse_utc(result["cut_utc"]) == deadline
    assert result["members"]["A5:h5"]["n"] == 20
    assert result["labels"]["A5:h5"] == "insufficient"


def test_v16_holm_m_is_fixed_at_family_size() -> None:
    pvalues = {f"k{i}": 0.0045 for i in range(9)}
    pvalues.update({f"x{i}": 1.0 for i in range(3)})
    assert not any(v.holm(pvalues).values())  # 0.0045 > 0.05/12 — m 을 9 로 줄였다면 기각됐다
    assert all(v.holm({f"k{i}": 0.0045 for i in range(9)}).values())


def test_v17_ordering_and_drawn_order_concatenation() -> None:
    ledgers = build_ledgers(39, {"A1": strong, "A3": zero_mean})
    shuffled = [list(part) for part in ledgers]
    for part in shuffled:
        random.Random(17).shuffle(part)
    left = run("superiority", ledgers)
    right = run("superiority", tuple(shuffled))
    # 원장 머리 해시는 파일(append) 순서의 지문이라 제외 — 쌍 벡터·판정은 추출 순서와 무관해야 한다
    left.pop("ledger_heads_at_cut")
    right.pop("ledger_heads_at_cut")
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    index = v.bootstrap_indices(7, 5)
    starts = np.random.default_rng([20261111, 5]).integers(0, 7 - 2 + 1, size=(5000, 4))
    manual = np.array([np.concatenate([[s, s + 1] for s in row])[:7] for row in starts])
    assert np.array_equal(index, manual)


def test_v19_corrections_within_cut_only() -> None:
    shadow, issuance, resolutions = build_ledgers(39, {"A1": strong})
    t_star = v.parse_utc(run("superiority", (shadow, issuance, resolutions))["t_star"])
    first = next(row for row in resolutions if row["forecast_id"] == "A1-0" and row["horizon"] == 5)
    inside = {**first, "resolution_id": first["resolution_id"] + "-r2", "crps_model": first["crps_model"] + 0.5,
              "supersedes": first["resolution_id"],
              "resolved_at": (v.parse_utc(first["resolved_at"]) + timedelta(days=1)).isoformat()}
    after = {**inside, "resolution_id": first["resolution_id"] + "-r3", "crps_model": first["crps_model"] - 0.5,
             "resolved_at": (t_star + timedelta(days=30)).isoformat()}
    with_inside = run("superiority", (shadow, issuance, resolutions + [inside]))
    with_both = run("superiority", (shadow, issuance, resolutions + [inside, after]))
    base = run("superiority", (shadow, issuance, resolutions))
    assert with_inside["members"]["A1:h5"]["mean_d"] > base["members"]["A1:h5"]["mean_d"]
    assert with_both["members"]["A1:h5"]["mean_d"] == with_inside["members"]["A1:h5"]["mean_d"]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def test_v12_append_refused_before_cut_and_once_per_family(tmp_path: Path) -> None:
    from ai_fc.timeseries_v15.pipeline import TimeSeriesV15PipelineError, verdict_v15

    root = make_root(tmp_path)
    store = root / "data/timeseries_v15/ledgers"
    shadow, issuance, resolutions = build_ledgers(20, {"A1": strong})
    _write_jsonl(store / "shadow_forecasts.jsonl", shadow)
    _write_jsonl(store / "issuance_forecasts.jsonl", issuance)
    _write_jsonl(store / "shadow_resolutions.jsonl", resolutions)
    now = datetime(2027, 6, 1, tzinfo=timezone.utc)
    printed = verdict_v15(root, family="superiority", now=now)
    assert printed["status"] == "pending" and set(printed["labels"].values()) == {"insufficient"}
    assert "members" not in printed  # T* 전에는 건수만
    with pytest.raises(TimeSeriesV15PipelineError):
        verdict_v15(root, family="superiority", append=True, now=now)
    shadow, issuance, resolutions = build_ledgers(39, {"A1": strong})
    _write_jsonl(store / "shadow_forecasts.jsonl", shadow)
    _write_jsonl(store / "issuance_forecasts.jsonl", issuance)
    _write_jsonl(store / "shadow_resolutions.jsonl", resolutions)
    appended = verdict_v15(root, family="superiority", append=True, now=datetime(2028, 1, 1, tzinfo=timezone.utc))
    assert appended["append"] is True and appended["labels"]["A1:h63"] == "pass"
    with pytest.raises(TimeSeriesV15PipelineError):
        verdict_v15(root, family="superiority", append=True, now=datetime(2028, 1, 2, tzinfo=timezone.utc))


def test_v18_verdict_code_drift_refuses(tmp_path: Path) -> None:
    from ai_fc.timeseries_v15.contracts import TimeSeriesV15ContractError
    from ai_fc.timeseries_v15.pipeline import verdict_v15

    root = make_root(tmp_path)
    path = root / "src/ai_fc/timeseries_v15/verdict.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8", newline="\n")
    with pytest.raises(TimeSeriesV15ContractError):
        verdict_v15(root, family="superiority", now=datetime(2027, 1, 1, tzinfo=timezone.utc))


def _drift_rows(resolutions: list[dict], arm: str, indices, h: int, stamp: datetime, calendar_hash: str,
                suffix: str) -> list[dict]:
    rows = []
    for i in indices:
        base = next(row for row in resolutions if row["forecast_id"] == f"{arm}-{i}" and row["horizon"] == h)
        row = {**base, "resolution_id": base["resolution_id"] + suffix, "supersedes": base["resolution_id"],
               "calendar_hash": calendar_hash, "resolved_at": stamp.isoformat().replace("+00:00", "Z")}
        row.pop("content_hash", None)
        row["content_hash"] = canonical_hash(row)
        rows.append(row)
    return rows


def test_v20_t_star_is_first_simultaneous_not_max_of_first_reach() -> None:
    """리뷰 비차단 6: 먼저 도달한 구성원이 달력 정정(calendar_drift)으로 다시 미달하면 T* 는 구성원별 최초 도달
    시각의 max 가 아니라 전원이 처음 **동시에** 충족하는 시각이다(계약 verdict_cut.rule)."""
    shadow, issuance, resolutions = build_ledgers(39, {"A1": strong})
    lower = v.parse_utc(run("superiority", (shadow, issuance, resolutions))["t_star"])
    # A1:h5 는 39쌍으로 먼저 도달 — lower 직전에 14원점을 calendar_drift 로 빼면 25 < 26
    dropped = _drift_rows(resolutions, "A1", range(14), 5, lower - timedelta(days=1), "drifted", "-r2")
    only_drop = run("superiority", (shadow, issuance, resolutions + dropped))
    assert only_drop["t_star"] is None and only_drop["status"] == "pending"
    assert only_drop["member_ready_at"]["A1:h5"] is not None  # 최초 도달은 있었다 — max 규칙이면 lower 가 됐을 것
    restore_at = lower + timedelta(days=10)
    restored = _drift_rows(resolutions, "A1", range(14), 5, restore_at, "cal", "-r3")
    for row, prior in zip(restored, dropped):
        row["supersedes"] = prior["resolution_id"]
    both = run("superiority", (shadow, issuance, sorted(resolutions + dropped + restored,
                                                       key=lambda row: (row["resolved_at"], row["resolution_id"]))))
    assert v.parse_utc(both["t_star"]) == v.parse_utc(restore_at.isoformat())
    assert both["status"] == "decided" and both["members"]["A1:h5"]["n"] == 39
