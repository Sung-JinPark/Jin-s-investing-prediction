"""Two additive long pivot overlays, pinned to the unchanged three-line model.

The original representative policy, IDs, source history and events are read-only.
Missing formations stay explicit; an inspected reference is never a certified
support/resistance boundary or a historical trading signal.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from . import contracts as C, engine as E, representative as V, research as R, storage as S

ROOT = Path('data/trendlines_research_long_boundaries')
POLICY_RELATIVE = Path('data/contracts/trendlines_long_boundaries_v1.yaml')
POLICY_VERSION = 'long_boundaries_v1'
TRANSPORT_CONTRACT = 'trendlines_private_long_boundaries_transport_v1'
DETAIL_CONTRACT = 'trendlines_private_long_boundaries_v1'
SNAPSHOT_PREFIX = 'long-boundaries-snapshot-'
SNAPSHOT_RE = re.compile(SNAPSHOT_PREFIX + r'[a-f0-9]{64}\Z')
SLOTS = ('long_upper', 'long_lower')
POLICY = {
    'schema_version': 1, 'contract_id': 'trendlines_private_long_boundaries_policy_v1',
    'policy_version': POLICY_VERSION, 'publication_scope': 'private_only',
    'official_forecast_write': False, 'verified_boundary': False,
    'left': 10, 'right': 10, 'lookback_sessions': 756, 'minimum_anchor_gap': 60,
    'maximum_second_anchor_age': 252, 'maximum_distance_atr': 8.0, 'maximum_distance_fraction': .5,
    'slots': list(SLOTS),
    'intact_rank': ['independent_contacts_desc', 'latest_touch_age_asc', 'distance_atr_asc', 'anchor_gap_desc', 'line_id_asc'],
    'reference_rank': ['formation_complete_desc', 'penetration_asc', 'second_anchor_desc', 'distance_atr_asc', 'line_id_asc'],
    'role_transition': 'no_automatic_flip', 'fallback': 'labeled_pivot_structure_only',
    'contact_independence': 'disjoint_confirmation_windows_latest_first',
    'comparison_tolerance': {'absolute': 1e-6, 'relative': 1e-10},
}
REFERENCE_FIELDS = ('asset_id', 'as_of', 'source_snapshot_id', 'source_archive_sha256', 'source_content_hash',
                    'source_full_snapshot_id', 'source_full_content_hash', 'source_engine_snapshot_id',
                    'source_engine_content_hash', 'full_manifest_payload_sha256')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_policy(root):
    policy = C._yaml(Path(root), POLICY_RELATIVE)
    if policy != POLICY:
        raise C.TrendlinesError('long_boundaries_policy_not_the_versioned_contract')
    return policy


def _over(value, limit):
    return value > limit + max(1e-6, abs(limit)*1e-10)


def _identity(first, second, axis, slot):
    return 'long-boundary-line-' + C.canonical_hash({
        'policy_sha256': C.canonical_hash(POLICY), 'slot': slot, 'axis': axis,
        'origin_role': first['side'], 'first_bar_id': first['bar_id'], 'second_bar_id': second['bar_id'],
    })[:32]


def _rank(line):
    if line['classification'] == 'intact_structure':
        return (0, -line['contact_count'], line['latest_touch_age_sessions'], line['distance_atr'],
                -(line['second_anchor']['index']-line['first_anchor']['index']), line['line_id'])
    return (1, -int(line['formation_complete']), line['formation_penetration'],
            -line['second_anchor']['index'], line['distance_atr'], line['line_id'])


def _geometry_equal(a, b):
    return (b.get('status') == 'ready' and b.get('kind') == 'pivot_structure'
            and a['axis'] == b['axis'] and a['origin_role'] == b['origin_role']
            and all(a[k]['bar_id'] == b[k]['bar_id'] and a[k]['price'] == b[k]['price'] for k in ('first_anchor', 'second_anchor'))
            and a['display_start_index'] == b['display_start_index'] and a['display_end_index'] == b['display_end_index']
            and math.isclose(a['slope'], b['slope'], abs_tol=1e-6, rel_tol=1e-10)
            and math.isclose(a['intercept'], b['intercept'], abs_tol=1e-6, rel_tol=1e-10))


def _formation_counts(first, second, rows, atr):
    positions = {r['session_index']: i for i, r in enumerate(rows)}
    indices = range(first['index'], second['confirmation_end_index']+1)
    missing = sum(i not in positions for i in indices)
    unavailable = sum(atr[positions[i]] is None for i in indices if i in positions)
    return missing, unavailable


def _eligible(first, second, rows, atr, axis, future):
    if (first['side'] != second['side'] or second['index']-first['index'] < POLICY['minimum_anchor_gap']
            or rows[-1]['session_index']-second['index'] > POLICY['maximum_second_anchor_age']):
        return False
    line = {'kind': 'pivot_structure', 'axis': axis, 'first_anchor': first, 'second_anchor': second}
    price = V._scalar_value(line, rows[-1]['session_index'])
    if price is None or any(V._scalar_value(line, p['index']) is None for p in future):
        return False
    close = rows[-1]['close']
    if (first['side'] == 'support' and _over(price, close)) or (first['side'] == 'resistance' and _over(close, price)):
        return False
    distance = abs(price-close)
    return (atr[-1] is not None and atr[-1] > 0
            and not _over(distance, POLICY['maximum_distance_atr']*atr[-1])
            and not _over(distance, POLICY['maximum_distance_fraction']*close))


def _candidate(first, second, pivots, rows, atr, asset, settings, axis, future, slot):
    line = V._pivot_line(first, second, pivots, rows, atr, asset, settings, axis, slot, future)
    line['line_id'] = _identity(first, second, axis, slot)
    missing, unavailable = _formation_counts(first, second, rows, atr)
    complete = not missing and not unavailable
    intact = line['formation_valid'] and line['structural_state'] in {'active', 'reclaimed'}
    reasons = []
    if missing: reasons.append('missing_formation_sessions')
    if unavailable: reasons.append('formation_atr_unavailable')
    if line['formation_penetration'] > 1+1e-10: reasons.append('formation_penetration')
    if line['structural_state'] not in {'active', 'reclaimed'}: reasons.append('original_role_not_reestablished')
    line.update(classification='intact_structure' if intact else 'reference_structure',
                formation_complete=complete, formation_missing_sessions=missing,
                formation_atr_unavailable=unavailable, reference_reasons=reasons,
                role=first['side'] if intact else 'direction_only',
                current_side='at' if not _over(max(line['current_price'], rows[-1]['close']), min(line['current_price'], rows[-1]['close'])) else
                             'above' if line['current_price'] > rows[-1]['close'] else 'below',
                distance_atr=abs(line['current_price']-rows[-1]['close'])/atr[-1],
                selection_reason='intact_first_then_versioned_side_specific_rank',
                equivalent_to_line_ids=[], label='장기 고점 연결선' if slot == 'long_upper' else '장기 저점 연결선')
    return line


def _calculate(source, full, representative):
    rows, asset, settings = full['bars'], source['asset'], source['config']
    if full['source_snapshot_id'] != source['snapshot_id'] or C.canonical_hash(rows) != full['input_hash']:
        raise C.TrendlinesError('long_boundaries_source_input_binding_invalid')
    atr = E._atr(rows, 14, segmented=True)
    pivots = [p for p in V._pivots(rows, 10, 10) if p['index'] >= rows[-1]['session_index']-POLICY['lookback_sessions']+1]
    future = V._future(rows, asset)
    if future != representative['projection_sessions']:
        raise C.TrendlinesError('long_boundaries_representative_calendar_mismatch')
    views, audits = {}, {}
    for axis in ('linear', 'log'):
        selected, audit = [], {}
        for slot, side in zip(SLOTS, ('resistance', 'support')):
            pool = [p for p in pivots if p['side'] == side]
            candidates = [_candidate(a, b, pivots, rows, atr, asset, settings, axis, future, slot)
                          for i, a in enumerate(pool) for b in pool[i+1:]
                          if _eligible(a, b, rows, atr, axis, future)]
            candidates.sort(key=_rank)
            audit[slot] = {'candidate_count': len(candidates), 'intact_count': sum(p['classification']=='intact_structure' for p in candidates),
                           'eligible_line_ids': [p['line_id'] for p in candidates]}
            if candidates:
                winner = candidates[0]
                winner['equivalent_to_line_ids'] = [p['line_id'] for p in representative['analyses'][axis]['representatives'] if _geometry_equal(winner, p)]
            else:
                winner = {'slot': slot, 'axis': axis, 'status': 'hold', 'kind': 'pivot_structure',
                          'reason_codes': ['no_eligible_confirmed_long_structure'], 'verified_boundary': False,
                          'current_price': None, 'points': [], 'projections': [], 'markers': [], 'equivalent_to_line_ids': []}
            selected.append(winner)
        views[axis], audits[axis] = {'boundaries': selected}, audit
    result = {'policy': deepcopy(POLICY), 'policy_sha256': C.canonical_hash(POLICY), 'input_hash': full['input_hash'],
              'calculation_settings_json': json.dumps(settings,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False),
              'config_sha256': C.canonical_hash(settings), 'calculation_tick_size': asset.get('tick_size',0.0),
              'input_bar_ids_hash': C.canonical_hash([r['bar_id'] for r in rows]),
              'reference_close': rows[-1]['close'], 'reference_session': rows[-1]['session_date'],
              'reference_index': rows[-1]['session_index'], 'atr14': atr[-1], 'projection_sessions': future,
              'analyses': views, 'candidate_audits': audits}
    result['independent_validation'] = _scalar_verify(rows, asset, settings, result)
    return result


def _scalar_candidate(first, second, pivots, rows, atr, asset, settings, axis, slot, future):
    """Separate interpolation, formation arithmetic, contacts and break runs."""
    last, close = rows[-1]['session_index'], rows[-1]['close']
    line = {'kind': 'pivot_structure', 'axis': axis, 'first_anchor': first, 'second_anchor': second,
            'origin_role': first['side'], 'activation_index': second['confirmation_end_index']}
    price = V._scalar_value(line, last)
    span = second['index']-first['index']
    if span < 60 or last-second['index'] > 252 or price is None or any(V._scalar_value(line, p['index']) is None for p in future): return None
    tolerance = max(1e-6, abs(close)*1e-10)
    if (first['side']=='support' and price>close+tolerance) or (first['side']=='resistance' and price<close-tolerance): return None
    distance = abs(price-close)
    if atr[-1] is None or atr[-1]<=0 or distance>8*atr[-1]+max(1e-6,8*atr[-1]*1e-10) or distance>.5*close+max(1e-6,.5*close*1e-10): return None
    positions = {r['session_index']: i for i, r in enumerate(rows)}
    missing, unavailable, penetration = 0, 0, 0.0
    for index in range(first['index'], second['confirmation_end_index']+1):
        position = positions.get(index)
        if position is None: missing += 1; continue
        value = V._scalar_value(line, index)
        if value is None or atr[position] is None: unavailable += 1; continue
        epsilon = max(asset.get('tick_size', 0.0), settings['touch']['atr_multiple']*atr[position], settings['touch']['price_fraction']*value, value*1e-12)
        adverse = value-rows[position]['low'] if first['side']=='support' else rows[position]['high']-value
        penetration = max(penetration, adverse/epsilon)
    touches = []
    for pivot in pivots:
        if pivot['side'] != first['side'] or pivot['index'] < first['index']: continue
        at = positions[pivot['index']]; value = V._scalar_value(line, pivot['index'])
        if value is None or atr[at] is None: continue
        epsilon = max(asset.get('tick_size', 0.0), settings['touch']['atr_multiple']*atr[at], settings['touch']['price_fraction']*value, value*1e-12)
        if abs(pivot['price']-value)<=epsilon: touches.append(pivot)
    independent, before = [], math.inf
    for pivot in sorted(touches, key=lambda p: (-p['index'], p['bar_id'])):
        if pivot['confirmation_end_index'] < before:
            independent.append(pivot); before=pivot['confirmation_start_index']
    independent.reverse()
    state = V._scalar_state(line, rows, atr, asset, settings)
    valid = not missing and not unavailable and penetration<=1+1e-10
    intact = valid and state['state'] in {'active','reclaimed'}
    identifier = 'long-boundary-line-'+C.canonical_hash({'policy_sha256':C.canonical_hash(POLICY), 'slot':slot,'axis':axis,
                   'origin_role':first['side'],'first_bar_id':first['bar_id'],'second_bar_id':second['bar_id']})[:32]
    latest = last-max((p['index'] for p in independent), default=second['index'])
    rank = ((0,-len(independent),latest,distance/atr[-1],-span,identifier) if intact else
            (1,-int(not missing and not unavailable),penetration,-second['index'],distance/atr[-1],identifier))
    return {'line_id':identifier,'first_anchor':first,'second_anchor':second,'rank':rank,'current_price':price,
            'classification':'intact_structure' if intact else 'reference_structure','formation_valid':valid,
            'formation_missing_sessions':missing,'formation_atr_unavailable':unavailable,'formation_penetration':penetration,
            'contacts':independent,'structural_review':state}


def _scalar_verify(rows, asset, settings, result):
    atr = V._scalar_atr(rows)
    pivots = [p for p in V._scalar_pivots(rows,10,10) if p['index']>=rows[-1]['session_index']-755]
    checked = 0
    for axis in ('linear','log'):
        for slot,side in zip(SLOTS,('resistance','support')):
            pool = [p for p in pivots if p['side']==side]
            expected = [candidate for i,a in enumerate(pool) for b in pool[i+1:]
                        if (candidate:=_scalar_candidate(a,b,pivots,rows,atr,asset,settings,axis,slot,result['projection_sessions'])) is not None]
            expected.sort(key=lambda p:p['rank'])
            audit = result['candidate_audits'][axis][slot]
            if audit != {'candidate_count':len(expected),'intact_count':sum(p['classification']=='intact_structure' for p in expected),
                          'eligible_line_ids':[p['line_id'] for p in expected]}:
                raise C.TrendlinesError('long_boundaries_scalar_candidate_completeness_or_rank')
            actual = next(p for p in result['analyses'][axis]['boundaries'] if p['slot']==slot)
            if not expected:
                if actual['status']!='hold': raise C.TrendlinesError('long_boundaries_scalar_unnecessary_line')
                continue
            winner=expected[0]
            for key in ('line_id','first_anchor','second_anchor','classification','formation_valid','formation_missing_sessions','formation_atr_unavailable','contacts'):
                if actual[key]!=winner[key]: raise C.TrendlinesError('long_boundaries_scalar_'+key)
            V._near(actual['formation_penetration'],winner['formation_penetration'],'long_formation_penetration')
            if any(actual['structural_review'][key]!=value for key,value in winner['structural_review'].items()):
                raise C.TrendlinesError('long_boundaries_scalar_break_or_reclaim')
            for point in actual['points']+actual['projections']:
                V._near(point['price'],V._scalar_value(actual,point['index']),'long_interpolation')
                checked+=1
    return {'independent_candidate_completeness_and_rank':True,'independent_pivots_atr_contacts_and_breaks':True,
            'arithmetic_points_checked':checked,'absolute_tolerance':1e-6,'relative_tolerance':1e-10}


def _export(snapshot):
    body={k:deepcopy(v) for k,v in snapshot.items() if k not in {'content_hash','policy','candidate_audits'}}
    body.update(contract_id=DETAIL_CONTRACT,rights_status=R.RIGHTS,source_context=R.CONTEXT)
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    envelope={'schema_version':1,'contract_id':TRANSPORT_CONTRACT,'publication_scope':'private_only',
              'asset_id':body['asset_id'],'snapshot_id':body['snapshot_id'],'payload_json':raw,'payload_sha256':_sha(raw.encode())}
    if len(raw.encode())>R.MAX_PRIVATE_PAYLOAD_BYTES or len(S.encode(envelope))>R.MAX_PRIVATE_ENVELOPE_BYTES:
        raise C.TrendlinesError('long_boundaries_transport_exceeds_budget')
    return envelope


def decode_envelope(envelope):
    try:
        if (set(envelope)!={'schema_version','contract_id','publication_scope','asset_id','snapshot_id','payload_json','payload_sha256'}
                or type(envelope['schema_version']) is not int or envelope['schema_version']!=1
                or envelope['contract_id']!=TRANSPORT_CONTRACT or envelope['publication_scope']!='private_only'
                or envelope['asset_id'] not in R.SYMBOLS or not SNAPSHOT_RE.fullmatch(envelope['snapshot_id'])
                or len(S.encode(envelope))>R.MAX_PRIVATE_ENVELOPE_BYTES): raise ValueError('envelope')
        raw=envelope['payload_json'].encode()
        if len(raw)>R.MAX_PRIVATE_PAYLOAD_BYTES or _sha(raw)!=envelope['payload_sha256']: raise ValueError('payload')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value: raise ValueError('duplicate key')
                value[key]=item
            return value
        body=json.loads(envelope['payload_json'],object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError(v)))
        if (type(body.get('schema_version')) is not int or body['schema_version']!=1 or body.get('contract_id')!=DETAIL_CONTRACT
                or body.get('policy_version')!=POLICY_VERSION or body.get('policy_sha256')!=C.canonical_hash(POLICY)
                or body.get('asset_id')!=envelope['asset_id'] or body.get('snapshot_id')!=envelope['snapshot_id']
                or body.get('publication_scope')!='private_only' or body.get('rights_status')!=R.RIGHTS or body.get('source_context')!=R.CONTEXT
                or any(body.get(k) is not False for k in ('verified_source','verified_boundary','official_forecast_write','historical_signals_available'))
                or body.get('events')!=[] or not V.SNAPSHOT_RE.fullmatch(body['source_representative_snapshot_id'])
                or not C.SHA256.fullmatch(body['source_representative_payload_sha256'])
                or not C.SHA256.fullmatch(body['input_hash']) or not C.SHA256.fullmatch(body['input_bar_ids_hash'])
                or _sha(body['calculation_settings_json'].encode())!=body['config_sha256']
                or not C._finite_number(body['calculation_tick_size']) or body['calculation_tick_size']<0
                or set(body['analyses'])!={'linear','log'}): raise ValueError('body')
        C.aware_time(body['as_of'])
        if not C._finite_number(body['reference_close']) or body['reference_close']<=0 or type(body['reference_index']) is not int: raise ValueError('reference')
        future=body['projection_sessions'];count=30 if body['asset_id']=='bitcoin' else 21
        if len(future)!=count or any(p['offset']!=i or p['index']!=body['reference_index']+i for i,p in enumerate(future,1)): raise ValueError('future')
        for axis,view in body['analyses'].items():
            if [p['slot'] for p in view['boundaries']]!=list(SLOTS): raise ValueError('slots')
            for line in view['boundaries']:
                if line['axis']!=axis or line['verified_boundary'] is not False or line['kind']!='pivot_structure': raise ValueError('line')
                if line['status']=='hold':
                    if line['current_price'] is not None or line['points'] or line['projections'] or line['markers']: raise ValueError('hold')
                    continue
                first,second=line['first_anchor'],line['second_anchor'];side='resistance' if line['slot']=='long_upper' else 'support'
                if (line['status']!='ready' or first['side']!=side or second['side']!=side or line['origin_role']!=side
                        or line['line_id']!=_identity(first,second,axis,line['slot']) or second['index']-first['index']<60
                        or first['index']<body['reference_index']-755 or body['reference_index']-second['index']>252
                        or line['classification'] not in {'intact_structure','reference_structure'}
                        or line['role']!=(side if line['classification']=='intact_structure' else 'direction_only')
                        or line['contact_count']!=len(line['contacts']) or line['contact_count']<2
                        or line['parameters']!={'left':10,'right':10,'min_anchor_gap':60}
                        or line['display_start_index']!=first['index'] or line['coordinate_origin_index']!=first['index']
                        or line['display_end_index']!=future[-1]['index'] or len(line['projections'])!=count
                        or not all(C._finite_number(line[k]) for k in ('slope','intercept','current_price','formation_penetration','distance_atr'))): raise ValueError('geometry')
                transform=math.log if axis=='log' else float
                V._near(line['intercept'],transform(first['price']),'long_intercept')
                V._near(line['slope'],(transform(second['price'])-transform(first['price']))/(second['index']-first['index']),'long_slope')
                if (line['direction']!=V._direction(line['slope']) or line['activation_index']!=second['confirmation_end_index']
                        or line['activation_session']!=second['confirmation_session']
                        or line['geometry_status']!=('three_contact' if line['contact_count']>=3 else 'two_anchor')
                        or len(line['markers'])!=2 or line['contacts']!=line['independent_contacts']
                        or line['classification']!=('intact_structure' if line['formation_valid'] and line['structural_state'] in {'active','reclaimed'} else 'reference_structure')
                        or line['formation_complete']!=(not line['formation_missing_sessions'] and not line['formation_atr_unavailable'])
                        or any(type(line[k]) is not int or line[k]<0 for k in ('formation_missing_sessions','formation_atr_unavailable'))): raise ValueError('classification')
                price=line['current_price'];close=body['reference_close'];at=body['atr14']
                if (not C._finite_number(at) or at<=0 or price<=0 or _over(abs(price-close),8*at) or _over(abs(price-close),.5*close)
                        or (side=='support' and _over(price,close)) or (side=='resistance' and _over(close,price))): raise ValueError('distance')
                V._near(line['distance_atr'],abs(price-close)/at,'long_distance')
                if any(C.aware_time(p['confirmed_at'])>C.aware_time(body['as_of']) or p['confirmation_end_index']>body['reference_index'] for p in [first,second]+line['contacts']): raise ValueError('future pivot')
                V._near(line['current_price'],V._scalar_value(line,body['reference_index']),'long_current')
                for point in line['points']+line['projections']:
                    if point['price'] is None or point['price']<=0 or set(point)&{'open','high','low','close','volume'}: raise ValueError('projection')
                    V._near(point['price'],V._scalar_value(line,point['index']),'long_point')
                for point,date in zip(line['projections'],future):
                    if any(point[k]!=date[k] for k in ('index','session','offset')): raise ValueError('projection date')
        return body
    except (ValueError,KeyError,TypeError,AttributeError,OverflowError,RecursionError) as exc:
        raise C.TrendlinesError('long_boundaries_transport_invalid: '+str(exc)) from exc


def _latest(root):
    path=S.safe_path(root,(ROOT/'latest.json').as_posix())
    if not path.is_file(): return {'assets':{}}
    value=R._checked(path)
    if (value.get('schema_version')!=1 or value.get('contract_id')!='trendlines_private_long_boundaries_latest_v1'
            or not isinstance(value.get('assets'),dict) or set(value['assets'])-set(R.SYMBOLS) or path.read_bytes()!=S.encode(value)):
        raise C.TrendlinesError('long_boundaries_latest_invalid')
    return value


def _context(root,asset_id,now=None,*,reparse=False,source_snapshot_id=None):
    options={} if source_snapshot_id is None else {'source_snapshot_id':source_snapshot_id}
    envelope=V.load_detail(root,asset_id,now=now,**options)
    if envelope is None: return None
    representative,source,full=V._read_snapshot(root,envelope['snapshot_id'],now,reparse=reparse)
    if envelope!=V._export(representative): raise C.TrendlinesError('long_boundaries_representative_export_mismatch')
    return representative,source,full,envelope


def _read_snapshot(root,sid,now=None,*,reparse=False):
    if not isinstance(sid,str) or not SNAPSHOT_RE.fullmatch(sid): raise C.TrendlinesError('long_boundaries_snapshot_id_invalid')
    path=S.safe_path(root,(ROOT/'snapshots'/(sid+'.json')).as_posix());snapshot=R._checked(path)
    identity={k:v for k,v in snapshot.items() if k not in {'snapshot_id','content_hash'}}
    if (snapshot.get('snapshot_id')!=sid or SNAPSHOT_PREFIX+C.canonical_hash(identity)!=sid
            or snapshot.get('contract_id')!='trendlines_private_long_boundaries_snapshot_v1' or snapshot.get('policy')!=POLICY
            or path.read_bytes()!=S.encode(snapshot)): raise C.TrendlinesError('long_boundaries_snapshot_identity_invalid')
    representative,source,full=V._read_snapshot(root,snapshot['source_representative_snapshot_id'],now,reparse=reparse)
    envelope=V._export(representative)
    if (any(snapshot[k]!=representative[k] for k in REFERENCE_FIELDS)
            or snapshot['source_representative_content_hash']!=representative['content_hash']
            or snapshot['source_representative_payload_sha256']!=envelope['payload_sha256']
            or snapshot['representative_lines_sha256']!=C.canonical_hash(representative['analyses'])
            or snapshot['calculation_settings_json']!=json.dumps(source['config'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
            or snapshot['calculation_tick_size']!=source['asset'].get('tick_size',0.0)
            or snapshot['input_hash']!=full['input_hash'] or snapshot['projection_sessions']!=representative['projection_sessions']):
        raise C.TrendlinesError('long_boundaries_source_binding_invalid')
    for axis,view in snapshot['analyses'].items():
        for line in view['boundaries']:
            if line['status']=='ready' and line['equivalent_to_line_ids']!=[p['line_id'] for p in representative['analyses'][axis]['representatives'] if _geometry_equal(line,p)]:
                raise C.TrendlinesError('long_boundaries_alias_binding_invalid')
    return snapshot,source,full,representative


def verify(root,*,asset_id=None,replay=True,now=None):
    root=Path(root);count=0;pending={};cache=R._ACTIVE_REPLAY_CACHE.get() if replay else None
    functions=(_calculate,_candidate,_eligible,_identity,_rank,_over,_geometry_equal,_scalar_verify,_scalar_candidate,_formation_counts,
               V._pivot_line,V._geometry,V._state,V._independent,V._pivots,V._scalar_pivots,V._scalar_atr,V._scalar_state,
               V._scalar_value,V._future,E._atr,E._epsilon,E._value,E._pivots,C.session_schedule,R._prepare)
    try:
        load_policy(root);snapshots={}
        for path in sorted(S.safe_path(root,(ROOT/'snapshots').as_posix()).glob('*.json')):
            if asset_id is not None and R._checked(path).get('asset_id')!=asset_id: continue
            snapshot,source,full,representative=_read_snapshot(root,path.stem,now,reparse=replay)
            key=('long_boundaries',str(root.resolve()),snapshot['content_hash'],_sha(path.read_bytes()),source['content_hash'],
                 full['content_hash'],representative['content_hash'],tuple(id(f) for f in functions))
            if replay and (cache is None or not cache._contains(key,functions)):
                actual=_calculate(source,full,representative)
                if any(snapshot.get(k)!=v for k,v in actual.items()): raise C.TrendlinesError('long_boundaries_replay_differs')
                pending[key]=functions
            export=S.safe_path(root,(ROOT/'exports'/snapshot['snapshot_id']/'detail.json').as_posix())
            if export.read_bytes()!=S.encode(_export(snapshot)): raise C.TrendlinesError('long_boundaries_export_binding_invalid')
            decode_envelope(S.read_json(export));snapshots[snapshot['snapshot_id']]=snapshot;count+=1
        for asset,pointer in _latest(root)['assets'].items():
            if asset_id is not None and asset!=asset_id: continue
            snapshot=snapshots[pointer['snapshot_id']]
            _check_pointer(root,pointer,snapshot)
            if snapshot['asset_id']!=asset: raise C.TrendlinesError('long_boundaries_latest_asset_invalid')
        if cache is not None: cache._remember(pending)
        return {'ok':True,'errors':[],'snapshots':count,'replay':replay}
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
        return {'ok':False,'errors':[str(exc)],'snapshots':count,'replay':replay}


def _check_pointer(root,pointer,snapshot):
    sp=ROOT/'snapshots'/(snapshot['snapshot_id']+'.json');ep=ROOT/'exports'/snapshot['snapshot_id']/'detail.json'
    if (pointer['snapshot_path']!=sp.as_posix() or pointer['detail_path']!=ep.as_posix()
            or _sha(S.safe_path(root,sp.as_posix()).read_bytes())!=pointer['snapshot_sha256']
            or _sha(S.safe_path(root,ep.as_posix()).read_bytes())!=pointer['detail_sha256']):
        raise C.TrendlinesError('long_boundaries_latest_binding_invalid')


def refresh(root,asset_id,now=None):
    root=Path(root)
    with S.writer_lock(root):
        audit=verify(root,asset_id=asset_id,replay=True,now=now)
        if not audit['ok']: raise C.TrendlinesError('long_boundaries_existing_integrity_failed: '+'; '.join(audit['errors']))
        context=_context(root,asset_id,now,reparse=True)
        if context is None: return {'asset_id':asset_id,'status':'hold','changed':False,'reason_codes':['missing_representative']}
        representative,source,full,envelope=context;pointer=_latest(root)
        prior=pointer['assets'].get(asset_id)
        if prior:
            previous,*_=_read_snapshot(root,prior['snapshot_id'],now)
            if previous['source_representative_snapshot_id']==representative['snapshot_id']:
                return {'asset_id':asset_id,'status':'ready','changed':False,'long_boundaries_snapshot_id':previous['snapshot_id']}
        body={k:deepcopy(representative[k]) for k in REFERENCE_FIELDS}
        body.update(schema_version=1,contract_id='trendlines_private_long_boundaries_snapshot_v1',publication_scope='private_only',
                    verified_source=False,verified_boundary=False,official_forecast_write=False,historical_signals_available=False,events=[],
                    policy_version=POLICY_VERSION,source_representative_snapshot_id=representative['snapshot_id'],
                    source_representative_content_hash=representative['content_hash'],source_representative_payload_sha256=envelope['payload_sha256'],
                    representative_lines_sha256=C.canonical_hash(representative['analyses']),**_calculate(source,full,representative))
        body['snapshot_id']=SNAPSHOT_PREFIX+C.canonical_hash(body);snapshot=V._hash(body);export=_export(snapshot);decode_envelope(export)
        if _context(root,asset_id,now)!=context: raise C.TrendlinesError('long_boundaries_source_changed_during_calculation')
        sp=ROOT/'snapshots'/(snapshot['snapshot_id']+'.json');ep=ROOT/'exports'/snapshot['snapshot_id']/'detail.json'
        S.atomic_json(S.safe_path(root,sp.as_posix()),snapshot,immutable=True)
        S.atomic_json(S.safe_path(root,ep.as_posix()),export,immutable=True)
        if _context(root,asset_id,now)!=context: raise C.TrendlinesError('long_boundaries_source_changed_before_publication')
        assets=deepcopy(pointer['assets']);assets[asset_id]={'snapshot_id':snapshot['snapshot_id'],'snapshot_path':sp.as_posix(),
                    'snapshot_sha256':_sha(S.encode(snapshot)),'detail_path':ep.as_posix(),'detail_sha256':_sha(S.encode(export))}
        S.atomic_json(S.safe_path(root,(ROOT/'latest.json').as_posix()),V._hash({'schema_version':1,'contract_id':'trendlines_private_long_boundaries_latest_v1','assets':assets}))
        return {'asset_id':asset_id,'status':'ready','changed':True,'long_boundaries_snapshot_id':snapshot['snapshot_id'],
                'validation':snapshot['independent_validation']}


def load_detail(root,asset_id,now=None,*,source_snapshot_id=None):
    root=Path(root);load_policy(root)
    if asset_id not in R.SYMBOLS: raise C.TrendlinesError('long_boundaries_asset_not_registered')
    pointer=_latest(root)['assets'].get(asset_id)
    if pointer is None: return None
    snapshot,*_=_read_snapshot(root,pointer['snapshot_id'],now);_check_pointer(root,pointer,snapshot)
    context=_context(root,asset_id,now,source_snapshot_id=source_snapshot_id)
    if context is None or context[0]['snapshot_id']!=snapshot['source_representative_snapshot_id']:
        raise C.TrendlinesError('long_boundaries_snapshot_is_not_current_source')
    envelope=S.read_json(S.safe_path(root,pointer['detail_path']))
    if envelope!=_export(snapshot): raise C.TrendlinesError('long_boundaries_export_mismatch')
    decode_envelope(envelope)
    return envelope
