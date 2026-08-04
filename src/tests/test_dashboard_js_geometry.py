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
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8"
    )
    labels = json.loads(completed.stdout)
    ordered = sorted(item["labelY"] for item in labels)
    assert all(right - left >= 16 for left, right in zip(ordered, ordered[1:]))
    assert ordered[0] >= 40
    assert ordered[-1] <= 200


def test_flow_reference_and_scenario_labels_avoid_right_edge_collisions() -> None:
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
    assert match
    helper = match.group(0).removesuffix("\nfunction drawIndexedCompare")
    program = helper + """
const rows=resolveEndpointLabels([
  {key:'S1',y:92},{key:'S2',y:121},{key:'ath',y:122},
  {key:'S3',y:188},{key:'corr10',y:189}
],21,40,240);
console.log(JSON.stringify(rows));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True
    )
    labels = json.loads(completed.stdout)
    ordered = sorted(item["labelY"] for item in labels)
    assert all(right - left >= 21 for left, right in zip(ordered, ordered[1:]))
    assert ordered[0] >= 40 and ordered[-1] <= 240


def test_flow_calendar_uses_readable_text_labels_and_groups_dense_earnings() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function flowCalendarEventLabel\([\s\S]+?\n}\nfunction buildRebasedFlowModel",
        source,
    )
    assert match, "calendar text helpers must remain standalone and testable"
    helpers = match.group(0).removesuffix("\nfunction buildRebasedFlowModel")
    program = helpers + r"""
const events=[
  {date:'2026-08-26',kind:'earnings',ticker:'NVDA',title:'NVIDIA FY27 Q2 실적'},
  {date:'2026-09-16',kind:'fomc',title:'FOMC 결정·SEP'},
  {date:'2026-10-28',kind:'earnings',ticker:'GOOGL',title:'Alphabet 분기 실적'},
  {date:'2026-10-28',kind:'earnings',ticker:'META',title:'Meta 분기 실적'},
  {date:'2026-10-28',kind:'earnings',ticker:'MSFT',title:'Microsoft 분기 실적'}
];
console.log(JSON.stringify(groupFlowCalendarEvents(events).map(flowCalendarEventLabel)));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8"
    )
    assert json.loads(completed.stdout) == [
        "8/26 NVDA 실적",
        "9/16 FOMC·SEP",
        "10/28 빅테크 실적 3건",
    ]
    assert "appendCalendarEventShape" not in source


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


def test_flow_uses_one_continuous_terminal_median_path_and_keeps_2027_dips() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function flowDisplayPath\([\s\S]+?\n}\nfunction flowAxisTickIndexes",
        source,
    )
    assert match, "display path helpers must remain standalone and testable"
    helpers = match.group(0).removesuffix("\nfunction flowAxisTickIndexes")
    program = helpers + r"""
const sc={
  paths:{S1:{values:[100,101,102,103]}},
  path_realism:{S1:{sample_paths:[
    {terminal_percentile:25,values:[100,90,99,101]},
    {terminal_percentile:50,values:[100,110,96,108]},
    {terminal_percentile:75,values:[100,120,111,130]}
  ]}}
};
const values=flowDisplayPath(sc,'S1');
console.log(JSON.stringify({values,stats:flowPathStats(values,['2026-12-31','2027-01-08','2027-01-15','2027-01-22'])}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8"
    )
    result = json.loads(completed.stdout)
    assert result["values"] == [100, 110, 96, 108]
    assert result["stats"] == {"maxDrawdownPct": 12.7, "downWeeks2027": 1}


def test_rebased_flow_uses_same_horizon_law_and_shortens_remaining_range() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function buildRebasedFlowModel\([\s\S]+?\n}\nfunction rebaseRelativeLabel",
        source,
    )
    assert match, "rebase model builder must remain a standalone testable helper"
    display_match = re.search(
        r"function flowDisplayPath\([\s\S]+?\n}\nfunction flowAxisTickIndexes",
        source,
    )
    assert display_match
    helper = (
        display_match.group(0).removesuffix("\nfunction flowAxisTickIndexes")
        + "\n"
        + match.group(0).removesuffix("\nfunction rebaseRelativeLabel")
    )
    program = helper + r"""
const days=Array.from({length:20},(_,i)=>`2026-08-${String(i+3).padStart(2,'0')}`);
const quantiles={};
['p10','p25','p50','p75','p90'].forEach((key,keyIndex)=>quantiles[key]=Array.from({length:20},(_,i)=>1000+(keyIndex*100)+(i+1)*10));
const sc={asof:'2026-08-02',anchor:1000,week_dates:days,quantile_table:{trading_days:days,quantiles},event_calendar:[],paths:{
  S1:{values:days.map((_,i)=>200+i*2)},S2:{values:days.map((_,i)=>200+i)},S3:{values:days.map((_,i)=>200-i)}
}};
const early=buildRebasedFlowModel(sc,days[0]);
const middle=buildRebasedFlowModel(sc,days[6]);
const late=buildRebasedFlowModel(sc,days[15]);
console.log(JSON.stringify({
  origins:[early.series.p10[0],middle.series.p50[0],late.series.p90[0]],
  earlyStep:[early.series.p10[1],early.series.p50[1],early.series.p90[1]],
  middleStep:middle.series.p50[1],
  scenarioOrigins:Object.values(early.scenario_series).map(values=>values[0]),
  scenarioSteps:Object.values(early.scenario_series).map(values=>values[1]),
  remaining:[early.remaining_trading_days,middle.remaining_trading_days,late.remaining_trading_days],
  ends:[early.dates.at(-1),middle.dates.at(-1),late.dates.at(-1)]
}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True
    )
    result = json.loads(completed.stdout)
    assert result["origins"] == [100, 100, 100]
    assert result["earlyStep"] == [104.95, 104.13, 103.55]
    assert result["middleStep"] == 103.94
    assert result["scenarioOrigins"] == [100, 100, 100]
    assert result["scenarioSteps"] == [105, 102.5, 97.5]
    assert result["remaining"] == [19, 13, 4]
    assert result["ends"] == ["2026-08-22"] * 3
