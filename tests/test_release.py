import hashlib
import importlib.util
import os
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'tools' / 'build_release.py')
build_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_release)


def fake_exe(machine=0x8664):
    """The start of a Windows executable: MZ header pointing at a PE header for `machine`."""
    return b'MZ' + bytes(0x3A) + (0x40).to_bytes(4, 'little') + b'PE\0\0' + machine.to_bytes(2, 'little') + b' fake uv'


@pytest.fixture
def release(tmp_path, monkeypatch):
    uv = tmp_path / 'uv.exe'
    uv.write_bytes(fake_exe())
    monkeypatch.setattr(build_release, 'uv_version', lambda path: 'uv 9.9.9')
    out = build_release.build(uv, tmp_path / 'dist', allow_dirty=True)
    with zipfile.ZipFile(out) as z:
        files = {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
    return out, files


def test_release_holds_the_app_and_uv(release):
    out, files = release
    assert out.name == f'Clip-Scout-{build_release.version()}-windows.zip'
    names = set(files)
    assert all(n.startswith('Clip Scout/') for n in names)
    for needed in ('Clip Scout.bat', 'pyproject.toml', 'uv.lock', 'AGENTS.md', '.ignore', 'clipscout/cli.py',
                   'clipscout/prompts/pick.md', 'web/index.html', 'elgato/channel-guide.md'):
        assert f'Clip Scout/{needed}' in names
    assert files['Clip Scout/uv/uv.exe'] == fake_exe()
    assert 'bundled uv 9.9.9' in files['Clip Scout/VERSION.txt'].decode()
    packaged = tomllib.loads(files['Clip Scout/pyproject.toml'].decode())['project']['version']
    assert out.name == f'Clip-Scout-{packaged}-windows.zip'
    notes = files['Clip Scout/READ ME FIRST.txt'].decode()
    assert f'Clip Scout {packaged}' in notes and 'To update' in notes and '\r\n' in notes


def test_wont_replace_a_release_of_the_same_version(release):
    out, _ = release
    uv = out.parent.parent / 'uv.exe'
    with pytest.raises(SystemExit, match='already exists'):
        build_release.build(uv, out.parent, allow_dirty=True)
    assert build_release.build(uv, out.parent, allow_dirty=True, force=True) == out


def test_a_failed_build_leaves_no_zip(tmp_path, monkeypatch):
    uv = tmp_path / 'uv.exe'
    uv.write_bytes(fake_exe())
    monkeypatch.setattr(build_release, 'uv_version', lambda path: 'uv 9.9.9')

    def broken(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(build_release.zipfile, 'ZipFile', broken)
    with pytest.raises(OSError):
        build_release.build(uv, tmp_path / 'dist', allow_dirty=True)
    assert list((tmp_path / 'dist').iterdir()) == []


def test_refuses_a_stale_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(build_release, 'locked_version', lambda: '0.0.1')
    with pytest.raises(SystemExit, match='run `uv lock`'):
        build_release.build(tmp_path / 'uv.exe', tmp_path / 'dist', allow_dirty=True)


REAL_UV = os.environ.get('UV') or shutil.which('uv')  # what build_release.main() picks


@pytest.mark.skipif(sys.platform != 'win32' or not REAL_UV, reason='needs Windows and uv')
def test_bundles_the_real_uv(tmp_path):
    out = build_release.build(REAL_UV, tmp_path / 'dist', allow_dirty=True)
    with zipfile.ZipFile(out) as z:
        assert z.read('Clip Scout/VERSION.txt').decode().splitlines()[1].startswith('bundled uv ')


@pytest.mark.parametrize('content, error', [
    (b'\x7fELF linux uv', 'not a Windows executable'),
    (b'MZ too short', 'not a Windows executable'),
    (fake_exe(machine=0xAA64), 'not an x86-64 build'),
])
def test_refuses_a_uv_that_is_not_for_windows_x64(tmp_path, content, error):
    uv = tmp_path / 'uv'
    uv.write_bytes(content)
    with pytest.raises(SystemExit, match=error):
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


def test_checksum_matches_and_works_with_sha256sum(release):
    out, _ = release
    raw = out.with_name(out.name + '.sha256').read_bytes()
    assert raw.endswith(b'\n') and b'\r' not in raw
    digest, name = raw.decode().split()
    assert name == out.name and digest == hashlib.sha256(out.read_bytes()).hexdigest()
