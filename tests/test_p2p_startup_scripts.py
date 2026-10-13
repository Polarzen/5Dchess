"""Windows launcher discovery and parsing, without downloads or public tunnels."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHELLS = [path for name in ('powershell', 'pwsh') if (path := shutil.which(name))]
pytestmark = pytest.mark.skipif(not SHELLS, reason='PowerShell unavailable')


def quoted(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def run(shell: str, body: str) -> subprocess.CompletedProcess:
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding = [Text.UTF8Encoding]::new(); . " + quoted(ROOT / 'scripts/p2p_common.ps1') + '; '
    encoded = base64.b64encode((prefix + body).encode('utf-16-le')).decode()
    return subprocess.run([shell, '-NoProfile', '-EncodedCommand', encoded], capture_output=True, timeout=20)


@pytest.mark.parametrize('shell', SHELLS)
def test_python_discovery_prefers_project_311_and_explicit_path(shell, tmp_path):
    # Spaces and non-ASCII paths must work without activation or global PATH changes.
    project = tmp_path / '项目 with spaces'
    expected = project / '.venv311/Scripts/python.exe'
    alternate = project / '.venv/Scripts/python.exe'
    for path in (expected, alternate):
        path.parent.mkdir(parents=True)
        path.touch()
    result = run(shell, f"""
$actual = Resolve-P2PPython -ProjectRoot {quoted(project)}
if ($actual -ne {quoted(expected)}) {{ throw 'Wrong project interpreter' }}
$explicit = Resolve-P2PPython -ProjectRoot {quoted(project)} -PythonPath {quoted(alternate)}
if ($explicit -ne {quoted(alternate)}) {{ throw 'Explicit interpreter ignored' }}
""")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('shell', SHELLS)
def test_cloudflared_discovery_is_project_relative_and_honors_explicit_path(shell, tmp_path):
    project = tmp_path / '项目 [portable] with spaces'
    runtime = project / '.runtime/cloudflared/cloudflared.exe'
    legacy = project / 'cloudflared.exe'
    explicit = tmp_path / 'custom/cloudflared.exe'
    for path in (runtime, legacy, explicit):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    result = run(shell, f"""
Set-Location -LiteralPath {quoted(tmp_path)}
if ((Resolve-P2PCloudflared -ProjectRoot {quoted(project)}) -ne {quoted(runtime)}) {{ throw 'Project runtime not preferred' }}
if ((Resolve-P2PCloudflared -ProjectRoot {quoted(project)} -CloudflaredPath {quoted(explicit)}) -ne {quoted(explicit)}) {{ throw 'Explicit path ignored' }}
Remove-Item -LiteralPath {quoted(runtime)}
if ((Resolve-P2PCloudflared -ProjectRoot {quoted(project)}) -ne {quoted(legacy)}) {{ throw 'Legacy project fallback broken' }}
""")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('shell', SHELLS)
def test_software_directory_uses_project_root_from_another_working_directory(shell, tmp_path):
    project = tmp_path / '项目 [portable] with spaces'
    project.mkdir()
    custom = tmp_path / 'external tools'
    result = run(shell, f"""
