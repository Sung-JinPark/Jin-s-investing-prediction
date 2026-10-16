"""Offline integrity and provenance checks against retained official documents."""
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent


def main():
    manifest=json.loads((ROOT/'source_manifest.json').read_text(encoding='utf8'))
    sources={s['source_id']:s for s in manifest['sources']}
    assert len(sources)==len(manifest['sources'])==19
    for s in sources.values():
        assert s['status']=='saved'
        data=(ROOT/s['local_path']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==s['sha256'],s['source_id']
        assert len(data)==s['bytes']
    for item in manifest['derived_artifacts']:
        assert hashlib.sha256((ROOT/item['local_path']).read_bytes()).hexdigest()==item['sha256']
    evidence=json.loads((ROOT/'evidence.json').read_text(encoding='utf8'))
    assert evidence['official_forecast'] is False and evidence['probability_outputs']==[]
    for record in evidence['observations']:
        assert record['source_id'] in sources
        assert record['source_sha256']==sources[record['source_id']]['sha256']
        for m in record['measurements']:
            assert m['original_unit'] and m['normalized_unit']
            if m['original_unit']=='percent':
                assert abs(m['normalized_value']-m['original_value']/100)<1e-12
    events=evidence['policy_events']
    reserve=[e for e in events if e['event_type']=='reserve_requirement_increase']
    rates=[e for e in events if e['event_type']=='benchmark_rate_increase']
    assert len(reserve)==10 and len(rates)==6 and len(events)==17
    assert abs(sum(e['normalized_change_fraction_points'] for e in reserve)-.055)<1e-12
    all_rows=list(csv.DictReader((ROOT/'daily_indices_2005_2008.csv').open(encoding='utf8',newline='')))
    core_rows=list(csv.DictReader((ROOT/'daily_indices_2006_2008.csv').open(encoding='utf8',newline='')))
    assert len(all_rows)==1942 and len(core_rows)==1458
    assert [r for r in all_rows if r['date']>='2006-01-01']==core_rows
    assert len({(r['index_id'],r['date']) for r in all_rows})==1942
    counts=Counter((r['index_id'],int(r['date'][:4])) for r in all_rows)
    for index in ['sse_composite','sse_a_share']:
        for year,n in [(2005,242),(2006,241),(2007,242),(2008,246)]:
            assert counts[index,year]==n
    for row in all_rows:
        assert row['unit']=='index_points' and float(row['close'])>0
        assert date.fromisoformat(row['date']).weekday()<5
        assert row['source_sha256']==sources[row['source_id']]['sha256']
        assert row['value_origin']=='official_numeric_table_transcription'
    print(json.dumps({'status':'passed','source_documents':len(sources),'evidence_records':len(evidence['observations']),'policy_events':len(events),'daily_rows':len(all_rows),'source_and_derived_hashes':'verified','core_subset':'exact_match'},indent=2))


if __name__=='__main__':
    main()
