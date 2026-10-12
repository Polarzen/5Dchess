"""Windows launcher discovery and parsing, without downloads or public tunnels."""
from __future__ import annotations

import base64
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHELLS = [path for name in ('powershell', 'pwsh') if (path := shutil.which(name))]
pytestmark = pytest.mark.skipif(not SHELLS, reason='PowerShell unavailable')


def quoted(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def run(shell: str, body: str) -> subprocess.CompletedProcess:
    prefix = "$ErrorActionPreference='Stop'; . " + quoted(ROOT / 'scripts/p2p_common.ps1') + '; '
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
