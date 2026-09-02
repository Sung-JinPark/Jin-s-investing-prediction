"""V10 헌법 테스트: 포크 항등·핀 감시·verb 부재·큐 정합·루프 가드."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v10.identity_test import check_source_pins, run_identity_check
from ai_fc.timeseries_v10.model_fork import (
    DistributionConfigV8 as ForkConfig,
    mixture_cdf_at_k,
    mixture_quantile_function_k,
    recalibration_levels_pav,
    weighted_midpoint_quantiles,
)
from ai_fc.timeseries_v10.pipeline import (
    EXPERIMENT_CONFIGS,
    load_contract_v10,
)
from ai_fc.timeseries_v10.state import build_state_series

ROOT = Path(__file__).resolve().parents[2]


def test_contract_queue_matches_the_code_map_and_pins_hold() -> None:
    contract = load_contract_v10(ROOT)
    queue = contract["development_protocol"]["preregistered_first_experiments"]
    assert list(queue) == list(EXPERIMENT_CONFIGS)
    assert check_source_pins(ROOT) == []


def test_tampered_source_pin_is_detected(tmp_path: Path) -> None:
    body = yaml.safe_load(
        (ROOT / "data/contracts/multivariate_timeseries_v10.yaml").read_text(encoding="utf-8"))
    target = tmp_path / "data/contracts/multivariate_timeseries_v10.yaml"
    target.parent.mkdir(parents=True)
    source = ROOT / "src/ai_fc/timeseries_v8/backtest.py"
    copied = tmp_path / "src/ai_fc/timeseries_v8/backtest.py"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(source.read_bytes() + b"\n# drift")
    body["source_pins"] = {
        "src/ai_fc/timeseries_v8/backtest.py":
            hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    target.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    errors = check_source_pins(tmp_path)
    assert errors and "drifted" in errors[0]


def test_forbidden_verbs_are_absent_from_cli_and_harness() -> None:
    # ★ 정지점: 개발 반복 밖의 평가 verb는 존재 자체가 금지 — 루프 PRE-FLIGHT와 동일 대조.
    for relative in ("src/ai_fc/timeseries_v10/cli.py", "tools/ralph_timeseries_v10.py"):
        text = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert "holdout" not in text and "sealed" not in text, relative


def test_loop_script_carries_the_safety_guards() -> None:
    script = (ROOT / "tools/v10_gate_loop.sh").read_text(encoding="utf-8")
    assert 'BR" = "main" ] && halt' in script.replace("$", ""), "main 거부"
    assert "sealed_baseline.hash" in script and "SEALED SOURCES CHANGED" in script
    assert "check_source_pins" in script, "계약 핀 매 사이클 대사"
    assert "1788393600" in script, "데드라인 2026-09-03 09:00 KST 기본값"
    assert "STOPLOSS_AT=12" in script
    assert "HOLDOUT-READY" in script and "awaiting user" in script
    assert "unset FRED_API_KEY" in script, "시크릿 미로드"
    assert 'grep -qiE "holdout|sealed"' in script, "verb 부재 PRE-FLIGHT"


def test_degenerate_config_flags_and_manifest_round_trip() -> None:
    assert ForkConfig().is_v10_degenerate()
    assert not ForkConfig(w1_kappa=0.5).is_v10_degenerate()
    manifest = ForkConfig(w2_mix_weights=(0.6, 0.3, 0.1)).as_manifest()
    assert manifest["w2_mix_weights"] == [0.6, 0.3, 0.1]
    assert manifest["w4_recal_map"] == "empirical"


def test_weighted_quantiles_and_k_mixture_are_deterministic_and_sane() -> None:
    rng = np.random.default_rng(3)
    values = rng.standard_normal(500)
    uniform = np.ones(500)
    baseline = np.sort(values)
    weighted = weighted_midpoint_quantiles(values, uniform, count=500)
    assert np.array_equal(weighted, baseline), "균등 가중 = 정렬 표본 그 자체"
    tilted = weighted_midpoint_quantiles(values, np.exp(values), count=500)
    assert tilted.mean() > baseline.mean(), "양수 꼬리 가중은 분포를 위로 민다"

    sets = [rng.standard_normal(300), rng.standard_normal(200) + 1.0,
            rng.standard_normal(100) - 1.0]
    levels = (np.arange(400) + 0.5) / 400
    mixed = mixture_quantile_function_k(sets, [0.5, 0.3, 0.2], levels=levels)
    assert np.all(np.diff(mixed) >= 0), "혼합 quantile 단조"
    cdf = mixture_cdf_at_k(sets, [0.5, 0.3, 0.2], value=0.0)
    assert 0.0 < cdf < 1.0
    with pytest.raises(Exception):
        mixture_quantile_function_k(sets, [0.5, 0.3, 0.3], levels=levels)


def test_pav_map_is_monotone_and_shrinks_toward_identity() -> None:
    rng = np.random.default_rng(5)
    history = np.clip(rng.beta(2, 1, 400), 0, 1)  # 상향 편중 PIT
    targets = (np.arange(200) + 0.5) / 200
    remapped = recalibration_levels_pav(history, target_levels=targets, shrinkage=0.5)
    assert np.all(np.diff(remapped) >= 0)
    assert np.all((remapped >= 0) & (remapped <= 1))
    full_identity = recalibration_levels_pav(history, target_levels=targets, shrinkage=1.0)
    assert np.allclose(full_identity, targets), "shrinkage 1.0 = 항등"


def test_state_series_warmup_is_declared_neutral_and_trailing_only() -> None:
    rng = np.random.default_rng(7)
    returns = 0.01 * rng.standard_normal(3000)
    primary, sensitivity = build_state_series(returns)
    assert np.all(primary[:2519] == 1.0), "기준선 미완성 구간 s≡1"
    assert primary[2520:].std() > 0
    assert np.all(sensitivity[:503] == 1.0)
    # trailing-only: 뒤쪽 데이터를 바꿔도 앞쪽 상태는 불변.
    perturbed = returns.copy(); perturbed[-1] += 0.05
    primary2, _ = build_state_series(perturbed)
    assert np.array_equal(primary[:-1], primary2[:-1])


def test_e0_fork_bit_identity_and_pins() -> None:
    result = run_identity_check(ROOT)
    assert result["ok"], result["errors"]
