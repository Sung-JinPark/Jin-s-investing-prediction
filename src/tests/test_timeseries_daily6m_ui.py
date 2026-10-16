"""Daily research charts retain source probabilities, dates, and snapshot identity."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest


SOURCE = Path(__file__).parents[1] / "ai_fc/dashboard_parts/dashboard.js"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def _projection() -> dict:
    dates = []
    cursor = date(2026, 1, 31)
    while cursor <= date(2026, 7, 30):
        if cursor.weekday() < 5:
            dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    records = []
    for index, session in enumerate(dates):
        median = 100 + index * 0.1
        records.append({
            "date": session,
            "median_index": median,
            "band_index": {
                "p10": median * 0.85, "p25": median * 0.95,
                "p50": median, "p75": median * 1.05, "p90": median * 1.15,
            },
            "probability_up_from_previous": 0.55 if index % 2 == 0 else 0.45,
            "probability_up_from_origin": 0.70,
            "median_return_from_origin": median / 100 - 1,
        })
    return {
        "schema_version": 1,
        "status": "research_preview",
        "numbers_visible": True,
        "probability_unit": "fraction",
        "run_id": "daily-ui-fixture",
        "as_of": "2026-01-30T21:00:00+00:00",
        "anchor_date": "2026-01-30",
        "anchor": {"date": "2026-01-30", "value": 100.0},
        "forecast_end_date": "2026-07-30",
        "content_hash": "fixture-content-hash",
        "path_count": 20000,
        "dates": dates,
        "records": records,
        "sample_paths": [
            {"path_id": f"simulation-{member}", "endpoint_percentile": [0.1, 0.25, 0.5, 0.75, 0.9][member], "values": [
                row["median_index"] * (1 + (member - 2) * 0.02 + ((index % 3) - 1) * 0.01)
                for index, row in enumerate(records)
            ]}
            for member in range(5)
        ],
        "history": {"dates": ["2026-01-29", "2026-01-30"], "index": [99, 100]},
        "realized": {"dates": dates[:2], "index": [101, 98]},
    }


def _helpers() -> str:
    source = _source()
    formatting = source[source.index("const tsLevel="):source.index("function tsTipMarkup")]
    daily = source[source.index("function tsDailyMonthEnd"):source.index("let TIMESERIES_DAILY_RESIZE")]
    escaping = next(line for line in source.splitlines() if line.startswith("const esc="))
    return escaping + "\n" + formatting + daily


def _run(tmp_path: Path, program: str, *, helpers: bool = True) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    path = tmp_path / "daily_ui_probe.js"
    path.write_text((_helpers() if helpers else "") + "\n" + program, encoding="utf-8")
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr[:3000]
    return json.loads(result.stdout)


def test_calendar_controls_slice_the_same_daily_bundle_without_reforecast(tmp_path: Path) -> None:
    projection = _projection()
    out = _run(tmp_path, "const ts=" + json.dumps(projection) + r""";
const before=JSON.stringify(ts),one=tsDailyChartModel(ts,1),three=tsDailyChartModel(ts,3),six=tsDailyChartModel(ts);
const resized=tsDailyChartModel(ts,6,375),reloaded=tsDailyChartModel(JSON.parse(JSON.stringify(ts)));
process.stdout.write(JSON.stringify({
  monthEnd:tsDailyMonthEnd('2026-01-31',1),
  aprilMonthEnd:tsDailyMonthEnd('2026-04-30',6),
  februaryMonthEnd:tsDailyMonthEnd('2026-02-28',6),
  one:one.endDate,three:three.endDate,six:six.endDate,
  counts:[one.records.length,three.records.length,six.records.length],
  sameRows:one.records.every((row,i)=>row===six.records[i]),
  primaryIds:[one,three,six,resized,reloaded].map(model=>model.primary.path_id),
  samePrimaryPrefix:[one,three,resized,reloaded].every(model=>model.primary.values.every((value,i)=>value===six.primary.values[i])),
  sourcePrimary:six.primary.values.every((value,i)=>value===ts.sample_paths[2].values[i]),
  samplesUnchanged:six.samples.every((row,i)=>JSON.stringify(row.values)===JSON.stringify(ts.sample_paths[i].values)),
  inputUnchanged:before===JSON.stringify(ts),
  probability:tsDailyDescribe(ts,six,six.origin+1).rows.find(row=>row.name==='전 거래일보다 오를 가능성').value,
  originProbability:ts.records[0].probability_up_from_origin,
  realized:six.realized.map(row=>row.date),
  rangeZero:six.py(0),rangeHalf:six.py(0.5),rangeOne:six.py(1),probT:six.probT,probH:six.probH
}));
""")
    assert out["monthEnd"] == "2026-02-28"
    assert out["aprilMonthEnd"] == "2026-10-31"
    assert out["februaryMonthEnd"] == "2026-08-31"
    assert [out["one"], out["three"], out["six"]] == ["2026-02-27", "2026-04-30", "2026-07-30"]
    assert out["counts"][0] < out["counts"][1] < out["counts"][2] == len(projection["records"])
    assert out["sameRows"] and out["samplesUnchanged"] and out["inputUnchanged"]
    assert out["primaryIds"] == ["simulation-2"] * 5
    assert out["samePrimaryPrefix"] and out["sourcePrimary"]
    assert out["probability"] == "55.0%" and out["originProbability"] == 0.70
    assert out["realized"] == projection["realized"]["dates"]
    assert out["rangeOne"] == out["probT"]
    assert out["rangeHalf"] == out["probT"] + out["probH"] / 2
    assert out["rangeZero"] == out["probT"] + out["probH"]


def test_primary_selection_uses_exact_endpoint_metadata_not_array_position(tmp_path: Path) -> None:
    out = _run(tmp_path, "const ts=" + json.dumps(_projection()) + """;
