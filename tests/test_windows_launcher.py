"""One-click distribution safeguards; no public tunnels or external downloads."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELLS = [path for name in ('powershell', 'pwsh') if (path := shutil.which(name))]
pytestmark = pytest.mark.skipif(not SHELLS, reason='PowerShell unavailable')


def quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def run(shell, body):
    script = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + body
    return subprocess.run(
        [shell, '-NoProfile', '-EncodedCommand', base64.b64encode(script.encode('utf-16-le')).decode()],
        capture_output=True, timeout=25,
    )


@pytest.mark.parametrize('shell', SHELLS)
def test_bootstrap_scripts_parse_and_do_nothing_when_loaded(shell):
    result = run(shell, f"""
[scriptblock]::Create((Get-Content -LiteralPath {quote(ROOT / 'scripts/launch_windows.ps1')} -Raw)) | Out-Null
function Invoke-WebRequest {{ throw 'Unexpected download' }}
function Start-Process {{ throw 'Unexpected process' }}
. {quote(ROOT / 'scripts/windows_bootstrap.ps1')}
""")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('scenario', ['cached', 'retry', 'mismatch', 'unreachable'])
def test_verified_download_cache_retry_and_rejection(shell, tmp_path, scenario):
    destination = tmp_path / 'component.bin'
    payload = b'verified component'
    if scenario == 'cached':
        destination.write_bytes(payload)
    actual_hash = hashlib.sha256(payload).hexdigest()
    expected_hash = '0' * 64 if scenario == 'mismatch' else actual_hash
    result = run(shell, f"""
