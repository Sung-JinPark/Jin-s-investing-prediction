"""Source-arrival fan-out and immutable-snapshot delivery regression tests."""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_fc.forecast_refresh import V13_POINTER, v13_pointer_changed
from test_timeseries_inputs_workflow import _concurrency_group

ROOT = Path(__file__).parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', ['scenario-refresh.yml', 'timeseries-v8-daily.yml', 'timeseries-v13-vol-live.yml', 'timeseries-daily6m.yml'])
def test_bad_upstream_cannot_displace_a_pending_main_refresh(name):
    expected = _concurrency_group(name, 'workflow_dispatch')
    assert _concurrency_group(name, 'workflow_run') == expected
    assert _concurrency_group(name, 'workflow_run', branch='codex/branch') != expected
    assert _concurrency_group(name, 'workflow_run', conclusion='failure') != expected
    job = next(iter(workflow(name)['jobs'].values()))
    assert "head_branch == 'main'" in job['if'] and "conclusion == 'success'" in job['if']
    checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout'))
    assert checkout['with']['ref'] == 'main'


def test_changed_sources_dispatch_every_consumer_even_if_one_dispatch_fails(tmp_path):
    doc = workflow('daily6m-sources-refresh.yml')
    step = next(s for s in doc['jobs']['publish']['steps'] if s.get('name', '').startswith('Recheck and regenerate'))
    assert "changed == 'true'" in step['if']
    git_bash = Path('C:/Program Files/Git/bin/bash.exe')
    bash = str(git_bash) if git_bash.is_file() else shutil.which('bash')
    if not bash:
        pytest.skip('bash unavailable')
    # Execute the exact fan-out control flow with a shell function, no network.
    script = 'gh(){ echo "$*" >> calls; return 1; }\n' + step['run']
    target = tmp_path / 'fanout.sh'; target.write_text(script, encoding='utf-8')
    result = subprocess.run([bash, str(target)], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    calls = (tmp_path / 'calls').read_text(encoding='utf-8')
    for target in ('timeseries-daily6m.yml', 'timeseries-v8-daily.yml', 'timeseries-v2-refresh.yml'):
        assert target in calls


def test_market_checkpoint_releases_displays_before_unrelated_model_work():
    steps = workflow('timeseries-v2-refresh.yml')['jobs']['refresh']['steps']
    checkpoint = next(s for s in steps if s.get('id') == 'checkpoint')
    relay = next(s for s in steps if s.get('name', '').startswith('Refresh displays after'))
    prepare = next(s for s in steps if 'timeseries-v2-prepare' in s.get('run', ''))
    assert steps.index(checkpoint) < steps.index(relay) < steps.index(prepare)
    assert checkpoint['run'].index('git push') < checkpoint['run'].index('echo "committed=true"')
    for clause in ("refs/heads/main", "!= 'pull_request'", "committed == 'true'"):
        assert clause in relay['if']
    for target in ('timeseries-v13-vol-live.yml', 'timeseries-v8-daily.yml', 'timeseries-v8-shadow.yml'):
        assert target in relay['run']
    assert '-f resolve_only=true' in relay['run']
    shadow = workflow('timeseries-v8-shadow.yml')
    forecast = next(s for s in shadow['jobs']['shadow']['steps'] if 'timeseries-v8-forecast' in s.get('run', ''))
    assert forecast['if'] == '${{ inputs.resolve_only != true }}'


@pytest.mark.parametrize('name,job', [('scenario-refresh.yml', 'refresh'), ('timeseries-v13-vol-live.yml', 'live'), ('timeseries-v8-shadow.yml', 'shadow')])
def test_token_dispatches_deploy_only_after_a_verified_commit(name, job):
    doc = workflow(name); steps = doc['jobs'][job]['steps']
    commit = next(s for s in steps if s.get('id') == 'commit')
    deploy = next(s for s in steps if 'gh workflow run pages.yml' in s.get('run', ''))
    assert steps.index(commit) < steps.index(deploy)
    assert 'committed=false' in commit['run'] and 'committed=true' in commit['run']
    assert "workflow_dispatch" in deploy['if'] and "outcome == 'success'" in deploy['if'] and "committed == 'true'" in deploy['if']
    assert doc['permissions']['actions'] == 'write'


@pytest.mark.parametrize('change', ['clock', 'origin', 'input', 'gate', 'freshness', 'probability'])
def test_v13_clock_only_retry_does_not_hide_a_real_change(tmp_path, change):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    pointer = tmp_path / V13_POINTER; pointer.parent.mkdir(parents=True)
    before = {'as_of': '2026-10-19', 'knowledge_cutoff': 'old', 'content_hash': 'old', 'inputs': {'vix': 18.44},
              'cells': {'a': {'p': .5}}, 'gate': {'pass': True}, 'freshness': {'status': 'fresh', 'evaluated_at': 'old'}}
    pointer.write_text(json.dumps(before), encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'add', V13_POINTER], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    current = copy.deepcopy(before); current.update(knowledge_cutoff='new', content_hash='new'); current['freshness']['evaluated_at'] = 'new'
    if change == 'origin': current['as_of'] = '2026-10-20'
    if change == 'input': current['inputs']['vix'] = 17.31
    if change == 'gate': current['gate']['pass'] = False
    if change == 'freshness': current['freshness']['status'] = 'stale'
    if change == 'probability': current['cells']['a']['p'] = .51
    pointer.write_text(json.dumps(current), encoding='utf-8'); original = pointer.read_bytes()
    assert v13_pointer_changed(tmp_path) is (change != 'clock')
    assert pointer.read_bytes() == original


def test_future_loader_rejects_old_snapshot_same_version_and_late_response(tmp_path):
    node = shutil.which('node')
    if not node: pytest.skip('node unavailable')
    source = (ROOT / 'src/ai_fc/dashboard_parts/dashboard.js').read_text(encoding='utf-8')
    helpers = '\n'.join(re.search(pattern, source).group(0) for pattern in
                        [r'function semanticReferenceMatches\([\s\S]+?\n}\n', r'async function ensureFuturePaths\([\s\S]+?\n}\n'])
    program = helpers + r'''
let DATA,FUTURE_PATHS_PROMISE=null,FUTURE_PATHS_ERROR=null;const window={};
const {createHash,webcrypto}=require('node:crypto');globalThis.crypto=webcrypto;
const raw=value=>JSON.stringify(value);const sha=value=>createHash('sha256').update(raw(value)).digest('hex');
const response=value=>({ok:true,text:async()=>raw(value)});
const ref={candidate_id:'candidate',model_version:'model',rules_version:'rules'};
function summary(){return {as_of:'2026-10-20',semantic_reference:ref,deferred_paths:{required:true,url:'paths.json',model_content_sha256:'newhash',payload_sha256:sha(payload())}};}
function payload(overrides={}){return {contract_id:'future_paths_v1',semantic_reference:ref,data:{scenario_v5_2:{as_of:'2026-10-20',model_content_sha256:'newhash',...overrides}}};}
(async()=>{
 const errors=[];
 for(const overrides of [{as_of:'2026-10-19'},{model_content_sha256:'oldhash'}]){
   const original=summary();original.deferred_paths.payload_sha256=sha(payload(overrides));DATA={scenario_v5_2:original};FUTURE_PATHS_PROMISE=null;
   globalThis.fetch=async()=>response(payload(overrides));
   try{await ensureFuturePaths();throw Error('accepted stale snapshot');}catch(e){errors.push(e.message);}
   if(DATA.scenario_v5_2!==original)throw Error('mutated summary');
 }
 const original=summary();DATA={scenario_v5_2:original};FUTURE_PATHS_PROMISE=null;
 globalThis.fetch=async()=>response(payload({runtime_gate:{pass:false}}));
 try{await ensureFuturePaths();throw Error('accepted altered gate');}catch(e){errors.push(e.message);}
 if(DATA.scenario_v5_2!==original)throw Error('mutated summary after altered body');
 let release;DATA={scenario_v5_2:summary()};FUTURE_PATHS_PROMISE=null;
 globalThis.fetch=()=>new Promise(resolve=>{release=resolve;});const pending=ensureFuturePaths();
 const replacement=summary();DATA.scenario_v5_2=replacement;release(response(payload()));
 try{await pending;throw Error('accepted late response');}catch(e){errors.push(e.message);}
 if(DATA.scenario_v5_2!==replacement)throw Error('overwrote new summary');
 FUTURE_PATHS_PROMISE=null;globalThis.fetch=async()=>response(payload());
 await ensureFuturePaths();console.log(JSON.stringify({errors,loaded:DATA.scenario_v5_2.deferred_paths.loaded}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    file = tmp_path / 'loader.js';file.write_text(program, encoding='utf-8')
    result = subprocess.run([node, str(file)], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output['errors'] == ['future paths snapshot mismatch'] * 2 + ['future paths payload mismatch', 'future paths summary changed during loading']
    assert output['loaded']