const source=ts.sample_paths[2];ts.sample_paths=[source,ts.sample_paths[4],ts.sample_paths[0],ts.sample_paths[3],ts.sample_paths[1]];
const before=JSON.stringify(ts),m=tsDailyChartModel(ts),html=timeseriesDailySvg(ts,m,true);
process.stdout.write(JSON.stringify({id:m.primary.path_id,percentile:m.primary.endpoint_percentile,
  values:JSON.stringify(m.primary.values)===JSON.stringify(source.values),unchanged:before===JSON.stringify(ts),
  overlay:(html.match(/data-daily-sample=/g)||[]).length,excluded:!html.includes('data-daily-sample="simulation-2"')}));
""")
    assert out["id"] == "simulation-2" and out["percentile"] == 0.5
    assert out["values"] and out["unchanged"] and out["excluded"] and out["overlay"] == 4


def test_issue_time_is_kst_while_source_asof_remains_unchanged(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const asOf='2026-10-09T22:00:00+00:00';
process.stdout.write(JSON.stringify({display:tsDailyIssuedAt(asOf),source:asOf}));
""")
    assert out["display"] == "2026. 10. 10. 07:00 KST"
    assert out["source"] == "2026-10-09T22:00:00+00:00"
    source = _source()
    assert 'title="${esc(ts.as_of||\'\')}"' in source
    assert "미국 거래일 종가 기준" in source


def test_hold_without_a_run_labels_check_time_without_relabeling_published_run(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const as_of='2026-10-12T11:06:27.237443+00:00';
const absent={status:'hold',numbers_visible:false,as_of,gate:{reasons:['no independent daily6m forecast exists']}};
const published={...absent,run_id:'original-run',anchor_date:'2026-10-09'};
const before=JSON.stringify([absent,published]);
process.stdout.write(JSON.stringify({unissued:tsDailyMetadataMarkup(absent),published:tsDailyMetadataMarkup(published),
  missing:tsDailyMetadataMarkup({status:'absent'}),unknown:tsDailyMetadataMarkup({status:'hold',as_of,gate:{reasons:['required source NASDAQCOM stale']}}),
  unchanged:before===JSON.stringify([absent,published])}));
""")
    assert "아직 발행된 일별 전망이 없습니다" in out["unissued"]
    assert "검사 시각 2026. 10. 12. 20:06 KST" in out["unissued"]
    assert "발행 2026. 10. 12. 20:06 KST" in out["published"]
    assert "검사 시각" not in out["published"]
    assert "2026-10-09 미국 거래일 종가 기준" in out["published"]
    for key in ("unissued", "published"):
        assert 'title="2026-10-12T11:06:27.237443+00:00"' in out[key]
    assert "검사 시각" not in out["missing"] and "발행 준비 중" not in out["missing"]
    assert "기준 시각 2026. 10. 12. 20:06 KST" in out["unknown"]
    assert "검사 시각" not in out["unknown"] and "아직 발행된" not in out["unknown"]
    assert out["unchanged"]


def test_hold_reasons_have_readable_labels_and_retain_every_original_reason(tmp_path: Path) -> None:
    reasons = [
        "no independent daily6m forecast exists",
        "required source NASDAQCOM stale", "required source VIX stale",
        "required source DGS2 missing", "required source curve stale",
        "required source dollar stale", "필수 시장 입력 신선도 초과: DGS10",
        "예측 원점 경과 거래일 10: 보류 임계 10 도달", "unrecognized audit reason",
    ]
    out = _run(tmp_path, "const reasons=" + json.dumps(reasons) + """;
process.stdout.write(JSON.stringify({labels:reasons.map(tsHoldReasonLabel),html:tsHoldReasonsMarkup(reasons)}));
""")
    assert out["labels"][:7] == [
        "아직 발행된 6개월 일별 전망이 없습니다.",
        "NASDAQ 종가 자료가 갱신 기준을 넘었습니다.", "변동성(VIX) 자료가 갱신 기준을 넘었습니다.",
        "2년물 금리 필수 자료가 없습니다.", "장단기 금리차 자료가 갱신 기준을 넘었습니다.",
        "달러지수 자료가 갱신 기준을 넘었습니다.", "10년물 금리 자료가 갱신 기준을 넘었습니다.",
    ]
    assert out["labels"][7:] == reasons[7:]
    assert out["html"].count("<li ") == len(reasons)
    for reason in reasons:
        assert f'title="{reason}"' in out["html"]


def test_hold_reason_markup_escapes_unknown_audit_text(tmp_path: Path) -> None:
    out = _run(tmp_path, r'''
const reason='<img src=x onerror="bad()"> & source';
process.stdout.write(JSON.stringify({label:tsHoldReasonLabel(reason),html:tsHoldReasonsMarkup([reason])}));
''')
    assert out["label"] == '<img src=x onerror="bad()"> & source'
    assert "<img" not in out["html"]
    assert out["html"].count("&lt;img") == 2
    assert out["html"].count("&quot;bad()&quot;") == 2
    assert out["html"].count("&amp; source") == 2


def test_failed_validation_is_not_described_as_only_waiting_for_new_inputs(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const model_id='shadow.mf_dfm_varx_calibrated_v8';
const failed={model_id,numbers_visible:false,gate:{sealed_gate_pass:false,operational_pass:false}};
const before=JSON.stringify(failed);
process.stdout.write(JSON.stringify({copy:tsHoldCopy(failed),missing:tsHoldCopy({model_id,numbers_visible:false}),unchanged:before===JSON.stringify(failed)}));
""")
    for key in ("copy", "missing"):
        assert out[key]["title"] == "표시 조건 확인 대기"
        assert "검증과 입력 자료" in out[key]["lead"]
        assert out[key]["metadata"] == ""
    assert out["unchanged"]


