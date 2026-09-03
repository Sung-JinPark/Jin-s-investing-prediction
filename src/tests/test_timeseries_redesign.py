"""시계열 예측 뷰 재설계 (docs/design/timeseries_view_redesign_260903.md) 마크업 계약."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from ai_fc import dashboard


def _html() -> str:
    return dashboard.load_template()


def test_method_box_is_last_child_of_summary_panel_only() -> None:
    html = _html()
    assert "timeseriesSpecCard()" not in html, "패널 밖 구 호출이 남아 있다"
    assert len(re.findall(r"\$\{timeseriesSpecCard\(ts\)\}", html)) == 3, "V8·HOLD·레거시 세 경로에 각 1회"
    v8 = html[html.index("function renderTimeseriesV8"):html.index("function renderTimeseries(")]
    assert "${timeseriesSpecCard(ts)}</div>`;" in v8
    assert v8.index("${timeseriesSpecCard(ts)}") < v8.index("const pathPanel"), "summary 문자열 안에서만"
    assert "${panel('summary',summaryPanel)}" in v8
    legacy = html[html.index("function renderTimeseries("):html.index("/* ── 관리자 전용")]
    hold, visible = legacy.split("if(!visible){", 1)[1].split("const one=ts.horizons", 1)
    assert "${timeseriesSpecCard(ts)}`)}" in hold and "${timeseriesSpecCard(ts)}${footnote}" not in hold
    assert "${timeseriesSpecCard(ts)}`)}" in visible
    assert visible.index("${timeseriesSpecCard(ts)}") < visible.index("${panel('path'")


def test_every_timeseries_chart_has_hover_and_readout() -> None:
    html = _html()
    assert "function bindTsHover(host,spec)" in html
    assert "matchMedia('(pointer: fine)')" in html
    for key in ("band", "range", "skill", "coverage"):
        assert f'data-ts-chart="{key}"' in html, key
    assert html.count("${tsReadout()}") >= 4, "SVG 도표마다 role=status 리드아웃"
    assert "data-ts-overlay" in html and 'role="status" aria-live="polite"' in html
    for key in ("cards", "ladder", "fresh", "kpis"):
        assert f'data-ts-chart="{key}"' in html, key
    v8 = html[html.index("function renderTimeseriesV8"):html.index("function renderTimeseries(")]
    assert "bindTimeseriesV8Interactions(root,ts);" in v8, "마운트 직후 바인딩"
    binder = html[html.index("function bindTimeseriesV8Interactions"):html.index("function tsBandModel")]
    for key in ("cards", "range", "band", "ladder", "fresh", "kpis", "skill", "coverage"):
        assert f'[data-ts-chart="{key}"]' in binder, f"{key} 표면 바인딩 누락"
    # SVG 도표는 svg 직후, DOM 표면은 바로 뒤 형제로 리드아웃을 둔다
    assert html.count("</svg>${tsReadout()}") >= 4
    assert "</section>${tsReadout()}" in html and "</ul>${tsReadout()}" in html and "</table>${tsReadout()}" in html
    # 툴팁은 고정 여부와 무관하게 pointerleave에서 숨긴다 (고정 툴팁 잔류 방지)
    assert "const hide=()=>{if(tip)tip.style.display='none';if(pinned)return;" in html


def test_v8_enables_four_tabs_and_keeps_disclosure_on_every_tab() -> None:
    html = _html()
    v8 = html[html.index("function renderTimeseriesV8"):html.index("function renderTimeseries(")]
    assert "const enabled=['summary','path','drivers','backtest']" in v8
    foot = html[html.index("function tsFootnote(ts)"):html.index("function bindTimeseriesV8Interactions")]
    assert "매매 신호가 아닙니다" in foot, "방법 박스가 첫 탭으로 들어가도 4탭 공통 공시 유지"
    assert "기여도(가중치×변화)가 아닙니다" in v8, "기여 요인 탭 정직성 리드"
    assert "선형 보간(참고용)" in html, "보간 정직성 캡션 유지"
    assert "아래에 있을 가능성" not in html, "가격 레벨+확률 결합 문장 금지"


def test_compacted_bundle_parses_with_node() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = dashboard.render_html({}, mode="embed")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts, "인라인 스크립트 없음"
    with tempfile.TemporaryDirectory() as tmp:
        for index, body in enumerate(scripts):
            path = Path(tmp) / f"bundle_{index}.js"
            path.write_text(body, encoding="utf-8")
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr[:2000]


def test_timeseries_pure_helpers_behave() -> None:
    """tsHorizonRows 폴백·tsSealedRows 필터·tsFootnote 중복 방지·spec card 분기를 node로 실행 검증."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    html = _html()
    script = html[html.index("const tsLevel="):html.index("function tsHoverLayer")]
    footnote = html[html.index("function tsFootnote(ts)"):html.index("function bindTimeseriesV8Interactions")]
    sealed = html[html.index("function tsSealedRows(ts)"):html.index("function tsSkillModel")]
    probe = """
const esc=s=>String(s==null?'':s);
""" + script + sealed + footnote + """
const ts={anchor:{value:100},horizons:{'1':{median_index:101,point_return:0.01,probability_up:0.6,band_index:{p10:98,p25:99,p75:102,p90:104}},'5':{}, '21':{median_index:0},'63':{median_index:110,point_return:0.1,probability_up:0.7,band_index:{p10:90,p25:100,p75:115,p90:120},log_return:{p10:-0.1,p25:0,p50:0.0953,p75:0.14,p90:0.18}}},
  sealed_metrics:{horizons:{'21':{crps_improvement_vs_best:0.02,coverage_p10_p90:0.79},'63':{crps_improvement_vs_best:null,coverage_p10_p90:0.8},'5':{crps_improvement_vs_best:'x'}}},footnote:'*기준 · 매매 신호가 아닙니다'};
const rows=tsHorizonRows(ts);
const out={
  keys:rows.map(r=>r.h),
  fallback_r10:Number(rows[0].r10.toFixed(3)),
  log_r10:Number(rows[1].r10.toFixed(4)),
  sealed:tsSealedRows(ts).map(r=>r.h),
  footnote_once:(tsFootnote(ts).match(/매매 신호/g)||[]).length,
  footnote_added:tsFootnote({}).includes('매매 신호가 아닙니다'),
};
process.stdout.write(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.js"
        path.write_text(probe, encoding="utf-8")
        result = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[:2000]
    import json
    out = json.loads(result.stdout)
    assert out["keys"] == ["1", "63"], "중앙값 없는 기간은 제외"
    assert out["fallback_r10"] == -0.02, "log_return 없으면 band_index/anchor 폴백"
    assert abs(out["log_r10"] - (-0.0952)) < 0.001, "log_return 있으면 expm1"
    assert out["sealed"] == ["21"], "CRPS 개선율이 숫자인 기간만"
    assert out["footnote_once"] == 1 and out["footnote_added"] is True
