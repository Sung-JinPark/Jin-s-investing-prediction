from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json,zipfile
import pytest

from ai_fc.timeseries_v7.codex_protocol import validate_envelope
from ai_fc.timeseries_v7.codex_worker import validate_result_paths,validate_secret_isolation
from ai_fc.timeseries_v7.model_registry import GenerationRecord,Registry
from ai_fc.timeseries_v7.monitoring import status_report
from ai_fc.timeseries_v7.planner import plan
from ai_fc.timeseries_v7.promotion import create_proposal
from ai_fc.timeseries_v7.scheduler import GenerationEvidence
from ai_fc.timeseries_v7.stop_rules import blocker_fingerprint,stop_decision
from tools.build_v7_review_pack import build


UTC=timezone.utc


def test_planner_requires_new_evidence_and_deduplicates_snapshot() -> None:
    now=datetime(2026,8,25,tzinfo=UTC);snapshot={'data':'x'}
    first=plan(snapshot,GenerationEvidence(matured_weekly_origins=4),now=now,last_generation_at=now-timedelta(days=30),prior_hashes=set(),candidate_ids=('E0','E1'))
    assert first.generation_state=='READY' and first.candidate_ids==('E0','E1')
    duplicate=plan(snapshot,GenerationEvidence(matured_weekly_origins=4),now=now,last_generation_at=None,prior_hashes={first.input_hash},candidate_ids=('E0',))
    assert duplicate.generation_state=='WAIT_DATA' and not duplicate.candidate_ids


def test_registry_binds_all_hashes_and_never_auto_promotes() -> None:
    row=GenerationRecord('g',None,'a'*64,'b'*64,'c'*64,'d'*64,'e'*64);registry=Registry();registry.register(row)
    assert registry.historical_winner('g')['automatic_promotion'] is False
    with pytest.raises(ValueError):registry.register(row)


def test_stop_rules_are_finite_and_block_prospective_reuse() -> None:
    assert stop_decision(new_evidence=False,admissible_hypothesis=False,blocker_repetitions=0,budget_ok=True,prospective_reused=False)=='WAIT_DATA'
    assert stop_decision(new_evidence=True,admissible_hypothesis=False,blocker_repetitions=3,budget_ok=True,prospective_reused=False)=='HOLD_REPEATED_BLOCKER'
    assert stop_decision(new_evidence=True,admissible_hypothesis=True,blocker_repetitions=0,budget_ok=True,prospective_reused=True)=='BLOCKED_GOVERNANCE'
    assert blocker_fingerprint('Error 123 at C:\\tmp\\abc hash '+('a'*64))==blocker_fingerprint('Error 999 at C:\\tmp\\xyz hash '+('b'*64))


def envelope():
    return {'schema_version':1,'run_id':'r','cycle_id':'c','generation_id':'g','task_key':'t','task_type':'code','worker_capability':'codex_worker','objective':'one','input_artifacts':[],'protected_manifest_hash':'a'*64,'allowed_paths':['src/ai_fc/timeseries_v7/**'],'forbidden_paths':['data/timeseries_v6/**'],'required_tests':['pytest'],'acceptance_criteria':['pass'],'max_diff_lines':100,'timeout_seconds':60,'budget':{},'secret_policy':'none','stop_after_this_task':True}


def test_one_task_envelope_and_worktree_diff_boundaries() -> None:
    validate_envelope(envelope())
    bad=envelope();bad['stop_after_this_task']=False
    with pytest.raises(ValueError):validate_envelope(bad)
    assert validate_result_paths(['src/ai_fc/timeseries_v7/a.py'],envelope()['allowed_paths'],envelope()['forbidden_paths'])['pass']
    report=validate_result_paths(['data/timeseries_v6/sealed.json'],envelope()['allowed_paths'],envelope()['forbidden_paths']);assert report['discard_diff']
    assert not validate_secret_isolation({'FRED_API_KEY':'secret'})['pass']


def test_monitor_hides_numbers_until_every_gate_and_manual_approval() -> None:
    gates={'integrity':True,'qualification':True,'operational':True,'prospective':False}
    report=status_report(loop_state='WAIT_DATA',data_freshness={},drift={},budget={},gates=gates,numbers={'h1':1},all_approved=True)
    assert report['forecast_numbers'] is None and report['numbers_visible'] is False


def test_manual_proposal_requires_all_gates_and_signature() -> None:
    gates={'integrity':True,'qualification':True,'operational':True,'prospective':True}
    proposal=create_proposal(proposal_id='p',generation_id='g',gate_bundle_hash='a'*64,owner_signature='owner',gates=gates)
    assert proposal.status=='proposed'
    with pytest.raises(ValueError):create_proposal(proposal_id='p',generation_id='g',gate_bundle_hash='a'*64,owner_signature='',gates=gates)


def test_review_pack_distinguishes_evidence_and_verifies_manifest(tmp_path) -> None:
    output=tmp_path/'review.zip';status={'historical_status':'not_run','prospective_status':'not_started'};report=build(output,status)
    assert report['automatic_publication'] is False
    with zipfile.ZipFile(output) as archive:
      manifest=json.loads(archive.read('MANIFEST.json'));assert manifest['historical_evidence_claim']=='not_run' and manifest['prospective_evidence_claim']=='not_started'
      assert manifest['file_count']==len(archive.namelist())-1
      for row in manifest['files']:
        import hashlib
        assert hashlib.sha256(archive.read(row['path'])).hexdigest()==row['sha256']
      assert 'outputs/timeseries_v7/task_results/FLYWHEEL_BOOTSTRAP/result.json' in archive.namelist()
