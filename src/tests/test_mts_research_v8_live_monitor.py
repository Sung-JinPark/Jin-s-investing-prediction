"""V8 라이브 성적 감시기 L1~L4 (설계서 P3) — 오라클은 실제 저장소 데이터, 쓰기는 tmp 사본에만.

실데이터 오라클은 as_of=2026-11-09·now=2026-11-11T12Z 와 **해소 행 허용 목록(ORACLE_SAMPLE, 29행)** 으로
묶는다. 해소 원장에는 기록 시각이 없어 as_of 만으로는 표본이 고정되지 않는다 — 목표 ≤ as_of 인데
늦게 해소되는 쌍(2026-11-06 h1, 2026-10-09 h21)이 나중에 resolved_session ≤ as_of 로 들어온다.
허용 목록은 grid basis 와 XNAS matched 코호트를 같이 묶고, XNAS all_closed 는 목표 ≤ as_of·아카이브
knowledge_cutoff=now 로 고정된다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.mts_research import v8_live_monitor as M
from ai_fc.mts_research.artifacts import read_chain
from ai_fc.mts_research.monitor_thresholds import THRESHOLDS_RELATIVE, load_pinned_thresholds

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 11, 9)
GRID = "ledger_grid"
XNAS_MATCHED = "xnas_diagnostic_v1.matched_ledger_rows"
XNAS_ALL = "xnas_diagnostic_v1.all_closed_targets"
# 오라클 고정 표본 — (지평, 원점). 2026-11-11 기준 원장의 resolved_session ≤ 2026-11-09 해소 행 전부.
_ORIGINS_11 = ("2026-08-14", "2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25",
               "2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30")
ORACLE_SAMPLE = {1: _ORIGINS_11, 5: _ORIGINS_11, 21: _ORIGINS_11[:7]}
PROTECTED = [
    M.V8_FORECAST_LEDGER,
    M.V8_RESOLUTION_LEDGER,
    M.SEALED_LEDGER,
    Path("data/timeseries_v2/ledgers/market_observations.jsonl"),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_hashes() -> dict[str, str]:
    from ai_fc.timeseries_daily6m.contracts import model_code_hash as daily6m_hash
    from ai_fc.timeseries_v2.contracts import model_code_hash as v2_hash
    from ai_fc.timeseries_v8.contracts import model_code_hash as v8_hash

    return {"v8": v8_hash(ROOT), "v2": v2_hash(ROOT), "daily6m": daily6m_hash(ROOT)}


def _read(relative: Path) -> list[dict]:
    return [json.loads(line) for line in (ROOT / relative).read_text(encoding="utf-8").splitlines() if line.strip()]


def _oracle_resolution_ids() -> list[str]:
    """ORACLE_SAMPLE (지평, 원점) → 원장 resolution_id. 정확히 29행이 아니면 오라클 전제가 깨진 것."""
    origin_of = {f["forecast_id"]: f["origin"] for f in _read(M.V8_FORECAST_LEDGER)}
    wanted = {(h, o) for h, origins in ORACLE_SAMPLE.items() for o in origins}
    ids = [r["resolution_id"] for r in _read(M.V8_RESOLUTION_LEDGER)
           if (int(r["horizon"]), origin_of[r["forecast_id"]]) in wanted]
    assert len(ids) == len(wanted) == 29
    return ids


@pytest.fixture(scope="module")
def real():
    """실제 저장소에서 감시 보고서 1회(B4 전 쌍둥이 포함, 약 3분) — 읽기 전용."""
    before = {p: _sha(ROOT / p) for p in PROTECTED}
    ledger_before = (ROOT / M.LEDGER_RELATIVE).read_bytes() if (ROOT / M.LEDGER_RELATIVE).is_file() else None
    code_before = _code_hashes()
    thresholds, status = load_pinned_thresholds(ROOT)
    assert status == "ok"
    report = M._plain(M.run_monitor(ROOT, thresholds=thresholds, threshold_status=status, now=NOW, as_of=AS_OF,
                                    resolution_ids=_oracle_resolution_ids()))
    ledger_after = (ROOT / M.LEDGER_RELATIVE).read_bytes() if (ROOT / M.LEDGER_RELATIVE).is_file() else None
    return {"report": report, "thresholds": thresholds,
            "before": before, "after": {p: _sha(ROOT / p) for p in PROTECTED},
            "ledger_before": ledger_before, "ledger_after": ledger_after,
            "code_before": code_before, "code_after": _code_hashes()}


def _rep(real, basis, h):
    return real["report"]["bases"][basis]["representative"][f"h{h}"]


def _post(real, basis, h=1):
    return real["report"]["bases"][basis]["post_dated"][f"h{h}"]


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------


def test_poisson_binomial_dp_matches_monte_carlo():
    rng = np.random.default_rng(7)
    ps = rng.uniform(0.4, 0.75, size=8)
    draws = (rng.random((200_000, ps.size)) < ps).sum(axis=1)
    for k in range(ps.size + 1):
        assert abs(M.poisson_binomial_cdf(ps, k) - float(np.mean(draws <= k))) <= 0.005
    assert M.poisson_binomial_cdf(ps, ps.size) == pytest.approx(1.0)
    assert M.poisson_binomial_cdf(ps, -1) == 0.0
    with pytest.raises(M.V8LiveMonitorError):
        M.poisson_binomial_cdf([1.2], 0)


def test_rolling_skill_uses_last_k_and_reports_both_cis():
    rows = [{"origin": f"2026-0{m}-01", "h": 5, "crps_model": 1.0 + 0.1 * m, "crps_baseline": 1.5}
            for m in range(1, 10)]
    out = M.rolling_skill(rows, 5, 4)
    assert out["n"] == 4 and out["origins"] == [r["origin"] for r in rows[-4:]]
    expected = 1.0 - sum(r["crps_model"] for r in rows[-4:]) / sum(r["crps_baseline"] for r in rows[-4:])
    assert out["skill"] == pytest.approx(expected)
    assert out["ci90_iid"][0] <= out["skill"] <= out["ci90_iid"][1]
    assert out["ci90_block"] is not None and out["block_length"] == 1
    assert M.rolling_skill(rows, 21, 4)["n"] == 0


def test_location_z_and_neutral_twin():
    rows = [{"origin": "a", "h": 5, "crps_model": 1, "crps_baseline": 1, "z": z} for z in (-1.0, 0.5, 2.0)]
    assert M.location_z(rows) == pytest.approx(0.5)
    grid = np.linspace(-0.1, 0.1, 200)
    hs = np.linspace(-0.2, 0.3, 200)
    twin = M.location_neutral_twin(grid, hs)
    assert twin[100] == pytest.approx(hs[100])
    assert np.allclose(np.diff(twin), np.diff(grid))
    with pytest.raises(M.V8LiveMonitorError):
        M.location_z([])


def test_block_resample_is_circular_contiguous():
    index = M._resample_indices(8, 4, 50, 1)
    assert index.shape == (50, 8)
    first = index[:, :4]
    assert np.all((np.diff(first, axis=1) % 8) == 1)


def test_sealed_rolling_q05_matches_pinned_thresholds():
    """봉인 2019+ 연속 창(k=12/11/8) q05 재계산이 사전고정 임계와 ±0.1%p 이내."""
    thresholds, status = load_pinned_thresholds(ROOT)
    assert status == "ok"
    pinned = thresholds["v8_live"]
    for h, k in ((1, 12), (5, 11), (21, 8)):
        out = M.sealed_percentile(0.0, h, k, ROOT, metric="skill")
        assert abs(out["q05_q50_q95"][0] - pinned["L1_skill_q05"][str(h)]) <= 0.001
        z = M.sealed_percentile(0.0, h, k, ROOT, metric="z")
        assert abs(z["q05_q50_q95"][0] - pinned["L2_location_z_q05"][str(h)]) <= 0.01
        lo, hi = out["q05_ci90_block"]
        assert lo <= out["q05_q50_q95"][0] <= hi
    composite = M._sealed_composite_windows(ROOT, {1: 12, 5: 11, 21: 8})
    assert abs(float(np.quantile(composite, 0.05)) - pinned["L1_skill_q05"]["mean_1_5_21"]) <= 0.001
    assert M.sealed_percentile(0.0, 1, 12, ROOT, metric="pup_gap")["proxy"] is True


def test_b4_twin_unreconstructable_returns_none():
    """재현 검증 실패(HS 기준선 불일치·PIT 이력 없음)면 숫자 대신 None."""
    forecast = json.loads((ROOT / M.V8_FORECAST_LEDGER).read_text(encoding="utf-8").splitlines()[0])
    rng = np.random.default_rng(3)
    returns = rng.normal(0.0004, 0.012, size=3000)
    dates = [f"d{i}" for i in range(2999)] + [forecast["origin"]]
    context = M.B4TwinContext(
        dates=dates, index={d: i for i, d in enumerate(dates)}, returns=returns, path_count=2000,
        pit_min_matured=104, pit_maturity=68, pit_history={21: [], 63: []},
        unknown_lambda_origins=[], lambda_fallback_rule="test", history_end=None,
    )
    assert M.b4_pre_twin_h21_h63(forecast, ROOT, context=context) is None


def test_twin_report_without_context_carries_no_numbers():
    report = M._twin_report(None, {}, None, "bundle unavailable")
    assert report["status"] == "unreconstructable"
    assert "b4_pre" not in report and report["scoring_excluded"] is True


def test_twin_report_missing_origin_fails_closed():
    """번들 밖 원점이면 _twin_grids 예외가 보고서 전체를 죽이지 않고 unreconstructable 로 닫는다."""
    from types import SimpleNamespace

    forecast = _read(M.V8_FORECAST_LEDGER)[0]
    context = M.B4TwinContext(
        dates=["d0"], index={"d0": 0}, returns=np.zeros(1), path_count=10, pit_min_matured=104,
        pit_maturity=68, pit_history={21: [], 63: []}, unknown_lambda_origins=[], lambda_fallback_rule="test",
        history_end=None,
    )
    report = M._twin_report(SimpleNamespace(forecasts=[forecast]), {}, context, None)
    assert report["status"] == "unreconstructable" and "b4_pre" not in report
    assert "번들에 없다" in report["reason"]


def test_alarm_label_order():
    assert M._alarm_label([], {"h5": "normal", "h21": "insufficient"}) == M.LABEL_NORMAL
    assert M._alarm_label([], {"h5": "insufficient"}) == "표본 부족(insufficient)"
    assert M._alarm_label([], {}) == "표본 부족(insufficient)"
    assert M._alarm_label([], {"h63": "no_pinned_threshold"}) == "사전고정 임계 없음"
    assert M._alarm_label([{"label": "경계 이탈(단일 에피소드)"}], {"h5": "breach"}) == "경계 이탈(단일 에피소드)"


def test_resolution_allowlist_missing_id_fails_closed():
    rows = [{"resolution_id": "a", "resolved_session": "2026-11-02"}]
    assert M._bounded_resolutions(rows, AS_OF, None) == rows
    assert M._bounded_resolutions(rows, AS_OF, frozenset({"a"})) == rows
    with pytest.raises(M.V8LiveMonitorError):
        M._bounded_resolutions(rows, AS_OF, frozenset({"a", "b"}))


def test_late_resolution_does_not_move_pinned_sample(monkeypatch):
    """원장 성장 재연: 2026-11-06 h1(목표 11-09)이 늦게 해소돼 들어와도 허용 목록 표본은 그대로."""
    from ai_fc.mts_research import v8_xnas_labels as X

    forecast = next(f for f in _read(M.V8_FORECAST_LEDGER) if f["origin"] == "2026-11-06")
    synthetic = {"resolution_id": f"{forecast['forecast_id']}-h1-synthetic", "forecast_id": forecast["forecast_id"],
                 "origin": "2026-11-06", "horizon": 1, "resolved_session": "2026-11-09", "actual_log_return": 0.0,
                 "model_crps": 0.0, "baseline_crps": 0.0, "covered_p10_p90": True, "covered_p25_p75": True,
                 "direction_correct": False, "p_up": 0.5}  # 합성 행 — 점수 필드는 형식만(감시기는 grid 로 재계산)
    original = X._read_jsonl

    def grown(root, relative):
        rows = original(root, relative)
        return rows + [dict(synthetic)] if Path(relative) == M.V8_RESOLUTION_LEDGER else rows

    monkeypatch.setattr(M, "_read_jsonl", grown)
    monkeypatch.setattr(X, "_read_jsonl", grown)
    ids = _oracle_resolution_ids()
    pinned = M._load_context(ROOT, now=NOW, as_of=AS_OF, resolution_ids=frozenset(ids))
    loose = M._load_context(ROOT, now=NOW, as_of=AS_OF)
    assert len(pinned.resolutions) == 29 and len(loose.resolutions) == 30
    assert max(r["origin"] for r in pinned.resolutions) == "2026-10-30"
    assert (forecast["forecast_id"], 1) not in pinned.resolved_keys
    matched = M._xnas_rows(pinned, matched_only=True)
    assert all(r.origin != "2026-11-06" for r in matched)
    assert any(r.origin == "2026-11-06" for r in M._xnas_rows(loose, matched_only=True))
    assert pinned.sample_bound["resolution_allowlist_n"] == 29


# ---------------------------------------------------------------------------
# 실데이터 오라클
# ---------------------------------------------------------------------------


def test_fixed_output_fields(real):
    report = real["report"]
    assert report["status"] == "ok" and report["threshold_status"] == "ok"
    assert report["notice"] == "참고 의견, 매매 신호 아님"
    assert report["display_only"] is True and report["scoring_excluded"] is True
    assert report["network_fetch_enabled"] is False
    assert report["as_of_session"] == "2026-11-09"
    assert (report["n"], report["n_origins"]) == (29, 11)
    assert report["n_dates"] > 0 and isinstance(report["single_episode"], bool)
    assert report["monitor_id"] == "v8lm-2026-10-30-v1"
    assert report["label_basis_mixing"] == "prohibited"
    bound = report["disclosures"]["sample_bound"]
    assert bound["resolution_allowlist_n"] == 29 and "knowledge_cutoff ≤ now" in bound["forecasts"]
    h1 = _post(real, GRID)["L1"]
    assert h1["threshold_window_k"] == 12 and h1["threshold_window_matches_n"] is False
    composite = report["bases"][GRID]["composite_mean_1_5_21"]
    assert composite["window_k_by_h"] == {"h1": 12, "h5": 11, "h21": 8}
    assert isinstance(composite["below_q05_information_only"], bool)


def test_ledger_grid_basis_oracle(real):
    assert _post(real, GRID)["L1"]["skill"] == pytest.approx(-0.05426, abs=5e-5)
    assert _post(real, GRID)["n"] == 11
    assert _rep(real, GRID, 5)["L1"]["skill"] == pytest.approx(0.00682, abs=5e-5)
    assert _rep(real, GRID, 5)["n"] == 11
    assert _rep(real, GRID, 21)["L1"]["skill"] == pytest.approx(0.01554, abs=5e-5)
    assert _rep(real, GRID, 21)["n"] == 7 and _rep(real, GRID, 21)["state"] == "insufficient"


def test_xnas_basis_oracle_and_shock_sensitivity(real):
    assert _rep(real, XNAS_MATCHED, 5)["L1"]["skill"] == pytest.approx(-0.0073, abs=5e-5)
    assert _rep(real, XNAS_MATCHED, 21)["L1"]["skill"] == pytest.approx(-0.0018, abs=5e-5)
    shock = _rep(real, XNAS_MATCHED, 5)["sensitivity"]["ex_shock_window"]
    assert shock["excluded"] == ["2026-10-30"] and shock["n"] == 10
    assert shock["skill"] == pytest.approx(0.0035, abs=5e-5)
    assert _rep(real, XNAS_ALL, 21)["L1"]["skill"] == pytest.approx(-0.0302, abs=5e-4)
    assert real["report"]["shock_days"] == ["2026-11-05"] and real["report"]["single_episode"] is True


def test_location_decomposition_identity(real):
    for basis in (GRID, XNAS_MATCHED, XNAS_ALL):
        for group in ("representative", "post_dated"):
            for block in real["report"]["bases"][basis][group].values():
                d = block["decomposition"]
                assert d["loss_vs_hs"] == pytest.approx(d["delta_loc"] + d["delta_shape"], abs=1e-12)
                assert d["loss_vs_hs"] == pytest.approx(-block["L1"]["skill"], abs=1e-12)


def test_poisson_binomial_h21_tail(real):
    pb = _rep(real, XNAS_ALL, 21)["L4"]["poisson_binomial"]
    assert pb["p_le_observed"] == pytest.approx(0.10, abs=0.01)
    assert pb["method"] == "exact_dp_convolution"


def test_h1_only_in_post_dated_block(real):
    report = real["report"]
    assert report["representative_horizons"] == [5, 21, 63] and report["post_dated_horizons"] == [1]
    for basis in (GRID, XNAS_MATCHED, XNAS_ALL):
        assert "h1" not in report["bases"][basis]["representative"]
        assert "h1" in report["bases"][basis]["post_dated"]
        assert report["bases"][basis]["post_dated"]["h1"]["breaches"] == []
    assert report["alarm"]["states"].keys() == {"h5", "h21"}
    assert report["post_dated_label"] == "pseudo-OOS(사전 기록 아님)"


def test_acceptance_no_alarm_h1_near_tail(real):
    report = real["report"]
    assert report["alarm"]["breaches"] == []
    assert report["alarm"]["label"] == "정상 범위(검정력 낮음)"
    h1 = _post(real, GRID)
    assert h1["state"] == "near_tail" and h1["information_flags"] == ["near_tail"]
    assert h1["L1"]["sealed"]["percentile"] <= 0.10
    disclosures = report["disclosures"]
    assert disclosures["model_code_hash"]["live"] == ["869418cc"]
    assert disclosures["model_code_hash"]["sealed"] == "8361899f"
    assert disclosures["model_code_hash"]["identity_replay"]["v8_tier1_identity"] is True
    assert disclosures["mde"]["skill_n12"] == -0.08
    assert "in-sample" in disclosures["in_sample"]
    assert "operational_gate" in disclosures["operational_gate"]


def test_b4_pre_twin_reconstructs_ledger(real):
    twin = real["report"]["twins"]["b4_pre_h21_h63"]
    assert twin["status"] == "reconstructed"
    verification = twin["verification"]
    assert verification["failures"] == [] and verification["n_checked"] == 24
    assert verification["hs_mae_observed_max"] <= M.TWIN_HS_MAE_MAX
    assert verification["grid_max_abs_observed_max"] <= M.TWIN_GRID_MAX_ABS
    scored = twin["b4_pre"]["h21"]["scored"]
    assert scored[XNAS_ALL]["skill_post_recon"] == pytest.approx(-0.0302, abs=0.001)
    assert scored[GRID]["skill_ledger_grid"] == pytest.approx(0.01554, abs=5e-5)
    h21 = twin["b4_pre"]["h21"]
    assert h21["p_up_ledger_mean"] > h21["p_up_pre_mean"]  # B4 가 p_up 을 올린다(§1.1 사슬)
    assert twin["scoring_excluded"] is True


def test_no_mixed_basis_average(real):
    text = json.dumps(real["report"], ensure_ascii=False)
    for basis in (GRID, XNAS_MATCHED, XNAS_ALL):
        assert real["report"]["bases"][basis]["composite_mean_1_5_21"]["representative"] is False
    assert "mixed" not in text and "basis_mean" not in text


def test_inputs_and_sealed_code_untouched(real):
    assert real["before"] == real["after"]
    assert real["ledger_before"] == real["ledger_after"]
    assert real["code_before"] == real["code_after"]


# ---------------------------------------------------------------------------
# 원장·CLI (tmp 사본)
# ---------------------------------------------------------------------------


def test_append_idempotent_on_tmp_copy(real, tmp_path):
    row = M.ledger_row(real["report"])
    first = M.append_monitor(tmp_path, row)
    assert first["appended"] == 1
    again = M.append_monitor(tmp_path, row)
    assert again == {"appended": 0, "identity": row["monitor_id"], "status": "identical", "rows": 1}
    changed = M.append_monitor(tmp_path, {**row, "n": -1})
    assert changed["appended"] == 0 and changed["status"] == "identity_exists_body_differs"
    chain = read_chain(tmp_path, M.LEDGER_RELATIVE)
    assert len(chain) == 1 and chain[0]["notice"] == "참고 의견, 매매 신호 아님"
    assert chain[0]["scoring_excluded"] is True and chain[0]["display_only"] is True
    path = M.write_derived(tmp_path, real["report"])
    assert json.loads(path.read_text(encoding="utf-8"))["monitor_id"] == row["monitor_id"]


def test_threshold_hash_mismatch_nulls_everything(tmp_path):
    target = tmp_path / THRESHOLDS_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads((ROOT / THRESHOLDS_RELATIVE).read_text(encoding="utf-8"))
    payload["v8_live"]["minimum_origins"] = 3
    target.write_text(json.dumps(payload), encoding="utf-8")
    args = argparse.Namespace(as_of=None, append=True, report=None, kind=None, now=None)
    code, out = M.run_cli(tmp_path, args)
    assert code == 2
    report = out["report"]
    assert report["status"] == "threshold_hash_mismatch"
    assert report["bases"] is None and report["alarm"] is None and report["n"] is None
    assert not (tmp_path / M.LEDGER_RELATIVE).exists()


def test_missing_threshold_file_is_null(tmp_path):
    code, out = M.run_cli(tmp_path, argparse.Namespace(as_of=None, append=False, report=None, kind=None, now=None))
    assert code == 2 and out["report"]["status"] == "threshold_file_missing"


def test_cli_verb_registered():
    from ai_fc.mts_research.cli import RESEARCH_TOOLS

    assert RESEARCH_TOOLS["v8-live-monitor"] == ("ai_fc.mts_research.v8_live_monitor", "run_cli")
    source = Path(M.__file__).read_text(encoding="utf-8")
    assert "timeseries_v14" not in source
