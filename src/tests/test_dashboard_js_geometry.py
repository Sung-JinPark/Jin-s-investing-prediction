from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def test_statistics_profile_rows_supports_dotcom_and_current_bars() -> None:
    script_path = (
        Path(__file__).parents[1]
        / "ai_fc"
        / "dashboard_parts"
        / "dashboard.js"
    )
    source = script_path.read_text(encoding="utf-8")
    match = re.search(
        r"function statisticsProfileRows\([\s\S]+?\n}\nfunction statisticsProfileCards",
        source,
    )
    assert match, "profile comparison rows must remain a standalone helper"
    helper = match.group(0).removesuffix("\nfunction statisticsProfileCards")
    program = helper + r"""
const rows=statisticsProfileRows({value:60,display_value:'60%',comparisons:[
  {label:'1999 닷컴',era:'dotcom',value:60,display_value:'60%'},
  {label:'AI 현재',era:'current',value:12,display_value:'12%'},
  {label:'미수집',era:'current',value:null,display_value:'—'}
]});
const legacy=statisticsProfileRows({value:90,display_value:'+90%'});
console.log(JSON.stringify({rows,legacy}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    result = json.loads(completed.stdout)
    assert [(row["era"], row["value"]) for row in result["rows"]] == [
        ("dotcom", 60), ("current", 12),
    ]
    assert result["legacy"] == [{
        "label": "1999 닷컴", "era": "dotcom", "value": 90,
        "display_value": "+90%",
    }]


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


def test_flow_keeps_center_path_separate_from_continuous_correction_sample() -> None:
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
  week_dates:['2026-12-31','2027-01-08','2027-01-15','2027-01-22'],
  paths:{S1:{values:[100,101,102,103]}},
  structural_forecast:{paths:{S1:{values:[100,96,108,101]}},years:[
    {year:2026,start_index:0,end_index:0},{year:2027,start_index:1,end_index:3}
  ]},
  path_realism:{S1:{sample_paths:[
    {terminal_percentile:25,values:[100,90,99,101]},
    {terminal_percentile:50,values:[100,110,96,108]},
    {terminal_percentile:75,values:[100,120,111,130]}
  ]}}
};
const values=flowDisplayPath(sc,'S1');
const sample=sc.path_realism.S1.sample_paths[1].values;
console.log(JSON.stringify({values,year:flowYearRange(sc,2027),centerStats:flowPathStats(values,sc.week_dates),sampleStats:flowPathStats(sample,sc.week_dates)}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8"
    )
    result = json.loads(completed.stdout)
    assert result["values"] == [100, 96, 108, 101]
    assert result["year"] == {"start": 1, "end": 3, "year": 2027}
    assert result["centerStats"] == {"maxDrawdownPct": 6.5, "downWeeks2027": 2}
    assert result["sampleStats"] == {"maxDrawdownPct": 12.7, "downWeeks2027": 1}


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


def _dashboard_source() -> str:
    return (
        Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.js"
    ).read_text(encoding="utf-8")


def test_close_probability_is_labelled_against_the_anchor_not_the_frozen_reference() -> None:
    """The hero sentence must name the threshold `prob_above_anchor` actually uses.

    `quantile_table.prob_above_anchor` is `(future > anchor)` — anchor is the asof
    close. S2's 기준가 is the frozen 2026-07-09 close (`REFERENCE_PRICE`). Calling
    both "기준가" read as one number until anchor sat above the reference; once
    anchor drops below it the sentence points the wrong way.
    """
    source = _dashboard_source()
    match = re.search(r"function marketThesis\([\s\S]+?\n}\n", source)
    assert match, "marketThesis must remain a standalone helper"
    program = match.group(0) + r"""
