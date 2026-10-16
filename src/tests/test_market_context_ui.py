"""The research chart preserves daily members and verifies publication identity."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_market_context_delivery import _projection


SOURCE = Path(__file__).parents[1] / "ai_fc/dashboard_parts/dashboard.js"


def _source():
    return SOURCE.read_text(encoding="utf-8")


def _helpers():
    source = _source()
    return "const esc=value=>String(value??'');\n" + source[source.index("function marketContextValidate("):source.index("function marketContextPanel(")]


def _run(tmp_path, program, *, helpers=True):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    path = tmp_path / "market_context_probe.js"
    path.write_text((_helpers() if helpers else "") + "\n" + program, encoding="utf-8")
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr[:4000]
    return json.loads(result.stdout)


def test_all_daily_member_points_and_dips_survive_without_changing_input(tmp_path):
    projection = _projection()
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + r""";
const before=JSON.stringify(mc),m=marketContextChartModel(mc),short=marketContextChartModel(mc,21),html=marketContextChartMarkup(mc);
process.stdout.write(JSON.stringify({
  rows:m.records.length,member:m.primary.length,short:short.primary.length,
  sameMember:JSON.stringify(m.primary)===JSON.stringify(mc.representative.values),
  sameRows:short.records.every((row,index)=>row===m.records[index]),
  dips:m.primary.filter((value,index)=>index>0&&value<m.primary[index-1]).length,
  exactMedian:JSON.stringify(m.median)===JSON.stringify([mc.anchor,...mc.records.map(row=>row.index_quantiles.p50)]),
  html,unchanged:before===JSON.stringify(mc),
  readout:marketContextDescribe(mc,m,m.origin+1),
  zeroDD:m.drawdown[0],date:m.dates.at(-1)
}));
""")
    assert result["rows"] == 252 and result["member"] == 253 and result["short"] == 22
    assert result["sameMember"] and result["sameRows"] and result["exactMedian"] and result["unchanged"]
    assert result["dips"] > 100 and result["zeroDD"] == 0
    for role in ("actual-member", "median", "baseline", "drawdown"):
        points = re.search(rf'data-mc-path="{role}"[^>]*points="([^"]+)"', result["html"])[1]
        assert len(points.split()) == 253
    assert "44.0%" in result["readout"], "Strict down probability must not be inferred as 1-up"
    assert "일간 수익률 중앙값" in result["readout"] and "기여" in result["readout"]


@pytest.mark.parametrize("problem", ["probability", "negative_price", "order", "date", "short_member", "anchor", "unit", "validation", "dd", "basis"])
def test_invalid_numeric_publication_is_rejected(tmp_path, problem):
    projection = _projection()
    if problem == "probability":
        projection["records"][0]["probability_down_from_previous"] = 44
    elif problem == "negative_price":
        projection["records"][0]["index_quantiles"]["p05"] = -1
    elif problem == "order":
        projection["records"][0]["index_quantiles"]["p25"] = 1000
    elif problem == "date":
        projection["records"][0]["date"] = projection["anchor_date"]
    elif problem == "short_member":
        projection["representative"]["values"].pop()
    elif problem == "anchor":
        projection["representative"]["values"][0] += 2
    elif problem == "unit":
        projection["probability_unit"] = "percent"
    elif problem == "validation":
        projection["predictive_validation"] = "passed"
    elif problem == "dd":
        projection["records"][0]["drawdown_quantiles"]["p95"] = .02
    elif problem == "basis":
        projection["attribution_basis"] = {"inflation": [.01, "0.02", .03]}
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + ";let rejected=false;try{marketContextChartModel(mc);}catch(error){rejected=true;}process.stdout.write(JSON.stringify({rejected}));")
    assert result["rejected"]


def test_missing_representative_does_not_turn_median_into_a_member(tmp_path):
    projection = _projection()
    projection["representative"] = {"status": "unavailable", "reason": "typicality gate"}
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + ";const html=marketContextChartMarkup(mc);process.stdout.write(JSON.stringify({noMember:!html.includes('data-mc-path=\"actual-member\"'),hasMedian:html.includes('data-mc-path=\"median\"')}));")
    assert all(result.values())


def test_selected_date_contribution_uses_registered_decay_and_stops_after63(tmp_path):
    projection = _projection()
    projection["coefficient_hash"] = "fitted-fixture"
    projection["numerical_context_applied"] = True
    projection["attribution_basis"] = {"inflation": [.001, .0003, .0001], "policy_rates": [-.0002, 0, 0]}
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + r""";
const model=marketContextChartModel(mc);
process.stdout.write(JSON.stringify({
  five:marketContextContributions(mc,5),twentyOne:marketContextContributions(mc,21),
  sixtyThree:marketContextContributions(mc,63),later:marketContextContributions(mc,252),
  readout:marketContextDescribe(mc,model,model.origin+5)
}));
""")
    def expected(step):
        return sum(weight * sum(2 ** (-day / half) for day in range(1, min(step, 63) + 1))
                   for weight, half in zip((.001, .0003, .0001), (5, 21, 63)))
    assert result["five"]["values"][0]["value"] == pytest.approx(expected(5), abs=1e-14)
    assert result["twentyOne"]["values"][0]["value"] == pytest.approx(expected(21), abs=1e-14)
    assert result["five"]["values"][0]["value"] != result["twentyOne"]["values"][0]["value"]
    assert result["sixtyThree"]["values"] == result["later"]["values"]
    assert "5거래일 누적 로그수익률 기여" in result["readout"]
    assert "21거래일 누적 로그수익률 기여" not in result["readout"]


def test_missing_decay_basis_uses_only_exact_stored_horizons(tmp_path):
    projection = _projection()
    projection["coefficient_hash"] = "older-fitted-fixture"
    projection["numerical_context_applied"] = True
    projection["attribution"] = {"inflation": {"5": .01, "21": .02, "63": .03}}
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + r""";
process.stdout.write(JSON.stringify({
  exact:marketContextContributions(mc,21),ten:marketContextContributions(mc,10),
  later:marketContextContributions(mc,126),readout:marketContextDescribe(mc,marketContextChartModel(mc),11)
}));
""")
    assert result["exact"]["basis"] == "stored_exact_horizon"
    assert result["exact"]["values"] == [{"axis": "inflation", "value": .02}]
    assert result["ten"]["status"] == result["later"]["status"] == "pending"
    assert "누적 기여 자료 대기" in result["readout"]


def test_unfitted_context_waits_instead_of_presenting_zero_as_neutral(tmp_path):
    projection = _projection()
    projection["attribution_basis"] = {"inflation": [0, 0, 0]}
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + r""";
const pending=marketContextContributions(mc,21),readout=marketContextDescribe(mc,marketContextChartModel(mc),22);
mc.coefficient_hash='fitted-neutral';
process.stdout.write(JSON.stringify({pending,readout,neutral:marketContextContributions(mc,21)}));
""")
    assert result["pending"]["reason"] == "unfitted" and not result["pending"]["values"]
    assert "수치 적용 대기" in result["readout"] and "inflation 0.00%" not in result["readout"]
    assert result["neutral"]["status"] == "ready"
    assert result["neutral"]["values"] == [{"axis": "inflation", "value": 0}]


def test_overall_score_shows_neutral_zero_and_unknown_separately(tmp_path):
    result = _run(tmp_path, r"""
