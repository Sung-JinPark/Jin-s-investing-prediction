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
const timeseriesTabsMarkup=()=>'',timeseriesSpecCard=()=>'';
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
    assert '향후 6개월을 하루씩 보기' not in out["v8"]
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
  accessible:plain.includes('role="img"')&&plain.includes('2026-07-30'),
  noCaption:!plain.includes('timeseries-band-caption')
}));
""")
    assert out["defaultSamples"] == 0 and out["displayedSamples"] == 4
    assert out["memberPoints"] == out["probabilityPoints"] + 1
    assert out["primaryPoints"] == out["memberPoints"]
    assert out["exactPrimaryPoints"] and out["samePrimaryWhenSamplesEnabled"] and out["noDuplicatedPrimary"]
    assert out["probabilityPoints"] == len(_projection()["records"])
    assert out["exactSamplePoint"] and out["noPathTouchProbability"] and out["accessible"] and out["noCaption"]
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
    binder = source[source.index("function tsTipMarkup"):source.index("function tsRangeModel")]
    document_stub = "const docListeners={};globalThis.document={addEventListener(k,fn){docListeners[k]=fn;}};\n"
    out = _run(tmp_path, document_stub + binder + "\nconst ts=" + json.dumps(_projection()) + r""";
const m=tsDailyChartModel(ts);
const node=()=>({attrs:{},listeners:{},setAttribute(k,v){this.attrs[k]=String(v);},addEventListener(k,v){this.listeners[k]=v;}});
const svg=node(),overlay=node(),cross=node(),price=node(),prob=node(),readout={textContent:''};
svg.hasAttribute=()=>true;svg.getBoundingClientRect=()=>({left:0,top:0,width:m.W,height:m.H});
const chart={nextElementSibling:null,querySelector(s){return ({svg,'[data-ts-overlay]':overlay,'.ts-cross':cross,'[data-daily-price-dot]':price,'[data-daily-prob-dot]':prob,'.ts-readout':readout})[s];}};
const host={querySelector:()=>chart};
const tip={style:{},innerHTML:'',offsetWidth:180,offsetHeight:80};
document.getElementById=id=>id==='tip'?tip:null;globalThis.window={matchMedia:()=>({matches:false}),innerWidth:390,innerHeight:844};
bindTimeseriesDailyChart(host,ts,m);
svg.listeners.focus();const historicalHidden=prob.attrs.opacity==='0';
const key={key:'ArrowRight',preventDefault(){}};
for(let i=0;i<=m.origin;i++)svg.listeners.keydown(key);
const first={cross:cross.attrs.x1,priceX:price.attrs.cx,priceY:price.attrs.cy,probX:prob.attrs.cx,probY:prob.attrs.cy,text:readout.textContent};
const keyboardTip=tip.style.display==='block'&&tip.innerHTML.includes(ts.records[0].date)&&tip.innerHTML.includes('55.0%');
const touchIndex=m.origin+10;
overlay.listeners.pointerdown({pointerType:'touch',clientX:m.x(touchIndex),clientY:m.py(0.5)});
const touchDate=readout.textContent.includes(ts.records[9].date),touchX=Number(prob.attrs.cx)===m.x(touchIndex);
const touchTip=tip.style.display==='block'&&tip.innerHTML.includes(ts.records[9].date);
overlay.listeners.pointerleave({pointerType:'touch'});const touchTipPersists=tip.style.display==='block';
svg.listeners.keydown({key:'Escape'});const escapeHidesTip=tip.style.display==='none';
overlay.listeners.pointermove({pointerType:'mouse',clientX:m.x(m.origin+1),clientY:m.py(0.5)});
const mouseTip=tip.style.display==='block'&&tip.innerHTML.includes(ts.records[0].date);
docListeners.pointerdown({target:{closest:()=>null}});const outsideTapHidesTip=tip.style.display==='none';
process.stdout.write(JSON.stringify({
  historicalHidden,
  sameX:first.cross===first.priceX&&first.priceX===first.probX,
  probabilityIsSource:Number(first.probY)===m.py(ts.records[0].probability_up_from_previous),
  primaryIsSource:Number(first.priceY)===m.y(ts.sample_paths[2].values[0]),
  bothValues:first.text.includes('대표 시나리오')&&first.text.includes('날짜별 중앙값'),
  firstDate:first.text.includes(ts.records[0].date),
  touchDate,touchX,keyboardTip,touchTip,touchTipPersists,escapeHidesTip,mouseTip,outsideTapHidesTip
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
    navigation = source[source.index("function privateDashboardDestination("):source.index("let ROUTE_EPOCH=")]
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
""" + navigation + route + r"""
(async()=>{const pending=route();location.hash='#timeseries';await route();release(true);await pending;
process.stdout.write(JSON.stringify({onlyNewScreen:JSON.stringify(rendered)==='["summary"]',onlyInitialLoading:JSON.stringify(loading)==='["loading"]',epoch:ROUTE_EPOCH}));})().catch(e=>{console.error(e);process.exit(1);});
"""
    out = _run(tmp_path, program, helpers=False)
    assert out["onlyNewScreen"] and out["onlyInitialLoading"] and out["epoch"] == 2


def test_daily_route_is_independent_of_v8_hold_and_has_no_promotional_or_repeated_copy() -> None:
    source = _source()
    render = source[source.index("function renderTimeseries(initialState)"):source.index("const GC_API=")]
    assert render.index("if(dailyRequested==='daily')") < render.index("if(ts.model_id===")
    assert "tsDailyCta" not in source
    assert "향후 6개월을 하루씩 보기" not in source
    assert "const on=key==='daily'||enabled.includes(key)" in source
    daily = source[source.index("function renderTimeseriesDaily("):source.index("function bindTimeseriesTabs")]
    for label in ("전진 검증 전", "이 모델의 성적이 아닙니다", "연구 프리뷰", "전진 성능: 미검증", "ts-daily-reading", "ts-daily-validation"):
        assert label not in daily
    for label in ("다시 불러오기", "페이지 새로고침"):
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


def test_forward_record_summarizes_resolutions_without_claiming_validation() -> None:
    """A9(2026-10-21): 해소 원장 요약은 채점·판정이 아니다 — 정정은 최신 개정만, 행 0이면 None."""
    from ai_fc.timeseries_daily6m.display import forward_record

    rows = [
        {"resolution_id": "a:2026-10-15", "forecast_id": "a", "date": "2026-10-15", "brier": 0.14, "inside_p10_p90": True},
        {"resolution_id": "a:2026-10-16", "forecast_id": "a", "date": "2026-10-16", "brier": 0.28, "inside_p10_p90": False},
        {"resolution_id": "b:2026-10-16", "forecast_id": "b", "date": "2026-10-16", "brier": 0.18, "inside_p10_p90": True},
        {"resolution_id": "b:2026-10-16:fix", "forecast_id": "b", "date": "2026-10-16", "brier": 0.10,
         "inside_p10_p90": True, "supersedes": "b:2026-10-16", "resolution_kind": "correction"},
        {"resolution_id": "broken", "forecast_id": "c", "date": "2026-10-17", "brier": None},
    ]
    record = forward_record(rows)
    assert (record["resolved_rows"], record["forecasts"], record["resolved_dates"]) == (3, 2, 2)
    assert record["mean_brier"] == round((0.14 + 0.28 + 0.10) / 3, 4)
    assert record["covered_p10_p90_rows"] == 2 and record["no_information_brier"] == 0.25
    assert record["nominal_interval_coverage"] == 0.8 and record["independent_rows"] is False
    assert record["predictive_validation"] == "not_established" and record["display_only"] is True
    assert (record["first_date"], record["last_date"]) == ("2026-10-15", "2026-10-16")
    empty = forward_record([])
    assert empty["resolved_rows"] == 0 and empty["mean_brier"] is None and empty["covered_p10_p90_rows"] is None
    assert empty["predictive_validation"] == "not_established"


def test_forward_record_loader_fails_closed_without_a_ledger(tmp_path: Path) -> None:
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import load_forward_record

    assert load_forward_record(tmp_path)["resolved_rows"] == 0
    path = tmp_path / C.RESOLUTION_LEDGER
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    broken = load_forward_record(tmp_path)
    assert broken["resolved_rows"] == 0 and broken["mean_brier"] is None and "ledger_error" in broken


def test_daily_record_markup_shows_dash_without_resolutions(tmp_path: Path) -> None:
    program = """
const withRows=tsDailyRecordMarkup({resolved_rows:5,forecasts:2,resolved_dates:4,mean_brier:0.2284,no_information_brier:0.25,covered_p10_p90_rows:4,first_date:'2026-10-15',last_date:'2026-10-20',predictive_validation:'not_established'});
const empty=tsDailyRecordMarkup({resolved_rows:0,mean_brier:null,covered_p10_p90_rows:null,predictive_validation:'not_established'});
const absent=tsDailyRecordMarkup({});
process.stdout.write(JSON.stringify({withRows,empty,absent}));
"""
    out = _run(tmp_path, program)
    full = out["withRows"]
    assert "0.228" in full and "4/5" in full and "2 / 4" in full and "검증 전" in full
    assert "무정보 0.25" in full and "predictive_validation=not_established" in full
    for markup in (out["empty"], out["absent"]):
        assert markup.count("—") >= 3 and "검증 전" in markup and "not_established" in markup
    for markup in out.values():
        assert "전진 검증 전" not in markup and "연구 프리뷰" not in markup
    source = _source()
    daily = source[source.index("function renderTimeseriesDaily("):source.index("function bindTimeseriesTabs")]
    assert "tsDailyRecordMarkup(DATA.timeseries_daily_record||{})" in daily
    from ai_fc import dashboard
    wiring = Path(dashboard.__file__).read_text(encoding="utf-8")
    assert '"timeseries_daily_record": timeseries_daily_record' in wiring


# ── P4 표시 정직성 (2026-11-11) ─────────────────────────────────────────────────
# 실제 원장 오라클은 '고정 원점 집합 + 목표일 <= 2026-11-09' 로 묶는다 — 해소가 늘어도 깨지지 않는다.
# 실제 저장소는 읽기만 하고, 실행 전후 원장·발행본·상수 파일 해시가 같음을 확인한다.
REPO = Path(__file__).resolve().parents[2]
P4_LAST_DATE = "2026-11-09"
P4_LAST_ORIGIN = "2026-11-06"


def _file_digests(root: Path) -> dict[str, str]:
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import DISPLAY_CONSTANTS_RELATIVE

    paths = [root / C.RESOLUTION_LEDGER, root / C.FORECAST_LEDGER, root / DISPLAY_CONSTANTS_RELATIVE,
             *sorted((root / C.STORE_RELATIVE / "runs").glob("*.json"))]
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _p4_inputs() -> tuple[list[dict], dict, list[dict], dict]:
    """(고정 해소 행, run 요약, 발행 원장 행, 상수) — 실제 저장소 읽기 전용."""
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import load_display_constants, read_ledgered_run, run_summary
    from ai_fc.timeseries_daily6m.pipeline import read_chain

    forecasts = read_chain(REPO, C.FORECAST_LEDGER)
    fixed = [row for row in forecasts if row["origin_session"] <= P4_LAST_ORIGIN]
    ids = {row["forecast_id"] for row in fixed}
    rows = [row for row in read_chain(REPO, C.RESOLUTION_LEDGER)
            if row["forecast_id"] in ids and row["date"] <= P4_LAST_DATE]
    runs = {row["forecast_id"]: run_summary(read_ledgered_run(REPO, row)) for row in fixed}
    constants, status = load_display_constants(REPO)
    assert status == "ok"
    return rows, runs, forecasts, constants


@pytest.fixture(scope="module")
def p4_record() -> dict:
    from ai_fc.timeseries_daily6m.display import forward_record

    before = _file_digests(REPO)
    rows, runs, forecasts, constants = _p4_inputs()
    record = forward_record(rows, runs=runs, forecasts=forecasts, constants=constants)
    assert _file_digests(REPO) == before
    return record


def test_display_is_outside_the_daily6m_model_code_hash_and_constants_are_pinned(tmp_path: Path) -> None:
    import inspect

    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import DISPLAY_CONSTANTS_RELATIVE, load_display_constants

    assert "display.py" not in inspect.getsource(C.model_code_hash)
    constants, status = load_display_constants(REPO)
    assert status == "ok" and constants["notice"] == "참고 의견, 매매 신호 아님"
    tampered = json.loads((REPO / DISPLAY_CONSTANTS_RELATIVE).read_text(encoding="utf-8"))
    tampered["shock_mark_abs_daily_z"] = 3.0
    target = tmp_path / DISPLAY_CONSTANTS_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(tampered), encoding="utf-8")
    assert load_display_constants(tmp_path) == (None, "constants_hash_mismatch")
    assert load_display_constants(tmp_path / "absent") == (None, "constants_file_missing")


def test_constant_baseline_reproduces_from_the_design_window_archive() -> None:
    """c = 2007~2014 NASDAQCOM 상승일 빈도 — 저장소 아카이브에서 재계산(네트워크 없음)."""
    import pyarrow.parquet as pq

    from ai_fc.timeseries_daily6m.contracts import canonical_hash
    from ai_fc.timeseries_daily6m.display import load_display_constants

    baseline = load_display_constants(REPO)[0]["up_day_constant_baseline"]
    frame = pq.read_table(REPO / baseline["source_path"], filters=[("series_id", "=", "NASDAQCOM")]).to_pandas()
    frame["day"] = frame["observation_time"].astype(str).str[:10]
    frame = frame[(frame["day"] >= baseline["previous_session"]) & (frame["day"] <= baseline["window_end"])].sort_values("day")
    pairs = [[day, float(value)] for day, value in zip(frame["day"], frame["value"])]
    up = sum(1 for before, after in zip(pairs, pairs[1:]) if after[1] > before[1])
    assert canonical_hash(pairs) == baseline["source_series_hash"]
    assert (up, len(pairs) - 1) == (baseline["k_up"], baseline["n_sessions"]) == (1114, 2014)
    assert baseline["c"] == up / (len(pairs) - 1) and pairs[1][0] == "2007-01-03"


def test_live_ledger_oracles_use_target_date_equal_weights(p4_record: dict) -> None:
    record = p4_record
    assert record["honesty_status"] == "ok" and record["scoring_excluded"] is True
    assert record["coverage_raw"] == {"k": 71, "n": 132}
    assert round(record["coverage_date_equal"], 3) == 0.648
    assert record["coverage_freshest_origin"] == {"k": 10, "n": 18}
    assert record["coverage_weekly_final"] == {"k": 20, "n": 37}
    assert record["effective_n_dates"] == 18 == record["n_dates"]
    assert (record["n_issuances"], record["n_active_weekly_lineages"]) == (15, 4)
    assert record["skill_judgeable"] is False and record["single_episode"] is True
    assert record["label"] == "원점 기준 누적 수준 p10~p90 (날짜별 pointwise)"
    assert record["increment_coverage"]["freshest_origin"] == {"k": 11, "n": 18}
    assert record["brier_in_sample_climatology"]["label"] == "in-sample"
    assert record["brier_const_prefixed"]["c"] == 0.5531
    # 원시 132행 Brier 와 목표일 균등 Brier 는 다른 숫자다(원장 가중 무변경 · 읽기 투영만).
    assert record["mean_brier"] == 0.2452 and record["brier_date_equal"] == 0.2417


def test_zeroing_the_1105_shock_reproduces_the_audit_sensitivity() -> None:
    """감사 도구(D6C-2)와 대조: 11-05 로그수익을 0 으로 바꾸면 원시 커버리지 0.538 → 0.735."""
    import math

    from ai_fc.timeseries_daily6m import display

    rows, runs, forecasts, _ = _p4_inputs()
    joined = display._resolved_rows(rows, runs, forecasts)
    shock_row = next(row for row in rows if row["date"] == "2026-11-05")
    shock = math.log(shock_row["actual_index"] / shock_row["actual_previous_index"])
    actual = {row["date"]: row["actual_index"] for row in rows}
    anchors = {row["forecast_id"]: _anchor_index(row) for row in forecasts if row["forecast_id"] in runs}
    inside = []
    for row in joined:
        level = math.log(actual[row["date"]] / anchors[row["forecast_id"]])
        if row["origin"] < "2026-11-05" <= row["date"]:
            level -= shock
        inside.append(row["level"][0] <= level <= row["level"][2])
    assert round(sum(inside) / len(inside), 3) == 0.735
    assert sum(row["inside"] for row in joined) == 71


def _anchor_index(forecast_row: dict) -> float:
    """run_summary 는 원점 대비 로그비만 갖는다 — 원점 종가는 발행본에서 다시 읽는다."""
    from ai_fc.timeseries_daily6m.display import read_ledgered_run

    return float(read_ledgered_run(REPO, forecast_row)["anchor_index"])


def test_null_band_is_bit_identical_and_brackets_the_audit_p_range(p4_record: dict) -> None:
    from ai_fc.timeseries_daily6m.display import forward_record

    rows, runs, forecasts, constants = _p4_inputs()
    again = forward_record(rows, runs=runs, forecasts=forecasts, constants=constants)
    assert again["null_band"] == p4_record["null_band"]
    assert again["null_band_sensitivity_freshest"] == p4_record["null_band_sensitivity_freshest"]
    for band in (p4_record["null_band"], p4_record["null_band_sensitivity_freshest"]):
        assert band["approximate"] is True and band["label"] == "model-true 근사"
        assert (band["seed"], band["draws"], band["df"]) == (20261111, 20000, 4)
        assert 0.08 <= band["p_raw_le_observed"] <= 0.16
        assert band["p05"] < p4_record["coverage_date_equal"] < band["p95"]
    assert p4_record["null_band"]["method"] != p4_record["null_band_sensitivity_freshest"]["method"]


def test_rows_after_the_1105_shock_from_earlier_origins_are_marked_not_dropped(p4_record: dict) -> None:
    from ai_fc.timeseries_daily6m import display

    rows, runs, forecasts, constants = _p4_inputs()
    joined = display._resolved_rows(rows, runs, forecasts)
    marked = display.shock_marked_keys(joined, display.shock_onsets(joined, constants["shock_mark_abs_daily_z"]))
    target = {(row["forecast_id"], row["date"]) for row in joined if row["origin"] < "2026-11-05" <= row["date"]}
    assert len(target) == 39 and len({fid for fid, _ in target}) == 13
    assert target <= marked
    shock = p4_record["post_shock_rows"]
    assert "2026-11-05" in shock["shock_dates"] and shock["marked"] == len(marked)
    assert shock["coverage_excl"]["n"] + shock["marked"] == shock["n"] == 132


def _synthetic_kappa_run(log_return: float, sigma: float, lam: float) -> dict:
    import math

    half = 1.2815515655446004 * sigma
    return {
        "anchor_date": "2026-11-05", "anchor_index": 100.0 * math.exp(log_return),
        "history": {"dates": ["2026-11-04", "2026-11-05"], "index": [100.0, 100.0 * math.exp(log_return)]},
        "model_config": {"ewma_lambda": lam},
        "records": [{"daily_return_quantiles": {"p10": -half, "p25": -half / 2, "p50": 0.0, "p75": half / 2, "p90": half}}],
    }


def test_origin_vol_lag_kappa_warns_only_for_the_shock_origin() -> None:
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import origin_vol_lag, read_ledgered_run
    from ai_fc.timeseries_daily6m.pipeline import read_chain

    shock = origin_vol_lag(_synthetic_kappa_run(-0.0568, 0.0133, 0.94), 1.10)
    assert shock["triggered"] is True and 1.40 < shock["kappa"] < 1.50
    assert shock["label"] == "폭이 원점일 충격 미반영(1세션 지연)"
    calm = origin_vol_lag(_synthetic_kappa_run(0.0, 0.0133, 0.94), 1.10)
    assert calm["triggered"] is False and calm["label"] is None
    real = {row["origin_session"]: row for row in read_chain(REPO, C.FORECAST_LEDGER)}
    kappa_1022 = origin_vol_lag(read_ledgered_run(REPO, real["2026-10-22"]), 1.10)
    kappa_1105 = origin_vol_lag(read_ledgered_run(REPO, real["2026-11-05"]), 1.10)
    assert kappa_1022["triggered"] is False and round(kappa_1022["kappa"], 2) == 1.08
    assert kappa_1105["triggered"] is True and round(kappa_1105["kappa"], 2) == 1.43
    with pytest.raises(ValueError):
        origin_vol_lag({**_synthetic_kappa_run(-0.01, 0.01, 0.94), "anchor_date": "2026-11-06"}, 1.10)


def test_run_disclosure_flags_the_1106_near_tie_and_renders_labels(tmp_path: Path) -> None:
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import read_ledgered_run, run_disclosure
    from ai_fc.timeseries_daily6m.pipeline import read_chain

    before = _file_digests(REPO)
    real = {row["origin_session"]: row for row in read_chain(REPO, C.FORECAST_LEDGER)}
    near = run_disclosure(REPO, read_ledgered_run(REPO, real["2026-11-06"]))
    shock = run_disclosure(REPO, read_ledgered_run(REPO, real["2026-11-05"]))
    first = run_disclosure(REPO, read_ledgered_run(REPO, real["2026-10-14"]))
    wide = run_disclosure(REPO, read_ledgered_run(REPO, real["2026-10-27"]))
    assert _file_digests(REPO) == before
    assert near["run_disclosure_status"] == "ok" and near["selection_margin_pct"] == 0.166
    assert near["selection_near_tie"] is True and near["lambda_switch_vs_prev"]["switched"] is False
    assert shock["origin_vol_lag_warning"]["triggered"] is True
    assert first["lambda_switch_vs_prev"]["status"] == "first_issuance"
    assert wide["selection_near_tie"] is False and wide["lambda_switch_vs_prev"]["switched"] is True
    out = _run(tmp_path, "const near=" + json.dumps(near) + ";const shock=" + json.dumps(shock) + r""";
process.stdout.write(JSON.stringify({near:tsDailyRunFlagsMarkup(near),shock:tsDailyRunFlagsMarkup(shock),none:tsDailyRunFlagsMarkup({})}));""")
    assert "설정 선택 근소차 0.17%" in out["near"] and "λ 전환" not in out["near"]
    assert "κ 1.43" in out["shock"] and out["none"] == ""
    source = _source()
    daily = source[source.index("function renderTimeseriesDaily("):source.index("function bindTimeseriesTabs")]
    assert "chart+tsDailyRunFlagsMarkup(ts)" in daily


def test_run_disclosure_fails_soft_with_a_reason_when_constants_are_missing(tmp_path: Path) -> None:
    from ai_fc.timeseries_daily6m.display import run_disclosure

    payload = run_disclosure(tmp_path, {"run_id": "x"})
    assert payload["run_disclosure_status"] == "constants_file_missing"
    assert payload["selection_margin_pct"] is None and payload["selection_near_tie"] is None


def test_ledgered_run_reader_rejects_identity_mismatch(tmp_path: Path) -> None:
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import Daily6mDisplayError, read_ledgered_run

    body = {"run_id": "daily6m-x", "value": 1}
    run = {**body, "content_hash": C.canonical_hash(body)}
    path = tmp_path / C.STORE_RELATIVE / "runs/daily6m-x.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(run), encoding="utf-8")
    row = {"forecast_id": "daily6m-x", "run_path": (C.STORE_RELATIVE / "runs/daily6m-x.json").as_posix(),
           "run_content_hash": run["content_hash"]}
    assert read_ledgered_run(tmp_path, row) == run
    for broken in ({**row, "run_content_hash": "0" * 64}, {**row, "forecast_id": "daily6m-y"},
                   {**row, "run_path": "../outside.json"}):
        with pytest.raises(Daily6mDisplayError):
            read_ledgered_run(tmp_path, broken)
    path.write_text(json.dumps({**run, "value": 2}), encoding="utf-8")
    with pytest.raises(Daily6mDisplayError):
        read_ledgered_run(tmp_path, row)


def test_honesty_fields_are_all_null_without_runs_and_ui_does_not_promote_raw_counts(tmp_path: Path) -> None:
    from ai_fc.timeseries_daily6m.display import HONESTY_FIELDS, forward_record

    rows = [{"resolution_id": "a:1", "forecast_id": "a", "date": "2026-10-15", "brier": 0.2, "inside_p10_p90": True}]
    bare = forward_record(rows)
    assert bare["honesty_status"] == "runs_unavailable" and all(bare[key] is None for key in HONESTY_FIELDS)
    assert bare["notice"] == "참고 의견, 매매 신호 아님" and bare["n"] == 1 and bare["n_dates"] == 1
    broken = forward_record(rows, runs={}, forecasts=[], constants={"x": 1})
    assert broken["honesty_status"].startswith("honesty_error") and broken["coverage_date_equal"] is None
    out = _run(tmp_path, "const rec=" + json.dumps(bare) + r""";
const html=tsDailyRecordMarkup(rec),strong=[...html.matchAll(/<strong>([^<]*)<\/strong>/g)].map(m=>m[1]);
process.stdout.write(JSON.stringify({html,strong}));""")
    assert out["strong"][0] == "—" and "원시 1/1" in out["html"]


def test_record_markup_leads_with_date_equal_coverage_and_null_band(tmp_path: Path, p4_record: dict) -> None:
    out = _run(tmp_path, "const rec=" + json.dumps(p4_record) + r""";
const html=tsDailyRecordMarkup(rec),strong=[...html.matchAll(/<strong>([^<]*)<\/strong>/g)].map(m=>m[1]);
process.stdout.write(JSON.stringify({html,strong}));""")
    html, strong = out["html"], out["strong"]
    band = p4_record["null_band"]
    assert strong[0] == "64.8%" and strong[0] != "71/132"
    assert f"귀무 {round(band['p05'] * 100)}%~{round(band['p95'] * 100)}%" in html and "원시 71/132" in html
    assert strong[1] == "0.242" and "사전 상수 0.553 → 0.247" in html and "무정보 0.25" in html
    assert "skill 판단 불가" in html
    assert '<details class="ts-daily-record-guide">' in html and "in-sample" in html
    assert "10/18" in html and "20/37" in html and "103/132" in html and "단일 에피소드" in html
    assert "<svg" not in html and "참고 의견, 매매 신호 아님" in html
    # 접기 밖 KPI 문구는 라벨만 — 자기설명 문장(…다.)은 접기 안에만 둔다.
    outside = html[:html.index("<details")]
    assert "다." not in outside and "비독립" not in outside


def test_live_loader_matches_the_pure_projection_and_stays_within_budget(p4_record: dict) -> None:
    from ai_fc.timeseries_daily6m import contracts as C
    from ai_fc.timeseries_daily6m.display import load_forward_record

    before = _file_digests(REPO)
    code_hash = C.model_code_hash(REPO)
    live = load_forward_record(REPO)
    assert _file_digests(REPO) == before and C.model_code_hash(REPO) == code_hash
    assert live["honesty_status"] == "ok" and live["n"] >= p4_record["n"]
    assert len(json.dumps(live, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) < 8 * 1024
