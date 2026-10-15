from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

NL = chr(10)


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
        r"function earningsGroup\([\s\S]+?\n}\nfunction buildRebasedFlowModel",
        source,
    )
    assert match, "calendar text helpers must remain standalone and testable"
    helpers = match.group(0).removesuffix("\nfunction buildRebasedFlowModel")
    program = helpers + r"""
const events=[
  {date:'2026-09-30',kind:'earnings',ticker:'MU',title:'Micron FY2026 Q4 실적'},
  {date:'2026-09-16',kind:'fomc',title:'FOMC 결정·SEP'},
  {date:'2026-10-28',kind:'earnings',ticker:'GOOGL',title:'Alphabet 분기 실적'},
  {date:'2026-10-28',kind:'earnings',ticker:'META',title:'Meta 분기 실적'},
  {date:'2026-10-28',kind:'earnings',ticker:'MSFT',title:'Microsoft 분기 실적'}
];
const grouped=groupFlowCalendarEvents(events);
console.log(JSON.stringify({labels:grouped.map(flowCalendarEventLabel),keys:grouped.map(eventBoardKindKey)}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8"
    )
    result = json.loads(completed.stdout)
    assert result["labels"] == [
        "9/16 FOMC·SEP",
        "9/30 반도체 실적 (Micron)",
        "10/28 빅테크 실적 3건 (Alphabet · Meta · Microsoft)",
    ]
    assert result["keys"] == ["fomc", "earnings:semiconductor", "earnings:bigtech"]
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
    # anchor 기준 숫자는 '지금'(=asof 종가)으로 부른다. 고정 기준가와 같은 말로 부르면
    # anchor 가 기준가 아래로 내려갈 때 문장이 반대를 가리킨다.
    assert "주가를 100번 굴리면 69번은 연말에 지금보다 높습니다." in result["up"]
    assert "기준가" not in result["up"], "anchor 문장에 고정 기준가 어휘가 섞이면 안 된다"
    assert "69번은 연말에 지금보다 높습니다" in result["range"]
    # closeProb 이 없으면 anchor 문장을 지어내지 않고, upProb 의 합성 조건을 그대로 적는다.
    assert "69" not in result["none"]
    assert "기준가 위로 끝나는 모의 경로가 86%" in result["none"]


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
        r"function tsForecastSignal\([\s\S]+?\n}\nfunction dotcomCycleSignal\([\s\S]+?\n}\n",
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


def test_home_timeseries_card_stays_behind_the_same_gate_as_the_tab() -> None:
    """홈 카드는 시계열 탭과 같은 공개 게이트를 써야 한다.

    숫자 비공개(numbers_visible / customer_numbers_visible)이거나 예측 원점이 계약의
    hold 임계에 닿으면, 마지막 값으로 버티지 않고 카드를 보류로 닫는다.
    """
    horizons = {
        "63": {"probability_up": 0.72, "median_index": 27444.78,
               "band_index": {"p10": 24508.33, "p90": 29340.82}},
    }
    program = _home_signal_helpers() + r"""
const base={numbers_visible:true,publication:{customer_numbers_visible:true},anchor:{value:26333.04},
  origin_age_policy:{warn_after_sessions:1,hold_after_sessions:10},horizons:HORIZONS};
console.log(JSON.stringify({
  live:tsForecastSignal({...base,origin_age_sessions:1}),
  aging:tsForecastSignal({...base,origin_age_sessions:4}),
  held:tsForecastSignal({...base,origin_age_sessions:10}),
  hidden:tsForecastSignal({...base,origin_age_sessions:1,numbers_visible:false}),
  internal:tsForecastSignal({...base,origin_age_sessions:1,
    publication:{customer_numbers_visible:false}}),
  empty:tsForecastSignal({...base,origin_age_sessions:1,horizons:{}}),
  missing:tsForecastSignal(null)
}));
""".replace("HORIZONS", json.dumps(horizons))
    result = _run_js(program)
    assert result["live"] == {"pct": 72, "median": 27445, "lo": 24508, "hi": 29341,
                              "now": 26333, "age": 1, "origin": None, "provisional": False,
                              "stale": False}
    # warn 임계를 넘기면 숫자는 내되 원점 나이를 카드 위에 남긴다.
    assert result["aging"]["stale"] is True and result["aging"]["age"] == 4
    # hold 임계에 닿으면 수치를 아예 내지 않는다(fail-closed).
    assert result["held"] is None
    assert result["hidden"] is None and result["internal"] is None
    assert result["empty"] is None and result["missing"] is None


def test_home_timeseries_card_carries_the_daily_origin_and_provisional_flag() -> None:
    """사용자 결정 2026-10-07: 홈 카드도 매일 갱신되는 표시 원점을 쓴다(잠정이면 표시)."""
    source = _dashboard_source()
    labels = re.search(
        r"function tsCadenceLabel\([\s\S]+?\n(?=function tsForecastSignal)", source)
    assert labels, "cadence label helpers must sit right before tsForecastSignal"
    horizons = {"63": {"probability_up": 0.7, "median_index": 27900.0,
                       "band_index": {"p10": 25000.0, "p90": 30000.0}}}
    program = labels.group(0) + _home_signal_helpers() + r"""