def test_v8_hold_renderer_uses_latest_input_status_and_keeps_numbers_hidden(tmp_path: Path) -> None:
    source = _source()
    render = source[source.index("function renderTimeseries(initialState)"):source.index("const GC_API=")]
    out = _run(tmp_path, """
let captured='';
let DATA={timeseries:{model_id:'shadow.mf_dfm_varx_calibrated_v8',status:'shadow_operational_hold',
  numbers_visible:false,as_of:'2026-10-02',knowledge_cutoff:'2026-10-13T00:58:05+00:00',
  gate:{sealed_gate_pass:true,operational_pass:false,reasons:['필수 시장 입력 신선도 초과: NASDAQCOM']},
  anchor:{value:987654},horizons:{'1':{median_index:123456}},path:{index:[654321]}}};
const before=JSON.stringify(DATA);
const TS_TABS=[['summary'],['path'],['drivers'],['backtest']];
const el=html=>({html}),mount=root=>{captured=root.html;};
const tsDailyCta=()=>'<a href="#timeseries/daily">향후 6개월을 하루씩 보기</a>';
const tsFootnote=()=>'',timeseriesTabsMarkup=()=>'',timeseriesSpecCard=()=>'';
const timeseriesV13TabEnabled=()=>false,renderTimeseriesV13VolPanel=()=>'';
const bindTimeseriesV13VolInteractions=()=>{},bindTimeseriesTabs=()=>{};
""" + render + """
renderTimeseries('summary');const v8=captured,unchanged=before===JSON.stringify(DATA);
DATA.timeseries={model_id:'shadow.nasdaq_pit_hybrid_distribution_v5',numbers_visible:false};
renderTimeseries('summary');const legacy=captured;
process.stdout.write(JSON.stringify({v8,legacy,unchanged}));
""")
    assert "최신 입력 자료 갱신 대기" in out["v8"]
    assert "예측 숫자와 그래프를 숨겼습니다" in out["v8"]
    assert "NASDAQ 종가 자료가 갱신 기준을 넘었습니다" in out["v8"]
    assert "예측 기준일 2026-10-02" in out["v8"]
    assert "마지막 확인 2026. 10. 13. 09:58 KST" in out["v8"]
    assert 'title="2026-10-13T00:58:05+00:00"' in out["v8"]
    assert "워크포워드와 구간 적중률 검사가 끝나기 전" not in out["v8"]
    assert "워크포워드와 구간 적중률 검사가 끝나기 전" in out["legacy"]
    assert '#timeseries/daily' in out["v8"]
    for hidden in ("987654", "123456", "654321", "<svg"):
        assert hidden not in out["v8"]
    assert out["unchanged"]


