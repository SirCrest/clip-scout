"""Build the standalone Windows release: dist/Clip-Scout-<version>-windows.zip (and a .sha256 beside it).

The zip holds one folder, `Clip Scout/`: the app as committed at HEAD (tests and tools are left out, see
.gitattributes) plus uv.exe, so nobody has to clone the repo or install anything first. Double-clicking
Clip Scout.bat in that folder sets up Python and the packages on the first run (a one-time download of a few GB),
then opens the app. The library is created inside the folder, so updating is copying a newer release over it;
READ ME FIRST.txt in the zip says so.

Usage: uv run python tools/build_release.py [--uv PATH] [--allow-dirty] [--force]
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
FOLDER = 'Clip Scout'
NOTES = """Clip Scout {version}

Start: double-click Clip Scout.bat. The first start downloads Python and the packages Clip Scout needs (a few GB);
after that it opens in seconds.

Where to put this folder: a drive with plenty of free space (each stream takes 5-15 GB), and not a folder that
OneDrive or Dropbox syncs.

Your streams, clips and YouTube sign-in are kept inside this folder, in library and secrets. Deleting this folder
deletes them.

To update: close Clip Scout, open the new zip, copy its Clip Scout folder into the folder that holds this one, and
choose to replace the files. The zip has no library or secrets folder, so yours are kept. Don't extract a new
version to a separate folder: it would start with an empty library.
"""


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def version():
    """The version committed at HEAD, which is what the zip contains (not the working copy's)."""
    return tomllib.loads(git('show', 'HEAD:pyproject.toml'))['project']['version']


def check_windows_exe(uv):
    with open(uv, 'rb') as f:
        if f.read(2) != b'MZ':
            raise SystemExit(f'{uv} is not a Windows executable: pass --uv with a Windows uv.exe')


def uv_version(uv):
    """`uv --version` of a lone copy of the uv being bundled. That proves it's a working Windows uv that doesn't need
    files beside it, as package-manager shims do."""
    if sys.platform != 'win32':
        return 'uv (version not checked: built off Windows)'
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / 'uv.exe'
        shutil.copyfile(uv, copy)
        return subprocess.run([str(copy), '--version'], capture_output=True, text=True, check=True).stdout.strip()


def locked_version():
    lock = tomllib.loads(git('show', 'HEAD:uv.lock'))
    return next((p.get('version') for p in lock['package'] if p['name'] == 'clip-scout'), None)


def build(uv, out_dir=DIST, allow_dirty=False, force=False):
    if not allow_dirty and git('status', '--porcelain'):
        raise SystemExit('commit your changes first: the release is built from HEAD (or pass --allow-dirty)')
    if locked_version() != version():
        raise SystemExit(f'uv.lock has clip-scout {locked_version()} but pyproject.toml has {version()}: '
                         f'run `uv lock` and commit it')
    out = out_dir / f'Clip-Scout-{version()}-windows.zip'
    if out.exists() and not force:
        raise SystemExit(f'{out.name} already exists: bump the version in pyproject.toml (or pass --force)')
    uv = Path(uv)
    check_windows_exe(uv)
    bundled = uv_version(uv)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    # git archive applies .gitattributes: export-ignore drops tests and tools, eol=crlf keeps the .bat runnable
    subprocess.run(['git', 'archive', '--format=zip', f'--prefix={FOLDER}/', '-o', str(out), 'HEAD'],
                   cwd=ROOT, check=True)
    with zipfile.ZipFile(out, 'a', zipfile.ZIP_DEFLATED) as z:
        z.write(uv, f'{FOLDER}/uv/uv.exe')
        z.writestr(f'{FOLDER}/VERSION.txt',
                   f'Clip Scout {version()} ({git("rev-parse", "--short", "HEAD")})\nbundled {bundled}\n')
        z.writestr(f'{FOLDER}/READ ME FIRST.txt', NOTES.format(version=version()).replace('\n', '\r\n'))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + '.sha256').write_text(f'{digest}  {out.name}\n', encoding='utf-8')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--uv', help='the uv.exe to bundle (default: the uv running this, else the one on PATH)')
    p.add_argument('--allow-dirty', action='store_true', help='build even with uncommitted changes (HEAD is used)')
    p.add_argument('--force', action='store_true', help='replace a zip of the same version')
    args = p.parse_args()
    uv = args.uv or os.environ.get('UV') or shutil.which('uv')  # `uv run` sets UV to the real binary, not a shim
    if not uv:
        raise SystemExit('uv not found: pass --uv PATH')
    out = build(uv, allow_dirty=args.allow_dirty, force=args.force)
    print(f'{out} ({out.stat().st_size / 2**20:.0f} MB)')


if __name__ == '__main__':
    main()
