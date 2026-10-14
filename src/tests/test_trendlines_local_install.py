"""Offline installation checks never register tasks or start a collector."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import runpy

import pytest

PROJECT = Path(__file__).resolve().parents[2]
INSTALLER = PROJECT / 'tools/install_private_trendlines.ps1'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Current-user Windows installer')


def install(runtime):
    return subprocess.run(['powershell', '-NoProfile', '-File', str(INSTALLER),
                           '-RuntimeDirectory', str(runtime), '-PythonExecutable', sys.executable,
                           '-NoStart', '-NoStartupRegistration'], capture_output=True, text=True, timeout=60)


def test_offline_installer_is_independent_and_preserves_existing_evidence(tmp_path):
    runtime = tmp_path / 'runtime'
    sentinel = runtime / 'app/outputs/trendlines/private-research-view/user-history-sentinel.json'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"preserve":"personal evidence"}')
    result = install(runtime)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((runtime / 'installation.json').read_text('utf-8'))
    assert manifest['startup_method'] == 'none'
    assert manifest['private_prices_only'] is True
    app = runtime / 'app'
    assert (app / 'tools/run_private_trendlines.py').is_file()
    assert (app / 'src/ai_fc/dashboard_parts/trendlines.js').is_file()
    assert (app / 'src/ai_fc/trendlines/critical.py').is_file()
    assert (app / 'data/contracts/trendlines_critical_v1.yaml').is_file()
    assert not list(app.rglob('*.sqlite*'))
    assert not list(app.rglob('.env*'))
    assert not list(app.glob('data/forecasts*'))
    assert sentinel.read_bytes() == b'{"preserve":"personal evidence"}'
    help_result = subprocess.run([sys.executable, str(app / 'tools/run_private_trendlines.py'), '--help'],
                                 capture_output=True, text=True, timeout=20)
    assert help_result.returncode == 0, help_result.stderr
    assert '--no-startup-refresh' in help_result.stdout


def test_installer_rejects_repository_ancestor_without_writes():
    result = install(PROJECT.parent)
    assert result.returncode != 0
    assert 'repository ancestor' in result.stderr


@pytest.mark.parametrize('task_arguments,accepted', [
    ('owned-base', True),
    ('owned-base --no-startup-refresh', True),
    ('owned-base --no-startup-refresh --extra', False),
    ('other-launcher', False),
])
def test_owned_task_allows_startup_refresh_mode_upgrade_only(tmp_path, task_arguments, accepted):
    # Run the actual ownership guard with fake scheduler objects; no registration,
    # process termination, collection, or writes to the installed runtime.
    source = INSTALLER.read_text('utf-8')
    guard = source[source.index('function Get-OwnedTask {'):source.index('function Stop-OwnedProcess {')]
    script = tmp_path / 'ownership.ps1'
    script.write_text(
        "param([string]$TaskArguments)\n"
        "$taskName='fixture'; $pythonWindowless='fixture-pythonw'; $baseArguments='owned-base'\n"
        "$arguments=$baseArguments + ' --no-startup-refresh'\n"
        "function Get-ScheduledTask { [pscustomobject]@{ Actions=@([pscustomobject]@{"
        " Execute='fixture-pythonw'; Arguments=$TaskArguments }) } }\n"
        + guard + "\ntry { $null=Get-OwnedTask; exit 0 } catch { exit 7 }\n",
        encoding='utf-8',
    )
    result = subprocess.run(['powershell', '-NoProfile', '-File', str(script),
                             '-TaskArguments', task_arguments], capture_output=True, text=True, timeout=20)
    assert result.returncode == (0 if accepted else 7), result.stderr


def test_installer_rejects_directory_junction(tmp_path):
    runtime, external = tmp_path / 'runtime', tmp_path / 'external'
    runtime.mkdir()
    external.mkdir()
    junction = runtime / 'app'
    helper = tmp_path / 'junction.ps1'
    helper.write_text('param($Link,$Destination)\nNew-Item -ItemType Junction -Path $Link -Target $Destination | Out-Null', encoding='utf-8')
    made = subprocess.run(['powershell', '-NoProfile', '-File', str(helper),
                           '-Link', str(junction), '-Destination', str(external)], capture_output=True, text=True)
    if made.returncode:
        pytest.skip('Windows directory junction creation unavailable')
    result = install(runtime)
    assert result.returncode != 0
    assert 'redirected directory' in result.stderr
    assert not list(external.iterdir())


def test_local_shell_does_not_embed_private_candles_and_pins_current_bundle(tmp_path):
    import shutil
    from ai_fc import dashboard
    from ai_fc.trendlines import contracts as C
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, target)
    preview = runpy.run_path(str(PROJECT / 'tools/preview_trendlines.py'))
    html_path = preview['build_local_service_preview'](tmp_path, tmp_path / 'site')
    assert html_path.is_file()
    data = json.loads((tmp_path / 'site/data.json').read_text('utf-8'))
    assert len(data['trendlines']['assets']) == 7
    assert all(row['status'] == 'hold' for row in data['trendlines']['assets'])
    assert not data['trendlines'].get('details')
    assert not list((tmp_path / 'site').glob('trendlines/*.json'))
    assert len(json.dumps(data['trendlines']).encode()) < 16 * 1024
    for suffix in ('js', 'css'):
        raw = (tmp_path / f'site/assets/trendlines.{suffix}').read_bytes()
        assert raw == (dashboard.DASHBOARD_PARTS / f'trendlines.{suffix}').read_bytes()
    manifest = json.loads((tmp_path / 'site/private_preview_manifest.json').read_text('utf-8'))
    assert manifest['embedded_private_prices'] is False
    assert '개인 연구 자동갱신' in html_path.read_text('utf-8')
