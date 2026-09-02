"""V10 CLI — 개발 반복 verb 두 개만 존재한다.

이 파일에는 개발 단계 밖의 어떤 평가 verb도 정의되지 않는다 — 루프 PRE-FLIGHT가
이 파일과 하네스를 grep으로 대조해 그 부재를 증명한다.
"""

from __future__ import annotations

import json
from pathlib import Path


def run_dev_backtest(root: Path, label: str) -> dict:
    from .pipeline import dev_backtest_timeseries_v10

    result = dev_backtest_timeseries_v10(root, experiment_label=label)
    return {
        "experiment_id": result["experiment_id"],
        "experiment_label": result["experiment_label"],
        "degenerate": result["degenerate"],
        "horizons": result["horizons"],
        "paired_long_horizon": result["paired_long_horizon"],
        "proxy_pass": result["proxy"]["pass"],
        "gate_margin": result["gate_margin"],
        "dual_vs_e0": result["dual_vs_e0"],
    }


def run_verify(root: Path) -> dict:
    from .pipeline import verify_timeseries_v10

    return verify_timeseries_v10(root)


def render(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
