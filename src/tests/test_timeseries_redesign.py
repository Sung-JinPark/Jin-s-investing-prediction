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