. {quote(ROOT / 'scripts/windows_bootstrap.ps1')}
# Load Utility before shadowing its exported download/sleep functions on PS5.
Import-Module Microsoft.PowerShell.Utility
$script:count = 0
function Start-Sleep {{}}
function Invoke-WebRequest {{
    param($Uri, $OutFile, $TimeoutSec, [switch]$UseBasicParsing)
    $script:count++
    if ('{scenario}' -eq 'unreachable' -or ('{scenario}' -eq 'retry' -and $script:count -lt 3)) {{ throw 'Network failed' }}
    [IO.File]::WriteAllBytes($OutFile, [Text.Encoding]::UTF8.GetBytes('verified component'))
}}
$failed = $false
$message = ''
try {{ Get-VerifiedLauncherDownload -Url https://example.test/package -Sha256 '{expected_hash}' -Destination {quote(destination)} 6>$null }} catch {{ $failed = $true; $message = $_.Exception.Message }}
[pscustomobject]@{{ Failed=$failed; Calls=$script:count; Message=$message }} | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    message = outcome.pop('Message')
    assert outcome == {
        'Failed': scenario in {'mismatch', 'unreachable'},
        'Calls': {'cached': 0, 'retry': 3, 'mismatch': 1, 'unreachable': 3}[scenario],
    }, message
    assert list(tmp_path.glob('*.download-*')) == []
    if scenario in {'cached', 'retry'}:
        assert destination.read_bytes() == payload
    else:
        assert not destination.exists()


@pytest.mark.parametrize('shell', SHELLS)
def test_launcher_lock_rejects_duplicate_then_releases(shell, tmp_path):
    result = run(shell, f"""
. {quote(ROOT / 'scripts/windows_bootstrap.ps1')}
$first = Enter-LauncherLock -RuntimeDirectory {quote(tmp_path)}
$rejected = $false
try {{ $second = Enter-LauncherLock -RuntimeDirectory {quote(tmp_path)} }} catch {{ $rejected = $_.Exception.Message.Contains('已有启动窗口') }}
if (-not $rejected) {{ throw 'Duplicate launch accepted' }}
$first.Dispose()
$next = Enter-LauncherLock -RuntimeDirectory {quote(tmp_path)}
$next.Dispose()
""")
    assert result.returncode == 0, result.stderr


def fake_project(tmp_path, *, failure=False):
    project = tmp_path / '下载 & !'
    (project / 'scripts/p2p').mkdir(parents=True)
    (project / 'src/web').mkdir(parents=True)
    for relative in ('requirements.txt', 'src/web/__init__.py', 'scripts/p2p/python-runtime.json', 'scripts/p2p/cloudflared-release.json'):
        (project / relative).touch()
    shutil.copyfile(ROOT / 'scripts/launch_windows.ps1', project / 'scripts/launch_windows.ps1')
    bootstrap = ROOT.joinpath('scripts/windows_bootstrap.ps1').read_text(encoding='utf-8-sig')
    # Keep the real locking function; mock only network/runtime preparation.
    bootstrap += "\nfunction Initialize-LauncherPython { " + (
        "throw 'SIMULATED_INSTALL_FAILURE'" if failure else "return 'project-python.exe'"
    ) + " }\nfunction Initialize-LauncherCloudflared { return 'project-cloudflared.exe' }\n"
    (project / 'scripts/windows_bootstrap.ps1').write_text(bootstrap, encoding='utf-8-sig')
    (project / 'scripts/start_p2p.ps1').write_text('''
param($PythonPath, $CloudflaredPath, [switch]$LanOnly, [switch]$Check, [switch]$OpenBrowser, $TunnelProtocol)
[pscustomobject]@{Python=$PythonPath;Cloudflared=$CloudflaredPath;LAN=[bool]$LanOnly;Check=[bool]$Check;Browser=[bool]$OpenBrowser;Protocol=$TunnelProtocol} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot '../started.json') -Encoding UTF8
''', encoding='utf-8-sig')
    return project


@pytest.mark.skipif(os.name != 'nt', reason='Windows entry point')
@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('mode,check', [('Local', False), ('Remote', False), ('Local', True), ('Remote', True)])
def test_launcher_selects_mode_and_check_never_opens_browser(shell, tmp_path, mode, check):
    project = fake_project(tmp_path)
    result = run(shell, f"& {quote(project / 'scripts/launch_windows.ps1')} -Mode {mode} " + ('-Check' if check else ''))
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads((project / 'started.json').read_text(encoding='utf-8-sig'))
    assert actual == {
        'Python': 'project-python.exe',
        'Cloudflared': 'project-cloudflared.exe' if mode == 'Remote' else None,
        'LAN': mode == 'Local', 'Check': check, 'Browser': not check,
        'Protocol': 'http2' if mode == 'Remote' else None,
    }


@pytest.mark.skipif(os.name != 'nt', reason='Windows entry point')
@pytest.mark.parametrize('shell', SHELLS)
def test_preparation_failure_retains_log_without_starting_game(shell, tmp_path):
    project = fake_project(tmp_path, failure=True)
    result = run(shell, f"& {quote(project / 'scripts/launch_windows.ps1')} -Mode Local")
    assert result.returncode == 1
    assert b'SIMULATED_INSTALL_FAILURE' in result.stdout
    assert not (project / 'started.json').exists()
    assert list((project / 'logs/launcher').glob('*.log'))
    # The error path must release the file lock for the next retry.
    retry = run(shell, f". {quote(ROOT / 'scripts/windows_bootstrap.ps1')}; $lock=Enter-LauncherLock -RuntimeDirectory {quote(project / '.runtime')}; $lock.Dispose()")
    assert retry.returncode == 0, retry.stderr


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch entry point')
@pytest.mark.parametrize('name,mode', [('本地.bat', 'Local'), ('远程.bat', 'Remote')])
def test_batch_handles_extracted_paths_and_preserves_failure_exit(tmp_path, name, mode):
    project = tmp_path / '解压 & !'
    (project / 'scripts').mkdir(parents=True)
    shutil.copyfile(ROOT / name, project / name)
    (project / 'scripts/launch_windows.ps1').write_text(
        "param($Mode)\n[IO.File]::WriteAllText((Join-Path $PSScriptRoot '../mode.txt'), $Mode)\nexit 23\n",
        encoding='utf-8-sig',
    )
    # Match Explorer's quoted /c invocation (Python list2cmdline alone does not
    # add cmd.exe's outer quote pair for a command containing shell metacharacters).
    result = subprocess.run(f'cmd.exe /d /s /c ""{project / name}""', input=b'\r\n', capture_output=True, timeout=20)
    assert result.returncode == 23, result.stdout + result.stderr
    assert (project / 'mode.txt').read_text() == mode


@pytest.mark.parametrize('shell', SHELLS)
def test_browser_failure_does_not_terminate_game(shell):
    result = run(shell, f"""
. {quote(ROOT / 'scripts/p2p_common.ps1')}
function Start-Process {{ throw 'No default browser' }}
Open-P2PBrowser -Url http://127.0.0.1:5051
Write-Output 'STILL_RUNNING'
""")
    assert result.returncode == 0, result.stderr
    assert b'STILL_RUNNING' in result.stdout