const base={numbers_visible:true,publication:{customer_numbers_visible:true},anchor:{value:27599.89},
  origin_age_policy:{warn_after_sessions:1,hold_after_sessions:10},horizons:HORIZONS,origin_age_sessions:0};
const daily={...base,as_of:'2026-10-06',cadence:'daily',input_state:'provisional',provisional_series:['DGS10','DGS2','VIX']};
console.log(JSON.stringify({
  signal:tsForecastSignal(daily),
  confirmed:tsForecastSignal({...daily,input_state:'confirmed'}),
  dailyLabel:tsCadenceLabel(daily),
  weeklyLabel:tsCadenceLabel({...base,as_of:'2026-10-02',cadence:'weekly'}),
  title:tsProvisionalTitle(daily)
}));
""".replace("HORIZONS", json.dumps(horizons))
    result = _run_js(program)
    assert result["signal"]["origin"] == "2026-10-06" and result["signal"]["provisional"] is True
    assert result["confirmed"]["provisional"] is False
    assert result["dailyLabel"] == "2026-10-06 종가 기준 · 매일 갱신"
    assert result["weeklyLabel"] == "2026-10-02 종가 기준 · 주 1회 갱신"
    assert "DGS10·DGS2·VIX" in result["title"]
    # 히어로는 잠정 배지를, 홈 카드는 원점 날짜를 싣는다. 채점 표면은 주간이라고 말한다.
    assert "ts.input_state==='provisional'" in source and ">잠정</span>" in source
    assert "종가 기준${tsf.provisional?' 잠정':''}" in source
    assert "<span>주간 원점 · 배포 후 쌓인 실제 성적</span>" in source
    assert "검증 성적 · 100점 환산 · 주간 원점" in source
    assert "주 1회 갱신</p>" not in source, "히어로 주기 라벨은 cadence 에서 온다"


def test_home_hero_summarises_the_three_cards_without_mixing_them() -> None:
    """히어로 요약줄은 카드 세 장을 이름과 함께 나열만 한다.

    세 숫자는 재는 것이 서로 달라 합치거나 견주면 안 된다. 그리고 overheat 지수가
    없을 때 cycle 경과율에 '과열도' 이름표를 붙이면 히어로가 없는 말을 하게 된다.
    """
    match = re.search(r"function homeSignalSummary\([\s\S]+?\n}\n", _dashboard_source())
    assert match, "homeSignalSummary must remain a standalone helper"
    program = match.group(0) + r"""
const hasNumeric=v=>v!==null&&v!==undefined&&Number.isFinite(Number(v));
const num=v=>Number(v).toLocaleString();
console.log(JSON.stringify({
  all:homeSignalSummary(78,{pct:72},{pct:61}),
  noHeat:homeSignalSummary(78,{pct:72},null),
  onlyOne:homeSignalSummary(78,null,null),
  none:homeSignalSummary(null,null,null)
}));
"""
    result = _run_js(program)
    assert result["all"] == "연말 몬테카를로 예측 78%, 3개월 시계열 예측 72%, 닷컴 대비 과열도 61%입니다."
    # 빠진 신호는 자리를 비우고 넘어간다 — 없는 숫자를 지어내지 않는다.
    assert result["noHeat"] == "연말 몬테카를로 예측 78%, 3개월 시계열 예측 72%입니다."
    # 한 장짜리는 요약이 아니다 — 빈 문자열을 돌려 시나리오 문장으로 되돌아가게 한다.
    assert result["onlyOne"] == "" and result["none"] == ""

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


def test_home_cards_say_in_plain_words_what_each_percent_counts() -> None:
    """숫자만 크게 띄우면 86·10·61 이 같은 종류로 읽힌다.

    라벨을 전문용어(가격 시나리오·다변량 시계열)에서 평이한 말로 바꾸고, 부제가 그 % 가
    무엇을 센 비율인지 직접 말하게 한다 — 그러면 "서로 다른 기준" 이라는 별도 주석줄이
    필요 없어진다 (홈 재설계, DECISIONS 2026-09-14).
    """
    source = _dashboard_source()
    assert 'aria-label="핵심 지표 3개"' in source
    row = source.split('<div class="today-signals"', 1)[1].split("</div>", 1)[0]
    for label in ("몬테카를로 예측 · 연말", "시계열 예측 · 3개월", "닷컴 대비 과열도"):
        assert f"card('{label}'" in row, label
    assert "신호 0" not in row
    # 각 부제가 그 숫자가 무엇을 센 것인지 말해야 한다.
    # 78% 를 '오를 확률' 로 읽지 않도록, 센 것이 무엇인지(100번 중 몇 번)와
    # 연말 종가가 오늘보다 높은 경로 수를 부제가 함께 말해야 한다.
    assert "모의 경로 중 전고점 터치·기준가 위 마감" in row, "몬테카를로 % 가 무엇을 센 것인지"
    assert "현재가 위 마감 ${num(closeProb)}%" in row, "상승 경로 수를 따로 밝혀야 한다"
    assert "3개월 뒤 ${num(tsf.now)} 위 마감" in row, "시계열 % 의 기준 시점과 임계"
    assert "100 = 닷컴 정점" in row, "과열도 축의 의미"


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
    assert result["ok"]["checkedAt"] == live["generated_at"]
    assert [result["ok"]["lo"], result["ok"]["hi"]] == live["category_span"]
    assert result["ok"]["beyond"] == live["beyond_peak_count"], "필드명이 모듈과 어긋났다"
    assert result["unavailable"] is None and result["missing"] is None

    card = source.split("'닷컴 대비 과열도'", 1)[1][:420]
    assert "100 = 닷컴 정점" in card, "축의 의미를 카드가 직접 말해야 한다"
    assert "분야별 ${heat.lo}~${heat.hi}" in card, "산포 없이 대표값만 내보내면 안 된다"
    assert "${heat.beyond}개 지표는 이미 정점 초과" in card
    assert "cycle.pct" not in card, "사이클 경과율을 과열도 값으로 대체하면 안 된다"


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


def _event_board_helpers() -> str:
    """홈 이벤트 보드의 선정·판정 로직만 잘라 낸다 (DOM 없이 node 로 돌리기 위해)."""
    source = (
        Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.js"
    ).read_text(encoding="utf-8")
    picked = []
    for name in ("const EV_BOARD_CAP", "function evConfirmed", "function evWeekStart",
                 "function evMergeWeekEarnings", "function evPick",
                 "function earningsGroup", "function eventBoardKindKey",
                 "function groupFlowCalendarEvents"):
        start = source.index(name)
        end = source.index(NL + "}" + NL, start) + 3 if name.startswith("function")             else source.index(NL, start) + 1
        picked.append(source[start:end])
    return NL.join(picked)


def test_home_event_board_selects_first_of_each_kind() -> None:
    """선정은 시간순이 아니라 종류별 첫 회차 먼저다.

    순수 시간순으로 되돌아가면 계절을 탄다 — 12월 창에서는 앞쪽을 nfp·cpi·gdp·fomc 가
    꽉 채워 실적이 홈에서 통째로 사라진다. 사용자가 묻는 것은 '다음 실적 언제'이고
    그 답은 데이터 밀도와 무관하게 나와야 한다.
    """
    program = _event_board_helpers() + r"""
