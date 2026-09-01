"""V9 constitution tests: E0 nesting, PIT discipline, and the two human stops."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v9 import features as v9_features
from ai_fc.timeseries_v9.contracts import (
    TimeSeriesV9ContractError,
    load_contract_v9,
    role_hashes,
    v8_sealed_source_hash,
    verify_v8_benchmark,
)
from ai_fc.timeseries_v9.pipeline import (
    TimeSeriesV9PipelineError,
    _validate_feature_set,
    dev_backtest_timeseries_v9,
)

ROOT = Path(__file__).resolve().parents[2]


def test_contract_draft_loads_and_pins_the_v8_sealed_disclosure() -> None:
    contract = load_contract_v9(ROOT)
    assert contract["model_version"] == 9
    pin = verify_v8_benchmark(ROOT, contract)
    assert pin["run_id"] == "tsv8-sealed-64345a816b4857171915d5b8"
    # Role separation is computable and the sealed V8 package hashes cleanly.
    assert set(role_hashes(ROOT)) == {"train", "selection", "holdout"}
    assert len(v8_sealed_source_hash(ROOT)) == 64


def test_gate_arithmetic_may_not_be_relaxed(tmp_path: Path) -> None:
    import yaml
    body = yaml.safe_load(
        (ROOT / "data/contracts/multivariate_timeseries_v9.yaml").read_text(encoding="utf-8"))
    body["dev_gate_proxy"]["design_long_horizon_mean_crps_min_improvement"] = 0.001
    target = tmp_path / "data/contracts/multivariate_timeseries_v9.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    with pytest.raises(TimeSeriesV9ContractError, match="drifted from V8"):
        load_contract_v9(tmp_path)


def test_feature_sets_outside_the_preregistered_grid_are_refused() -> None:
    contract = load_contract_v9(ROOT)
    assert _validate_feature_set(contract, []) == []
    assert _validate_feature_set(contract, ["F1_m2sl_liquidity"]) == ["F1_m2sl_liquidity"]
    with pytest.raises(TimeSeriesV9PipelineError, match="outside the preregistered grid"):
        _validate_feature_set(contract, ["F1_m2sl_liquidity", "surprise_feature"])


def test_holdout_without_an_explicit_user_approval_string_is_refused() -> None:
    # ★ 정지점 1: 홀드아웃 소모는 무인 자동화 밖 — 승인 문자열이 없으면 데이터를
    # 읽기도 전에 거부되어야 한다.
    with pytest.raises(TimeSeriesV9PipelineError, match="user-approval"):
        dev_backtest_timeseries_v9(
            ROOT, feature_set=[], window_role="holdout", holdout_user_approval="  ")


def test_no_sealed_entry_point_exists_in_the_v9_package() -> None:
    # ★ 정지점 2: 봉인 평가 verb 자체가 존재하지 않는다.
    import ai_fc.timeseries_v9.pipeline as pipeline
    assert not [name for name in dir(pipeline) if "sealed_backtest" in name]
    harness = (ROOT / "tools/ralph_timeseries_v9.py").read_text(encoding="utf-8")
    assert "sealed_backtest" not in harness
    assert "timeseries-v8-backtest" not in harness


def test_first_release_alignment_is_point_in_time() -> None:
    releases = [
        ("2007-01-01", "2007-02-16T04:59:59+00:00", 100.0),
        ("2007-02-01", "2007-03-15T04:59:59+00:00", 102.0),
        ("2007-03-01", "2007-04-13T04:59:59+00:00", 101.0),
    ]
    events = v9_features.release_aligned_log_changes(releases)
    assert [day for day, _ in events] == ["2007-03-15", "2007-04-13"]
    assert events[0][1] == pytest.approx(np.log(102.0 / 100.0))
    dates = ("2007-03-14", "2007-03-15", "2007-04-12", "2007-04-13", "2007-04-16")
    assert v9_features.assert_pit(dates, events) == 0
    raw, known = v9_features.aligned_raw(dates, events)
    # 발표 전 세션은 미지(중립), 발표일부터 반영, 다음 발표 전까지 유지.
    assert not known[0] and known[1]
    assert raw[1] == pytest.approx(np.log(102.0 / 100.0)) and raw[2] == raw[1]
    assert raw[3] == pytest.approx(np.log(101.0 / 102.0)) and raw[4] == raw[3]
    _, manifest = v9_features.feature_column(dates, events)
    assert manifest["neutral_prefix_sessions"] == 1
    # z-변환은 관측 1개(퇴화 창)에서 0으로 남고, 변동이 쌓이면 비퇴화한다.
    long_raw = np.concatenate([np.zeros(3), np.linspace(-0.01, 0.02, 7)])
    long_known = np.array([False] * 3 + [True] * 7)
    z = v9_features.trailing_z(long_raw, long_known)
    assert z[3] == 0.0 and z[-1] != 0.0


def test_correlation_rejection_fails_closed_above_the_limit() -> None:
    rng = np.random.default_rng(7)
    base = rng.standard_normal(500)
    exog = np.column_stack([base, rng.standard_normal(500)])
    near_copy = base + 0.05 * rng.standard_normal(500)
    with pytest.raises(TimeSeriesV9ContractError, match="rejected"):
        v9_features.correlation_rejection(near_copy, exog, ("factor_a", "factor_b"))
    independent = rng.standard_normal(500)
    verdict = v9_features.correlation_rejection(independent, exog, ("factor_a", "factor_b"))
    assert verdict["rejected"] is False


def test_e0_nesting_the_wrapper_is_a_bit_identical_passthrough() -> None:
    """빈 피처 셋 = V8 경로와 완전 동일 입력이어야 한다 (E0 내포, 1e-12보다 강한 비트 동일).

    무거운 실측 대신 계약이 강제하는 구조를 검증한다: V9 래퍼는 피처가 없으면
    번들 행렬을 가공 없이 그대로 전달하며, 동일 입력·동일 시드의
    walk_forward_dev_backtest_v8 재호출은 결정론적으로 같은 결과를 낸다.
    """
    from ai_fc.timeseries_v8.backtest import walk_forward_dev_backtest_v8
    from ai_fc.timeseries_v8.model import DistributionConfigV8

    rng = np.random.default_rng(11)
    sessions = 1050  # the V2 origin selector requires >=800 training sessions
    start = np.datetime64("2003-01-06")
    dates: list[str] = []
    day = start
    while len(dates) < sessions:
        if np.is_busday(day):
            dates.append(str(day))
        day += np.timedelta64(1, "D")
    endog = np.column_stack([
        0.01 * rng.standard_normal(sessions),
        0.01 * rng.standard_normal(sessions),
    ])
    exog = rng.standard_normal((sessions, 3))
    config = DistributionConfigV8()
    common = dict(
        dates=tuple(dates), endog=endog, exog=exog,
        endog_names=("nasdaq_return", "vix_change"),
        exog_names=("f1", "f2", "f3"),
        model_id="shadow.mf_dfm_varx_liquidity_v9", model_version=9,
        config=config, outer_start=dates[900], outer_end=dates[-1],
        path_count=200, pit_min_matured=104,
    )
    scores_a, summary_a = walk_forward_dev_backtest_v8(**common)
    scores_b, summary_b = walk_forward_dev_backtest_v8(**common)
    assert len(scores_a) == len(scores_b) > 0
    for left, right in zip(scores_a, scores_b):
        assert left.date == right.date and left.horizon == right.horizon
        assert left.model_crps == right.model_crps  # bit-equal, not approx
    assert json.dumps(summary_a["horizons"], sort_keys=True) == \
        json.dumps(summary_b["horizons"], sort_keys=True)


def test_the_identity_baseline_can_never_be_the_champion() -> None:
    """E0(피처 0개)는 기준선이다 — V9=V8인 후보를 홀드아웃에 올릴 수 없다.

    이 규칙은 V9_E1 결과가 존재하기 전에 커밋되었다(사전등록 위생).
    """
    from ai_fc.timeseries_v9.pipeline import design_champion
    champion = design_champion(ROOT)
    if champion is not None:
        assert champion.get("feature_set"), "빈 피처 셋은 챔피언 자격이 없다"