Set-Location -LiteralPath {quoted(tmp_path)}
if ((Resolve-P2PSoftwareDirectory -ProjectRoot {quoted(project)}) -ne {quoted(project / '.runtime')}) {{ throw 'Default directory not portable' }}
if ((Resolve-P2PSoftwareDirectory -ProjectRoot {quoted(project)} -SoftwareDirectory 'tools') -ne {quoted(project / 'tools')}) {{ throw 'Relative directory not rooted at project' }}
if ((Resolve-P2PSoftwareDirectory -ProjectRoot {quoted(project)} -SoftwareDirectory {quoted(custom)}) -ne {quoted(custom)}) {{ throw 'Explicit absolute directory changed' }}
""")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('shell', SHELLS)
def test_startup_check_from_project_path_with_brackets(shell, tmp_path):
    project = tmp_path / '项目 [portable] with spaces'
    scripts = project / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('start_p2p.ps1', 'p2p_common.ps1'):
        shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
    result = run(shell, f"& {quoted(scripts / 'start_p2p.ps1')} -LanOnly -Check -PythonPath {quoted(Path(sys.executable))}")
    assert result.returncode == 0, result.stderr
    assert b'P2P environment OK' in result.stdout


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('resolver,parameter', [('Resolve-P2PPython', 'PythonPath'), ('Resolve-P2PCloudflared', 'CloudflaredPath')])
def test_explicit_missing_program_rejects_instead_of_falling_back(shell, resolver, parameter, tmp_path):
    result = run(shell, f"{resolver} -ProjectRoot {quoted(ROOT)} -{parameter} {quoted(tmp_path / 'missing.exe')}")
    assert result.returncode != 0


@pytest.mark.parametrize('shell', SHELLS)
def test_all_p2p_powershell_scripts_parse(shell):
    body = '\n'.join(
        f"[scriptblock]::Create((Get-Content -LiteralPath {quoted(ROOT / 'scripts' / name)} -Raw)) | Out-Null"
        for name in ('start_p2p.ps1', 'setup_p2p.ps1', 'p2p_common.ps1')
    )
    result = run(shell, body)
    assert result.returncode == 0, result.stderr


PROVISIONING_TIMEOUT = (
    'failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": '
    'context deadline exceeded (Client.Timeout exceeded while awaiting headers)'
)
RESPONSE_BODY_TIMEOUT = (
    'failed to read quick-tunnel response: context deadline exceeded '
    '(Client.Timeout or context cancellation while reading body)'
)
PUBLIC_URL = 'https://test-connection.trycloudflare.com'
CONNECTED = PUBLIC_URL + '\nINF Registered tunnel connection'


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('log,retryable', [
    (PROVISIONING_TIMEOUT, True),
    (RESPONSE_BODY_TIMEOUT, True),
    ('failed to read quick-tunnel response: unexpected EOF', True),
    ('failed to request quick Tunnel: connection reset by peer', True),
    ('quick tunnel provisioning failed with status 503', True),
    ('quick tunnel provisioning failed with status 429', True),
    ('quick tunnel provisioning failed with status 403', False),
    ('failed to request quick Tunnel: x509: certificate signed by unknown authority', False),
    ('ERR Failed to dial a quic connection: timeout: no recent network activity', False),
    ('Incorrect Usage: flag provided but not defined', False),
    ('', False),
])
def test_tunnel_failure_classifies_only_transient_provisioning_errors(shell, log, retryable):
    literal = "'" + log.replace("'", "''") + "'"
    result = run(shell, f'Get-P2PTunnelFailure -Output {literal} | ConvertTo-Json -Compress')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['Retryable'] is retryable


def tunnel_scenario(shell, tmp_path, plan, *, limit=3, action='', server_exited=False, open_browser=False):
    """Exercise the real supervisor with fake processes and clock, no network.

    Logs are real files; retain the last process reference for caller cleanup.
    """
    plan_json = json.dumps(plan).replace("'", "''")
    result = run(shell, f"""