const rows=[
  {date:'2026-12-04',kind:'nfp',status:'confirmed'},
  {date:'2026-12-09',kind:'fomc',status:'confirmed'},
  {date:'2026-12-10',kind:'cpi',status:'confirmed'},
  {date:'2026-12-23',kind:'gdp',status:'confirmed'},
  {date:'2027-01-08',kind:'nfp',status:'estimated'},
  {date:'2027-01-13',kind:'cpi',status:'estimated'},
  {date:'2027-02-24',kind:'earnings',status:'estimated',ticker:'NVDA'},
  {date:'2027-03-01',kind:'earnings',status:'estimated',ticker:'MSFT'},
];
console.log(JSON.stringify(evPick(rows,EV_BOARD_CAP).map(r=>[r.date,eventBoardKindKey(r)])));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    picked = json.loads(completed.stdout)
    kinds = [kind for _, kind in picked]
    assert "earnings:semiconductor" in kinds, f"반도체 실적이 빠지면 안 된다: {picked}"
    assert "earnings:bigtech" in kinds, f"빅테크 실적이 빠지면 안 된다: {picked}"
    assert len(set(["nfp", "fomc", "cpi", "gdp", "earnings:semiconductor", "earnings:bigtech"]) - set(kinds)) == 0
    dates = [date for date, _ in picked]
    assert dates == sorted(dates), "읽는 순서는 시간 순서여야 한다"


