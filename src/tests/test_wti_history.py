from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from ai_fc import statistics_lab as lab
from ai_fc.authoritative_statistics import read_normalized_observations
from ai_fc.wti_history import (
    MANIFEST, MANIFEST_SHA256, WtiCoverageError, WtiManifestError,
    load_manifest, review_current, validate_summary,
)

ROOT = Path(__file__).resolve().parents[2]


def csv_bytes(rows, missing):
    values = {r['date']: str(r['value']) for r in rows}
    values.update({d: '.' for d in missing})
    return ('observation_date,DCOILWTICO\n' + ''.join(d+','+v+'\n' for d,v in sorted(values.items()))).encode()


@pytest.fixture(scope='module')
def historical_wti():
    manifest = load_manifest(ROOT)
    raw = (ROOT/'data/statistics/official_store/raw/fred_market_signals/8688eeb0c4807836deb9afc28917c6ab7be099f1df491dce4e7c0e351b7f4942.bin').read_bytes()
    rows = lab._parse_fred_csv(raw, 'DCOILWTICO')
    missing = [x['date'] for x in manifest['observations']]
    cached = sorted(rows + [{'date':x['date'],'value':float(x['value'])} for x in manifest['observations']],key=lambda r:r['date'])
    ids = {x['observation_id'] for x in manifest['observations']}
    obs = [r for r in read_normalized_observations(ROOT/'data/statistics/official_store',series_id='DCOILWTICO') if r.observation_id in ids]
    assert len(obs)==620
    return manifest, rows, cached, missing, obs


@pytest.fixture
def prepared(tmp_path, historical_wti):
    manifest, rows, cached, missing, obs = historical_wti
    (tmp_path/MANIFEST).parent.mkdir(parents=True)
    shutil.copyfile(ROOT/MANIFEST,tmp_path/MANIFEST)
    old = Path('data/statistics/official_store/raw/fred_market_signals')/(manifest['archive_raw_sha256']+'.bin')
    (tmp_path/old).parent.mkdir(parents=True)
    shutil.copyfile(ROOT/old,tmp_path/old)
    return tmp_path, copy.deepcopy(rows), copy.deepcopy(cached), list(missing), list(obs)


def review(prepared, **overrides):
    root, rows, cached, missing, obs = prepared
    return review_current(root, rows=overrides.get('rows',rows),
                          raw=overrides.get('raw',csv_bytes(overrides.get('rows',rows),missing)),
                          cached=cached, observations=overrides.get('observations',obs),
                          cutoff=overrides.get('cutoff',date(2026,10,22)))


def test_reviewed_archive_allows_fresh_tail_without_filling_response(prepared):
    root, rows, cached, missing, obs = prepared
    rows.append({'date':'2026-10-21','value':108.12})
    raw=csv_bytes(rows,missing)
    result=review(prepared,raw=raw)
    assert result['archived_count']==620 and result['current_release_count']==7360
    assert result['current_release_endpoint']=='2026-10-21'
    assert result['current_release_raw_sha256']==hashlib.sha256(raw).hexdigest()
    assert result['archive_rebound_to_current_receipt'] is False
    assert not set(missing)&{r['date'] for r in rows}
    source={'series_id':'DCOILWTICO','policy_source_id':'fred_market_signals','history_coverage':result,
            'refresh_status':'current_fred','unit':'dollars_per_barrel','latest_observation':'2026-10-21','raw_sha256':result['current_release_raw_sha256'],
            'row_count':len(cached)+1}
    validate_summary(source)
    validate_summary({k:v for k,v in source.items() if k not in ('raw_sha256','row_count')},projected=True)
    source['raw_sha256']='0'*64
    with pytest.raises(WtiCoverageError,match='receipt'):validate_summary(source)


@pytest.mark.parametrize('kind',['recent_missing','unreviewed_old_missing','dropped_archive_row','duplicate','future','regressed','row_raw_mismatch','archive_revision'])
def test_unreviewed_or_invalid_change_cannot_use_archive_exception(prepared,kind):
    root,rows,cached,missing,obs=prepared
    kw={}
    if kind=='recent_missing':rows.pop(-2)
    if kind=='unreviewed_old_missing':rows.pop(0)
    if kind=='dropped_archive_row':kw['raw']=csv_bytes(rows,missing[1:])
    if kind=='duplicate':kw['raw']=csv_bytes(rows,missing)+f"{rows[-1]['date']},{rows[-1]['value']}\n".encode()
    if kind=='future':rows.append({'date':'2026-10-23','value':100})
    if kind=='regressed':rows.pop()
    if kind=='row_raw_mismatch':kw['raw']=csv_bytes(rows,missing);rows[-1]['value']+=1
    if kind=='archive_revision':obs[0]=obs[0].model_copy(update={'value':'999'})
    with pytest.raises((WtiCoverageError,lab.StatisticsLabError)):review(prepared,**kw)


def test_restored_history_is_current_and_new_revision_can_be_appended(prepared):
    root,rows,cached,missing,obs=prepared
    restored=missing.pop(0)
    rows.append({'date':restored,'value':17.70});rows.sort(key=lambda r:r['date'])
    result=review(prepared)
    assert result['archived_count']==619 and result['current_release_count']==7360
    assert any(r['date']==restored and r['value']==17.70 for r in rows)


@pytest.mark.parametrize('kind',['manifest','archive_raw','missing_manifest'])
def test_review_evidence_corruption_is_fatal_not_source_wait(prepared,kind):
    root,rows,cached,missing,obs=prepared
    path=root/MANIFEST
    if kind=='archive_raw':path=root/'data/statistics/official_store/raw/fred_market_signals'/('828546b69c140a559527eda2b8514f02f98d44f02d2fd87f3834eefef0f4b62a.bin')
    if kind=='missing_manifest':path.unlink()
    else:path.write_bytes(b'controlled corrupted proof')
    with pytest.raises(WtiManifestError):review(prepared)


def test_manifest_pins_exact_620_original_observations(historical_wti):
    manifest,rows,cached,missing,obs=historical_wti
    assert hashlib.sha256((ROOT/MANIFEST).read_bytes()).hexdigest()==MANIFEST_SHA256
    assert len(set(missing))==620 and min(missing)=='1995-01-06' and max(missing)=='2015-02-04'
    assert {r.raw_sha256 for r in obs}=={manifest['archive_raw_sha256']}
    assert manifest['model_use'] is manifest['official_forecast_input'] is False
