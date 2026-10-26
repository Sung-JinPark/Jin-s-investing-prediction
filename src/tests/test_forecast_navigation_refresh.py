"""Long-lived forecast menus revalidate the public snapshot without reloading editors."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_navigation_refresh_replaces_stale_cache_and_discards_late_responses(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    source = (ROOT / 'src/ai_fc/dashboard_parts/dashboard.js').read_text(encoding='utf-8')
    helpers = '\n'.join(re.search(r'(?:async )?function ' + name + r'\([\s\S]+?\n}', source).group(0)
                        for name in ['forecastSummaryCheckDue', 'refreshForecastSummary'])
    program = helpers + r"""
let clock=61000;Date.now=()=>clock;let DATA,ROUTE_EPOCH=1,updates=0;
const window={__DATA_URL__:'data.json'};
let FORECAST_SUMMARY_CHECKED_AT=0,FORECAST_SUMMARY_PROMISE=null,FORECAST_SUMMARY_ERROR=null;
let FUTURE_PATHS_PROMISE=null,FUTURE_PATHS_ERROR=null,DAILY_FLOW_PROMISE=null,DAILY_FLOW_ERROR=null;
let TIMESERIES_DAILY_PROMISE=null,TIMESERIES_DAILY_ERROR=null,STATISTICS_PROMISE=null,STATISTICS_ERROR=null;
let FORECAST_BODIES={},FORECAST_BODIES_PROMISE=null,FORECAST_BODIES_ERROR=null;
function syncForecastChrome(){updates++;}
function model(day,state){return {meta:{generated:`2026-10-${day}T08:00:00Z`},scenario:{asof:`2026-10-${day}`},scenario_v5_2:{deferred_paths:{required:true}},timeseries:{input_state:state}};}
function reset(){clock+=61000;FORECAST_SUMMARY_CHECKED_AT=0;FORECAST_SUMMARY_PROMISE=null;FORECAST_SUMMARY_ERROR=null;DATA=model('20','provisional');}
(async()=>{
 reset();let calls=0;FUTURE_PATHS_PROMISE=Promise.resolve('old');
 const next=model('21','confirmed');globalThis.fetch=async(url,options)=>{calls++;if(options.cache!=='no-store')throw Error('cached fetch');return {ok:true,json:async()=>next};};
 if(!await refreshForecastSummary(1)||DATA!==next||FUTURE_PATHS_PROMISE!==null||updates!==1)throw Error('old page cache survived');
 await refreshForecastSummary(1);if(calls!==1)throw Error('unthrottled request');
 reset();const old=DATA;globalThis.fetch=async()=>({ok:true,json:async()=>model('20','provisional')});
 await refreshForecastSummary(1);if(DATA!==old)throw Error('same publication discarded loaded content');
 reset();const unavailable=DATA;globalThis.fetch=async()=>({ok:false,status:503});
 await refreshForecastSummary(1);if(DATA!==unavailable||!FORECAST_SUMMARY_ERROR)throw Error('network failure hid old snapshot status');
 reset();const malformed=DATA;globalThis.fetch=async()=>({ok:true,json:async()=>({meta:{generated:'bad'}})});
 await refreshForecastSummary(1);if(DATA!==malformed||!FORECAST_SUMMARY_ERROR)throw Error('malformed snapshot accepted');
 reset();DATA=model('21','confirmed');const newer=DATA;globalThis.fetch=async()=>({ok:true,json:async()=>model('20','provisional')});
 await refreshForecastSummary(1);if(DATA!==newer||!FORECAST_SUMMARY_ERROR)throw Error('older deployment replaced current');
 reset();let release;const staying=DATA;globalThis.fetch=()=>new Promise(resolve=>release=resolve);const pending=refreshForecastSummary(1);
 ROUTE_EPOCH=2;release({ok:true,json:async()=>next});await pending;
 if(DATA!==staying||FORECAST_SUMMARY_ERROR)throw Error('late refresh touched another route');
 reset();window.__DATA__=DATA;globalThis.fetch=async()=>{throw Error('snapshot embed fetched');};
 await refreshForecastSummary(2);delete window.__DATA__;
 console.log(JSON.stringify({passed:true,updates}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    path = tmp_path / 'refresh.js'; path.write_text(program, encoding='utf-8')
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['passed']


def test_old_lazy_rejection_cannot_clear_new_dataset_request(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    source = (ROOT / 'src/ai_fc/dashboard_parts/dashboard.js').read_text(encoding='utf-8')
    helpers = '\n'.join(re.search(pattern, source).group(0) for pattern in
                        [r'function dailyFlowSemanticReferenceMatches\([\s\S]+?\n}',
                         r'async function ensureDailyFlow\([\s\S]+?\n}'])
    program = helpers + r"""
let DATA,DAILY_FLOW_PROMISE=null,DAILY_FLOW_ERROR=null;const window={};
const ref={contract_id:'c',artifact_id:'a',source_snapshot_id:'s',source_snapshot_sha256:'s',input_sha256:'i',version:'v',model_content_sha256:'m'};
DATA={daily_flow:{semantic_reference:ref,deferred_paths:{required:true,url:'daily.json'}}};
let release;globalThis.fetch=async()=>({ok:true,json:()=>new Promise(resolve=>release=resolve)});
(async()=>{
 const pending=ensureDailyFlow();await new Promise(resolve=>setImmediate(resolve));
 const replacement={daily_flow:{new:true}};DATA=replacement;const newer=Promise.resolve('new');DAILY_FLOW_PROMISE=newer;
 release({contract_id:'daily_flow_route_v1',semantic_reference:ref,data:{daily_flow:{semantic_reference:ref}}});
 let rejected=false;try{await pending;}catch(error){rejected=true;}
 if(!rejected||DATA!==replacement||DAILY_FLOW_PROMISE!==newer||DAILY_FLOW_ERROR)throw Error('stale response replaced current request');
 console.log('passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    path = tmp_path / 'late.js'; path.write_text(program, encoding='utf-8')
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'passed'


def test_internal_tab_refresh_does_not_reenter_personal_drawing_routes(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    source = (ROOT / 'src/ai_fc/dashboard_parts/dashboard.js').read_text(encoding='utf-8')
    helper = re.search(r'function syncMidHash\([\s\S]+?\n}', source).group(0)
    program = helper + r"""
let calls=0,focused=false;const location={hash:''};
const history={replaceState:(a,b,hash)=>location.hash=hash};
const document={body:{dataset:{view:'trendlines'}},activeElement:{dataset:{tsTab:'path'}},querySelectorAll:()=>[{dataset:{tsTab:'path'},focus:()=>focused=true}]};
function paintRailSubNav(){}function forecastSummaryCheckDue(){return true;}async function route(){calls++;}
(async()=>{
 syncMidHash('#future/trendlines/sk-hynix');await Promise.resolve();if(calls)throw Error('editor route refreshed');
 document.body.dataset.view='future';syncMidHash('#future/timeseries/path');await Promise.resolve();
 if(calls!==1||!focused)throw Error('forecast tab did not preserve focus');
 focused=false;document.body.dataset.view='statistics';document.activeElement={dataset:{statFilter:'rates'}};
 document.querySelectorAll=()=>[{dataset:{statFilter:'rates'},focus:()=>focused=true}];
 syncMidHash('#statistics/dotcom/rates');await Promise.resolve();
 if(calls!==2||!focused)throw Error('statistics filter kept stale data or lost focus');console.log('passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    path = tmp_path / 'scope.js'; path.write_text(program, encoding='utf-8')
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'passed'