$script:plan = ConvertFrom-Json -InputObject '{plan_json}'
$script:created = [Collections.Generic.List[object]]::new()
$script:clock = [datetime]'2026-10-12T00:00:00Z'
$script:sleeps = [Collections.Generic.List[int]]::new()
$script:browserUrls = [Collections.Generic.List[string]]::new()
function Open-P2PBrowser {{ param($Url) $script:browserUrls.Add($Url) }}
$script:server = [pscustomobject]@{{ HasExited = ${str(server_exited).lower()} }}
function Get-Date {{ return $script:clock }}
function Start-Sleep {{
    param([int]$Milliseconds)
    $script:sleeps.Add($Milliseconds)
    $script:clock = $script:clock.AddMilliseconds($Milliseconds)
    {action}
}}
function Start-Process {{
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
          $RedirectStandardOutput, $RedirectStandardError, [switch]$PassThru)
    if ($script:created.Count -ge $script:plan.Count) {{ throw 'Unexpected extra process' }}
    $item = $script:plan[$script:created.Count]
    [IO.File]::WriteAllText($RedirectStandardError, [string]$item.log, [Text.UTF8Encoding]::new())
    [IO.File]::WriteAllText($RedirectStandardOutput, [string]$item.stdout, [Text.UTF8Encoding]::new())
    $process = [pscustomobject]@{{
        HasExited = [bool]$item.exited; ExitCode = 1; Disposed = $false
        Log = $RedirectStandardError; Arguments = $ArgumentList
        WindowStyle = $WindowStyle; Waited = $false
    }}
    $process | Add-Member ScriptMethod WaitForExit {{ $this.Waited = $true }}
    $process | Add-Member ScriptMethod Dispose {{ $this.Disposed = $true }}
    $script:created.Add($process)
    return $process
}}
$tunnel = $null
$errorMessage = $null
try {{
    & {{ Connect-P2PQuickTunnel -Executable 'fake-cloudflared' -ProjectRoot {quoted(ROOT)} `
        -Port 61234 -Protocol http2 -LogStem {quoted(tmp_path / 'startup')} `
        -Server $script:server -Tunnel ([ref]$tunnel) -MaxAttempts {limit} -OpenBrowser:${str(open_browser).lower()} }} 6>$null
}} catch {{ $errorMessage = $_.Exception.Message }}
[pscustomobject]@{{
    Error = $errorMessage; Created = @($script:created.ToArray()); Sleeps = @($script:sleeps.ToArray())
    RetainedLog = $(if ($tunnel) {{ $tunnel.Log }} else {{ $null }})
    BrowserUrls = @($script:browserUrls.ToArray())
    ServerExited = $script:server.HasExited
}} | ConvertTo-Json -Depth 6 -Compress
""")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('shell', SHELLS)
def test_two_timeouts_retry_then_connect_without_restarting_origin(shell, tmp_path):
    result = tunnel_scenario(shell, tmp_path, [
        {'exited': True, 'log': PROVISIONING_TIMEOUT},
        {'exited': True, 'log': RESPONSE_BODY_TIMEOUT},
        {'exited': False, 'log': CONNECTED},
    ])
    assert result['Error'] is None
    assert not result['ServerExited']
    assert sum(result['Sleeps']) == 6000  # 2s, then 4s backoff
    processes = result['Created']
    assert len(processes) == 3
    assert [p['Disposed'] for p in processes] == [True, True, False]
    assert result['RetainedLog'] == processes[-1]['Log']
    assert len({p['Log'] for p in processes}) == 3
    for process in processes:
        assert process['WindowStyle'] == 'Hidden'
        assert process['Arguments'] == [
            'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', 'http://127.0.0.1:61234',
        ]
        assert Path(process['Log']).exists()


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('limit', [1, 3])
def test_provisioning_failure_stops_at_attempt_limit_and_keeps_cause(shell, tmp_path, limit):
    result = tunnel_scenario(shell, tmp_path, [{'exited': True, 'log': RESPONSE_BODY_TIMEOUT}] * limit, limit=limit)
    assert len(result['Created']) == limit
    assert f'{limit}/{limit}' in result['Error']
    assert 'api.trycloudflare.com' in result['Error']
    assert result['Created'][-1]['Log'] in result['Error']
    assert result['RetainedLog'] == result['Created'][-1]['Log']


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('log', [
    'Incorrect Usage: flag provided but not defined',
    PUBLIC_URL + '\n' + PROVISIONING_TIMEOUT,
    'INF Registered tunnel connection\n' + PROVISIONING_TIMEOUT,
])
def test_permanent_failure_or_provisioned_tunnel_does_not_rotate_url(shell, tmp_path, log):
    result = tunnel_scenario(shell, tmp_path, [{'exited': True, 'log': log}])
    assert result['Error']
    assert len(result['Created']) == 1
    assert result['Sleeps'] == []


@pytest.mark.parametrize('shell', SHELLS)
def test_url_is_not_ready_until_connection_registered(shell, tmp_path):
    result = tunnel_scenario(shell, tmp_path, [{'exited': False, 'log': PUBLIC_URL}], action="""
Add-Content -LiteralPath $script:created[0].Log -Value "`nINF Registered tunnel connection"
""")
    assert result['Error'] is None
    assert result['Sleeps'] == [500]


@pytest.mark.parametrize('shell', SHELLS)
def test_tunnel_accepts_registration_split_between_stdout_and_stderr(shell, tmp_path):
    result = tunnel_scenario(shell, tmp_path, [{'exited': False, 'log': PUBLIC_URL, 'stdout': 'INF Registered tunnel connection'}])
    assert result['Error'] is None


@pytest.mark.parametrize('shell', SHELLS)
def test_failed_automatic_tunnel_preserves_server_and_offers_manual_port(shell):
    result = run(shell, """
$script:stopped = @(); $script:manualPort = 0; $script:opened = ''
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) $script:stopped += $Id }
function Show-P2PManualConnection { param($Port, $Executable) $script:manualPort = $Port }
function Open-P2PBrowser { param($Url) $script:opened = $Url }
function Connect-P2PQuickTunnel { throw 'SIMULATED_TIMEOUT' }
$server = [pscustomobject]@{HasExited=$false; Id=11}
$tunnel = [pscustomobject]@{HasExited=$false; Id=22; Disposed=$false}
$tunnel | Add-Member ScriptMethod Dispose { $this.Disposed=$true }
$original = $tunnel
Start-P2PRemoteConnection -Executable fake -ProjectRoot . -Port 5053 -Protocol auto -Server $server -Tunnel ([ref]$tunnel) -OpenBrowser 6>$null
[pscustomobject]@{Stopped=$script:stopped;ManualPort=$script:manualPort;Opened=$script:opened;Cleared=($null -eq $tunnel);Disposed=$original.Disposed;ServerExited=$server.HasExited} | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'Stopped': [22], 'ManualPort': 5053, 'Opened': 'http://127.0.0.1:5053', 'Cleared': True, 'Disposed': True, 'ServerExited': False}


