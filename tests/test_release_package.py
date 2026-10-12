"""Release archives must use committed files and remain reproducible."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_windows', ROOT / 'scripts/release/build_windows.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
pytestmark = pytest.mark.skipif(not shutil.which('git'), reason='Git unavailable')


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    for relative in builder.REQUIRED:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    (root / '.gitattributes').write_text('*.bat -text whitespace=cr-at-eol\n')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '.'], cwd=root, check=True, capture_output=True)
    subprocess.run(['git', '-c', 'user.name=Release Test', '-c', 'user.email=release@example.invalid',
                    'commit', '-qm', 'fixture'], cwd=root, check=True)
    return root


def test_release_uses_commit_excludes_local_files_and_is_reproducible(repository, tmp_path):
    committed_readme = subprocess.check_output(['git', 'show', 'HEAD:README.md'], cwd=repository)
    (repository / 'README.md').write_text('Uncommitted local changes')
    (repository / 'logs').mkdir()
    (repository / 'logs/private.log').write_text('Local only')
    first = builder.build_package(repository, ref='HEAD', version='v0.1.0', output=tmp_path / 'first')
    second = builder.build_package(repository, ref='HEAD', version='v0.1.0', output=tmp_path / 'second')
    assert first['sha256'] == second['sha256']
    assert hashlib.sha256(Path(first['zip']).read_bytes()).hexdigest() == first['sha256']
    assert Path(first['checksum']).read_text() == f"{first['sha256']}  5DChess-Windows.zip\n"
    with zipfile.ZipFile(first['zip']) as archive:
        assert archive.read('5DChess/README.md') == committed_readme
        assert '5DChess/logs/private.log' not in archive.namelist()
        assert first['commit'] in archive.read('5DChess/VERSION.txt').decode()
        builder.validate_archive(archive)
    with pytest.raises(FileExistsError):
        builder.build_package(repository, ref='HEAD', version='v0.1.0', output=tmp_path / 'first')


def test_release_rejects_tracked_private_data(repository, tmp_path):
    (repository / '.env').write_text('fixture only')
    subprocess.run(['git', 'add', '.env'], cwd=repository, check=True)
    subprocess.run(['git', '-c', 'user.name=Release Test', '-c', 'user.email=release@example.invalid',
                    'commit', '-qm', 'invalid fixture'], cwd=repository, check=True)
    with pytest.raises(ValueError, match='private file'):
        builder.build_package(repository, ref='HEAD', version='v0.1.0', output=tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()