process.stdout.write(JSON.stringify({zero:marketContextScoreMarkup({score:0}),unknown:marketContextScoreMarkup({score:null})}));
""")
    assert "종합 시황 점수" in result["zero"] and "data-mc-score>0.00" in result["zero"]
    assert "산출 대기" not in result["zero"] and "산출 대기" in result["unknown"]
    assert "21거래일 추가 기대 로그수익률을 위험으로 표준화한 지표 · 확률 아님" in result["zero"]


def test_unknown_axis_and_source_failure_are_explicit(tmp_path):
    projection = _projection()
    projection["state_summary"]["axes"][0]["score"] = None
    projection["state_summary"]["total_event_count"] = 28
    projection["state_summary"]["source_statuses"] = [
        {"source_id": "official-feed", "status": "failed", "reason": "HTTP503", "retrieved_at": projection["as_of"]},
        {"source_id": "index-feed", "status": "quality_degraded", "reason": "invalid source row rejected", "retrieved_at": projection["as_of"]},
    ]
    result = _run(tmp_path, "const mc=" + json.dumps(projection) + ";process.stdout.write(JSON.stringify({html:marketContextSources(mc)}));")
    assert "산출 대기" in result["html"]
    assert "수집 실패·대기" in result["html"] and "HTTP503" in result["html"]
    assert "품질 주의" in result["html"] and "1 / 전체 28개" in result["html"]


def _loader_program(projection, summary):
    source = _source()
    loader = source[source.index("async function ensureMarketContextData("):source.index("async function ensureTimeseriesDaily(")]
    raw = json.dumps({"schema_version": 1, "contract_id": "market_context_route_v1", "data": {"market_context": projection}}, separators=(",", ":"))
    return ("let MARKET_CONTEXT_PROMISE=null,MARKET_CONTEXT_ERROR=null;const window={};Object.defineProperty(globalThis,'crypto',{value:require('node:crypto').webcrypto,configurable:true});\n"
            + "let DATA={market_context:" + json.dumps(summary) + "};const raw=" + json.dumps(raw) + ";\n" + loader)


def _summary(projection):
    raw = json.dumps({"schema_version": 1, "contract_id": "market_context_route_v1", "data": {"market_context": projection}}, separators=(",", ":"))
    keys = ("forecast_id", "as_of", "anchor_date", "input_hash", "contract_hash", "coefficient_hash")
    return {"status": "research_preview", **{key: projection[key] for key in keys},
            "deferred_data": {"required": True, "loaded": False, "url": "market_context.json",
                              **{key: projection[key] for key in keys}, "payload_sha256": hashlib.sha256(raw.encode()).hexdigest()}}


def test_loader_deduplicates_requests_and_retries_after_http_failure(tmp_path):
    projection = _projection()
    program = _loader_program(projection, _summary(projection)) + r"""