@pytest.mark.parametrize('shell', SHELLS)
def test_manual_tunnel_check_does_not_require_cloudflared(shell, tmp_path):
    result = run(shell, f"& {quoted(ROOT / 'scripts/start_p2p.ps1')} -ManualTunnel -Check -PythonPath {quoted(Path(sys.executable))}")
    assert result.returncode == 0, result.stderr
    assert b'P2P environment OK' in result.stdout
    invalid = run(shell, f"& {quoted(ROOT / 'scripts/start_p2p.ps1')} -ManualTunnel -Check -CloudflaredPath {quoted(tmp_path / 'missing.exe')} -PythonPath {quoted(Path(sys.executable))}")
    assert invalid.returncode != 0


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('log', ['', PUBLIC_URL])
def test_hung_startup_is_bounded_and_retains_process_for_cleanup(shell, tmp_path, log):
    result = tunnel_scenario(shell, tmp_path, [{'exited': False, 'log': log}])
    assert '90' in result['Error']
    assert ('-TunnelProtocol http2' in result['Error']) == bool(log)
    assert len(result['Created']) == 1
    assert result['RetainedLog'] == result['Created'][0]['Log']


@pytest.mark.parametrize('shell', SHELLS)
@pytest.mark.parametrize('log,expected', [(PUBLIC_URL, []), (CONNECTED, [PUBLIC_URL])])
def test_browser_opens_only_after_tunnel_is_usable(shell, tmp_path, log, expected):
    result = tunnel_scenario(shell, tmp_path, [{'exited': False, 'log': log}], open_browser=True)
    assert result['BrowserUrls'] == expected


@pytest.mark.parametrize('shell', SHELLS)
def test_origin_exit_during_backoff_prevents_another_tunnel(shell, tmp_path):
    result = tunnel_scenario(shell, tmp_path, [{'exited': True, 'log': PROVISIONING_TIMEOUT}],
                             action='$script:server.HasExited = $true')
    assert 'Flask' in result['Error']
    assert len(result['Created']) == 1
    assert result['RetainedLog'] is None
    assert result['Created'][0]['Disposed']


@pytest.mark.parametrize('shell', SHELLS)
def test_origin_exit_while_connecting_retains_tunnel_for_cleanup(shell, tmp_path):
    result = tunnel_scenario(shell, tmp_path, [{'exited': False, 'log': PUBLIC_URL}],
                             action='$script:server.HasExited = $true')
    assert 'Flask' in result['Error']
    assert len(result['Created']) == 1
    assert result['RetainedLog'] == result['Created'][0]['Log']


@pytest.mark.parametrize('shell', SHELLS)
def test_real_child_reports_body_timeout_and_preserves_exit_code(shell, tmp_path):
    child_script = tmp_path / 'fake provisioning response.py'
    child_script.write_text(
        'import sys, time\ntime.sleep(0.3)\n'
        f'print({RESPONSE_BODY_TIMEOUT!r}, file=sys.stderr, flush=True)\n'
        'sys.exit(23)\n', encoding='utf-8',
    )
    result = run(shell, f"""
function Start-Process {{
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle,
          $RedirectStandardOutput, $RedirectStandardError, [switch]$PassThru)
    $PSBoundParameters['ArgumentList'] = @('-u', ('"' + {quoted(child_script)} + '"'))
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {{
        $PSBoundParameters.Remove('WindowStyle') | Out-Null
    }}
    Microsoft.PowerShell.Management\\Start-Process @PSBoundParameters
}}
$tunnel = $null
$message = $null
try {{
    & {{ Connect-P2PQuickTunnel -Executable {quoted(Path(sys.executable))} -ProjectRoot {quoted(ROOT)} `
        -Port 61234 -Protocol auto -LogStem {quoted(tmp_path / 'real-child')} `
        -Server ([pscustomobject]@{{HasExited=$false}}) -Tunnel ([ref]$tunnel) -MaxAttempts 1 }} 6>$null
}} catch {{ $message = $_.Exception.Message }} finally {{
    if ($tunnel -and -not $tunnel.HasExited) {{ Stop-Process -InputObject $tunnel -Force }}
}}
[pscustomobject]@{{ Error=$message; ExitCode=$tunnel.ExitCode }} | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert 'api.trycloudflare.com' in payload['Error']
    assert '23' in payload['Error']
    assert payload['ExitCode'] == 23