@pytest.mark.parametrize("problem", ["probability", "probability_unit", "path_count_missing", "path_count_type", "path_count_small", "crossing", "date", "sample", "hold"])
def test_invalid_daily_inputs_fail_instead_of_clipping_or_hiding(tmp_path: Path, problem: str) -> None:
    ts = _projection()
    if problem == "probability":
        ts["records"][0]["probability_up_from_previous"] = 55
    elif problem == "probability_unit":
        ts["probability_unit"] = "percent"
    elif problem == "path_count_missing":
        ts.pop("path_count")
    elif problem == "path_count_type":
        ts["path_count"] = "20000"
    elif problem == "path_count_small":
        ts["path_count"] = 4
    elif problem == "crossing":
        ts["records"][0]["band_index"]["p25"] = 110
    elif problem == "date":
        ts["records"][1]["date"] = ts["records"][0]["date"]
    elif problem == "sample":
        ts["sample_paths"][0]["values"].pop()
    else:
        ts["numbers_visible"] = False
        ts["status"] = "hold"
    out = _run(tmp_path, "const ts=" + json.dumps(ts) + """;
let rejected=false;try{tsDailyChartModel(ts);}catch(error){rejected=true;}
process.stdout.write(JSON.stringify({rejected}));
""")
    assert out["rejected"]


@pytest.mark.parametrize("problem", [
    "missing", "duplicate", "metadata_absent", "wrong_type", "near_half", "length", "nonfinite",
])
def test_invalid_representative_member_fails_without_silent_fallback(tmp_path: Path, problem: str) -> None:
    projection = _projection()
    if problem == "missing":
        projection["sample_paths"][2]["endpoint_percentile"] = 0.6
    elif problem == "duplicate":
        projection["sample_paths"][0]["endpoint_percentile"] = 0.5
    elif problem == "metadata_absent":
        projection["sample_paths"][2].pop("endpoint_percentile")
    elif problem == "wrong_type":
        projection["sample_paths"][2]["endpoint_percentile"] = "0.5"
    elif problem == "near_half":
        projection["sample_paths"][2]["endpoint_percentile"] = 0.5000000000001
    elif problem == "length":
        projection["sample_paths"][2]["values"].pop()
    program = "const ts=" + json.dumps(projection) + ";\n"
    if problem == "nonfinite":
        program += "ts.sample_paths[2].values[4]=Infinity;\n"
    out = _run(tmp_path, program + """
const before=JSON.stringify(ts);let rejected=false,message='';
try{tsDailyChartModel(ts);}catch(error){rejected=true;message=String(error.message);}
process.stdout.write(JSON.stringify({rejected,message,unchanged:before===JSON.stringify(ts)}));
""")
    assert out["rejected"] and out["unchanged"]
    assert out["message"], "The invalid representative member must have a visible failure reason"


def test_chart_preserves_daily_points_and_only_toggles_real_simulated_samples(tmp_path: Path) -> None:
    out = _run(tmp_path, "const ts=" + json.dumps(_projection()) + r""";
const m=tsDailyChartModel(ts,6,375),plain=timeseriesDailySvg(ts,m),sampled=timeseriesDailySvg(ts,m,true);
const match=sampled.match(/data-daily-sample="simulation-0" points="([^"]+)"/),points=match[1].split(' ');
const probability=plain.match(/data-daily-probability="previous_session" points="([^"]+)"/)[1].split(' ');
const primary=plain.match(/data-daily-primary="simulation-2" points="([^"]+)"/)[1].split(' ');
const primarySource=ts.sample_paths.find(row=>row.endpoint_percentile===0.5);
process.stdout.write(JSON.stringify({
  defaultSamples:(plain.match(/data-daily-sample=/g)||[]).length,
  displayedSamples:(sampled.match(/data-daily-sample=/g)||[]).length,
  memberPoints:points.length,probabilityPoints:probability.length,
  primaryPoints:primary.length,
  exactPrimaryPoints:primary.every((point,i)=>point===`${m.x(m.origin+i).toFixed(2)},${m.y(i?primarySource.values[i-1]:ts.anchor.value).toFixed(2)}`),
  samePrimaryWhenSamplesEnabled:sampled.includes(`data-daily-primary="simulation-2" points="${primary.join(' ')}"`),
  noDuplicatedPrimary:!sampled.includes('data-daily-sample="simulation-2"'),
  exactSamplePoint:points[4]===`${m.x(m.origin+4).toFixed(2)},${m.y(ts.sample_paths[0].values[3]).toFixed(2)}`,
  ticks:m.tickIndices.map(index=>m.x(index)),width:m.W,
  noPathTouchProbability:!sampled.includes('누적 터치확률'),
  disclosure:plain.includes('80%/50%')&&plain.includes('2026-07-30')
}));
""")
    assert out["defaultSamples"] == 0 and out["displayedSamples"] == 4
    assert out["memberPoints"] == out["probabilityPoints"] + 1
    assert out["primaryPoints"] == out["memberPoints"]
    assert out["exactPrimaryPoints"] and out["samePrimaryWhenSamplesEnabled"] and out["noDuplicatedPrimary"]
    assert out["probabilityPoints"] == len(_projection()["records"])
    assert out["exactSamplePoint"] and out["noPathTouchProbability"] and out["disclosure"]
    assert all(0 <= tick <= out["width"] for tick in out["ticks"])
    assert all(right - left >= 82 for left, right in zip(out["ticks"], out["ticks"][1:]))


