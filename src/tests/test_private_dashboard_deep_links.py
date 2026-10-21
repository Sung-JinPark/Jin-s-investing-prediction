"""Cold links work before the personal chart's navigation bridge is loaded."""
import json
import shutil
import subprocess

import pytest

from ai_fc import dashboard


def test_local_dashboard_deep_links_preserve_destinations_and_origin_boundary(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    helper = source[source.index("function privateDashboardDestination("):source.index("let ROUTE_EPOCH=")]
    public = [("future", "#future"), ("future", "#future/original"),
              ("future", "#future/timeseries/daily"), ("statistics", "#statistics"),
              ("statistics", "#statistics/dotcom/credit"), ("statistics", "#statistics/history"),
              ("statistics", "#statistics/market-liquidity"), ("statistics", "#statistics/cross-asset"),
              ("statistics", "#statistics/fear-greed"), ("records", "#records/journal")]
    local = [("trendlines", "#trendlines/sk-hynix"), ("trendlines", "#trendlines/soxx"),
             ("trendlines", "#future/trendlines/bitcoin"), ("overview", "#app")]
    origins = ["http://127.0.0.1:8878", "https://sung-jinpark.github.io",
               "http://localhost:8878", "http://127.0.0.1:8879", "https://example.com"]
    program = tmp_path / "navigation.js"
    program.write_text(helper + "\nconst cases=" + json.dumps(public + local)
                       + ";const origins=" + json.dumps(origins)
                       + ";process.stdout.write(JSON.stringify(origins.map(origin=>cases.map(([section,hash])=>privateDashboardDestination(origin,section,hash)))));", encoding="utf-8")
    result = subprocess.run([node, str(program)], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    rows = json.loads(result.stdout)
    assert rows[0] == ["https://sung-jinpark.github.io/Jin-s-investing-prediction/" + value for _, value in public] + [None] * len(local)
    assert all(row == [None] * (len(public) + len(local)) for row in rows[1:])


def test_local_deep_link_forwarding_precedes_data_loading_and_keeps_chart_cleanup():
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    route = source[source.index("async function route(){"):]
    forward = route.index("privateDashboardDestination(location.origin,navView,rawHash)")
    assert route.index("globalThis.TrendlineUI?.cleanup()") < forward
    assert route.index("legacyRouteRedirect(enteredHash)") < forward
    assert forward < route.index("await ensureTrendlineAssets()")
    assert forward < route.index("await ensureFuturePaths()")
    assert "if(publicDestination){location.replace(publicDestination);return;}" in route
