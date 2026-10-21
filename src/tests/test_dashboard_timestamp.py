"""Published UTC build instants must display as actual Korean local time."""
import json
import os
import shutil
import subprocess

import pytest

from ai_fc import dashboard


@pytest.mark.parametrize("zone", ["UTC", "Asia/Seoul", "America/New_York"])
def test_build_timestamp_is_kst_independent_of_browser_timezone(tmp_path, zone):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    helper = source[source.index("function formatKstTimestamp("):source.index("function freshnessInfo(")]
    values = [
        "2026-10-20T22:47:16+00:00", "2026-10-20T22:47:16Z",
        "2026-10-21T07:47:16+09:00", "2026-10-20T18:47:16-04:00",
        "2026-10-21T07:47:16", "2026-12-31T18:05:00Z",
        "", None, "invalid-time",
    ]
    program = tmp_path / "kst.js"
    program.write_text(helper + "\nprocess.stdout.write(JSON.stringify(" + json.dumps(values)
                       + ".map(formatKstTimestamp)));", encoding="utf-8")
    result = subprocess.run([node, str(program)], env={**os.environ, "TZ": zone},
                            capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(result.stdout) == ["2026-10-21 07:47 KST"] * 5 + [
        "2027-01-01 03:05 KST", "시각 미상", "시각 미상", "시각 미상"]


def test_rail_drawer_and_data_status_use_the_same_timestamp_formatter():
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    assert "const generated='갱신 '+formatKstTimestamp(DATA.meta.generated)" in source
    assert "const generated=formatKstTimestamp(DATA?.meta?.generated)" in source
    assert "DATA.meta.generated.replace('T',' ').slice(0,16)+' KST'" not in source
