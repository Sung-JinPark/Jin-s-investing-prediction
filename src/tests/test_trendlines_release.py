"""Repository identity and raw Git bytes must match the trendline ledger."""
import importlib.util
import sqlite3
import subprocess
from pathlib import Path

from ai_fc.integrity import source_fingerprint

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_trendline_inputs_invalidate_index_but_pending_inbox_does_not(tmp_path):
    original = source_fingerprint(tmp_path)
    folder = tmp_path / 'data/trendlines'
    folder.mkdir(parents=True)
    (folder / 'asset_registry.yaml').write_text('schema_version: 1\n', encoding='utf-8')
    registered = source_fingerprint(tmp_path)
    assert registered != original
    (folder / 'inbox').mkdir()
    (folder / 'inbox/pending.json').write_text('{"unapproved":true}', encoding='utf-8')
    assert source_fingerprint(tmp_path) == registered
    (folder / 'ledgers').mkdir()
    (folder / 'ledgers/bars.jsonl').write_text('{"revision":1}\n', encoding='utf-8')
    assert source_fingerprint(tmp_path) != registered


def test_scoped_git_attributes_preserve_response_archive_and_ledger_bytes():
    paths = ['data/trendlines/raw/abc.json', 'data/trendlines/archive/bitcoin/abc.json',
             'data/trendlines/ledgers/bars.jsonl']
    result = subprocess.run(['git', 'check-attr', 'text', '--', *paths], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    assert all(line.endswith(': text: unset') for line in result.stdout.splitlines())


def test_database_audit_closes_the_disposable_connection_and_keeps_source_bytes(tmp_path):
    path = tmp_path / 'index.db'
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY)')
    connection.execute('INSERT INTO sample VALUES(1)')
    connection.commit()
    connection.close()
    before = path.read_bytes()
    spec = importlib.util.spec_from_file_location('release_audit', ROOT / 'tools/audit_trendlines_release.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    result = audit.audit_sqlite(path)
    assert result['ok'] and result['source_bytes_unchanged']
    assert path.read_bytes() == before
