"""Explicit reviewed WTI archive/current partition; never fill a current release.

The manifest pins 620 genuine archived observations, not a blanket missingness
exception. Only an explicit dot for one of those unchanged historical revisions
can coexist with a fresh, non-regressed current release. No archive value is
passed to the normalized append boundary with a new receipt or availability.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

MANIFEST = Path('data/statistics/reference/wti_reviewed_history_v1.json')
MANIFEST_SHA256 = 'a9d30d16c94bdb22edcd0100f0dc8e0312da456f5af96f396563db46b40de9cf'
POLICY = 'wti-reviewed-history-v1'


class WtiCoverageError(ValueError):
    """An unreviewed omission or changed archive revision cannot be promoted."""


class WtiManifestError(ValueError):
    """Broken reviewed evidence is a publication-blocking integrity failure."""


def load_manifest(root: Path) -> dict[str, Any]:
    try:
        raw = (root / MANIFEST).read_bytes()
    except OSError as exc:
        raise WtiManifestError('reviewed WTI manifest unavailable') from exc
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise WtiManifestError('reviewed WTI manifest hash mismatch')
    return json.loads(raw)


def review_current(root: Path, *, rows: list[dict], raw: bytes,
                   cached: list[dict], observations: list, cutoff: date) -> dict:
    from .statistics_lab import _parse_fred_csv
    manifest = load_manifest(root)
    allowed = {x['date']: x for x in manifest['observations']}
    if not rows or rows[-1]['date'] < cached[-1]['date']:
        raise WtiCoverageError('WTI latest observation regressed')
    if rows != _parse_fred_csv(raw, 'DCOILWTICO'):
        raise WtiCoverageError('WTI rows differ from received bytes')
    if any(date.fromisoformat(x['date']) > cutoff for x in rows):
        raise WtiCoverageError('future WTI observation')
    current = {x['date']: x['value'] for x in rows}
    if len(current) != len(rows):
        raise WtiCoverageError('duplicate WTI observations')
    missing = sorted({x['date'] for x in cached} - current.keys())
    if not missing or not set(missing).issubset(allowed):
        raise WtiCoverageError('unreviewed WTI historical omission')
    cells = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    raw_by_date = {x['observation_date']: x['DCOILWTICO'] for x in cells}
    if len(raw_by_date) != len(cells) or any(raw_by_date.get(d) != '.' for d in missing):
        raise WtiCoverageError('reviewed WTI dates must be explicitly missing, not dropped')
    latest = {}
    for observation in observations:
        if observation.source_id == 'fred_market_signals' and observation.series_id == 'DCOILWTICO':
            latest[observation.observation_date] = observation
    archived_raw_path = (root / 'data/statistics/official_store/raw/fred_market_signals'
                         / (manifest['archive_raw_sha256'] + '.bin'))
    try:
        archived_raw = archived_raw_path.read_bytes()
    except OSError as exc:
        raise WtiManifestError('WTI archive evidence unavailable') from exc
    if hashlib.sha256(archived_raw).hexdigest() != manifest['archive_raw_sha256']:
        raise WtiManifestError('WTI archive raw hash mismatch')
    original = {x['date']: x['value'] for x in _parse_fred_csv(archived_raw, 'DCOILWTICO')}
    for d in missing:
        observation, expected = latest.get(d), allowed[d]
        if (observation is None or observation.observation_id != expected['observation_id']
                or observation.value != expected['value']
                or observation.raw_sha256 != expected['raw_sha256']
                or observation.available_at != expected['available_at']
                or original.get(d) != float(expected['value'])):
            raise WtiCoverageError('reviewed WTI archive identity/value changed')
    return {
        'policy': POLICY, 'manifest_sha256': MANIFEST_SHA256,
        'manifest_path': MANIFEST.as_posix(),
        'archive_raw_sha256': manifest['archive_raw_sha256'],
        'archived_dates': missing, 'archived_count': len(missing), 'archived_first': missing[0], 'archived_last': missing[-1],
        'archived_dates_sha256': hashlib.sha256('\n'.join(missing).encode()).hexdigest(),
        'archived_available_at': sorted({allowed[d]['available_at'] for d in missing}),
        'semantics': manifest['semantics'],
        'current_release_count': len(rows), 'current_release_endpoint': rows[-1]['date'],
        'current_release_raw_sha256': hashlib.sha256(raw).hexdigest(),
        'archive_rebound_to_current_receipt': False,
    }


def validate_summary(source: dict, *, projected: bool = False) -> None:
    summary = source.get('history_coverage')
    if summary is None:
        return
    if (source.get('series_id') != 'DCOILWTICO'
            or source.get('policy_source_id') != 'fred_market_signals'
            or summary.get('policy') != POLICY
            or summary.get('manifest_sha256') != MANIFEST_SHA256
            or summary.get('manifest_path') != MANIFEST.as_posix()
            or summary.get('archive_rebound_to_current_receipt') is not False):
        raise WtiCoverageError('WTI history/current source binding invalid')
    manifest = load_manifest(Path(__file__).resolve().parents[2])
    allowed = {x['date']: x for x in manifest['observations']}
    dates = summary.get('archived_dates')
    if (not isinstance(dates, list) or not dates or len(dates) > len(allowed)
            or not all(isinstance(d, str) for d in dates)
            or dates != sorted(set(dates)) or not set(dates).issubset(allowed)
            or summary.get('archived_dates_sha256') != hashlib.sha256('\n'.join(dates).encode()).hexdigest()
            or summary.get('archived_count') != len(dates)
            or summary.get('archived_first') != dates[0] or summary.get('archived_last') != dates[-1]):
        raise WtiCoverageError('WTI reviewed archive date partition invalid')
    if (type(summary.get('archived_count')) is not int or not 1 <= summary['archived_count'] <= len(allowed)
            or summary.get('archived_first') not in allowed or summary.get('archived_last') not in allowed
            or summary['archived_first'] > summary['archived_last']
            or summary.get('archive_raw_sha256') != manifest['archive_raw_sha256']
            or summary.get('semantics') != manifest['semantics']
            or type(summary.get('current_release_count')) is not int or summary['current_release_count'] < 1
            or summary.get('current_release_endpoint') != source.get('latest_observation')
            or summary.get('archived_available_at') != sorted({allowed[d]['available_at'] for d in dates})):
        raise WtiCoverageError('WTI history/current coverage invalid')
    for key in ['current_release_raw_sha256', 'archived_dates_sha256']:
        value = str(summary.get(key, ''))
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise WtiCoverageError('WTI history/current hash invalid')
    if source.get('refresh_status') not in {'current_fred', 'verified_cache_waiting_source'}:
        raise WtiCoverageError('WTI refresh state invalid')
    if not projected and (source.get('unit') != manifest['unit'] or summary['current_release_raw_sha256'] != source.get('raw_sha256')
                          or summary['current_release_count'] + summary['archived_count'] != source.get('row_count')):
        raise WtiCoverageError('WTI current receipt/row count invalid')