def test_representative_display_preserves_source_distribution_and_payload_hash(tmp_path: Path) -> None:
    out = _run(tmp_path, "const ts=" + json.dumps(_projection()) + r""";
const digest=value=>require('node:crypto').createHash('sha256').update(JSON.stringify(value)).digest('hex');
const before=digest(ts),contentHash=ts.content_hash,records=JSON.stringify(ts.records);
const m=tsDailyChartModel(ts),html=timeseriesDailySvg(ts,m);
const points=rows=>rows.map(([x,y])=>`${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
const seq=[{position:m.origin,q:Object.fromEntries(['p10','p25','p50','p75','p90'].map(key=>[key,ts.anchor.value]))},
  ...ts.records.map((row,i)=>({position:m.origin+i+1,q:row.band_index}))];
const expectedBand=(hi,lo)=>points([...seq.map(row=>[m.x(row.position),m.y(row.q[hi])]),...[...seq].reverse().map(row=>[m.x(row.position),m.y(row.q[lo])])]);
const median=html.match(/class="[^"]*\bts-daily-median-line\b[^"]*" points="([^"]+)"/)[1];
const probability=html.match(/data-daily-probability="previous_session" points="([^"]+)"/)[1];
const outer=html.match(/class="ts-band-outer" points="([^"]+)"/)[1];
const inner=html.match(/class="ts-band-inner" points="([^"]+)"/)[1];
process.stdout.write(JSON.stringify({
  payloadHash:before===digest(ts),contentHash:contentHash===ts.content_hash,
  recordsUnchanged:records===JSON.stringify(ts.records),
  median:median===points(seq.map(row=>[m.x(row.position),m.y(row.q.p50)])),
  probability:probability===points(ts.records.map((row,i)=>[m.x(m.origin+i+1),m.py(row.probability_up_from_previous)])),
  outer:outer===expectedBand('p90','p10'),inner:inner===expectedBand('p75','p25')
}));
""")
    assert all(out.values())


def test_tooltip_and_accessible_readout_distinguish_primary_change_from_ensemble_probability(tmp_path: Path) -> None:
    out = _run(tmp_path, "const ts=" + json.dumps(_projection()) + r""";
const m=tsDailyChartModel(ts),d=tsDailyDescribe(ts,m,m.origin+1),html=timeseriesDailySvg(ts,m);
const primary=d.rows.find(row=>row.name==='대표 시나리오'),median=d.rows.find(row=>row.name==='날짜별 중앙값');
const probability=d.rows.find(row=>row.name==='전 거래일보다 오를 가능성');
const next=tsDailyDescribe(ts,m,m.origin+2),nextPrimary=next.rows.find(row=>row.name==='대표 시나리오');
const detail=rows=>rows.map(row=>`${row.name} ${row.value} ${row.sub||''}`).join(' ');
process.stdout.write(JSON.stringify({
  values:primary?.value===tsLevel(ts.sample_paths[2].values[0])&&median?.value===tsLevel(ts.records[0].median_index),
  primaryChange:detail(d.rows).includes(tsPct(ts.sample_paths[2].values[0]/ts.anchor.value-1)),
  nextPrimaryChange:detail(next.rows).includes(tsPct(ts.sample_paths[2].values[1]/ts.sample_paths[2].values[0]-1)),
  probability:probability?.value==='55.0%'&&probability.sub.includes('전체')&&probability.sub.includes('20,000'),
  accessible:d.speak.includes('대표 시나리오')&&d.speak.includes('날짜별 중앙값')&&d.speak.includes('55.0%'),
  aria:html.includes('대표 시나리오')&&html.includes('날짜별 중앙값'),
  differentValues:primary?.value!==median?.value
}));
""")
    assert all(out.values())


