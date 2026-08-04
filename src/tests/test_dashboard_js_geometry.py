from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def test_cross_asset_endpoint_labels_keep_minimum_gap() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function resolveEndpointLabels\([\s\S]+?\n}\nfunction drawIndexedCompare",
        source,
    )
    assert match, "resolveEndpointLabels must remain a standalone testable helper"
    helper = match.group(0).removesuffix("\nfunction drawIndexedCompare")
    program = (
        helper
        + "\nconsole.log(JSON.stringify(resolveEndpointLabels("
        "[{key:'a',y:101},{key:'b',y:105},{key:'c',y:109}],16,40,200)))"
    )
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True
    )
    labels = json.loads(completed.stdout)
    ordered = sorted(item["labelY"] for item in labels)
    assert all(right - left >= 16 for left, right in zip(ordered, ordered[1:]))
    assert ordered[0] >= 40
    assert ordered[-1] <= 200


def test_flow_horizon_and_sparse_axis_geometry() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function flowHorizonEndIndex\([\s\S]+?\n}\nfunction drawFlow",
        source,
    )
    assert match, "flow horizon helpers must remain standalone and testable"
    helpers = match.group(0).removesuffix("\nfunction drawFlow")
    program = helpers + """
const sc={
  week_dates:['2026-08-03','2026-09-01','2027-02-02','2027-08-04'],
  weeks:['8/3','9/1','2/2','8/4'],
  quantile_table:{trading_days:Array(252).fill('2027-02-03')}
};
console.log(JSON.stringify({
  six:flowHorizonEndIndex(sc,126),
  full:flowHorizonEndIndex(sc,252),
  ticks:flowAxisTickIndexes(52,6),
  eventLanes:flowEventLayout(
    [[1,'8/7 고용'],[2,'8/26 NVDA'],[3,'9/4 고용'],[4,'9/15–16 FOMC·SEP']],
    51,index=>58+index*18,58,1020
  ).map(row=>row.lane)
}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True
    )
    result = json.loads(completed.stdout)
    assert result["six"] == 2
    assert result["full"] == 3
    assert len(result["ticks"]) == 6
    assert result["ticks"][0] == 0 and result["ticks"][-1] == 51
    assert len(set(result["eventLanes"])) >= 3
    assert all(0 <= lane < 5 for lane in result["eventLanes"])