def test_home_event_board_marks_mixed_day_cluster_as_estimated() -> None:
    """같은 날 확정과 추정이 섞이면 추정으로 그린다 — 반대로는 절대 틀리지 않는다.

    groupFlowCalendarEvents 는 묶음 행에 첫 행의 status 를 물려준다. 2026-10-28 은
    확정 FOMC 와 추정 실적 3건이 같은 날이라, 그대로 두면 추정이 확정으로 표시된다.
    """
    program = _event_board_helpers() + r"""
const rows=[
  {date:'2026-10-28',kind:'earnings',status:'confirmed',ticker:'MSFT'},
  {date:'2026-10-28',kind:'earnings',status:'estimated',ticker:'META'},
  {date:'2026-10-28',kind:'fomc',status:'confirmed'},
  {date:'2026-11-06',kind:'nfp',status:'provisional'},
];
const grouped=groupFlowCalendarEvents(rows);
console.log(JSON.stringify(grouped.map(r=>[r.kind,r.clusterCount||1,evConfirmed(rows,r)])));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    verdicts = {kind: (count, ok) for kind, count, ok in json.loads(completed.stdout)}
    assert verdicts["earnings"] == (2, False), "추정이 섞인 묶음은 추정이다"
    assert verdicts["fomc"][1] is True, "단독 확정은 확정 그대로다"
    assert verdicts["nfp"][1] is False, "미지의 status 는 추정 쪽으로 떨어진다"


def test_home_event_board_never_uses_time_et_as_status_proxy() -> None:
    """time_et 공백과 estimated 가 지금 정확히 겹치지만 둘을 묶지 않는다.

    실측상 time_et 공백 34건 = estimated 34건이라 '최적화'하고 싶어지는 자리다.
    묶는 순간, 시각 없는 확정 일정이 하나 들어오면 화면이 거짓말한다.
    """
    source = (
        Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.js"
    ).read_text(encoding="utf-8")
    decider = source[source.index("function evConfirmed"):source.index("function evPick")]
    assert "time_et" not in decider, "확정/추정 판정에 time_et 이 들어가면 안 된다"
    board = source[source.index("function renderEventBoard"):]
    board = board[:board.index(NL + "}" + NL)]
    # time_et 이 나오는 줄은 전부 '무엇을 인쇄할지'를 고르는 줄이어야 한다.
    # 확정/추정을 가르는 이름(ok·word·is-estimated)과 같은 줄에 있으면 프록시가 된 것이다.
    for line in board.split(NL):
        if "time_et" not in line:
            continue
        assert "ev-meta" in line, f"time_et 은 메타 줄에서만 쓴다: {line.strip()[:80]}"
        for name in ("is-estimated", "confirmed", "word", "ok?"):
            assert name not in line, f"time_et 이 판정에 섞였다: {line.strip()[:80]}"
    assert "시각 미정" in board, "시각이 없으면 0시로 채우지 않고 말로 적는다"


def test_home_event_board_column_counts_collapse_without_orphans() -> None:
    """6장은 3열로도 2열로도 나누어떨어진다 — 마지막 줄에 고아 카드가 없다.

    빅테크·반도체를 별도 종류로 고른 뒤에는 모바일에서도 여섯 장을 유지해야 두 실적
    묶음이 모두 보인다. 2열 3행이므로 마지막 줄에도 고아 카드는 생기지 않는다.
    """
    css = (
        Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.css"
    ).read_text(encoding="utf-8")
    assert re.search(r"\.ev-cards\{[^}]*grid-template-columns:repeat\(3,", css)
    assert re.search(r"@media\(max-width:760px\)\{[^@]*?\.ev-cards\{grid-template-columns:repeat\(2,",
                     css, re.S)
    assert ".ev-card:nth-child(n+5){display:none}" not in css


def test_home_event_title_is_never_truncated() -> None:
    """제목은 말줄임하지 않는다 — 잘린 줄은 잘린 줄인지도 모른다 (DECISIONS 2026-09-14)."""
    css = (
        Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.css"
    ).read_text(encoding="utf-8")
    for selector in (r"\.ev-title b\{([^}]*)\}", r"\.ev-title em\{([^}]*)\}"):
        for body in re.findall(selector, css):
            assert "ellipsis" not in body and "line-clamp" not in body, body
            assert "nowrap" not in body, body
    assert re.search(r"\.ev-title b\{[^}]*word-break:keep-all", css)


def test_unscoped_event_track_height_override_is_gone() -> None:
    """무범위 `.event-track{height:3px}` 은 미래 탭 달력을 3px 상자에 가둔다.

    css 의 `.market-event-calendar .event-track` 는 height 를 선언하지 않아, 홈 레일용으로
    넣은 이 전역 규칙이 그대로 걸린다(min-height:138px 카드들이 뭉개진다). 이름 재사용이
    만든 충돌이라, 다시 들어오면 같은 자리에서 같은 일이 벌어진다.
    """
    css = (
        Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.css"
    ).read_text(encoding="utf-8")
    assert re.search(r"(?<![\w.-])\.event-track\{position:relative;height:3px", css) is None


def test_home_event_board_keeps_both_semis_of_one_week() -> None:
    """ASML(10-14)·TSMC(10-15)처럼 같은 주 같은 분류 실적은 한 카드로 묶여 둘 다 남는다."""
    program = _event_board_helpers() + r"""