def test_keyboard_and_touch_link_both_charts_to_the_same_real_daily_row(tmp_path: Path) -> None:
    source = _source()
    binder = source[source.index("function bindTsHover"):source.index("function tsRangeModel")]
    out = _run(tmp_path, binder + "\nconst ts=" + json.dumps(_projection()) + r""";
const m=tsDailyChartModel(ts);
const node=()=>({attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=String(v);},addEventListener(k,v){this.listeners[k]=v;}});
const svg=node(),overlay=node(),cross=node(),price=node(),prob=node(),readout={textContent:''};
svg.hasAttribute=()=>true;svg.getBoundingClientRect=()=>({left:0,top:0,width:m.W,height:m.H});
const chart={nextElementSibling:null,querySelector(s){return ({svg,'[data-ts-overlay]':overlay,'.ts-cross':cross,'[data-daily-price-dot]':price,'[data-daily-prob-dot]':prob,'.ts-readout':readout})[s];}};
const host={querySelector:()=>chart};
globalThis.document={getElementById:()=>null};globalThis.window={matchMedia:()=>({matches:false})};
bindTimeseriesDailyChart(host,ts,m);
svg.listeners.focus();const historicalHidden=prob.attrs.opacity==='0';
const key={key:'ArrowRight',preventDefault(){}};
for(let i=0;i<=m.origin;i++)svg.listeners.keydown(key);
const first={cross:cross.attrs.x1,priceX:price.attrs.cx,priceY:price.attrs.cy,probX:prob.attrs.cx,probY:prob.attrs.cy,text:readout.textContent};
const touchIndex=m.origin+10;
overlay.listeners.pointerdown({clientX:m.x(touchIndex),clientY:m.py(0.5)});
process.stdout.write(JSON.stringify({
  historicalHidden,
  sameX:first.cross===first.priceX&&first.priceX===first.probX,
  probabilityIsSource:Number(first.probY)===m.py(ts.records[0].probability_up_from_previous),
  primaryIsSource:Number(first.priceY)===m.y(ts.sample_paths[2].values[0]),
  bothValues:first.text.includes('대표 시나리오')&&first.text.includes('날짜별 중앙값'),
  firstDate:first.text.includes(ts.records[0].date),
  touchDate:readout.textContent.includes(ts.records[9].date),
  touchX:Number(prob.attrs.cx)===m.x(touchIndex)
}));
""")
    assert all(out.values())


