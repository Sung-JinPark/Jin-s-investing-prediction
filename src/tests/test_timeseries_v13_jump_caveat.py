"""V13-D16 점프 위험 미표현 caveat — 계약 전사값·live 일 때만·라벨은 게이트가 아님·라벨+tooltip 규약."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_fc import timeseries_v13_vol_display as display
from ai_fc.timeseries_v13 import contracts as C

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
STYLE = (ROOT / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")
DERIVED = ROOT / "data/mts_research/derived/v13_live_diagnostics.json"


def _contract() -> dict:
    return C.load_contract_v13(ROOT)


def _live_latest() -> dict:
    cells = {}
    for name in C.CELL_ORDER:
        h = int(name.rsplit("h", 1)[1])
        cells[name] = {"model": "persistence_pb", "p": 0.42, "band80": [0.38, 0.46], "clim_base_rate": 0.31,
                       "reliability": "good", "h": h}
    return {"status": "live", "as_of": "2026-11-10", "inputs": {"vix_close": 18.0}, "cells": cells,
            "gate": {"design_gate_pass": True, "armed": True, "coefficients_pinned": True, "freshness_pass": True,
                     "reasons": []}}


def _project(contract: dict, latest: dict | None) -> dict:
    return display.build_projection(latest, tier="t3_live_card", contract=contract, freshness={"status": "fresh"},
                                    pin_ok=True, pin_reason=None, armed_now=True,
                                    applications={"status": "ok", "rows": [], "by_id": {}, "demoted": [],
                                                  "t7": None, "error": None})


def test_contract_caveat_matches_research_fact() -> None:
    if not DERIVED.is_file():
        pytest.skip("연구 파생 파일 없음")
    jump = json.loads(DERIVED.read_text(encoding="utf-8"))["jump_support"]
    facts = _contract()["live_display_caveats"]["caveats"][0]["facts"]
    first = jump["live_exceedances"][0]
    assert facts["design_max_vix_log_jump"] == jump["design_max_log_jump"] == 0.496
    assert facts["design_max_session"] == jump["design_max_session"] == "2007-02-27"
    assert facts["live_exceedance_session"] == first["session"] == "2026-11-05"
    assert facts["live_exceedance_log_jump"] == first["log_jump"] == 0.5286
    assert facts["live_exceedance_vix"] == [first["from"], first["to"]]
    assert facts["design_days_at_or_above"] == first["design_days_at_or_above"] == 0
    pre = jump["pre_jump_origins"][0]
    assert facts["pre_jump_origin"] == {"origin": pre["origin"], "vix_close": pre["vix_close"],
                                        "p_vix25_h5": pre["p_vix25_h5"]}
    assert facts["single_episode"] is True and jump["single_episode"] is True


def test_projection_carries_caveat_only_when_live() -> None:
    contract = _contract()
    live = _project(contract, _live_latest())
    label = contract["live_display_caveats"]["caveats"][0]["label"]
    assert live["status"] == "live" and live["caveats"][0]["label"] == label
    assert live["caveats"][0]["hint_key"] == "v13_jump_hint"
    hold = _project(contract, {**_live_latest(), "status": "hold"})
    assert hold["status"] == "hold" and "caveats" not in hold
    assert "caveats" not in _project(contract, None)


def test_invalid_caveat_contract_does_not_hide_numbers() -> None:
    contract = json.loads(json.dumps(_contract(), default=str))
    contract["live_display_caveats"]["caveats"][0]["label"] = "  "
    proj = _project(contract, _live_latest())
    assert proj["status"] == "live" and proj["cells"] and "caveats" not in proj
    assert "caveat_contract_invalid" in proj["gate"]["reasons"]
    del contract["live_display_caveats"]["caveats"][0]["facts"]["design_max_session"]
    contract["live_display_caveats"]["caveats"][0]["label"] = "x"
    proj = _project(contract, _live_latest())
    assert proj["status"] == "live" and "caveat_contract_invalid" in proj["gate"]["reasons"]


def _panel_source() -> str:
    start = SCRIPT.index("function renderTimeseriesV13VolPanel(")
    end = SCRIPT.index("function bindTimeseriesV13VolInteractions(")
    return SCRIPT[start:end]


def _node(program: str) -> str:
    completed = subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(completed.stdout)["html"]


STUBS = ("const esc=s=>String(s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));\n"
         "const plainTerm=k=>k;const num=String;const v13Pct=v=>String(v);\n"
         "const hasNumeric=v=>typeof v==='number'&&Number.isFinite(v);\n"
         "const V13_CELL_LABELS={vix25:'VIX 25',vix30:'VIX 30',rv:'RV'};\n")


def _live_forward_renderer() -> str:
    renderer = re.search(r"function renderV13LiveForward\([\s\S]+?\n}\n", SCRIPT)
    assert renderer
    return renderer.group(0)


def test_panel_renders_jump_chip_from_payload() -> None:
    if shutil.which("node") is None:
        pytest.skip("node 미설치")
    proj = _project(_contract(), _live_latest())
    proj = json.loads(json.dumps(proj, default=str))
    proj["numbers_visible"] = True
    program = (STUBS + _live_forward_renderer() + _panel_source()
               + "\nconsole.log(JSON.stringify({html:renderTimeseriesV13VolPanel(" + json.dumps(proj) + ")}));\n")
    html = _node(program)
    assert html.count('class="v13-jump-chip"') == 1
    assert 'title="v13_jump_hint"' in html and proj["caveats"][0]["label"] in html
    proj.pop("caveats")
    program = (STUBS + _live_forward_renderer() + _panel_source()
               + "\nconsole.log(JSON.stringify({html:renderTimeseriesV13VolPanel(" + json.dumps(proj) + ")}));\n")
    assert "v13-jump-chip" not in _node(program)


def test_panel_copy_rules_still_hold() -> None:
    src = _panel_source()
    assert "v13-caveat" not in src and "${caveat}" not in src
    assert src.count("${head}") == 2
    assert "${head}${jumpChips}${hTabs}${table}${liveForward}" in src
    term = re.search(r"  v13_jump_hint:'([^']*)'", SCRIPT)
    assert term and "단일 사례" in term.group(1) and "늦게 따라옵니다" not in term.group(1)
    # 사실만 — 단일 사례로 방향(과소)을 시사하지 않는다(리뷰 비차단 8: 같은 VIX 구간 설계창 빈도 0/133, 모형 p 가 그보다 높다)
    assert "낮게" not in term.group(1) and "과소" not in term.group(1)
    assert ".v13-jump-chip{" in STYLE and "min-width:0" in STYLE.split(".v13-jump-chip{", 1)[1].split("}", 1)[0]
    assert ".v13-lf-demoted{" in STYLE
    assert "2026-11-05" not in src, "라벨 날짜는 페이로드에서 온다(하드코딩 금지)"


def test_live_forward_marks_demoted_and_pending_without_new_columns() -> None:
    if shutil.which("node") is None:
        pytest.skip("node 미설치")
    base = {"matured": 60, "minimum": 60, "progress": 1, "events": 20, "brier_model": 0.12,
            "brier_climatology": 0.2, "bss": 0.4, "claim_blocked": False, "claim_block_reasons": []}
    cells = [{**base, "cell": "vix25_h21", "live_verdict": {"checkpoint": 60, "outcome": "demotion_applied"}},
             {**base, "cell": "rv_h5", "verdict_pending_checkpoint": 60, "live_verdict": None},
             {**base, "cell": "rv_h21", "live_verdict": None, "verdict_pending_checkpoint": None}]
    lf = {"status": "accumulating", "minimum": 60, "matured_total": 180, "origins_recorded": 70,
          "events_total": 60, "cells": cells}
    program = STUBS + _live_forward_renderer() + "\nconsole.log(JSON.stringify({html:renderV13LiveForward(" \
        + json.dumps(lf) + ",[])}));\n"
    html = _node(program)
    assert "라이브 강등(60)" in html and "판정 대기(60)" in html
    assert html.count("v13-lf-demoted") == 1
    thead = html[html.index("<thead>"):html.index("</thead>")]
    assert thead.count('<th scope="col">') == 6
    assert "체크포인트 기록 있음" in html
    lf["cells"] = [cells[2]]
    html = _node(STUBS + _live_forward_renderer() + "\nconsole.log(JSON.stringify({html:renderV13LiveForward("
                 + json.dumps(lf) + ",[])}));\n")
    assert "판정 없음 · 누적 중" in html and "라이브 강등" not in html and "판정 대기" not in html
