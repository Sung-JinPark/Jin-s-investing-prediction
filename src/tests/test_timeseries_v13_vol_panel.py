"""V13-VOL 대시보드 패널 — 배선(기본 숨김)·X1 이름충돌 6항·레일 tier 게이트를 JS/CSS 소스에서 고정한다.

표시 설계서 docs/design/v13_vol_live_card_display_design_260908.md §1.2(X1)·§4.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
STYLE = (ROOT / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")


def _panel_source() -> str:
    start = SCRIPT.index("function renderTimeseriesV13VolPanel(")
    end = SCRIPT.index("function bindTimeseriesV13VolInteractions(")
    return SCRIPT[start:end]


def test_v13_vol_panel_is_wired_hidden_by_default() -> None:
    assert "const TS_TABS=[['summary','전망 요약']" in SCRIPT, "기존 탭 키와 라벨 보존"
    assert "const TS_V13_TAB=['volatility','변동성 기준율']" in SCRIPT
    assert "[...TS_TABS,TS_V13_TAB].map(" in SCRIPT, "탭 마크업이 5탭을 그린다(비활성=검증 대기)"
    assert "function timeseriesV13TabEnabled(" in SCRIPT
    assert "get('review')==='v13vol'" in SCRIPT, "T2 는 ?review=v13vol 로만 열람"
    assert "tier==='t3_live_card')return true" in SCRIPT
    # 세 렌더 경로(V8 · HOLD · 레거시) 모두 패널을 싣고 탭 토글이 5번째 패널을 안다
    assert SCRIPT.count("${panel('volatility',renderTimeseriesV13VolPanel(DATA.timeseries_v13_vol))}") == 3
    legacy_renderers = SCRIPT[SCRIPT.index("function renderTimeseriesV8"):SCRIPT.index("const GC_API=")]
    assert legacy_renderers.count("if(timeseriesV13TabEnabled(DATA.timeseries_v13_vol))enabled.push('volatility');") == 2
    daily_renderer = SCRIPT[SCRIPT.index("function renderTimeseriesDaily"):SCRIPT.index("function bindTimeseriesTabs")]
    assert "if(timeseriesV13TabEnabled(DATA.timeseries_v13_vol))enabled.push('volatility');" in daily_renderer
    assert "[...TS_TABS,TS_V13_TAB].forEach(([name])=>{const node=$(`#lab-ts-${name}`,root);if(node)node.hidden=name!==next;});" in SCRIPT
    assert "bindTimeseriesTabs(root,enabled,'summary');" in SCRIPT, "V8 HOLD 경로에도 탭 바인더"


def test_v13_vol_panel_keeps_cell_contract_without_repeated_status_copy() -> None:
    src = _panel_source()
    # ① 명칭 — 제목·셀 라벨은 '기준율', 예측이라는 이름을 쓰지 않는다
    assert "<h2>변동성 이벤트 기준율</h2>" in src
    assert "<b>기준율 ${v13Pct(c.p)}</b>" in src
    # 보조 배지·상태 줄·설명 문단을 제거해도 hold/live 제목과 실제 셀은 남는다.
    for removed in ("아래 숫자는 예측이 아니라", "v13-source-badge", "v13-caveat", "${caveat}", "v13-role", "v13-reading", "timeseries-gate-strip", "설계창(2007~2014) 스킬", "참고 의견 — 매매 신호가 아닙니다"):
        assert removed not in src, removed
    assert src.count("${head}") == 2
    # ③ 지평 단위 — 영업일 + 달력일 병기
    assert "영업일</abbr>" in src and "'63':'(≈90달력일)'" in src
    # LLM과 수치모델의 확률을 결합하거나 평균내는 산식은 추가하지 않는다.
    assert "컨센서스" not in src and "평균(" not in src
    assert "(llm+" not in src and "+llm)" not in src and "*llm" not in src
    # h63 보정 약함 + 국면 표본 얇음 텍스트 마커 + 80% 대역 + 기후 병기
    assert "▲ 보정 약함" in src and "[80%: " in src and "기후 ${v13Pct(c.clim_base_rate)}" in src
    assert "▲ 국면 표본 얇음" in src and "c.episode_sample==='thin'" in src
    assert "  v13_thin_hint:'" in SCRIPT and "국면" in SCRIPT
    # hold 분기: 실제 사유 목록과 기존 숫자 표시 조건을 유지한다.
    assert "timeseries-hold-reasons" in src and "v13.numbers_visible===true" in src
    for term in ("persistence_hint", "base_rate_hint", "business_day_hint", "band80_coef_hint", "v13_weak_hint"):
        assert f"  {term}:'" in SCRIPT, term


def test_v13_vol_rail_entry_is_tier_gated_and_parseable() -> None:
    registry = SCRIPT.split("const MID_CATEGORIES={")[1].split("\n};")[0]
    entry = re.search(r"\{key:'volatility'[^}]*\}", registry)
    assert entry, "레일 항목 존재"
    assert "hash:'#future/timeseries/volatility'" in entry.group(0)
    assert "available:()=>DATA?.timeseries_v13_vol?.publication?.display_tier==='t3_live_card'" in entry.group(0)


def test_v13_vol_css_keeps_mobile_horizons_and_cleans_unused_copy_styles() -> None:
    for removed in (".v13-source-badge{", ".v13-caveat{", ".v13-role{", ".v13-reading{"):
        assert removed not in STYLE
    assert ".v13-h-tabs{display:none}" in STYLE
    mobile = STYLE.split("@media (max-width:620px){", 1)[1].split("}\n}", 1)[0]
    assert ".v13-h-tabs{display:flex" in mobile
    assert 'data-active-h="63"' in mobile
    assert ".v13-vol-table td.is-weak i{" in STYLE, "색만이 아니라 텍스트 마커"


def test_live_forward_table_scrolls_inside_mobile_card_without_hiding_cells() -> None:
    import pytest

    playwright = pytest.importorskip("playwright.sync_api")
    renderer = re.search(r"function renderV13LiveForward\([\s\S]+?\n}\n", SCRIPT)
    assert renderer
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True, channel="chrome")
        except playwright.Error as error:
            pytest.skip(f"installed Chrome not available: {error}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content(
                "<style>" + STYLE + '</style><main style="max-width:390px;padding:16px">'
                '<article class="ts-card v13-vol-card" id="card"></article></main>'
            )
            page.add_script_tag(content=(
                "const hasNumeric=x=>typeof x==='number'&&Number.isFinite(x),esc=String,num=String;"
                + renderer.group(0)
            ))
            for status in ("accumulating", "empty"):
                result = page.evaluate(r"""status => {
                  const empty=status==='empty',lf={status,minimum:60,matured_total:empty?0:60,origins_recorded:29,cells:[
                    {cell:'vix25_h21',matured:empty?0:60,minimum:60,progress:empty?0:1,brier_model:empty?null:.21,brier_climatology:empty?null:.25,bss:empty?null:.16},
                    {cell:'rv_h5',matured:0,minimum:60,progress:0,brier_model:null,brier_climatology:null,bss:null}
                  ]},before=JSON.stringify(lf);
                  document.getElementById('card').innerHTML=renderV13LiveForward(lf,[]);
                  const wrap=document.querySelector('.v13-lf-table-wrap'),table=wrap.querySelector('table');
                  wrap.scrollLeft=wrap.scrollWidth;
                  return {
                    overflow:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)-innerWidth,
                    scrolls:wrap.scrollWidth>wrap.clientWidth&&wrap.scrollLeft>0,
                    lastColumnReachable:table.rows[1].cells[5].getBoundingClientRect().right<=wrap.getBoundingClientRect().right+1,
                    focusable:wrap.tabIndex===0,unchanged:before===JSON.stringify(lf),
                    rows:[...table.tBodies[0].rows].map(row=>[...row.cells].map(cell=>cell.innerText.trim()))
                  };
                }""", status)
                assert result["overflow"] == 0
                assert all(result[key] for key in (
                    "scrolls", "lastColumnReachable", "focusable", "unchanged",
                ))
                # 2026-10-21: '사건' 열 추가 — 고정 fixture 에는 events 가 없으므로 '—' 로 렌더된다
                expected = ["0/60", "—", "—", "—", "—"] if status == "empty" else [
                    "60/60", "—", "0.2100", "0.2500", "+16%",
                ]
                assert result["rows"] == [
                    ["vix25_h21", *expected], ["rv_h5", "0/60", "—", "—", "—", "—"],
                ]
        finally:
            browser.close()


def test_v13_vol_panel_has_no_trailing_line_comments() -> None:
    # 컴팩터가 줄을 공백으로 잇는다 — 줄 끝 // 주석은 번들을 죽인다 (test_compacted_bundle 과 같은 규율)
    start = SCRIPT.index("function timeseriesV13TabEnabled(")
    end = SCRIPT.index("function renderTimeseriesV8(")
    for line in SCRIPT[start:end].splitlines():
        stripped = line.strip()
        assert not re.search(r"(?<![:'\"])//(?!.*['\"`])", stripped) or stripped.startswith("/*") or stripped.startswith("*"), line


# ── V13-D13 live_claim_restriction — 판정불가(제한) 칩 (표시 전용·열 수 불변) ────────────────────


def _live_forward_renderer() -> str:
    renderer = re.search(r"function renderV13LiveForward\([\s\S]+?\n}\n", SCRIPT)
    assert renderer
    return renderer.group(0)


def test_live_forward_marks_claim_blocked_cells_without_adding_columns() -> None:
    renderer = _live_forward_renderer()
    assert "c.claim_blocked===true" in renderer
    assert ("<small class=\"v13-lf-claim\" title=\"${esc(plainTerm('v13_claim_hint'))}\">판정불가(제한)</small>"
            in renderer)
    assert "' 전 셀 <b>판정불가(제한)</b>.'" in renderer
    thead = renderer[renderer.index("<thead>"):renderer.index("</thead>")]
    assert thead.count('<th scope="col">') == 6, "열 수 불변 — 라벨은 셀 이름 칸 안의 칩"
    assert "  v13_claim_hint:'" in SCRIPT
    term = re.search(r"  v13_claim_hint:'([^']*)'", SCRIPT).group(1)
    assert "V13-D13" in term and "강등 판정은 그대로" in term and "20 미만" in term and "5 미만" in term
    assert ".v13-lf-claim{" in STYLE and ".v13-lf-table tr.is-claim-blocked td{" in STYLE


def test_live_forward_chip_renders_only_for_blocked_cells() -> None:
    import json
    import shutil
    import subprocess

    import pytest

    if shutil.which("node") is None:
        pytest.skip("node 미설치")

    def render(cells: list[dict]) -> str:
        lf = {"status": "accumulating", "minimum": 60, "matured_total": 30, "origins_recorded": 31,
              "events_total": 3, "cells": cells}
        program = (
            "const esc=s=>String(s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;',"
            "'>':'&gt;','\"':'&quot;'}[c]));\n"
            "const plainTerm=k=>k;const num=String;\n"
            "const hasNumeric=v=>typeof v==='number'&&Number.isFinite(v);\n"
            + _live_forward_renderer()
            + "\nconsole.log(JSON.stringify({html:renderV13LiveForward(" + json.dumps(lf) + ",[])}));\n"
        )
        completed = subprocess.run(["node", "-e", program], check=True, capture_output=True,
                                   text=True, encoding="utf-8")
        return json.loads(completed.stdout)["html"]

    blocked = {"cell": "vix25_h5", "matured": 26, "minimum": 60, "progress": 0.43, "events": 0,
               "brier_model": 0.0001, "brier_climatology": 0.09, "bss": 0.99,
               "episodes": {"event_runs": 0, "non_event_runs": 1},
               "claim_blocked": True, "claim_block_reasons": ["events<20", "episodes<5"]}
    allowed = {"cell": "rv_h5", "matured": 60, "minimum": 60, "progress": 1, "events": 30,
               "brier_model": 0.12, "brier_climatology": 0.2, "bss": 0.4,
               "episodes": {"event_runs": 6, "non_event_runs": 6},
               "claim_blocked": False, "claim_block_reasons": []}
    html = render([blocked, allowed])
    assert html.count('class="v13-lf-claim"') == 1 and 'title="v13_claim_hint"' in html
    assert '<th scope="row">vix25_h5<small class="v13-lf-claim"' in html
    assert '<th scope="row">rv_h5</th>' in html
    assert '<tr class="is-degenerate is-claim-blocked">' in html
    assert "전 셀 <b>판정불가(제한)</b>" not in html, "한 셀만 제한이면 리드에 쓰지 않는다"
    assert html.count("<th scope=\"col\">") == 6 and html.count("</td>") == 2 * 5
    # 전 셀 제한 → 리드 끝에 라벨 한 조각
    html = render([blocked, dict(allowed, claim_blocked=True, claim_block_reasons=["episodes<5"])])
    assert html.count('class="v13-lf-claim"') == 2 and "전 셀 <b>판정불가(제한)</b>." in html
