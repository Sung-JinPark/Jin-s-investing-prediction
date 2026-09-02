"""E0 비트동일 검사 — 포크(퇴화 파라미터)가 V8 원본과 완전히 같은 숫자를 낸다.

합성 데이터에서 같은 정체성 좌표·같은 시드로 원본 walk_forward와 포크 walk_forward를
실행해 전 원점·전 지평의 CRPS·분위수·PIT 관련 산출이 부동소수점까지 동일함을 단언한다.
루프는 매 실험 전 이 검사를 통과하지 못하면 그 실험을 무효로 한다.  원본 2파일의
sha256이 계약 source_pins와 일치하는지도 함께 대조한다 (사본 드리프트 감시).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v10.yaml")


def check_source_pins(root: Path) -> list[str]:
    contract = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    errors: list[str] = []
    for relative, expected in (contract.get("source_pins") or {}).items():
        path = root / relative
        if not path.is_file():
            errors.append(f"pinned source missing: {relative}")
            continue
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != expected:
            errors.append(f"pinned source drifted: {relative}")
    return errors


def _synthetic_inputs(sessions: int = 1050):
    rng = np.random.default_rng(11)
    day = np.datetime64("2003-01-06")
    dates: list[str] = []
    while len(dates) < sessions:
        if np.is_busday(day):
            dates.append(str(day))
        day += np.timedelta64(1, "D")
    endog = np.column_stack([
        0.01 * rng.standard_normal(sessions),
        0.01 * rng.standard_normal(sessions),
    ])
    exog = rng.standard_normal((sessions, 3))
    return tuple(dates), endog, exog


def run_identity_check(root: Path, *, path_count: int = 200) -> dict:
    """Return {'ok': bool, 'errors': [...]} — bit-identity plus source pins."""
    from ai_fc.timeseries_v8.backtest import (
        walk_forward_dev_backtest_v8 as original_walk,
    )
    from ai_fc.timeseries_v8.model import DistributionConfigV8 as OriginalConfig
    from .backtest_fork import walk_forward_dev_backtest_v8 as fork_walk
    from .model_fork import DistributionConfigV8 as ForkConfig

    errors = check_source_pins(root)
    dates, endog, exog = _synthetic_inputs()
    champion = dict(
        fhs_horizons=(21, 63),
        blend_weight_by_horizon={1: 1.0, 5: 1.0, 21: 0.75, 63: 0.75},
        pit_recalibration_shrinkage=0.5,
    )
    common = dict(
        dates=dates, endog=endog, exog=exog,
        endog_names=("nasdaq_return", "vix_change"),
        exog_names=("f1", "f2", "f3"),
        model_id="shadow.mf_dfm_varx_regime_width_v10",
        model_version=10,
        outer_start=dates[900], outer_end=dates[-1],
        path_count=path_count, pit_min_matured=104,
    )
    original_scores, original_summary = original_walk(
        config=OriginalConfig(**champion), **common,
    )
    fork_scores, fork_summary = fork_walk(config=ForkConfig(**champion), **common)
    if len(original_scores) != len(fork_scores) or not original_scores:
        errors.append("identity: score row count mismatch or empty")
    else:
        for left, right in zip(original_scores, fork_scores):
            if (left.date, left.horizon) != (right.date, right.horizon):
                errors.append(f"identity: origin misalignment at {right.date}")
                break
            if left.model_crps != right.model_crps:  # bit-equal, not approx
                errors.append(
                    f"identity: CRPS diverged at {right.date} h{right.horizon}"
                )
                break
        original_h = json.dumps(original_summary.get("horizons"), sort_keys=True)
        fork_h = json.dumps(fork_summary.get("horizons"), sort_keys=True)
        if original_h != fork_h:
            errors.append("identity: summary horizons diverged")
    return {"ok": not errors, "errors": errors}
