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
        "dates": dates,
        "records": records,
        "sample_paths": [
            {"path_id": f"simulation-{member}", "values": [
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
    return "const esc=s=>String(s==null?'':s);\n" + formatting + daily


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
process.stdout.write(JSON.stringify({
  monthEnd:tsDailyMonthEnd('2026-01-31',1),
  one:one.endDate,three:three.endDate,six:six.endDate,
  counts:[one.records.length,three.records.length,six.records.length],
  sameRows:one.records.every((row,i)=>row===six.records[i]),
  samplesUnchanged:six.samples.every((row,i)=>JSON.stringify(row.values)===JSON.stringify(ts.sample_paths[i].values)),
  inputUnchanged:before===JSON.stringify(ts),
  probability:tsDailyDescribe(ts,six,six.origin+1).rows.find(row=>row.name==='전 거래일보다 오를 가능성').value,
  originProbability:ts.records[0].probability_up_from_origin,
  realized:six.realized.map(row=>row.date),
  rangeZero:six.py(0),rangeHalf:six.py(0.5),rangeOne:six.py(1),probT:six.probT,probH:six.probH
}));
""")
    assert out["monthEnd"] == "2026-02-28"
    assert [out["one"], out["three"], out["six"]] == ["2026-02-27", "2026-04-30", "2026-07-30"]
    assert out["counts"][0] < out["counts"][1] < out["counts"][2] == len(projection["records"])
    assert out["sameRows"] and out["samplesUnchanged"] and out["inputUnchanged"]
    assert out["probability"] == "55.0%" and out["originProbability"] == 0.70
    assert out["realized"] == projection["realized"]["dates"]
    assert out["rangeOne"] == out["probT"]
    assert out["rangeHalf"] == out["probT"] + out["probH"] / 2
    assert out["rangeZero"] == out["probT"] + out["probH"]


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


@pytest.mark.parametrize("problem", ["probability", "crossing", "date", "sample", "hold"])
def test_invalid_daily_inputs_fail_instead_of_clipping_or_hiding(tmp_path: Path, problem: str) -> None:
    ts = _projection()
    if problem == "probability":
        ts["records"][0]["probability_up_from_previous"] = 55
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


def test_chart_preserves_daily_points_and_only_toggles_real_simulated_samples(tmp_path: Path) -> None:
    out = _run(tmp_path, "const ts=" + json.dumps(_projection()) + r""";
const m=tsDailyChartModel(ts,6,375),plain=timeseriesDailySvg(ts,m),sampled=timeseriesDailySvg(ts,m,true);
const match=sampled.match(/data-daily-sample="simulation-0" points="([^"]+)"/),points=match[1].split(' ');
const probability=plain.match(/data-daily-probability="previous_session" points="([^"]+)"/)[1].split(' ');
process.stdout.write(JSON.stringify({
  defaultSamples:(plain.match(/data-daily-sample=/g)||[]).length,
  displayedSamples:(sampled.match(/data-daily-sample=/g)||[]).length,
  memberPoints:points.length,probabilityPoints:probability.length,
  exactSamplePoint:points[4]===`${m.x(m.origin+4).toFixed(2)},${m.y(ts.sample_paths[0].values[3]).toFixed(2)}`,
  ticks:m.tickIndices.map(index=>m.x(index)),width:m.W,
  noPathTouchProbability:!sampled.includes('누적 터치확률'),
  disclosure:plain.includes('80%/50%')&&plain.includes('2026-07-30')
}));
""")
    assert out["defaultSamples"] == 0 and out["displayedSamples"] == 5
    assert out["memberPoints"] == out["probabilityPoints"] + 1
    assert out["probabilityPoints"] == len(_projection()["records"])
    assert out["exactSamplePoint"] and out["noPathTouchProbability"] and out["disclosure"]
    assert all(0 <= tick <= out["width"] for tick in out["ticks"])
    assert all(right - left >= 82 for left, right in zip(out["ticks"], out["ticks"][1:]))


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
const first={cross:cross.attrs.x1,priceX:price.attrs.cx,probX:prob.attrs.cx,probY:prob.attrs.cy,text:readout.textContent};
const touchIndex=m.origin+10;
overlay.listeners.pointerdown({clientX:m.x(touchIndex),clientY:m.py(0.5)});
process.stdout.write(JSON.stringify({
  historicalHidden,
  sameX:first.cross===first.priceX&&first.priceX===first.probX,
  probabilityIsSource:Number(first.probY)===m.py(ts.records[0].probability_up_from_previous),
  firstDate:first.text.includes(ts.records[0].date),
  touchDate:readout.textContent.includes(ts.records[9].date),
  touchX:Number(prob.attrs.cx)===m.x(touchIndex)
}));
""")
    assert all(out.values())


def test_zoom_copy_hides_hover_markers_but_keeps_forecast_lines(tmp_path: Path) -> None:
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
            page.set_content(f'<style>{css}</style><div id="normal">{out["html"]}</div><div id="zoom" class="chart-zoom-content">{out["html"]}</div>')
            page.locator("[data-daily-price-dot],[data-daily-prob-dot]").evaluate_all("nodes=>nodes.forEach(node=>node.setAttribute('opacity','1'))")
            for marker in ("[data-daily-price-dot]", "[data-daily-prob-dot]"):
                assert page.locator("#normal " + marker).evaluate("node=>getComputedStyle(node).display") != "none"
                assert page.locator("#zoom " + marker).evaluate("node=>getComputedStyle(node).display") == "none"
            for line in (".ts-median-line", ".ts-daily-prob-line"):
                assert page.locator("#zoom " + line).evaluate("node=>getComputedStyle(node).display") != "none"
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
