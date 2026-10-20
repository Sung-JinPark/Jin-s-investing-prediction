"""Route compatibility and independent research/forecast grouping."""
import json
import shutil
import subprocess

import pytest

from ai_fc import dashboard


@pytest.mark.parametrize("old,canonical,section,view,arg", [
    ("#future/history", "#statistics/history", "statistics", "statistics", {"page": "history"}),
    ("#future/cross-asset/S2", "#statistics/cross-asset/S2", "statistics", "statistics", {"page": "cross-asset", "scenario": "S2"}),
    ("#future/liquidity", "#statistics/market-liquidity", "statistics", "statistics", {"page": "market-liquidity"}),
    ("#statistics/liquidity", "#statistics/dotcom/liquidity", "statistics", "statistics", {"page": "dotcom", "category": "liquidity"}),
    ("#statistics/ipo", "#statistics/dotcom/ipo", "statistics", "statistics", {"page": "dotcom", "category": "ipo"}),
    ("#statistics/fear-greed", "#statistics/fear-greed", "statistics", "statistics", {"page": "fear-greed"}),
    ("#timeseries", "#future/timeseries", "future", "timeseries", {"tsTab": None}),
    ("#timeseries/daily", "#future/timeseries/daily", "future", "timeseries", {"tsTab": "daily"}),
    ("#timeseries/backtest", "#future/timeseries/backtest", "future", "timeseries", {"tsTab": "backtest"}),
    ("#lab=history", "#statistics/history", "statistics", "statistics", {"page": "history"}),
    ("#future/trendlines/soxx", "#trendlines/soxx", "trendlines", "trendlines", {"asset": "soxx"}),
])
def test_legacy_links_normalize_once_without_losing_context(tmp_path, old, canonical, section, view, arg):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    alias = source[source.index("function trendRouteAlias"):source.index("const UI_KEY=")]
    router = source[source.index("function legacyRouteRedirect"):source.index("function renderFuturePathsLoadState")]
    program = tmp_path / "routes.js"
    program.write_text(alias + router + "\nconst h=legacyRouteRedirect(" + json.dumps(old) + ");"
                       "process.stdout.write(JSON.stringify({h,twice:legacyRouteRedirect(h),parsed:parseCanonicalRoute(h)}));", encoding="utf-8")
    result = subprocess.run([node, str(program)], capture_output=True, text=True, check=True)
    row = json.loads(result.stdout)
    assert row["h"] == row["twice"] == canonical
    assert row["parsed"]["section"] == section
    assert row["parsed"]["view"] == view
    for key, value in arg.items():
        assert row["parsed"]["arg"][key] == value


def test_statistics_studies_are_independent_and_case_box_is_removed():
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    for name, end in [("renderScenarioV52", "renderFlow"), ("renderFlow", "analogPanel")]:
        body = source[source.index("function " + name + "("):source.index("function " + end + "(")]
        assert "analogPanel()" not in body
        assert "crossAssetPanel()" not in body
        assert "liquidityPanel()" not in body
        assert "predictionSectionNav('graph')" in body
    assert "v==='flow'||statisticsStudyRequested" in source
    assert "if(statisticsStudyRequested){renderStatisticsStudy(arg,{error});return;}" in source
    assert "if(v==='flow'&&DATA?.daily_flow" in source
    assert "arg?.page==='dotcom'&&DATA?.statistics_lab" in source
    assert "analog-case-list" not in source
    assert "forwardMarkup" not in source
    assert 'data-analog-focus="ALL" aria-pressed="true">전체' in source
    assert "root.classList.contains('timeseries-page')" in source
