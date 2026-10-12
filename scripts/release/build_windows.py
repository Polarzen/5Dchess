"""Build a versioned, auditable source ZIP from an immutable Git commit."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PREFIX = '5DChess/'
ASSET_NAME = '5DChess-Windows.zip'
REQUIRED = {
    'README.md', 'LICENSE', '使用说明.txt', '本地.bat', '远程.bat',
    'requirements.txt', 'src/web/__init__.py', 'scripts/launch_windows.ps1',
    'scripts/windows_bootstrap.ps1', 'scripts/start_p2p.ps1',
    'scripts/p2p_common.ps1', 'scripts/run_p2p_server.py',
    'scripts/p2p/python-runtime.json', 'scripts/p2p/cloudflared-release.json',
}
PRIVATE_DIRS = {'.git', '.runtime', '.venv', '.venv311', '.venv-training',
                '.planner-work', '.pytest_cache', '__pycache__', '.claude',
                '.vscode', '.idea', 'logs', 'dist', 'runs', 'checkpoints',
                'datasets', 'training_data', 'saves'}


def validate_archive(archive: zipfile.ZipFile) -> None:
    names = set(archive.namelist())
    missing = {PREFIX + name for name in REQUIRED} - names
    if missing:
        raise ValueError('Release is missing required files: ' + ', '.join(sorted(missing)))
    for name in names:
        if not name.startswith(PREFIX):
            raise ValueError(f'Unexpected archive root: {name}')
        parts = PurePosixPath(name[len(PREFIX):]).parts
        if '..' in parts or set(parts) & PRIVATE_DIRS or any(part == '.env' or part.startswith('.env.') for part in parts):
            raise ValueError(f'Local or private file must not be released: {name}')
    for name in ('本地.bat', '远程.bat'):
        data = archive.read(PREFIX + name)
        if b'\r\n' not in data or b'\n' in data.replace(b'\r\n', b'') or data.startswith(b'\xef\xbb\xbf'):
            raise ValueError(f'Batch file must preserve CRLF without BOM: {name}')
    for name in ('launch_windows.ps1', 'windows_bootstrap.ps1', 'start_p2p.ps1', 'p2p_common.ps1'):
        if not archive.read(PREFIX + 'scripts/' + name).startswith(b'\xef\xbb\xbf'):
            raise ValueError(f'PowerShell 5.1 requires UTF-8 BOM for Chinese messages: {name}')
    if archive.testzip():
        raise ValueError('ZIP CRC validation failed')


def build_package(root: Path, *, ref: str, version: str, output: Path) -> dict:
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('Version must look like v0.1.0 or v0.1.0-rc.1')
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}'], cwd=root,
        text=True,
    ).strip()
    payload = subprocess.check_output(
        ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive',
         '--format=zip', '--prefix=' + PREFIX, commit], cwd=root,
    )
    buffer = io.BytesIO(payload)
    with zipfile.ZipFile(buffer, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        validate_archive(archive)
        if PREFIX + 'VERSION.txt' in archive.namelist():
            raise ValueError('VERSION.txt is reserved for generated release provenance')
        info = zipfile.ZipInfo(PREFIX + 'VERSION.txt', date_time=archive.infolist()[0].date_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, f'{version}\nCommit: {commit}\n')
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    zip_path = output / ASSET_NAME
    checksum_path = output / 'SHA256SUMS.txt'
    if zip_path.exists() or checksum_path.exists():
        raise FileExistsError('Release output already exists; choose a new directory to avoid replacing an asset')
    with zip_path.open('xb') as stream:
        stream.write(content)
    with checksum_path.open('x', encoding='ascii', newline='\n') as stream:
        stream.write(f'{digest}  {ASSET_NAME}\n')
    return {'version': version, 'commit': commit, 'zip': str(zip_path.resolve()),
            'checksum': str(checksum_path.resolve()), 'sha256': digest,
            'bytes': len(content)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Commit or tag to package, not working-tree files')
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, help='Default: dist/<version>')
    args = parser.parse_args()
    try:
        result = build_package(ROOT, ref=args.ref, version=args.version,
                               output=args.output or ROOT / 'dist' / args.version)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Build failed: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
