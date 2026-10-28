"""Build the standalone Windows release: dist/Clip-Scout-<version>-windows.zip (and a .sha256 beside it).

The zip holds one folder, `Clip Scout/`: the app as committed at HEAD (tests and tools are left out, see
.gitattributes) plus uv.exe and its license, so nobody has to clone the repo or install anything first.
Double-clicking Clip Scout.bat in that folder sets up Python and the packages on the first run (a one-time download
of a few GB), then opens the app. The library is created inside the folder, so updating is copying a newer release
over it; READ ME FIRST.txt in the zip says so.

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

Install: if you downloaded the zip, first right-click it, choose Properties, tick Unblock (if it's there) and click
OK, so Windows doesn't warn every time you open Clip Scout. Then extract the whole zip (right-click it, Extract
All) to a drive with plenty of free space (each stream takes 5-15 GB), not a folder that OneDrive or Dropbox
syncs, and double-click Clip Scout.bat in the extracted Clip Scout folder. If Windows still warns that it can't
verify the publisher or that it protected your PC, choose Run (or More info, then Run anyway).

The first start downloads Python and the packages Clip Scout needs (a few GB); after that Clip Scout opens in
seconds. Besides this folder it keeps about 8 GB on drive C, in a download cache of about 6 GB in AppData and the
speech and audio models (about 2 GB, fetched when first used) in .cache\\huggingface in your user folder.

Your streams, clips and YouTube sign-in are kept inside this folder, in library and secrets. Deleting this folder
deletes them.

To update: close Clip Scout and unblock the new zip as above. In this folder, delete the clipscout, web and elgato
folders, and the clip-scout folder in .claude\\skills: they hold only Clip Scout's own files, and this clears out
any that the new version dropped (the rest of .claude keeps your agent's settings and skills). Then copy
everything inside the new zip's Clip Scout folder into this one, replacing the files that are already here. Your
library, secrets and .venv folders aren't in the zip, so they stay as they are. Deleting elgato also deletes
changes you made to its guides, so keep a copy of any you want first. Don't extract a new version to a separate
folder: it would start with an empty library.
"""
X64 = 0x8664  # PE machine type of an x86-64 Windows executable
UV_LICENSE = ROOT / 'tools' / 'uv-LICENSE-MIT.txt'  # uv is MIT OR Apache-2.0; copies of uv.exe carry the notice


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                          check=True).stdout.strip()


def version():
    """The version committed at HEAD, which is what the zip contains (not the working copy's)."""
    return tomllib.loads(git('show', 'HEAD:pyproject.toml'))['project']['version']


def check_windows_exe(uv):
    """The bundled uv must be an x86-64 Windows executable: an MZ header whose PE header names that machine."""
    with open(uv, 'rb') as f:
        head = f.read(4096)
    pe = int.from_bytes(head[0x3C:0x40], 'little') if len(head) >= 0x40 else 0
    if head[:2] != b'MZ' or head[pe:pe + 4] != b'PE\0\0':
        raise SystemExit(f'{uv} is not a Windows executable: pass --uv with a Windows uv.exe')
    if int.from_bytes(head[pe + 4:pe + 6], 'little') != X64:
        raise SystemExit(f'{uv} is not an x86-64 build: pass --uv with the x86_64 Windows uv.exe')


def uv_version(uv):
    """`uv --version` of a lone copy of the uv being bundled. That proves it's a working Windows uv that doesn't need
    files beside it, as package-manager shims do."""
    if sys.platform != 'win32':
        return 'uv (version not checked: built off Windows)'
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # antivirus may still hold the copy
        copy = Path(tmp) / 'uv.exe'
        shutil.copyfile(uv, copy)
        try:
            return subprocess.run([str(copy), '--version'], capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as e:
            raise SystemExit(f"{uv} doesn't run on its own ({e}); it may be a package manager's shim: "
                             f'pass --uv with the real uv.exe') from None


def check_lock(uv, archive):
    """The uv.lock in `archive` must match its pyproject.toml, or every user's first start would resolve the packages
    afresh, to versions nobody tested. Checked on an extracted copy, so it's the packaged files and not the working
    copy's, with the uv being bundled, which must read this lock (off Windows, with the local uv)."""
    runner = str(uv) if sys.platform == 'win32' else os.environ.get('UV') or shutil.which('uv')
    if not runner:
        raise SystemExit("can't check uv.lock: no uv to run here")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        r = subprocess.run([runner, 'lock', '--check'], cwd=Path(tmp) / FOLDER, capture_output=True, text=True,
                           encoding='utf-8')
    if r.returncode:
        raise SystemExit(f'`uv lock --check` failed (if uv.lock is out of date, run `uv lock` and commit it):\n'
                         f'{r.stderr.strip()}')


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
    partial = out.with_name(out.name + '.partial')  # a failed build never leaves a half-made zip under the real name
    partial.unlink(missing_ok=True)
    try:
        # git archive applies .gitattributes: export-ignore drops tests and tools, eol=crlf keeps the .bat runnable
        subprocess.run(['git', 'archive', '--format=zip', f'--prefix={FOLDER}/', '-o', str(partial), 'HEAD'],
                       cwd=ROOT, check=True)
        check_lock(uv, partial)
        with zipfile.ZipFile(partial, 'a', zipfile.ZIP_DEFLATED) as z:
            z.write(uv, f'{FOLDER}/uv/uv.exe')
            z.write(UV_LICENSE, f'{FOLDER}/uv/LICENSE-MIT.txt')
            z.writestr(f'{FOLDER}/VERSION.txt',
                       f'Clip Scout {version()} ({git("rev-parse", "--short", "HEAD")})\nbundled {bundled}\n')
            z.writestr(f'{FOLDER}/READ ME FIRST.txt', NOTES.format(version=version()).replace('\n', '\r\n'))
        digest = hashlib.sha256(partial.read_bytes()).hexdigest()
        os.replace(partial, out)
    finally:
        partial.unlink(missing_ok=True)
    out.with_name(out.name + '.sha256').write_bytes(f'{digest}  {out.name}\n'.encode())  # LF, for sha256sum -c
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
