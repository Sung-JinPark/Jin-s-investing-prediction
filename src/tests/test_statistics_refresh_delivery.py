"""Statistics source recovery and snapshot-bound publication regressions."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_fc import dashboard, fred_api

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize('bad', ['', '<html>temporarily unavailable</html>', b'{"observations":'])
def test_official_api_retries_malformed_gateway_response_without_changing_source(monkeypatch, bad):
    monkeypatch.setenv('FRED_API_KEY', 'fixture-key')
    sleeps = []
    monkeypatch.setattr(fred_api.time, 'sleep', sleeps.append)
    calls = []
    good = '{"observations":[{"date":"2026-10-21","value":"10.5"}]}'
    def fetch(url, **kwargs):
        calls.append(url)
        return bad if len(calls) == 1 else good
    result = fred_api.observations_csv('M2SL', fetch_text=fetch)
    assert result == 'observation_date,M2SL\n2026-10-21,10.5\n'
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0].startswith(fred_api.OBSERVATIONS_ENDPOINT)
    assert sleeps == [1]


def test_api_retry_budget_preserves_failure_and_rejects_valid_json_schema_error(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'fixture-key')
    sleeps = []
    monkeypatch.setattr(fred_api.time, 'sleep', sleeps.append)
    calls = []
    def malformed(url, **kwargs):
        calls.append(url)
        return '<html>gateway down</html>'
    with pytest.raises(fred_api.FredApiError, match='html; 3 attempts'):
        fred_api.observations_csv('M2SL', fetch_text=malformed)
    assert len(calls) == 3 and sleeps == [1, 2]
    calls.clear()
    def denied(url, **kwargs):
        calls.append(url)
        return '{"error_code":400,"error_message":"unavailable"}'
    with pytest.raises(fred_api.FredApiError):
        fred_api.observations_csv('M2SL', fetch_text=denied)
    assert len(calls) == 1


def test_statistics_summary_hash_pins_exact_published_bytes():
    statistics = {'schema_version': 1, 'dataset_id': 'd', 'status': 'ok',
                  'generated_at': '2026-10-22T01:00:00Z', 'as_of': '2026-10-21',
                  'charts': [{'label': '한글', 'points': [1.0, 2.0]}], 'sources': []}
    base, payload = dashboard.split_statistics_data({'statistics_lab': statistics})
    raw = json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':')).encode('utf-8')
    assert base['statistics_lab']['deferred_data']['payload_sha256'] == hashlib.sha256(raw).hexdigest()
    assert payload['data']['statistics_lab'] is statistics
    again, unchanged = dashboard.split_statistics_data(base)
    assert again is base and unchanged is None


def test_statistics_loader_rejects_tampering_mixed_deployments_and_late_responses(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    source = (ROOT/'src/ai_fc/dashboard_parts/dashboard.js').read_text(encoding='utf-8')
    helper = re.search(r'async function ensureStatistics\([\s\S]+?\n}', source).group(0)
    program = helper + r"""
const {createHash,webcrypto}=require('node:crypto');globalThis.crypto=webcrypto;
let DATA,STATISTICS_PROMISE=null,STATISTICS_ERROR=null;const window={};
const statistics={dataset_id:'d',generated_at:'2026-10-22T01:00:00Z',as_of:'2026-10-21',status:'ok',charts:[{value:21}]};
const raw=JSON.stringify({contract_id:'statistics_route_v1',data:{statistics_lab:statistics}});
const sha=createHash('sha256').update(raw).digest('hex');
function reset(){STATISTICS_PROMISE=null;STATISTICS_ERROR=null;DATA={statistics_lab:{...statistics,charts:undefined,deferred_data:{required:true,url:'statistics.json',payload_sha256:sha}}};}
async function reject(){let failed=false;try{await ensureStatistics();}catch(e){failed=true;}if(!failed)throw Error('invalid detail accepted');}
(async()=>{
 reset();globalThis.fetch=async()=>({ok:true,text:async()=>raw});await ensureStatistics();
 if(DATA.statistics_lab.charts[0].value!==21||!DATA.statistics_lab.deferred_data.loaded)throw Error('verified data not installed');
 reset();const old=DATA;globalThis.fetch=async()=>({ok:true,text:async()=>raw.replace('"value":21','"value":20')});await reject();if(DATA!==old||DATA.statistics_lab.charts)throw Error('tampering installed');
 reset();DATA.statistics_lab.as_of='2026-10-20';globalThis.fetch=async()=>({ok:true,text:async()=>raw});await reject();
 reset();globalThis.fetch=async()=>({ok:false,status:404});await reject();
 reset();let release;globalThis.fetch=async()=>({ok:true,text:()=>new Promise(r=>release=r)});
 const pending=ensureStatistics();await new Promise(r=>setImmediate(r));DATA={statistics_lab:{new:true}};const replacement=DATA,newer=Promise.resolve('new');STATISTICS_PROMISE=newer;release(raw);
 try{await pending;throw Error('old response accepted');}catch(e){if(e.message==='old response accepted')throw e;}
 if(DATA!==replacement||STATISTICS_PROMISE!==newer||STATISTICS_ERROR)throw Error('late response affected current data');
 console.log('passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    path = tmp_path/'statistics.js'; path.write_text(program, encoding='utf-8')
    result = subprocess.run([node, str(path)], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


def test_statistics_retry_and_partial_auxiliary_failure_cannot_hide_verified_publication():
    doc = yaml.safe_load((ROOT/'.github/workflows/statistics-refresh.yml').read_text(encoding='utf-8'))
    triggers = doc.get('on', doc.get(True))
    assert len(triggers['schedule']) >= 3
    assert "refs/heads/main" in doc['jobs']['refresh']['if']
    for name in ['statistics-refresh.yml', 'scenario-refresh.yml']:
        workflow = yaml.safe_load((ROOT/'.github/workflows'/name).read_text(encoding='utf-8'))
        steps = workflow['jobs']['refresh']['steps']
        commit = next(s for s in steps if s.get('id') == 'commit')
        deploy = next(s for s in steps if 'gh workflow run pages.yml' in s.get('run', ''))
        assert steps.index(commit) < steps.index(deploy)
        assert "committed == 'true'" in deploy['if'] and "outcome == 'success'" in deploy['if']
        assert 'workflow_dispatch' not in deploy['if']
        assert commit['run'].index('git push') < commit['run'].index('committed=true')
        assert workflow['permissions']['actions'] == 'write'