console.log(JSON.stringify({
  up:marketThesis(86,14,69).accent,
  range:marketThesis(30,60,69).accent,
  none:marketThesis(86,14,null).accent
}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",  # the sentence is Korean; the OS codepage is not
    )
    result = json.loads(completed.stdout)
    assert "연말 종가가 현재가를 넘는 모의 경로는 69%입니다." in result["up"]
    assert "기준가를 넘는" not in result["up"]
    # S2's own wording keeps 기준가 — only the anchor-based tail was wrong.
    assert "기준가를 지키는 경로가 86%" in result["up"]
    assert "현재가를 넘는 모의 경로는 69%" in result["range"]
    assert "69%" not in result["none"]


def test_scenario_close_probability_source_still_compares_against_anchor() -> None:
    """Pin the other half: if the engine ever switches thresholds, this fails too."""
    engine = (Path(__file__).parents[1] / "ai_fc" / "scenario.py").read_text(encoding="utf-8")
    assert '"prob_above_anchor": [' in engine
    assert "(future > anchor).mean(axis=0)" in engine
    assert "end_above_reference = classification[:, -1] > REFERENCE_PRICE" in engine


def test_ath_chip_does_not_claim_a_52_week_window() -> None:
    """`ath = max(closes)` spans the whole fetched series (from 2023-01-01)."""
    source = _dashboard_source()
    assert "sub:'52주 기준'" not in source
    assert "sub:'2023년 이후 최고 종가'" in source
    engine = (Path(__file__).parents[1] / "ai_fc" / "scenario.py").read_text(encoding="utf-8")
    assert "ath = float(max(closes))" in engine
    assert "date(2023, 1, 1)" in engine


def _home_signal_helpers() -> str:
    match = re.search(
        r"function v13VolSignal\([\s\S]+?\n}\nfunction dotcomCycleSignal\([\s\S]+?\n}\n",
        _dashboard_source(),
    )
    assert match, "home signal helpers must remain standalone"
    return match.group(0)


def _run_js_file(program: str) -> dict:
    """큰 payload 는 `node -e` 의 커맨드라인 길이 제한을 넘는다."""
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "check.js"
        script.write_text(program, encoding="utf-8")
        completed = subprocess.run(["node", str(script)], check=True,
                                   capture_output=True, text=True, encoding="utf-8")
    return json.loads(completed.stdout)


def _run_js(program: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_home_volatility_card_stays_behind_the_t3_gate() -> None:
    """The home card must not leak V13 numbers ahead of the same gate the tab uses."""
    cell = {"p": 0.099046, "clim_base_rate": 0.419468,
            "episode_sample": "thin", "reliability": "good"}
    program = _home_signal_helpers() + r"""
const live={publication:{display_tier:'t3_live_card',holdout_status:'partial'},cells:{vix25_h21:CELL}};
const hidden={publication:{display_tier:'t2_hidden_panel'},cells:{vix25_h21:CELL}};
const internal={publication:{display_tier:'t0_internal'},cells:{vix25_h21:CELL}};
console.log(JSON.stringify({
  live:v13VolSignal(live), hidden:v13VolSignal(hidden), internal:v13VolSignal(internal),
  empty:v13VolSignal({publication:{display_tier:'t3_live_card'},cells:{}}), missing:v13VolSignal(null)
}));
""".replace("CELL", json.dumps(cell))
    result = _run_js(program)
    assert result["live"] == {"pct": 10, "clim": 42, "caution": True, "holdout": "partial"}
    assert result["hidden"] is None and result["internal"] is None
    assert result["empty"] is None and result["missing"] is None


def test_home_era_card_reports_a_cycle_position_not_a_probability() -> None:
    """statistics_lab is reference_only — the card may show elapsed months, never a %."""
    program = _home_signal_helpers() + r"""
const ok={status:'ok',charts:[{},{},{}],cycle_alignment:{
  current_start:'2023-01-01',current_observed_through:'2026-09-01',comparison_months:59}};
const noTotal={status:'ok',charts:[],cycle_alignment:{
  current_start:'2023-01-01',current_observed_through:'2026-09-01'}};
console.log(JSON.stringify({
  ok:dotcomCycleSignal(ok), noTotal:dotcomCycleSignal(noTotal),
  stale:dotcomCycleSignal({status:'stale',cycle_alignment:ok.cycle_alignment}),
  noAlign:dotcomCycleSignal({status:'ok',charts:[]}),
  missing:dotcomCycleSignal(null)
}));
"""
    result = _run_js(program)
    assert result["ok"] == {"elapsed": 44, "total": 59, "pct": 75, "charts": 3}
    # 경과율이지 확률이 아니다 — 28개 이질 지표를 하나의 % 로 합성하지 않는다.
    assert result["noTotal"] == {"elapsed": 44, "total": None, "pct": None, "charts": 0}
    assert result["stale"] is None and result["noAlign"] is None and result["missing"] is None


def test_home_cards_name_their_basis_and_the_row_says_they_are_not_combinable() -> None:
    """세 숫자는 확률공간이 다르다. 그 사실을 어딘가에서 반드시 말해야 한다.

    카드마다 "결합 금지 참고값" 을 반복하던 것을 행 아래 한 줄로 옮겼다 — 카드가 셋뿐이라
    한 줄이 더 분명하고, 반복 태그보다 읽는 부담이 작다 (홈 재설계, DECISIONS 2026-09-14).
    """
    source = _dashboard_source()
    assert 'aria-label="핵심 지표 3개"' in source
    row = source.split('<div class="today-signals"', 1)[1].split("</div>", 1)[0]
    for label in ("가격 시나리오", "다변량 시계열", "AI 닷컴 비교"):
        assert f"card('{label}'" in row, label
    assert "신호 0" not in row
    # 결합 금지 고지는 사라진 게 아니라 행 주석으로 옮겨졌다.
    note = source.split('class="today-basis-note"', 1)[1].split("</p>", 1)[0]
    assert "서로 다른 기준" in note and "더하거나 평균하지 않습니다" in note


def test_home_overheat_card_never_shows_the_composite_without_its_spread() -> None:
    """대표값만 내보내면 부문이 33~160% 로 갈려 있다는 사실이 지워진다."""
    source = _dashboard_source()
    pattern = "function dotcomOverheatSignal" + r"\([\s\S]+?" + chr(10) + "}" + chr(10)
    match = re.search(pattern, source)
    assert match, "dotcomOverheatSignal must remain standalone"
    # 손으로 쓴 픽스처는 필드명이 어긋나도 자기들끼리 맞아 통과한다 —
    # 실제로 beyond_window_count/beyond_peak_count 가 어긋난 채 배포됐다.
    from ai_fc.dotcom_overheat import compute_index
    live = compute_index(Path(__file__).resolve().parents[2])
    assert live["status"] == "ok", live
    call = ("console.log(JSON.stringify({ok:dotcomOverheatSignal("
            + json.dumps(live, default=str)
            + "),unavailable:dotcomOverheatSignal({status:'unavailable'}),"
              "missing:dotcomOverheatSignal(null)}));")
    result = _run_js_file(match.group(0) + chr(10) + call + chr(10))
    assert result["ok"]["pct"] == live["overheat_pct"]
    assert [result["ok"]["lo"], result["ok"]["hi"]] == live["category_span"]
    assert result["ok"]["beyond"] == live["beyond_peak_count"], "필드명이 모듈과 어긋났다"
    assert result["unavailable"] is None and result["missing"] is None

    card = source.split("'AI 닷컴 비교'", 1)[1].split("}", 1)[0] + source.split("'AI 닷컴 비교'", 1)[1][:400]
    assert "닷컴 정점 100%" in card, "축의 의미를 카드가 직접 말해야 한다"
    assert "부문 ${heat.lo}~${heat.hi}%" in card, "산포 없이 대표값만 내보내면 안 된다"
    assert "정점 초과 ${heat.beyond}종" in card


def test_home_card_subtitle_is_never_clipped_to_a_fixed_line_count() -> None:
    """부제는 카드의 단서를 담는다 — 줄 수를 고정하면 뒤가 통째로 사라진다.

    실측 이력: 한 줄 고정(nowrap+ellipsis)일 때 과열도 카드가 131px 잘려 있었고,
    2줄 클램프로 바꿔도 좁은 폭에서는 여전히 잘렸다. 재설계에서 카드를 세로 스택으로
    돌려 부제가 카드 폭을 다 쓰게 했고, 줄 수 제한 자체를 없앴다.
    """
    css = (Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.css").read_text(
        encoding="utf-8")
    rule = re.search(r"\.today-signals small\{([^}]*)\}", css)
    assert rule, ".today-signals small 기본 규칙이 있어야 한다"
    body = rule.group(1)
    assert "white-space:nowrap" not in body, "한 줄 고정은 부제 뒷부분을 버린다"
    assert "text-overflow:ellipsis" not in body, "말줄임은 정보 손실을 숨긴다"
    assert "-webkit-line-clamp" not in body, "줄 수 고정도 같은 손실을 만든다"
    assert "white-space:normal" in body
    # 이벤트 제목도 같은 이유로 줄바꿈을 허용한다.
    rail = re.search(r"\.agenda-rail p\{([^}]*)\}", css)
    assert rail and "white-space:normal" in rail.group(1)

