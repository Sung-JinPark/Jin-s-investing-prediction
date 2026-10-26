"""Atomic private chart selection; immutable evidence and model history stay intact.

Calculation pointers may advance independently. HTTP selects one verified set
of candles/full geometry/overlays, then reads only those immutable artifacts.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json

from . import contracts as C, research as R, storage as S

ROOT = Path('data/trendlines_research_delivery')
PREFIX = 'private-delivery-'
MAX_BYTES = R.MAX_PRIVATE_ENVELOPE_BYTES + 16 * 1024
KINDS = ('full', 'critical', 'representative', 'long_boundaries')


def _modules():
    from . import full_history as F, critical as K, representative as V, long_boundaries as B
    return dict(zip(KINDS, (F, K, V, B)))


def selection_path(root, asset_id):
    if asset_id not in R.SYMBOLS:
        raise C.TrendlinesError('private_delivery_asset_not_registered')
    return S.safe_path(Path(root), (ROOT/'selected'/(asset_id+'.json')).as_posix())


def load_selected(root, asset_id, *, now=None):
    path = selection_path(root, asset_id)
    if not path.exists():
        return None
    pointer_bytes = path.read_bytes()
    if len(pointer_bytes)>4096:
        raise C.TrendlinesError('private_delivery_pointer_size_invalid')
    pointer = json.loads(pointer_bytes)
    if not isinstance(pointer,dict) or pointer.get('content_hash')!=C.canonical_hash({k:v for k,v in pointer.items() if k!='content_hash'}):
        raise C.TrendlinesError('private_delivery_pointer_hash_invalid')
    sid = pointer.get('snapshot_id')
    if (pointer.get('contract_id') != 'trendlines_private_delivery_pointer_v1'
            or type(pointer.get('schema_version')) is not int or pointer['schema_version'] != 1 or pointer.get('asset_id') != asset_id
            or not isinstance(sid, str) or not sid.startswith(PREFIX)
            or not C.SHA256.fullmatch(sid[len(PREFIX):])
            or pointer.get('snapshot_path') != (ROOT/'snapshots'/(sid+'.json')).as_posix()
            or pointer_bytes!=S.encode(pointer)):
        raise C.TrendlinesError('private_delivery_pointer_invalid')
    snapshot_path = S.safe_path(Path(root), pointer['snapshot_path'])
    raw = snapshot_path.read_bytes()
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != pointer.get('snapshot_sha256'):
        raise C.TrendlinesError('private_delivery_snapshot_bytes_invalid')
    value = R._checked(snapshot_path)
    identity = {k:v for k,v in value.items() if k not in ('snapshot_id','content_hash')}
    if (type(value.get('schema_version')) is not int or value['schema_version'] != 1 or value.get('contract_id') != 'trendlines_private_delivery_v1'
            or value.get('publication_scope') != 'private_only' or value.get('asset_id') != asset_id
            or value.get('snapshot_id') != sid or PREFIX+C.canonical_hash(identity) != sid
            or set(value.get('models', {})) != set(KINDS) or raw != S.encode(value)):
        raise C.TrendlinesError('private_delivery_snapshot_invalid')
    from .local_service import validate_envelope
    current = validate_envelope(S.encode(value['ohlc']), asset_id, now=S.aware_time(now))
    if current['snapshot_id'] != value.get('source_snapshot_id'):
        raise C.TrendlinesError('private_delivery_ohlc_binding_invalid')
    return value


def read_envelope(root, selected, kind, *, now=None):
    """Recheck exact immutable bytes, source evidence and selected model links."""
    module = _modules()[kind]
    if kind!='full':
        module.load_policy(root)
    row = selected['models'][kind]
    sid = row['snapshot_id']
    snapshot, source, *_ = module._read_snapshot(Path(root), sid, **({} if kind=='full' else {'now':now}))
    if S.aware_time(source['capture_asof'])>S.aware_time(now):
        raise C.TrendlinesError('private_delivery_source_after_cutoff')
    if (snapshot['asset_id'] != selected['asset_id'] or snapshot['source_snapshot_id'] != selected['source_snapshot_id']
            or source['snapshot_id'] != selected['source_snapshot_id']
            or (kind!='full' and snapshot['source_full_snapshot_id'] != selected['models']['full']['snapshot_id'])
            or (kind=='long_boundaries' and snapshot['source_representative_snapshot_id'] != selected['models']['representative']['snapshot_id'])):
        raise C.TrendlinesError('private_delivery_model_cohort_mismatch')
    snapshot_relative = module.ROOT/'snapshots'/(sid+'.json')
    export_relative = module.ROOT/'exports'/sid/('manifest.json' if kind=='full' else 'detail.json')
    key = 'manifest' if kind=='full' else 'detail'
    if (row['snapshot_path'] != snapshot_relative.as_posix() or row[key+'_path'] != export_relative.as_posix()
            or row['snapshot_sha256'] != hashlib.sha256(S.safe_path(Path(root),snapshot_relative.as_posix()).read_bytes()).hexdigest()):
        raise C.TrendlinesError('private_delivery_model_pointer_invalid')
    path = S.safe_path(Path(root),export_relative.as_posix())
    raw = path.read_bytes()
    envelope = S.read_json(path)
    expected = module._exports(snapshot)[0] if kind=='full' else module._export(snapshot)
    if envelope != expected or raw != S.encode(expected) or hashlib.sha256(raw).hexdigest()!=row[key+'_sha256']:
        raise C.TrendlinesError('private_delivery_model_export_invalid')
    body = module.decode_envelope(envelope, module.MANIFEST_CONTRACT) if kind=='full' else module.decode_envelope(envelope)
    current = R.decode_private_import(selected['ohlc'])
    if body['as_of'] != current['as_of']:
        raise C.TrendlinesError('private_delivery_model_asof_mismatch')
    if kind!='full' and (body['reference_session']!=current['observation_through']
            or body['reference_close']!=current['bars'][-1]['close']
            or body['reference_index']!=current['bars'][-1]['session_index']):
        raise C.TrendlinesError('private_delivery_model_reference_mismatch')
    return envelope


def publish(root, asset_id, ohlc):
    """Validate endpoints after the caller's source/replay gates, then select."""
    root = Path(root)
    R._check_replay_asset(asset_id)
    from .local_service import validate_envelope
    current = validate_envelope(S.encode(ohlc), asset_id, now=S.aware_time(None))
    with S.writer_lock(root):
        models = {kind:deepcopy(module._latest(root)['assets'][asset_id]) for kind,module in _modules().items()}
        body = {'schema_version':1,'contract_id':'trendlines_private_delivery_v1',
                'publication_scope':'private_only','asset_id':asset_id,
                'source_snapshot_id':current['snapshot_id'],'ohlc':deepcopy(ohlc),'models':models}
        body['snapshot_id'] = PREFIX+C.canonical_hash(body)
        body['content_hash'] = C.canonical_hash(body)
        if len(S.encode(body))>MAX_BYTES:
            raise C.TrendlinesError('private_delivery_size_budget_exceeded')
        for kind in KINDS:
            read_envelope(root,body,kind)
        relative = ROOT/'snapshots'/(body['snapshot_id']+'.json')
        S.atomic_json(S.safe_path(root,relative.as_posix()),body,immutable=True)
        pointer = {'schema_version':1,'contract_id':'trendlines_private_delivery_pointer_v1','asset_id':asset_id,
                   'snapshot_id':body['snapshot_id'],'snapshot_path':relative.as_posix(),
                   'snapshot_sha256':hashlib.sha256(S.encode(body)).hexdigest()}
        pointer['content_hash'] = C.canonical_hash(pointer)
        S.atomic_json(selection_path(root,asset_id),pointer)
    return {'snapshot_id':body['snapshot_id'],'source_snapshot_id':current['snapshot_id']}


def freeze_previous(root, asset_id):
    """Preserve the last delivered cohort before any calculation pointer moves."""
    selected = load_selected(root,asset_id)
    if selected is not None:
        return selected['snapshot_id']
    path = S.safe_path(Path(root),asset_id+'.trendlines.json')
    if not path.exists():
        return None
    # An incomplete first installation has no complete prior chart to retain.
    if any(asset_id not in module._latest(root)['assets'] for module in _modules().values()):
        return None
    return publish(root,asset_id,S.read_json(path))['snapshot_id']