const rows=[
  {date:'2026-10-14',kind:'cpi',status:'confirmed'},
  {date:'2026-10-14',kind:'earnings',status:'confirmed',ticker:'ASML',event_id:'asml'},
  {date:'2026-10-15',kind:'earnings',status:'confirmed',ticker:'TSM',event_id:'tsmc'},
  {date:'2026-10-28',kind:'earnings',status:'estimated',ticker:'MSFT',event_id:'msft'},
  {date:'2026-10-28',kind:'fomc',status:'confirmed'},
  {date:'2026-10-29',kind:'gdp',status:'confirmed'},
  {date:'2026-11-06',kind:'nfp',status:'confirmed'},
];
const semi=evPick(rows,EV_BOARD_CAP).find(r=>eventBoardKindKey(r)==='earnings:semiconductor');
console.log(JSON.stringify({tickers:semi.clusterTickers,dates:semi.clusterDates,count:semi.clusterCount}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True,
        text=True, encoding="utf-8",
    )
    semi = json.loads(completed.stdout)
    assert semi == {"tickers": ["ASML", "TSM"], "dates": ["2026-10-14", "2026-10-15"], "count": 2}


def _earnings_display_helpers() -> str:
    source = (Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.js").read_text(encoding="utf-8")
    helpers = [source[source.index("const EV_WEEKDAY="):source.index("/* 히어로 요약줄")]]
    for name in ("generatedDay", "dayDiff", "earningsGroup", "earningsCompanyName", "earningsMemberNames", "flowCalendarEventLabel", "eventBoardKindKey", "groupFlowCalendarEvents", "renderEventForecast", "earningsQuestionEvent", "earningsQuestionPending", "earningsQuestionNotice", "questionStatusLabel"):
        start = source.index(f"function {name}(")
        # Some small existing helpers have a single authored line.
        line_end = source.index(NL, start)
        end = line_end if source[start:line_end].endswith("}") else source.index(NL + "}" + NL, start) + 2
        helpers.append(source[start:end])
    return NL.join(helpers) + r"""
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const el=value=>value;
let mounted='';
const mount=value=>{mounted=value;};
const DATA={meta:{generated:'2026-10-15T00:40:00Z'},calendar_events:[
 {event_id:'asml',kind:'earnings',ticker:'ASML',date:'2026-10-14',time_et:'01:00',status:'confirmed',source_url:'https://asml.example/results'},
 {event_id:'tsmc',kind:'earnings',ticker:'TSM',date:'2026-10-15',time_et:'02:00',status:'confirmed',source_url:'https://tsmc.example/results'}
],event_consensus:{asml:[
 {metric:'eps',label:'USD 컨센서스 EPS',actual:null,consensus:'$12.47',previous:'$8.81',captured_at:'2026-10-11T09:43:03Z',source:'Nasdaq',source_url:'https://nasdaq.example/asml'},
 {metric:'revenue_reported',label:'매출 (백만 EUR)',actual:'EUR 11,662M',consensus:null,currency:'EUR',unit:'million_currency',share_basis:'not_applicable',accounting_basis:'US_GAAP',comparison_allowed:false,available_at:'2026-10-14T06:00:00Z',source:'ASML IR',source_url:'https://asml.example/release'},
 {metric:'gross_margin_reported',label:'매출총이익률 (%)',actual:'57.5%',consensus:null,unit:'percent',share_basis:'not_applicable',accounting_basis:'US_GAAP',comparison_allowed:false,available_at:'2026-10-14T06:00:00Z',source:'ASML IR',source_url:'https://asml.example/release'},
 {metric:'eps_reported',label:'공식 기본 EPS',actual:'EUR 12.95',consensus:null,previous:'EUR 7.59',unit:'currency_per_share',currency:'EUR',share_basis:'ordinary_share',eps_basis:'basic',accounting_basis:'US_GAAP',comparison_allowed:false,published_at:'2026-10-14T05:00:00Z',available_at:'2026-10-14T06:00:00Z',captured_at:'2026-10-14T06:00:00Z',source:'ASML IR',source_url:'https://asml.example/release'}
],tsmc:[{metric:'eps',label:'EPS',actual:null,consensus:'$4.45',previous:'$4.31',captured_at:'2026-10-07T06:06:56Z'}]}};
"""


def _run_earnings_js(program: str) -> dict:
    completed = subprocess.run(["node", "-e", _earnings_display_helpers() + program], check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(completed.stdout)


def test_earnings_release_state_uses_aware_time_and_kst_day() -> None:
    result = _run_earnings_js(r"""
const asml=DATA.calendar_events[0],tsmc=DATA.calendar_events[1];
const before={day:generatedDay(),asml:evReleaseState(asml),tsmc:evReleaseState(tsmc)};
DATA.meta.generated='2026-10-15T06:01:00Z';
const awaiting=evReleaseState(tsmc);
DATA.event_consensus.tsmc.push({published_at:'2026-10-15T06:00:00Z',actual:null});
const announced=evReleaseState(tsmc);
DATA.event_consensus.tsmc.push({actual:'NT$22',available_at:'2026-10-16T06:00:00Z'});
const future=evReleaseState(tsmc);
DATA.meta.generated='2026-10-14T23:40:00Z';
console.log(JSON.stringify({before,awaiting,announced,future,kst:generatedDay(),summer:new Date(evScheduledAt(tsmc)).toISOString(),winter:new Date(evScheduledAt({...tsmc,date:'2027-01-15'})).toISOString(),naive:evTimestamp('2026-10-15T06:00:00')}));
""")
    assert result["before"]["day"] == result["kst"] == "2026-10-15"
    assert result["before"]["asml"]["code"] == "reported"
    assert result["before"]["tsmc"]["code"] == "scheduled"
    assert result["awaiting"]["code"] == "awaiting"
    assert result["announced"]["code"] == result["future"]["code"] == "announced"
    assert result["summer"] == "2026-10-15T06:00:00.000Z"
    assert result["winter"] == "2027-01-15T07:00:00.000Z"
    assert result["naive"] is None


def test_recent_earnings_remain_visible_without_retaining_past_macro_events() -> None:
    result = _run_earnings_js(r"""
const rows=[...DATA.calendar_events,{...DATA.calendar_events[0],event_id:'old',date:'2026-10-07'},{kind:'cpi',date:'2026-10-14',event_id:'past-cpi'}];
const visible=evFuture(rows,generatedDay());
console.log(JSON.stringify({ids:visible.map(row=>row.event_id),board:renderEventBoard(rows,generatedDay())}));
""")
    assert result["ids"] == ["asml", "tsmc"]
    board = result["board"]
    assert 'href="#today/event/asml"' in board and 'href="#today/event/tsmc"' in board
    assert "ASML · 발표값 확인" in board and "TSMC · 발표 예정" in board
    assert "EUR 12.95" in board and "$12.47" in board and "$4.45" in board
    assert "EUR 11,662M" in board and "57.5%" in board
    assert board.index("EUR 12.95") < board.index("$12.47")
    assert board.index("EUR 12.95") < board.index("EUR 11,662M")
    assert 'data-afp-label="실제"' in board and 'data-afp-label="예상"' in board
    assert "D--" not in board and "1일 전" in board


def test_incompatible_earnings_basis_has_no_beat_colour_and_keeps_sources() -> None:
    result = _run_earnings_js(r"""
const rows=DATA.event_consensus.asml;
const native=rows.find(row=>row.metric==='eps_reported');
console.log(JSON.stringify({tone:evAfpTone({metric:'eps',actual:'$14',consensus:'$12',comparison_allowed:false}),native:evAfpTone(native),adr:evRowBasis({currency:'USD',unit:'currency_per_adr',share_basis:'ADR_unit',eps_basis:'diluted',accounting_basis:'TIFRS'}),table:evAfpTable([...rows,{...native,source_url:'https://asml.example/statements',label:'<bad>'}])}));
""")
    assert result["tone"] == result["native"] == ""
    assert "is-beat" not in result["table"] and "is-miss" not in result["table"]
    assert "EUR · 보통주 · 기본 EPS · US GAAP" in result["table"]
    assert result["adr"] == "USD · ADR · 희석 EPS · 대만 IFRS"
    assert "직접 비교하지 않습니다" in result["table"]
    assert "https://asml.example/release" in result["table"] and "https://asml.example/statements" in result["table"]
    assert "&lt;bad&gt;" in result["table"]


def test_weekly_earnings_detail_separates_each_company_release_state() -> None:
    result = _run_earnings_js(r"""
renderEventForecast('asml');
console.log(JSON.stringify({html:mounted}));
""")
    html = result["html"]
    assert "반도체 실적 2건 (ASML · TSMC)" in html
    assert 'data-earnings-id="asml"' in html and 'data-earnings-id="tsmc"' in html
    assert "ASML · 발표값 확인" in html and "TSMC · 발표 예정" in html
    assert "15:00 KST" in html and "EUR 12.95" in html
    assert "USD 컨센서스 EPS" in html and "공식 기본 EPS" in html


def test_earnings_question_waits_for_comparable_evidence_without_changing_outcomes() -> None:
    result = _run_earnings_js(r"""
const asml={id:'asml-eps-beat-2026q3',domain:'earnings',status:'active',resolved:false,deadline:'2026-10-14',latest_prob:60};
const tsmc={...asml,id:'tsmc-eps-beat-2026q3',deadline:'2026-10-15',latest_prob:83};
const before=JSON.stringify([asml,tsmc]);
console.log(JSON.stringify({asml:questionStatusLabel(asml),tsmc:questionStatusLabel(tsmc),notice:earningsQuestionNotice(asml),futureNotice:earningsQuestionNotice(tsmc),resolved:questionStatusLabel({...asml,status:'resolved',resolved:true}),unchanged:before===JSON.stringify([asml,tsmc])}));
""")
    assert result["asml"]["text"] == "판정 대기"
    assert result["tsmc"]["text"] == "진행 중" and result["futureNotice"] == ""
    assert "USD ADR 컨센서스를 직접 비교하지 않습니다" in result["notice"]
    assert 'href="#today/event/asml"' in result["notice"]
    assert result["resolved"]["text"] == "완료" and result["unchanged"] is True


def _original_daily_flow_helpers() -> str:
    source = _dashboard_source()
    model = re.search(
        r"function addFlowCalendarMonths\([\s\S]+?\n}\nfunction drawOriginalWeeklyFlow", source)
    calendar = re.search(
        r"function earningsGroup\([\s\S]+?\n}\nfunction buildRebasedFlowModel", source)
    assert model and calendar, "daily model and calendar mapping must remain testable"
    metadata = re.search(r"const EVENT_KIND_META=.*?;", source)
    assert metadata
    return (metadata.group(0) + NL + model.group(0).removesuffix("\nfunction drawOriginalWeeklyFlow") + NL
            + calendar.group(0).removesuffix("\nfunction buildRebasedFlowModel") + NL
            + "const trackDay=value=>Date.parse(value+'T00:00:00Z')/86400000;" + NL)


def _original_daily_fixture(asof: str = "2026-10-09", calendar_end: str = "2027-04-09") -> dict:
    from datetime import date
    from ai_fc.scenario import future_trading_days, load_calendar_contract

    root = Path(__file__).resolve().parents[2]
    dates = [asof] + [day.isoformat() for day in future_trading_days(
        date.fromisoformat(asof), 252, load_calendar_contract(root))]
    values = [100.0] + [100.0 + index * 0.12 + (-1.0 if index % 2 else 1.0)
                       for index in range(1, 253)]
    bands = {q: [100.0] + [100.0 + index * 0.1 + offset for index in range(1, 253)]
             for q, offset in (("p10", -6), ("p25", -3), ("p50", 0), ("p75", 3), ("p90", 6))}
    return {
        "status": "ok", "asof": asof, "anchor": 100.0,
        "calendar_end": calendar_end, "probability_unit": "fraction",
        "source_snapshot_id": "baseline-fixture", "shadow": {"passed": True},
        "default_end_index": max(i for i, day in enumerate(dates) if day <= calendar_end),
        "dates": dates,
        "scenarios": {"S1": {"status": "ok", "probability": 0.92,
                             "probability_unit": "fraction", "member_path_index": 123,
                             "values": values, "conditional_bands": bands}},
        "risk": {"probability_unit": "fraction", "probability_space": "original_all_gbm_ensemble",
                 "threshold": 90.0, "cumulative_touch": [index / 1000 for index in range(253)],
                 "levels": ["저"] * 253},
    }


def test_original_daily_default_uses_six_calendar_months_and_raw_member_values() -> None:
    fixture = _original_daily_fixture()
    program = _original_daily_flow_helpers() + "const daily=" + json.dumps(fixture) + r""";
const sc={asof:daily.asof,anchor:daily.anchor,corr10:90,snapshot_id:daily.source_snapshot_id};
const track={status:'ok',cut:'2026-11-20',actual:[['2026-07-30',95],['2026-10-09',100]]};
const six=buildOriginalDailyFlowModel(sc,daily,track),compare=buildOriginalDailyFlowModel(sc,daily,track,'S1','compare');
const full=buildOriginalDailyFlowModel(sc,daily,track,'S1','full');
console.log(JSON.stringify({status:six.status,count:six.dates.length,end:six.calendarEnd,last:six.dates.at(-1),
  startDay:six.startDay,expectedStart:trackDay('2026-07-30'),endValue:six.values.at(-1),raw:daily.scenarios.S1.values[124],
  median:six.conditionalBands.p50.at(-1),risk:six.riskValues.at(-1),share:six.scenarioProbability,
  compareEnd:compare.calendarEnd,fullCount:full.dates.length,months:[
    addFlowCalendarMonths('2026-08-31'),addFlowCalendarMonths('2023-08-31'),
    addFlowCalendarMonths('2026-12-31'),addFlowCalendarMonths('2026-02-30')]}));
"""
    result = _run_js_file(program)
    assert result["status"] == "ok"
    assert result["count"] == 125 and result["end"] == result["last"] == "2027-04-09"
    assert result["endValue"] == result["raw"] != result["median"]
    assert result["risk"] == 0.124 and result["share"] == 0.92
    assert result["startDay"] == result["expectedStart"]
    assert result["compareEnd"] == "2026-11-20" and result["fullCount"] == 253
    assert result["months"] == ["2027-02-28", "2024-02-29", "2027-06-30", None]


def test_original_daily_holiday_endpoint_and_calendar_events_share_trade_grid() -> None:
    fixture = _original_daily_fixture("2026-08-31", "2027-02-28")
    program = _original_daily_flow_helpers() + "const daily=" + json.dumps(fixture) + r""";
const sc={asof:daily.asof,anchor:daily.anchor,corr10:90,snapshot_id:daily.source_snapshot_id};
const events=[{date:'2026-12-25',kind:'fomc',title:'휴장일 일정'},
 {date:'2027-01-20',kind:'cpi',title:'CPI'}, {date:'2027-03-01',kind:'fomc',title:'범위 밖'}];
const m=buildOriginalDailyFlowModel(sc,daily,null,'S1','six_months',events);
console.log(JSON.stringify({status:m.status,end:m.calendarEnd,last:m.dates.at(-1),
  events:m.events,holidayPoint:m.dates.includes('2026-12-25'),weekendPoint:m.dates.includes('2027-02-28')}));
"""
    result = _run_js_file(program)
    assert result["status"] == "ok" and result["end"] == "2027-02-28"
    assert result["last"] == "2027-02-26"
    assert result["holidayPoint"] is False and result["weekendPoint"] is False
    assert [event["date"] for event in result["events"]] == ["2026-12-25", "2027-01-20"]
    assert result["events"][0]["mapped_date"] == "2026-12-28"
    assert result["events"][0]["short_label"] == "12/25 FOMC"
    assert result["events"][0]["full_label"] == "휴장일 일정"
    for event in result["events"]:
        assert fixture["dates"][event["index"]] == event["mapped_date"]


def test_original_daily_model_fails_closed_for_mixed_snapshots_units_and_bad_grid() -> None:
    fixture = _original_daily_fixture()
    program = _original_daily_flow_helpers() + "const daily=" + json.dumps(fixture) + r""";
const sc={asof:daily.asof,anchor:daily.anchor,corr10:90,snapshot_id:daily.source_snapshot_id};
const checks=[null,{...daily,status:'blocked',reason:'selection blocked'},
 {...daily,source_snapshot_id:'wrong'}, {...daily,shadow:{passed:false}}, {...daily,probability_unit:'percent'},
 {...daily,calendar_end:'2026-12-31'}, {...daily,dates:daily.dates.slice(0,20)},
 {...daily,risk:{...daily.risk,cumulative_touch:daily.risk.cumulative_touch.slice(1)}},
 {...daily,scenarios:{S1:{...daily.scenarios.S1,status:'blocked',reason:'too few eligible members'}}},
 {...daily,scenarios:{S1:{...daily.scenarios.S1,probability_unit:'percent',probability:92}}},
 {...daily,scenarios:{S1:{...daily.scenarios.S1,values:daily.scenarios.S1.values.slice(1)}}},
 {...daily,dates:daily.dates.map((day,i)=>i===1?'2026-02-30':day)}];
console.log(JSON.stringify({results:checks.map(item=>buildOriginalDailyFlowModel(sc,item)),
 wrongAnchor:buildOriginalDailyFlowModel({...sc,anchor:101},daily)}));
"""
    result = _run_js_file(program)
    for blocked in [*result["results"], result["wrongAnchor"]]:
        assert blocked["status"] == "blocked" and blocked["reason"]
        assert "values" not in blocked and "scenarioProbability" not in blocked
    source = _dashboard_source()
    assert "일간 대표 경로 보류 · 기존 주간 기준선 표시" in source
    assert "S1 시나리오 비중" in source and "최빈군 대표 경로" in source
    assert "horizon='six_months'" in source
    css = (Path(__file__).parents[1] / "ai_fc" / "dashboard_parts" / "dashboard.css").read_text(encoding="utf-8")
    assert ".daily-flow-readout{display:grid" in css, "모바일도 선택 거래일·값을 그림 밖에서 읽어야 한다"


def test_daily_flow_fetch_rejects_mixed_artifact_identity_before_assigning() -> None:
    source = _dashboard_source()
    reference = re.search(r"function dailyFlowSemanticReferenceMatches\([\s\S]+?\n}\n", source)
    loader = re.search(r"async function ensureDailyFlow\([\s\S]+?\n}\n", source)
    assert reference and loader
    program = reference.group(0) + loader.group(0) + r"""
let DAILY_FLOW_PROMISE=null,DAILY_FLOW_ERROR=null;
const window={},ref={contract_id:'daily_flow_artifact_v1',artifact_id:'daily-flow:2026-10-09:r1',
 source_snapshot_id:'scenario:2026-10-09:r1',source_snapshot_sha256:'sourcehash',input_sha256:'inputhash',
 version:'daily-flow-modal-medoid-v1',model_content_sha256:'modelhash'};
const summary={status:'ok',semantic_reference:ref,deferred_paths:{required:true,loaded:false,url:'daily_flow.json'}};
let DATA={daily_flow:summary},fetch=async()=>({ok:true,json:async()=>({contract_id:'daily_flow_route_v1',
 semantic_reference:ref,data:{daily_flow:{status:'ok',semantic_reference:{...ref,input_sha256:'mixed'},dates:['wrong']}}})});
(async()=>{
 let rejected='';try{await ensureDailyFlow();}catch(error){rejected=error.message;}
 const preserved=DATA.daily_flow===summary&&!DATA.daily_flow.dates&&!DATA.daily_flow.deferred_paths.loaded;
 fetch=async()=>({ok:true,json:async()=>({contract_id:'daily_flow_route_v1',semantic_reference:ref,
 data:{daily_flow:{status:'ok',semantic_reference:{...ref},dates:['2026-10-09']}}})});
 await ensureDailyFlow();
 console.log(JSON.stringify({rejected,preserved,loaded:DATA.daily_flow.deferred_paths.loaded,
  dates:DATA.daily_flow.dates,error:DAILY_FLOW_ERROR}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = _run_js_file(program)
    assert result["rejected"] == "daily flow semantic reference mismatch" and result["preserved"] is True
    assert result["loaded"] is True and result["dates"] == ["2026-10-09"] and result["error"] is None


def test_daily_chart_mobile_zoom_starts_at_readable_native_width_only_for_daily_flow() -> None:
    source = _dashboard_source()
    match = re.search(r"function chartZoomInitialWidth\([\s\S]+?\n}\n", source)
    assert match
    result = _run_js(match.group(0) + r"""
const daily={querySelector:()=>({viewBox:{baseVal:{width:1160}}})},other={querySelector:()=>null};
console.log(JSON.stringify({dailyMobile:chartZoomInitialWidth(daily,366,true),
  otherMobile:chartZoomInitialWidth(other,366,true),desktop:chartZoomInitialWidth(daily,900,false)}));
""")
    assert result == {"dailyMobile": 1160, "otherMobile": 366, "desktop": 900}
    assert "events.map(event=>[event.index,event.short_label])" in source
    assert 'class="daily-flow-events"' in source and "esc(event.full_label)" in source
