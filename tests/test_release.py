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
    monkeypatch.setattr(build_release, 'check_lock', lambda uv, archive: None)
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
    assert b'Astral Software' in files['Clip Scout/uv/LICENSE-MIT.txt']
    assert 'bundled uv 9.9.9' in files['Clip Scout/VERSION.txt'].decode()
    packaged = tomllib.loads(files['Clip Scout/pyproject.toml'].decode())['project']['version']
    assert out.name == f'Clip-Scout-{packaged}-windows.zip'
    notes = files['Clip Scout/READ ME FIRST.txt'].decode()
    assert f'Clip Scout {packaged}' in notes and 'To update' in notes and '\r\n' in notes


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_names_its_own_uv_in_commands(release, tmp_path):
    """Commands the app shows (TASK.md, health hints) name the bundled uv in a release, where uv isn't on PATH."""
    _, files = release
    folder = tmp_path / 'extracted'
    for name in ('Clip Scout/clipscout/library.py', 'Clip Scout/uv/uv.exe'):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(files[name])
    released = load('released_library', folder / 'Clip Scout/clipscout/library.py').uv('run scout task list')
    assert '`uv/uv.exe run scout task list` in the Clip Scout folder' in released and '`uv\\uv.exe`' in released
    assert load('repo_library', ROOT / 'clipscout/library.py').uv('run scout task list') == '`uv run scout task list`'


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
    monkeypatch.setattr(build_release, 'check_lock', lambda uv, archive: None)

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


def archive_of(tmp_path, pyproject):
    """A zip laid out like the release's git archive, holding the given pyproject.toml and HEAD's uv.lock."""
    path = tmp_path / 'archive.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('Clip Scout/pyproject.toml', pyproject)
        z.writestr('Clip Scout/uv.lock', build_release.git('show', 'HEAD:uv.lock'))
    return path


@pytest.mark.skipif(sys.platform != 'win32' or not REAL_UV, reason='needs Windows and uv')
def test_checks_the_packaged_lock(tmp_path):
    """The lock is checked in the archive, so a working copy that differs from HEAD can't hide a stale lock."""
    pyproject = build_release.git('show', 'HEAD:pyproject.toml')
    build_release.check_lock(REAL_UV, archive_of(tmp_path, pyproject))
    stale = pyproject.replace('dependencies = [', 'dependencies = [\n    "numpy>=999",', 1)
    with pytest.raises(SystemExit, match='uv lock --check'):
        build_release.check_lock(REAL_UV, archive_of(tmp_path, stale))


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


def test_ignore_lists_what_gitignore_does():
    """.ignore stands in for .gitignore where there's no git repo, as in a release folder."""
    def patterns(name):
        lines = (ROOT / name).read_text().splitlines()
        return {line.strip() for line in lines if line.strip() and not line.startswith('#')}
    assert patterns('.gitignore') <= patterns('.ignore')


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
