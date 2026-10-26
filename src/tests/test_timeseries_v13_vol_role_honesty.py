"""V13-VOL 보조 문구 제거 뒤에도 통과 셀과 모바일 기본 지평은 보존한다.

소스 문자열이 아니라 렌더 결과를 node 로 실제 실행해 확인한다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")


def _render(payload: dict) -> str:
    """패널 렌더러만 잘라내 최소 스텁과 함께 실행한다."""
    head = SCRIPT.index("const V13_CELL_LABELS=")
    tail = SCRIPT.index("function bindTimeseriesV13VolInteractions(")
    program = (
        "const esc=s=>String(s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;',"
        "'>':'&gt;','\"':'&quot;'}[c]));\n"
        "const plainTerm=k=>k;\n"
        "const hasNumeric=v=>typeof v==='number'&&Number.isFinite(v);\n"
        "const DATA={questions:[]};\n"
        + SCRIPT[head:tail]
        + "\nconsole.log(JSON.stringify({html:renderTimeseriesV13VolPanel("
        + json.dumps(payload)
        + ")}));\n"
    )
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    return json.loads(completed.stdout)["html"]


def _payload(**over: object) -> dict:
    base = {
        "status": "live",
        "numbers_visible": True,
        "as_of": "2026-09-08",
        "publication": {"display_tier": "t3_live_card", "holdout_status": "partial"},
        "gate": {"design_gate_pass": True, "freshness_pass": True},
        "freshness": {"missing_sessions": 0, "max_missing_sessions": 1},
        "inputs": {"vix_close": 14.5, "rv21_ann": 0.129},
        "reference_question": {
            "id": "vix-25-90d", "cell": "vix25_h63", "divergence_threshold_pp": 15,
        },
        "holdout_pass_cells": ["vix25_h21", "rv_h5", "rv_h21"],
        "holdout_fail_cells": [
            "vix25_h5", "vix25_h63", "vix30_h5", "vix30_h21", "vix30_h63", "rv_h63",
        ],
        "cells": {
            "vix25_h21": {
                "p": 0.06, "band80": [0.04, 0.09], "clim_base_rate": 0.42,
                "episode_sample": "thin",
            },
            "rv_h5": {"p": 0.11, "band80": [0.09, 0.13], "clim_base_rate": 0.55},
            "rv_h21": {"p": 0.42, "band80": [0.35, 0.49], "clim_base_rate": 0.67},
        },
    }
    base.update(over)
    return base


@pytest.fixture(scope="module")
def node_available() -> None:
    try:
        subprocess.run(["node", "-v"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        pytest.skip("node 미설치")


def test_removed_role_copy_does_not_change_partial_holdout_cells(node_available: None) -> None:
    html = _render(_payload())
    assert "base rate를 공급하지 않습니다" not in html and "공급원입니다" not in html
    assert "이 질문에 대입하지 않습니다" not in html
    assert "기준율 42%" in html, "통과 셀(rv_h21)은 그대로 표시"
    assert html.count("<b>기준율 ") == 3, "통과 3셀만 숫자를 싣는다"


def test_removed_role_copy_does_not_change_passed_reference_cell(node_available: None) -> None:
    payload = _payload(
        holdout_pass_cells=["vix25_h63"], holdout_fail_cells=[],
        publication={"display_tier": "t3_live_card", "holdout_status": "pass"},
    )
    payload["cells"]["vix25_h63"] = {
        "p": 0.2, "band80": [0.15, 0.26], "clim_base_rate": 0.42, "reliability": "weak",
    }
    html = _render(payload)
    assert "공급원입니다" not in html
    assert "합치거나 평균내지 않습니다" not in html
    assert "base rate를 공급하지 않습니다" not in html
    assert "<b>기준율 20%</b>" in html
    assert "[80%: 15%–26%]" in html


def test_repeated_reading_guide_is_removed_while_actual_cell_remains(node_available: None) -> None:
    html = _render(_payload())
    assert '"기준율 —"' not in html
    assert '"기준율 6%"' not in html and "21영업일 안에 25를 터치한" not in html
    assert "<b>기준율 6%</b>" in html


def test_realized_volatility_cells_remain_without_reading_guide(node_available: None) -> None:
    payload = _payload(
        holdout_pass_cells=["rv_h5", "rv_h21"],
        holdout_fail_cells=[
            "vix25_h5", "vix25_h21", "vix25_h63",
            "vix30_h5", "vix30_h21", "vix30_h63", "rv_h63",
        ],
    )
    payload["cells"].pop("vix25_h21")
    html = _render(payload)
    assert "과거 같은 실현변동성 수준에서" not in html
    assert "16.9%(연율)를 넘은" not in html
    assert "25를 터치한" not in html
    assert "<b>기준율 11%</b>" in html and "<b>기준율 42%</b>" in html
    assert html.count("<b>기준율 ") == 2


def test_mobile_opens_on_a_horizon_that_has_numbers(node_available: None) -> None:
    """모바일은 지평 한 칸만 보인다 — 기본 지평이 비어 있으면 카드가 대시만 남는다.

    홀드아웃에서 63영업일 3셀이 모두 떨어진 뒤, 375px 화면에서 카드는 기본 탭(63)을 열고
    대시 세 개만 보여줬다. 통과 셀 3개는 다른 지평에 멀쩡히 있는데도.
    """
    html = _render(_payload())
    assert 'data-active-h="21"' in html, "숫자가 있는 지평으로 열어야 한다"
    assert 'data-v13-h-tab="21" aria-selected="true"' in html
    assert 'data-v13-h-tab="63" aria-selected="true"' not in html


def test_mobile_default_prefers_the_longest_horizon_that_has_numbers(node_available: None) -> None:
    """63 에 숫자가 있으면 설계 그대로 63 으로 연다 — 순서는 63→21→5."""
    payload = _payload(
        holdout_pass_cells=["vix25_h63"], holdout_fail_cells=[],
        publication={"display_tier": "t3_live_card", "holdout_status": "pass"},
    )
    payload["cells"]["vix25_h63"] = {
        "p": 0.2, "band80": [0.15, 0.26], "clim_base_rate": 0.42,
    }
    html = _render(payload)
    assert 'data-active-h="63"' in html
    assert 'data-v13-h-tab="63" aria-selected="true"' in html


def test_no_displayable_cell_leaves_no_dangling_example(node_available: None) -> None:
    payload = _payload(cells={}, holdout_pass_cells=[])
    html = _render(payload)
    assert "인용할 기준율이 없습니다" not in html
    assert '"기준율 —"' not in html
    assert "<b>기준율 " not in html


def test_hold_keeps_reasons_and_does_not_reuse_cells(node_available: None) -> None:
    payload = _payload(numbers_visible=False, gate={"reasons": ["required source VIX stale"]})
    html = _render(payload)
    assert "required source VIX stale" in html
    assert "<b>기준율 " not in html
    assert "v13-vol-table" not in html