let calls=0;globalThis.fetch=async()=>{calls++;return calls===1?{ok:false,status:503}:{ok:true,text:async()=>raw};};
(async()=>{let rejected=false;try{await ensureMarketContextData();}catch(error){rejected=true;}
const reset=MARKET_CONTEXT_PROMISE===null;await Promise.all([ensureMarketContextData(),ensureMarketContextData()]);await ensureMarketContextData();
process.stdout.write(JSON.stringify({rejected,reset,calls,loaded:DATA.market_context.deferred_data.loaded}));})().catch(error=>{console.error(error);process.exit(1);});
"""
    result = _run(tmp_path, program)
    assert result == {"rejected": True, "reset": True, "calls": 2, "loaded": True}


@pytest.mark.parametrize("problem", ["hash", "forecast_id", "as_of", "anchor_date", "input_hash", "contract_hash", "coefficient_hash", "crypto"])
def test_loader_rejects_wrong_bytes_or_publication_without_replacement(tmp_path, problem):
    projection = _projection()
    summary = _summary(projection)
    if problem == "hash":
        summary["deferred_data"]["payload_sha256"] = "0" * 64
    elif problem != "crypto":
        summary["deferred_data"][problem] = "other-publication"
    program = _loader_program(projection, summary)
    if problem == "crypto":
        program += "Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});\n"
    program += r"""
globalThis.fetch=async()=>({ok:true,text:async()=>raw});
(async()=>{const original=DATA.market_context;let rejected=false;try{await ensureMarketContextData();}catch(error){rejected=true;}
process.stdout.write(JSON.stringify({rejected,unchanged:DATA.market_context===original,reset:MARKET_CONTEXT_PROMISE===null}));})().catch(error=>{console.error(error);process.exit(1);});
"""
    assert all(_run(tmp_path, program).values())


def test_inflight_response_cannot_replace_new_dataset(tmp_path):
    projection = _projection()
    program = _loader_program(projection, _summary(projection)) + r"""
let finish;globalThis.fetch=async()=>({ok:true,text:()=>new Promise(resolve=>{finish=resolve;})});
(async()=>{const pending=ensureMarketContextData();await new Promise(resolve=>setImmediate(resolve));
const replacement={status:'hold'};DATA={market_context:replacement};finish(raw);
let rejected=false;try{await pending;}catch(error){rejected=true;}
process.stdout.write(JSON.stringify({rejected,unchanged:DATA.market_context===replacement}));})().catch(error=>{console.error(error);process.exit(1);});
"""
    assert all(_run(tmp_path, program).values())


def test_graph02_is_independent_and_only_fetches_when_selected():
    source = _source()
    flow = source[source.index("function renderFlow(initialLookup)"):source.index("const candidateData=DATA.scenario_v5")]
    assert flow.index("initialState.futureGraph==='original'") < flow.index("const candidate52=DATA.scenario_v5_2")
    assert "futurePathsRequested=v==='flow'&&arg?.futureGraph!=='original'" in source
    assert "if(graphKey==='original'&&!originalPanel" in source
    panel = source[source.index("function marketContextPanel("):source.index("function originalFlowPanel(")]
    for phrase in ("전진 검증 전", "기존 S1 기록 보기", "정확한", "예측 성적은 확립되지", "중앙값을 실제 경로로 대체하지"):
        assert phrase in panel


def test_compacted_dashboard_javascript_parses(tmp_path):
    from ai_fc import dashboard

    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    html = dashboard._compact_static_bundle(dashboard.load_template())
    for index, script in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
        path = tmp_path / f"market_compacted_{index}.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[:2000]
