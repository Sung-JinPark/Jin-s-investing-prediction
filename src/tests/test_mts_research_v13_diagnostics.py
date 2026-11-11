"""P6 — V13 라이브 읽기 전용 진단 테스트 (합성 수학 + 실자료 오라클 + CLI 쓰기 규율).

실자료 오라클은 as_of=2026-11-09 고정 원점 집합으로 묶는다 — 원장이 늘어도 깨지지 않는다.
영구 원장·스냅샷은 읽기만 한다(실행 전후 sha256 동일). CLI 쓰기 검사는 tmp_path 사본에서만 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ai_fc.mts_research.audits import v13_live_diagnostics as D
from mts_research_fixtures import research_root

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-11-09"
HAS_INPUTS = all((ROOT / p).is_file() for p in (
    "data/timeseries_v13/vol/champion_coefficients.json",
    "data/timeseries_v13/ledgers/vol_live.jsonl",
    "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
    "data/timeseries_v13/ledgers/holdout_scorings.jsonl",
    "data/mts_research/experiments/rv_mechanics/prereg.json",
))


# ---------------------------------------------------------------------------
# 합성 수학
# ---------------------------------------------------------------------------


def _curve(a: float, b: float, preds: list[float], n: int = 1000) -> list[dict]:
    """정확히 Cox(a,b) 를 따르는 구간 곡선 — 적합이 (a,b) 를 복원해야 한다."""
    out = []
    for k, p in enumerate(preds):
        obs = 1.0 / (1.0 + np.exp(-(a + b * np.log(p / (1 - p)))))
        out.append({"bin": k, "n": n, "pred": p, "obs": float(obs)})
    return out


def test_binned_cox_recovers_known_slope():
    curve = _curve(-0.3, 0.7, [0.02, 0.15, 0.35, 0.55, 0.8])
    fit = D.binned_cox(curve)
    assert fit["a"] == pytest.approx(-0.3, abs=1e-4)
    assert fit["b"] == pytest.approx(0.7, abs=1e-4)
    assert fit["n"] == 5000 and fit["n_bins"] == 5
    dropped = D.binned_cox(curve, drop_bin0=True)
    assert dropped["n_bins"] == 4 and dropped["b"] == pytest.approx(0.7, abs=1e-4)


def test_binned_cox_rejects_degenerate_pred_without_clipping():
    curve = _curve(0.0, 1.0, [0.1, 0.5])
    curve[0]["pred"] = 0.0
    with pytest.raises(D.MtsV13DiagnosticsError):
        D.binned_cox(curve)
    with pytest.raises(D.MtsV13DiagnosticsError):
        D.binned_cox(_curve(0.0, 1.0, [0.1, 0.5]), drop_bin0=True)   # 구간 1개 — 적합 불가


def test_reliability_by_bin_hand_oracle():
    rows = [
        {"origin": "2026-01-01", "probability": 0.05, "label": 0.0},
        {"origin": "2026-01-02", "probability": 0.08, "label": 1.0},
        {"origin": "2026-01-03", "probability": 0.09, "label": 1.0},
        {"origin": "2026-01-04", "probability": 0.02, "label": 0.0},
        {"origin": "2026-01-05", "probability": 0.07, "label": 1.0},
        {"origin": "2026-01-06", "probability": 1.0, "label": 1.0},
    ]
    out = D.reliability_by_bin(rows)
    assert [b["n"] for b in out] == [5, 0, 0, 1]
    assert out[0]["sum_p"] == pytest.approx(0.31)
    assert out[0]["events"] == 3 and out[0]["event_runs"] == 2      # (1,1) · (1) 두 run
    assert out[3]["events"] == 1                                      # 마지막 구간은 1.0 포함
    with pytest.raises(D.MtsV13DiagnosticsError):
        D.reliability_by_bin(rows, edges=(0.1, 1.0))


def test_future_best_uses_event_path_not_only_nonevent():
    """회귀: 최선 d = max(π², (1−π)²). π<0.5 이면 사건·p→1 경로가 최선이다."""
    best, worst = D.best_worst_future(0.4195)
    assert best[0] == pytest.approx((1 - 0.4195) ** 2) and best[1:] == (1.0, 1.0)
    assert worst[0] == pytest.approx(0.4195 ** 2 - 1.0)
    best_hi, _ = D.best_worst_future(0.7)
    assert best_hi[0] == pytest.approx(0.49) and best_hi[1:] == (0.0, 0.0)
    (open_best, y_best), (open_worst, _) = D.best_worst_open(0.4195, 0.843535)
    assert y_best == 1.0 and open_best == pytest.approx(D.loss_difference(0.4195, 0.843535, 1.0))
    assert open_worst < 0 < open_best


def test_expected_loss_sign_condition_matches_direct_expectation():
    pi, p = 0.4195, 0.08
    threshold = D.expected_loss_sign_threshold(pi, p)["pi_true_threshold"]
    for pi_true in (threshold - 0.05, threshold + 0.05):
        expected = pi_true * D.loss_difference(pi, p, 1.0) + (1 - pi_true) * D.loss_difference(pi, p, 0.0)
        assert expected == pytest.approx((pi - p) * (pi + p - 2 * pi_true))
        assert (expected > 0) == (pi_true < threshold)


def test_const_baseline_loss_hand_oracle_and_guards():
    rows = [{"probability": 0.2, "label": 1.0}, {"probability": 0.1, "label": 0.0}]
    out = D.const_baseline_loss(rows, 0.5)
    assert out["brier_model"] == pytest.approx((0.64 + 0.01) / 2)
    assert out["brier_const"] == pytest.approx(0.25)
    assert out["bss_vs_const"] == pytest.approx(round(1 - 0.325 / 0.25, 4))
    with pytest.raises(D.MtsV13DiagnosticsError):
        D.const_baseline_loss(rows, 0.0)
    with pytest.raises(D.MtsV13DiagnosticsError):
        D.const_baseline_loss([{"probability": 0.0, "label": 0.0}], 0.3)


def test_partial_label_determination():
    spec = {"name": "vix25_h5", "target": "vix_touch", "K": 25, "h": 5}
    panel = {"dates": np.array([f"d{i}" for i in range(6)], dtype=object),
             "vix": np.array([18.0, 19.0, 26.0, 20.0, 19.0, 18.0])}
    assert D._partial_label(spec, panel, 0) == (1.0, True)          # 창 끝 = 마지막 세션
    assert D._partial_label(spec, panel, 1) == (1.0, False)         # 미성숙이지만 이미 사건
    assert D._partial_label(spec, panel, 3) == (None, False)        # 미성숙·미확정
    calm = dict(panel, vix=np.full(6, 18.0))
    assert D._partial_label(spec, calm, 0) == (0.0, True)


# ---------------------------------------------------------------------------
# 실자료 오라클 (as_of 고정, 읽기 전용)
# ---------------------------------------------------------------------------


def _protected_hashes() -> dict[str, str]:
    paths = [
        "data/timeseries_v13/ledgers/vol_live.jsonl",
        "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
        "data/timeseries_v13/ledgers/holdout_scorings.jsonl",
        "data/timeseries_v13/vol/champion_coefficients.json",
        "data/contracts/multivariate_timeseries_v13_vol.yaml",
        "data/mts_research/ledgers/exposures.jsonl",
    ]
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if (ROOT / p).is_file()}


@pytest.fixture(scope="module")
def report():
    if not HAS_INPUTS:
        pytest.skip("실자료 없음")
    before = _protected_hashes()
    result = D.build_report(ROOT, as_of=AS_OF)
    assert _protected_hashes() == before, "진단이 원장·계수·계약을 바꿨다"
    return result


def test_report_fixed_fields(report):
    assert report["display_only"] is True and report["scoring_excluded"] is True
    assert report["notice"] == "참고 의견, 매매 신호 아님"
    assert report["as_of"] == AS_OF and report["n_origins"] == 43
    assert report["single_episode"] is True
    assert report["writes_to_ledgers"] == 0
    json.dumps(report, allow_nan=False)


def test_t7_vix25_h21_oracle(report):
    t7 = report["cells"]["vix25_h21"]["t7"]
    assert t7["climatology_pi"] == pytest.approx(0.4195, abs=1e-4)
    assert t7["determined_n"] == 41
    assert t7["sum_d_determined"] == pytest.approx(-2.963, abs=1e-3)
    assert t7["future_origins"] == 17
    assert t7["target_origin_session"] == "2026-12-03"
    assert t7["target_verdict_session"] == "2027-01-05"
    assert t7["d_upper"] <= 0.057
    assert t7["paths"]["best_case"]["ci90"][0] < 0
    assert t7["demotion_at_best_path"] is True
    # 회귀: 비사건 전용 π² 상한(+0.006)은 대조로만 남고 판단 상한이 아니다
    assert t7["contrast_nonevent_only_upper"] == pytest.approx(0.006, abs=1e-3)
    assert t7["d_upper"] > t7["contrast_nonevent_only_upper"] + 0.03


def test_t7_rv_cells_and_summary(report):
    rv_h5 = report["cells"]["rv_h5"]["t7"]["paths"]["persistence_event"]
    assert rv_h5["ci90"][0] > 0.1                                     # 견고 (하한 약 +0.14)
    rv_h21 = report["cells"]["rv_h21"]["t7"]["paths"]["persistence_event"]
    assert -0.01 < rv_h21["ci90"][0] < 0.02                          # 칼날 (하한 약 +0.002)
    summary = report["t7_summary"]
    assert summary["scope_cells"] == ["vix25_h21", "rv_h5", "rv_h21"]
    assert summary["demotion_in_all_paths"] == ["vix25_h21"]
    assert summary["t7_trigger_determined"] is False


def test_live_verdict_consistency(report):
    live = report["cells"]["vix25_h21"]["live"]
    assert live["matured"] == 23
    assert live["brier_model"] == pytest.approx(0.1224, abs=1e-4)
    assert live["brier_climatology"] == pytest.approx(0.1970, abs=1e-4)
    assert live["status"] == "insufficient_sample"
    assert report["cells"]["vix25_h5"]["live"]["brier_model"] == pytest.approx(0.0657, abs=1e-4)


def test_holdout_cox_oracle(report):
    cells = report["cells"]
    assert cells["vix25_h5"]["holdout_cox"]["all_bins"]["b"] == pytest.approx(0.728, abs=0.02)
    assert cells["vix25_h21"]["holdout_cox"]["all_bins"]["b"] == pytest.approx(0.666, abs=0.02)
    assert cells["rv_h5"]["holdout_cox"]["all_bins"]["b"] == pytest.approx(1.06, abs=0.02)
    assert cells["vix25_h21"]["holdout_cox"]["drop_bin0"]["b"] == pytest.approx(0.87, abs=0.02)
    example = cells["vix25_h21"]["holdout_cox"]["example_probability_not_published"]
    assert "발행값 아님" in example["label"]


def test_rv_mechanics_split_oracle(report):
    split = report["cells"]["rv_h5"]["rv_mechanics_split"]
    assert (split["mechanical_positives"], split["events"]) == (7, 12)
    assert split["nonmechanical"]["n"] == 31
    assert split["nonmechanical_event_split"]["events_n"] == 5
    assert split["nonmechanical"]["bss"] == pytest.approx(0.69, abs=0.01)
    assert report["cells"]["rv_h21"]["rv_mechanics_split"]["mechanical_positives"] == 0


def test_const_baselines_and_jump(report):
    h5 = report["cells"]["vix25_h5"]["const_baselines"]["design_calm_band"]
    h21 = report["cells"]["vix25_h21"]["const_baselines"]["design_calm_band"]
    assert (h5["n"], h5["events"], h5["c"]) == (559, 17, 0.0304)
    assert (h21["n"], h21["events"], h21["c"]) == (553, 134, 0.2423)
    assert h5["window"] == ["2007-01-01", "2014-12-31"]
    jump = report["jump_support"]
    assert jump["design_max_log_jump"] == pytest.approx(0.496, abs=1e-3)
    assert [e["session"] for e in jump["live_exceedances"]] == ["2026-11-05"]
    assert jump["live_exceedances"][0]["design_days_at_or_above"] == 0


def test_recomputed_probabilities_match_ledger(report):
    assert report["p_recompute"]["checked"] > 0
    assert report["p_recompute"]["max_abs_delta"] <= 5e-7


# ---------------------------------------------------------------------------
# CLI 쓰기 규율 (tmp 사본, build_report 는 스텁)
# ---------------------------------------------------------------------------


def test_run_cli_dry_run_writes_nothing_and_append_is_idempotent(tmp_path, monkeypatch):
    root = research_root(tmp_path)
    stub = {"schema": "stub", "display_only": True, "notice": D.NOTICE}
    monkeypatch.setattr(D, "build_report", lambda r, as_of=None: dict(stub))
    exposures = root / "data/mts_research/ledgers/exposures.jsonl"
    derived = root / D.DERIVED_RELATIVE

    def args(append: bool) -> argparse.Namespace:
        return argparse.Namespace(as_of=None, append=append, report=None, kind=None, now=None)

    code, out = D.run_cli(root, args(False))
    assert code == 0 and out["mode"] == "dry_run" and out["ledger_appends"] == 0
    assert not exposures.exists() and not derived.exists()

    code, out = D.run_cli(root, args(True))
    assert code == 0 and out["derived_written"] is True and out["ledger_appends"] == 1
    first = derived.read_bytes()
    code, out = D.run_cli(root, args(True))
    assert out["derived_written"] is False and out["ledger_appends"] == 0
    assert derived.read_bytes() == first
    row = json.loads(exposures.read_text(encoding="utf-8").splitlines()[0])
    assert row["run_id"] == D.RUN_ID and row["purpose"] == "audit"


def test_run_cli_prerequisite_failure_is_fail_closed(tmp_path, monkeypatch):
    root = research_root(tmp_path)

    def boom(r, as_of=None):
        raise D.MtsV13DiagnosticsError("전제 부족")

    monkeypatch.setattr(D, "build_report", boom)
    code, out = D.run_cli(root, argparse.Namespace(as_of=None, append=True, report=None, kind=None, now=None))
    assert code == 4 and out["status"] == "PREREQUISITE_FAILED"
    assert not (root / D.DERIVED_RELATIVE).exists()
