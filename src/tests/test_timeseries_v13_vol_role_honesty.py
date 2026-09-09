"""V13-VOL 카드 — 역할 문구와 '읽는 법'이 화면에 없는 셀을 가리키지 않는다.

홀드아웃 부분 통과(2026-09-09)로 `vix25_h63` 이 표에서 내려갔다. 그런데도 카드가
"등록 질문 vix-25-90d 의 base rate 공급원입니다" 라고 계속 말하면, 독자는 남아 있는
다른 지평(21영업일)의 기준율을 그 질문 값으로 읽는다. 숫자를 숨기는 것만으로는
표시 정직성이 성립하지 않는다 — 문장도 같이 따라가야 한다.

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


def test_role_line_withdraws_when_the_mapped_cell_failed_holdout(node_available: None) -> None:
    html = _render(_payload())
    assert "base rate를 공급하지 않습니다" in html
    assert "공급원입니다" not in html, "떨어진 셀을 공급원이라 계속 말하면 안 된다"
    assert "이 질문에 대입하지 않습니다" in html
    # 대응 셀 숫자는 실제로 표에 없다 — 문장과 표가 같은 사실을 말한다
    assert "기준율 42%" in html, "통과 셀(rv_h21)은 그대로 표시"
    assert html.count("<b>기준율 ") == 3, "통과 3셀만 숫자를 싣는다"


def test_role_line_stays_when_the_mapped_cell_passed(node_available: None) -> None:
    payload = _payload(
        holdout_pass_cells=["vix25_h63"], holdout_fail_cells=[],
        publication={"display_tier": "t3_live_card", "holdout_status": "pass"},
    )
    payload["cells"]["vix25_h63"] = {
        "p": 0.2, "band80": [0.15, 0.26], "clim_base_rate": 0.42, "reliability": "weak",
    }
    html = _render(payload)
    assert "공급원입니다" in html
    assert "합치거나 평균내지 않습니다" in html
    assert "base rate를 공급하지 않습니다" not in html


def test_reading_guide_quotes_a_cell_that_is_actually_displayed(node_available: None) -> None:
    html = _render(_payload())
    # 대응 셀이 숨겨졌으니 표에 실린 셀을 인용해야 한다 — "기준율 —" 는 나오지 않는다
    assert '"기준율 —"' not in html
    assert '"기준율 6%"' in html and "21영업일 안에 25를 터치한" in html


def test_reading_guide_describes_the_event_of_the_cell_it_quotes(node_available: None) -> None:
    """VIX 셀이 전부 떨어지면 인용은 실현변동성 셀로 넘어가고 설명도 함께 바뀐다."""
    payload = _payload(
        holdout_pass_cells=["rv_h5", "rv_h21"],
        holdout_fail_cells=[
            "vix25_h5", "vix25_h21", "vix25_h63",
            "vix30_h5", "vix30_h21", "vix30_h63", "rv_h63",
        ],
    )
    payload["cells"].pop("vix25_h21")
    html = _render(payload)
    assert "과거 같은 실현변동성 수준에서" in html
    assert "16.9%(연율)를 넘은" in html
    assert "25를 터치한" not in html, "인용하지 않은 사건을 설명하면 안 된다"


def test_no_displayable_cell_leaves_no_dangling_example(node_available: None) -> None:
    payload = _payload(cells={}, holdout_pass_cells=[])
    html = _render(payload)
    assert "인용할 기준율이 없습니다" in html
    assert '"기준율 —"' not in html