def test_hover_markers_preserve_pointer_selection_and_stay_out_of_zoom(tmp_path: Path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    out = _run(tmp_path, "const ts=" + json.dumps(_projection()) + """;
process.stdout.write(JSON.stringify({html:timeseriesDailySvg(ts,tsDailyChartModel(ts))}));
""")
    css = (SOURCE.parent / "dashboard.css").read_text(encoding="utf-8")
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(channel="chrome", headless=True)
        except playwright.Error as exc:
            pytest.skip(f"installed Chrome not available: {exc}")
        try:
            page = browser.new_page()
            page.set_content(f'<style>{css}</style><div id="normal" class="ts-daily-page">{out["html"]}</div><div id="zoom" class="chart-zoom-content">{out["html"]}</div>')
            page.locator("[data-daily-price-dot],[data-daily-prob-dot]").evaluate_all("nodes=>nodes.forEach(node=>node.setAttribute('opacity','1'))")
            for marker in ("[data-daily-price-dot]", "[data-daily-prob-dot]"):
                assert page.locator("#normal " + marker).evaluate("node=>getComputedStyle(node).display") != "none"
                assert page.locator("#normal " + marker).evaluate("node=>getComputedStyle(node).pointerEvents") == "none"
                assert page.locator("#zoom " + marker).evaluate("node=>getComputedStyle(node).display") == "none"
            # Visible selection markers sit above the pointer overlay in SVG
            # order. Hit testing must still reach the overlay at their centers.
            page.locator("#normal [data-daily-price-dot],#normal [data-daily-prob-dot]").evaluate_all("nodes=>nodes.forEach(node=>{node.setAttribute('cx','100');node.setAttribute('cy','100');})")
            assert page.locator("#normal svg").evaluate("""svg=>{
                const point=svg.createSVGPoint();point.x=100;point.y=100;
                const screen=point.matrixTransform(svg.getScreenCTM());
                return document.elementFromPoint(screen.x,screen.y)?.hasAttribute('data-ts-overlay');
            }""")
            for line in (".ts-daily-primary-line", ".ts-daily-median-line", ".ts-daily-prob-line"):
                assert page.locator("#zoom " + line).evaluate("node=>getComputedStyle(node).display") != "none"
            for container in ("#normal", "#zoom"):
                primary = page.locator(container + " .ts-daily-primary-line")
                median = page.locator(container + " .ts-daily-median-line")
                assert primary.evaluate("node=>getComputedStyle(node).fill") == "none"
                assert primary.evaluate("node=>getComputedStyle(node).stroke") != "none"
                assert primary.evaluate("node=>parseFloat(getComputedStyle(node).strokeWidth)") > median.evaluate("node=>parseFloat(getComputedStyle(node).strokeWidth)")
                assert median.evaluate("node=>getComputedStyle(node).strokeDasharray") != "none"
        finally:
            browser.close()


def _loader_program(projection: dict, summary: dict) -> str:
    source = _source()
    loader = source[source.index("async function ensureTimeseriesDaily"):source.index("let DATA=null")]
    return (
        "let TIMESERIES_DAILY_PROMISE=null,TIMESERIES_DAILY_ERROR=null;\n"
        "globalThis.window={};Object.defineProperty(globalThis,'crypto',{value:require('node:crypto').webcrypto,configurable:true});\n"
        "let DATA={timeseries_daily:" + json.dumps(summary) + "};\n"
        "const raw=" + json.dumps(json.dumps({"schema_version": 1, "contract_id": "timeseries_daily_route_v1", "data": {"timeseries_daily": projection}}, separators=(",", ":"))) + ";\n"
        + loader
    )


def _summary(projection: dict) -> dict:
    raw = json.dumps({"schema_version": 1, "contract_id": "timeseries_daily_route_v1", "data": {"timeseries_daily": projection}}, separators=(",", ":"))
    return {
        **{key: projection[key] for key in ("schema_version", "status", "numbers_visible", "probability_unit", "run_id", "as_of", "anchor_date", "content_hash")},
        "deferred_data": {
            "required": True, "loaded": False, "url": "timeseries_daily.json",
            "payload_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            **{key: projection[key] for key in ("run_id", "as_of", "anchor_date", "content_hash")},
        },
    }


def test_loader_deduplicates_requests_and_recovers_from_http_failure(tmp_path: Path) -> None:
    projection = _projection()
    program = _loader_program(projection, _summary(projection)) + r"""
let calls=0;globalThis.fetch=async()=>{calls++;if(calls===1)return {ok:false,status:503};return {ok:true,text:async()=>raw};};
(async()=>{let rejected=false;try{await ensureTimeseriesDaily();}catch(error){rejected=true;}
const reset=TIMESERIES_DAILY_PROMISE===null;
await Promise.all([ensureTimeseriesDaily(),ensureTimeseriesDaily()]);await ensureTimeseriesDaily();
process.stdout.write(JSON.stringify({rejected,reset,calls,loaded:DATA.timeseries_daily.deferred_data.loaded,rows:DATA.timeseries_daily.records.length}));})().catch(e=>{console.error(e);process.exit(1);});
"""
    out = _run(tmp_path, program)
    assert out["rejected"] and out["reset"] and out["loaded"]
    assert out["calls"] == 2 and out["rows"] == len(projection["records"])


@pytest.mark.parametrize("problem", ["body_hash", "run_id", "as_of", "anchor_date", "content_hash", "crypto"])
def test_loader_rejects_mismatched_snapshot_without_replacing_summary(tmp_path: Path, problem: str) -> None:
    projection = _projection()
    summary = _summary(projection)
    if problem == "body_hash":
        summary["deferred_data"]["payload_sha256"] = "0" * 64
    elif problem != "crypto":
        summary["deferred_data"][problem] = "another-snapshot"
    program = _loader_program(projection, summary)
    if problem == "crypto":
        program += "Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});\n"
    program += r"""
globalThis.fetch=async()=>({ok:true,text:async()=>raw});
(async()=>{const original=DATA.timeseries_daily;let rejected=false;
try{await ensureTimeseriesDaily();}catch(error){rejected=true;}
process.stdout.write(JSON.stringify({rejected,unchanged:DATA.timeseries_daily===original,notLoaded:!DATA.timeseries_daily.deferred_data.loaded,reset:TIMESERIES_DAILY_PROMISE===null}));})().catch(e=>{console.error(e);process.exit(1);});
"""
    assert all(_run(tmp_path, program).values())


def test_inflight_sidecar_does_not_replace_a_new_base_dataset(tmp_path: Path) -> None:
    projection = _projection()
    program = _loader_program(projection, _summary(projection)) + r"""
let finish;globalThis.fetch=async()=>({ok:true,text:()=>new Promise(resolve=>{finish=resolve;})});
(async()=>{const pending=ensureTimeseriesDaily();
await new Promise(resolve=>setImmediate(resolve));
const replacement={...DATA.timeseries_daily,run_id:'new-base-dataset'};
DATA={timeseries_daily:replacement};finish(raw);
let rejected=false;try{await pending;}catch(error){rejected=true;}
process.stdout.write(JSON.stringify({rejected,unchanged:DATA.timeseries_daily===replacement,noOldRows:!DATA.timeseries_daily.records,reset:TIMESERIES_DAILY_PROMISE===null}));})().catch(e=>{console.error(e);process.exit(1);});
"""
    assert all(_run(tmp_path, program).values())


def test_route_change_during_fetch_does_not_render_the_old_daily_screen(tmp_path: Path) -> None:
    source = _source()
    route = source[source.index("async function route()"):source.index("window.addEventListener('hashchange',route)")]
    program = r"""
let ROUTE_EPOCH=0,TIMESERIES_DAILY_RESIZE=null,release;
let DATA={timeseries_daily:{deferred_data:{required:true,loaded:false}}};
const rendered=[],loading=[],location={hash:'#timeseries/daily'};
const noop=()=>{},window={scrollTo:noop},history={replaceState:noop};
const document={body:{dataset:{},classList:{remove:noop,contains:()=>false}},querySelector:()=>null,querySelectorAll:()=>[]};
const briefingLayer={hidden:true},shareLayer={hidden:true},commandLayer={hidden:true},mobileMore=null;
const closeQuickPeek=noop,closeChartZoom=noop,setBriefing=noop,setShare=noop,paintRailSubNav=noop,enhanceChartZoom=noop,renderCompareTray=noop,recordRecent=noop,setDrawer=noop,setCommand=noop;
const legacyRouteRedirect=hash=>hash,parseCanonicalRoute=hash=>({view:'timeseries',section:'timeseries',arg:{tsTab:hash.endsWith('/daily')?'daily':null}});
const renderTimeseriesDaily=(_data,state)=>loading.push(state.loading?'loading':'failed');
const ensureTimeseriesDaily=()=>new Promise(resolve=>{release=resolve;});
const VIEWS={timeseries:arg=>rendered.push(arg.tsTab||'summary')},renderOverview=noop,requestAnimationFrame=noop,app=noop;
""" + route + r"""
(async()=>{const pending=route();location.hash='#timeseries';await route();release(true);await pending;
process.stdout.write(JSON.stringify({onlyNewScreen:JSON.stringify(rendered)==='["summary"]',onlyInitialLoading:JSON.stringify(loading)==='["loading"]',epoch:ROUTE_EPOCH}));})().catch(e=>{console.error(e);process.exit(1);});
"""
    out = _run(tmp_path, program, helpers=False)
    assert out["onlyNewScreen"] and out["onlyInitialLoading"] and out["epoch"] == 2


def test_daily_route_is_independent_of_v8_hold_and_discloses_validation_limits() -> None:
    source = _source()
    render = source[source.index("function renderTimeseries(initialState)"):source.index("const GC_API=")]
    assert render.index("if(dailyRequested==='daily')") < render.index("if(ts.model_id===")
    assert render.count("${tsDailyCta()}") == 2, "Legacy and HOLD summaries both expose the daily route"
    assert "${tsBrief}${tsDailyCta()}" in source
    assert "const on=key==='daily'||enabled.includes(key)" in source
    daily = source[source.index("function renderTimeseriesDaily("):source.index("function bindTimeseriesTabs")]
    for label in ("전진 검증 전", "이 모델의 성적이 아닙니다", "마지막 알려진 값", "같은 모의 경로", "다시 불러오기", "페이지 새로고침"):
        assert label in daily
    assert "TIMESERIES_DAILY_RESIZE.disconnect()" in source
    assert "enhanceChartZoom(host)" in daily


def test_compacted_daily_chart_bundle_parses(tmp_path: Path) -> None:
    from ai_fc import dashboard
    import re

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    compacted = dashboard._compact_static_bundle(dashboard.load_template())
    scripts = re.findall(r"<script>(.*?)</script>", compacted, re.S)
    assert scripts
    for index, script in enumerate(scripts):
        path = tmp_path / f"daily_compacted_{index}.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[:2000]


def test_static_comment_compaction_preserves_literals_regex_and_runtime(tmp_path: Path) -> None:
    from ai_fc import dashboard

    source = r'''
/* removable-source-block
   whose bytes should not be shipped */
const literal='/* keep string */';
const nested=`visible first line
/* keep template text */
${`nested ${'/* keep nested string */'}`}
visible last line`;
const pattern=/["'`{}]/;
const slashes=/\/\* visible \*\//;
let controlMatch=false;
if(true) /["'`{}]/.test('`') && (controlMatch=true);
const quotient=8/2;
const/* keep token separation */value=3;
function automaticSemicolon(){return
/* removable-asi-block */
value;}
const trailing='quoted'; // trailing comment must remain on its own line
const afterComment=7;
process.stdout.write(JSON.stringify({literal,nested,regex:pattern.test('`'),slash:slashes.test('/* visible */'),controlMatch,quotient,value,asi:automaticSemicolon()===undefined,afterComment}));
'''
    compacted = dashboard._compact_static_bundle("<script>" + source + "</script>")
    body = compacted.removeprefix("<script>").removesuffix("</script>")
    assert "removable-source-block" not in body and "removable-asi-block" not in body
    assert "/* keep template text */" in body and "/* keep nested string */" in body
    original = _run(tmp_path, source, helpers=False)
    compressed = _run(tmp_path, body, helpers=False)
    assert compressed == original
