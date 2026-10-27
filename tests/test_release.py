import hashlib
import importlib.util
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'tools' / 'build_release.py')
build_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_release)


@pytest.fixture
def release(tmp_path, monkeypatch):
    uv = tmp_path / 'uv.exe'
    uv.write_bytes(b'MZ fake uv')
    monkeypatch.setattr(build_release, 'uv_version', lambda path: 'uv 9.9.9')
    out = build_release.build(uv, tmp_path / 'dist', allow_dirty=True)
    with zipfile.ZipFile(out) as z:
        yield out, {n: z.read(n) for n in z.namelist() if not n.endswith('/')}


def test_release_holds_the_app_and_uv(release):
    out, files = release
    assert out.name == f'Clip-Scout-{build_release.version()}-windows.zip'
    names = set(files)
    assert all(n.startswith('Clip Scout/') for n in names)
    for needed in ('Clip Scout.bat', 'pyproject.toml', 'uv.lock', 'AGENTS.md', 'clipscout/cli.py',
                   'clipscout/prompts/pick.md', 'web/index.html', 'elgato/channel-guide.md'):
        assert f'Clip Scout/{needed}' in names
    assert files['Clip Scout/uv/uv.exe'] == b'MZ fake uv'
    assert 'bundled uv 9.9.9' in files['Clip Scout/VERSION.txt'].decode()
    packaged = tomllib.loads(files['Clip Scout/pyproject.toml'].decode())['project']['version']
    assert out.name == f'Clip-Scout-{packaged}-windows.zip'


def test_refuses_a_uv_that_is_not_for_windows(tmp_path):
    uv = tmp_path / 'uv'
    uv.write_bytes(b'\x7fELF linux uv')
    with pytest.raises(SystemExit, match='not a Windows executable'):
        build_release.build(uv, tmp_path / 'dist', allow_dirty=True)
    assert not (tmp_path / 'dist').exists()


def test_release_leaves_out_dev_and_private_files(release):
    _, files = release
    for n in files:
        rel = n.removeprefix('Clip Scout/')
        assert not rel.startswith(('tests/', 'tools/', 'library/', 'secrets/', '.venv/', 'dist/')), n
        assert rel != '.gitattributes'


def test_launcher_has_windows_line_endings(release):
    _, files = release
    bat = files['Clip Scout/Clip Scout.bat']
    assert b'\r\n' in bat and b'\n' not in bat.replace(b'\r\n', b'')


def test_checksum_matches(release):
    out, _ = release
    digest, name = out.with_name(out.name + '.sha256').read_text(encoding='utf-8').split()
    assert name == out.name and digest == hashlib.sha256(out.read_bytes()).hexdigest()
